#!/usr/bin/env python3
"""Check the archive with libarchive (the reader used by TrollStore) and zipfile."""
import ctypes
import plistlib
import stat
import sys
import zipfile
from pathlib import Path


def verify(path):
    lib = ctypes.CDLL('/usr/lib/libarchive.dylib')
    signatures = {
        'archive_read_new': (ctypes.c_void_p, []),
        'archive_read_support_format_all': (ctypes.c_int, [ctypes.c_void_p]),
        'archive_read_support_filter_all': (ctypes.c_int, [ctypes.c_void_p]),
        'archive_read_open_filename': (ctypes.c_int, [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t]),
        'archive_read_next_header': (ctypes.c_int, [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]),
        'archive_entry_pathname': (ctypes.c_char_p, [ctypes.c_void_p]),
        'archive_error_string': (ctypes.c_char_p, [ctypes.c_void_p]),
        'archive_read_free': (ctypes.c_int, [ctypes.c_void_p]),
    }
    for name, (result, args) in signatures.items():
        fn = getattr(lib, name)
        fn.restype, fn.argtypes = result, args
    archive = lib.archive_read_new()
    names = []
    try:
        lib.archive_read_support_format_all(archive)
        lib.archive_read_support_filter_all(archive)
        if lib.archive_read_open_filename(archive, bytes(path), 10240) != 0:
            raise ValueError('libarchive 无法打开 IPA')
        entry = ctypes.c_void_p()
        while True:
            status = lib.archive_read_next_header(archive, ctypes.byref(entry))
            if status == 1:  # ARCHIVE_EOF
                break
            if status < -20:  # Below ARCHIVE_WARN, TrollStore stops enumerating.
                raise ValueError(str(lib.archive_error_string(archive)))
            names.append(lib.archive_entry_pathname(entry).decode('utf-8'))
    finally:
        lib.archive_read_free(archive)

    # TrollStore discovers an app from Payload/<name>.app/<entry>.
    apps = {parts[1] for name in names if len(parts := name.rstrip('/').split('/')) == 3
            and parts[0] == 'Payload' and parts[1].endswith('.app')}
    if apps != {'ChargeLimiter.app'}:
        raise ValueError(f'libarchive 无法定位唯一的 ChargeLimiter.app: {apps}')
    with zipfile.ZipFile(path) as archive:
        if len(archive.namelist()) != len(set(archive.namelist())):
            raise ValueError('IPA 存在重复路径')
        if archive.testzip() is not None:
            raise ValueError('IPA 完整性校验失败')
        prefix = 'Payload/ChargeLimiter.app/'
        info = plistlib.loads(archive.read(prefix + 'Info.plist'))
        if info.get('CFBundlePackageType') != 'APPL' or not info.get('CFBundleIdentifier'):
            raise ValueError('Info.plist 缺少有效的应用标识')
        executable = info.get('CFBundleExecutable')
        if executable != 'ChargeLimiter':
            raise ValueError(f'主程序名称不正确: {executable!r}')
        for binary in [executable, 'ChargeLimiterDaemon',
                       'Frameworks/GCDWebServers.framework/GCDWebServers']:
            entry = archive.getinfo(prefix + binary)
            if not stat.S_IMODE(entry.external_attr >> 16) & 0o111:
                raise ValueError(f'缺少执行权限: {binary}')
            data = archive.read(entry)
            if data[:4] != b'\xcf\xfa\xed\xfe' or data[4:8] != b'\x0c\x00\x00\x01':
                raise ValueError(f'不是 arm64 Mach-O: {binary}')
        if prefix + 'www/index.html' not in names:
            raise ValueError('缺少界面资源')
    print(f'IPA 校验通过（libarchive、应用目录、Info.plist、arm64 程序、权限）: {path}')


if __name__ == '__main__':
    try:
        verify(Path(sys.argv[1]).resolve())
    except (ValueError, OSError, KeyError, zipfile.BadZipFile) as error:
        sys.exit(f'IPA 校验失败: {error}')
