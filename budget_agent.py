import os
import glob
import pandas as pd
from google import genai

client = genai.Client()

def find_quickbooks_file(pattern):
    """Scans financial_data for a file matching a pattern."""
    search_path = os.path.join("financial_data", f"*{pattern}*")
    found_files = glob.glob(search_path)
    if found_files:
        return max(found_files, key=os.path.getmtime)
    return None

def load_quickbooks_matrix(filepath, prefix):
    """Loads a QuickBooks layout and isolates data columns."""
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
    import time
    
    # Identify files by checking name strings
    file_24 = find_quickbooks_file("24")
    file_25 = find_quickbooks_file("25")
    file_26 = find_quickbooks_file("26")

    if not file_24 or not file_26:
        print("Error: Missing required fiscal data files in folder.")
        return

    df_24 = load_quickbooks_matrix(file_24, "FY24")
    df_25 = load_quickbooks_matrix(file_25, "FY25") if file_25 else pd.DataFrame()
    df_26 = load_quickbooks_matrix(file_26, "FY26")

    # Combine data columns sideways
    master_df = df_24
    if not df_25.empty:
        master_df = pd.merge(master_df, df_25, on='account', how='outer')
    master_df = pd.merge(master_df, df_26, on='account', how='outer').fillna(0.0)

    # Project active year metrics through June 30th (Day 353 to 365 run-rate conversion)
    master_df['FY26 Projected Close'] = (master_df['FY26 Actual'] / 353.0) * 365.0
    master_df['FY26 Projected Close'] = master_df['FY26 Projected Close'].round(2)

    data_matrix_str = master_df.to_string(index=False)

    prompt = f"""
    You are an expert CFO. Review this budget matrix comparing historical performance to project a final FY2027 recommended budget starting July 1st.

    Consolidated spreadsheet data rows:
    {data_matrix_str}

    Directives:
    1. For staff operator salary lines: increase base allocations.
    2. For annual bonus lines: completely discontinue and set target to 0.
    3. For other lines: assess baseline variance and velocity ('FY26 Budget' vs 'FY26 Projected Close'). If a line tracks over budget, adjust upward. If under-utilized, reduce it.

    Formatting Rules:
    Generate a clean markdown table with these columns:
    | Account Item | FY24 Budget | FY24 Actual | FY26 Budget | FY26 Actual YTD | FY26 Projected Close | FY27 Proposed Budget | Notes |
    """

    print("Analyzing combined spreadsheets...")
    
    # Self-healing retry loop for 429 rate limits
    response = None
    for attempt in range(3):
        try:
            response = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
            break
        except Exception as e:
            if "429" in str(e) or "quota" in str(e).lower():
                print(f"Hit AI rate limit. Pausing 30 seconds to clear buffer (Attempt {attempt + 1}/3)...")
                time.sleep(30)
            else:
                print(f"Error calling AI: {e}")
                return

    if not response:
        print("Error: Could not get a response from the AI after retries.")
        return
        
    with open("budget_proposal_fy27.md", "w", encoding="utf-8") as f:
        f.write(response.text)
    
    summary_env = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary_env:
        with open(summary_env, "w", encoding="utf-8") as f:
            f.write(response.text)

if __name__ == "__main__":
    main()
