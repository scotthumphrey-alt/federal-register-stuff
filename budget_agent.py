import os
import glob
import sys
import time
import pandas as pd
from google import genai

client = genai.Client()

def find_quickbooks_file(pattern):
    search_path = os.path.join("financial_data", f"*{pattern}*")
    found_files = glob.glob(search_path)
    if found_files:
        return max(found_files, key=os.path.getmtime)
    return None

def load_quickbooks_matrix(filepath, prefix):
    if not filepath or not os.path.exists(filepath):
        return pd.DataFrame()
        
    if filepath.endswith('.xlsx') or filepath.endswith('.xls'):
        df = pd.read_excel(filepath, keep_default_na=False)
    else:
        df = pd.read_csv(filepath, keep_default_na=False)
        
    df.columns = [str(col).strip().lower() for col in df.columns]
    account_col = df.columns[0]
    
    budget_col = None
    actual_col = None
    
    for col in df.columns:
        if 'budget' in col:
            budget_col = col
        elif 'actual' in col or 'total' in col or 'amount' in col or 'balance' in col:
            if not actual_col or 'actual' in col:
                actual_col = col

    if not budget_col and len(df.columns) > 1:
        budget_col = df.columns[1]
    if not actual_col and len(df.columns) > 2:
        actual_col = df.columns[2]

    cleaned_rows = []
    for _, row in df.iterrows():
        acct_label = str(row[account_col]).strip()
        if not acct_label or 'total' in acct_label.lower() or 'net' in acct_label.lower():
            continue
            
        def clean_val(val_str):
            val_cleaned = str(val_str).replace('$', '').replace(',', '').replace('(', '-').replace(')', '').strip()
            try:
                return float(val_cleaned) if val_cleaned else 0.0
            except ValueError:
                return 0.0

        b_val = clean_val(row[budget_col]) if budget_col else 0.0
        a_val = clean_val(row[actual_col]) if actual_col else 0.0
            
        cleaned_rows.append({
            'account': acct_label, 
            f'{prefix} Budget': b_val,
            f'{prefix} Actual': a_val
        })
        
    return pd.DataFrame(cleaned_rows)

def main():
    file_24 = find_quickbooks_file("24")
    file_25 = find_quickbooks_file("25")
    file_26 = find_quickbooks_file("26")
    salary_file = find_quickbooks_file("salary") or find_quickbooks_file("personnel")

    if not file_24 or not file_26:
        print("Error: Missing required fiscal data files in folder.")
        sys.exit(1)

    df_24 = load_quickbooks_matrix(file_24, "FY24")
    df_25 = load_quickbooks_matrix(file_25, "FY25") if file_25 else pd.DataFrame()
    df_26 = load_quickbooks_matrix(file_26, "FY26")

    master_df = df_24
    if not df_25.empty:
        master_df = pd.merge(master_df, df_25, on='account', how='outer')
    master_df = pd.merge(master_df, df_26, on='account', how='outer').fillna(0.0)

    master_df['FY26 Projected Close'] = (master_df['FY26 Actual'] / 353.0) * 365.0
    master_df['FY26 Projected Close'] = master_df['FY26 Projected Close'].round(2)

    # TOKEN SAVER LAYER: Filter out every single row where all financial values equal zero
    numeric_cols = master_df.select_dtypes(include=['number']).columns
    master_df = master_df[(master_df[numeric_cols] != 0).any(axis=1)]

    data_matrix_csv = master_df.to_csv(index=False)

    salary_context_csv = "No separate salary spreadsheet uploaded."
    if salary_file:
        if salary_file.endswith('.xlsx') or salary_file.endswith('.xls'):
            df_sal = pd.read_excel(salary_file, keep_default_na=False)
        else:
            df_sal = pd.read_csv(salary_file, keep_default_na=False)
        salary_context_csv = df_sal.to_csv(index=False)

    prompt = f"""
    You are an expert CFO. Review this financial dataset to construct a recommended FY2027 budget starting July 1st.

    DATASET 1: Consolidated QuickBooks General Ledger (CSV format):
    {data_matrix_csv}

    DATASET 2: Raw Personnel Salary & Bonus List (CSV format):
    {salary_context_csv}

    Directives for FY27 Column Target Construction:
    1. For staff operator salary lines: do not use basic run-rate math. Instead, analyze Dataset 2, calculate the cumulative total of the new annual salaries listed, and map that exact value into the FY27 Proposed Budget line.
    2. For annual bonus lines: calculate the cumulative total from the bonus columns in Dataset 2, or set to 0 if the spreadsheet dictates discontinuation.
    3. For all other operational lines: assess baseline variance and velocity ('FY26 Budget' vs 'FY26 Projected Close'). If a line tracks over budget, adjust upward logically. If under-utilized, reduce it.

    Formatting Rules:
    Generate a clean markdown table with these columns:
    | Account Item | FY24 Budget | FY24 Actual | FY26 Budget | FY26 Actual YTD | FY26 Projected Close | FY27 Proposed Budget | Notes / Justification |
    """

    print("Analyzing trimmed financial matrices...")
    
    response = None
    for attempt in range(3):
        try:
            # Switched model to gemini-1.5-flash for more lenient rate windows
            response = client.models.generate_content(model='gemini-1.5-flash', contents=prompt)
            break
        except Exception as e:
            print(f"Rate window busy. Waiting 60 seconds (Attempt {attempt + 1}/3)...")
            time.sleep(60)

    if not response:
        print("Error: Quota constraints could not be cleared.")
        sys.exit(1)
        
    with open("budget_proposal_fy27.md", "w", encoding="utf-8") as f:
        f.write(response.text)
    
    summary_env = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary_env:
        with open(summary_env, "w", encoding="utf-8") as f:
            f.write(response.text)

if __name__ == "__main__":
    main()
