#!/usr/bin/env python3

from selenium import webdriver
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
import os
import csv
from datetime import datetime
import mysql.connector
import time
from collections import Counter
import math
from dotenv import load_dotenv

load_dotenv()

MYSQL_HOST = os.getenv("MYSQL_HOST")
MYSQL_USER = os.getenv("MYSQL_USER")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE")

def find_latest_file(directory):
    # Check if the directory exists
    if not os.path.isdir(directory):
        raise ValueError(f"The directory {directory} does not exist")

    # List all files in the directory
    files = [os.path.join(directory, f) for f in os.listdir(directory)]
    # Filter out directories, leave only files
    files = [f for f in files if os.path.isfile(f)]

    # Find the latest file
    latest_file = max(files, key=os.path.getmtime)

    return latest_file

def delete_latest_file(filePath):
    try:
        # Find the latest file in the specified directory
        # Delete the file
        os.remove(filePath)
    except ValueError as e:
        # Handle the case where the directory does not exist or is empty
        print(e)
    except Exception as e:
        # Handle other potential errors, such as permission issues
        print(f"Error deleting file: {e}")


""" PATH = '/Users/neillkernohan/Library/CloudStorage/OneDrive-Personal/Python Scripts/chromedriver'
driver = webdriver.Chrome()

driver.get("https://app.neonsso.com/login")
WebDriverWait(driver,10).until(EC.presence_of_element_located((By.XPATH, "(//input[@id='email'])[1]"))).send_keys(NEON_EMAIL)
driver.find_element(By.XPATH, "(//button[normalize-space()='Next'])[1]").click()
WebDriverWait(driver,10).until(EC.element_to_be_clickable((By.XPATH, "(//input[@id='password'])[1]"))).send_keys(NEON_PASSWORD)
driver.find_element(By.XPATH, "(//button[normalize-space()='Log In'])[1]").click()
WebDriverWait(driver,30).until(EC.presence_of_element_located((By.XPATH, "(//a[normalize-space()='Open'])[1]"))).click()
WebDriverWait(driver,30).until(EC.presence_of_element_located((By.XPATH, "(//a[normalize-space()='All Tickets from 2014'])[1]"))).click()
WebDriverWait(driver,60).until(EC.presence_of_element_located((By.XPATH, "(//button[@ng-click='viewVm.exportCsv();'])[1]"))).click()
time.sleep(3) """
directory_path = os.path.join(os.path.expanduser("~"), "Downloads")
Ticket_Data_CSV = find_latest_file(directory_path)

Ticket_Data_DB = mysql.connector.connect(
    host=MYSQL_HOST,
    user=MYSQL_USER,
    password=MYSQL_PASSWORD,
    database=MYSQL_DATABASE
)

# Load existing data into memory
Ticket_Data_Select_Cursor = Ticket_Data_DB.cursor()
Ticket_Data_Select_SQL = "select Item_ID, Item_count from Ticket_Info"
Ticket_Data_Select_Cursor.execute(Ticket_Data_Select_SQL)
existing_data = {(item_id, item_count) for item_id, item_count in Ticket_Data_Select_Cursor}

# Prepare insert statement
Ticket_Data_Insert_Cursor = Ticket_Data_DB.cursor(prepared=True)
Ticket_Data_Insert_SQL = """insert into Ticket_Info (Show_name, Performance_date, Price_terms, Customer, Transaction_type, 
                            Purchase_date, Item_type, Dropdown_comments, Per_item_fee, CC_fee, Item_ID, Item_count, 
                            Reserve_amount, Season, Amount, Person_type, Person_type_edited, Seat, Subscription_package) values (%s, %s, %s, %s, %s, %s, %s, 
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"""

Ticket_Data_Delete_Cursor = Ticket_Data_DB.cursor(prepared=True)
Ticket_Data_Delete_SQL = "delete from Ticket_Info where Item_ID = %s and Item_count = %s"
Update_Cursor = Ticket_Data_DB.cursor()
Update_SQL = "insert into Updates (Update_date_time, Rows_added, Rows_removed) values (%s,%s,%s)"

