import os
import sys
import re
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

        # Find all ViewQuestion click targets
        print("Locating ViewQuestion elements...")
        targets = page.locator("div.row[onclick*='ViewQuestion']")
        count = targets.count()
        print(f"Found {count} ViewQuestion target rows")

        if count > 0:
            # Click the first one (which is the newest assignment card)
            target = targets.first
            print("Clicking the first assignment card...")
            try:
                target.scroll_into_view_if_needed()
                target.click(timeout=10000)
                print("Clicked target. Waiting 7 seconds for AJAX load...")
                page.wait_for_timeout(7000)
                
                # Take screenshot
                page.screenshot(path="webapp/scratch/assignment_detail.png")
                print("Screenshot saved to webapp/scratch/assignment_detail.png")
                
                # Extract page content
                detail_html = page.content()
                with open("webapp/scratch/assignment_detail.html", "w", encoding="utf-8") as f:
                    f.write(detail_html)
                print("Detail HTML saved to webapp/scratch/assignment_detail.html")
                
                # Parse detail page with BS4
                soup = BeautifulSoup(detail_html, "html.parser")
                
                # Look for attachments
                print("\nInspecting detail page elements for attachments:")
                
                # Check for PDF or document download links
                links = soup.find_all("a")
                print(f"Found {len(links)} links in document:")
                for a in links:
                    txt = a.get_text(" ", strip=True)
                    href = a.get("href")
                    onclick = a.get("onclick")
                    if href or onclick or txt:
                        # Print link details
                        print(f"  Link: text='{txt}', href='{href}', onclick='{onclick}'")
                        
                # Look for PDF images/icons or other images that might be clicked
                imgs = soup.find_all("img")
                print(f"Found {len(imgs)} images:")
                for img in imgs:
                    src = img.get("src")
                    onclick = img.get("onclick")
                    print(f"  Img: src='{src}', onclick='{onclick}'")
                    
                # Look for onclick events in other elements
                onclicks = soup.find_all(onclick=True)
                print(f"Found {len(onclicks)} elements with onclick:")
                for el in onclicks:
                    print(f"  {el.name}: text='{el.get_text(strip=True)[:50]}', onclick='{el.get('onclick')}'")

            except Exception as e:
                print(f"Error clicking/inspecting: {e}")
        else:
            print("No ViewQuestion targets found!")

        browser.close()

if __name__ == "__main__":
    main()
