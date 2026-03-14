#!/usr/bin/env python3

from selenium import webdriver
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
import os
import csv
import glob
from datetime import datetime
import mysql.connector
import time
from collections import Counter
import math
from dotenv import load_dotenv

load_dotenv()

BAR_WIDTH = 30


def status(icon, message):
    """Print a timestamped status message."""
    timestamp = datetime.now().strftime('%H:%M:%S')
    print(f"  {icon}  [{timestamp}] {message}")


def progress_bar(current, total, label=""):
    """Print an in-place progress bar."""
    filled = int(BAR_WIDTH * current / total) if total else BAR_WIDTH
    bar = "█" * filled + "░" * (BAR_WIDTH - filled)
    pct = int(100 * current / total) if total else 100
    print(f"\r  ⏳ {bar} {pct:3d}% {label}", end="", flush=True)
    if current >= total:
        print()  # newline when done

NEON_EMAIL = os.getenv("NEON_EMAIL")
NEON_PASSWORD = os.getenv("NEON_PASSWORD")
MYSQL_HOST = os.getenv("MYSQL_HOST")
MYSQL_USER = os.getenv("MYSQL_USER")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE")

PERSON_TYPE_MAP = {
    "General": "General",
    "General Admission": "General",
    "Regular": "Regular",
    "Senior": "Senior",
    "Student": "Student",
    "Regular - Musical": "Regular",
    "Senior - Musical": "Senior",
    "Youth": "Student",
    "Adult- Family Crow": "Regular",
    "Regular - Drag Show": "Regular",
    "Senior - Drag Show": "Senior",
    "Adult": "Regular",
    "Senior - Family Crow": "Senior",
    "Youth - Family Crow": "Student",
    "Regular - Special": "Regular",
    "Senior - Special": "Senior",
    "Student - Special": "Student",
    "Adult (Holiday Pty)": "Regular",
    "Student (Holiday Pty": "Student",
}


def find_latest_file(directory):
    if not os.path.isdir(directory):
        raise ValueError(f"The directory {directory} does not exist")
    files = [os.path.join(directory, f) for f in os.listdir(directory)]
    files = [f for f in files if os.path.isfile(f)]
    if not files:
        raise ValueError(f"No files found in {directory}")
    latest_file = max(files, key=os.path.getmtime)
    return latest_file


def delete_latest_file(filePath):
    try:
        os.remove(filePath)
    except ValueError as e:
        print(e)
    except Exception as e:
        print(f"Error deleting file: {e}")


def wait_for_download(directory, existing_files, timeout=120):
    """Wait for a new CSV file to appear that wasn't in existing_files."""
    start_time = time.time()
    while time.time() - start_time < timeout:
        elapsed = int(time.time() - start_time)
        partial_files = glob.glob(os.path.join(directory, "*.crdownload"))
        if partial_files:
            progress_bar(elapsed, timeout, "Downloading...")
        else:
            current_files = set(glob.glob(os.path.join(directory, "*.csv")))
            new_files = current_files - existing_files
            if new_files:
                progress_bar(timeout, timeout, "Download complete")
                return new_files.pop()
            progress_bar(elapsed, timeout, "Waiting for file...")
        time.sleep(1)
    print()
    raise TimeoutError(f"Download did not complete within {timeout} seconds")


def download_csv(driver, link_text, directory):
    """Navigate to a report link and download the CSV export."""
    status("📂", f"Navigating to report: {link_text}")
    existing_csvs = set(glob.glob(os.path.join(directory, "*.csv")))

    WebDriverWait(driver, 30).until(
        EC.presence_of_element_located((By.XPATH, f"(//a[normalize-space()='{link_text}'])[1]"))
    ).click()
    status("📄", "Report loaded, clicking Export CSV...")
    WebDriverWait(driver, 60).until(
        EC.presence_of_element_located((By.XPATH, "(//button[@ng-click='viewVm.exportCsv();'])[1]"))
    ).click()
    status("⬇️ ", "Export triggered, waiting for download...")
    csv_file = wait_for_download(directory, existing_csvs)
    status("✅", f"Downloaded: {os.path.basename(csv_file)}")
    return csv_file


