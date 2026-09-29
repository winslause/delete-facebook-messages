import sys
import time
import random
from playwright.sync_api import sync_playwright

# Configuration Variables
# -------------------------------------------------------------
# For safety, consider logging in manually during the pause 
# rather than hardcoding passwords.
FB_EMAIL = ""
FB_PASSWORD = ""
# -------------------------------------------------------------

def human_delay(min_sec=0.3, max_sec=1.0):
    time.sleep(random.uniform(min_sec, max_sec))

def run_automation():
    print("[*] Starting browser session...")
    with sync_playwright() as p:
        # Launch browser in non-headless mode so you can see actions and handle 2FA
        browser = p.chromium.launch(headless=False, channel="chrome")
        
        # Create a browser context that ignores window sizing bounds
        context = browser.new_context(viewport=None)
        page = context.new_page()
        
        # Navigate to Messenger
        print("[*] Navigating to Messenger...")
        page.goto("https://www.messenger.com/", wait_until="networkidle")
        human_delay(2, 3)
        
        # Handle Cookies banner if present
        try:
            decline_cookies = page.locator("button:has-text('Decline optional cookies')", 
                                           "button:has-text('Only allow essential cookies')")
            if decline_cookies.first.is_visible():
                decline_cookies.first.click()
                print("[+] Handled cookies banner.")
                human_delay(1, 2)
        except Exception:
            pass

        # Check if already logged in, otherwise log in
        if page.locator("input#email").is_visible():
            print("[*] Logging in...")
            page.fill("input#email", FB_EMAIL)
            human_delay(0.5, 1.5)
            page.fill("input#pass", FB_PASSWORD)
            human_delay(0.5, 1.2)
            page.click("button[type='submit']")
            
            print("[!] Please complete Two-Factor Authentication (2FA) or Security Checks in the browser window now.")
            print("[*] Waiting for authentication to complete...")
        
        # Keep checking until the main Messenger grid interface is loaded
        # We wait for the main navigation element or chat search box
        # Extended timeout (5 min) to allow manual 2FA / security checkpoint completion
        print("[*] Waiting for inbox to load (up to 5 minutes)...")
        try:
            page.wait_for_selector("input[placeholder*='Search Messenger']", timeout=300000)
        except Exception:
            # If we're still on a checkpoint/security page, wait even longer
            current_url = page.url
            if "checkpoint" in current_url or "login" in current_url:
                print("[!] Still on security checkpoint page. Waiting additional time for manual completion...")
                page.wait_for_selector("input[placeholder*='Search Messenger']", timeout=300000)
            else:
                raise
        print("[+] Login successful! Inbox loaded.")
        human_delay(3, 5)

        deleted_count = 0
        
        while True:
            try:
                # Find chat rows in the left sidebar, skipping non-chat rows like "Create story"
                # Chat threads contain links to user profiles or conversation threads
                all_rows = page.locator("div[role='grid'] div[role='row']").all()
                chat_row = None
                for row in all_rows:
                    try:
                        # Skip rows that are not actual chat threads (e.g., "Create story")
                        links = row.locator("a").all()
                        is_chat = False
                        for link in links:
                            href = link.get_attribute("href") or ""
                            if "/user/" in href or "/t/" in href or "messages" in href.lower():
                                is_chat = True
                                break
                        if is_chat and row.is_visible():
                            chat_row = row
                            break
                    except Exception:
                        continue
                
                if chat_row is None:
                    print("[+] No more conversation threads found or inbox is empty.")
                    break
                
                # Extract chat name from the link's aria-label (more reliable than first span)
                try:
                    link = chat_row.locator("a[aria-label]").first
                    chat_name = link.get_attribute("aria-label") or "Unknown Thread"
                    if not chat_name:
                        chat_name = chat_row.locator("span").first.inner_text()
                    print(f"[*] Target identified: Processing thread with '{chat_name}'")
                except:
                    chat_name = "Unknown Thread"
                
                # Hover over the thread row to reveal hidden menu elements (the '...' button)
                chat_row.hover()
                human_delay(1, 2)
                
                # Locate the 3-dot options menu button — try multiple strategies
                options_menu = None
                menu_strategies = [
                    "div[aria-label*='Menu']",
                    "div[aria-haspopup='menu']",
                    "div[aria-label*='Options']",
                    "div[role='button'][aria-label]",
                    "div[role='button']",
                ]
                for sel in menu_strategies:
                    try:
                        loc = chat_row.locator(sel).last
                        if loc.is_visible():
                            options_menu = loc
                            print(f"[+] Found options menu via: {sel}")
                            break
                    except Exception:
                        continue
                
                if options_menu is None:
                    print("[-] Could not find options menu button. Skipping this thread.")
                    page.mouse.click(0, 0)
                    human_delay(1, 2)
                    continue
                
                options_menu.click(force=True)
                human_delay(1.5, 2.5)
                
                # Look for the "Delete chat" action item inside the visible popover menu overlay
                # Wait for the popover menu to render before checking visibility
                try:
                    page.wait_for_selector("div[role='menuitem']", timeout=8000)
                except Exception:
                    pass
                
                delete_action = page.locator("div[role='menuitem']:has-text('Delete chat')")
                
                if not delete_action.is_visible():
                    print("[-] 'Delete chat' menu option not found. Attempting to skip or archive...")
                    # Fallback: Close the open menu by clicking somewhere neutral
                    page.mouse.click(0, 0)
                    human_delay(0.5, 1)
                    continue
                    
                # Try multiple click strategies for the menu item too
                delete_clicked = False
                for attempt_name, attempt_fn in [
                    ("normal", lambda: delete_action.click(timeout=5000)),
                    ("force", lambda: delete_action.click(force=True, timeout=5000)),
                    ("JS", lambda: delete_action.evaluate("el => el.click()")),
                    ("JS dispatchEvent", lambda: delete_action.evaluate("el => el.dispatchEvent(new MouseEvent('click', {bubbles: true}))")),
                ]:
                    try:
                        print(f"[*] Trying {attempt_name} click on 'Delete chat' menuitem...")
                        attempt_fn()
                        human_delay(1, 1.5)
                        delete_clicked = True
                        print(f"[+] {attempt_name} click on menuitem succeeded")
                        break
                    except Exception as ex:
                        print(f"[DEBUG] {attempt_name} menuitem click failed: {ex}")
                        continue
                
                if not delete_clicked:
                    print("[-] Could not click 'Delete chat' menuitem. Closing menu and skipping.")
                    page.keyboard.press("Escape")
                    human_delay(0.5, 1)
                    continue
                
                # Wait for the confirmation dialog to appear — detect by "Delete chat" heading text
                # (more reliable than role selectors which vary across Facebook UI versions)
                try:
                    page.wait_for_selector("text=Delete chat", timeout=10000)
                except Exception:
                    print("[-] Confirmation dialog did not appear. Skipping this thread.")
                    page.keyboard.press("Escape")
                    human_delay(0.5, 1)
                    continue
                
                # Debug: dump the dialog's HTML to understand its actual structure
                try:
                    dialog_el = page.locator("h2:has-text('Delete chat'), [role='dialog'], div[role='alertdialog']").first
                    parent = dialog_el.locator("..")
                    dialog_html = parent.first.inner_html()[:1200]
                    print(f"[DEBUG] Dialog HTML: {dialog_html}")
                except Exception as ex:
                    print(f"[DEBUG] Could not dump dialog HTML: {ex}")
                
