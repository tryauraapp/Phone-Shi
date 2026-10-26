import os
import asyncio
from pathlib import Path
import subprocess
import tempfile
import json
import io
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import emulator_proxy as proxy


class ProxyTests(unittest.TestCase):
    def test_adb_failure_prevents_emulator_launch(self):
        with patch('sys.argv', ['emulator_proxy.py', '--avd', 'Test', '--no-proxy']), \
             patch.object(proxy, 'identifier_options', return_value=[]), \
             patch.object(proxy, 'ensure_adb_server', side_effect=subprocess.TimeoutExpired('adb', 20)), \
             patch.object(proxy, 'launch', new_callable=AsyncMock) as launch:
            with self.assertRaises(SystemExit) as result:
                proxy.main()
            self.assertEqual(result.exception.code, 2)
            launch.assert_not_called()

    def test_adb_ready_before_emulator_launch(self):
        events = []
        async def launch(*args):
            events.append('emulator')
            return 0
        with patch('sys.argv', ['emulator_proxy.py', '--avd', 'Test', '--no-proxy']), \
             patch.object(proxy, 'identifier_options', return_value=[]), \
             patch.object(proxy, 'ensure_adb_server', side_effect=lambda *args: events.append('adb')), \
             patch.object(proxy, 'launch', side_effect=launch):
            proxy.main()
        self.assertEqual(events, ['adb', 'emulator'])

    def test_adb_uses_selected_sdk_and_environment(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(proxy.subprocess, 'run') as run:
            env = {'ANDROID_USER_HOME': directory, 'ANDROID_ADB_SERVER_PORT': '5038'}
            proxy.ensure_adb_server(Path('/sdk'), env)
            run.assert_called_once_with(['/sdk/platform-tools/adb', 'start-server'],
                                        env=env, check=True, timeout=20)

    def test_launch_refreshes_private_ramdisk_after_root_patch(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            avd = home / 'Test.avd'
            modem = avd / 's25-system/data/misc/modem_simulator'
            modem.mkdir(parents=True)
            (modem / 'iccprofile_for_sim0.xml').write_text('<sim/>')
            private = avd / 'engine'
            (private / 'qemu').mkdir(parents=True)
            (avd / 's25-identifiers.json').write_text(json.dumps(dict(
                avd='Test', private_emulator=str(private), serial='S25TEST')))
            with patch.dict(os.environ, {'ANDROID_AVD_HOME': directory}), \
                 patch('sys.argv', ['emulator_proxy.py', '--avd', 'Test', '--no-proxy']), \
                 patch.object(proxy, 'ensure_adb_server'), \
                 patch.object(proxy, 'launch', new_callable=AsyncMock, return_value=0) as launch:
                for contents in (b'stock ramdisk', b'rootAVD patched ramdisk'):
                    (avd / 'ramdisk.img').write_bytes(contents)
                    proxy.main()
                    self.assertEqual((avd / 's25-system/ramdisk.img').read_bytes(), contents)
                    arguments = launch.call_args.args[0]
                    self.assertEqual(arguments[arguments.index('-ramdisk') + 1], str(avd / 's25-system/ramdisk.img'))

    def test_lab_phones_and_video_cameras_disable_host_native_sync(self):
        flag = ['-feature', '-GLAsyncSwap']
        self.assertEqual(proxy.graphics_sync_options(['-android-serialno', 'S25'], None, []), flag)
        self.assertEqual(proxy.graphics_sync_options([], Path('/v/front.webm'), []), flag)
        self.assertEqual(proxy.graphics_sync_options([], None, []), [])
        self.assertEqual(proxy.graphics_sync_options(['-android-serialno', 'S25'], None, ['-feature', 'GLAsyncSwap']), [])

    def test_location_uses_authenticated_proxy_tunnel_and_validates_result(self):
        data = dict(success=True, ip='192.0.2.8', latitude=42.3314,
                    longitude=-83.0457, timezone={'id': 'America/Detroit'},
                    city='Detroit', region='Michigan', country='United States')
        with patch.object(proxy.http.client, 'HTTPSConnection') as connection:
            response = connection.return_value.getresponse.return_value
            response.status = 200
            response.read.return_value = json.dumps(data).encode()
            result = proxy.locate('http://user:password@proxy.example:8080')
            connection.assert_called_once_with('proxy.example', 8080, timeout=30)
            connection.return_value.set_tunnel.assert_called_once_with(
                'ipwho.is', 443, headers={'Proxy-Authorization': 'Basic dXNlcjpwYXNzd29yZA=='})
            self.assertEqual(result['timezone'], 'America/Detroit')
            self.assertEqual(result['latitude'], data['latitude'])
            self.assertNotIn('password', json.dumps(result))
            for changes in ({'success': False}, {'latitude': 91}, {'longitude': float('nan')},
                            {'timezone': {'id': 'invalid/zone'}}, {'ip': 'invalid'}):
                response.read.return_value = json.dumps(dict(data, **changes)).encode()
                with self.assertRaises((ValueError, KeyError)):
                    proxy.locate('http://proxy.example:8080')
            connection.return_value.close.assert_called()

    def test_formats_and_validation(self):
        expected = 'http://user:password@192.0.2.1:8080'
        self.assertEqual(proxy.normalize('192.0.2.1:8080:user:password'), expected)
        self.assertEqual(proxy.normalize(expected), expected)
        for value in ('', 'socks5://host:80', 'http://host:0', 'http://host:99999',
                      'http://host:80/path', 'host:8080:user:', 'a\nb:80'):
            with self.assertRaises(ValueError, msg=value):
                proxy.normalize(value)

    def test_explicit_missing_file_does_not_fall_back_to_direct(self):
        with self.assertRaises(OSError):
            proxy.resolve(file='/nonexistent/proxy-test')
        self.assertEqual(proxy.resolve(file='/nonexistent/proxy-test', disabled=True), '')

    def test_phone_proxy_path_is_scoped_to_one_avd(self):
        self.assertEqual(proxy.phone_proxy_file('Phone_A', '/private/backups'),
                         Path('/private/backups/Phone_A/setup/nodemaven-proxy'))

    def test_launch_passes_explicit_host_proxy_without_proxying_control_services(self):
        with patch('sys.argv', ['emulator_proxy.py', '--avd', 'Test', '--proxy',
                                '192.0.2.1:8080:user:password']), patch.object(proxy, 'ensure_adb_server'), patch.object(proxy, 'launch', new_callable=AsyncMock, return_value=0) as launch:
            proxy.main()
        command, env, upstream, diagnostic = launch.call_args.args
        self.assertEqual(upstream, 'http://user:password@192.0.2.1:8080')
        self.assertNotIn('password', ' '.join(command))
        self.assertNotIn('http_proxy', env)
        self.assertNotIn('HTTP_PROXY', env)
        self.assertEqual(env['no_grpc_proxy'], 'localhost,127.0.0.1,::1')
        self.assertIn('Test', command)
        self.assertIsInstance(diagnostic, proxy.RelayDiagnostics)

    def test_diagnostic_file_is_private_jsonl(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'relay.jsonl'
            log = proxy.RelayDiagnostics(path)
            log({'event': 'connection_started', 'connection_id': 'test'})
            log.close()
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads(path.read_text())['event'], 'connection_started')

    def test_diagnostic_disk_failure_does_not_interrupt_relay(self):
        with tempfile.TemporaryDirectory() as folder:
            log = proxy.RelayDiagnostics(Path(folder) / 'relay.jsonl')
            output = io.StringIO()
            try:
                with patch.object(proxy.os, 'write', side_effect=OSError('sensitive-path')), \
                        patch.object(proxy.sys, 'stderr', output):
                    log({'event': 'test'})
                    log({'event': 'test'})
            finally:
                log.close()
            self.assertEqual(output.getvalue().count('write failed'), 1)
            self.assertNotIn('sensitive-path', output.getvalue())

    def test_setup_preview_redacts_credentials_and_can_disable_default(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'proxy'
            path.write_text('192.0.2.1:8080:user:password')
            command = ['bash', str(root / 'setup_galaxy_s25_avd.sh'), '--dry-run', '--yes',
                       '--proxy-file', str(path)]
            env = dict(os.environ, HOME=directory, ANDROID_AVD_HOME=directory + '/avds')
            result = subprocess.run(command, env=env, text=True, capture_output=True, check=True)
            self.assertIn('Host proxy: enabled', result.stdout)
            self.assertNotIn('password', result.stdout + result.stderr)
            result = subprocess.run(command + ['--no-proxy'], env=env, text=True, capture_output=True, check=True)
            self.assertIn('Host proxy: disabled', result.stdout)


class RelayTests(unittest.IsolatedAsyncioTestCase):
    async def test_upstream_rejection_is_logged_without_headers_or_secrets(self):
        reader = AsyncMock()
        reader.readuntil.return_value = b'CONNECT example.com:443 HTTP/1.1\r\nProxy-Authorization: private-client-secret\r\n\r\n'
        writer = MagicMock(drain=AsyncMock())
        remote_reader = AsyncMock()
        remote_reader.readuntil.return_value = b'HTTP/1.1 407 private-reason-token\r\nSecret: response-secret\r\n\r\n'
        remote = MagicMock(drain=AsyncMock())
        events = []
        with patch.object(proxy.asyncio, 'open_connection', new_callable=AsyncMock,
                          return_value=(remote_reader, remote)):
            await proxy.relay_connection(reader, writer, 'http://user:upstream-secret@host:80', events.append)
        response = next(e for e in events if e['event'] == 'upstream_connect_response')
        self.assertEqual(response['status_code'], 407)
        self.assertEqual(events[-1]['reason'], 'upstream_rejected')
        encoded = json.dumps(events)
        for secret in ('private-client-secret', 'private-reason-token', 'response-secret',
                       'upstream-secret', 'example.com'):
            self.assertNotIn(secret, encoded)
        self.assertIn(b'502 Bad Gateway', writer.write.call_args.args[0])

    async def test_connection_timeout_has_stage_and_no_exception_message(self):
        reader = AsyncMock()
        reader.readuntil.return_value = b'CONNECT example.com:443 HTTP/1.1\r\n\r\n'
        writer = MagicMock(drain=AsyncMock())
        events = []
        with patch.object(proxy.asyncio, 'open_connection', new_callable=AsyncMock,
                          side_effect=TimeoutError('secret-token-url')):
            await proxy.relay_connection(reader, writer, 'http://user:secret@host:80', events.append)
        failed = next(e for e in events if e['event'] == 'connection_failed')
        self.assertEqual(failed['stage'], 'upstream_tcp')
        self.assertEqual(failed['reason'], 'timeout')
        self.assertIn('phase_ms', failed)
        self.assertNotIn('secret', json.dumps(events))

    async def test_connect_response_timeout_is_distinguished_from_tcp_timeout(self):
        reader = AsyncMock()
        reader.readuntil.return_value = b'CONNECT example.com:443 HTTP/1.1\r\n\r\n'
        writer = MagicMock(drain=AsyncMock())
        remote_reader = AsyncMock()
        remote_reader.readuntil.side_effect = TimeoutError('private-data')
        remote = MagicMock(drain=AsyncMock())
        events = []
        with patch.object(proxy.asyncio, 'open_connection', new_callable=AsyncMock,
                          return_value=(remote_reader, remote)):
            await proxy.relay_connection(reader, writer, 'http://host:80', events.append)
        failed = next(e for e in events if e['event'] == 'connection_failed')
        self.assertEqual(failed['stage'], 'upstream_connect')
        self.assertNotIn('private-data', json.dumps(events))

    async def test_proxy_option_precedes_qemu_passthrough(self):
        server = MagicMock()
        server.sockets[0].getsockname.return_value = ('127.0.0.1', 23456)
        process = MagicMock(returncode=0)
        process.wait = AsyncMock(return_value=0)
        command = ['/sdk/emulator', '-avd', 'Test', '-qemu', '-global', 'virtio-net-device.mac=06:11:22:33:44:55']
        with patch.object(proxy.asyncio, 'start_server', new_callable=AsyncMock, return_value=server), \
             patch.object(proxy.asyncio, 'create_subprocess_exec', new_callable=AsyncMock, return_value=process) as launch:
            self.assertEqual(await proxy.launch(command, {}, 'http://host:8080'), 0)
        arguments = launch.call_args.args
        self.assertLess(arguments.index('-http-proxy'), arguments.index('-qemu'))
        self.assertEqual(arguments[-2:], ('-global', 'virtio-net-device.mac=06:11:22:33:44:55'))

    async def test_http10_success_normalized_and_tunnel_preserves_bytes(self):
        observed = []
        events = []

        async def upstream(reader, writer):
            observed.append(await reader.readuntil(b'\r\n\r\n'))
            writer.write(b'HTTP/1.0 200 OK\r\n\r\n')
            await writer.drain()
            data = await reader.readexactly(4)
            writer.write(data)
            await writer.drain()
            writer.close()

        remote = await asyncio.start_server(upstream, '127.0.0.1', 0)
        remote_port = remote.sockets[0].getsockname()[1]
        relay = await asyncio.start_server(lambda r, w: proxy.relay_connection(
            r, w, f'http://user:password@127.0.0.1:{remote_port}', events.append), '127.0.0.1', 0)
        async with remote, relay:
            reader, writer = await asyncio.open_connection('127.0.0.1', relay.sockets[0].getsockname()[1])
            writer.write(b'CONNECT example.com:443 HTTP/1.1\r\nHost: example.com:443\r\n\r\n')
            await writer.drain()
            response = await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), 2)
            self.assertTrue(response.startswith(b'HTTP/1.1 200 '))
            writer.write(b'\x00\xffOK')
            await writer.drain()
            self.assertEqual(await asyncio.wait_for(reader.readexactly(4), 2), b'\x00\xffOK')
            writer.close()
            await writer.wait_closed()
        self.assertIn(b'Proxy-Authorization: Basic dXNlcjpwYXNzd29yZA==', observed[0])
        self.assertTrue(any(e['event'] == 'tunnel_established' for e in events))
        self.assertNotIn('password', json.dumps(events))
        self.assertNotIn('example.com', json.dumps(events))
