import os
import re
from bs4 import BeautifulSoup

scratch_dir = r"c:\Users\Jovan Fernandes\OneDrive\Documents\mcb  int\mcb-to-notion-sync\webapp\scratch"
files = [f for f in os.listdir(scratch_dir) if f.startswith("detail_view_") and f.endswith(".html")]

print(f"Total files: {len(files)}")
for fn in files:
    path = os.path.join(scratch_dir, fn)
    with open(path, "r", encoding="utf-8") as f:
        html = f.read()
    
    # We want to see if this file has some text from our worksheets
    # like "Math Revision Sheet Answerkey"
    if "math revision sheet answerkey" in html.lower() or "revision worksheet -01" in html.lower() or "it -pa i revision sheet" in html.lower():
        print(f"\n--- {fn} ---")
        soup = BeautifulSoup(html, "html.parser")
        
        # Look for any occurrence of "ViewFile" in the HTML string itself
        matches = re.findall(r"ViewFile\([^)]*\)", html)
        if matches:
            print("  Found ViewFile matches in text:")
            for m in matches[:5]:
                print(f"    {m}")
        else:
            print("  No ViewFile matches in text")
            
        # Let's search for "pdf"
        pdf_matches = re.findall(r"[\w\-\./]+\.pdf", html, re.I)
        if pdf_matches:
            print("  Found pdf matches in text:")
            for m in list(set(pdf_matches))[:5]:
                print(f"    {m}")
        else:
            print("  No PDF matches in text")
            
        # Print first 500 characters of page text to see what kind of page it is
        text = soup.get_text(" ", strip=True)
        print(f"  Page text snippet: {text[:300]}")
