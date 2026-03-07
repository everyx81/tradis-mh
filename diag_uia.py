from pywinauto import Desktop
import os

def diag():
    print("--- UIA/Win32 Diagnostic Start ---")
    for backend in ["uia", "win32"]:
        print(f"\n=== Testing Backend: {backend} ===")
        try:
            desktop = Desktop(backend=backend)
            windows = desktop.windows(visible_only=True)
            
            for w in windows:
                try:
                    title = w.window_text()
                    cls = w.class_name()
                    
                    if "Acrobat" in cls or "Chrome" in cls:
                        print(f"\n[Window] Title: {title} | Class: {cls}")
                        # Scan descendants for anything containing .pdf or .xlsx
                        for e in w.descendants():
                            try:
                                txt = e.window_text()
                                if txt and ('.pdf' in txt.lower() or '.xlsx' in txt.lower()):
                                    print(f"  - Found File Text: '{txt}'")
                            except Exception:
                                continue
                except Exception:
                    continue
        except Exception as e:
            print(f"Backend {backend} Error: {e}")
    print("\n--- Diagnostic End ---")

if __name__ == "__main__":
    diag()
