#!/usr/bin/env python3
"""Create a plain IPA without ZIP extensions or host-specific metadata."""
import argparse
import stat
import zipfile
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('app', type=Path)
parser.add_argument('output', type=Path)
parser.add_argument('--store', action='store_true', help='Disable compression for compatibility testing')
args = parser.parse_args()
app = args.app.resolve()
if app.name != 'ChargeLimiter.app' or not (app / 'Info.plist').is_file():
    parser.error('expected ChargeLimiter.app containing Info.plist')
files = sorted((p for p in app.rglob('*') if p.is_file()),
               key=lambda p: (p.name != 'Info.plist' or p.parent != app, p.as_posix()))
with zipfile.ZipFile(args.output, 'w', allowZip64=False) as archive:
    for path in files:
        # Framework links, if present, are copied as regular files for older readers.
        if not path.resolve().is_relative_to(app):
            parser.error(f'file points outside app: {path}')
        entry = zipfile.ZipInfo('Payload/' + app.name + '/' + path.relative_to(app).as_posix(),
                                date_time=(2020, 1, 1, 0, 0, 0))
        entry.create_system = 3
        entry.compress_type = zipfile.ZIP_STORED if args.store else zipfile.ZIP_DEFLATED
        entry.create_version = entry.extract_version = 10 if args.store else 20
        entry.external_attr = (stat.S_IFREG | stat.S_IMODE(path.stat().st_mode)) << 16
        entry.extra = b''
        entry.comment = b''
        archive.writestr(entry, path.read_bytes())
