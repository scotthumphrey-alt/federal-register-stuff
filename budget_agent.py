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
        
    print(f"\n--- DIAGNOSTIC FOR FILE: {path} ---")
    df_raw = pd.read_excel(path, header=None).fillna("")
    
    # Locate where the actual columns begin
    header_idx = 0
    for idx, row in df_raw.iterrows():
        row_str = " ".join([str(val).lower() for val in row])
        if any(k in row_str for k in ["budget", "actual", "amount", "total", "balance", "prop", "year"]):
            header_idx = idx
            break
            
    df = pd.read_excel(path, skiprows=header_idx, keep_default_na=False)
    df.columns = [str(c).strip().lower() for c in df.columns]
    
    # CRITICAL DIAGNOSTIC: Print out exactly what Python sees as columns
    print(f"Identified Header Row Columns: {df.columns.tolist()}")
    
    acct_col = df.columns[0]
    
    # Scan for column names flexibly
    b_col = next((c for c in df.columns if 'bud' in c or 'target' in c), None)
    a_col = next((c for c in df.columns if any(k in c for k in ['act', 'tot', 'amo', 'bal', 'run']) and 'over' not in c and 'diff' not in c), None)
    
    # Automatic fallback allocations if the names are custom or empty strings
    if not b_col and len(df.columns) > 1:
        b_col = df.columns[1]
    if not a_col and len(df.columns) > 2:
        a_col = df.columns[2]
        
    print(f"Mapped Data Selection -> Budget Column: [{b_col}], Actual Column: [{a_col}]")

    rows = []
    for _, r in df.iterrows():
        label = str(r[acct_col]).strip()
        if not label or any(k in label.lower() for k in ['total', 'net', 'income after', 'gross profit', 'beginning balance', 'account', 'description']): 
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
    f24 = find_file("24")
    f25 = find_file("25")
    f26 = find_file("26")
    f_sal = find_file("salary") or find_file("matrix")
    
    if not f24 or not f26:
        print(f"Error: Missing core files. Found FY24: {f24}, FY26: {f26}")
        sys.exit(1)
        
    df24 = load_quickbooks_excel(f24, "FY24")
    df25 = load_quickbooks_excel(f25, "FY25") if f25 else pd.DataFrame()
    df26 = load_quickbooks_excel(f26, "FY26")
    
    if df24.empty or df26.empty:
        print("\n[!] Data Frame Row Alignment is missing. Let's fix the column labels above.")
        sys.exit(1)
        
    master = pd.merge(df24, df26, on='account', how='outer').fillna(0.0)
    master['FY26 Projected Close'] = ((master['FY26 Actual'] / 353.0) * 365.0).round(2)
    
    num_cols = master.select_dtypes(include=['number']).columns
    master = master[(master[num_cols] != 0).any(axis=1)]
    
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
        if 'salary' in acct or 'wages' in acct or '6100' in acct:
            proposed_vals.append(total_new_salaries if total_new_salaries > 0 else r['FY26 Projected Close'])
            notes.append("Extracted directly from 2027 Salary Matrix baseline adjustments." if total_new_salaries > 0 else "Base runway close.")
        elif 'bonus' in acct or '6200' in acct:
            proposed_vals.append(0.0)
            notes.append("Discontinued per corporate directive.")
        else:
            proj = r['FY26 Projected Close']
            bud = r['FY26 Budget']
            target = proj if proj > bud else bud
            proposed_vals.append(round(target, 2))
            notes.append("Adjusted to align with current year spending velocity.")
            
    master['FY27 Proposed Budget'] = proposed_vals
    master['Notes'] = notes
    
    for c in master.columns:
        if c != 'account' and c != 'Notes':
            master[c] = master[c].apply(lambda x: f"${x:,.2f}")
            
    md_table = "| Account Item | FY24 Budget | FY24 Actual | FY26 Budget | FY26 Actual YTD | FY26 Projected Close | FY27 Proposed Budget | Notes |\n"
    md_table += "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |\n"
    for _, r in master.iterrows():
        md_table += f"| {r['account']} | {r['FY24 Budget']} | {r['FY24 Actual']} | {r['FY26 Budget']} | {r['FY26 Actual']} | {r['FY26 Projected Close']} | {r['FY27 Proposed Budget']} | {r['Notes']} |\n"

    final_report = f"# FY2027 Recommended Fiscal Budget Proposal\n\n## Budget Comparison Matrix\n\n{md_table}"
    
    with open("budget_proposal_fy27.md", "w", encoding="utf-8") as f:
        f.write(final_report)
    s_env = os.environ.get('GITHUB_STEP_SUMMARY')
    if s_env:
        with open(s_env, "w", encoding="utf-8") as f:
            f.write(final_report)

if __name__ == "__main__":
    main()
