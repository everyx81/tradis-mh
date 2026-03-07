import win32gui
import win32process
from pywinauto import Application
import sys

def dump_acro():
    hwnds = []
    win32gui.EnumWindows(lambda h, _: hwnds.append(h) if 'Acrobat' in win32gui.GetClassName(h) else None, None)
    
    if not hwnds:
        print("No Acrobat windows found.")
        return

    # Use the first one that has a title
    target_hwnd = None
    for h in hwnds:
        if win32gui.GetWindowText(h):
            target_hwnd = h
            break
    
    if not target_hwnd:
        target_hwnd = hwnds[0]

    print(f"Connecting to HWND: {target_hwnd} ({win32gui.GetWindowText(target_hwnd)})")
    
    try:
        app = Application(backend="uia").connect(handle=target_hwnd)
        main_win = app.window(handle=target_hwnd)
        
        # Dump to file
        with open("acro_tree.txt", "w", encoding="utf-8") as f:
            # We use a custom crawler to avoid pywinauto's print_control_identifiers which is too verbose
            def crawl(element, depth=0):
                try:
                    name = element.window_text()
                    ctype = element.element_info.control_type
                    f.write("  " * depth + f"- [{ctype}] Name: '{name}'\n")
                    for child in element.children():
                        crawl(child, depth + 1)
                except:
                    pass
            
            crawl(main_win)
        print("Tree dumped to acro_tree.txt")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    dump_acro()
