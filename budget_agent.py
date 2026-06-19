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

def main():
    f_master = find_file("Budget_FY26_P&L")
    f_sal = find_file("salary") or find_file("matrix")
    
    if not f_master:
        print("Error: Could not find the core Budget_FY26_P&L source data file.")
        sys.exit(1)
        
    print(f"Loading Source Foundation: {f_master}")
    df_raw = pd.read_excel(f_master, header=None).fillna("") if f_master.endswith(('.xlsx', '.xls')) else pd.read_csv(f_master, header=None).fillna("")
    
    # Locate where the actual QuickBooks account columns begin
    header_idx = 0
    for idx, row in df_raw.iterrows():
        row_str = " ".join([str(v).lower() for v in row])
        if "accounts" in row_str or "budget" in row_str:
            header_idx = idx
            break
            
    df = pd.read_excel(f_master, skiprows=header_idx, keep_default_na=False) if f_master.endswith(('.xlsx', '.xls')) else pd.read_csv(f_master, skiprows=header_idx, keep_default_na=False)
    
    # Load personnel configurations from your separate Salary Matrix file
    total_new_salaries = 0.0
    if f_sal:
        print(f"Loading Salary Matrix Reference: {f_sal}")
        df_sal = pd.read_excel(f_sal, keep_default_na=False) if f_sal.endswith(('.xlsx', '.xls')) else pd.read_csv(f_sal, keep_default_na=False)
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
        
        # Read the baseline value from the template column
        v26 = clean_num(r.iloc[1])
        
        # Format structural grouping rows cleanly
        if gl == "" and v26 == 0.0:
            md_table += f"| **{re.sub(r's+', ' ', label).strip()}** | | | Structural Group Header |\n"
            continue
            
        # Core operational budget routing logic
        if gl == '50610' or 'gross salaries' in acct_low:
            prop = total_new_salaries if total_new_salaries > 0 else v26
            note = "Overridden using automated total parsed from 2027 Salary Matrix."
        elif gl == '6200' or 'bonus' in acct_low:
            prop = 0.0
            note = "Discontinued per corporate operational directive."
        else:
            # Baseline target preservation mapping
            prop = v26
            note = "Carried forward to preserve baseline operational parameters."
            
        v26_str = f"${v26:,.2f}" if v26 != 0 else "$0.00"
        prop_str = f"${prop:,.2f}" if prop != 0 else "$0.00"
        display_label = re.sub(r'\s+', ' ', label).strip()
        
        md_table += f"| {display_label} | {v26_str} | {prop_str} | {note} |\n"

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