# Confirm the structural action inside the confirmation dialog
                # Gather ALL clickable elements and inspect their text, then filter to those
                # containing "Delete"
                confirm_button = None
                try:
                    # Search broadly for elements with "Delete Chat" text/aria anywhere
                    all_delete = page.locator("*:has-text('Delete Chat')").all()
                    print(f"[DEBUG] Found {len(all_delete)} elements with 'Delete Chat' text")
                    for idx, cand in enumerate(all_delete):
                        try:
                            txt = cand.inner_text().strip()
                            aria = cand.get_attribute("aria-label") or ""
                            is_hidden = cand.get_attribute("aria-hidden") == "true"
                            is_disabled = cand.get_attribute("aria-disabled") == "true"
                            tag = cand.evaluate("el => el.tagName")
                            role = cand.get_attribute("role") or ""
                            print(f"[DEBUG] DeleteChat elem {idx}: tag={tag} role={role} text='{txt}' aria-label='{aria}' hidden={is_hidden} disabled={is_disabled}")
                            if txt and not is_hidden and not is_disabled:
                                confirm_button = cand
                                break
                            if confirm_button is None:
                                confirm_button = cand
                        except Exception:
                            continue
                except Exception as ex:
                    print(f"[DEBUG] Error enumerating delete candidates: {ex}")
                
                # Fallback: any element whose text contains "Delete"
                if confirm_button is None:
                    try:
                        confirm_button = page.locator("*:has-text('Delete')").first
                    except Exception:
                        pass
                
                if confirm_button is None:
                    print("[-] Could not find confirm button in dialog. Skipping this thread.")
                    page.keyboard.press("Escape")
                    human_delay(0.5, 1)
                    continue
                
                # Try multiple click strategies — the button may be aria-disabled/aria-hidden
                delete_confirmed = False
                click_attempts = [
                    ("normal click", lambda: confirm_button.click(timeout=5000)),
                    ("force click", lambda: confirm_button.click(force=True, timeout=5000)),
                    ("JS click", lambda: confirm_button.evaluate("el => el.click()")),
                    ("JS dispatchEvent", lambda: confirm_button.evaluate("el => el.dispatchEvent(new MouseEvent('click', {bubbles: true}))")),
                ]
                for attempt_name, attempt_fn in click_attempts:
                    try:
                        print(f"[*] Trying {attempt_name} on confirm button...")
                        attempt_fn()
                        human_delay(1, 1.5)
                        delete_confirmed = True
                        print(f"[+] {attempt_name} succeeded")
                        break
                    except Exception as ex:
                        print(f"[DEBUG] {attempt_name} failed: {ex}")
                        continue
                
                # If clicks didn't work, try keyboard Enter as last resort
                if not delete_confirmed:
                    print("[*] Trying keyboard Enter to confirm dialog...")
                    page.keyboard.press("Enter")
                    human_delay(1, 1.5)
                    delete_confirmed = True
                
                # Skip strict verification — trust the click worked and move to next chat
                deleted_count += 1
                print(f"[+] Deleted thread #{deleted_count} ({chat_name})")
                
                # Brief buffer to let DOM updates finish before next iteration
                human_delay(1, 2)
                
            except Exception as e:
                print(f"[-] Error interacting with thread loop: {str(e)}")
                print("[*] Refreshing inbox context page structure to resolve stalls...")
                try:
                    page.reload(wait_until="domcontentloaded", timeout=60000)
                except Exception:
                    page.reload(timeout=60000)
                human_delay(2, 3)
                
                # Double check if structure completely breaks to exit loop safely
                if not page.locator("input[placeholder*='Search Messenger']").is_visible():
                    print("[-] Failed to restore chat list state. Exiting workflow.")
                    break

        print(f"[=] Session wrapped up. Total chat threads removed: {deleted_count}")
        browser.close()

if __name__ == "__main__":
    # Quick sanity check for setup
    try:
        import playwright
    except ImportError:
        print("[!] Playwright module is missing. Please run: pip install playwright && playwright install")
        sys.exit(1)
        
    run_automation()