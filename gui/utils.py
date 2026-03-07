# JARVIS GUI 유틸리티 함수
"""
GUI 유틸리티 함수:
- resource_path: 리소스 절대 경로 반환
- get_run_dir: 실행 파일 디렉토리 반환
- generate_pdf_thumbnail: PDF 썸네일 생성 및 캐싱
"""

import os
import sys

_thumbnail_cache = {}  # {filepath: QPixmap}

def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)

def get_run_dir():
    """ Get directory where the executable (or script) is running """
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    # gui 패키지 내부에 있으므로, 상위 디렉토리(프로젝트 루트)를 반환
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def generate_pdf_thumbnail(pdf_path, width=200, height=280):
    """PDF 첫 페이지를 썸네일로 렌더링하여 QPixmap 반환"""
    if not pdf_path or not os.path.exists(pdf_path):
        return None
    
    # 캐시 확인
    if pdf_path in _thumbnail_cache:
        return _thumbnail_cache[pdf_path]
    
    try:
        import pypdfium2 as pdfium
        from PyQt6.QtGui import QPixmap
        from PyQt6.QtCore import Qt
        import io
        
        with open(pdf_path, 'rb') as f:
            pdf_bytes = f.read()
        
        pdf = pdfium.PdfDocument(pdf_bytes)
        if len(pdf) > 0:
            page = pdf[0]
            # 썸네일 크기에 맞춰 스케일 계산 (scale 높을수록 화질 향상)
            bitmap = page.render(scale=3)
            pil_image = bitmap.to_pil()
            
            # PIL 이미지를 QPixmap으로 변환
            img_byte_arr = io.BytesIO()
            pil_image.save(img_byte_arr, format='PNG')
            img_byte_arr.seek(0)
            
            pixmap = QPixmap()
            pixmap.loadFromData(img_byte_arr.read())
            pixmap = pixmap.scaled(width, height, Qt.AspectRatioMode.KeepAspectRatio, 
                                    Qt.TransformationMode.SmoothTransformation)
            
            # 캐시 저장
            _thumbnail_cache[pdf_path] = pixmap
            pdf.close()
            return pixmap
        pdf.close()
    except Exception as e:
        print(f"썸네일 생성 오류: {e}")
    return None
