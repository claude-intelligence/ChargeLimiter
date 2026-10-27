#!/usr/bin/env python3
"""Version local scripts and styles in the staged app to avoid stale WebView assets."""
import hashlib
from pathlib import Path
import re
import sys

root = Path(sys.argv[1])
index = root / 'index.html'

def version(match):
    name = match.group(2).split('?', 1)[0]
    asset = root / name
    if not asset.is_file() or asset.suffix not in ('.css', '.js'):
        return match.group(0)
    digest = hashlib.sha256(asset.read_bytes()).hexdigest()[:16]
    return match.group(1) + name + '?v=' + digest + match.group(3)

index.write_text(re.sub(r'((?:src|href)=")([^"\s]+)(")', version,
                        index.read_text(encoding='utf-8')), encoding='utf-8')
