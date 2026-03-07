# JARVIS Core - 열린 파일 감지
"""
Windows에서 현재 열려있는 파일(PDF, Excel, 이미지, Word 등)을 감지합니다.
win32gui를 사용하여 모든 창의 제목에서 파일명을 추출합니다.
"""

import os
import re
import warnings
import win32gui
import win32process

# pywinauto의 COM 스레딩 경고 억제
warnings.filterwarnings("ignore", category=UserWarning, module="pywinauto")


# 감지 대상 확장자
TARGET_EXTENSIONS = {
    '.pdf', '.xlsx', '.xls', '.csv',
    '.jpg', '.jpeg', '.png', '.bmp', '.gif', '.tif', '.tiff',
    '.doc', '.docx', '.hwp', '.hwpx',
    '.ppt', '.pptx',
}

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


def get_open_files() -> list[dict]:
    """
    현재 열려있는 파일 목록을 반환합니다.
    
    Returns:
        list[dict]: 각 항목은 {'name': 파일명, 'path': 경로 또는 '', 'icon': 아이콘}
    """
    found_files = {}  # name -> dict (중복 방지)
    
    # 1. win32gui를 이용한 창 제목 스캔 (기본)
    def enum_windows_callback(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return
        
        title = win32gui.GetWindowText(hwnd)
        if not title:
            return
        
        extracted = _extract_filename_from_title(title)
        if extracted:
            name, path = extracted
            if name not in found_files:
                found_files[name] = {
                    'name': name,
                    'path': path,
                    'icon': get_file_type_icon(name),
                    'source': 'window'
                }
    
    try:
        win32gui.EnumWindows(enum_windows_callback, None)
    except Exception:
        pass

    # 2. UI Automation (pywinauto)을 이용한 다중 탭 스캔 (보조)
    _scan_tabs_via_uia(found_files)
    
    # 3. 프로세스 파일 핸들 스캔 (근본적인 방법)
    # Acrobat, Chrome, Edge 등이 물리적으로 물고 있는 파일 핸들 추출
    _scan_process_handles(found_files)
    
    # JARVIS 관련 파일 제외
    result = []
    for info in found_files.values():
        name_lower = info['name'].lower()
        if 'jarvis' in name_lower or 'gui_jarvis' in name_lower:
            continue
        # 정보 보정: source 필드 제거 (UI에 필요 없음)
        info.pop('source', None)
        result.append(info)
    
    result.sort(key=lambda x: x['name'].lower())
    return result


def _scan_process_handles(found_files):
    """psutil을 사용하여 프로세스가 실제로 열고 있는(점유 중인) 파일 핸들 추출"""
    import psutil
    try:
        # 스캔 대상 프로세스 (Acrobat은 필수로 포함)
        # 중요: chrome.exe, msedge.exe는 파일 핸들이나 UIA 접근 시 
        # Chrome 내부에 심각한 메모리 누수(Accessibility tree bloat)를 유발하므로 제외합니다.
        target_proc_names = {"acrobat.exe", "excel.exe", "hwp.exe"}
        
        for proc in psutil.process_iter(['name', 'pid']):
            try:
                p_name = proc.info['name'].lower()
                if p_name in target_proc_names:
                    # 프로세스가 열고 있는 파일 목록 가져오기
                    open_files = proc.open_files()
                    for f in open_files:
                        path = f.path
                        # 감지 대상 확장자 확인
                        ext = os.path.splitext(path)[1].lower()
                        if ext in TARGET_EXTENSIONS:
                            # 시스템 파일이나 임시 파일 제외 (사용자 문서만 추출)
                            path_lower = path.lower()
                            if 'appdata' in path_lower or 'windows' in path_lower:
                                continue
                            
                            if os.path.exists(path):
                                name = os.path.basename(path)
                                # 엑셀/워드 등 임시 소유자 파일(~$...) 제외
                                if name.startswith('~$'):
                                    continue
                                    
                                if name not in found_files:
                                    found_files[name] = {
                                        'name': name,
                                        'path': path,
                                        'icon': get_file_type_icon(name),
                                        'source': 'handle'
                                    }
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                continue
            except Exception:
                continue
    except Exception:
        pass


def _scan_tabs_via_uia(found_files):
    """pywinauto를 사용하여 Acrobat의 다중 탭 제목을 추출
    
    주의: Desktop(backend="uia")는 모든 창의 접근성 트리에 접근하여
    Chrome/Edge 등에 심각한 메모리 누수를 유발하므로 사용 금지.
    대신 Application.connect()로 Acrobat에만 직접 연결합니다.
    """
    try:
        from pywinauto import Application
        
        # Acrobat 프로세스에만 직접 연결 (다른 프로그램에 접근하지 않음)
        try:
            app = Application(backend="uia").connect(class_name="AcrobatSDIWindow", visible_only=True)
        except Exception:
            # Acrobat이 실행 중이 아니면 스캔 불필요
            return
        
        # 연결된 Acrobat 창에서 탭 제목 추출
        for w in app.windows(class_name="AcrobatSDIWindow", visible_only=True):
            try:
                # 탭 항목에서 파일명 추출
                for element in w.descendants(control_type="TabItem"):
                    title = element.window_text()
                    if title:
                        extracted = _extract_filename_from_title(title)
                        if extracted:
                            name, path = extracted
                            if name not in found_files:
                                found_files[name] = {
                                    'name': name,
                                    'path': path,
                                    'icon': get_file_type_icon(name),
                                }
                
                # 텍스트 컨트롤에서도 파일명 추출 (Acrobat 일부 버전 호환)
                for element in w.descendants(control_type="Text"):
                    title = element.window_text()
                    if any(ext in title.lower() for ext in TARGET_EXTENSIONS):
                        extracted = _extract_filename_from_title(title)
                        if extracted:
                            name, path = extracted
                            if name not in found_files:
                                found_files[name] = {
                                    'name': name,
                                    'path': path,
                                    'icon': get_file_type_icon(name),
                                }
            except Exception:
                continue
    except Exception:
        pass


def _extract_filename_from_title(title: str):
    """
    창 제목에서 파일명과 경로를 추출합니다.
    
    일반적인 창 제목 패턴:
    - "파일명.xlsx - Excel"
    - "파일명 - Excel"  (확장자 없이)
    - "파일명.pdf - Adobe Acrobat"
    - "파일명.pdf - Chrome"
    - "C:\\path\\to\\파일명.pdf - 프로그램"
    - "파일명 [호환 모드] - Excel"
    - "파일명.png - Windows 사진 뷰어"
    
    Returns:
        (filename, filepath) 튜플 또는 None
    """
    # 전처리: 불필요한 공백 및 제어문자 제거
    title = title.strip()
    if not title:
        return None

    # 패턴 1: 전체 경로가 제목에 있는 경우
    path_pattern = re.compile(
        r'([A-Za-z]:\\[^\*\?"<>|]+\.(' + '|'.join(
            ext.lstrip('.') for ext in TARGET_EXTENSIONS
        ) + r'))', re.IGNORECASE
    )
    path_match = path_pattern.search(title)
    if path_match:
        full_path = path_match.group(1)
        filename = os.path.basename(full_path)
        return filename, full_path
    
    # 패턴 2: 파일명 + 확장자가 제목에 있는 경우
    # "filename.pdf - Adobe Reader" 등에서 정확히 "filename.pdf" 추출
    name_pattern = re.compile(
        r'([^\\/\*\?"<>|]+\.(' + '|'.join(
            ext.lstrip('.') for ext in TARGET_EXTENSIONS
        ) + r'))',
        re.IGNORECASE
    )
    name_match = name_pattern.search(title)
    if name_match:
        filename = name_match.group(1).strip()
        # 대괄호 접미사 제거
        filename = re.sub(r'\s*\[.*?\]\s*$', '', filename)
        return filename, ''
    
    # 패턴 3: 확장자 없이 프로그램명으로 매칭 (Excel, Word, HWP 등)
    # "파일명 - Excel", "파일명 [호환 모드] - Excel", "파일명 - Word"
    app_patterns = {
        r'^(.+?)(?:\s*\[.*?\])?\s*-\s*(?:Microsoft\s+)?Excel': '.xlsx',
        r'^(.+?)(?:\s*\[.*?\])?\s*-\s*(?:Microsoft\s+)?Word': '.docx',
        r'^(.+?)(?:\s*\[.*?\])?\s*-\s*(?:Microsoft\s+)?PowerPoint': '.pptx',
        r'^(.+?)(?:\s*\[.*?\])?\s*-\s*Adobe\s+Acrobat': '.pdf',
        r'^(.+?)(?:\s*\[.*?\])?\s*-\s*한글': '.hwp',
        r'^(.+?)\s*-\s*사진': '.jpg',  # Windows 사진 앱
    }
    
    for pattern, default_ext in app_patterns.items():
        match = re.match(pattern, title, re.IGNORECASE)
        if match:
            raw_name = match.group(1).strip()
            # 이미 확장자가 있으면 그대로, 없으면 추가
            _, ext = os.path.splitext(raw_name)
            if ext.lower() in TARGET_EXTENSIONS:
                return raw_name, ''
            else:
                return raw_name + default_ext, ''
    
    return None



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
        for root, dirs, files in os.walk(search_dir):
            if filename in files:
                return os.path.join(root, filename)
            # 1단계 깊이만 탐색
            if root != search_dir:
                continue
    
    return ''
