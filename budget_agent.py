import os
import sys
import re
import pandas as pd
from google import genai

client = genai.Client()

def clean_num(v):
    s = str(v).replace('$', '').replace(',', '').replace('(', '-').replace(')', '').strip()
    try: return float(s) if s else 0.0
    except: return 0.0

def main():
    # ABSOLUTE HARDCODED PATHS: Prevents the script from reading zero-value files
    f_master = os.path.join("financial_data", "Budget_FY26_P&L.xlsx - Consolidated.csv")
    f_sal = os.path.join("financial_data", "2027_salary_matrix.xlsx")
    
    if not os.path.exists(f_master):
        print(f"Error: Missing core reference data sheet path at: {f_master}")
        sys.exit(1)
        
    print(f"Successfully connected to core data file: {f_master}")
    df_raw = pd.read_csv(f_master, header=None).fillna("")
    
    # Locate the start of the account tables explicitly
    header_idx = 0
    for idx, row in df_raw.iterrows():
        row_str = " ".join([str(v).lower() for v in row])
        if "accounts" in row_str or "budget" in row_str or "total" in row_str:
            header_idx = idx
            break
            
    df = pd.read_csv(f_master, skiprows=header_idx, keep_default_na=False)
    
    # Parse human capital baseline adjustments
    total_new_salaries = 0.0
    if os.path.exists(f_sal):
        print(f"Processing personnel adjustments from matrix: {f_sal}")
        df_sal = pd.read_excel(f_sal, keep_default_na=False)
        df_sal.columns = [str(c).lower().strip() for c in df_sal.columns]
        sal_col = next((c for c in df_sal.columns if any(k in c for k in ['salary', 'new', 'pay', 'annual', 'total'])), df_sal.columns[-1])
        for _, r in df_sal.iterrows():
            s_str = str(r[sal_col]).replace('$', '').replace(',', '').strip()
            try: total_new_salaries += float(s_str) if s_str else 0.0
            except: pass

    md_table = "| Account Item | FY26 Budget Baseline | FY27 Proposed Budget | Notes |\n"
    md_table += "| :--- | :--- | :--- | :--- |\n"
    
    for _, r in df.iterrows():
        label = str(r.iloc[0]).strip()
        if not label or any(k in label.lower() for k in ['total income', 'total expense', 'gross profit', 'net income', 'net operating', 'company name', 'budget name']):
            continue
            
        gl_match = re.search(r'\d+', label)
        gl = gl_match.group(0) if gl_match else ""
        acct_low = label.lower()
        
        v26 = clean_num(r.iloc[1]) if len(r) > 1 else 0.0
        
        # FIX: Normalize spacing outside the f-string block to eliminate backslash syntax errors
        clean_label = re.sub(r'\s+', ' ', label).strip()
        
        if gl == "" and v26 == 0.0:
            md_table += f"| **{clean_label}** | | | Structural Group Header |\n"
            continue
            
        # Corporate baseline allocation policies
        if gl == '50610' or 'gross salaries' in acct_low:
            prop = total_new_salaries if total
