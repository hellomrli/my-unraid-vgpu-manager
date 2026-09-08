#!/usr/bin/env python3
"""Build/check the exact source payload referenced by the Unraid .plg file."""
import argparse
from datetime import datetime, timezone
import hashlib
import io
from pathlib import Path
import re
import tarfile

ROOT = Path(__file__).resolve().parents[1]

def payload(version):
    timestamp = int(datetime.strptime(version[:10], '%Y.%m.%d').replace(tzinfo=timezone.utc).timestamp())
    buffer = io.BytesIO()
    source = ROOT / 'source'
    with tarfile.open(fileobj=buffer, mode='w:xz', format=tarfile.GNU_FORMAT, preset=9) as archive:
        for path in [source, *sorted(source.rglob('*'))]:
            name = '.' if path == source else './'+path.relative_to(source).as_posix()
            info = archive.gettarinfo(str(path), arcname=name)
            info.uid = info.gid = 0
            info.uname = info.gname = 'root'
            info.mtime = timestamp
            # Git tracks executability, while other permission bits vary with
            # the checkout's umask. Normalize those bits for portable builds.
            if info.issym():
                info.mode = 0o777
            elif info.isdir() or info.mode & 0o100:
                info.mode = 0o755
            else:
                info.mode = 0o644
            if info.isfile():
                with path.open('rb') as file: archive.addfile(info, file)
            else: archive.addfile(info)
    return buffer.getvalue()

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Verify the committed archive and .plg checksum without modifying files')
    args=parser.parse_args()
    manifest=ROOT/'my-unraid-vgpu-manager.plg'
    text=manifest.read_text()
    version=re.search(r'<!ENTITY version\s+"([0-9]{4}\.[0-9]{2}\.[0-9]{2}[a-z]?)">',text).group(1)
    package=ROOT/'packages'/f'my-unraid-vgpu-manager-{version}.txz'
    data=payload(version)
    checksum=hashlib.md5(data).hexdigest()
    if args.check:
        recorded=re.search(r'<!ENTITY md5\s+"([0-9a-f]+)">',text).group(1)
        if not package.is_file() or package.read_bytes()!=data or recorded!=checksum:
            raise SystemExit('Package/source/checksum mismatch. Run python3 scripts/build-plugin.py and commit both outputs.')
        print(f'Package matches source and manifest: {package.name} ({checksum})')
    else:
        package.parent.mkdir(exist_ok=True)
        package.write_bytes(data)
        manifest.write_text(re.sub(r'<!ENTITY md5\s+"[0-9a-f]+">',f'<!ENTITY md5       "{checksum}">',text,count=1))
        print(f'Built {package.relative_to(ROOT)} ({len(data)} bytes; MD5 {checksum})')

if __name__=='__main__': main()
