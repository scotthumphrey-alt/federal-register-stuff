import datetime
import os
import requests
from google import genai
from google.genai import types

TARGET_TOPIC = "Federal Grant Infrastructure and Uniform Guidance updates"
AGENCY_FILTER = ""  

client = genai.Client()

def fetch_daily_federal_register():
    today = datetime.date.today().strftime("%Y-%m-%d")
    url = "https://www.federalregister.gov/api/v1/documents.json"
    params = {
        "conditions[publication_date][is]": today,
        "per_page": 100
    }
    if AGENCY_FILTER:
        params["conditions[agencies][]"] = AGENCY_FILTER
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        return response.json().get("results", [])
    except requests.exceptions.RequestException as e:
        print(f"Error fetching Federal Register data: {e}")
        return []

def analyze_document_with_ai(doc, topic):
    title = doc.get("title", "No Title")
    abstract = doc.get("abstract", "No Abstract Provided")
    html_url = doc.get("html_url", "")
    pdf_url = doc.get("pdf_url", "")
    agency = ", ".join([a.get("name") for a in doc.get("agencies", [])])

    prompt = f"""
    You are a regulatory compliance AI agent. Evaluate the following Federal Register entry.
    
    Target Topic to Monitor: {topic}
    
    Document Title: {title}
    Agency: {agency}
    Abstract: {abstract}
    
    Determine if this document is directly relevant to the Target Topic.
    Respond strictly in the following format:
    RELEVANT: [Yes/No]
    SUMMARY: [If Yes, a concise active-voice bulleted breakdown of the operational impact. If No, leave blank.]
    """
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
        )
        return response.text, html_url, pdf_url
    except Exception as e:
        print(f"AI Analysis failed for {title}: {e}")
        return None

def main():
    print(f"Starting morning scan for topic: '{TARGET_TOPIC}'...")
    documents = fetch_daily_federal_register()
    if not documents:
        print("No documents published today or connection failed.")
        return
    print(f"Found {len(documents)} documents published today. Analyzing...")
    relevant_findings = []
    for doc in documents:
        analysis = analyze_document_with_ai(doc, TARGET_TOPIC)
        if analysis:
            result_text, html_url, pdf_url = analysis
            if "RELEVANT: Yes" in result_text:
                relevant_findings.append({
                    "title": doc.get("title"),
                    "agency": ", ".join([a.get("name") for a in doc.get("agencies", [])]),
                    "analysis": result_text.split("SUMMARY:")[-1].strip(),
                    "html": html_url,
                    "pdf": pdf_url
                })
    if relevant_findings:
        print(f"\n Scan Complete. Found {len(relevant_findings)} matching items:")
        for item in relevant_findings:
            print(f"\n=== MATCH FOUND ===")
            print(f"Title: {item['title']}")
            print(f"Agency: {item['agency']}")
            print(f"Impact:\n{item['analysis']}")
            print(f"Links: {item['html']} | {item['pdf']}")
    else:
        print("\nScan Complete. No relevant updates found today.")

if __name__ == "__main__":
    main()
