#!/usr/bin/env python3

from selenium import webdriver
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException
import csv
from datetime import datetime
import tkinter as tk
from tkinter import filedialog
from tkinter import messagebox
import time
from collections import Counter

PATH = '/Users/neillkernohan/Library/CloudStorage/OneDrive-Personal/Python Scripts/chromedriver'
driver = webdriver.Chrome()

driver.get("https://app.neonsso.com/login")
WebDriverWait(driver,10).until(EC.presence_of_element_located((By.XPATH, "(//input[@id='email'])[1]"))).send_keys('president@theatreaurora.com')
driver.find_element(By.XPATH, "(//button[normalize-space()='Next'])[1]").click()
WebDriverWait(driver,10).until(EC.element_to_be_clickable((By.XPATH, "(//input[@id='password'])[1]"))).send_keys('fJ6<wI5;xH5#gP0!')
driver.find_element(By.XPATH, "(//button[normalize-space()='Log In'])[1]").click()
WebDriverWait(driver,10).until(EC.presence_of_element_located((By.XPATH, "(//a[normalize-space()='Open'])[1]"))).click()
driver.get("https://app.arts-people.com/admin/legacyurl/1090")

# Create a new Tkinter root window
root = tk.Tk()
# Hide the root window
root.withdraw()

subscribedFile = filedialog.askopenfilename(filetypes=[("CSV files","*.csv")], title='Subscribed:')
#unsubscribedFile = filedialog.askopenfilename(filetypes=[("CSV files","*.csv")], title='Unsubscribed:')
#cleanedFile = filedialog.askopenfilename(filetypes=[("CSV files","*.csv")], title='Cleaned:')

def Type_Into_Inputbox(XPATH, Text_To_Type):
    driver.find_element(By.XPATH, XPATH).send_keys(Text_To_Type)

with open(subscribedFile) as subscribedDataFile:
    subscribedData = csv.reader(subscribedDataFile)
    next(subscribedData)  # Skip header
    for row in subscribedData:
        WebDriverWait(driver,10).until(EC.presence_of_element_located((By.XPATH, "/html[1]/body[1]/form[1]/div[1]/div[3]/div[1]/div[1]/div[2]/div[1]/table[1]/tbody[1]/tr[1]/td[1]/table[1]/tbody[1]/tr[3]/td[1]/table[1]/tbody[1]/tr[2]/td[1]/input[1]"))).send_keys(row[0])
        WebDriverWait(driver,10).until(EC.presence_of_element_located((By.XPATH, "/html[1]/body[1]/form[1]/div[1]/div[3]/div[1]/div[1]/div[2]/div[1]/table[1]/tbody[1]/tr[1]/td[1]/table[1]/tbody[1]/tr[1]/td[1]/div[1]/input[1]"))).click()
        try:
            # Try to find the element
            element = driver.find_element(By.XPATH, "//*[contains(text(),'No customers found')]")
            driver.find_element(By.XPATH, "/html[1]/body[1]/form[1]/div[1]/div[3]/div[1]/div[1]/div[3]/div[1]/table[1]/tbody[1]/tr[1]/td[1]/table[1]/tbody[1]/tr[2]/td[1]/div[1]/div[2]/div[1]/input[1]").send_keys(row[1])
            driver.find_element(By.XPATH, "/html[1]/body[1]/form[1]/div[1]/div[3]/div[1]/div[1]/div[3]/div[1]/table[1]/tbody[1]/tr[1]/td[1]/table[1]/tbody[1]/tr[2]/td[1]/div[1]/div[4]/div[1]/input[1]").send_keys(row[2])
            driver.find_element(By.XPATH, "/html[1]/body[1]/form[1]/div[1]/div[3]/div[1]/div[1]/div[3]/div[1]/table[1]/tbody[1]/tr[1]/td[1]/table[1]/tbody[1]/tr[1]/td[1]/div[1]/input[2]").click()
            driver.find_element(By.XPATH, "/html[1]/body[1]/form[1]/div[1]/div[3]/div[1]/div[1]/div[2]/div[1]/table[1]/tbody[1]/tr[1]/td[1]/table[1]/tbody[1]/tr[3]/td[1]/table[1]/tbody[1]/tr[2]/td[4]/input[2]").click()
            modal = WebDriverWait(driver, 10).until(EC.visibility_of_element_located((By.ID, "the_form")))        
            modal.find_element(By.XPATH, "/html[1]/body[1]/div[3]/div[1]/div[1]/div[1]/div[2]/div[2]/button[1]").click()
        except NoSuchElementException:
            # Person found, don't worry about it
            pass
        try:
            element = driver.find_element(By.XPATH, "/html[1]/body[1]/form[1]/div[1]/div[3]/div[1]/div[1]/div[2]/div[1]/table[1]/tbody[1]/tr[1]/td[1]/table[1]/tbody[1]/tr[1]/td[1]/div[1]/input[3]")
            element.click()
            # WebDriverWait(driver,10).until(EC.presence_of_element_located((By.XPATH, "/html[1]/body[1]/form[1]/div[1]/div[3]/div[1]/div[1]/div[2]/div[1]/table[1]/tbody[1]/tr[1]/td[1]/table[1]/tbody[1]/tr[1]/td[1]/div[1]/input[3]"))).click()
        except NoSuchElementException:
            root = tk.Tk()
            root.withdraw()  # Hides the main window
            messagebox.showinfo("Alert", "An important event has occurred.")
            root.destroy()
        
