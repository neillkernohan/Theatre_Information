#!/usr/bin/env python3
"""
Add volunteers from CSV to ArtsPeople.
For each volunteer:
  1. Search by email in ArtsPeople
  2. If found, add to "Volunteers" list (if not already on it)
  3. If not found, create the patron record, then add to "Volunteers" list
"""

import csv
import os
import time
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
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

CSV_FILE = os.path.join(script_dir, "Volunteers from Ruth.csv")

VOLUNTEERS_LIST_NAME = "Volunteers"

# ArtsPeople People page
PEOPLE_URL = "https://app.arts-people.com/admin/legacyurl/1090"


def timestamp():
    return datetime.now().strftime("%H:%M:%S")


def log(icon, message):
    print(f"  {icon}  [{timestamp()}] {message}")


def login(driver):
    """Log into ArtsPeople via Neon SSO."""
    log("🔑", "Logging into Neon SSO...")
    driver.get("https://app.neonsso.com/login")

    # Enter email
    email_input = WebDriverWait(driver, 15).until(
        EC.presence_of_element_located((By.ID, "email"))
    )
    email_input.send_keys(NEON_EMAIL)

    # Click Next
    driver.find_element(By.XPATH, "//button[normalize-space()='Next']").click()

    # Enter password
    password_input = WebDriverWait(driver, 15).until(
        EC.element_to_be_clickable((By.ID, "password"))
    )
    password_input.send_keys(NEON_PASSWORD)

    # Click Log In
    driver.find_element(By.XPATH, "//button[normalize-space()='Log In']").click()

    # Wait for the "Open" link to appear, then click it
    WebDriverWait(driver, 15).until(
        EC.presence_of_element_located(
            (By.XPATH, "//a[normalize-space()='Open']")
        )
    ).click()

    # Wait for ArtsPeople dashboard to load
    WebDriverWait(driver, 30).until(
        EC.url_contains("dashboard")
    )
    log("✅", "Logged in successfully.")

    # Navigate to the People page
    navigate_to_people_page(driver)


def navigate_to_people_page(driver):
    """Navigate to the Database > People page."""
    driver.get(PEOPLE_URL)
    WebDriverWait(driver, 30).until(
        EC.presence_of_element_located((By.ID, "BTNlookupExisting"))
    )


def clear_screen(driver):
    """Click Clear Screen to reset the form."""
    try:
        clear_btn = driver.find_element(By.ID, "BTNpatron_clear_btn")
        clear_btn.click()
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "BTNlookupExisting"))
        )
        time.sleep(0.5)
    except Exception:
        # If clear doesn't work, navigate directly
        navigate_to_people_page(driver)


def lookup_by_email(driver, email):
    """
    Search for a patron by email.
    Returns True if found (patron record loaded), False if not found.
    """
    # Enter email
    email_field = driver.find_element(By.ID, "TXT3293")
    email_field.clear()
    email_field.send_keys(email)

    # Click Lookup Existing Patron
    driver.find_element(By.ID, "BTNlookupExisting").click()

    # Wait for either the patron record to load or "No customers found"
    time.sleep(2)

    try:
        # Check for "No customers found" message
        driver.find_element(By.XPATH, "//*[contains(text(),'No customers found')]")
        return False
    except NoSuchElementException:
        # Patron was found - check that we're on a patron record
        # by looking for "Update Patron Record" or "Exit Record" button
        try:
            WebDriverWait(driver, 5).until(
                EC.presence_of_element_located(
                    (By.XPATH, "//input[@value='Exit Record']")
                )
            )
            return True
        except TimeoutException:
            return False


def create_patron(driver, first_name, last_name, email):
    """
    Create a new patron with the given details.
    Assumes we're on the People page after a failed lookup.
    """
    # First name and last name fields should already be on the page
    first_field = driver.find_element(By.ID, "TXTfirst_name")
    first_field.clear()
    first_field.send_keys(first_name)

    last_field = driver.find_element(By.ID, "TXTlast_name")
    last_field.clear()
    last_field.send_keys(last_name)

    # Email should still be filled from the lookup attempt

    # Click Save New Patron
    driver.find_element(By.ID, "BTNsave_patron").click()

    # Wait for patron record to load
    WebDriverWait(driver, 10).until(
        EC.presence_of_element_located(
            (By.XPATH, "//input[@value='Exit Record']")
        )
    )
    time.sleep(1)


