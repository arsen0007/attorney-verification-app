# ==============================================================================
# DEFINITIVE MULTI-STATE ATTORNEY VERIFICATION DASHBOARD (V33 - AI SUMMARIES)
# ==============================================================================
#
# Description:
# This is the final, definitive version of the application. It has been
# re-architected to use the Gemini API as an "AI Reporting Officer." After the
# automation gathers the raw facts, it sends them to the AI to generate a
# single, clear, human-readable summary in a new "Comments" column. This
# replaces all previous "Yes/No" matching columns and provides a superior,
# more professional reporting experience for both CA and GA.
#
# Author: Gemini
# Date: June 23, 2025
#
# ==============================================================================

import streamlit as st
import pandas as pd
import time
import re
import threading
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from selenium.common.exceptions import TimeoutException, NoSuchElementException
import queue
import math
import google.generativeai as genai

# --- Page Configuration ---
st.set_page_config(page_title="AI-Powered Attorney Verification", page_icon="🤖", layout="wide")

# --- State Management & Thread-Safe Queue ---
if 'log_queue' not in st.session_state: st.session_state.log_queue = queue.Queue()
if 'results_queue' not in st.session_state: st.session_state.results_queue = queue.Queue()
if 'progress_queue' not in st.session_state: st.session_state.progress_queue = queue.Queue()
if 'stop_event' not in st.session_state: st.session_state.stop_event = threading.Event()
if 'process_running' not in st.session_state: st.session_state.process_running = False
if 'log_messages' not in st.session_state: st.session_state.log_messages = ["Welcome! Please select a state, provide an API Key, and upload a CSV to begin."]
if 'results_df' not in st.session_state: st.session_state.results_df = pd.DataFrame()
if 'progress' not in st.session_state: st.session_state.progress = (0, 0)

# --- CONFIGURATION ---
BATCH_SIZE = 50
COOL_DOWN_SECONDS = 5
CALBAR_SEARCH_URL = 'https://apps.calbar.ca.gov/attorney/LicenseeSearch/QuickSearch'
GABAR_SEARCH_URL = 'https://www.gabar.org/member-directory/'
POLITE_WAIT_TIME = 2.5

# --- Helper Functions ---
def setup_driver(log_q):
    log_q.put("Setting up robust web driver...")
    service = ChromeService(ChromeDriverManager().install())
    options = webdriver.ChromeOptions()
    options.add_argument("start-maximized")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_argument('--log-level=3')
    return webdriver.Chrome(service=service, options=options)

def definitive_clean_name(name_str):
    if not isinstance(name_str, str): return ""
    name_str = re.sub(r',?\s+(jr|sr|ii|iii|iv|esq)\.?$', '', name_str, flags=re.I).strip()
    name_str = name_str.replace('.', '')
    parts = name_str.split()
    if not parts: return ""
    if len(parts[0]) == 1 and len(parts) > 1:
        return parts[1]
    return parts[0]

def get_name_parts(row):
    first, last = row.get('First Name', ''), row.get('Last Name', '')
    clean_last = str(last).strip().split()[0] if isinstance(last, str) and last.strip() else ""
    return definitive_clean_name(first).lower(), clean_last.lower()

def get_match_signals(name_parts, firm_name, page_text):
    first, last = name_parts
    signals = []
    if firm_name and firm_name in page_text:
        signals.append("Firm Name")
    
    page_emails = re.findall(r'[\w\.-]+@[\w\.-]+', page_text)
    website_match = re.search(r'Website:\s*<a[^>]*>([^<]+)</a>', page_text, re.IGNORECASE) or re.search(r'Website:\s*(\S+)', page_text, re.IGNORECASE)
    page_website = website_match.group(1).lower() if website_match else None

    email_name_match = False
    for email in page_emails:
        if last in email and first[:4] in email:
            email_name_match = True
            break
    if email_name_match: signals.append("Name in Email")
    
    website_name_match = False
    if page_website:
        if last in page_website and first[:4] in page_website:
            website_name_match = True
    if website_name_match: signals.append("Name in Website")
            
    return signals

