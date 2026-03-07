import win32com.client
import pythoncom
import os
import time

def try_close_excel_individual():
    print("--- Excel Individual Close Test Start ---")
    pythoncom.CoInitialize()
    targets = ["lot_304", "lot_303"] # 테스트용 타겟
    
    try:
        context = pythoncom.CreateBindCtx(0)
        rot = pythoncom.GetRunningObjectTable()
        for mon in rot.EnumRunning():
            try:
                name = mon.GetDisplayName(context, mon)
                low_name = name.lower()
                if any(ext in low_name for ext in ['.xls', '.xlsx', '.xlsm', '.csv']):
                    base_name = os.path.splitext(os.path.basename(low_name))[0]
                    print(f"Checking: {base_name}")
                    
                    matched = False
                    for t in targets:
                        if t in base_name:
                            matched = True
                            break
                    
                    if matched:
                        print(f"Target Matched: {name}. Attempting to close...")
                        obj = rot.GetObject(mon)
                        # 방식 1: Dynamic Dispatch
                        try:
                            from win32com.client import dynamic
                            wb = dynamic.Dispatch(obj)
                            print(f"  [Method 1] Close call for {wb.Name}")
                            wb.Close(False)
                            print("  [Method 1] Success")
                            continue
                        except Exception as e:
                            print(f"  [Method 1] Failed: {e}")
                            
                        # 방식 2: Raw IDispatch invoke
                        try:
                            # 0 is the DISPID for Close in Excel Workbook usually, or use name
                            print("  [Method 2] Raw Invoke Close")
                            # This is complex in Python, trying Dispatch again with more care
                            wb = win32com.client.Dispatch(obj.QueryInterface(pythoncom.IID_IDispatch))
                            wb.Close(False)
                            print("  [Method 2] Success")
                        except Exception as e:
                            print(f"  [Method 2] Failed: {e}")
            except Exception as e:
                print(f"Error in Enum: {e}")
                continue
    finally:
        pythoncom.CoUninitialize()
    print("--- Test End ---")

if __name__ == "__main__":
    try_close_excel_individual()
