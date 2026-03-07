import win32gui
import win32con
import win32api
import os
import time

def diag_acrobat_windows():
    print("=== Acrobat Multi-Window/Tab Diagnostic ===")
    
    found_titles = []
    
    # 1. EnumWindows - 모든 창 제목 수집 (비가시 포함)
    def enum_cb(hwnd, _):
        class_name = win32gui.GetClassName(hwnd)
        if "Acrobat" in class_name:
            title = win32gui.GetWindowText(hwnd)
            visible = win32gui.IsWindowVisible(hwnd)
            # 텍스트가 있는 창만 수집
            if title:
                found_titles.append(f"Title: {title} | Class: {class_name} | Visible: {visible}")
                
    win32gui.EnumWindows(enum_cb, None)
    
    print(f"\n[1] Windows found ({len(found_titles)}):")
    for t in found_titles:
        print(f"  - {t}")

    # 2. DDE (Dynamic Data Exchange) 시도
    # Acrobat은 DDE를 통해 목록을 줄 수 있음
    print("\n[2] Attempting DDE to get open documents...")
    try:
        import win32ui
        import dde
        server = dde.CreateServer()
        server.Create("JarvisScan")
        conversation = dde.CreateConversation(server)
        
        # Acrobat DDE Service: 'acroview', Topic: 'Control'
        try:
            conversation.ConnectTo("acroview", "Control")
            # [AppGetActiveDoc()] or similar commands exist but documentation is sparse
            # Let's try to request something general
            docs = conversation.Request("AppGetActiveDoc")
            print(f"  DDE Response (ActiveDoc): {docs}")
        except Exception as e:
            print(f"  DDE Connection failed: {e}")
    except Exception as e:
        print(f"  DDE Module error: {e}")

    # 3. Registry - 최근 열린 파일 또는 상태 정보 확인
    print("\n[3] Checking Registry (Recent Files)...")
    try:
        import winreg
        # Adobe Acrobat DC path: 
        # HKEY_CURRENT_USER\Software\Adobe\Acrobat Reader\DC\AVGeneral\cRecentFiles
        key_path = r"Software\Adobe\Acrobat Reader\DC\AVGeneral\cRecentFiles"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            for i in range(10): # Top 10 recent
                try:
                    sub_key_name = f"c{i}"
                    with winreg.OpenKey(key, sub_key_name) as subkey:
                        file_path, _ = winreg.QueryValueEx(subkey, "tName")
                        print(f"  Recent {i}: {file_path}")
                except OSError:
                    break
    except Exception as e:
        print(f"  Registry check failed: {e}")

if __name__ == "__main__":
    diag_acrobat_windows()