def is_name_only_match(name_parts, driver):
    first, last = name_parts
    try:
        headings = driver.find_elements(By.XPATH, "//h1 | //h2 | //h3")
        for heading in headings:
            if last in heading.text.lower() and first in heading.text.lower():
                return True
    except: return False
    return False

def get_ai_summary(api_key, raw_data, log_q):
    """Uses Gemini to generate a final summary comment."""
    log_q.put(" -> Generating AI summary comment...")
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        # Create a clean summary of the input data for the prompt
        prompt_facts = f"""
        - Verified Status: {raw_data.get('Verified Status', 'N/A')}
        - Discipline Found: {raw_data.get('Discipline Found', 'N/A')}
        - Match Signals: {', '.join(raw_data.get('Match Signals', [])) if raw_data.get('Match Signals') else 'None'}
        - Name Only Fallback Used: {raw_data.get('Name Match Only', 'No')}
        - Unmatched Links Found: {'Yes' if raw_data.get('Unmatched Profile Links') else 'No'}
        """

        prompt = f"""
        You are a reporting agent. Summarize the following verification results into a single, concise sentence for a 'Comments' column in a report.
        
        Input Data:
        {prompt_facts}

        Task: Generate the comment. Be clear and direct.
        Example 1: If Match Signals contains 'Firm Name', respond: "Verified: Match confirmed based on firm name. No discipline found."
        Example 2: If Name Only Fallback is 'Yes', respond: "Verified: Name matched on profile, but no other contact/firm data was found."
        Example 3: If Verified Status is 'Match Not Confirmed', respond: "Match Not Confirmed. See links provided for manual review."
        Example 4: If Verified Status is 'Deceased', respond: "Result determined from search page. Profile status is Deceased."
        """
        response = model.generate_content(prompt)
        summary = response.text.strip().replace('\n', ' ')
        log_q.put(f" -> AI Comment: {summary}")
        return summary
    except Exception as e:
        log_q.put(f" -> ERROR: AI summary failed: {e}")
        return "AI summary failed."

