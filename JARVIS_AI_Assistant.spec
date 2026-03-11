# -*- mode: python ; coding: utf-8 -*-

import os

block_cipher = None

# 리소스 파일들 (이미지, 아이콘, 설정 등)
datas = [
    ('intro_jarvis.jpg', '.'),
    ('jarvis_bg.png', '.'),
    ('app_icon.ico', '.'),
    ('es.exe', '.'),  # Everything 검색 도구
]

# Hidden imports - 동적으로 임포트되는 모듈들
hidden_imports = [
    'PyQt6',
    'PyQt6.QtWidgets',
    'PyQt6.QtCore',
    'PyQt6.QtGui',
    'google.generativeai',
    'google.ai.generativelanguage',
    'PIL',
    'PIL.Image',
    'pdf2image',
    'fitz',  # PyMuPDF
    'winotify',
    'keyring',
    'keyring.backends',
    'keyring.backends.Windows',
    # 엑셀 파싱 (수출 자동화)
    'openpyxl',
    'openpyxl.workbook',
    'openpyxl.worksheet',
    'openpyxl.utils',
    # 메일 모니터링
    'imaplib',
    'email',
    'email.header',
    'email.message',
    # pywinauto (ReadyKorea 자동화)
    'pywinauto',
    'pywinauto.application',
    'pywinauto.keyboard',
    'pywinauto.mouse',
    # 수출 자동화 모듈
    'export_mail_monitor',
    'export_excel_parser',
    'readykorea_automation',
    'export_mail_sender',
    # Google Sheets 연동
    'gspread',
    'google.oauth2',
    'google.oauth2.service_account',
    # PDF 보고서 생성 (reportlab)
    'reportlab',
    'reportlab.lib',
    'reportlab.lib.colors',
    'reportlab.lib.pagesizes',
    'reportlab.lib.styles',
    'reportlab.lib.units',
    'reportlab.pdfbase',
    'reportlab.pdfbase.pdfmetrics',
    'reportlab.pdfbase.ttfonts',
    'reportlab.platypus',
    'reportlab.platypus.tables',
    'reportlab.platypus.paragraph',
    # 내부 모듈들
    'core',
    'core.config',
    'core.constants',
    'core.utils',
    'core.ocr',
    'core.file_processor',
    'core.archiver',
    'core.google_sheets',
    'core.report_generator',
    'gui',
    'gui.styles',
    'gui.utils',
    'gui.widgets',
    'gui.panels',
    'gui.dialogs',
    'gui.mk3_widgets',
    'gui.report_panel',
    'gui.jarvis_toast',
    'calendar_manager',
    'auto_rename',
    'version',
    'updater',
]

a = Analysis(
    ['gui_jarvis.py'],
    pathex=['.'],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'PyQt5',
        'PyQt5.QtCore',
        'PyQt5.QtGui', 
        'PyQt5.QtWidgets',
        'PyQt5.sip',
    ],
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
    a.datas,
    [],
    name='TRADIS_MH',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # GUI 앱이므로 콘솔 숨김
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='app_icon.ico',
)