def process_ticket_data(csv_file, db):
    """Process ticket CSV and sync with database. Returns (rows_added, rows_removed, ticket_info)."""
    print()
    print("  ╔══════════════════════════════════════════╗")
    print("  ║         🎫  TICKET DATA SYNC             ║")
    print("  ╚══════════════════════════════════════════╝")
    status("🔍", "Loading existing ticket data from database...")
    select_cursor = db.cursor()
    select_cursor.execute("SELECT Item_ID, Item_count FROM Ticket_Info")
    existing_data = {(item_id, item_count) for item_id, item_count in select_cursor}
    select_cursor.close()
    status("📊", f"Found {len(existing_data):,} existing tickets in database")

    status("📖", "Reading ticket CSV file...")
    csv_rows = []
    csv_short_rows = set()
    with open(csv_file) as f:
        reader = csv.reader(f)
        next(reader)  # Skip header
        next(reader)  # Skip first line
        for row in reader:
            csv_rows.append(row)
            csv_short_rows.add((row[10], int(row[11])))
    status("📊", f"Found {len(csv_rows):,} tickets in CSV")

    # Find new rows to insert
    batch_data = []
    ticket_info = []
    for row in csv_rows:
        if (row[10], int(row[11])) not in existing_data:
            performance_date = datetime.strptime(row[1], '%Y-%m-%d %I:%M %p').strftime('%Y-%m-%d %H:%M:%S')
            purchase_date = datetime.strptime(row[5], '%Y-%m-%d %I:%M %p').strftime('%Y-%m-%d %H:%M:%S')
            reserve_amount = row[12] if row[12] else 0
            person_type_edited = PERSON_TYPE_MAP.get(row[15], "")
            batch_data.append((
                row[0], performance_date, row[2], row[3], row[4], purchase_date,
                row[6], row[7], row[8], row[9], row[10], row[11], reserve_amount,
                row[13], row[14], row[15], person_type_edited, row[16], row[17]
            ))
            ticket_info.append((row[0], row[10]))

    rows_added = len(batch_data)
    status("🔄", f"Comparing... {rows_added:,} new tickets to insert")
    if batch_data:
        insert_cursor = db.cursor(prepared=True)
        insert_sql = """INSERT INTO Ticket_Info (Show_name, Performance_date, Price_terms, Customer, Transaction_type,
                        Purchase_date, Item_type, Dropdown_comments, Per_item_fee, CC_fee, Item_ID, Item_count,
                        Reserve_amount, Season, Amount, Person_type, Person_type_edited, Seat, Subscription_package)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"""
        try:
            db.cursor().execute("SET foreign_key_checks = 0")
            db.cursor().execute("SET unique_checks = 0")
            db.commit()
            db.cursor().execute("LOCK TABLES Ticket_Info WRITE")

            chunk_size = 1000
            num_chunks = math.ceil(len(batch_data) / chunk_size)
            for i in range(num_chunks):
                chunk = batch_data[i * chunk_size:(i + 1) * chunk_size]
                progress_bar(i + 1, num_chunks, f"Inserting chunk {i + 1}/{num_chunks}")
                insert_cursor.executemany(insert_sql, chunk)
                db.commit()
        finally:
            db.cursor().execute("UNLOCK TABLES")
            db.commit()
            db.cursor().execute("SET foreign_key_checks = 1")
            db.cursor().execute("SET unique_checks = 1")
            db.commit()
        status("✅", f"Inserted {rows_added:,} new tickets")
    else:
        status("👍", "No new tickets to insert")

    # Find rows to delete (in DB but no longer in CSV)
    delete_data = [(x[0], x[1]) for x in existing_data if (x[0], x[1]) not in csv_short_rows]
    rows_removed = len(delete_data)
    if delete_data:
        status("🗑️ ", f"Removing {rows_removed:,} stale tickets...")
        delete_cursor = db.cursor(prepared=True)
        delete_sql = "DELETE FROM Ticket_Info WHERE Item_ID = %s AND Item_count = %s"
        delete_cursor.executemany(delete_sql, delete_data)
        db.commit()
        status("✅", f"Removed {rows_removed:,} tickets")
    else:
        status("👍", "No stale tickets to remove")

    return rows_added, rows_removed, ticket_info


