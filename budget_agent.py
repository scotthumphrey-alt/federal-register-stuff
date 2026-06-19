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

def load_budget_vs_actuals(path, prefix):
    if not path or not os.path.exists(path): 
        return pd.DataFrame()
        
    print(f"Loading Report File: {path}")
    
    # Read the data, treating the 6th row (index 5) as the column labels row directly
    if path.endswith(('.xlsx', '.xls')):
        df = pd.read_excel(path, skiprows=5, keep_default_na=False)
    else:
        df = pd.read_csv(path, skiprows=5, keep_default_na=False)
        
    df.columns = [str(c).strip().lower() for c in df.columns]
    print(f"Standardized Columns: {df.columns.tolist()}")
    
    if len(df.columns) < 3:
        print("Error: Sheet column footprint is smaller than expected.")
        return pd.DataFrame()
        
    acct_col = df.columns[0]
    
    # Identify the correct column indexes explicitly from left to right positions
    # Column 0: Account Names | Column 1: Actuals | Column 2: Budget Targets
    actual_col = df.columns[1]
    budget_col = df.columns[2]

    print(f"Selected Columns -> Account Names: [{acct_col}], Actuals: [{actual_col}], Budget: [{budget_col}]")

    rows = []
    for _, r in df.iterrows():
        label = str(r[acct_col]).strip()
        if not label or any(k in label.lower() for k in ['total', 'net', 'income after', 'gross profit', 'beginning balance', 'marine exchange', 'actual', 'budget']): 
            continue
            
        def clean(v):
            s = str(v).replace('$', '').replace(',', '').replace('(', '-').replace(')', '').strip()
            try: return float(s) if s else 0.0
            except: return 0.0
            
        rows.append({
            'account': label,
            f'{prefix} Budget': clean(r[budget_col]),
            f'{prefix} Actual': clean(r[actual_col])
        })
    return pd.DataFrame(rows)

def main():
    # Target files dynamically based on your uploaded naming conventions
    f_data = find_file("Actuals") or find_file("PL") or find_file("25")
    f_sal = find_file("salary") or find_file("matrix")
    
    if not f_data:
        print("Error: Could not locate your budget file in financial_data/ folder.")
        sys.exit(1)
        
    master = load_budget_vs_actuals(f_data, "FY25")
    
    if master.empty:
        print("Error: Empty dataset generated during processing pass.")
        sys.exit(1)
        
    master['FY25 Projected Close'] = master['FY25 Actual'].round(2)
    master = master[(master['FY25 Budget'] != 0) | (master['FY25 Actual'] != 0)]
    
    total_new_salaries = 0.0
    if f_sal:
        df_sal = pd.read_excel(f_sal, keep_default_na=False) if f_sal.endswith(('.xlsx', '.xls')) else pd.read_csv(f_sal, keep_default_na=False)
        df_sal.columns = [str(c).lower().strip() for c in df_sal.columns]
        sal_col = next((c for c in df_sal.columns if any(k in c for k in ['salary', 'new', 'pay', 'annual', 'total'])), df_sal.columns[-1])
        for _, r in df_sal.iterrows():
            s_str = str(r[sal_col]).replace('$', '').replace(',', '').strip()
            try: total_new_salaries += float(s_str) if s_str else 0.0
            except: pass

    proposed_vals = []
    notes = []
    for _, r in master.iterrows():
        acct = r['account'].lower()
        
        if any(k in acct for k in ['salary', 'wages', '6100', 'payroll']):
            proposed_vals.append(total_new_salaries if total_new_salaries > 0 else r['FY25 Projected Close'])
            notes.append("Derived from 2027 Salary Matrix adjustments." if total_new_salaries > 0 else "Base runway close.")
        elif 'bonus' in acct or '6200' in acct:
            proposed_vals.append(0.0)
            notes.append("Discontinued per directive.")
        else:
            proj = r['FY25 Projected Close']
            bud = r['FY25 Budget']
            target = proj if proj > bud else bud
            proposed_vals.append(round(target, 2))
            notes.append("Balanced to support ongoing tracking run-rates.")
            
    master['FY27 Proposed Budget'] = proposed_vals
    master['Notes'] = notes
    
    for c in ['FY25 Budget', 'FY25 Actual', 'FY25 Projected Close', 'FY27 Proposed Budget']:
        master[c] = master[c].apply(lambda x: f"${x:,.2f}")
        
    md_table = "| Account Item | FY25 Budget | FY25 Actuals | FY25 Projected Close | FY27 Proposed Budget | Notes |\n"
    md_table += "| :--- | :--- | :--- | :--- | :--- | :--- |\n"
    for _, r in master.iterrows():
        md_table += f"| {r['account']} | {r['FY25 Budget']} | {r['FY25 Actual']} | {r['FY25 Projected Close']} | {r['FY27 Proposed Budget']} | {r['Notes']} |\n"

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
