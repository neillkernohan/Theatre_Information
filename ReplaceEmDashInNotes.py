#!/usr/bin/env python3
"""
Replace " — " (em dash) with " // " in the "Note to House Manager" field
on ArtsPeople for all patrons whose Notes contain an em dash.

1. Query local database for patrons with " — " in Notes
2. Look up each patron in ArtsPeople by email
3. Replace " — " with " // " in the Note to House Manager field
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
from selenium.common.exceptions import (
    NoSuchElementException,
    TimeoutException,
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
NOTE_FIELD_ID = "TXT109000026"

OLD_SEP = " \u2014 "   # em dash
NEW_SEP = " // "


def timestamp():
    return datetime.now().strftime("%H:%M:%S")


def log(icon, message):
    print(f"  {icon}  [{timestamp()}] {message}")


def get_patrons_with_emdash():
    """Query local DB for patrons whose Notes contain an em dash."""
    db = mysql.connector.connect(
        host=MYSQL_HOST,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DATABASE,
    )
    cursor = db.cursor()
    cursor.execute(
        "SELECT First_name, Last_name, Email, Notes "
        "FROM Patrons WHERE Notes LIKE %s AND Email IS NOT NULL AND Email != ''",
        (f"%{OLD_SEP}%",),
    )
    results = cursor.fetchall()
    db.close()
    return [
        {
            "first_name": row[0] or "",
            "last_name": row[1] or "",
            "email": row[2] or "",
            "notes": row[3] or "",
        }
        for row in results
    ]


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


def replace_emdash_in_note(driver):
    """
    Read the Note to House Manager field, replace em dash with //,
    and write it back.
    Returns True if a replacement was made, False if no em dash found.
    """
    note_field = driver.find_element(By.ID, NOTE_FIELD_ID)
    driver.execute_script("arguments[0].scrollIntoView(true);", note_field)
    time.sleep(0.3)

    existing = note_field.get_attribute("value") or ""

    if OLD_SEP not in existing:
        return False

    new_value = existing.replace(OLD_SEP, NEW_SEP)
    note_field.clear()
    note_field.send_keys(new_value)
    time.sleep(0.3)
    return True


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
    patrons = get_patrons_with_emdash()
    log("📋", f"Found {len(patrons)} patrons with em dash in Notes")

    replaced_count = 0
    skipped_count = 0
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
                    input("  Press Enter after you've selected the patron...")
                    # Wait for patron record to load after manual selection
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

                was_replaced = replace_emdash_in_note(driver)
                if was_replaced:
                    log("✅", f"  Replaced ' — ' with ' // '")
                    update_patron_record(driver)
                    replaced_count += 1
                else:
                    log("ℹ️", "  No em dash found in ArtsPeople note — skipping")
                    skipped_count += 1

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
        print(f"  Total patrons:         {len(patrons)}")
        print(f"  Replaced:              {replaced_count}")
        print(f"  No em dash on AP:      {skipped_count}")
        print(f"  Not found on AP:       {not_found_count}")
        print(f"  Multiple matches:      {multiple_count}")
        print(f"  Errors:                {error_count}")
        print("=" * 50)

        input("\nPress Enter to close the browser...")
        driver.quit()


if __name__ == "__main__":
    main()
