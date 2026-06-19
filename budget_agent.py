import os
import glob
import sys
import re
import pandas as pd
from google import genai

client = genai.Client()

def find_file(pattern):
    search_path = os.path.join("financial_data", "*")
    files = glob.glob(search_path)
    matched_files = [f for f in files if pattern.lower() in os.path.basename(f).lower()]
    return max(matched_files, key=os.path.getmtime) if matched_files else None

def clean_num(v):
    s = str(v).replace('$', '').replace(',', '').replace('(', '-').replace(')', '').strip()
    try: return float(s) if s else 0.0
    except: return 0.0

def parse_qb_csv(path):
    """Parses a QuickBooks CSV row by row dynamically finding column indices without using rigid skiprows."""
    if not path or not os.path.exists(path):
        return {}, {}, {}
        
    print(f"Parsing File: {path}")
    
    actuals_map = {}
    budgets_map = {}
    displays_map = {}
    
    actual_idx = None
    budget_idx = None
    
    # Read raw lines to completely avoid multi-header format fragmentation
    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
        lines = [line.split(',') for line in f.readlines()]
        
    for idx, row in enumerate(lines):
        clean_row = [str(cell).strip().lower() for cell in row]
        
        # Detect the true header row
        if "actual" in clean_row and "budget" in clean_row:
            actual_idx = clean_row.index("actual")
            # Pull the first occurrence of "budget", skipping metrics like "% of budget"
            for c_idx, cell in enumerate(clean_row):
                if cell == "budget":
                    budget_idx = c_idx
                    break
            continue
            
        # Once columns are mapped, extract data lines starting with GL codes
        if actual_idx is not None and budget_idx is not None:
            if len(row) == 0:
                continue
            label = str(row[0]).strip()
            if not label or any(k in label.lower() for k in ['total income', 'total expense', 'gross profit', 'net income', 'net operating']):
                continue
                
            gl_match = re.search(r'^\s*(\d+)', label)
            if gl_match:
                gl = gl_match.group(1)
                act_val = row[actual_idx] if actual_idx < len(row) else "0"
                bud_val = row[budget_idx] if budget_idx < len(row) else "0"
                
                actuals_map[gl] = clean_num(act_val)
                budgets_map[gl] = clean_num(bud_val)
                displays_map[gl] = re.sub(r'\s+', ' ', label).strip()
                
    return actuals_map, budgets_map, displays_map

def main():
    f_p26 = find_file("FY26+PL")
    f_p25 = find_file("FY25+PL")
    f_sal = find_file("salary") or find_file("matrix")
    
    if not f_p26 or not f_p25:
        print(f"Error: Missing required financial data sheets. (Found FY25: {f_p25}, FY26: {f_p26})")
        sys.exit(1)
        
    # Extract structural maps row-by-row
    fy25_acts, _, _ = parse_qb_csv(f_p25)
    fy26_acts, fy26_buds, fy26_displays = parse_qb_csv(f_p26)
    
    # Establish master unique account baseline indices
    all_gls = sorted(list(set(list(fy26_displays.keys()) + list(fy25_acts.keys()))), key=lambda x: int(x) if x.isdigit() else 99999)
    
    if not all_gls:
        print("Error: Matrix array generation halted. Account extraction generated empty row mappings.")
        sys.exit(1)
        
    # Parse Salary Matrix Reference
    total_new_salaries = 0.0
    if f_sal:
        df_sal = pd.read_excel(f_sal, keep_default_na=False) if f_sal.endswith(('.xlsx', '.xls')) else pd.read_csv(f_sal, keep_default_na=False)
        df_sal.columns = [str(c).lower().strip() for c in df_sal.columns]
        sal_col = next((c for c in df_sal.columns if any(k in c for k in ['salary', 'new', 'pay', 'annual', 'total'])), df_sal.columns[-1])
        for _, r in df_sal.iterrows():
            s_str = str(r[sal_col]).replace('$', '').replace(',', '').strip()
            try: total_new_salaries += float(s_str) if s_str else 0.0
            except: pass

    md_table = "| Account Item | FY25 Actuals | FY26 Budget
