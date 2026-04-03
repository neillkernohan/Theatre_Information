#!/usr/bin/env python3
"""
Add anyone with a Show // Role in their ArtsPeople record to the Volunteers list.
1. Query local DB for patrons with '//' in Notes
2. Look up each in ArtsPeople by email
3. If not already on the Volunteers list, add them
4. Update and exit the record
"""

import os
import time
from datetime import datetime
import mysql.connector
from selenium import webdriver
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
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
VOLUNTEERS_LIST_NAME = "Volunteers"


def timestamp():
    return datetime.now().strftime("%H:%M:%S")


def log(icon, message):
    print(f"  {icon}  [{timestamp()}] {message}")


def get_patrons_with_roles():
    """Query local DB for patrons whose Notes contain '//'."""
    db = mysql.connector.connect(
        host=MYSQL_HOST,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DATABASE,
    )
    cursor = db.cursor()
    cursor.execute(
        "SELECT First_name, Last_name, Email, Marketing_Lists "
        "FROM Patrons WHERE Notes LIKE %s AND Email IS NOT NULL AND Email != ''",
        ("%//%",),
    )
    results = cursor.fetchall()
    db.close()

    patrons = []
    for row in results:
        marketing_lists = row[3] or ""
        # Check if already on Volunteers list in the database
        list_items = [item.strip() for item in marketing_lists.split(";")]
        already_volunteer = "Volunteers" in list_items
        patrons.append({
            "first_name": row[0] or "",
            "last_name": row[1] or "",
            "email": row[2] or "",
            "already_volunteer": already_volunteer,
        })
    return patrons


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

    # Check for "Select Customer" page (multiple matches)
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


def is_on_volunteers_list(driver):
    """Check if the current patron is already on the Volunteers list."""
    try:
        elements = driver.find_elements(
            By.XPATH,
            "//h2[contains(text(),'Lists')]/following-sibling::*"
            "//*[normalize-space()='Volunteers'] | "
            "//*[contains(text(),'Lists')]"
            "/following::*[normalize-space()='Volunteers']"
        )
        for el in elements:
            try:
                if "Volunteers" in el.text:
                    return True
            except StaleElementReferenceException:
                continue
        return False
    except Exception:
        return False


def add_to_volunteers_list(driver):
    """Add the current patron to the Volunteers list."""
    try:
        driver.execute_script("window.scrollTo(0, 500);")
        time.sleep(0.5)

        # Click "Add to List" button
        add_btn = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located(
                (By.XPATH, "//button[normalize-space()='Add to List']")
            )
        )
        driver.execute_script("arguments[0].scrollIntoView(true);", add_btn)
        time.sleep(0.5)
        driver.execute_script("arguments[0].click();", add_btn)
        time.sleep(1)

        # Wait for the slide-out panel
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located(
                (By.XPATH, "//*[contains(text(),'Add patron to lists')]")
            )
        )

        # Find and click "Volunteers"
        volunteers_item = None
        try:
            volunteers_item = driver.find_element(
                By.XPATH,
                "//div[contains(@class,'add-patron-to-lists')]"
                "//span[normalize-space()='Volunteers'] | "
                "//div[contains(@class,'add-patron-to-lists')]"
                "//*[normalize-space()='Volunteers']"
            )
        except NoSuchElementException:
            try:
                volunteers_item = driver.find_element(
                    By.XPATH,
                    "//*[contains(text(),'Add patron to lists')]"
                    "/following::*[normalize-space()='Volunteers']"
                )
            except NoSuchElementException:
                pass

        if volunteers_item is None:
            log("ℹ️", "  'Volunteers' not in add list (may already be on it)")
            driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
            time.sleep(0.5)
            return True

        volunteers_item.click()
        time.sleep(0.5)

        # Click confirm "Add to List" button in panel
        panel_add_btn = driver.find_element(
            By.CSS_SELECTOR,
            "button.mailing-list-add-to-list:not(.ng-scope)"
        )
        driver.execute_script("arguments[0].click();", panel_add_btn)
        time.sleep(1)

        return True

    except Exception as e:
        log("❌", f"  Error adding to list: {e}")
        return False


def update_patron_record(driver):
    try:
        update_btn = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located(
                (By.XPATH, "//input[@value='Update Patron Record']")
            )
        )
        driver.execute_script("arguments[0].scrollIntoView(true);", update_btn)
        time.sleep(0.5)
        driver.execute_script("arguments[0].click();", update_btn)
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located(
                (By.XPATH, "//input[@value='Exit Record']")
            )
        )
        time.sleep(1)
        log("✅", "  Patron record updated")
    except Exception as e:
        log("⚠️", f"  Could not update patron record: {e}")


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
    all_patrons = get_patrons_with_roles()

    # Split into already on list vs need to process
    already_in_db = [p for p in all_patrons if p["already_volunteer"]]
    to_process = [p for p in all_patrons if not p["already_volunteer"]]

    log("📋", f"Found {len(all_patrons)} patrons with Show // Role in Notes")
    log("ℹ️", f"  {len(already_in_db)} already on Volunteers list (per database) — skipping")
    log("ℹ️", f"  {len(to_process)} to check/add in ArtsPeople")

    added_count = 0
    already_on_list_count = len(already_in_db)
    not_found_count = 0
    multiple_count = 0
    error_count = 0

    if not to_process:
        print("\nAll patrons are already on the Volunteers list. Nothing to do.")
        return

    driver = webdriver.Chrome()
    driver.maximize_window()

    try:
        login(driver)

        for seq, patron in enumerate(to_process, 1):
            email = patron["email"]
            first = patron["first_name"]
            last = patron["last_name"]

            log("👤", f"[{seq}/{len(to_process)}] {first} {last} ({email})")

            try:
                clear_screen(driver)
                found = lookup_by_email(driver, email)

                if found == "multiple":
                    log("⚠️", "  MULTIPLE MATCHES — please select the correct patron")
                    input("  Press Enter after you've selected the patron...")
                    WebDriverWait(driver, 30).until(
                        EC.presence_of_element_located(
                            (By.XPATH, "//input[@value='Exit Record']")
                        )
                    )
                    multiple_count += 1
                elif not found:
                    log("⚠️", "  Not found in ArtsPeople — skipping")
                    not_found_count += 1
                    continue

                # Check if already on Volunteers list
                if is_on_volunteers_list(driver):
                    log("ℹ️", "  Already on Volunteers list")
                    already_on_list_count += 1
                else:
                    if add_to_volunteers_list(driver):
                        log("✅", "  Added to Volunteers list")
                        update_patron_record(driver)
                        added_count += 1
                    else:
                        log("❌", "  Failed to add to Volunteers list")
                        error_count += 1

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
        print(f"  Total patrons w/ roles:  {len(all_patrons)}")
        print(f"  Skipped (already in DB): {len(already_in_db)}")
        print(f"  Added to Volunteers:     {added_count}")
        print(f"  Already on list (AP):    {already_on_list_count - len(already_in_db)}")
        print(f"  Not found on AP:         {not_found_count}")
        print(f"  Multiple matches:        {multiple_count}")
        print(f"  Errors:                  {error_count}")
        print("=" * 50)

        input("\nPress Enter to close the browser...")
        driver.quit()


if __name__ == "__main__":
    main()
