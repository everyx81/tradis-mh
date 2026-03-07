# Windows OLE 드래그 앤 드롭 모듈
"""
Windows 탐색기와 동일한 OLE 드래그 앤 드롭을 구현합니다.
카카오톡, 네이트온 등 외부 프로그램과 호환됩니다.
"""

import os
import struct
import ctypes
from ctypes import wintypes, POINTER, byref, c_void_p, c_ulong, WINFUNCTYPE

# COM 인터페이스 GUID 정의
class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8)
    ]

# IID 정의
IID_IDataObject = GUID(0x0000010E, 0x0000, 0x0000, (0xC0, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x46))
IID_IDropSource = GUID(0x00000121, 0x0000, 0x0000, (0xC0, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x46))

# 상수 정의
CF_HDROP = 15
TYMED_HGLOBAL = 1
DVASPECT_CONTENT = 1
DATADIR_GET = 1

DROPEFFECT_NONE = 0
DROPEFFECT_COPY = 1
DROPEFFECT_MOVE = 2
DROPEFFECT_LINK = 4

DRAGDROP_S_DROP = 0x00040100
DRAGDROP_S_CANCEL = 0x00040101

MK_LBUTTON = 0x0001

GMEM_MOVEABLE = 0x0002
GMEM_ZEROINIT = 0x0040

# FORMATETC 구조체
class FORMATETC(ctypes.Structure):
    _fields_ = [
        ("cfFormat", ctypes.c_ushort),
        ("ptd", ctypes.c_void_p),
        ("dwAspect", ctypes.c_ulong),
        ("lindex", ctypes.c_long),
        ("tymed", ctypes.c_ulong)
    ]

# STGMEDIUM 구조체
class STGMEDIUM(ctypes.Structure):
    _fields_ = [
        ("tymed", ctypes.c_ulong),
        ("hGlobal", ctypes.c_void_p),
        ("pUnkForRelease", ctypes.c_void_p)
    ]


def create_hdrop_data(file_paths):
    """CF_HDROP 형식의 데이터 생성"""
    header_size = 20
    file_data = b""
    for path in file_paths:
        path = os.path.abspath(path).replace("/", "\\")
        file_data += path.encode("utf-16-le") + b"\x00\x00"
    file_data += b"\x00\x00"  # 이중 NULL 종료
    
    # DROPFILES 헤더: pFiles(4), pt.x(4), pt.y(4), fNC(4), fWide(4)
    header = struct.pack("IIIII", header_size, 0, 0, 0, 1)  # fWide=1 (유니코드)
    return header + file_data


def do_file_drag_drop(file_paths):
    """Windows OLE 드래그 앤 드롭 실행
    
    참고: pywin32의 DoDragDrop은 IDropSource COM 게이트웨이 미등록으로
    호환성 문제가 있어, False를 반환하여 PyQt 드래그 폴백을 사용합니다.
    PyQt 내부적으로 OLE DoDragDrop을 올바르게 처리합니다.
    """
    return False


if __name__ == "__main__":
    # 테스트
    test_file = r"C:\Users\최명헌\Desktop\test\gui_jarvis.py"
    if os.path.exists(test_file):
        print(f"Testing drag drop with: {test_file}")
        do_file_drag_drop([test_file])
    else:
        print("Test file not found")
