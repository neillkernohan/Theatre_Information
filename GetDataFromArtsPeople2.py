#!/usr/bin/env python3

import argparse
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


def download_csv(driver, report_name, directory, csv_url=None):
    """Download a CSV report, either via direct URL or by navigating the saved reports UI."""
    status("📂", f"Downloading report: {report_name}")
    existing_csvs = set(glob.glob(os.path.join(directory, "*.csv")))

    if csv_url:
        # Direct URL approach — just navigate to the CSV download URL
        status("⬇️ ", "Navigating to CSV download URL...")
        driver.get(csv_url)
    else:
        # Fallback: navigate through saved reports UI
        status("📂", "Opening Saved Reports page...")
        driver.get("https://app.arts-people.com/admin/app/#/reports/saved")
        WebDriverWait(driver, 30).until(
            EC.element_to_be_clickable((By.XPATH, f"//*[normalize-space()='{report_name}']"))
        ).click()
        WebDriverWait(driver, 60).until(
            EC.presence_of_element_located((By.XPATH, "(//button[@ng-click='viewVm.exportCsv();'])[1]"))
        ).click()

    status("⬇️ ", "Waiting for download...")
    csv_file = wait_for_download(directory, existing_csvs)
    status("✅", f"Downloaded: {os.path.basename(csv_file)}")
    return csv_file


def process_ticket_data(csv_file, db, full_sync=False):
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

    # Find rows to delete (in DB but no longer in CSV) — only in full sync mode
    rows_removed = 0
    if full_sync:
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
    else:
        status("⏭️ ", "Skipping delete check (recent mode — use --full for full sync)")

    return rows_added, rows_removed, ticket_info


def parse_date(value):
    """Parse a date string that may be 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM AM/PM'."""
    for fmt in ('%Y-%m-%d %I:%M %p', '%Y-%m-%d'):
        try:
            return datetime.strptime(value, fmt).strftime('%Y-%m-%d %H:%M:%S')
        except ValueError:
            continue
    return value


