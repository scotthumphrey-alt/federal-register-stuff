import os
import glob
import sys
import pandas as pd

def find_file(pattern):
    search_path = os.path.join("financial_data", f"*{pattern}*")
    files = glob.glob(search_path)
    return max(files, key=os.path.getmtime) if files else None

def main():
    f24 = find_file("24")
    f26 = find_file("26")
    
    print("\n========================================================")
    print("        RAW SPREADSHEET STRUCTURAL DIAGNOSTIC           ")
    print("========================================================\n")
    
    for label, filepath in [("FY24 FILE", f24), ("FY26 FILE", f26)]:
        if not filepath:
            print(f"[!] {label}: Missing or not found in folder.")
            continue
            
        print(f"\n>>> PRINTING TOP 20 RAW ROWS FOR: {filepath} <<<")
        try:
            # Read absolute raw layout completely ignoring headers
            df_raw = pd.read_excel(filepath, header=None).fillna("[EMPTY]")
            
            # Print the first 20 rows of the sheet with structural column indexes
            for idx, row in df_raw.head(20).iterrows():
                row_items = [f"Col{i}: '{str(val).strip()}'" for i, val in enumerate(row)]
                print(f"Row {idx:02d} -> " + " | ".join(row_items))
        except Exception as e:
            print(f"Error reading {filepath}: {e}")
            
    print("\n========================================================")
    sys.exit(1) # Intentionally halt the run here so you can look at the log printout

if __name__ == "__main__":
    main()
