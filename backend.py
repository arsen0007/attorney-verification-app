# ==============================================================================
# ATTORNEY VERIFICATION WEB APP - PRODUCTION BACKEND (V2.0)
# ==============================================================================
# This Flask server is optimized for deployment on a platform like Render.
# It runs Selenium in headless mode and is packaged with a Dockerfile.
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

status = {
    'is_running': False,
    'progress': 0,
    'total': 0,
    'log': [],
    'results': []
}

def run_verification_process(filepath):
    global status
    try:
        df = pd.read_csv(filepath)
        required_cols = ['First Name', 'Last Name', 'Primary Pr Email', 'Primary Practice Name']
        if not all(col in df.columns for col in required_cols):
            raise ValueError(f"CSV is missing required columns. Please ensure it has headers: {', '.join(required_cols)}")

        status['total'] = len(df)
        status['log'].append(f"Found {status['total']} attorneys to verify.")
        
        driver = setup_driver()
        if not driver:
            raise Exception("Could not initialize the Chrome web driver on the server.")

        for index, row in df.iterrows():
            if not status['is_running']:
                status['log'].append("Process cancelled by user.")
                break

            status['progress'] = index + 1
            first_name = row.get('First Name', '').strip()
            last_name = row.get('Last Name', '').strip()
            full_name_cleaned = clean_name(first_name, last_name)
            original_name = f"{first_name} {last_name}"
            csv_email = row.get('Primary Pr Email', '').strip().lower()
            csv_firm_name = row.get('Primary Practice Name', '').strip().lower()

            status['log'].append(f"Processing {index + 1}/{status['total']}: {original_name}")

            result_data = {
                'Name': original_name,
                'Email': row.get('Primary Pr Email', ''),
                'Firm Name': row.get('Primary Practice Name', ''),
                'Verified Status': 'Error Processing',
                'Discipline Found': 'Error Processing',
                'Firmname match': 'No',
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

                try:
                    wait.until(EC.visibility_of_element_located((By.ID, "tblAttorney")))
                except TimeoutException:
                    if "No results found" in driver.page_source:
                        result_data['Verified Status'] = 'Not Found on CalBar'
                        status['results'].append(result_data)
                        continue
                    else:
                        raise TimeoutException("Search failed: Page did not return known results.")

                active_profile_links = []
                result_rows = driver.find_elements(By.XPATH, "//table[@id='tblAttorney']/tbody/tr")
                for r in result_rows:
                    if r.find_element(By.XPATH, "./td[2]").text.strip().lower() == 'active':
                        active_profile_links.append(r.find_element(By.XPATH, "./td[1]/a").get_attribute('href'))
                
                if not active_profile_links:
                    result_data['Verified Status'] = 'No Active Match Found'
                    status['results'].append(result_data)
                    continue

                match_found = False
                for link in active_profile_links:
                    driver.get(link)
                    time.sleep(1)
                    
                    page_text_lower = driver.find_element(By.TAG_NAME, 'body').text.lower()
                    email_match = csv_email and csv_email in page_text_lower
                    firm_match = not email_match and csv_firm_name and csv_firm_name.lower() in page_text_lower

                    if email_match or firm_match:
                        status['log'].append(f"    -> Match FOUND on profile: {link}")
                        match_found = True
                        result_data['Profile Link'] = link
                        result_data['Firmname match'] = 'Yes' if firm_match else 'No'
                        
                        try:
                            status_xpath = "//table//tbody/tr[td/strong[text()='Present']]/td[2]"
                            result_data['Verified Status'] = driver.find_element(By.XPATH, status_xpath).text.strip()
                        except: result_data['Verified Status'] = 'Status Not Found'

                        try:
                            discipline_xpath = "//table//tbody/tr[td/strong[text()='Present']]/td[3]"
                            cell_html = driver.find_element(By.XPATH, discipline_xpath).get_attribute('innerHTML')
                            result_data['Discipline Found'] = 'No' if '&nbsp;' in cell_html else 'Yes'
                        except: result_data['Discipline Found'] = 'Discipline Info Not Found'
                        break
                
                if not match_found:
                    result_data['Verified Status'] = 'Match Not Found'

            except Exception as e:
                status['log'].append(f" -> CRITICAL ERROR: {e}")
            
            status['results'].append(result_data)
        
        driver.quit()
        status['log'].append("Verification process complete!")
        output_df = pd.DataFrame(status['results'])
        output_df.to_csv('Verification_Results.csv', index=False)
        status['log'].append("Results saved to 'Verification_Results.csv'")

    except Exception as e:
        status['log'].append(f"--- FATAL ERROR ---: {str(e)}")
    finally:
        status['is_running'] = False

def setup_driver():
    try:
        options = webdriver.ChromeOptions()
        options.add_argument("--headless")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        service = ChromeService()
        driver = webdriver.Chrome(service=service, options=options)
        return driver
    except Exception as e:
        print(f"Error setting up driver: {e}")
        return None

def clean_name(first_name, last_name):
    clean_first = re.split(r'[.\s]', first_name)[0]
    clean_last = re.split(r'[.\s]', last_name)[-1]
    return f"{clean_first} {clean_last}"

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

@app.route('/stop', methods=['POST'])
def stop_process():
    global status
    if status['is_running']:
        status['is_running'] = False
        return jsonify({'message': 'Stop signal sent.'})
    return jsonify({'error': 'No process is running.'})
