#!/usr/bin/env python3
"""Host-only proxy configuration and launcher for Android Emulator."""
import argparse
import asyncio
import base64
import http.client
import ipaddress
import importlib.util
import json
import math
import os
import re
import shutil
import secrets
import time
from pathlib import Path
import sys
from urllib.parse import unquote, urlsplit
from zoneinfo import ZoneInfo

DEFAULT_FILE = Path(__file__).resolve().parent / '.local' / 'emulator-proxy'


def camera_module():
    # setup launches Python with -I: load this exact sibling, not PYTHONPATH.
    path = Path(__file__).resolve().with_name('native_video_camera.py')
    spec = importlib.util.spec_from_file_location('_native_video_camera', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def camera_preflight(avd, env, extra):
    return camera_module().preflight(avd, env, extra)


async def start_camera_check(avd, viewer=False, serial=None):
    root = Path(__file__).resolve().parent
    if viewer:
        arguments = [str(root / 'camera_probe/build_and_run.py'), '--avd', avd,
                     '--keep-preview', '--seconds', '22', '--output',
                     str(DEFAULT_FILE.parent / 'video-camera' / avd / 'direct')]
    else:
        arguments = [str(root / 'verify_camera_playback.py'), '--avd', avd,
                     '--wait-and-open', '--seconds', '20', '--output',
                     str(DEFAULT_FILE.parent / 'video-camera' / avd)]
    if serial:
        arguments += ['--serial', serial]
    return await asyncio.create_subprocess_exec(sys.executable, *arguments)


def record_camera_check(avd, env, viewer, exit_code):
    path = DEFAULT_FILE.parent / 'video-camera' / avd
    if viewer:
        path /= 'direct'
    try:
        return camera_module().record_verification(avd, env, path / 'report.json',
                                                   'camera2_reader' if viewer else 'stock', exit_code)
    except (OSError, ValueError) as exc:
        print(f'Camera verification metadata failed: {exc}', file=sys.stderr, flush=True)
        return False


async def launch_with_camera_check(command, env, proxy, diagnostic, avd, viewer=False):
    """Keep the relay alive, but never label an unchecked/frozen camera ready."""
    emulator_task = asyncio.create_task(launch(command, env, proxy, diagnostic))
    check = await start_camera_check(avd, viewer)
    check_task = asyncio.create_task(check.wait())
    try:
        await asyncio.wait({emulator_task, check_task}, return_when=asyncio.FIRST_COMPLETED)
        if not check_task.done():
            print('Emulator closed before camera verification completed; camera is NOT verified ready.', flush=True)
            record_camera_check(avd, env, viewer, 1)
            return (await emulator_task) or 1
        check_code = await check_task
        if record_camera_check(avd, env, viewer, check_code) is False:
            check_code = check_code or 1
        print(('Native front Camera2 pixel check passed. Camera Feed Preview is open.' if viewer else
               'Camera motion check passed (20 seconds). Review framing and full loop order.')
              if check_code == 0 else
              'Camera check FAILED. The phone is left open for diagnosis; it is NOT verified ready.',
              flush=True)
        launch_code = await emulator_task
        return launch_code or check_code
    finally:
        if check.returncode is None:
            try:
                check.terminate()
            except ProcessLookupError:
                pass
            await check.wait()
        if not check_task.done():
            check_task.cancel()
            await asyncio.gather(check_task, return_exceptions=True)


class RelayDiagnostics:
    """Append only fixed-schema metadata; never request/response text or payloads."""
    def __init__(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        os.fchmod(self.fd, 0o600)
        self.failed = False

    def __call__(self, event):
        try:
            os.write(self.fd, (json.dumps(event, separators=(',', ':')) + '\n').encode())
        except OSError:
            if not self.failed:
                print('Proxy diagnostic write failed; relay remains active.', file=sys.stderr)
                self.failed = True

    def close(self):
        os.close(self.fd)


def normalize(value):
    value = value.strip()
    if not value or any(c.isspace() for c in value):
        raise ValueError('Proxy must be a nonempty single line.')
    if '://' not in value and '@' not in value:
        parts = value.split(':', 3)
        if len(parts) == 4:
            host, port, user, password = parts
            if not user or not password or any(c in user + password for c in '@:/?#%'):
                raise ValueError('Use an HTTP URL for credentials containing special characters.')
            value = f'{user}:{password}@{host}:{port}'
    if '://' not in value:
        value = 'http://' + value
    try:
        parsed = urlsplit(value)
        valid = (parsed.scheme == 'http' and parsed.hostname and parsed.port
                 and 1 <= parsed.port <= 65535 and not parsed.path
                 and not parsed.query and not parsed.fragment
                 and (parsed.username is None or (parsed.username and parsed.password)))
    except ValueError:
        valid = False
    if not valid:
        raise ValueError('Expected host:port:user:password or http://[user:password@]host:port.')
    return value


def resolve(value=None, file=None, disabled=False):
    if disabled:
        return ''
    if value is not None:
        return normalize(value)
    path = Path(file) if file else DEFAULT_FILE
    if file or path.exists():
        return normalize(path.read_text())
    return ''


def locate(upstream):
    """Query the exit IP through this exact proxy, with no direct fallback."""
    if not upstream:
        raise ValueError('A proxy is required for location lookup.')
    proxy = urlsplit(normalize(upstream))
    headers = {}
    if proxy.username is not None:
        token = base64.b64encode(f'{unquote(proxy.username)}:{unquote(proxy.password)}'.encode()).decode()
        headers['Proxy-Authorization'] = 'Basic ' + token
    # HTTPSConnection establishes CONNECT over plain HTTP to the upstream, then
    # verifies TLS to the destination. It does not consult NO_PROXY or env proxies.
    connection = http.client.HTTPSConnection(proxy.hostname, proxy.port, timeout=30)
    try:
        connection.set_tunnel('ipwho.is', 443, headers=headers)
        connection.request('GET', '/', headers={'Accept': 'application/json'})
        response = connection.getresponse()
        if response.status != 200:
            raise ValueError('Geolocation service rejected the request.')
        data = json.loads(response.read(65536))
    finally:
        connection.close()
    if data.get('success') is not True:
        raise ValueError('Geolocation lookup did not succeed.')
    latitude, longitude = data['latitude'], data['longitude']
    if (type(latitude) not in (int, float) or type(longitude) not in (int, float)
            or not math.isfinite(latitude) or not math.isfinite(longitude)
            or not -90 <= latitude <= 90 or not -180 <= longitude <= 180):
        raise ValueError('Invalid geolocation coordinates.')
    timezone = data['timezone']['id']
    ZoneInfo(timezone)
    ip = str(ipaddress.ip_address(data['ip']))
    label = ', '.join(str(data.get(key) or '') for key in ('city', 'region', 'country'))
    label = ' '.join(label.split())
    return dict(ip=ip, latitude=latitude, longitude=longitude, timezone=timezone, label=label)


def graphics_sync_options(identity_args, video, extra):
    """Keep SurfaceTexture camera previews moving on the lab phones.

    The S25 boot fixture renames /dev/goldfish_sync, but the EGL library that
    apps load still opens the old name, so EGL native fences fail and every
    SurfaceTexture preview (stock Camera, CameraX) shows one frame forever.
    Not advertising host native sync makes guest EGL skip native fences; the
    boot scripts stay untouched. Verified on screen on 24 October 2026.
    """
    if any('GLAsyncSwap' in arg for arg in extra):  # caller chose explicitly
        return []
    return ['-feature', '-GLAsyncSwap'] if identity_args or video else []


def identifier_options(avd, env):
    avd_home = Path(env.get('ANDROID_AVD_HOME') or Path.home() / '.android/avd')
    avd_dir = avd_home / (avd + '.avd')
    registration = avd_home / (avd + '.ini')
    if registration.exists():
        for line in registration.read_text().splitlines():
            if line.startswith('path='):
                avd_dir = Path(line[5:])
                break
    manifest = avd_dir / 's25-identifiers.json'
    if not manifest.exists():
        return []
    identity = json.loads(manifest.read_text())
    if identity['avd'] != avd or not (Path(identity['private_emulator']) / 'qemu').is_dir():
        raise ValueError('Missing private emulator engine or mismatched identifiers')
    options = ['-qemu-top-dir', identity['private_emulator'], '-android-serialno', identity['serial']]
    if (avd_dir / 's25-system/data/misc/modem_simulator/iccprofile_for_sim0.xml').is_file():
        options += ['-ramdisk', str(avd_dir / 's25-system/ramdisk.img')]
    if 'network' in identity:
        # Older manifests contained dns=, which this emulator rejects. libslirp
        # computes the DNS address from net= without that unsupported option.
        radio_options = ','.join(p for p in identity['network']['radio_options'].split(',') if not p.startswith('dns='))
        wifi_options = ','.join(p for p in identity['network']['wifi_options'].split(',') if not p.startswith('dns='))
        options += ['-network-user-mode-options', radio_options,
                    '-wifi-user-mode-options', wifi_options,
                    '-qemu', '-global', 'virtio-net-device.mac=' + identity['cellular_mac']]
    return options


async def relay_connection(reader, writer, upstream, diagnostic=None):
    """Normalize HTTP/1.0 CONNECT success for netsim, which requires HTTP/1.1."""
    remote = None
    connection_id = secrets.token_hex(8)
    started = phase_started = time.monotonic()
    stage = 'client_headers'
    reason = 'closed'
    counts = {'client_to_upstream': 0, 'upstream_to_client': 0}

    def emit(event, **fields):
        if diagnostic:
            diagnostic(dict(event=event, connection_id=connection_id,
                            timestamp_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                            stage=stage, elapsed_ms=round((time.monotonic() - started) * 1000),
                            **fields))

    emit('connection_started')
    try:
        request = await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), 15)
        lines = request.split(b'\r\n')
        if not lines[0].startswith(b'CONNECT '):
            reason = 'unsupported_method'
            emit('request_rejected', reason=reason)
            writer.write(b'HTTP/1.1 405 Method Not Allowed\r\nContent-Length: 0\r\n\r\n')
            await writer.drain()
            return
        parsed = urlsplit(upstream)
        stage = 'upstream_tcp'
        phase_started = time.monotonic()
        remote_reader, remote = await asyncio.wait_for(asyncio.open_connection(parsed.hostname, parsed.port), 15)
        emit('upstream_connected', phase_ms=round((time.monotonic() - phase_started) * 1000))
        # Use only credentials from the private host config, never from clients.
        lines = [line for line in lines if not line.lower().startswith(b'proxy-authorization:')]
        if parsed.username is not None:
            from urllib.parse import unquote
            token = base64.b64encode(f'{unquote(parsed.username)}:{unquote(parsed.password)}'.encode())
            lines.insert(1, b'Proxy-Authorization: Basic ' + token)
        stage = 'upstream_connect'
        phase_started = time.monotonic()
        remote.write(b'\r\n'.join(lines))
        await remote.drain()
        response = await asyncio.wait_for(remote_reader.readuntil(b'\r\n\r\n'), 20)
        status = response.split(b'\r\n', 1)[0].split()
        # Never log reason phrases, headers, URLs, credentials or exception text.
        code = int(status[1]) if len(status) >= 2 and re.fullmatch(rb'[1-5][0-9]{2}', status[1]) else None
        emit('upstream_connect_response', status_code=code,
             phase_ms=round((time.monotonic() - phase_started) * 1000))
        if len(status) < 2 or status[1] != b'200':
            reason = 'upstream_rejected'
            writer.write(b'HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n')
            await writer.drain()
            return
        writer.write(b'HTTP/1.1 200 Connection Established\r\n\r\n')
        await writer.drain()
        stage = 'tunnel'
        phase_started = time.monotonic()
        emit('tunnel_established')

        async def copy(source, destination, direction):
            while data := await source.read(65536):
                destination.write(data)
                await destination.drain()
                counts[direction] += len(data)

        tasks = [asyncio.create_task(copy(reader, remote, 'client_to_upstream')),
                 asyncio.create_task(copy(remote_reader, writer, 'upstream_to_client'))]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                error = task.exception()
                if error:
                    raise error
            reason = 'peer_eof'
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
    except (OSError, asyncio.TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError) as error:
        # No direct-connection fallback when the upstream proxy is unavailable.
        reason = 'timeout' if isinstance(error, asyncio.TimeoutError) else 'connection_error'
        emit('connection_failed', reason=reason, error_type=type(error).__name__,
             phase_ms=round((time.monotonic() - phase_started) * 1000))
    except asyncio.CancelledError:
        reason = 'cancelled'
        raise
    finally:
        emit('connection_closed', reason=reason, **counts)
        writer.close()
        if remote:
            remote.close()


