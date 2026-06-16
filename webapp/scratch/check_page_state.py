from bs4 import BeautifulSoup

path = r"c:\Users\Jovan Fernandes\OneDrive\Documents\mcb  int\mcb-to-notion-sync\webapp\scratch\real_detail_clicked.html"
with open(path, "r", encoding="utf-8") as f:
    html = f.read()

soup = BeautifulSoup(html, "html.parser")

# Find ddl_SubjectID
select = soup.find("select", id="ddl_SubjectID")
if select:
    print("ddl_SubjectID options:")
    for opt in select.find_all("option"):
        selected = "SELECTED" if opt.has_attr("selected") else ""
        print(f"  value='{opt.get('value')}', text='{opt.get_text(strip=True)}' {selected}")
else:
    print("ddl_SubjectID not found")

# Find optradio
radios = soup.find_all("input", attrs={"name": "optradio"})
print(f"optradio inputs ({len(radios)}):")
for r in radios:
    checked = "CHECKED" if r.has_attr("checked") else ""
    print(f"  value='{r.get('value')}', checked='{checked}'")
