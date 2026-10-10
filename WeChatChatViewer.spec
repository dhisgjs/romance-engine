# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['F:/ProgramFiles/微信逆向/wx-chat-export/client.py'],
    pathex=['F:/ProgramFiles/微信逆向/wx-chat-export'],
    binaries=[],
    datas=[],
    hiddenimports=['backend.core.memscan', 'backend.core.decrypt', 'backend.core.models', 'backend.core.pipeline', 'backend.core.watcher', 'backend.core.exporter', 'backend.core.collections', 'backend.core.imported_store', 'backend.core.media', 'backend.core.aigen', 'backend.core.notes', 'backend.core.buddy_memory', 'backend.core.ai_chats', 'backend.core.account_info', 'PIL', 'PIL.Image', 'PIL.ImageFile', 'pillow_heif', 'zstandard', 'zstandard.backend_c'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='WeChatChatViewer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='WeChatChatViewer',
)
