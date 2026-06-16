import os
from bs4 import BeautifulSoup
import re

scratch_dir = r"c:\Users\Jovan Fernandes\OneDrive\Documents\mcb  int\mcb-to-notion-sync\webapp\scratch"
files = [f for f in os.listdir(scratch_dir) if f.startswith("detail_view_") and f.endswith(".html")]

print(f"Found {len(files)} detail view HTML files.")

for fn in files:
    path = os.path.join(scratch_dir, fn)
    with open(path, "r", encoding="utf-8") as f:
        html = f.read()
    
    soup = BeautifulSoup(html, "html.parser")
    
    # Let's search for any PDF or download image or link
    # Let's look for onclick containing "ViewFile" or "Download" or similar
    view_files = soup.find_all(lambda tag: tag.has_attr("onclick") and "ViewFile" in tag["onclick"])
    pdf_links = soup.find_all("a", href=re.compile(r"\.pdf", re.I))
    pdf_imgs = soup.find_all("img", src=re.compile(r"pdf", re.I))
    
    if view_files or pdf_links or pdf_imgs or "pdf" in html.lower():
        print(f"\nFile: {fn}")
        title = soup.find("b")
        title_text = title.get_text(strip=True) if title else "No title"
        print(f"Title: {title_text}")
        
        for el in view_files:
            print(f"  [ViewFile] {el.name}: tag={el.name}, text='{el.get_text(strip=True)}', onclick='{el['onclick']}'")
        for a in pdf_links:
            print(f"  [pdf link] a: text='{a.get_text(strip=True)}', href='{a['href']}'")
        for img in pdf_imgs:
            print(f"  [pdf img] img: src='{img['src']}', parent={img.parent.name if img.parent else 'None'}, parent_onclick={img.parent.get('onclick') if img.parent else 'None'}")