def process_patron_data(csv_file, db, full_sync=False):
    """Process patron CSV: insert new patrons, update changed, and optionally delete removed."""
    print()
    print("  ╔══════════════════════════════════════════╗")
    print("  ║         👥  PATRON DATA SYNC             ║")
    print("  ╚══════════════════════════════════════════╝")
    status("🔍", "Loading existing patron data from database...")
    select_cursor = db.cursor()
    select_cursor.execute("""SELECT Patron_ID, First_name, Last_name, Organization, Assoc_Organization,
                             Address_1, Address_2, City, Province, Postal_Code, No_Email, Notes,
                             Home_Phone, Cell_Phone, Work_Phone, Created, Last_Activity, Updated,
                             Marketing_Lists, Email
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
            home_phone = row[12] if len(row) > 12 else ""
            cell_phone = row[13] if len(row) > 13 else ""
            work_phone = row[14] if len(row) > 14 else ""
            created = parse_date(row[15]) if len(row) > 15 and row[15] else None
            last_activity = parse_date(row[16]) if len(row) > 16 and row[16] else None
            updated = parse_date(row[17]) if len(row) > 17 and row[17] else None
            marketing_lists = row[18] if len(row) > 18 else ""
            email = row[19] if len(row) > 19 else ""
            csv_values = (row[1], row[2], row[3], row[4], row[5],
                          row[6], row[7], row[8], row[9], no_email, notes,
                          home_phone, cell_phone, work_phone,
                          created, last_activity, updated, marketing_lists, email)

            if row[0] not in existing_data:
                insert_data.append((row[0], *csv_values))
            else:
                db_values = existing_data[row[0]]
                # Convert DB values for comparison
                db_comparable = (db_values[0], db_values[1], db_values[2], db_values[3],
                                 db_values[4], db_values[5], db_values[6], db_values[7],
                                 db_values[8], int(db_values[9]), db_values[10] or "",
                                 db_values[11] or "", db_values[12] or "", db_values[13] or "",
                                 str(db_values[14]) if db_values[14] else None,
                                 str(db_values[15]) if db_values[15] else None,
                                 str(db_values[16]) if db_values[16] else None,
                                 db_values[17] or "", db_values[18] or "")
                if csv_values != db_comparable:
                    update_data.append((*csv_values, row[0]))

    status("🔄", f"Found {len(insert_data):,} new, {len(update_data):,} changed patrons")

    if insert_data:
        status("➕", f"Inserting {len(insert_data):,} new patrons...")
        insert_cursor = db.cursor(prepared=True)
        insert_sql = """INSERT INTO Theatre_Information.Patrons
                        (Patron_ID, First_name, Last_name, Organization, Assoc_Organization,
                         Address_1, Address_2, City, Province, Postal_Code, No_Email, Notes,
                         Home_Phone, Cell_Phone, Work_Phone, Created, Last_Activity, Updated,
                         Marketing_Lists, Email)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"""
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
                            No_Email=%s, Notes=%s, Home_Phone=%s, Cell_Phone=%s, Work_Phone=%s,
                            Created=%s, Last_Activity=%s, Updated=%s, Marketing_Lists=%s, Email=%s
                        WHERE Patron_ID=%s"""
        update_cursor.executemany(update_sql, update_data)
        db.commit()
        status("✅", f"Updated {len(update_data):,} patrons")
    else:
        status("👍", "No patron records to update")

    # Delete patrons no longer in CSV — only in full sync mode
    if full_sync:
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
    else:
        status("⏭️ ", "Skipping delete check (recent mode — use --full for full sync)")

    return len(insert_data)


def main():
    parser = argparse.ArgumentParser(description="Sync Theatre Aurora data from Arts People to MySQL")
    parser.add_argument("--full", action="store_true",
                        help="Full sync from 2014 (inserts + deletes). Default is recent mode (inserts + updates only).")
    args = parser.parse_args()

    full_sync = args.full

    # Direct CSV download URLs (append /mode/csv to the report view URL)
    TICKET_RECENT_CSV_URL = "https://app.arts-people.com/admin/app/index/type/no-decor#/reports/view/SalesByPricePointReport/saved/188499/params/(a*:(dateRange:(e*:7~H1~H2026_12~I00_am,pst:--,7*:custom,s*:7~H1~H2025_12~I00_am),t*:(T*,u*),n*:(i*)),J*:31x255nnnnnnnnyx255nnnnnnnnyx255nnnnnnnnyx511nnnnnnnnnyx255nnnnnnnny,r*:(c*:((~S:+0),(~S:+2),(~S:customer,w*:+1K),(~S:+4),(~S:transaction~S5*,w*:+21),(~S:+6),(~S:+7),(~S:trans~Sdate~Stime,w*:+2M),(~S:+9),(~S:item~S5*,w*:+1H),(~S:order~Sdropdown~Scomments,w*:+2Z),(~S:ap~Sitem~Sfee,w*:+2M),(~S:cc~Sfees,w*:+2M),(~S:item~Sid,w*:+13),(~S:+B),(~S:+D),(~S:+F),(~S:+G),(~S:+H),(~S:+K),(~S:item~Scount,w*:+1Q),(~S:reservation~Samount,w*:+2M),(~S:season~Ss*,w*:+14),(~S:+N),(~S:+O),(~S:amount,w*:+2M),(~S:ticket~Sshow,4*:+0,2*:+1,3*:+0,w*:+9J),(~S:ticket~Sperson~S5*,w*:+1Y),(~S:ticket~Sseat,w*:+n),(~S:ticket~Ssubscription~Spackage,w*:+2a),(~S:+T),(~S:+U),(~S:+V),(~S:+W),(~S:+X),(~S:+Y),(~S:+a),(~S:+b),(~S:+d),(~S:+e),(~S:+f),(~S:+g),(~S:+h),(~S:+i),(~S:+j),(~S:+k),(~S:+l),(~S:ticket~Sperformance,4*:+1,2*:+1,3*:+1,w*:+2M),(~S:+n),(~S:+o),(~S:ticket~Sprice~Sterms,4*:+2,2*:+1,3*:+2,w*:+2K)),b*:--,f*:--))/from/standardParams/mode/csv"
    PATRON_CSV_URL = "https://app.arts-people.com/admin/app/index/type/no-decor#/reports/view/PatronInfoReport/saved/86165/params/(a*:(dateRange:(e*:7~H1~H2026_12~I00_am,pst:--,7*:custom,s*:7~H1~H2014_12~I00_am)),J*:'',r*:(c*:((~S:+1),(~S:+2),(~S:+3),(~S:person~Sid,w*:+1H),(~S:+5),(~S:first~Sname,w*:+1P),(~S:last~Sname,w*:+1O),(~S:+8),(~S:+9),(~S:+A),(~S:+B),(~S:+C),(~S:+D),(~S:org~Sname,w*:+1e),(~S:associated~Sorgs,w*:+1a),(~S:address,w*:+1L),(~S:address~S2,w*:+1L),(~S:city,w*:+j),(~S:state,w*:+s),(~S:+K),(~S:+L),(~S:+M),(~S:+N),(~S:+O),(~S:zip,w*:+1Y),(~S:no~Semail,w*:+1D),(~S:notes,w*:+2y),(~S:phone,w*:+1e),(~S:cell~Sphone,w*:+1Q),(~S:work~Sphone,w*:+1Z),(~S:entered,w*:+18),(~S:last~Sact~Sdate,w*:+1Z),(~S:last~Schange,w*:+2M),(~S:+T),(~S:+V),(~S:+a),(~S:+b),(~S:+c),(~S:+d),(~S:+e),(~S:+f),(~S:+g),(~S:person~Smarketing~Slists,w*:+1r),(~S:person~Semail~Sprimary,w*:+u)),b*:--,f*:--))/from/standardParams/mode/csv"

    if full_sync:
        ticket_report = "All Tickets from 2014"
        ticket_csv_url = None  # Full sync uses UI navigation
        mode_label = "FULL SYNC (from 2014)"
    else:
        ticket_report = "Tickets from July 2025"
        ticket_csv_url = TICKET_RECENT_CSV_URL
        mode_label = "RECENT MODE (from July 2025)"

    # Patrons always pulls the full list from 2014
    patron_csv_url = PATRON_CSV_URL

    download_dir = os.path.join(os.path.expanduser("~"), "Downloads")
    driver = None
    db = None

    try:
        print()
        print("  ╔══════════════════════════════════════════╗")
        print("  ║     🎭  THEATRE DATA SYNC STARTING       ║")
        print("  ╚══════════════════════════════════════════╝")
        print(f"  Mode: {mode_label}")
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
        ticket_csv = download_csv(driver, ticket_report, download_dir, csv_url=ticket_csv_url)

        status("🗄️ ", "Connecting to database...")
        db = mysql.connector.connect(
            host=MYSQL_HOST,
            user=MYSQL_USER,
            password=MYSQL_PASSWORD,
            database=MYSQL_DATABASE,
        )
        status("✅", "Database connected")

        rows_added, rows_removed, ticket_info = process_ticket_data(ticket_csv, db, full_sync)
        status("🗑️ ", f"Deleting {os.path.basename(ticket_csv)}...")
        os.remove(ticket_csv)
        status("✅", "Ticket CSV deleted")

        # Download and process patron data (always full list from 2014)
        patron_csv = download_csv(driver, "Patrons since 2014", download_dir, csv_url=patron_csv_url)
        process_patron_data(patron_csv, db, full_sync=True)
        status("🗑️ ", f"Deleting {os.path.basename(patron_csv)}...")
        os.remove(patron_csv)
        status("✅", "Patron CSV deleted")

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
