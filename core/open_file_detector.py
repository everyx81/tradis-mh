# JARVIS Core - 열린 파일 감지
"""
Windows에서 현재 열려있는 파일(PDF, Excel, 이미지, Word 등)을 감지합니다.
win32gui를 사용하여 모든 창의 제목에서 파일명을 추출합니다.
"""

import os
import warnings

# pywinauto의 COM 스레딩 경고 억제
warnings.filterwarnings("ignore", category=UserWarning, module="pywinauto")


# 파일 타입 아이콘 매핑
FILE_TYPE_ICONS = {
    '.pdf': '📄',
    '.xlsx': '📊', '.xls': '📊', '.csv': '📊',
    '.jpg': '🖼️', '.jpeg': '🖼️', '.png': '🖼️', 
    '.bmp': '🖼️', '.gif': '🖼️', '.tif': '🖼️', '.tiff': '🖼️',
    '.doc': '📝', '.docx': '📝',
    '.hwp': '📝', '.hwpx': '📝',
    '.ppt': '📊', '.pptx': '📊',
}

def get_file_type_icon(filename: str) -> str:
    """파일 확장자에 따른 아이콘 반환"""
    ext = os.path.splitext(filename)[1].lower()
    return FILE_TYPE_ICONS.get(ext, '📁')


def find_file_path(filename: str, search_dirs: list[str] = None) -> str:
    """
    파일명으로 실제 경로를 찾습니다.
    
    Args:
        filename: 찾을 파일명
        search_dirs: 검색할 디렉토리 목록
    
    Returns:
        찾은 파일의 전체 경로 또는 빈 문자열
    """
    if not search_dirs:
        return ''
    
    for search_dir in search_dirs:
        if not search_dir or not os.path.exists(search_dir):
            continue
        # 해당 디렉토리와 하위 폴더를 재귀 검색
        for root, dirs, files in os.walk(search_dir):
            if filename in files:
                return os.path.join(root, filename)

    return ''
