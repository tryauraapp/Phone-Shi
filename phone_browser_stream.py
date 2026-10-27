"""Shared scrcpy H.264 -> fragmented MP4 display streams, without transcoding."""
from fractions import Fraction
import atexit
import io
import os
from pathlib import Path
import queue
import re
import shutil
import socket
import struct
import subprocess
import threading
import time


def adb(serial, *args):
    return subprocess.run(["adb", "-s", serial, *args], capture_output=True,
                          timeout=10, check=True).stdout


class AwakeLeases:
    def __init__(self):
        self.lock = threading.Lock()
        self.phones = {}
        threading.Thread(target=self._watch, daemon=True).start()
        atexit.register(self.close)

    def touch(self, serial):
        with self.lock:
            if serial not in self.phones:
                previous = adb(serial, "shell", "settings", "get", "system",
                               "screen_off_timeout").decode().strip()
                adb(serial, "shell", "settings", "put", "system",
                    "screen_off_timeout", "2147483647")
                self.phones[serial] = [previous, time.monotonic() + 45]
                adb(serial, "shell", "input", "keyevent", "KEYCODE_WAKEUP")
            else:
                self.phones[serial][1] = time.monotonic() + 45

    def _restore(self, serial):
        previous, _ = self.phones.pop(serial)
        try:
            if previous == "null":
                adb(serial, "shell", "settings", "delete", "system", "screen_off_timeout")
            else:
                adb(serial, "shell", "settings", "put", "system", "screen_off_timeout", previous)
        except (OSError, subprocess.SubprocessError):
            pass

    def _watch(self):
        while True:
            time.sleep(5)
            with self.lock:
                for serial, (_, expires) in list(self.phones.items()):
                    if expires < time.monotonic():
                        self._restore(serial)

    def close(self):
        with self.lock:
            for serial in list(self.phones):
                self._restore(serial)


def server_binary():
    candidates = [os.environ.get("SCRCPY_SERVER_PATH", ""),
                  str(Path(__file__).parent / ".local/browser-stream/scrcpy-server"),
                  "/opt/homebrew/share/scrcpy/scrcpy-server",
                  "/usr/local/share/scrcpy/scrcpy-server",
                  "/usr/share/scrcpy/scrcpy-server"]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    raise RuntimeError("Install scrcpy to enable live video streaming")


def read_exact(sock, size):
    result = bytearray()
    while len(result) < size:
        chunk = sock.recv(size - len(result))
        if not chunk:
            raise EOFError("Phone video stream ended")
        result.extend(chunk)
    return bytes(result)


class Output(io.RawIOBase):
    def __init__(self):
        self.data = bytearray()

    def writable(self):
        return True

    def write(self, data):
        self.data.extend(data)
        return len(data)

    def take(self):
        result = bytes(self.data)
        self.data.clear()
        return result


