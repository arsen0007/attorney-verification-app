# ==============================================================================
# ATTORNEY VERIFICATION WEB APP - PRODUCTION BACKEND (V21 LOGIC)
# ==============================================================================
# This is the definitive backend, updated with the final, most robust "two-pass"
# and lenient "confidence score" matching logic for maximum accuracy.
#
# Author: Gemini
# Date: June 20, 2025
# ==============================================================================

from flask import Flask, request, jsonify, render_template
import pandas as pd
import time
import re
import os
import threading
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

app = Flask(__name__)

# --- Global State Management ---
status = {
    'is_running': False, 'progress': 0, 'total': 0,
    'log': [], 'results': []
}

# --- Core Logic Functions (from our final local script) ---

def setup_driver():
    """Initializes a headless Selenium WebDriver for the server."""
    try:
        options = webdriver.ChromeOptions()
        options.add_argument("--headless")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
        service = ChromeService()
        driver = webdriver.Chrome(service=service, options=options)
        return driver
    except Exception as e:
        status['log'].append(f"CRITICAL DRIVER ERROR: {e}")
        return None

def clean_name_for_search(first_name, last_name):
    clean_first = re.split(r'[.\s]', str(first_name))[0]
    clean_last = re.split(r'[.\s]', str(last_name))[-1]
    return f"{clean_first} {clean_last}"

def get_name_parts_for_matching(first_name, last_name):
    clean_first = re.split(r'[.\s]', str(first_name))[0].lower()
    clean_last = re.split(r'[.\s]', str(last_name))[-1].lower()
    return clean_first, clean_last

def get_match_confidence(first_name_part, last_name_part, csv_email, page_text):
    confidence = {
        "Email Matched (Exact)": "No", "Lastname in Email": "No", "Firstname in Email": "No",
        "Lastname in Website": "No", "Firstname in Website": "No",
    }
    page_emails = re.findall(r'[\w\.-]+@[\w\.-]+', page_text)
    website_match = re.search(r'Website:\s*<a[^>]*>([^<]+)</a>', page_text, re.IGNORECASE) or \
                    re.search(r'Website:\s*(\S+)', page_text, re.IGNORECASE)
    page_website = website_match.group(1).lower() if website_match else None

    csv_email_handle = csv_email.split('@')[0] if '@' in csv_email else None
    if csv_email_handle:
        for email in page_emails:
            if email.split('@')[0] == csv_email_handle:
                confidence["Email Matched (Exact)"] = "Yes"
                confidence["Lastname in Email"] = "Yes"
                confidence["Firstname in Email"] = "Yes"
                return True, confidence

    for email in page_emails:
        if last_name_part in email: confidence["Lastname in Email"] = "Yes"
        if first_name_part[:3] in email: confidence["Firstname in Email"] = "Yes"
    if page_website:
        if last_name_part in page_website: confidence["Lastname in Website"] = "Yes"
        if first_name_part[:3] in page_website: confidence["Firstname in Website"] = "Yes"

    match_score = sum(1 for v in confidence.values() if v == "Yes")
    return match_score >= 2, confidence