async def launch(command, env, upstream, diagnostic=None):
    if not upstream:
        os.execve(command[0], command, env)
    server = await asyncio.start_server(
        lambda r, w: relay_connection(r, w, upstream, diagnostic), '127.0.0.1', 0)
    port = server.sockets[0].getsockname()[1]
    async with server:
        proxy_args = ['-http-proxy', f'http://127.0.0.1:{port}']
        # Emulator flags must precede the QEMU passthrough delimiter.
        boundary = command.index('-qemu') if '-qemu' in command else len(command)
        command = command[:boundary] + proxy_args + command[boundary:]
        process = await asyncio.create_subprocess_exec(
            *command, env=env)
        try:
            return await process.wait()
        finally:
            if process.returncode is None:
                process.terminate()
                await process.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--proxy')
    parser.add_argument('--proxy-file')
    parser.add_argument('--diagnostics-file', help='Redacted JSONL relay log; defaults to .local/proxy-diagnostics.jsonl')
    parser.add_argument('--no-proxy', action='store_true')
    parser.add_argument('--resolve', action='store_true', help='Print URL for the setup script; contains credentials.')
    parser.add_argument('--location', action='store_true', help='Look up exit GPS coordinates and time zone through the proxy; print JSON.')
    parser.add_argument('--avd', help='Launch an existing AVD with the host proxy.')
    parser.add_argument('--check-video-camera', action='store_true',
                        help='Open the front camera after boot and reject frozen playback.')
    parser.add_argument('--camera-viewer', action='store_true',
                        help='Use our real Camera2 frame viewer/check instead of the stock Camera preview.')
    args, extra = parser.parse_known_args()
    try:
        proxy = resolve(args.proxy, args.proxy_file, args.no_proxy)
    except (ValueError, OSError):
        parser.exit(2, 'Invalid or unreadable host proxy configuration. Check the proxy file/format.\n')
    if args.resolve:
        if extra:
            parser.error('Unexpected arguments.')
        print(proxy)
        return
    if args.location:
        if extra:
            parser.error('Unexpected arguments.')
        try:
            print(json.dumps(locate(proxy)))
        except (OSError, ValueError, KeyError, TypeError, http.client.HTTPException):
            parser.exit(2, 'Proxy location lookup failed. Check proxy connectivity, credentials, and geolocation service availability.\n')
        return
    if not args.avd:
        parser.error('--avd is required to launch an emulator.')
    # Pass an explicit option: modern Wi-Fi backends may ignore http_proxy.
    env = dict(os.environ)
    env.pop('HTTP_PROXY', None)
    env.pop('http_proxy', None)
    # Emulator control services (netsim/gRPC) must talk directly over loopback.
    env['no_grpc_proxy'] = 'localhost,127.0.0.1,::1'
    sdk = Path(env.get('ANDROID_SDK_ROOT') or env.get('ANDROID_HOME') or Path.home() / 'Library/Android/sdk')
    # The private engine lives under the AVD folder, so the emulator cannot infer
    # the SDK from its own path; name it explicitly.
    env.setdefault('ANDROID_SDK_ROOT', str(sdk))
    env.setdefault('ANDROID_HOME', str(sdk))
    command = [str(sdk / 'emulator/emulator'), '-avd', args.avd,
               '-no-snapshot-load', '-no-snapshot-save']
    try:
        identity_args = identifier_options(args.avd, env)
    except (OSError, ValueError, KeyError, TypeError):
        parser.exit(2, 'Could not load this AVD’s identifiers and private emulator engine.\n')
    if identity_args and any(option in extra for option in ('-qemu-top-dir', '-android-serialno', '-ramdisk',
                                                           '-network-user-mode-options', '-wifi-user-mode-options', '-qemu')):
        parser.error('This AVD uses its reserved serial and private engine; conflicting overrides are not allowed.')
    qemu_args = []
    if '-qemu' in identity_args:
        boundary = identity_args.index('-qemu')
        qemu_args, identity_args = identity_args[boundary:], identity_args[:boundary]
    command += identity_args
    try:
        video = camera_preflight(args.avd, env, extra)
    except (OSError, ValueError) as exc:
        parser.exit(2, f'Native camera preflight failed: {exc}\n')
    command += graphics_sync_options(identity_args, video, extra)
    if args.check_video_camera and video is None:
        parser.error('--check-video-camera requires a configured videofile front camera.')
    if args.camera_viewer and not args.check_video_camera:
        parser.error('--camera-viewer requires --check-video-camera')
    use_viewer = args.camera_viewer
    if args.check_video_camera and not use_viewer:
        try:
            use_viewer = camera_module().viewer_preferred(args.avd, env)
        except (OSError, ValueError) as exc:
            parser.exit(2, f'Could not read the saved camera preview preference: {exc}\n')
    if args.check_video_camera:
        try:
            existing_serial = camera_module().running_serial(args.avd)
        except (OSError, ValueError) as exc:
            parser.exit(2, f'Could not inspect running camera device: {exc}\n')
        if existing_serial:
            if extra or args.proxy is not None or args.proxy_file is not None or args.no_proxy:
                parser.error('This AVD is already running; close it first to apply extra launch arguments.')
            print(f'Reusing {args.avd} on {existing_serial}; its existing proxy/launch settings are unchanged.', flush=True)
            async def check_existing():
                process = await start_camera_check(args.avd, use_viewer, existing_serial)
                result = await process.wait()
                if record_camera_check(args.avd, env, use_viewer, result) is False:
                    result = result or 1
                return result
            return asyncio.run(check_existing())
    if '-ramdisk' in identity_args:
        ramdisk = Path(identity_args[identity_args.index('-ramdisk') + 1])
        # rootAVD patches AVD/ramdisk.img. Refresh the private launch copy on
        # each cold start so the modem source location and patched image agree.
        try:
            shutil.copy2(ramdisk.parent.parent / 'ramdisk.img', ramdisk)
        except OSError:
            parser.exit(2, 'Could not stage the private launch ramdisk.\n')
    if '-http-proxy' in extra:
        parser.error('Use --proxy or --proxy-file instead of -http-proxy.')
    print('Launching with host proxy enabled.' if proxy else 'Launching without a host proxy.', flush=True)
    diagnostic = None
    try:
        if proxy:
            path = Path(args.diagnostics_file) if args.diagnostics_file else DEFAULT_FILE.parent / 'proxy-diagnostics.jsonl'
            diagnostic = RelayDiagnostics(path)
            print(f'Redacted proxy diagnostics: {path}', flush=True)
        if args.check_video_camera:
            return asyncio.run(launch_with_camera_check(command + extra + qemu_args, env,
                                                       proxy, diagnostic, args.avd, use_viewer))
        return asyncio.run(launch(command + extra + qemu_args, env, proxy, diagnostic))
    finally:
        if diagnostic:
            diagnostic.close()


if __name__ == '__main__':
    sys.exit(main())
