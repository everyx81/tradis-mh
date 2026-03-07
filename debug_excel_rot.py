import win32com.client
import pythoncom
import os

def check_excel_rot():
    print("--- Excel ROT Scan Start ---")
    excel_instances = []
    try:
        context = pythoncom.CreateBindCtx(0)
        rot = pythoncom.GetRunningObjectTable()
        for mon in rot.EnumRunning():
            name = mon.GetDisplayName(context, mon)
            if "Excel" in name or ".xls" in name.lower() or ".csv" in name.lower():
                print(f"Found Moniker: {name}")
                obj = rot.GetObject(mon)
                try:
                    app = getattr(obj, "Application", obj)
                    if app not in excel_instances:
                        excel_instances.append(app)
                except Exception as e:
                    print(f"Error binding to instance: {e}")
    except Exception as e:
        print(f"ROT Scan Error: {e}")

    print(f"\nTotal Excel Instances Found: {len(excel_instances)}")
    
    for i, app in enumerate(excel_instances):
        try:
            app_disp = win32com.client.Dispatch(app)
            print(f"\nInstance {i+1} Workbooks:")
            for wb in app_disp.Workbooks:
                print(f" - Name: {wb.Name} (Full: {wb.FullName})")
        except Exception as e:
            print(f"Error accessing instance {i+1}: {e}")
    print("\n--- Scan End ---")

if __name__ == "__main__":
    check_excel_rot()
