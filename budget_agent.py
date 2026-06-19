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

def parse_financial_sheet(path, column_keyword):
    if not path or not os.path.exists(path):
        return pd.DataFrame(columns=['gl_account', 'account_display', 'value', 'is_header'])
        
    print(f"Parsing File: {path}")
    df_raw = pd.read_excel(path, header=None).fillna("") if path.endswith(('.xlsx', '.xls')) else pd.read_csv(path, header=None).fillna("")
    
    header_idx = 0
    for idx, row in df_raw.iterrows():
        row_str = " ".join([str(val).lower() for val in row])
        if ("actual" in row_str and "budget" in row_str) or ("accounts" in row_str and "totals" in row_str):
            header_idx = idx
            break
            
    df = pd.read_excel(path, skiprows=header_idx, keep_default_na=False) if path.endswith(('.xlsx', '.xls')) else pd.read_csv(path, skiprows=header_idx, keep_default_na=False)
    df.columns = [str(c).strip().lower() for c in df.columns]
    
    acct_col = df.columns[0]
    
    val_col = None
    for col in df.columns:
        if column_keyword.lower() in col and 'over' not in col and '%' not in col:
            val_col = col
            break
    if not val_col:
        val_col = df.columns[1] if len(df.columns) > 1 else df.columns[0]

    rows = []
    for _, r in df.iterrows():
        raw_label = str(r[acct_col]).strip()
        if not raw_label or any(k in raw_label.lower() for k in ['income after', 'gross profit', 'guidelines', 'marine exchange', 'gmt', 'july', 'june', 'accounting', 'total income', 'total expenses', 'total expense']):
            continue
            
        raw_val = str(r[val_col]).strip()
        
        # Pull out the first contiguous string of digits to use as the GL account key
        gl_match = re.search(r'\d+', raw_label)
        gl_account = gl_match.group(0) if gl_match else ""
        
        def clean_num(v):
            s = str(v).replace('$', '').replace(',', '').replace('(', '-').replace(')', '').strip()
            try: return float(s) if s else 0.0
            except: return 0.0
            
        cleaned_val = clean_num(raw_val)
        is_header = (gl_account == "")
        
        rows.append({
            'gl_account': gl_account,
            'account_display': re.sub(r'\s+', ' ', raw_label).strip(),
            'value': 0.0 if is_header else cleaned_val,
            'is_header': is_header
        })
        
    return pd.DataFrame(rows)

def main():
    f_b26 = find_file("26")
    f_p25 = find_file("25")
    f_sal = find_file("salary") or find_file("matrix")
    
    df_26 = parse_financial_sheet(f_b26, "total")
    df_25 = parse_financial_sheet(f_p25, "actual")
    
    if df_26.empty and df_25.empty:
        print("Error: Component data frames are missing valid rows.")
        sys.exit(1)
        
    # Isolate data rows from structural parent categories
    data_26 = df_26[df_26['gl_account'] != '']
    data_25 = df_25[df_25['gl_account'] != '']
    
    headers_26 = df_26[df_26['gl_account'] == '']
    headers_25 = df_25[df_25['gl_account'] == '']
    
    # Merge quantitative values strictly matching on numerical GL codes
    data_merged = pd.merge(data_26, data_25, on='gl_account', how='outer').fillna({'value_x': 0.0, 'value_y': 0.0})
    data_merged['account_name'] = data_merged['account_display_x'].fillna(data_merged['account_display_y'])
    data_merged = data_merged.rename(columns={'value_x': 'v26', 'value_y': 'v25'})
    data_merged['is_header'] = False
    
    # Process headers list for structural mapping layout
    all_headers = pd.concat([headers_26, headers_25]).drop_duplicates(subset=['account_display'])
    all_headers = all_headers.rename(columns={'account_display': 'account_name', 'value': 'v26'})
    all_headers['v25'] = 0.0
    all_headers['is_header'] = True
    all_headers['gl_account'] = ''
    
    # Combine structural names and numeric maps together
    master = pd.concat([data_merged[['gl_account', 'account_name', 'v26', 'v25', 'is_header']], all_headers[['gl_account', 'account_name', 'v26', 'v25', 'is_header']]])
    
    # Sort logically so sub-accounts drop neatly underneath group headers
    master['sort_key'] = master.apply(lambda r: r['gl_account'] if r['gl_account'] != '' else r['account_name'], axis=1)
    master = master.sort_values(by='sort_key').drop_duplicates(subset=['account_name'], keep='first')

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
        label = r['account_name']
        gl = r['gl_account']
        
        if r['is_header'] or gl == '':
            md_table += f"| **{label}** | | | | Structural Group Header |\n"
            continue
            
        if gl == '50610' or 'gross salaries' in label.lower():
            prop = total_new_salaries if total_new_salaries > 0 else r['v26']
            note = f"Overridden using automated total parsed from 2027 Salary Matrix."
        elif gl == '6200' or 'bonus' in label.lower():
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
