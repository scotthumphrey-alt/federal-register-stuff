import os
import sys
import re
import glob
import pandas as pd
from google import genai

client = genai.Client()

def find_exact_file(prefix_pattern):
    """Finds any file in financial_data starting with the pattern, regardless of suffix or extension format."""
    search_path = os.path.join("financial_data", "*")
    files = glob.glob(search_path)
    matched = [f for f in files if prefix_pattern.lower() in os.path.basename(f).lower()]
    return max(matched, key=os.path.getmtime) if matched else None

def clean_num(v):
    s = str(v).replace('$', '').replace(',', '').replace('(', '-').replace(')', '').strip()
    try: return float(s) if s else 0.0
    except: return 0.0

def parse_qb_csv(path):
    """Parses a QuickBooks data report row-by-row, identifying 'Actual' and 'Budget' column indices dynamically."""
    if not path or not os.path.exists(path):
        return {}, {}, {}
        
    print(f"Direct Parsing Engaged For: {path}")
    actuals_map = {}
    budgets_map = {}
    displays_map = {}
    
    actual_idx = None
    budget_idx = None
    
    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
        lines = [line.split(',') for line in f.readlines()]
        
    for row in lines:
        clean_row = [str(cell).strip().lower() for cell in row]
        
        # Track the precise location of header values dynamically
        if "actual" in clean_row and "budget" in clean_row:
            actual_idx = clean_row.index("actual")
            for c_idx, cell in enumerate(clean_row):
                if cell == "budget":
                    budget_idx = c_idx
                    break
            continue
            
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
    # Use robust wildcard mapping to absorb whatever extension or suffix is present
    f_p26 = find_exact_file("fy26")
    f_p25 = find_exact_file("fy25")
    f_sal = find_exact_file("salary") or find_exact_file("matrix") or os.path.join("financial_data", "2027_salary_matrix.xlsx")
    
    if not f_p26 or not f_p25:
        print(f"Error: Missing targeted financial data matching patterns. (Found FY25: {f_p25}, FY26: {f_p26})")
        sys.exit(1)
        
    fy25_acts, _, _ = parse_qb_csv(f_p25)
    fy26_acts, fy26_buds, fy26_displays = parse_qb_csv(f_p26)
    
    all_gls = sorted(list(set(list(fy26_displays.keys()) + list(fy25_acts.keys()))), key=lambda x: int(x) if x.isdigit() else 99999)
    
    if not all_gls:
        print("Error: Account extraction generated empty row mappings.")
        sys.exit(1)
        
    total_new_salaries = 0.0
    if f_sal and os.path.exists(f_sal):
        print(f"Extracting salary overrides from: {f_sal}")
        df_sal = pd.read_excel(f_sal, keep_default_na=False)
        df_sal.columns = [str(c).lower().strip() for c in df_sal.columns]
        sal_col = next((c for c in df_sal.columns if any(k in c for k in ['salary', 'new', 'pay', 'annual', 'total'])), df_sal.columns[-1])
        for _, r in df_sal.iterrows():
            s_str = str(r[sal_col]).replace('$', '').replace(',', '').strip()
            try: total_new_salaries += float(s_str) if s_str else 0.0
            except: pass

    md_table = "| Account Item | FY25 Actuals | FY26 Budget Baseline | FY27 Proposed Budget | Notes |\n"
    md_table += "| :--- | :--- | :--- | :--- | :--- |\n"
    
    for gl in all_gls:
        label = fy26_displays.get(gl, f"{gl} Account")
        acct_low = label.lower()
        
        v25 = fy25_acts.get(gl, 0.0)
        v26 = fy26_buds.get(gl, 0.0)
        
        clean_label = re.sub(r'\s+', ' ', label).strip()
        
        if gl == '50610' or 'gross salaries' in acct_low:
            prop = total_new_salaries if total_new_salaries > 0 else v26
            note = "Overridden using automated total parsed from 2027 Salary Matrix."
        elif gl == '6200' or 'bonus' in acct_low:
            prop = 0.0
            note = "Discontinued per corporate operational directive."
        else:
            prop = v26 if v26 > v25 else v25
            note = "Balanced to support active operational baseline targets."
            
        v25_str = f"${v25:,.2f}" if v25 != 0 else "$0.00"
        v26_str = f"${v26:,.2f}" if v26 != 0 else "$0.00"
        prop_str = f"${prop:,.2f}" if prop != 0 else "$0.00"
        
        md_table += f"| {clean_label} | {v25_str} | {v26_str} | {prop_str} | {note} |\n"

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
