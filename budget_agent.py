import os
import glob
import sys
import pandas as pd
from google import genai

client = genai.Client()

def find_file(pattern):
    search_path = os.path.join("financial_data", f"*{pattern}*")
    files = glob.glob(search_path)
    return max(files, key=os.path.getmtime) if files else None

def parse_financial_sheet(path):
    if not path or not os.path.exists(path):
        return pd.DataFrame(columns=['account', 'value', 'is_header'])
        
    print(f"Reading file: {path}")
    if path.endswith(('.xlsx', '.xls')):
        df_raw = pd.read_excel(path, header=None).fillna("")
    else:
        df_raw = pd.read_csv(path, header=None).fillna("")
        
    header_idx = 0
    for idx, row in df_raw.iterrows():
        row_str = " ".join([str(val).lower() for val in row])
        if any(k in row_str for k in ["actual", "budget", "totals", "amount"]):
            header_idx = idx
            break
            
    df = pd.read_excel(path, skiprows=header_idx, keep_default_na=False) if path.endswith(('.xlsx', '.xls')) else pd.read_csv(path, skiprows=header_idx, keep_default_na=False)
    df.columns = [str(c).strip().lower() for c in df.columns]
    
    acct_col = df.columns[0]
    val_col = df.columns[1] if len(df.columns) > 1 else df.columns[0]
    for col in df.columns:
        if 'budget' in col and 'over' not in col and '%' not in col:
            val_col = col
            break
        elif 'total' in col or 'actual' in col:
            val_col = col

    rows = []
    for _, r in df.iterrows():
        label = str(r[acct_col]).strip()
        if not label or any(k in label.lower() for k in ['income after', 'gross profit', 'guidelines', 'marine exchange']):
            continue
            
        raw_val = str(r[val_col]).strip()
        # If the value cell is totally blank or contains text rather than a number, it's a structural group header
        is_header = raw_val == "" or any(alpha in raw_val.lower() for alpha in ['a', 'b', 'c', 'e', 'r'])
        
        def clean(v):
            s = str(v).replace('$', '').replace(',', '').replace('(', '-').replace(')', '').strip()
            try: return float(s) if s else 0.0
            except: return 0.0
            
        rows.append({
            'account': label, 
            'value': 0.0 if is_header else clean(r[val_col]),
            'is_header': is_header
        })
        
    return pd.DataFrame(rows)

def main():
    f_b26 = find_file("FY26") or find_file("26")
    f_p25 = find_file("FY25") or find_file("25")
    f_sal = find_file("salary") or find_file("matrix")
    
    df_26 = parse_financial_sheet(f_b26)
    df_25 = parse_financial_sheet(f_p25)
    
    if df_26.empty and df_25.empty:
        print("Error: No data could be processed from files.")
        sys.exit(1)
        
    # Merge using an outer join to ensure every account name and header string is preserved
    master = pd.merge(df_26, df_25, on='account', how='outer').fillna({'value_26': 0.0, 'value_25': 0.0, 'is_header_26': True, 'is_header_25': True})
    
    # Resolve header status
    master['is_header'] = master['is_header_26'] & master['is_header_25']
    master = master.rename(columns={'value_26': 'v26', 'value_25': 'v25'})
    
    total_new_salaries = 0.0
    if f_sal:
        df_sal = pd.read_excel(f_sal, keep_default_na=False) if f_sal.endswith(('.xlsx', '.xls')) else pd.read_csv(f_sal, keep_default_na=False)
        df_sal.columns = [str(c).lower().strip() for c in df_sal.columns]
        sal_col = next((c for c in df_sal.columns if any(k in c for k in ['salary', 'new', 'pay', 'annual', 'total'])), df_sal.columns[-1])
        for _, r in df_sal.iterrows():
            s_str = str(r[sal_col]).replace('$', '').replace(',', '').strip()
            try: total_new_salaries += float(
