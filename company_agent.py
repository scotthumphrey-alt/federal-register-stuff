import csv
import datetime
import os
import time
import requests
from bs4 import BeautifulSoup
from google import genai

client = genai.Client()

def broad_internet_search(identity_name):
    """Executes an open search query to aggregate data from any available public resource."""
    # We utilize a clean, free public search engine endpoint (DuckDuckGo HTML) 
    # to find open market profile entries without getting locked down by enterprise firewalls.
    search_url = "https://html.duckduckgo.com/html/"
    query = f"{identity_name} corporate headquarters executive leadership profile team"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    try:
        print(f"Executing broad internet search vector for: {identity_name}")
        res = requests.post(search_url, data={"q": query}, headers=headers, timeout=15)
        res.raise_for_status()
        
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # Pull text from snippet containers and search result cards
        search_snippets = []
        for result in soup.find_all('td', class_='result-snippet'):
            search_snippets.append(result.get_text(strip=True))
            
        # If we successfully scraped public search summaries, combine them as the text source
        if search_snippets:
            combined_context = " ".join(search_snippets[:8])
            print(f"--> Successfully extracted {len(search_snippets)} public data text layers.")
            return combined_context
            
        # Fallback: If snippets structure changed, scrape the plain text layout of the page
        return soup.get_text(separator=" ", strip=True)[:10000]
        
    except Exception as e:
        print(f"Search vector exception for {identity_name}: {e}")
        return ""

def extract_corporate_metrics_with_retry(identity_name, raw_context):
    """Processes search data through Gemini using a rate-limiting fallback safety valve."""
    if not raw_context.strip():
        return f"| {identity_name} | Search Query Blocked | N/A | N/A |\n"

    prompt = f"""
    Analyze the following internet search results and public snippet data regarding: {identity_name}.
    
    Your goal is to extract:
    1. Corporate Headquarters (City and State/Country)
    2. Executive Leadership (Identify the top leader, such as CEO, Executive Director, or President)
    3. Operational Footprint (Summarize their core services, infrastructure, or domain in one brief sentence)

    Formatting Rules:
    Output your answer strictly as a single row of a markdown table matching this layout:
    | {identity_name} | [Headquarters Location] | [CEO/Director Name] | [Operational Summary Detail] |
    
    Do not include conversational introductions, markdown headers, or trailing notes.

    Public Search Data Content:
    {raw_context}
    """
    
    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt
            )
            return response.text.strip() + "\n"
        except Exception as e:
            print(f"Gemini API rate buffer triggered. Attempt {attempt + 1} paused...")
            time.sleep(5 * (attempt + 1))
            
    return f"| {identity_name} | Extraction Processing Error | N/A | N/A |\n"

def main():
    if not os.path.exists("companies.csv"):
        print("Missing target file companies.csv")
        return

    today_str = datetime.date.today().strftime("%B %d, %Y")
    report = f"# Compiled Corporate & Agency Intelligence Digest - {today_str}\n\n"
    report += "| Entity Name | Corporate Headquarters | Executive Leadership | Operational Profile / Footprint |\n"
    report += "| :--- | :--- | :--- | :--- |\n"

    with open("companies.csv", mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row.get("Company")
            if not name:
                continue
                
            print(f"\n--- Processing Open Internet Vector: {name} ---")
            aggregated_text = broad_internet_search(name)
            
            extracted_row = extract_corporate_metrics_with_retry(name, aggregated_text)
            report += extracted_row
            
            # 3-second delay to keep the automation completely stable
            time.sleep(3)

    with open("company_intelligence.md", "w", encoding="utf-8") as f:
        f.write(report)

    summary_env = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary_env:
        with open(summary_env, "w", encoding="utf-8") as f:
            f.write(report)

if __name__ == "__main__":
    main()
