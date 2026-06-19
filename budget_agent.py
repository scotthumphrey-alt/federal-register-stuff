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

def load_quickbooks_excel(path, prefix):
    if not path or not os.path.exists(path): 
        return pd.DataFrame()
        
    print(f"Loading file: {path}")
    # Load raw excel rows without headers first to locate the real header row
    df_raw = pd.read_excel(path, header=None).fillna("")
    
    # Scan rows to find the actual QuickBooks column header line
    header_idx = 0
    for idx, row in df_raw.iterrows():
        row_str = " ".join([str(val).lower() for val in row])
        if "budget" in row_str or "actual" in row_str or "amount" in row_str:
            header_idx = idx
            break
            
    # Reload the dataframe using the correct header row slot
    df = pd.read_excel(path, skiprows=header_idx, keep_default_na=False)
    df.columns = [str(c).strip().lower() for c in df.columns]
    
    acct_col = df.columns[0]
    b_col = next((c for c in df.columns if 'budget' in c), None)
    a_col = next((c for c in df.columns if any(k in c for k in ['actual', 'total', 'amount', 'balance']) and 'over' not in c), None)
    
    if not b_col or not a_col:
        print(f"Warning: Could not auto-map columns for {path}. Columns found: {df.columns.tolist()}")
        # Fallbacks if columns are unnamed
        b_col = df.columns[1] if len(df.columns) > 1 else None
        a_col = df.columns[2] if len(df.columns) > 2 else None

    rows = []
    for _, r in df.iterrows():
        label = str(r[acct_col]).strip()
        if not label or any(k in label.lower() for k in ['total', 'net', 'income after', 'gross profit', 'beginning balance']): 
            continue
        
        def clean(v):
            s = str(v).replace('$', '').replace(',', '').replace('(', '-').replace(')', '').strip()
            try: return float(s) if s else 0.0
            except: return 0.0
            
        rows.append({
            'account': label,
            f'{prefix} Budget': clean(r[b_col]) if b_col else 0.0,
            f'{prefix} Actual': clean(r[a_col]) if a_col else 0.0
        })
    return pd.DataFrame(rows)

def main():
    f24 = find_file("FY24") or find_file("24")
    f25 = find_file("FY25") or find_file("25")
    f26 = find_file("FY26") or find_file("26")
    f_sal = find_file("salary") or find_file("matrix")
    
    if not f24 or not f26:
        print(f"Error: Missing core files. Found FY24: {f24}, FY26: {f26}")
        sys.exit(1)
        
    df24 = load_quickbooks_excel(f24, "FY24")
    df25 = load_quickbooks_excel(f25, "FY25") if f25 else pd.DataFrame()
    df26 = load_quickbooks_excel(f26, "FY26")
    
    if df24.empty or df26.empty:
        print("Error: Extracted frames are empty. Row alignment failed.")
        sys.exit(1)
        
    # Python Math Engine: Merge and calculate projections locally
    master = pd.merge(df24, df26, on='account', how='outer').fillna(0.0)
    master['FY26 Projected Close'] = ((master['FY26 Actual'] / 353.0) * 365.0).round(2)
    
    # Filter out empty account lines
    num_cols = master.select_dtypes(include=['number']).columns
    master = master[(master[num_cols] != 0).any(axis=1)]
    
    # Local Salary Engine: Calculate total new payroll sum from your matrix
    total_new_salaries = 0.0
    if f_sal:
        print(f"Processing salary sheet: {f_sal}")
        df_sal = pd.read_excel(f_sal, keep_default_na=False) if f_sal.endswith(('.xlsx', '.xls')) else pd.read_csv(f_sal, keep_default_na=False)
        df_sal.columns = [str(c).lower().strip() for c in df_sal.columns]
        sal_col = next((c for c in df_sal.columns if 'salary' in c or 'new' in c or 'pay' in c or 'annual' in c), df_sal.columns[-1])
        for _, r in df_sal.iterrows():
            s_str = str(r[sal_col]).replace('$', '').replace(',', '').strip()
            try: total_new_salaries += float(s_str) if s_str else 0.0
            except: pass
    else:
        print("Note: No separate salary matrix sheet processed. Falling back to baseline calculations.")
                
    # Create the FY27 Proposed Budget column with programmatic logic
    proposed_vals = []
    notes = []
    for _, r in master.iterrows():
        acct = r['account'].lower()
        if 'salary' in acct or 'wages' in acct or '6100' in acct:
            proposed_vals.append(total_new_salaries if total_new_salaries > 0 else r['FY26 Projected Close'])
            notes.append("Extracted directly from 2027 Salary Matrix baseline adjustments." if total_new_salaries > 0 else "Base runway projection.")
        elif 'bonus' in acct or '6200' in acct:
            proposed_vals.append(0.0)
            notes.append("Discontinued per corporate directive.")
        else:
            proj = r['FY26 Projected Close']
            bud = r['FY26 Budget']
            target = proj if proj > bud else bud
            proposed_vals.append(round(target, 2))
            notes.append("Adjusted to align with current year spending velocity and runway baseline.")
            
    master['FY27 Proposed Budget'] = proposed_vals
    master['Notes'] = notes
    
    # Format columns for display
    for c in master.columns:
        if c != 'account' and c != 'Notes':
            master[c] = master[c].apply(lambda x: f"${x:,.2f}")
            
    # Build markdown matrix table
    md_table = "| Account Item | FY24 Budget | FY24 Actual | FY26 Budget | FY26 Actual YTD | FY26 Projected Close | FY27 Proposed Budget | Notes |\n"
    md_table += "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |\n"
    for _, r in master.iterrows():
        md_table += f"| {r['account']} | {r['FY24 Budget']} | {r['FY24 Actual']} | {r['FY26 Budget']} | {r['FY26 Actual']} | {r['FY26 Projected Close']} | {r['FY27 Proposed Budget']} | {r['Notes']} |\n"

    summary_prompt = f"Review this calculated budget summary table and write a concise, professional 3-sentence executive summary memo as a corporate CFO:\n\n{md_table}"
    
    try:
        response = client.models.generate_content(model='gemini-2.5-flash', contents=summary_prompt)
        analysis_text = response.text
    except Exception as e:
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
