from pywinauto import Desktop
import sys

def deep_scan_acro():
    print("--- Acrobat Deep Accessibility Scan ---")
    try:
        desktop = Desktop(backend="uia")
        acro_wins = [w for w in desktop.windows(visible_only=True) if "Acrobat" in w.class_name()]
        
        if not acro_wins:
            print("No visible Acrobat windows.")
            return

        found = set()
        for w in acro_wins:
            print(f"Scanning Window: {w.window_text()}")
            # 1. 모든 자손 요소를 타입 가리지 않고 전수 조사
            # depth를 깊게 하여 탭 내부의 텍스트 노드까지 검색
            try:
                # children() 순회로 깊이 우선 탐색
                def recursive_find(element, depth=0):
                    if depth > 15: return # 과도한 깊이 방지
                    
                    try:
                        name = element.window_text()
                        ctype = element.element_info.control_type
                        
                        if name and ('.pdf' in name.lower()):
                            print(f"  [Found at depth {depth}] Name: '{name}' | Type: {ctype}")
                            found.add(name)
                        
                        # 하위 요소 탐색
                        for child in element.children():
                            recursive_find(child, depth + 1)
                    except:
                        pass
                
                recursive_find(w)
            except Exception as e:
                print(f"  Error during scan: {e}")
        
        print(f"\nTotal Files Found: {len(found)}")
        for f in found:
            print(f"  * {f}")

    except Exception as e:
        print(f"Global Error: {e}")

if __name__ == "__main__":
    deep_scan_acro()