# --- STATE-SPECIFIC LOGIC ---
def process_california_attorney(driver, wait, attorney_data, result_data, log_q):
    first_name_match, last_name_match = attorney_data['name_parts']
    firm_name = attorney_data['firm']
    log_q.put(f" -> [CA] Searching for '{first_name_match} {last_name_match}'...")
    driver.get(CALBAR_SEARCH_URL)
    search_box = wait.until(EC.element_to_be_clickable((By.ID, "FreeText")))
    search_box.clear()
    search_box.send_keys(f"{first_name_match} {last_name_match}")
    wait.until(EC.element_to_be_clickable((By.ID, "btn_quicksearch"))).click()
    time.sleep(POLITE_WAIT_TIME)
    try:
        if "returned no results" in driver.find_element(By.CLASS_NAME, "attSearchRes").text:
            result_data['Verified Status'] = 'Not Found on CalBar'
            return result_data
    except NoSuchElementException: pass

    try:
        wait.until(EC.visibility_of_element_located((By.ID, "tblAttorney")))
        result_rows = driver.find_elements(By.XPATH, "//table[@id='tblAttorney']/tbody/tr")
        all_statuses = [r.find_element(By.XPATH, "./td[2]").text.strip() for r in result_rows]
        active_profile_links = [r.find_element(By.XPATH, "./td[1]/a").get_attribute('href') for i, r in enumerate(result_rows) if all_statuses[i].lower() == 'active']
        
        if active_profile_links:
            result_data['Verified Status'] = 'Active'
            match_found = False
            for link in active_profile_links:
                driver.get(link)
                time.sleep(1.5)
                page_text = driver.find_element(By.TAG_NAME, 'body').text.lower()
                
                match_signals = get_match_signals(attorney_data['name_parts'], firm_name, page_text)
                name_match_only = False
                if not match_signals and is_name_only_match(attorney_data['name_parts'], driver):
                    match_signals.append("Name Only Fallback")
                    name_match_only = True
                
                if match_signals:
                    match_found = True
                    result_data['Profile Link'] = link
                    result_data['Match Signals'] = match_signals
                    result_data['Name Match Only'] = 'Yes' if name_match_only else 'No'
                    try:
                        xpath = "//table//tbody/tr[td/strong[text()='Present']]/td[3]"
                        cell_html = driver.find_element(By.XPATH, xpath).get_attribute('innerHTML')
                        result_data['Discipline Found'] = 'No' if '&nbsp;' in cell_html else 'Yes'
                    except: result_data['Discipline Found'] = 'Discipline Info Not Found (CA)'
                    break
            if not match_found:
                result_data['Discipline Found'] = 'Match Not Confirmed'
                result_data['Unmatched Profile Links'] = " | ".join(active_profile_links)
        else:
            status_hierarchy = ['deceased', 'disbarred', 'resigned', 'suspended', 'inactive']
            best_status = "Not Found"
            for status in sorted(list(set(all_statuses)), key=lambda s: status_hierarchy.index(s.lower()) if s.lower() in status_hierarchy else len(status_hierarchy)):
                best_status = status
                break
            result_data['Verified Status'] = best_status
            if len(set(all_statuses)) > 1:
                result_data['Comments'] = f"Multiple non-active statuses found: {', '.join(sorted(list(set(all_statuses))))}"
            result_data['Discipline Found'] = 'Not Applicable (Non-Active)'

    except (NoSuchElementException, TimeoutException):
        result_data['Verified Status'] = 'Search Error (CA)'
    
    return result_data

def process_georgia_attorney(driver, wait, attorney_data, result_data, log_q):
    first_name_match, last_name_match = attorney_data['name_parts']
    firm_name = attorney_data['firm']
    log_q.put(f" -> [GA] Searching for '{first_name_match} {last_name_match}'...")
    driver.get(GABAR_SEARCH_URL)
    time.sleep(2)

    try:
        first_name_input = wait.until(EC.presence_of_element_located((By.NAME, "firstName")))
        driver.execute_script("arguments[0].value = arguments[1];", first_name_input, first_name_match)
        last_name_input = driver.find_element(By.NAME, "lastName")
        driver.execute_script("arguments[0].value = arguments[1];", last_name_input, last_name_match)
        search_button = driver.find_element(By.XPATH, "//form[contains(@action, '/member-directory/')]//button[@type='submit']")
        driver.execute_script("arguments[0].click();", search_button)
        time.sleep(2.5)
    except Exception as e:
        raise Exception(f"Failed during GA search form interaction: {e}")
    
    profile_urls = []
    try:
        wait.until(EC.presence_of_element_located((By.XPATH, "//a[contains(@href, '/member-directory/?id=')]")))
        profile_links = driver.find_elements(By.XPATH, "//a[contains(@href, '/member-directory/?id=')]")
        profile_urls = [link.get_attribute('href') for link in profile_links]
    except (NoSuchElementException, TimeoutException):
        result_data['Verified Status'] = 'Not Found on GA Bar'
        return result_data

    match_found = False
    log_q.put(f" -> [GA] Checking {len(profile_urls)} profile(s)...")
    for url in profile_urls:
        driver.get(url)
        time.sleep(1.5)
        page_text = driver.find_element(By.TAG_NAME, 'body').text.lower()
        
        match_signals = get_match_signals(attorney_data['name_parts'], firm_name, page_text)
        name_match_only = False
        if not match_signals and is_name_only_match(attorney_data['name_parts'], driver):
            match_signals.append("Name Only Fallback")
            name_match_only = True
        
        if match_signals:
            match_found = True
            result_data['Profile Link'] = url
            result_data['Match Signals'] = match_signals
            result_data['Name Match Only'] = 'Yes' if name_match_only else 'No'
            try:
                status_xpath = "//p[span[contains(text(),'Status')]]/span[contains(@class,'fw-bold')]"
                result_data['Verified Status'] = driver.find_element(By.XPATH, status_xpath).text.strip()
            except: result_data['Verified Status'] = "Status Not Found (GA)"
            try:
                discipline_xpath = "//div[span[contains(text(),'Public Discipline')]]/span[contains(@class,'fw-bold')]"
                result_data['Discipline Found'] = driver.find_element(By.XPATH, discipline_xpath).text.strip()
            except: result_data['Discipline Found'] = "Discipline Info Not Found (GA)"
            break
            
    if not match_found:
        result_data['Verified Status'] = 'Match Not Confirmed'
        result_data['Unmatched Profile Links'] = " | ".join(profile_urls)
        
    return result_data

