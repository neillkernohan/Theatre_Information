#!/usr/bin/env python3
"""
Remove patrons with a specific role from the "Volunteers" mailing list in ArtsPeople.

1. Query local database for patrons whose Notes contain the specified role
2. Look up each patron in ArtsPeople by email
3. If they are on the Volunteers list, remove them by clicking the trash icon
4. Exit the record

Usage:
    python3 RemoveRoleFromVolunteersList.py "Band"
    python3 RemoveRoleFromVolunteersList.py "Lighting Operator"
"""

import os
import sys
import time
from datetime import datetime
import mysql.connector
from selenium import webdriver
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import (
    NoSuchElementException,
    TimeoutException,
    StaleElementReferenceException,
)
from dotenv import load_dotenv

# Load env from same directory as this script
script_dir = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(script_dir, ".env"))

NEON_EMAIL = os.getenv("NEON_EMAIL")
NEON_PASSWORD = os.getenv("NEON_PASSWORD")
MYSQL_HOST = os.getenv("MYSQL_HOST")
MYSQL_USER = os.getenv("MYSQL_USER")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE")

PEOPLE_URL = "https://app.arts-people.com/admin/legacyurl/1090"


def timestamp():
    return datetime.now().strftime("%H:%M:%S")


def log(icon, message):
    print(f"  {icon}  [{timestamp()}] {message}")


def get_patrons_with_role(role):
    """Query local DB for patrons whose Notes contain '// <role>' and who are on the Volunteers list."""
    db = mysql.connector.connect(
        host=MYSQL_HOST,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DATABASE,
    )
    cursor = db.cursor()
    cursor.execute(
        "SELECT First_name, Last_name, Email, Notes "
        "FROM Patrons "
        "WHERE Notes LIKE %s "
        "AND Marketing_Lists LIKE %s "
        "AND Email IS NOT NULL AND Email != ''",
        (f"%// {role}%", "%Volunteers%"),
    )
    results = cursor.fetchall()
    db.close()

    # Filter to only those whose ONLY roles are the specified role
    # (i.e. every line in their notes ends with "// <role>")
    filtered = []
    for row in results:
        notes = row[3] or ""
        lines = [l.strip() for l in notes.strip().splitlines() if l.strip()]
        all_match = all(line.endswith(f"// {role}") for line in lines)
        if all_match:
            filtered.append({
                "first_name": row[0] or "",
                "last_name": row[1] or "",
                "email": row[2] or "",
                "notes": notes,
            })

    return filtered


def login(driver):
    """Log into ArtsPeople via Neon SSO."""
    log("🔑", "Logging into Neon SSO...")
    driver.get("https://app.neonsso.com/login")

    email_input = WebDriverWait(driver, 15).until(
        EC.presence_of_element_located((By.ID, "email"))
    )
    email_input.send_keys(NEON_EMAIL)

    driver.find_element(By.XPATH, "//button[normalize-space()='Next']").click()

    password_input = WebDriverWait(driver, 15).until(
        EC.element_to_be_clickable((By.ID, "password"))
    )
    password_input.send_keys(NEON_PASSWORD)

    driver.find_element(By.XPATH, "//button[normalize-space()='Log In']").click()

    WebDriverWait(driver, 15).until(
        EC.presence_of_element_located(
            (By.XPATH, "//a[normalize-space()='Open']")
        )
    ).click()

    WebDriverWait(driver, 30).until(
        EC.url_contains("dashboard")
    )
    log("✅", "Logged in successfully.")

    navigate_to_people_page(driver)


def navigate_to_people_page(driver):
    driver.get(PEOPLE_URL)
    WebDriverWait(driver, 30).until(
        EC.presence_of_element_located((By.ID, "BTNlookupExisting"))
    )


def clear_screen(driver):
    try:
        clear_btn = driver.find_element(By.ID, "BTNpatron_clear_btn")
        clear_btn.click()
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "BTNlookupExisting"))
        )
        time.sleep(0.5)
    except Exception:
        navigate_to_people_page(driver)


def lookup_by_email(driver, email):
    email_field = driver.find_element(By.ID, "TXT3293")
    email_field.clear()
    email_field.send_keys(email)

    driver.find_element(By.ID, "BTNlookupExisting").click()

    time.sleep(2)

    try:
        driver.find_element(By.XPATH, "//*[contains(text(),'Select Customer')]")
        return "multiple"
    except NoSuchElementException:
        pass

    try:
        driver.find_element(By.XPATH, "//*[contains(text(),'No customers found')]")
        return False
    except NoSuchElementException:
        try:
            WebDriverWait(driver, 5).until(
                EC.presence_of_element_located(
                    (By.XPATH, "//input[@value='Exit Record']")
                )
            )
            return True
        except TimeoutException:
            return False


