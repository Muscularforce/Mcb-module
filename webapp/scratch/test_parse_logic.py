import os
import re
from bs4 import BeautifulSoup

path = r"c:\Users\Jovan Fernandes\OneDrive\Documents\mcb  int\mcb-to-notion-sync\webapp\scratch\real_detail_clicked.html"
with open(path, "r", encoding="utf-8") as f:
    html = f.read()

soup = BeautifulSoup(html, "html.parser")

print("1. Searching for all 'a' tags with 'ViewFile' in onclick...")
a_tags = soup.find_all("a", onclick=re.compile(r"ViewFile", re.I))
print(f"Found {len(a_tags)} tags.")

for idx, a in enumerate(a_tags):
    onclick = a.get("onclick", "")
    print(f"[{idx}] onclick: {onclick}")
    
    # Let's try to match with the regex
    pattern = r"ViewFile\s*\(\s*'([^']*)'\s*,\s*'([^']*)'\s*,\s*'([^']*)'\s*\)"
    match = re.search(pattern, onclick)
    if match:
        filename, url, rno_val = match.groups()
        print(f"  Matched! filename='{filename}', url='{url}', rno='{rno_val}'")
    else:
        print("  Did not match regex!")
        # Let's inspect why it didn't match:
        print(f"  Regex pattern: {pattern}")
