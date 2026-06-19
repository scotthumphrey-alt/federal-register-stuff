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

def parse_financial_sheet(path, target_col_idx):
    if not path or not os.path.exists(path):
        return pd.DataFrame(columns=['account', 'value', 'is_header'])
        
    print(f"Parsing File: {path}")
    df_raw = pd.read_excel(path, header=None).fillna("") if path.endswith(('.xlsx', '.xls')) else pd.read_csv(path, header=None).fillna("")
    
    header_idx = 0
    for idx, row in df_raw.iterrows():
        row_str = " ".join([str(val).lower() for val in row])
        if ("actual" in row_str and "budget" in row_str) or ("accounts" in row_str and "totals" in row_str):
            header_idx = idx
            break
            
    df = pd.read_excel(path, skiprows=header_idx, keep_default_na=False) if path.endswith(('.xlsx', '.xls')) else pd.read_csv(path, skiprows=header_idx, keep_default_na=False)
    
    acct_col = df.columns[0]
    # Grab column explicitly by its absolute numerical positional index position
    val_col = df.columns[target_col_idx] if len(df.columns) > target_col_idx else df.columns[1]

    print(f"File Mapped -> Account Column: [{acct_col}] | Selected Data Column: [{val_col}]")

    rows = []
    for _, r in df.iterrows():
        label = str(r[acct_col]).strip()
        if not label or any(k in label.lower() for k in ['income after', 'gross profit', 'guidelines', 'marine exchange', 'gmt', 'july', 'june', 'accounting', 'total income', 'total expenses', 'total expense']):
            continue
            
        raw_val = str(r[val_col]).strip()
        has_gl_code = bool(re.match(r'^\d+', label))
        
        def clean_num(v):
            s = str(v).replace('$', '').replace(',', '').replace('(', '-').replace(')', '').strip()
            try: return float(s) if s else 0.0
            except: return 0.0
            
        cleaned_val = clean_num(raw_val)
        is_header = not has_gl_code and (cleaned_val == 0.0 or raw_val == "")
        
        rows.append({
            'account': label, 
            'value': 0.0 if is_header else cleaned_val,
            'is_header': is_header
        })
        
    return pd.DataFrame(rows)

def main():
    f_b26 = find_file("26")
    f_p25 = find_file("25")
    f_sal = find_file("salary") or find_file("matrix")
    
    # Force exact column slot indexing positions 
    # Consolidated template has data in column slot 1. Budget vs Actuals has Actual in slot 1.
    df_26 = parse_financial_sheet(f_b26, 1)
    df_25 = parse_financial_sheet(f_p25, 1)
    
    if df_26.empty and df_25.empty:
        print("Error: Component data frames are empty.")
        sys.exit(1)
        
    df_26 = df_26.rename(columns={'value': 'v26', 'is_header': 'h26'})
    df_25 = df_25.rename(columns={'value': 'v25', 'is_header': 'h25'})
    
    master = pd.merge(df_26, df_25, on='account', how='outer').fillna({'v26': 0.0, 'v25': 0.0, 'h26': True, 'h25': True})
    master['is_header'] = master['h26'] & master['h25']

    total_new_salaries = 0.0
    if f_sal:
        df_sal = pd.read_excel(f_sal, keep_default_na=False) if f_sal.endswith(('.xlsx', '.xls')) else pd.read_csv(f_sal, keep_default_na=False)
        df_sal.columns = [str(c).lower().strip() for c in df_sal.columns]
        sal_col = next((c for c in df_sal.columns if any(k in c for k in ['salary', 'new', 'pay', 'annual', 'total'])), df_sal.columns[-1])
        for _, r in df_sal.iterrows():
            s_str = str(r[sal_col]).replace('$', '').replace(',', '').strip()
            try: total_new_salaries += float(s_str) if s_str else 0.0
            except: pass

    md_table = "| Account Item | FY25 Actuals | FY26 Budget Baseline | FY27 Proposed Budget | Notes |\n"
    md_table += "| :--- | :--- | :--- | :--- | :--- |\n"
    
    for _, r in master.iterrows():
        label = r['account']
        acct_low = label.lower()
        
        if r['is_header'] or (any(k in acct_low for k in ['income', 'expense', 'assets', 'liabilities']) and not bool(re.match(r'^\d+', label))):
            md_table += f"| **{label}** | | | | Structural Group Header |\n"
            continue
            
        if '50610' in acct_low or 'gross salaries' in acct_low:
            prop = total_new_salaries if total_new_salaries > 0 else r['v26']
            note = f"Overridden using automated total parsed from 2027 Salary Matrix."
        elif 'bonus' in acct_low or '6200' in acct_low:
            prop = 0.0
            note = "Discontinued per corporate operational directive."
        else:
            v26 = r['v26']
            v25 = r['v25']
            prop = v26 if v26 > v25 else v25
            note = "Balanced to support active operational baseline targets."
            
        v25_str = f"${r['v25']:,.2f}" if r['v25'] != 0 else "$0.00"
        v26_str = f"${r['v26']:,.2f}" if r['v26'] != 0 else "$0.00"
        prop_str = f"${prop:,.2f}" if prop != 0 else "$0.00"
        
        md_table += f"| {label} | {v25_str} | {v26_str} | {prop_str} | {note} |\n"

    summary_prompt = f"Write a professional 3-sentence CFO executive summary review for this upcoming fiscal year budget proposal:\n\n{md_table}"
    try:
        response = client.models.generate_content(model='gemini-2.5-flash', contents=summary_prompt)
        analysis_text = response.text
    except Exception:
        analysis_text = "Budget matrix generated successfully by local automation script engine."

    final_report = f"# FY2027 Recommended Fiscal Budget Proposal\n\n## Executive Analysis Summary\n{analysis_text}\n\n## Budget Comparison Matrix\n\n{md_table}"
    
    with open("budget_proposal_fy27.md", "w", encoding="utf-8") as f:
        f.write(final_report)
    s_env = os.environ.get('GITHUB_STEP_SUMMARY')
    if s_env:
        with open(s_env, "w", encoding="utf-8") as f:
            f.write(final_report)

if __name__ == "__main__":
    main()
