import os
import asyncio
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

import emulator_proxy as proxy


class ProxyTests(unittest.TestCase):
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

    def test_launch_passes_explicit_host_proxy_without_proxying_control_services(self):
        with patch('sys.argv', ['emulator_proxy.py', '--avd', 'Test', '--proxy',
                                '192.0.2.1:8080:user:password']), patch.object(proxy, 'launch', new_callable=AsyncMock, return_value=0) as launch:
            proxy.main()
        command, env, upstream = launch.call_args.args
        self.assertEqual(upstream, 'http://user:password@192.0.2.1:8080')
        self.assertNotIn('password', ' '.join(command))
        self.assertNotIn('http_proxy', env)
        self.assertNotIn('HTTP_PROXY', env)
        self.assertEqual(env['no_grpc_proxy'], 'localhost,127.0.0.1,::1')
        self.assertIn('Test', command)

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
    async def test_http10_success_normalized_and_tunnel_preserves_bytes(self):
        observed = []

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
            r, w, f'http://user:password@127.0.0.1:{remote_port}'), '127.0.0.1', 0)
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
