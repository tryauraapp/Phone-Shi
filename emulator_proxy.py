#!/usr/bin/env python3
"""Host-only proxy configuration and launcher for Android Emulator."""
import argparse
import asyncio
import base64
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit

DEFAULT_FILE = Path(__file__).resolve().parent / '.local' / 'emulator-proxy'


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


async def relay_connection(reader, writer, upstream):
    """Normalize HTTP/1.0 CONNECT success for netsim, which requires HTTP/1.1."""
    remote = None
    try:
        request = await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), 15)
        lines = request.split(b'\r\n')
        if not lines[0].startswith(b'CONNECT '):
            writer.write(b'HTTP/1.1 405 Method Not Allowed\r\nContent-Length: 0\r\n\r\n')
            await writer.drain()
            return
        parsed = urlsplit(upstream)
        remote_reader, remote = await asyncio.wait_for(asyncio.open_connection(parsed.hostname, parsed.port), 15)
        # Use only credentials from the private host config, never from clients.
        lines = [line for line in lines if not line.lower().startswith(b'proxy-authorization:')]
        if parsed.username is not None:
            from urllib.parse import unquote
            token = base64.b64encode(f'{unquote(parsed.username)}:{unquote(parsed.password)}'.encode())
            lines.insert(1, b'Proxy-Authorization: Basic ' + token)
        remote.write(b'\r\n'.join(lines))
        await remote.drain()
        response = await asyncio.wait_for(remote_reader.readuntil(b'\r\n\r\n'), 20)
        status = response.split(b'\r\n', 1)[0].split()
        if len(status) < 2 or status[1] != b'200':
            writer.write(b'HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n')
            await writer.drain()
            return
        writer.write(b'HTTP/1.1 200 Connection Established\r\n\r\n')
        await writer.drain()

        async def copy(source, destination):
            while data := await source.read(65536):
                destination.write(data)
                await destination.drain()

        tasks = [asyncio.create_task(copy(reader, remote)), asyncio.create_task(copy(remote_reader, writer))]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
    except (OSError, asyncio.TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
        # No direct-connection fallback when the upstream proxy is unavailable.
        pass
    finally:
        writer.close()
        if remote:
            remote.close()


async def launch(command, env, upstream):
    if not upstream:
        os.execve(command[0], command, env)
    server = await asyncio.start_server(
        lambda r, w: relay_connection(r, w, upstream), '127.0.0.1', 0)
    port = server.sockets[0].getsockname()[1]
    async with server:
        process = await asyncio.create_subprocess_exec(
            *command, '-http-proxy', f'http://127.0.0.1:{port}', env=env)
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
    parser.add_argument('--no-proxy', action='store_true')
    parser.add_argument('--resolve', action='store_true', help='Print URL for the setup script; contains credentials.')
    parser.add_argument('--avd', help='Launch an existing AVD with the host proxy.')
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
    if not args.avd:
        parser.error('--avd is required to launch an emulator.')
    # Pass an explicit option: modern Wi-Fi backends may ignore http_proxy.
    env = dict(os.environ)
    env.pop('HTTP_PROXY', None)
    env.pop('http_proxy', None)
    # Emulator control services (netsim/gRPC) must talk directly over loopback.
    env['no_grpc_proxy'] = 'localhost,127.0.0.1,::1'
    sdk = Path(env.get('ANDROID_SDK_ROOT') or env.get('ANDROID_HOME') or Path.home() / 'Library/Android/sdk')
    command = [str(sdk / 'emulator/emulator'), '-avd', args.avd,
               '-no-snapshot-load', '-no-snapshot-save']
    if '-http-proxy' in extra:
        parser.error('Use --proxy or --proxy-file instead of -http-proxy.')
    print('Launching with host proxy enabled.' if proxy else 'Launching without a host proxy.', flush=True)
    return asyncio.run(launch(command + extra, env, proxy))


if __name__ == '__main__':
    sys.exit(main())