def remove_from_volunteers_list(driver):
    """
    Remove the current patron from the Volunteers list by hovering over the
    Volunteers row to reveal the controls, then clicking the delete icon.
    The row structure is:
      div.mailing-list-item.row.ap-row-more
        div.ng-binding  (list name text)
        div.row-more    (contains i.apicon-more "..." — visible by default)
        div.row-controls (contains i.apicon-delete and i.apicon-view — hidden until hover)
    Returns True if removed, False if not on the list or couldn't remove.
    """
    try:
        # Scroll to the Lists section
        driver.execute_script("window.scrollTo(0, 500);")
        time.sleep(0.5)

        # Find the Volunteers row among all mailing-list-item rows
        list_rows = driver.find_elements(By.CSS_SELECTOR, ".mailing-list-item")
        volunteers_row = None
        for row in list_rows:
            try:
                name_el = row.find_element(By.CSS_SELECTOR, ".ng-binding")
                if name_el.text.strip() == "Volunteers":
                    volunteers_row = row
                    break
            except (NoSuchElementException, StaleElementReferenceException):
                continue

        if volunteers_row is None:
            return False

        # Hover over the row to reveal the controls (hides .row-more, shows .row-controls)
        driver.execute_script("arguments[0].scrollIntoView(true);", volunteers_row)
        time.sleep(0.3)
        ActionChains(driver).move_to_element(volunteers_row).perform()
        time.sleep(0.5)

        # Click the delete icon (i.apicon-delete) which calls vm.deletePatronFromList(list)
        delete_icon = volunteers_row.find_element(By.CSS_SELECTOR, "i.apicon-delete")
        driver.execute_script("arguments[0].click();", delete_icon)
        time.sleep(1)

        # Handle any confirmation dialog
        try:
            confirm_btn = WebDriverWait(driver, 3).until(
                EC.presence_of_element_located(
                    (By.XPATH,
                     "//button[normalize-space()='OK' or normalize-space()='Yes' "
                     "or normalize-space()='Confirm' or normalize-space()='Delete' "
                     "or normalize-space()='Remove']")
                )
            )
            confirm_btn.click()
            time.sleep(1)
        except TimeoutException:
            # No confirmation dialog — removal was immediate
            pass

        return True

    except Exception as e:
        log("❌", f"  Error removing from Volunteers list: {e}")
        return False


def exit_record(driver):
    try:
        exit_btn = driver.find_element(
            By.XPATH, "//input[@value='Exit Record']"
        )
        driver.execute_script("arguments[0].click();", exit_btn)
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "BTNlookupExisting"))
        )
        time.sleep(0.5)
    except Exception:
        navigate_to_people_page(driver)


def main():
    if len(sys.argv) < 2:
        print('Usage: python3 RemoveRoleFromVolunteersList.py "Band"')
        print('       python3 RemoveRoleFromVolunteersList.py "Lighting Operator"')
        sys.exit(1)

    role = sys.argv[1]

    log("🔄", f'Removing patrons with ONLY "{role}" role(s) from Volunteers list')

    patrons = get_patrons_with_role(role)
    log("📋", f"Found {len(patrons)} patrons whose only role(s) are \"{role}\"")

    if not patrons:
        log("✅", "Nothing to do")
        return

    # Show the list for confirmation
    print()
    for i, p in enumerate(patrons, 1):
        notes_preview = p["notes"].replace("\n", " | ")
        if len(notes_preview) > 80:
            notes_preview = notes_preview[:77] + "..."
        print(f"  {i:3}. {p['first_name']} {p['last_name']} ({p['email']})")
        print(f"       Notes: {notes_preview}")
    print()
    confirm = input(f"  Remove these {len(patrons)} patrons from Volunteers list? (y/n): ")
    if confirm.strip().lower() != "y":
        log("🚫", "Cancelled")
        return

    removed_count = 0
    not_on_list_count = 0
    not_found_count = 0
    multiple_count = 0
    error_count = 0

    driver = webdriver.Chrome()
    driver.maximize_window()

    try:
        login(driver)

        for seq, patron in enumerate(patrons, 1):
            email = patron["email"]
            first = patron["first_name"]
            last = patron["last_name"]

            log("👤", f"[{seq}/{len(patrons)}] {first} {last} ({email})")

            try:
                clear_screen(driver)
                found = lookup_by_email(driver, email)

                if found == "multiple":
                    log("⚠️", "  MULTIPLE MATCHES — please select the correct patron")
                    input("  ⏸️  Press Enter after you've selected the patron...")
                    try:
                        WebDriverWait(driver, 5).until(
                            EC.presence_of_element_located(
                                (By.XPATH, "//input[@value='Exit Record']")
                            )
                        )
                        multiple_count += 1
                    except TimeoutException:
                        log("❌", "  No patron record loaded — skipping")
                        error_count += 1
                        navigate_to_people_page(driver)
                        continue
                elif not found:
                    log("⚠️", "  Not found in ArtsPeople — skipping")
                    not_found_count += 1
                    continue

                was_removed = remove_from_volunteers_list(driver)
                if was_removed:
                    log("✅", f"  Removed from Volunteers list")
                    removed_count += 1
                else:
                    log("ℹ️", "  Not on Volunteers list — skipping")
                    not_on_list_count += 1

                exit_record(driver)

            except Exception as e:
                log("❌", f"  Error processing: {e}")
                error_count += 1
                try:
                    navigate_to_people_page(driver)
                except Exception:
                    pass

    finally:
        print("\n" + "=" * 50)
        print("  SUMMARY")
        print("=" * 50)
        print(f'  Role filtered:         "{role}"')
        print(f"  Total patrons:         {len(patrons)}")
        print(f"  Removed from list:     {removed_count}")
        print(f"  Not on list:           {not_on_list_count}")
        print(f"  Not found on AP:       {not_found_count}")
        print(f"  Multiple matches:      {multiple_count}")
        print(f"  Errors:                {error_count}")
        print("=" * 50)

        input("\nPress Enter to close the browser...")
        driver.quit()


if __name__ == "__main__":
    main()