def process_patron_data(csv_file, db):
    """Process patron CSV: insert new patrons and update changed existing patrons."""
    print()
    print("  ╔══════════════════════════════════════════╗")
    print("  ║         👥  PATRON DATA SYNC             ║")
    print("  ╚══════════════════════════════════════════╝")
    status("🔍", "Loading existing patron data from database...")
    select_cursor = db.cursor()
    select_cursor.execute("""SELECT Patron_ID, First_name, Last_name, Organization, Assoc_Organization,
                             Address_1, Address_2, City, Province, Postal_Code, No_Email, Notes, Email
                             FROM Patrons""")
    existing_data = {}
    for row in select_cursor:
        existing_data[row[0]] = row[1:]
    select_cursor.close()
    status("📊", f"Found {len(existing_data):,} existing patrons in database")

    status("📖", "Reading patron CSV and comparing records...")
    insert_data = []
    update_data = []
    with open(csv_file) as f:
        reader = csv.reader(f)
        next(reader)  # Skip header
        for row in reader:
            no_email = 1 if row[10] == 'X' else 0
            notes = row[11] if len(row) > 11 else ""
            email = row[12] if len(row) > 12 else ""
            csv_values = (row[1], row[2], row[3], row[4], row[5],
                          row[6], row[7], row[8], row[9], no_email, notes, email)

            if row[0] not in existing_data:
                insert_data.append((row[0], *csv_values))
            else:
                db_values = existing_data[row[0]]
                # Convert DB No_Email to int for comparison
                db_comparable = (db_values[0], db_values[1], db_values[2], db_values[3],
                                 db_values[4], db_values[5], db_values[6], db_values[7],
                                 db_values[8], int(db_values[9]), db_values[10] or "", db_values[11] or "")
                if csv_values != db_comparable:
                    update_data.append((*csv_values, row[0]))

    status("🔄", f"Found {len(insert_data):,} new, {len(update_data):,} changed patrons")

    if insert_data:
        status("➕", f"Inserting {len(insert_data):,} new patrons...")
        insert_cursor = db.cursor(prepared=True)
        insert_sql = """INSERT INTO Theatre_Information.Patrons
                        (Patron_ID, First_name, Last_name, Organization, Assoc_Organization,
                         Address_1, Address_2, City, Province, Postal_Code, No_Email, Notes, Email)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"""
        insert_cursor.executemany(insert_sql, insert_data)
        db.commit()
        status("✅", f"Inserted {len(insert_data):,} new patrons")
    else:
        status("👍", "No new patrons to insert")

    if update_data:
        status("✏️ ", f"Updating {len(update_data):,} changed patrons...")
        update_cursor = db.cursor(prepared=True)
        update_sql = """UPDATE Theatre_Information.Patrons
                        SET First_name=%s, Last_name=%s, Organization=%s, Assoc_Organization=%s,
                            Address_1=%s, Address_2=%s, City=%s, Province=%s, Postal_Code=%s,
                            No_Email=%s, Notes=%s, Email=%s
                        WHERE Patron_ID=%s"""
        update_cursor.executemany(update_sql, update_data)
        db.commit()
        status("✅", f"Updated {len(update_data):,} patrons")
    else:
        status("👍", "No patron records to update")

    # Delete patrons no longer in CSV
    csv_patron_ids = set()
    with open(csv_file) as f:
        reader = csv.reader(f)
        next(reader)  # Skip header
        for row in reader:
            csv_patron_ids.add(row[0])

    delete_data = [(pid,) for pid in existing_data if pid not in csv_patron_ids]
    if delete_data:
        status("🗑️ ", f"Removing {len(delete_data):,} patrons no longer in report...")
        delete_cursor = db.cursor(prepared=True)
        delete_sql = "DELETE FROM Theatre_Information.Patrons WHERE Patron_ID = %s"
        delete_cursor.executemany(delete_sql, delete_data)
        db.commit()
        status("✅", f"Removed {len(delete_data):,} patrons")
    else:
        status("👍", "No patrons to remove")

    return len(insert_data)


def main():
    download_dir = os.path.join(os.path.expanduser("~"), "Downloads")
    driver = None
    db = None

    try:
        print()
        print("  ╔══════════════════════════════════════════╗")
        print("  ║     🎭  THEATRE DATA SYNC STARTING       ║")
        print("  ╚══════════════════════════════════════════╝")
        print()

        # Login to Neon SSO
        status("🌐", "Opening browser...")
        driver = webdriver.Chrome()
        status("🔑", "Logging in to Neon SSO...")
        driver.get("https://app.neonsso.com/login")
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, "(//input[@id='email'])[1]"))
        ).send_keys(NEON_EMAIL)
        driver.find_element(By.XPATH, "(//button[normalize-space()='Next'])[1]").click()
        WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, "(//input[@id='password'])[1]"))
        ).send_keys(NEON_PASSWORD)
        driver.find_element(By.XPATH, "(//button[normalize-space()='Log In'])[1]").click()
        WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.XPATH, "(//a[normalize-space()='Open'])[1]"))
        ).click()
        status("✅", "Login successful, opening Arts People")

        # Download and process ticket data
        ticket_csv = download_csv(driver, "All Tickets from 2014", download_dir)

        status("🗄️ ", "Connecting to database...")
        db = mysql.connector.connect(
            host=MYSQL_HOST,
            user=MYSQL_USER,
            password=MYSQL_PASSWORD,
            database=MYSQL_DATABASE,
        )
        status("✅", "Database connected")

        rows_added, rows_removed, ticket_info = process_ticket_data(ticket_csv, db)
        delete_latest_file(ticket_csv)

        # Download and process patron data
        driver.back()
        patron_csv = download_csv(driver, "Patrons since 2014", download_dir)
        process_patron_data(patron_csv, db)
        delete_latest_file(patron_csv)

        # Log the update
        status("📝", "Logging update to database...")
        update_cursor = db.cursor()
        update_sql = "INSERT INTO Updates (Update_date_time, Rows_added, Rows_removed) VALUES (%s,%s,%s)"
        update_cursor.execute(update_sql, [datetime.now().strftime('%Y-%m-%d %H:%M:%S'), rows_added, rows_removed])
        db.commit()

        # Print summary
        print()
        print("  ╔══════════════════════════════════════════╗")
        print("  ║            📋  SUMMARY                   ║")
        print("  ╚══════════════════════════════════════════╝")
        print(f"  Completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"  Tickets added:   {rows_added:,}")
        print(f"  Tickets removed: {rows_removed:,}")
        if ticket_info:
            print("  New tickets by show:")
            title_counts = Counter(title[0] for title in ticket_info)
            for title, count in title_counts.items():
                print(f"    • {title}: {count:,}")
        print()
        status("🎉", "All done!")

    except Exception as e:
        print(f"Error: {e}")
        if db:
            db.rollback()
        raise

    finally:
        if driver:
            driver.quit()
        if db:
            db.close()


if __name__ == "__main__":
    main()
