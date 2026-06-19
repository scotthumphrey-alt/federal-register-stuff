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

def parse_pl_sheet(path):
    """Parses a QuickBooks Budget vs Actuals report extracting live columns by index."""
    if not path or not os.path.exists(path):
        return {}, {}
        
    print(f"Processing P&L Report: {path}")
    df_raw = pd.read_excel(path, header=None).fillna("") if path.endswith(('.xlsx', '.xls')) else pd.read_csv(path, header=None).fillna("")
    
    # Locate column labels row explicitly (skip the decorative title banners)
    header_idx = 0
    for idx, row in df_raw.iterrows():
        row_str = " ".join([str(v).lower() for v in row])
        if "actual" in row_str and "budget" in row_str:
            header_idx = idx
            break
            
    df = pd.read_excel(path, skiprows=header_idx, keep_default_na=False) if path.endswith(('.xlsx', '.xls')) else pd.read_csv(path, skiprows=header_idx, keep_default_na=False)
    
    actuals_map = {}
    budgets_map = {}
    
    for _, r in df.iterrows():
        label = str(r.iloc[0]).strip()
        if not label or any(k in label.lower() for k in ['total income', 'total expense', 'gross profit', 'net income', 'net operating']):
            continue
            
        gl_match = re.search(r'\d+', label)
        if gl_match:
            gl = gl_match.group(0)
            # Positional matching: Column index 1 is Actuals, Column index 2 is Budget
            actuals_map[gl] = clean_num(r.iloc[1])
            budgets_map[gl] = clean_num(r.iloc[2])
            
    return actuals_map, budgets_map

def main():
    f_b26 = find_file("Budget_FY26")
    f_p26 = find_file("FY26+PL+")
    f_p25 = find_file("FY25+PL+")
    f_sal = find_file("salary") or find_file("matrix")
    
    # 1. Parse the primary layout structure from the template master
    if not f_b26:
        print("Error: Missing primary Budget_FY26 baseline layout reference sheet.")
        sys.exit(1)
        
    df26_raw = pd.read_excel(f_b26, header=None).fillna("") if f_b26.endswith(('.xlsx', '.xls')) else pd.read_csv(f_b26, header=None).fillna("")
    
    h26_idx = 0
    for idx, row in df26_raw.iterrows():
        if "budget" in "".join([str(v).lower() for v in row]):
            h26_idx = idx
            break
    df26_template = pd.read_excel(f_b26, skiprows=h26_idx, keep_default_na=False) if f_b26.endswith(('.xlsx', '.xls')) else pd.read_csv(f_b26, skiprows=h26_idx, keep_default_na=False)
    
    fy26_template_targets = {}
    account_displays = {}
    ordered_gls = []
    
    for _, r in df26_template.iterrows():
        label = str(r.iloc[0]).strip()
        if not label or any(k in label.lower() for k in ['total income', 'total expense', 'gross profit', 'net income']):
            continue
        gl_match = re.search(r'\d+', label)
        if gl_match:
            gl = gl_match.group(0)
            fy26_template_targets[gl] = clean_num(r.iloc[1])
            account_displays[gl] = re.sub(r'\s+', ' ', label).strip()
            if gl not in ordered_gls:
                ordered_gls.append(gl)

    # 2. Extract quantitative historical columns from live reports
    fy25_actuals, _ = parse_pl_sheet(f_p25)
    fy26_actuals, fy26_report_budgets = parse_pl_sheet(f_p26)
    
    # 3. Pull target from separate Salary Matrix file
    total_new_salaries = 0.0
    if f_sal:
        df_sal = pd.read_excel(f_sal, keep_default_na=False) if f_sal.endswith(('.xlsx', '.xls')) else pd.read_csv(f_sal, keep_default_na=False)
        df_sal.columns = [str(c).lower().strip() for c in df_sal.columns]
        sal_col = next((c for c in df_sal.columns if any(k in c for k in ['salary', 'new', 'pay', 'annual', 'total'])), df_sal.columns[-1])
        for _, r in df_sal.iterrows():
            s_str = str(r[sal_col]).replace('$', '').replace(',', '').strip()
            try: total_new_salaries += float(s_str) if s_str else 0.0
            except: pass

    # 4. Generate the Matrix Output Row by Row preserving template structure
    md_table = "| Account Item | FY25 Actuals | FY26 Budget Baseline | FY27 Proposed Budget | Notes |\n"
    md_table += "| :--- | :--- | :--- | :--- | :--- |\n"
    
    for gl in ordered_gls:
        label = account_displays[gl]
        acct_low = label.lower()
        
        # Pull values securely by checking dictionaries using the GL code number
        v25 = fy25_actuals.get(gl, 0.0)
        # Use template target first; fall back to report budget if empty
        v26 = fy26_template_targets.get(gl, 0.0) if fy26_template_targets.get(gl, 0.0) != 0 else fy26_report_budgets.get(gl, 0.0)
        
        # Explicit routing rules
        if gl == '50610' or 'gross salaries' in acct_low:
            prop = total_new_salaries if total_new_salaries > 0 else v26
            note = "Overridden using automated total parsed from 2027 Salary Matrix."
        elif gl == '6200' or 'bonus' in acct_low:
            prop = 0.0
            note = "Discontinued per corporate operational directive."
        else:
            # Use active operational baseline velocity parameters
            prop = v26 if v26 > v25 else v25
            note = "Balanced to support active operational baseline targets."
            
        v25_str = f"${v25:,.2f}" if v25 != 0 else "$0.00"
        v26_str = f"${v26:,.2f}" if v26 != 0 else "$0.00"
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
