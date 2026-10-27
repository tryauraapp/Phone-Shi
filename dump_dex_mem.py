import subprocess
import sys
import struct

def run_su(cmd):
    p = subprocess.Popen(['adb', 'shell', 'su', '0', 'sh'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = p.communicate(cmd.encode())
    return stdout

pid = run_su('pidof com.tinder').decode().strip().split()[0]
print(f"Scanning PID {pid}...")

maps_data = run_su(f'cat /proc/{pid}/maps').decode('utf-8', errors='ignore')
anon_maps = []
for line in maps_data.splitlines():
    parts = line.split()
    if len(parts) >= 5:
        addr = parts[0]
        perms = parts[1]
        path = parts[5] if len(parts) >= 6 else ''
        if 'r' in perms and ('anon' in path or path == '' or 'memfd' in path or 'dex' in path or 'apk' in path):
            start, end = [int(x, 16) for x in addr.split('-')]
            anon_maps.append((start, end, perms, path))

print(f"Found {len(anon_maps)} readable candidate memory mappings")

# Write a script on device to scan and dump dex files directly
dev_script = f"""
cat << 'EOF' > /data/local/tmp/dump_dex.py
import sys, os

pid = "{pid}"
with open(f"/proc/{{pid}}/maps") as f:
    maps = f.readlines()

os.makedirs("/data/local/tmp/dex_dumps", exist_ok=True)

with open(f"/proc/{{pid}}/mem", "rb", 0) as mem:
    idx = 0
    for line in maps:
        parts = line.split()
        if len(parts) < 5 or 'r' not in parts[1]:
            continue
        start, end = [int(x, 16) for x in parts[0].split('-')]
        size = end - start
        if size > 50 * 1024 * 1024 or size < 1024:
            continue
        try:
            mem.seek(start)
            data = mem.read(size)
            pos = 0
            while True:
                p = data.find(b"dex\\n", pos)
                if p == -1:
                    break
                # Check dex header
                if p + 36 <= len(data):
                    dex_size = int.from_bytes(data[p+32:p+36], 'little')
                    if 1024 < dex_size <= 20 * 1024 * 1024 and p + dex_size <= len(data):
                        dex_data = data[p:p+dex_size]
                        if b"FaceTec" in dex_data or b"lzQ" in dex_data or b"mbH" in dex_data:
                            print(f"Found FaceTec DEX in map {{hex(start)}} at offset {{hex(p)}}, size {{dex_size}}")
                            with open(f"/data/local/tmp/dex_dumps/dex_{{idx}}.dex", "wb") as out:
                                out.write(dex_data)
                            idx += 1
                pos = p + 4
        except Exception as e:
            pass
EOF
python3 /data/local/tmp/dump_dex.py 2>/dev/null || true
"""
out = run_su(dev_script)
print("Device output:", out.decode('utf-8', errors='ignore'))
