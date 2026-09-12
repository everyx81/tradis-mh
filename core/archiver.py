# JARVIS Core - 아카이버
"""
파일 아카이빙 및 폴더 관리
"""

from typing import Optional, Callable


class Archiver:
    """파일 아카이빙 관리자"""
    
    def __init__(self, import_root: str, export_root: str, export_docs_root: str = "", log_callback: Optional[Callable[[str], None]] = None):
        self.import_root = import_root
        self.export_root = export_root
        self.export_docs_root = export_docs_root
        self.log_callback = log_callback

    def log(self, message: str):
        if self.log_callback:
            self.log_callback(message)
