import os
import sys
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

MCB_USERNAME = os.getenv("MCB_USERNAME")
MCB_PASSWORD = os.getenv("MCB_PASSWORD")

def find_login_scope(page):
    password_selectors = [
        "input[type='password']",
        "input#txtPassword",
        "input#txtPass",
        "input[id*='pass' i]",
        "input[name*='pass' i]",
    ]
    for frame in page.frames:
        try:
            if any(frame.locator(sel).count() > 0 for sel in password_selectors):
                return frame
        except Exception:
            pass
    return page

def try_fill_first_matching(locators, value):
    for loc in locators:
        try:
            target = loc.first
            if target.count() > 0:
                target.fill(value)
                return True
        except Exception:
            pass
    return False

def find_first_match(scope, selectors):
    for selector in selectors:
        try:
            loc = scope.locator(selector)
            if loc.count() > 0:
                return loc.first
        except Exception:
            pass
    return None

def main():
    if not MCB_USERNAME or not MCB_PASSWORD:
        print("Missing credentials")
        return

    with sync_playwright() as p:
        print("Launching browser...")
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_default_navigation_timeout(90000)
        page.set_default_timeout(30000)

        # Login
        print("Navigating to login URL...")
        try:
            page.goto("https://rainbow.myclassboard.com/Account/Login", wait_until="commit", timeout=60000)
        except Exception as e:
            print(f"Failed to load login page: {e}")
            browser.close()
            return

        page.wait_for_timeout(5000)
        
        # Click login button if pre-login page
        try:
            btn = page.locator("text=Click here to Login").first
            if btn.count() > 0:
                btn.click()
                page.wait_for_timeout(3000)
        except Exception as e:
            pass

        # Login process
        scope = find_login_scope(page)
        username_selectors = [
            "input#txtUserName", "input#txtUsername", "input#txtUser",
            "input#username", "input#UserName", "input#LoginID",
            "input#txtLoginId", "input#txtEmail", "input[type='text']",
        ]
        password_selectors = [
            "input#txtPassword", "input#txtPass", "input#txtPwd",
            "input#password", "input[type='password']",
        ]
        
        try_fill_first_matching([scope.locator(s) for s in username_selectors], MCB_USERNAME)
        try_fill_first_matching([scope.locator(s) for s in password_selectors], MCB_PASSWORD)
        
        login_btn = find_first_match(scope, [
            "#LogID", "#btnLogin",
            "button:has-text('Login')", "button:has-text('Sign In')",
            "input[type='submit']", "button[type='submit']",
        ])
        if login_btn:
            login_btn.click()
        else:
            page.keyboard.press("Enter")
            
        page.wait_for_timeout(10000)
        print("Login successful.")

        # Navigate to Assignments
        print("Clicking Assignments tab...")
        try:
            ass_tab = page.locator("a:has-text('Assignments'), li:has-text('Assignments'), button:has-text('Assignments')").first
            ass_tab.click()
            page.wait_for_timeout(7000)
            print("Assignments tab loaded.")
        except Exception as e:
            print(f"Failed to click Assignments tab: {e}")
            browser.close()
            return

        # Let's inspect the cards
        html = page.content()
        soup = BeautifulSoup(html, "html.parser")
        
        # Innermost elements that contain the text "Submission due date"
        print("Searching for assignment cards using BS4...")
        cards = []
        for elem in soup.find_all(True):
            text = elem.get_text(" ", strip=True)
            if "Submission due date" in text:
                # Check if this element has any child containing "Submission due date"
                has_child = False
                for child in elem.find_all(True):
                    if child != elem and "Submission due date" in child.get_text(" ", strip=True):
                        has_child = True
                        break
                if not has_child:
                    cards.append(elem)

        print(f"Found {len(cards)} innermost cards containing 'Submission due date'")
        
        for idx, card in enumerate(cards[:5]):
            print(f"\n--- Card {idx} ---")
            print(card.get_text(" ", strip=True))
            print("Tag name:", card.name)
            print("Attributes:", card.attrs)
            # Find if there are any buttons or click targets in this card
            onclick_elems = card.find_all(onclick=True)
            for oe in onclick_elems:
                print(f"  Onclick child: {oe.name}, text='{oe.get_text(strip=True)}', onclick='{oe.get('onclick')}'")
            links = card.find_all("a")
            for l in links:
                print(f"  Link child: {l.name}, text='{l.get_text(strip=True)}', href='{l.get('href')}', onclick='{l.get('onclick')}'")

        # Let's try to click the first card by selecting it in Playwright via text
        if cards:
            first_card_text = cards[0].get_text(" ", strip=True)
            # Find a substring that is unique, e.g. the first 30 chars
            search_text = first_card_text[:40].replace("'", "\\'")
            print(f"\nAttempting to click card in Playwright using text match: '{search_text}'")
            
            try:
                # Find the element that has this text and click it
                card_loc = page.locator(f"text='{search_text}'").first
                card_loc.scroll_into_view_if_needed()
                card_loc.click(timeout=10000)
                page.wait_for_timeout(5000)
                print("Clicked! Dumping detail view content...")
                page.screenshot(path="webapp/scratch/clicked_real_card.png")
                
                detail_html = page.content()
                with open("webapp/scratch/real_detail_view.html", "w", encoding="utf-8") as f:
                    f.write(detail_html)
                print("Saved detail view to webapp/scratch/real_detail_view.html")
                
                # Check for attachments/links
                detail_soup = BeautifulSoup(detail_html, "html.parser")
                print("\nAll links/attachments on the detail page:")
                for a in detail_soup.find_all("a"):
                    print(f"  a: text='{a.get_text(strip=True)}', href='{a.get('href')}', onclick='{a.get('onclick')}'")
                for img in detail_soup.find_all("img"):
                    print(f"  img: src='{img.get('src')}', onclick='{img.get('onclick')}'")
                for btn in detail_soup.find_all("button"):
                    print(f"  button: text='{btn.get_text(strip=True)}', onclick='{btn.get('onclick')}'")
                
                # Check if there is any PDF text or download icon
                pdf_icons = detail_soup.find_all(class_=re.compile(r"pdf|download|file|doc", re.I))
                for pi in pdf_icons:
                    print(f"  Found PDF/download class element: {pi.name}, class={pi.get('class')}, text='{pi.get_text(strip=True)}'")
            except Exception as e:
                print(f"Click/Inspect failed: {e}")

        browser.close()

if __name__ == "__main__":
    main()
