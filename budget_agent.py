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

def parse_financial_sheet(path):
    if not path or not os.path.exists(path):
        return pd.DataFrame(columns=['account', 'value', 'is_header'])
        
    print(f"Parsing File: {path}")
    df_raw = pd.read_excel(path, header=None).fillna("") if path.endswith(('.xlsx', '.xls')) else pd.read_csv(path, header=None).fillna("")
    
    # Locate where the data row headers live
    header_idx = 0
    for idx, row in df_raw.iterrows():
        row_str = " ".join([str(val).lower() for val in row])
        if any(k in row_str for k in ["actual", "budget", "totals", "amount"]):
            header_idx = idx
            break
            
    df = pd.read_excel(path, skiprows=header_idx, keep_default_na=False) if path.endswith(('.xlsx', '.xls')) else pd.read_csv(path, skiprows=header_idx, keep_default_na=False)
    df.columns = [str(c).strip().lower() for c in df.columns]
    
    acct_col = df.columns[0]
    
    # Grab the target budget column preferentially
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
        
        # Completely drop footer timestamps, metadata system logs, or summary dividers
        if not label or any(k in label.lower() for k in ['income after', 'gross profit', 'guidelines', 'marine exchange', 'basis', 'gmt', 'july', 'june', 'accounting']):
            continue
            
        raw_val = str(r[val_col]).strip()
        
        # STRICT DESIGNATION RULE: If it starts with an accounting GL code digit, it is an active data row
        has_gl_code = bool(re.match(r'^\d+', label))
        
        # If it has a real numeric value assigned, it is also a data row
        def clean_num(v):
            s = str(v).replace('$', '').replace(',', '').replace('(', '-').replace(')', '').strip()
            try: return float(s) if s else 0.0
            except: return None
            
        cleaned_val = clean_num(raw_val)
        
        # It's a header only if it lacks a GL code and contains no direct valid numeric input values
        is_header = not has_gl_code and (cleaned_val is None or raw_val == "" or cleaned_val == 0.0)
        
        rows.append({
            'account': label, 
            'value': 0.0 if is_header else (cleaned_val if cleaned_val is not None else 0.0),
            'is_header': is_header
        })
        
    return pd.DataFrame(rows)

def main():
    f_b26 = find_file("26")
    f_p25 = find_file("25")
    f_sal = find_file("salary") or find_file("matrix")
    
    print(f"Matched Paths -> FY25: {f_p25} | FY26: {f_b26} | Salary: {f_sal}")
    
    df_26 = parse_financial_sheet(f_b26)
    df_25 = parse_financial_sheet(f_p25)
    
    if df_26.empty and df_25.empty:
        print("Error: Empty account sets produced.")
        sys.exit(1)
        
    # Align rows side by side cleanly
    if not df_26.empty and not df_25.empty:
        master = pd.merge(df_26, df_25, on='account', how='outer').fillna({'value_x': 0.0, 'value_y': 0.0, 'is_header_x': True, 'is_header_y': True})
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

    md_table = "| Account Item | FY25 Actuals | FY26 Budget Baseline | FY27 Proposed Budget | Notes |\n"
    md_table += "| :--- | :--- | :--- | :--- | :--- |\n"
    
    for _, r in master.iterrows():
        label = r['account']
        acct_low = label.lower()
        
        # Check explicit formatting rules for structural headers versus numerical items
        if r.get('is_header', False) or (any(k in acct_low for k in ['income', 'expense', 'assets', 'liabilities']) and not bool(re.match(r'^\d+', label))):
            md_table += f"| **{label}** | | | | Structural Group Header |\n"
            continue
            
        # Match payroll logic rules
        if any(k in acct_low for k in ['salary', 'wages', '6100', 'payroll']):
            prop = total_new_salaries if total_new_salaries > 0 else r['v26']
            note = f"Overridden using automated total parsed from 2027 Salary Matrix." if total_new_salaries > 0 else "Carried active target forward."
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
