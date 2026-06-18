import csv
import datetime
import os
import requests
from bs4 import BeautifulSoup
from google import genai

client = genai.Client()

def fetch_web_text(url):
    """Downloads clean text using an explicitly declared, policy-compliant descriptive header."""
    headers = {
        # Declares a clear, compliant identity with contact info so servers don't flag it as an invasive bot
        "User-Agent": "CorporateIntelScanAgent/1.0 (scotthumphrey-alt; contact: agent@github.com)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    }
    try:
        res = requests.get(url, headers=headers, timeout=20, allow_redirects=True)
        res.raise_for_status()
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # Strip template layout noise
        for element in soup(["script", "style", "nav", "footer", "header", "aside", "noscript"]):
            element.decompose()
            
        return soup.get_text(separator=" ", strip=True)
    except Exception as e:
        print(f"Skipping {url} due to connection issue: {e}")
        return ""

def extract_corporate_metrics(company_name, raw_text):
    """Instructs Gemini to return rigid data points from messy page text."""
    if not raw_text.strip():
        return f"| {company_name} | Connection Failed | N/A | N/A |\n"

    prompt = f"""
    Analyze the following raw text content extracted from the official website of {company_name}.
    
    Task: Extract these exact metrics:
    1. Corporate Headquarters (City and State/Country)
    2. Executive Leadership (Identify the current CEO or equivalent President)
    3. Operational Footprint (Summarize key services, vessel size indicators, or focus areas in a brief sentence)

    Formatting Rules:
    Output your answer strictly as a single row of a markdown table matching this layout:
    | {company_name} | [Headquarters Location] | [CEO Name] | [Operational Summary Detail] |

    Do not provide conversational introductions, no column headers, and no trailing notes. 

    Raw Text Data:
    {raw_text}
    """
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
        )
        return response.text.strip() + "\n"
    except Exception as e:
        print(f"AI parsing error for {company_name}: {e}")
        return f"| {company_name} | Extraction Timeout | N/A | N/A |\n"

def main():
    if not os.path.exists("companies.csv"):
        print("Missing target file companies.csv")
        return

    # Initialize the report dashboard layout
    today_str = datetime.date.today().strftime("%B %d, %Y")
    report = f"# Compiled Company Intelligence Digest - {today_str}\n\n"
    report += "| Company Name | Corporate Headquarters | Executive Leadership | Operational Profile / Footprint |\n"
    report += "| :--- | :--- | :--- | :--- |\n"

    # Loop through the list of targets
    with open("companies.csv", mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row.get("Company")
            target_url = row.get("URL")
            
            print(f"Scanning target entity: {name} at {target_url}...")
            site_text = fetch_web_text(target_url)
            
            # Appends the single-row data directly to the table list
            extracted_row = extract_corporate_metrics(name, site_text[:12000])
            report += extracted_row

    # Save results to code repository
    with open("company_intelligence.md", "w", encoding="utf-8") as f:
        f.write(report)

    # Export directly to dashboard environment
    summary_env = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary_env:
        with open(summary_env, "w", encoding="utf-8") as f:
            f.write(report)

if __name__ == "__main__":
    main()