class PhoneStream:
    def __init__(self, serial):
        self.serial = serial
        self.lock = threading.Lock()
        self.listeners = set()
        self.init = b""
        self.gop = []
        self.error = None
        self.width = self.height = 0
        self.frames = 0
        self.last_frame = 0
        self.last_used = time.monotonic()
        self.done = threading.Event()
        self.stopping = threading.Event()
        self.process = None
        self.socket = None
        threading.Thread(target=self._run, daemon=True).start()

    def stop(self):
        self.stopping.set()
        if self.socket:
            try:
                self.socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        if self.process and self.process.poll() is None:
            self.process.terminate()

    def subscribe(self):
        listener = queue.Queue(maxsize=180)
        with self.lock:
            if self.error:
                raise RuntimeError(self.error)
            if self.init:
                listener.put_nowait(self.init)
                for fragment in self.gop:
                    listener.put_nowait(fragment)
            self.listeners.add(listener)
            self.last_used = time.monotonic()
        return listener

    def unsubscribe(self, listener):
        with self.lock:
            self.listeners.discard(listener)
            self.last_used = time.monotonic()

    def publish(self, data, *, keyframe=False, initial=False):
        with self.lock:
            if initial:
                self.init = data
            else:
                if keyframe:
                    self.gop = []
                self.gop.append(data)
                # Keep memory bounded even if an encoder ignores the keyframe interval.
                if len(self.gop) > 150:
                    raise RuntimeError("Encoder did not produce regular keyframes")
            for listener in list(self.listeners):
                try:
                    listener.put_nowait(data)
                except queue.Full:
                    # A slow browser must reconnect rather than build seconds of delay.
                    self.listeners.discard(listener)
                    while not listener.empty():
                        listener.get_nowait()
                    listener.put_nowait(None)

    def _run(self):
        process = sock = container = None
        port = None
        log = io.BytesIO()
        try:
            import av
            binary = server_binary()
            version_file = Path(binary).with_name("scrcpy-version")
            version = os.environ.get("SCRCPY_SERVER_VERSION", "")
            if not version and version_file.is_file():
                version = version_file.read_text().strip()
            if not version:
                executable = shutil.which("scrcpy")
                if not executable:
                    raise RuntimeError("scrcpy executable or server version is missing")
                version_text = subprocess.run([executable, "--version"], capture_output=True,
                                              text=True, timeout=8, check=True).stdout
                version = re.search(r"scrcpy ([\w.]+)", version_text).group(1)
            if not re.fullmatch(r"\d+(?:\.\d+)+", version):
                raise RuntimeError("Invalid scrcpy server version")
            modern = int(version.split(".")[0]) >= 5
            scid = f"{int.from_bytes(os.urandom(4), 'big') & 0x7fffffff:08x}"
            remote = f"/data/local/tmp/phone-shi-scrcpy-{version}.jar"
            adb(self.serial, "push", binary, remote)
            port = int(adb(self.serial, "forward", "tcp:0", f"localabstract:scrcpy_{scid}").strip())
            command = ["adb", "-s", self.serial, "shell", f"CLASSPATH={remote}",
                       "app_process", "/", "com.genymobile.scrcpy.Server", version,
                       f"scid={scid}", "tunnel_forward=true", "audio=false", "control=false",
                       "send_device_meta=false", "send_dummy_byte=false",
                       "max_size=1280", "max_fps=30", "video_bit_rate=3000000",
                       "video_codec_options=i-frame-interval=1", "cleanup=true"]
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            self.process = process
            def drain():
                for line in process.stdout:
                    if log.tell() < 16000:
                        log.write(line)
            threading.Thread(target=drain, daemon=True).start()
            deadline = time.monotonic() + 12
            while True:
                try:
                    sock = socket.create_connection(("127.0.0.1", port), timeout=1)
                    # ADB can accept a connection before the abstract socket is ready.
                    sock.settimeout(2)
                    metadata = read_exact(sock, 4)
                    break
                except (OSError, EOFError):
                    if sock:
                        sock.close()
                    if time.monotonic() > deadline or process.poll() is not None:
                        raise RuntimeError("scrcpy startup failed: " + log.getvalue().decode(errors="replace"))
                    time.sleep(.1)
            codec = struct.unpack(">I", metadata)[0]
            if codec != 0x68323634:
                raise RuntimeError("Phone did not provide H.264 video")
            if modern:
                session, self.width, self.height = struct.unpack(">III", read_exact(sock, 12))
                if not session & (1 << 31):
                    raise RuntimeError("Missing video session metadata")
            else:
                self.width, self.height = struct.unpack(">II", read_exact(sock, 8))
            sock.settimeout(3)
            self.socket = sock
            output = Output()
            container = av.open(output, "w", format="mp4", options={
                "movflags": "empty_moov+default_base_moof+frag_every_frame",
                "flush_packets": "1"})
            stream = None
            config = b""
            pending_keyframe = False
            origin = None
            while True:
                if self.stopping.is_set():
                    break
                if not self.listeners and time.monotonic() - self.last_used > 15:
                    break
                try:
                    header = read_exact(sock, 12)
                except socket.timeout:
                    continue
                pts_flags, size = struct.unpack(">QI", header)
                if modern and pts_flags & (1 << 63):
                    raise RuntimeError("Phone display changed orientation; reconnecting video")
                if size > 16 * 1024 * 1024:
                    raise RuntimeError("Invalid video packet")
                payload = read_exact(sock, size)
                if pts_flags & (1 << (62 if modern else 63)):
                    config = payload
                    stream = container.add_mux_stream("h264", rate=30,
                        width=self.width, height=self.height,
                        time_base=Fraction(1, 1000000))
                    continue
                keyframe = bool(pts_flags & (1 << (61 if modern else 62)))
                pts = pts_flags & ((1 << (61 if modern else 62)) - 1)
                if origin is None:
                    origin = pts
                packet = av.Packet(config + payload)
                config = b""
                packet.pts = packet.dts = pts - origin
                packet.time_base = Fraction(1, 1000000)
                packet.duration = 33333
                packet.is_keyframe = keyframe
                packet.stream = stream
                container.mux(packet)
                fragment = output.take()
                if not self.init and fragment:
                    marker = fragment.find(b"moof")
                    split = marker - 4 if marker >= 4 else len(fragment)
                    self.publish(fragment[:split], initial=True)
                    fragment = fragment[split:]
                if fragment:
                    self.publish(fragment, keyframe=pending_keyframe)
                pending_keyframe = keyframe
                self.frames += 1
                self.last_frame = time.monotonic()
        except Exception as exc:
            self.error = str(exc)
        finally:
            if sock:
                sock.close()
            if process:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
            if container:
                try:
                    container.close()
                except Exception:
                    pass
            if port:
                try:
                    adb(self.serial, "forward", "--remove", f"tcp:{port}")
                except Exception:
                    pass
            with self.lock:
                for listener in self.listeners:
                    try:
                        listener.put_nowait(None)
                    except queue.Full:
                        pass
            self.done.set()


class StreamPool:
    def __init__(self):
        self.lock = threading.Lock()
        self.streams = {}
        atexit.register(self.close)

    def close(self):
        with self.lock:
            for stream in self.streams.values():
                stream.stop()

    def get(self, serial):
        with self.lock:
            stream = self.streams.get(serial)
            if not stream or stream.done.is_set():
                stream = self.streams[serial] = PhoneStream(serial)
            return stream