def is_on_volunteers_list(driver):
    """Check if the current patron is already on the Volunteers list."""
    try:
        # On the patron page, lists the patron belongs to appear as text
        # under the "Lists" heading (e.g. "Volunteers" with a "..." menu)
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
    """
    Add the current patron to the Volunteers list.
    Assumes we're on a patron record page.
    Returns True if successful, False otherwise.
    """
    try:
        # Scroll to make sure the Lists / Add to List area is visible
        driver.execute_script("window.scrollTo(0, 500);")
        time.sleep(0.5)

        # Step 1: Click the "Add to List" button next to the "Lists" heading
        # Use JavaScript click to avoid "element click intercepted" errors
        add_btn = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located(
                (By.XPATH, "//button[normalize-space()='Add to List']")
            )
        )
        driver.execute_script("arguments[0].scrollIntoView(true);", add_btn)
        time.sleep(0.5)
        driver.execute_script("arguments[0].click();", add_btn)
        time.sleep(1)

        # Step 2: Wait for the slide-out panel "Add patron to lists" to appear
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located(
                (By.XPATH, "//*[contains(text(),'Add patron to lists')]")
            )
        )

        # Step 3: Find and click "Volunteers" in the list
        # The list items are clickable text elements in the panel
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
            # Try a broader search — find any clickable element with text "Volunteers"
            # in the panel area (right side of page)
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
            # Close panel by pressing Escape
            from selenium.webdriver.common.keys import Keys
            driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
            time.sleep(0.5)
            return True

        volunteers_item.click()
        time.sleep(0.5)

        # Step 4: Click the "Add to List" button at the top of the panel to confirm
        # From the error, we know the actual class: mailing-list-add-to-list
        # There are two such buttons — the original (ng-scope) and the panel one
        # We want the panel confirm button
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
    """Click 'Update Patron Record' to save changes."""
    try:
        update_btn = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located(
                (By.XPATH, "//input[@value='Update Patron Record']")
            )
        )
        driver.execute_script("arguments[0].scrollIntoView(true);", update_btn)
        time.sleep(0.5)
        driver.execute_script("arguments[0].click();", update_btn)
        # Wait for the page to refresh/save
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
    """Click Exit Record to go back to the search page."""
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


def read_csv():
    """Read all rows from the CSV, preserving original data for rewriting."""
    rows = []
    with open(CSV_FILE, encoding="latin-1") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        for row in reader:
            rows.append(row)
    return fieldnames, rows


def save_csv(fieldnames, rows):
    """Write updated rows back to the CSV file."""
    with open(CSV_FILE, "w", encoding="latin-1", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main():
    fieldnames, all_rows = read_csv()

    # Filter to only Transfer=Yes and not already moved
    to_process = []
    for idx, row in enumerate(all_rows):
        transfer = row.get("Transfer", "").strip().lower()
        already_moved = row.get("Moved to ArtsPeople", "").strip().lower()
        if transfer == "yes" and already_moved != "yes":
            to_process.append(idx)

    log("📋", f"Loaded {len(to_process)} volunteers to process "
        f"({len(all_rows)} total, skipping already-moved and Transfer=No)")

    # Stats
    found_count = 0
    created_count = 0
    added_to_list_count = 0
    already_on_list_count = 0
    error_count = 0
    skipped_count = len(all_rows) - len(to_process)

    driver = webdriver.Chrome()
    driver.maximize_window()

    try:
        login(driver)
        navigate_to_people_page(driver)


        for seq, row_idx in enumerate(to_process, 1):
            row = all_rows[row_idx]
            email = row.get("Email", "").strip()
            first = row.get("First Name", "").strip()
            last = row.get("Last Name", "").strip()

            log("👤", f"[{seq}/{len(to_process)}] {first} {last} ({email})")

            success = False
            try:
                # Clear and search
                clear_screen(driver)
                found = lookup_by_email(driver, email)

                if found:
                    log("✅", f"  Found in ArtsPeople")
                    found_count += 1
                else:
                    log("🆕", f"  Not found - creating new patron...")
                    create_patron(driver, first, last, email)
                    created_count += 1

                # Now on patron record - add to Volunteers list
                if is_on_volunteers_list(driver):
                    log("ℹ️", f"  Already on Volunteers list")
                    already_on_list_count += 1
                    success = True
                else:
                    if add_to_volunteers_list(driver):
                        log("✅", f"  Added to Volunteers list")
                        added_to_list_count += 1
                        success = True
                    else:
                        log("❌", f"  Failed to add to Volunteers list")
                        error_count += 1

                # Update the patron record before exiting
                update_patron_record(driver)

                # Exit back to search page
                exit_record(driver)

            except Exception as e:
                log("❌", f"  Error processing: {e}")
                error_count += 1
                # Try to recover by navigating to People page
                try:
                    navigate_to_people_page(driver)
                except Exception:
                    pass

            # Mark as moved in CSV if successful
            if success:
                all_rows[row_idx]["Moved to ArtsPeople"] = "Yes"
                save_csv(fieldnames, all_rows)

    finally:
        print("\n" + "=" * 50)
        print("  SUMMARY")
        print("=" * 50)
        print(f"  Total processed:       {found_count + created_count}")
        print(f"  Found in ArtsPeople:   {found_count}")
        print(f"  Created new patrons:   {created_count}")
        print(f"  Added to Volunteers:   {added_to_list_count}")
        print(f"  Already on list:       {already_on_list_count}")
        print(f"  Errors:                {error_count}")
        print(f"  Skipped (prev done):   {skipped_count}")
        print("=" * 50)

        input("\nPress Enter to close the browser...")
        driver.quit()


if __name__ == "__main__":
    main()
