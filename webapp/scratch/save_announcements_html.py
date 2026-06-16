import os
import sys
from playwright.sync_api import sync_playwright
from dotenv import load_dotenv

env_path = r"c:\Users\Jovan Fernandes\OneDrive\Documents\mcb  int\mcb-to-notion-sync\.env"
load_dotenv(env_path)

MCB_USERNAME = os.getenv("MCB_USERNAME")
MCB_PASSWORD = os.getenv("MCB_PASSWORD")

def find_login_scope(page):
    password_selectors = ["input[type='password']", "input#txtPassword", "input#txtPass"]
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

        print("Navigating to login URL...")
        page.goto("https://rainbow.myclassboard.com/Account/Login", wait_until="commit", timeout=60000)
        page.wait_for_timeout(5000)
        
        try:
            btn = page.locator("text=Click here to Login").first
            if btn.count() > 0:
                btn.click()
                page.wait_for_timeout(3000)
        except Exception:
            pass

        scope = find_login_scope(page)
        username_selectors = ["input#txtUserName", "input#txtUsername", "input#username"]
        password_selectors = ["input#txtPassword", "input#password"]
        
        try_fill_first_matching([scope.locator(s) for s in username_selectors], MCB_USERNAME)
        try_fill_first_matching([scope.locator(s) for s in password_selectors], MCB_PASSWORD)
        
        login_btn = find_first_match(scope, ["#LogID", "#btnLogin", "button:has-text('Login')"])
        if login_btn:
            login_btn.click()
        else:
            page.keyboard.press("Enter")
            
        page.wait_for_timeout(10000)
        print("Login successful.")

        print("Clicking Announcements tab...")
        try:
            ann_tab = page.locator("a:has-text('Announcements'), li:has-text('Announcements'), button:has-text('Announcements')").first
            ann_tab.click()
            page.wait_for_timeout(7000)
            print("Announcements tab loaded.")
            
            html = page.content()
            with open("webapp/scratch/announcements.html", "w", encoding="utf-8") as f:
                f.write(html)
            print("Saved announcements.html successfully.")
        except Exception as e:
            print(f"Failed: {e}")
            
        browser.close()

if __name__ == "__main__":
    main()
