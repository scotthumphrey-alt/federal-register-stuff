import csv
import datetime
import os
import time
import urllib.parse
import requests
from bs4 import BeautifulSoup
from google import genai

client = genai.Client()

def get_wikipedia_variants(company_name):
    """Generates 10 different structural URL possibilities to guarantee a match."""
    # Clean up trailing spaces and common punctuation
    base = company_name.strip()
    
    # 10 structural formatting strategies
    variants = [
        base,                                # 1. Matson
        f"{base} (company)",                 # 2. Matson (company)
        f"{base} Navigation Company",        # 3. Matson Navigation Company
        f"{base}, Inc.",                     # 4. Matson, Inc.
        f"{base} Inc.",                      # 5. Matson Inc
        f"{base} Corporation",               # 6. Matson Corporation
        f"{base} Maritime",                  # 7. Matson Maritime
        f"{base} Logistics",                 # 8. Matson Logistics
        f"{base} Holdings",                  # 9. Matson Holdings
        f"{base} (shipping company)"         # 10. Matson (shipping company)
    ]
    
    # Format spaces into underscores and cleanly encode special characters for URLs
    urls = []
    for v in variants:
        encoded_title = urllib.parse.quote(v.replace(" ", "_"))
        urls.append(f"https://en.wikipedia.org/wiki/{encoded_title}")
    return urls

def fetch_web_text_with_fallbacks(company_name):
    """Tries up to 10 different URL variations until a page successfully loads."""
    headers = {
        "User-Agent": "CorporateIntelScanAgent/1.0 (scotthumphrey-alt; contact: agent@github.com)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    }
    
    # Fetch our list of 10 search variations
    target_urls = get_wikipedia_variants(company_name)
    
    for url in target_urls:
        try:
            print(f"Checking variant path for {company_name}: {url}")
            res = requests.get(url, headers=headers, timeout=10, allow_redirects=True)
            
            # If the server responds with a 404 error, skip immediately to the next variant
            if res.status_code == 404:
                continue
                
            res.raise_for_status()
            soup = BeautifulSoup(res.text, 'html.parser')
            
            # Check if it's a blank search results page or a "disambiguation" helper page
            page_text = soup.get_text()
            if "may refer to:" in page_text or "Other reasons this message may be displayed" in page_text:
                continue
                
            # Clean layout noise if successful
            for element in soup(["script", "style", "nav", "footer", "header", "aside", "noscript"]):
                element.decompose()
                
            print(f"--> Success! Found valid reference page layout at: {url}")
            return soup.get_text(separator=" ", strip=True)
            
        except Exception as e:
            print(f"Skipping path due to handshake block: {e}")
            continue
            
    print(f"❌ All 10 variants exhausted for {company_name}")
    return ""

def extract_corporate_metrics(company_name, raw_text):
    if not raw_text.strip():
        return f"| {company_name} | Metrics Unavailable | N/A | N/A |\n"

    prompt = f"""
    Analyze the following raw text content extracted from the profile of {company_name}.
    Task: Extract these exact metrics:
    1. Corporate Headquarters (City and State/Country)
    2. Executive Leadership (Identify the current CEO or equivalent President)
    3. Operational Footprint (Summarize key services or focus areas in a brief sentence)

    Formatting Rules:
    Output your answer strictly as a single row of a markdown table matching this layout:
    | {company_name} | [Headquarters Location] | [CEO Name] | [Operational Summary Detail] |
    Do not provide conversational introductions, no column headers, and no trailing notes. 

    Raw Text Data:
    {raw_text}
    """
    try:
        response = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
        return response.text.strip() + "\n"
    except Exception as e:
        return f"| {company_name} | Extraction Error | N/A | N/A |\n"

def main():
    if not os.path.exists("companies.csv"):
        return

    today_str = datetime.date.today().strftime("%B %d, %Y")
    report = f"# Compiled Company Intelligence Digest - {today_str}\n\n"
    report += "| Company Name | Corporate Headquarters | Executive Leadership | Operational Profile / Footprint |\n"
    report += "| :--- | :--- | :--- | :--- |\n"

    with open("companies.csv", mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row.get("Company")
            
            # Use our new 10-tier fallback logic
            site_text = fetch_web_text_with_fallbacks(name)
            extracted_row = extract_corporate_metrics(name, site_text[:12000])
            report += extracted_row
            time.sleep(2)

    with open("company_intelligence.md", "w", encoding="utf-8") as f:
        f.write(report)

    summary_env = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary_env:
        with open(summary_env, "w", encoding="utf-8") as f:
            f.write(report)

if __name__ == "__main__":
    main()
