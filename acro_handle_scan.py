import psutil
import os

def find_acro_open_files():
    print("--- Acrobat Physical Handle Scan ---")
    found_pdfs = set()
    
    # 1. Acrobat 프로세스 모두 찾기
    acro_procs = []
    for p in psutil.process_iter(['name', 'pid']):
        try:
            name = p.info.get('name', '')
            if name and 'acrobat' in name.lower():
                acro_procs.append(p)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
            
    if not acro_procs:
        print("No Acrobat processes found.")
        return

    print(f"Found {len(acro_procs)} Acrobat processes.")

    # 2. 각 프로세스가 열고 있는 파일(Handles) 전수 조사
    for p in acro_procs:
        try:
            print(f"  Scanning PID {p.pid}...")
            files = p.open_files()
            for f in files:
                path = f.path
                if path.lower().endswith('.pdf'):
                    # 시스템 임시 파일이나 폰트 등 제외 (순수 사용자 PDF만 추출)
                    if 'appdata' not in path.lower() and 'windows' not in path.lower():
                        print(f"    * Found Handle: {path}")
                        found_pdfs.add(path)
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            continue
        except Exception as e:
            print(f"    Error on PID {p.pid}: {e}")

    print(f"\nFinal Result ({len(found_pdfs)} files):")
    for pdf in found_pdfs:
        print(f"  - {pdf}")

if __name__ == "__main__":
    find_acro_open_files()