# Person type mapping
person_type_map = {
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
                        
# Process CSV

csv_rows = []
csv_short_rows = set()
with open(Ticket_Data_CSV) as Ticket_Data_File:
    Ticket_Data = csv.reader(Ticket_Data_File)
    next(Ticket_Data)  # Skip header
    next(Ticket_Data)  # Skip first line
    for row in Ticket_Data:
        csv_rows.append(row)
        csv_short_rows.add((row[10],int(row[11])))

batch_data = []
Ticket_Info = []
for row in csv_rows:
    if (row[10], int(row[11])) not in existing_data:
        Show_name = row[0]
        Performance_date = datetime.strptime(row[1], '%Y-%m-%d %I:%M %p').strftime('%Y-%m-%d %H:%M:%S')        
        Price_terms = row[2]
        Customer_name = row[3]
        Transaction_type = row[4]
        Purchase_date = datetime.strptime(row[5], '%Y-%m-%d %I:%M %p').strftime('%Y-%m-%d %H:%M:%S')        
        Item_type = row[6]
        Dropdown_comments = row[7]
        Per_item_fee = row[8]
        CC_fee = row[9]
        Item_ID = row[10]
        Item_count = row[11]
        Reserve_amount = row[12] if row[12] else 0
        Season = row[13]
        Amount = row[14]
        Person_type = row[15]
        Person_type_edited = person_type_map.get(row[15], "")
        Seat = row[16]
        Subscription_package = row[17]
        batch_data.append((Show_name, Performance_date, Price_terms, Customer_name, Transaction_type, Purchase_date, Item_type, Dropdown_comments, Per_item_fee, CC_fee, Item_ID, Item_count, Reserve_amount, Season, Amount, Person_type, Person_type_edited,Seat, Subscription_package))        
        # batch_data.append((row[0], Performance_date, row[2], row[3], row[4], Purchase_date, row[6], row[7], row[8], 0, row[9], row[10], row[11], Reserve_amount, row[13], row[14], row[15], Person_type_edited, row[16]))
        Ticket_Info.append((row[0], row[10]))

rowsAdded = len(batch_data)
if batch_data:
    disable_fk_cursor = Ticket_Data_DB.cursor()
    disable_fk_cursor.execute("SET foreign_key_checks = 0")
    disable_fk_cursor.execute("SET unique_checks = 0")
    Ticket_Data_DB.commit()  # Commit to apply the setting

    lock_cursor = Ticket_Data_DB.cursor()
    lock_cursor.execute("LOCK TABLES Ticket_Info WRITE")

# Break the data into chunks
    chunk_size = 1000
    num_chunks = math.ceil(len(batch_data) / chunk_size)
    
    for i in range(num_chunks):
        chunk = batch_data[i * chunk_size:(i + 1) * chunk_size]
        
        # Insert the chunk
        print(i)
        Ticket_Data_Insert_Cursor.executemany(Ticket_Data_Insert_SQL, chunk)
        Ticket_Data_DB.commit()  # Commit after each chunk to free memory and avoid timeouts


    unlock_cursor = Ticket_Data_DB.cursor()
    unlock_cursor.execute("UNLOCK TABLES")
    Ticket_Data_DB.commit()

    enable_fk_cursor = Ticket_Data_DB.cursor()
    enable_fk_cursor.execute("SET foreign_key_checks = 1")
    enable_fk_cursor.execute("set unique_checks = 1")
    Ticket_Data_DB.commit()  # Commit to reapply the foreign key checks


# Check if data is no longer in CSV
batch_data = []
for x in existing_data:
    if (x[0],x[1]) not in csv_short_rows:
        batch_data.append((x[0],x[1]))

rowsRemoved = len(batch_data)
if batch_data:
    Ticket_Data_Delete_Cursor.executemany(Ticket_Data_Delete_SQL,batch_data)
    Ticket_Data_DB.commit()

delete_latest_file(Ticket_Data_CSV)
# Download Patron Report

# pass

# driver.back()
# WebDriverWait(driver,10).until(EC.presence_of_element_located((By.XPATH, "(//a[normalize-space()='Patrons since 2014'])[1]"))).click()
# WebDriverWait(driver,60).until(EC.presence_of_element_located((By.XPATH, "(//button[@ng-click='viewVm.exportCsv();'])[1]"))).click()

# time.sleep(3)

# directory_path = os.path.join(os.path.expanduser("~"), "Downloads")
# # directory_path = '/Users/neillkernohan_mini/Downloads'
# Patron_Data_CSV = find_latest_file(directory_path)

# # Load existing data into memory
# Patron_IDs = Ticket_Data_DB.cursor()
# Patron_IDs_Select_SQL = "select Patron_ID from Patrons"
# Patron_IDs.execute(Patron_IDs_Select_SQL)
# existing_data = {(patron_id) for patron_id in Patron_IDs}

# batch_data = []
# with open(Patron_Data_CSV) as Patron_Data_File:
#     Patron_Data = csv.reader(Patron_Data_File)
#     next(Patron_Data)  # Skip header
#     for row in Patron_Data:
#         if row[0] == '5775936':
#             pass
#         if (row[0],) not in existing_data:
#             if row[10] == 'X':
#                 no_email = 1
#             else:
#                 no_email = 0
#             batch_data.append((row[0],row[1],row[2],row[3],row[4],row[5],row[6],row[7],row[8],row[9],no_email, row[11]))
#         else:
#             pass

# # Prepare insert statement
# Patron_Data_Insert_Cursor = Ticket_Data_DB.cursor(prepared=True)
# Patron_Data_Insert_SQL = """INSERT INTO Theatre_Information.Patrons (Patron_ID, First_name, Last_name, Organization, Assoc_Organization, Address_1, Address_2, City, Province, Postal_Code, No_Email, Email)
#                                 VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s);"""

# Patron_Data_Insert_Cursor.executemany(Patron_Data_Insert_SQL, batch_data)
# Ticket_Data_DB.commit()

# Update_Cursor.execute(Update_SQL,[datetime.now().strftime('%Y-%m-%d %H:%M:%S'),rowsAdded,rowsRemoved])
# Ticket_Data_DB.commit()

# Ticket_Data_DB.close()

# delete_latest_file(Patron_Data_CSV)

print(datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
print('Rows added: ' + str(rowsAdded))
print('Rows removed: ' + str(rowsRemoved))

# Extracting the book names and counting them
title_counts = Counter(title[0] for title in Ticket_Info)

# Iterating through the Counter object to print each book title and its count
for title, count in title_counts.items():
    print(f"{title}: {count}")