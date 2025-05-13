# AiHR – AI-Powered HR Automation System

AiHR is a fully automated Human Resource Management system built with Python and Flask that streamlines recruitment, applicant tracking, interview scheduling, and transcription. It integrates with Google Meet, MongoDB, and OpenAI APIs to simplify and enhance the hiring process.

---

## 🚀 Features

- 💼 **Job Role Creation**: Define roles and requirements using simple forms.
- 📄 **Resume Analysis**: Automatically evaluate resumes using LLMs to extract skills and match candidates.
- 📆 **Interview Scheduling**: Automatically create Google Meet links and schedule interviews with calendar invites.
- 🤖 **Meeting Bot**: A Python bot joins Google Meet calls via Selenium to capture live captions.
- 📝 **Real-time Transcription**: Captions are stored with speaker labels and timestamps in MongoDB.
- 🔍 **Interview Captions Analysis**: The interview captions are passed to the LLM for analysis which provides deep insights into the candidate's performance in the interview along with graphical charts for quick understanding.
- 📊 **Dashboard**: View applicant details, skills breakdown, interview history, and more.
- ✉️ **Email Notifications**: Send automated interview invites and updates.

---

## 🧠 Tech Stack

- **Backend**: Python, Flask
- **Frontend**: Bootstrap, Chart.js, JavaScript
- **Database**: MongoDB (via `pymongo`)
- **Automation**: Selenium webdriver
- **Google Services**: Google Calendar API, Google Meet
- **AI**: Groq API (GPT models for resume analysis & interview question generation)

---

## 🔧 Setup & Installation

1. **Clone the Repository**
   ```bash
   git clone https://github.com/irf-rox/AiHR.git
   cd AiHR


2. **Install Requirements**

   ```bash
   pip install -r requirements.txt

3. **Environment Setup**
   Create a `.env` file in the root directory with the following variables:

   ```
   # MongoDB
   MONGODB_URI=<your_mongodb_connection_string>
   
   # Email Configuration
   EMAIL_SENDER=<your_email_address>
   EMAIL_APP_PASSWORD=<your_app_specific_password>
   
   # Chrome Profile for Google Meet Automation
   CHROME_PROFILE=<your_chrome_profile_name>  # e.g., "Profile 2" or "Person 1"
   
   # File Storage Paths
   UPLOAD_FOLDER=KnowledgeBase
   DATA_PATH=KnowledgeBase
   CHROMA_PATH=chroma
   
   # Google Drive Folder
   PARENT_FOLDER_ID=<your_google_drive_folder_id>  # e.g., "docs"
   
   # AI Model & API
   GROQ_API_KEY=<your_groq_api_key>
   MODEL=<your_preferred_model>  # e.g., "llama-3.1-8b-instant"
   
   # Interviewer Emails (Comma-separated)
   INTERVIEWERS=<email1>,<email2>,<email3>  # e.g., alice@example.com,bob@example.com
   ```

4. **Google API Credentials**

   * Create OAuth 2.0 credentials at [Google Cloud Console](https://console.cloud.google.com/)
   * Download the `credentials.json` file and place it in the project root.
   * On first run, the script will guide you through authentication and save a `token.pickle`.

---

## 🧪 Running the App

You can run the application by executing the app.py file.

Ensure your Chrome is closed before running the bot and that your `Profile 2` is signed in and allowed to join Meet calls.

---

## 📁 Project Structure

```
AiHR/
├── templates/               # HTML files
├── static/                  # CSS, JS, images
├── meet_bot.py              # Google Meet caption bot
├── app.py                   # Main Flask app
├── token.pickle             # Saved user auth token (created after first run)
├── credentials.json         # Google API credentials
├── .env                     # Environment variables
└── requirements.txt         # Python dependencies
```

---

## 📌 Known Issues

* **Chrome DevTools Error**: Ensure Chrome is not already running. Use a custom `--user-data-dir` for Selenium.
* **Authentication**: Must use an already signed-in Chrome profile with Meet access.

---

## 🤝 Contributing

Pull requests are welcome! Please follow these steps:

1. Fork the repo
2. Create a feature branch (`git checkout -b feature-name`)
3. Commit changes (`git commit -am 'Add new feature'`)
4. Push to your branch (`git push origin feature-name`)
5. Create a Pull Request

---

## 👨‍💻 Author

Developed with 💻 by [@irf-rox](https://github.com/irf-rox)
