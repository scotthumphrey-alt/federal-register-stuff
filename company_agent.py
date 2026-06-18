import csv
import datetime
import os
import requests
from bs4 import BeautifulSoup
from google import genai

client = genai.Client()

def fetch_web_text(url):
    """Downloads a public page using realistic browser signatures to bypass bot filters."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Upgrade-Insecure-Requests": "1",
        "Cache-Control": "max-age=0"
    }
    try:
        # Added an automatic redirect follower and a slightly relaxed timeout
        res = requests.get(url, headers=headers, timeout=20, allow_redirects=True)
        res.raise_for_status()
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # Strip away clutter
        for element in soup(["script", "style", "nav", "footer", "header", "aside"]):
            element.decompose()
            
        return soup.get_text(separator=" ", strip=True)
    except Exception as e:
        print(f"Skipping {url} due to connection error: {e}")
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
