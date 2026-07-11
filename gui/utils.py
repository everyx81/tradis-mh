# JARVIS GUI 유틸리티 함수
"""
GUI 유틸리티 함수:
- resource_path: 리소스 절대 경로 반환
- get_run_dir: 실행 파일 디렉토리 반환
- generate_pdf_thumbnail: PDF 썸네일 생성 및 캐싱
"""

import os
import sys
from collections import OrderedDict

# 썸네일 LRU 캐시 — 미리보기 팝업 썸네일은 장당 수 MB(최대 ~900×1260px)라서
# 무제한으로 쌓으면 세션이 길어질수록 메모리가 계속 증가한다.
# 바이트 예산을 넘으면 가장 오래 안 쓴 항목부터 자동 삭제.
_thumbnail_cache = OrderedDict()  # {(filepath, width, height, page, dpr): QPixmap}
_thumbnail_cache_bytes = 0
_THUMB_CACHE_MAX_BYTES = 60 * 1024 * 1024  # 60MB

_page_count_cache = {}  # {filepath: int}
_PAGE_COUNT_CACHE_MAX = 1000


def _pixmap_nbytes(pm):
    """QPixmap 대략적 메모리 크기 (RGBA 4바이트/픽셀)."""
    return pm.width() * pm.height() * 4


def _thumb_cache_put(key, pm):
    """썸네일을 LRU 캐시에 넣고 예산 초과분을 오래된 순으로 제거."""
    global _thumbnail_cache_bytes
    old = _thumbnail_cache.pop(key, None)
    if old is not None:
        _thumbnail_cache_bytes -= _pixmap_nbytes(old)
    _thumbnail_cache[key] = pm
    _thumbnail_cache_bytes += _pixmap_nbytes(pm)
    while _thumbnail_cache_bytes > _THUMB_CACHE_MAX_BYTES and len(_thumbnail_cache) > 1:
        _, evicted = _thumbnail_cache.popitem(last=False)
        _thumbnail_cache_bytes -= _pixmap_nbytes(evicted)


def _thumb_cache_get(key):
    """캐시 조회 — 히트 시 최근 사용으로 갱신."""
    pm = _thumbnail_cache.get(key)
    if pm is not None:
        _thumbnail_cache.move_to_end(key)
    return pm

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

def get_pdf_page_count(pdf_path):
    """PDF 페이지 수 반환 (실패 시 1)."""
    if not pdf_path or not os.path.exists(pdf_path):
        return 1
    if pdf_path in _page_count_cache:
        return _page_count_cache[pdf_path]
    try:
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(pdf_path)
        n = len(pdf)
        pdf.close()
        if len(_page_count_cache) >= _PAGE_COUNT_CACHE_MAX:
            _page_count_cache.clear()
        _page_count_cache[pdf_path] = max(1, n)
        return _page_count_cache[pdf_path]
    except Exception:
        return 1


def generate_pdf_thumbnail(pdf_path, width=200, height=280, page_index=0):
    """PDF 페이지를 썸네일로 렌더링하여 QPixmap 반환.

    화면 배율(DPI)에 맞는 실제 픽셀 해상도로 렌더링해 확대 화면에서도 선명하다.
    캐시는 (경로, 크기, 페이지, 배율) 조합별로 저장 — 크기가 다른 요청이
    서로의 캐시를 덮어쓰던 문제 방지.
    """
    if not pdf_path or not os.path.exists(pdf_path):
        return None

    # 디바이스 픽셀 비율 (150% 화면 = 1.5)
    dpr = 1.0
    try:
        from PyQt6.QtGui import QGuiApplication
        app = QGuiApplication.instance()
        if app is not None:
            dpr = max(1.0, float(app.devicePixelRatio()))
    except Exception:
        pass

    cache_key = (pdf_path, width, height, page_index, round(dpr * 100))
    cached = _thumb_cache_get(cache_key)
    if cached is not None:
        return cached

    try:
        import pypdfium2 as pdfium
        from PyQt6.QtGui import QPixmap
        from PyQt6.QtCore import Qt
        import io

        with open(pdf_path, 'rb') as f:
            pdf_bytes = f.read()

        pdf = pdfium.PdfDocument(pdf_bytes)
        if 0 <= page_index < len(pdf):
            page = pdf[page_index]
            # 목표 픽셀 크기(논리 크기 × 배율)에 맞춰 렌더 스케일 계산
            # (pypdfium2 scale=1 → 72dpi, 페이지 pt 크기 기준)
            target_w = width * dpr
            target_h = height * dpr
            try:
                pw, ph = page.get_size()
                scale = max(1.0, min(target_w / pw, target_h / ph))
                scale = min(scale, 6.0)  # 과도한 메모리 사용 방지
            except Exception:
                scale = 3.0
            bitmap = page.render(scale=scale)
            pil_image = bitmap.to_pil()

            # PIL 이미지를 QPixmap으로 변환
            img_byte_arr = io.BytesIO()
            pil_image.save(img_byte_arr, format='PNG')
            img_byte_arr.seek(0)

            pixmap = QPixmap()
            pixmap.loadFromData(img_byte_arr.read())
            pixmap = pixmap.scaled(int(target_w), int(target_h),
                                   Qt.AspectRatioMode.KeepAspectRatio,
                                   Qt.TransformationMode.SmoothTransformation)
            pixmap.setDevicePixelRatio(dpr)

            _thumb_cache_put(cache_key, pixmap)
            pdf.close()
            return pixmap
        pdf.close()
    except Exception as e:
        print(f"썸네일 생성 오류: {e}")
    return None
