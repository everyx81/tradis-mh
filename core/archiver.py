# JARVIS Core - 아카이버
"""
파일 아카이빙 및 폴더 관리
"""

import os
from typing import Optional, Callable

from .utils import parse_renamed_filename


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

    def find_company_folder(self, root, cn, depth=3):
        """회사 폴더 찾기"""
        for d, dirs, files in os.walk(root):
            if d.count(os.sep) - root.count(os.sep) > depth:
                continue
            for dr in dirs:
                if cn.upper() in dr.upper():
                    return os.path.join(d, dr)
        return None

    def analyze_folder(self, path):
        """폴더 분석"""
        files = [f for f in os.listdir(path) if f.lower().endswith('.pdf')]
        if not files:
            return "import", "Unknown", "Unknown", "No PDF files found"
        valid_companies = []
        valid_ids = []
        for f in files:
            c, i, d, s = parse_renamed_filename(f)
            if c and c != "Unknown":
                valid_companies.append(c)
            if i and i != "Unknown":
                valid_ids.append(i)
        mode = "export" if any("수출" in f for f in files) else "import"
        comp = max(set(valid_companies), key=valid_companies.count) if valid_companies else "Unknown"
        iden = max(set(valid_ids), key=valid_ids.count) if valid_ids else "Unknown"
        return mode, comp, iden, ""
