import os
import glob
import sys
import pandas as pd
from google import genai

client = genai.Client()

def find_file(pattern):
    """Scans financial_data folder using case-insensitive partial keyword matching."""
    search_path = os.path.join("financial_data", "*")
    files = glob.glob(search_path)
    # Check if the keyword pattern exists anywhere inside the filename string (lowercased)
    matched_files = [f for f in files if pattern.lower() in os.path.basename(f).lower()]
    return max(matched_files, key=os.path.getmtime) if matched_files else None

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
    # Broad partial keyword patterns to look through regardless of special characters (+ or _)
    f_b26 = find_file("26")
    f_p25 = find_file("25")
    f_sal = find_file("salary") or find_file("matrix")
    
    print(f"Matched File Paths -> FY25: {f_p25} | FY26: {f_b26} | Salary: {f_sal}")
    
    if not f_b26 and not f_p25:
        print("Error: Could not locate any matching data sheets in financial_data/ folder.")
        sys.exit(1)
        
    df_26 = parse_financial_sheet(f_b26)
    df_25 = parse_financial_sheet(f_p25)
        
    # Merge using outer join to preserve every single account name and structural group header string
    if not df_26.empty and not df_25.empty:
        master = pd.merge(df_26, df_25, on='account', how='outer').fillna({'value_26': 0.0, 'value_25': 0.0, 'is_header_26': True, 'is_header_25': True})
        master['is_header'] = master['is_header_x'] & master['is_header_y']
        master = master.rename(columns={'value_x': 'v26', 'value_y': 'v25'})
    elif not df_26.empty:
        master = df_26.rename(columns={'value': 'v26'})
        master['v25'] = 0.0
    else:
        master = df_25.rename(columns={'value': 'v25'})
        master['v26'] = 0.0
        master['is_header'] = master['is_header']
    
    total_new_salaries = 0.0
    if f_sal:
        df_sal = pd.read_excel(f_sal, keep_default_na=False) if f_sal.endswith(('.xlsx', '.xls')) else pd.read_csv(f_sal, keep_default_na=False)
        df_sal.columns = [str(c).lower().strip() for c in df_sal.columns]
        sal_col = next((c for c in df_sal.columns if any(k in c for k in ['salary', 'new', 'pay', 'annual', 'total'])), df_sal.columns[-1])
        for _, r in df_sal.iterrows():
            s_str = str(r[sal_col]).replace('$', '').replace(',', '').strip()
            try: total_new_salaries += float(s_str) if s_str else 0.0
            except: pass

    # Build matrix arrays row-by-row
    md_table = "| Account Item | FY25 Actuals | FY26 Budget Baseline | FY27 Proposed Budget | Notes |\n"
    md_table += "| :--- | :--- | :--- | :--- | :--- |\n"
    
    for _, r in master.iterrows():
        label = r['account']
        acct_low = label.lower()
        
        # If it's a structural group header, print it in bold text and leave numbers blank
        if r.get('is_header', False) or (any(k in acct_low for k in ['income', 'expense', 'assets', 'liabilities']) and not any(num in acct_low for num in ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9'])):
            md_table += f"| **{label}** | | | | Structural Group Header |\n"
            continue
            
        # Match payroll logic overrides
        if any(k in acct_low for k in ['salary', 'wages', '6100', 'payroll']):
            prop = total_new_salaries if total_new_salaries > 0 else r['v26']
            note = "Derived from 2027 Salary Matrix adjustments." if total_new_salaries > 0 else "Carried active target forward."
        elif 'bonus' in acct_low or '6200' in acct_low:
            prop = 0.0
            note = "Discontinued per corporate operational directive."
        else:
            prop = r['v26'] if r['v26'] > r['v25'] else r['v25']
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