def run_verification_process(filepath):
    """The main Selenium scraping and processing logic."""
    global status
    try:
        df = pd.read_csv(filepath)
        required_cols = ['First Name', 'Last Name', 'Primary Pr Email', 'Primary Practice Name']
        if not all(col in df.columns for col in required_cols):
            raise ValueError(f"CSV is missing required headers.")

        status['total'] = len(df)
        driver = setup_driver()
        if not driver:
            raise Exception("Could not initialize web driver on server.")

        for index, row in df.iterrows():
            if not status['is_running']:
                status['log'].append("Process cancelled by user.")
                break

            status['progress'] = index + 1
            first_name, last_name = row.get('First Name', ''), row.get('Last Name', '')
            full_name_cleaned = clean_name_for_search(first_name, last_name)
            first_name_match, last_name_match = get_name_parts_for_matching(first_name, last_name)
            original_name = f"{first_name} {last_name}"
            csv_email = str(row.get('Primary Pr Email', '')).strip().lower()

            status['log'].append(f"Processing {index + 1}/{status['total']}: {original_name}")

            result_data = {
                'Name': original_name, 'Email (from CSV)': row.get('Primary Pr Email', ''),
                'Firm Name (from CSV)': row.get('Primary Practice Name', ''), 'Verified Status': 'Error Processing',
                'Discipline Found': 'Not Checked', 'Email Matched (Exact)': 'No', 'Lastname in Email': 'No',
                'Firstname in Email': 'No', 'Lastname in Website': 'No', 'Firstname in Website': 'No',
                'Profile Link': 'Not Found'
            }

            try:
                driver.get('https://apps.calbar.ca.gov/attorney/LicenseeSearch/QuickSearch')
                wait = WebDriverWait(driver, 20)
                search_box = wait.until(EC.element_to_be_clickable((By.ID, "FreeText")))
                search_box.clear()
                search_box.send_keys(full_name_cleaned)
                search_button = wait.until(EC.element_to_be_clickable((By.ID, "btn_quicksearch")))
                search_button.click()
                time.sleep(1.5)

                try:
                    no_results_span = driver.find_element(By.CLASS_NAME, "attSearchRes")
                    if "returned no results" in no_results_span.text:
                        result_data['Verified Status'] = 'Not Found on CalBar'
                        status['results'].append(result_data)
                        continue
                except NoSuchElementException: pass
                
                # PASS 1: Determine Status and collect links
                all_profile_links = []
                overall_status = "Not Found"
                wait.until(EC.visibility_of_element_located((By.ID, "tblAttorney")))
                result_rows = driver.find_elements(By.XPATH, "//table[@id='tblAttorney']/tbody/tr")
                statuses = [r.find_element(By.XPATH, "./td[2]").text.strip() for r in result_rows]
                all_profile_links = [r.find_element(By.XPATH, "./td[1]/a").get_attribute('href') for r in result_rows]
                
                if any(s.lower() == 'active' for s in statuses): overall_status = 'Active'
                elif statuses: overall_status = statuses[0]
                
                result_data['Verified Status'] = overall_status
                status['log'].append(f" -> Status determined as: {overall_status}")
                
                # PASS 2: Find first confident match
                match_found = False
                for link in all_profile_links:
                    driver.get(link)
                    time.sleep(1)
                    page_text = driver.find_element(By.TAG_NAME, 'body').text.lower()
                    is_match, confidence = get_match_confidence(first_name_match, last_name_match, csv_email, page_text)
                    if is_match:
                        status['log'].append("    -> Match CONFIRMED.")
                        match_found = True
                        result_data.update(confidence)
                        result_data['Profile Link'] = link
                        try:
                            discipline_xpath = "//table//tbody/tr[td/strong[text()='Present']]/td[3]"
                            cell_html = driver.find_element(By.XPATH, discipline_xpath).get_attribute('innerHTML')
                            result_data['Discipline Found'] = 'No' if '&nbsp;' in cell_html else 'Yes'
                        except: result_data['Discipline Found'] = 'Discipline Info Not Found'
                        break
                
                if not match_found:
                    status['log'].append(" -> No definitive match found, but status was recorded.")
                    result_data['Discipline Found'] = 'Match Not Confirmed'
            except Exception as e:
                status['log'].append(f" -> CRITICAL ERROR during processing: {e}")
            
            status['results'].append(result_data)

        driver.quit()
        status['log'].append("Verification process complete!")

    except Exception as e:
        status['log'].append(f"--- FATAL ERROR ---: {str(e)}")
    finally:
        status['is_running'] = False

# --- API Routes ---
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/start', methods=['POST'])
def start_process():
    global status
    if status['is_running']:
        return jsonify({'error': 'A process is already running.'}), 400

    file = request.files.get('file')
    if not file or not file.filename.endswith('.csv'):
        return jsonify({'error': 'Invalid file. Please upload a CSV.'}), 400
    
    status = {'is_running': True, 'progress': 0, 'total': 0, 'log': ["Starting verification..."], 'results': []}
    
    filepath = "uploaded_file.csv"
    file.save(filepath)

    thread = threading.Thread(target=run_verification_process, args=(filepath,))
    thread.start()
    return jsonify({'message': 'Process started successfully.'})

@app.route('/status')
def get_status():
    return jsonify(status)
