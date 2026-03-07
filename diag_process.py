import pywinauto
from pywinauto import Desktop
import psutil

def diag_by_process():
    print("--- Process Based Diagnostic ---")
    acro_pids = [p.info['pid'] for p in psutil.process_iter(['name', 'pid']) if 'acrobat' in p.info['name'].lower()]
    print(f"Acrobat PIDs: {acro_pids}")
    
    if not acro_pids:
        print("Acrobat not running.")
        return

    d_uia = Desktop(backend="uia")
    d_win32 = Desktop(backend="win32")
    
    for pid in acro_pids:
        print(f"\nScanning PID: {pid}")
        # Find all windows for this PID
        for backend, d in [("uia", d_uia), ("win32", d_win32)]:
            print(f"  Backend: {backend}")
            try:
                wins = d.windows(process=pid)
                for w in wins:
                    print(f"    - Window Title: '{w.window_text()}' | Class: '{w.class_name()}' | Visible: {w.is_visible()}")
                    # Try to find anything looking like a filename in children
                    for e in w.descendants():
                        try:
                            txt = e.window_text()
                            if txt and ('.pdf' in txt.lower()):
                                print(f"      * Found PDF: '{txt}'")
                        except:
                            continue
            except Exception as e:
                print(f"    Error: {e}")

if __name__ == "__main__":
    diag_by_process()
