# -*- mode: python ; coding: utf-8 -*-

import sys
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

block_cipher = None

# Collect all submodules for packages that might be dynamically imported
hiddenimports = [
    'boto3',
    'botocore',
    'click',
    'mysql.connector',
    'paramiko',
    'dotenv',
    'cryptography',
    'pkg_resources.py2_warn',
    'db_backup',
    'db_backup.app',
    'db_backup.data',
    'db_backup.domain',
    'db_backup.interface',
]

# Collect data files for packages that need them
datas = []

# Collect submodules for boto3 and botocore (they have many dynamic imports)
hiddenimports += collect_submodules('boto3')
hiddenimports += collect_submodules('botocore')
hiddenimports += collect_submodules('mysql')
hiddenimports += collect_submodules('paramiko')
hiddenimports += collect_submodules('cryptography')

a = Analysis(
    ['entry_point.py'],
    pathex=['.', 'db-backup'],  # Add db-backup directory to path for imports
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='db-backup',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

