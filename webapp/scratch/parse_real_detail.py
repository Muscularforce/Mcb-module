import os
from bs4 import BeautifulSoup
import re

path = r"c:\Users\Jovan Fernandes\OneDrive\Documents\mcb  int\mcb-to-notion-sync\webapp\scratch\real_detail_clicked.html"
if not os.path.exists(path):
    print("File does not exist")
    exit()

with open(path, "r", encoding="utf-8") as f:
    html = f.read()

soup = BeautifulSoup(html, "html.parser")
container = soup.find(id="DivMarksAssignments")

if container:
    print("Found DivMarksAssignments!")
    # Look for any links or buttons or onclick attributes
    for idx, tag in enumerate(container.find_all(True)):
        onclick = tag.get("onclick")
        src = tag.get("src")
        href = tag.get("href")
        
        # If the tag is an anchor, image, or has an onclick, print it
        if tag.name in ["a", "img", "button"] or onclick:
            txt = tag.get_text(" ", strip=True)[:100]
            print(f"[{idx}] {tag.name}: text='{txt}'")
            if onclick: print(f"    onclick='{onclick}'")
            if src: print(f"    src='{src}'")
            if href: print(f"    href='{href}'")
else:
    print("DivMarksAssignments not found in HTML!")