# --- MAIN THREAD ---
def verification_thread_target(uploaded_file, selected_state, api_key, log_q, results_q, progress_q, stop_event):
    driver = None
    try:
        df = pd.read_csv(uploaded_file)
        total_records = len(df)
        progress_q.put((0, total_records))
        required_cols = ['First Name', 'Last Name', 'Firm name', 'Email']
        if not all(col in df.columns for col in required_cols):
            log_q.put(f"ERROR: CSV is missing required columns: {', '.join(required_cols)}")
            return

        num_batches = math.ceil(total_records / BATCH_SIZE)
        for batch_num in range(num_batches):
            if stop_event.is_set(): break
            driver = setup_driver(log_q)
            if driver is None: break

            start_index = batch_num * BATCH_SIZE
            end_index = start_index + BATCH_SIZE
            batch_df = df[start_index:end_index]
            log_q.put(f"--- Starting Batch {batch_num + 1} of {num_batches} ---")

            for index, row in batch_df.iterrows():
                if stop_event.is_set(): break
                progress_q.put((index + 1, total_records))
                original_name = f"{row.get('First Name', '')} {row.get('Last Name', '')}"
                log_q.put(f"Processing {index + 1}/{total_records}: {original_name}")

                result_data = {
                    'Name': original_name, 'State': selected_state.upper(), 'Firm Name': row.get('Firm name', ''),
                    'Verified Status': 'Error Processing', 'Discipline Found': 'Not Checked',
                    'Profile Link': 'Not Found', 'Unmatched Profile Links': ''
                }
                try:
                    attorney_data = {
                        'name_parts': get_name_parts(row),
                        'firm': str(row.get('Firm name', '')).strip().lower(),
                    }
                    wait = WebDriverWait(driver, 25)
                    if selected_state.lower() == 'california':
                        result_data = process_california_attorney(driver, wait, attorney_data, result_data, log_q)
                    elif selected_state.lower() == 'georgia':
                         result_data = process_georgia_attorney(driver, wait, attorney_data, result_data, log_q)
                    
                    # Generate AI summary comment after processing
                    result_data['Comments'] = get_ai_summary(api_key, result_data, log_q)

                except Exception as e:
                    log_q.put(f"CRITICAL ERROR processing row: {e}")
                    result_data['Comments'] = f"A critical error occurred: {e}"
                
                results_q.put(result_data)
            
            if driver: driver.quit()
            if batch_num < num_batches - 1 and not stop_event.is_set():
                log_q.put(f"--- Batch {batch_num + 1} complete. Cooling down for {COOL_DOWN_SECONDS}s... ---")
                time.sleep(COOL_DOWN_SECONDS)
    finally:
        if 'driver' in locals() and driver: driver.quit()
        log_q.put("Verification process finished.")
        progress_q.put(('done', 'done'))

