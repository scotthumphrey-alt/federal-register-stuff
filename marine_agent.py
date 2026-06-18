import datetime
import requests
from bs4 import BeautifulSoup
from google import genai

TARGET_URL = "https://www.sfmx.org/events"
client = genai.Client()

def scrape_upcoming_events():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    try:
        response = requests.get(TARGET_URL, headers=headers, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        return soup.get_text(separator="\n")
    except Exception as e:
        print(f"Error reading webpage content: {e}")
        return ""

def filter_events_with_ai(raw_html_content):
    current_date = datetime.date.today().strftime("%B %d, %Y")
    prompt = f"""
    You are an automated administrative tracking agent. Review the following raw text pulled from the Marine Exchange upcoming events feed.
    
    Today's Date: {current_date}
    
    Instructions:
    1. Look through the text for any events explicitly related to the "Harbor Safety Committee" or its subcommittees/working groups (often abbreviated as HSC or TTE).
    2. Filter out any events that occurred in the past relative to today's date ({current_date}). Only identify events scheduled in the future.
    3. Output your findings using a clear, active-voice bulleted list summarizing the Event Title, Date, and Scheduled Time. 
    4. If no future Harbor Safety Committee events are found in the text, respond strictly with: "No upcoming Harbor Safety Committee events found."

    Raw Webpage Data:
    {raw_html_content}
    """
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
        )
        return response.text
    except Exception as e:
        print(f"AI Analysis failed: {e}")
        return None

def main():
    print(f"Scraping Marine Exchange upcoming events feed at: {TARGET_URL}...")
    raw_content = scrape_upcoming_events()
    if not raw_content.strip():
        print("Failed to pull text data from the target page.")
        return
    print("Analyzing event calendar details with AI...")
    analysis_results = filter_events_with_ai(raw_content)
    print("\n=== AGENT SCAN RESULTS ===")
    print(analysis_results)

if __name__ == "__main__":
    main()
