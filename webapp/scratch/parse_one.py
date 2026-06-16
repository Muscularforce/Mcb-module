import os
from bs4 import BeautifulSoup
import re

scratch_dir = r"c:\Users\Jovan Fernandes\OneDrive\Documents\mcb  int\mcb-to-notion-sync\webapp\scratch"
files = [f for f in os.listdir(scratch_dir) if f.startswith("detail_view_") and f.endswith(".html")]

for fn in files:
    path = os.path.join(scratch_dir, fn)
    with open(path, "r", encoding="utf-8") as f:
        html = f.read()
    if "math revision sheet answerkey" in html.lower():
        print(f"Match: {fn}")
        soup = BeautifulSoup(html, "html.parser")
        # Let's print out the body contents, or links
        # Print anything that could be an attachment link
        for a in soup.find_all("a"):
            print(f"  a: text='{a.get_text(strip=True)}', href='{a.get('href')}', onclick='{a.get('onclick')}'")
        for img in soup.find_all("img"):
            print(f"  img: src='{img.get('src')[:100]}', onclick='{img.get('onclick')}', parent_onclick='{img.parent.get('onclick') if img.parent else None}'")
        break
