import win32com.client
import pythoncom
import os

def test_single_excel_close(target_keyword):
    print(f"--- Single Excel Close Test ({target_keyword}) ---")
    pythoncom.CoInitialize()
    try:
        context = pythoncom.CreateBindCtx(0)
        rot = pythoncom.GetRunningObjectTable()
        found_and_closed = False
        
        for mon in rot.EnumRunning():
            try:
                name = mon.GetDisplayName(context, mon)
                low_name = name.lower()
                if any(ext in low_name for ext in ['.xls', '.xlsx', '.xlsm', '.csv']):
                    if target_keyword.lower() in low_name:
                        print(f"Target Found: {name}")
                        unk = rot.GetObject(mon)
                        disp = unk.QueryInterface(pythoncom.IID_IDispatch)
                        wb = win32com.client.Dispatch(disp)
                        
                        print(f"Closing {wb.Name}...")
                        wb.Close(False)
                        print("Successfully closed.")
                        found_and_closed = True
                        break
            except Exception as e:
                print(f"Error: {e}")
                continue
        
        if not found_and_closed:
            print("Target not found in ROT.")
            
    finally:
        pythoncom.CoUninitialize()
    print("--- Test End ---")

if __name__ == "__main__":
    # 사용자 환경의 3개 파일 중 하나(Lot_304)를 대상으로 테스트
    test_single_excel_close("Lot_304")
