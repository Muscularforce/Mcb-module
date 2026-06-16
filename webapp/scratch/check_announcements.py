import os
from bs4 import BeautifulSoup
import re

path = r"c:\Users\Jovan Fernandes\OneDrive\Documents\mcb  int\mcb-to-notion-sync\webapp\scratch\announcements.html"
if not os.path.exists(path):
    print("File does not exist")
    exit()

with open(path, "r", encoding="utf-8") as f:
    html = f.read()

soup = BeautifulSoup(html, "html.parser")
print("Found announcements page HTML!")

# Let's find all divs containing announcements
# They are generic cards. Let's find card-body nodes
nodes = soup.find_all("div", class_=lambda c: c and "card-body" in c)
print(f"Found {len(nodes)} card-body elements.")

for idx, node in enumerate(nodes):
    text = node.get_text(" ", strip=True)
    if "art competition" in text.lower() or "planner" in text.lower() or "menu" in text.lower():
        print(f"\n[{idx}] Card text preview: {text[:150]}")
        # Find any links, images, or onclick elements in this card
        for a in node.find_all("a"):
            print(f"  a: text='{a.get_text(strip=True)}', href='{a.get('href')}', onclick='{a.get('onclick')}'")
        for img in node.find_all("img"):
            print(f"  img: src='{img.get('src')}', onclick='{img.get('onclick')}'")
        for tag in node.find_all(onclick=True):
            print(f"  {tag.name} with onclick: '{tag.get('onclick')}'")
