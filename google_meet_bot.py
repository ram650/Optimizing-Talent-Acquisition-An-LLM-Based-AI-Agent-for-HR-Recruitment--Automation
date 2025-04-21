from selenium.webdriver.chrome.options import Options
import time
import os
import pickle
from datetime import datetime, timezone
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from pymongo import MongoClient
from dotenv import load_dotenv
import time
from bson import ObjectId

load_dotenv()

# MongoDB URI and client setup
uri = os.getenv("MONGODB_URI")
client = MongoClient(uri)
hrdb = client["hr-agent"]
applicants_collection = hrdb["applicants"]

SCOPES = ['https://www.googleapis.com/auth/calendar', 'https://www.googleapis.com/auth/meet']

conversation_history=[]

def authenticate_google_account():
    """Handles OAuth2 Authentication for Google APIs."""
    creds = None
    # Token file stores the user's access and refresh tokens
    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)

    # If no valid credentials, request new ones
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)

        # Save the credentials for future use
        with open('token.pickle', 'wb') as token:
            pickle.dump(creds, token)

    return creds

def join_meeting(driver):
    try:
        # Try clicking 'Join now'
        join_now_button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, "//span[text()='Join now']/ancestor::button"))
        )
        join_now_button.click()
        print("✅ Clicked 'Join now' button.")
    except Exception as e:
        print("❌ 'Join now' button not found or not clickable:", e)
        try:
            # Try clicking 'Join anyway'
            join_anyway_button = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, "//span[text()='Join anyway']/ancestor::button"))
            )
            join_anyway_button.click()
            print("✅ Clicked 'Join anyway' button.")
        except Exception as e:
            print("❌ 'Join anyway' button not found or not clickable:", e)

        try:
            # Handle "Switch here" if present
            switch_here_button = driver.find_element(By.XPATH, "//span[contains(text(), 'Switch here')]/ancestor::button")
            switch_here_button.click()
            print("✅ Clicked 'Switch here' button.")
            time.sleep(2)  # Wait for UI to update
        except Exception:
            print("❌ 'Switch here' button not found or not needed.")

def ensure_captions_enabled(driver):
    try:
        captions_buttons = driver.find_elements(By.XPATH, "//button[contains(@aria-label, 'captions')]")
        for btn in captions_buttons:
            label = btn.get_attribute("aria-label")
            if "Turn on captions" in label:
                btn.click()
                print("✅ Captions were off, now enabled.")
                return
            elif "Turn off captions" in label:
                print("✅ Captions already enabled.")
                return
        print("❌ Couldn't find captions toggle.")
    except Exception as e:
        print("❌ Error ensuring captions:", e)

def save_to_db(applicant_id, history):
    try:
        applicants_collection.update_one(
            {"_id": ObjectId(applicant_id)},
            {"$set": {"meeting_captions": history}}
        )
        print("✅ Successfully saved caption history to database.")
    except Exception as e:
        print(f"❌ Error saving caption to MongoDB: {e}")

def capture_captions(driver, applicant_id, duration=3600):
    print("✅ Starting caption capture loop...")
    start_time = time.time()
    seen_caption_texts = set()

    while True:
        # Stop if meeting ends or tab is redirected
        if "meet.google.com" not in driver.current_url:
            print("⚠️ Meeting seems to have ended or you left the call.")
            break

        if time.time() - start_time > duration:
            print("⏱️ Max duration reached, ending capture.")
            break

        try:
            blocks = driver.find_elements(By.XPATH, "//div[contains(@class, 'nMcdL')]")

            for block in blocks:
                try:
                    speaker_elem = block.find_element(By.XPATH, ".//span[contains(@class, 'NWpY1d')]")
                    caption_elem = block.find_element(By.XPATH, ".//div[contains(@class, 'bh44bd')]")

                    speaker = speaker_elem.text.strip()
                    caption = caption_elem.text.strip()

                    if not caption:
                        continue

                    caption_key = f"{speaker}:{caption}"
                    if caption_key in seen_caption_texts:
                        continue

                    seen_caption_texts.add(caption_key)

                    last_caption = conversation_history[-1]["caption"] if conversation_history else None
                    last_speaker = conversation_history[-1]["speaker"] if conversation_history else None

                    if speaker and (caption != last_caption or speaker != last_speaker):
                        caption_data = {
                            "applicant_id": applicant_id,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "speaker": speaker,
                            "caption": caption
                        }
                        conversation_history.append(caption_data)
                        print("✅ Stored caption:", caption_data)

                    time.sleep(0.5)

                except Exception:
                    continue

        except Exception as e:
            print("❌ Error while reading captions:", e)

        time.sleep(1)

def clean_captions(history):
    cleaned = []
    for entry in history:
        if cleaned and entry["speaker"] == cleaned[-1]["speaker"]:
            # Replace previous entry with current one
            cleaned[-1] = entry
        else:
            cleaned.append(entry)
    return cleaned


def run_meet_bot(meeting_link, applicant_id, duration_seconds=3600):
    chrome_binary_path = r'C:\Program Files\Google\Chrome\Application\chrome.exe'  # Adjust if needed
    user_data_dir = r'C:\Users\IrfaanFareedA\AppData\Local\Google\Chrome\User Data'  # Your actual path

    options = Options()
    options.binary_location = chrome_binary_path
    options.add_argument(f"--user-data-dir={user_data_dir}")  # Use your local Chrome data
    options.add_argument("--profile-directory=Profile 2")  # Or 'Profile 1', etc.
    options.add_argument("--disable-notifications")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

    print("✅ Navigating to Google Meet...")
    driver.get(meeting_link)
    time.sleep(10)
    try:
        mute_button = driver.find_element(By.XPATH, "//div[@aria-label='Turn off microphone']")
        if mute_button.is_enabled() and mute_button.is_displayed():
            mute_button.click()
            print("✅ Microphone muted.")

        video_button = driver.find_element(By.XPATH, "//div[@aria-label='Turn off camera']")
        if video_button.is_enabled() and video_button.is_displayed():
            video_button.click()
            print("✅ Video turned off.")
    except Exception as e:
        print(f"❌ Error muting microphone or turning off video: {e}")
    join_meeting(driver)
    print("✅ Joined meeting")
    time.sleep(20)
    ensure_captions_enabled(driver)
    print("✅ Captions enabled")
    capture_captions(driver,applicant_id, duration_seconds)
    print("✅ Exitting...")
    driver.quit()
    cleaned_history = clean_captions(conversation_history)
    print("Filtered Conversation:\n", cleaned_history)
    save_to_db(applicant_id, cleaned_history)
    return cleaned_history


# if __name__ == "__main__":
#     meeting_url = "https://meet.google.com/vhp-pptm-tqp" 
#     applicant_id = "67d182de8a873ceafc315d20"
#     google_account_email = os.getenv("EMAIL_SENDER")
#     google_account_password = os.getenv("EMAIL_APP_PASSWORD")  
#     run_meet_bot(meeting_url, applicant_id, duration_seconds=60)