# --- UI LAYOUT ---
st.title("🤖 AI-Powered Attorney Verification Dashboard")
st.markdown("This application uses automation to verify attorney status and discipline.")
st.sidebar.header("Controls")

state_options = ["California", "Georgia"]
selected_state = st.sidebar.selectbox("Select State Bar to Verify", state_options)
api_key = st.sidebar.text_input("Enter your Gemini API Key", type="password", help="Required for AI-powered summaries.")

uploaded_file = st.sidebar.file_uploader(
    "Upload your CSV file", type="csv",
    help="Required headers: 'First Name', 'Last Name', 'Firm name', 'Email'"
)

if st.sidebar.button("Start Verification", disabled=not uploaded_file or not api_key or st.session_state.process_running):
    st.session_state.process_running = True
    st.session_state.log_messages = [f"Starting verification for {selected_state.upper()}..."]
    st.session_state.results_df = pd.DataFrame()
    st.session_state.progress = (0, 0)
    st.session_state.stop_event.clear()
    for q in [st.session_state.log_queue, st.session_state.results_queue, st.session_state.progress_queue]:
        while not q.empty(): q.get()
    
    thread = threading.Thread(
        target=verification_thread_target,
        args=(uploaded_file, selected_state, api_key, st.session_state.log_queue, st.session_state.results_queue, st.session_state.progress_queue, st.session_state.stop_event)
    )
    thread.start()
    st.rerun()

if st.sidebar.button("Stop Process", disabled=not st.session_state.process_running):
    st.session_state.stop_event.set()
    st.rerun()

st.sidebar.info("A Chrome window will run in the background. Please do not close it.")

col1, col2 = st.columns([1, 2])
with col1:
    st.subheader("📊 Progress")
    current_progress, total_progress = st.session_state.progress
    progress_bar = st.progress(0)
    progress_text = st.empty()
    if total_progress > 0:
        percent_complete = int((current_progress / total_progress) * 100) if total_progress > 0 else 0
        progress_bar.progress(percent_complete)
        progress_text.text(f"Processed {current_progress} of {total_progress} ({percent_complete}%)")
    else: progress_text.text("Waiting to start...")

with col2:
    st.subheader("📝 Activity Log")
    log_placeholder = st.empty()
    with log_placeholder.container(height=300):
        for msg in reversed(st.session_state.log_messages):
            st.write(msg)

st.divider()
st.subheader("✅ Results")
results_placeholder = st.empty()
if not st.session_state.results_df.empty:
    # Display only a subset of columns for a cleaner UI
    display_cols = ['Name', 'State', 'Firm Name', 'Verified Status', 'Discipline Found', 'Comments', 'Profile Link', 'Unmatched Profile Links']
    display_df = st.session_state.results_df[[col for col in display_cols if col in st.session_state.results_df.columns]]
    results_placeholder.dataframe(display_df)
    
    @st.cache_data
    def convert_df_to_csv(df): return df.to_csv(index=False).encode('utf-8')
    st.download_button(
       label="Download Full Results as CSV", data=convert_df_to_csv(st.session_state.results_df),
       file_name="Verification_Results.csv", mime="text/csv",
    )
else: results_placeholder.info("Results will appear here once the process starts.")

if st.session_state.process_running:
    while not st.session_state.log_queue.empty(): st.session_state.log_messages.append(st.session_state.log_queue.get())
    temp_results = []
    while not st.session_state.results_queue.empty(): temp_results.append(st.session_state.results_queue.get())
    if temp_results:
        new_df = pd.DataFrame(temp_results)
        st.session_state.results_df = pd.concat([st.session_state.results_df, new_df], ignore_index=True) if not st.session_state.results_df.empty else new_df
    while not st.session_state.progress_queue.empty():
        progress_update = st.session_state.progress_queue.get()
        if progress_update[0] == 'done': 
            st.session_state.process_running = False
            st.rerun()
        else: 
            st.session_state.progress = progress_update
    time.sleep(1)
    st.rerun()
