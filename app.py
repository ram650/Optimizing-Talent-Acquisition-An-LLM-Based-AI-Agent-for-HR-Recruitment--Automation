from flask import Flask, render_template, request, jsonify
import os
from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.server_api import ServerApi
from bson import ObjectId
from werkzeug.utils import secure_filename
import fitz
from groq import Groq
import tempfile
import json
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import uuid
import pickle
from datetime import datetime, timedelta
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from create_database import load_documents, split_text
from apscheduler.schedulers.background import BackgroundScheduler
import google_meet_bot as bot
import pytz
scheduler = BackgroundScheduler()
scheduler.start()

def schedule_bot(meeting_link, applicant_id, run_time, interview_no, duration):
    scheduler.add_job(
        func=bot.run_meet_bot,
        trigger='date',
        run_date=run_time,
        args=[meeting_link, applicant_id, interview_no, duration*60]
    )
    print(f"Scheduled the bot to run at {run_time}")

# Define the scope

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
MODEL = os.getenv("MODEL")
uri = os.getenv("MONGODB_URI")
client = MongoClient(uri, server_api=ServerApi('1'))
hrdb = client["hr-agent"]

ALLOWED_EXTENSIONS = {'pdf', 'docx', 'txt'}

app = Flask(__name__)
UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER")
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
CHROMA_PATH =os.getenv("CHROMA_PATH")
SCOPES = ['https://www.googleapis.com/auth/calendar']
groq_client = Groq(api_key=GROQ_API_KEY)

try:
    client.admin.command('ping')
    print("✅ Successfully connected to MongoDB!")
except Exception as e:
    print(f"❌ MongoDB Connection Error: {e}")


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def send_email_gmail(sender_email, sender_password, receiver_email, subject, body):
    msg = MIMEMultipart()
    msg['From'] = sender_email
    msg['To'] = receiver_email
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain'))
    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(sender_email, sender_password)
        server.sendmail(sender_email, receiver_email, msg.as_string())
        server.quit()
        print("Email sent successfully!")
    except Exception as e:
        print("Failed to send email:", e)

def get_calendar_service():
    creds = None
    # Token file stores the user's access and refresh tokens
    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)
    # If no valid credentials, prompt the user to log in
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        # Save the credentials for next run
        with open('token.pickle', 'wb') as token:
            pickle.dump(creds, token)
    service = build('calendar', 'v3', credentials=creds)
    return service

def schedule_google_meet(applicant_name, role_name, applicant_email, iso_start_time, invitee_emails=None):
    service = get_calendar_service()
    end_time = datetime.fromisoformat(iso_start_time.replace("Z", "")) + timedelta(hours=1)
    end_iso = end_time.isoformat() + "Z"

    # Build attendees list
    attendees = [{'email': applicant_email}]
    if invitee_emails:
        attendees += [{'email': email} for email in invitee_emails]

    event_body = {
        'summary': f'Interview with {applicant_name} for {role_name}',
        'description': 'Scheduled interview via system',
        'start': {
            'dateTime': iso_start_time,
            'timeZone': 'UTC',
        },
        'end': {
            'dateTime': end_iso,
            'timeZone': 'UTC',
        },
        'attendees': attendees,
        'conferenceData': {
            'createRequest': {
                'requestId': str(uuid.uuid4()),
                'conferenceSolutionKey': {
                    'type': 'hangoutsMeet'
                }
            }
        }
    }
    import json
    print(json.dumps(event_body, indent=2))


    event = service.events().insert(
        calendarId='primary',
        body=event_body,
        conferenceDataVersion=1,
        sendUpdates='all'
    ).execute()


    return event

def extract_text_from_pdf(pdf_path):
    pdf_document = fitz.open(pdf_path)
    extracted_text = ""
    for page_num in range(len(pdf_document)):
        page = pdf_document.load_page(page_num)
        page_text = page.get_text()
        extracted_text += page_text
    return extracted_text

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/apply-job', methods=['GET'])
def apply():
    hrcols = hrdb["roles"]
    roles_cursor = hrcols.find({}, {"_id": 0, "Role": 1, "JD": 1})
    roles_list = list(roles_cursor)

    for role in roles_list:
        jd = role.get('JD', '')
        prompt = f"""This is the input text: '{jd}'
        I want to format this text in a neat manner with spaces and new lines.
        Please remove all text formatting like bold and hash tags, etc.
        Return only the cleaned text."""
        completion = groq_client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5,
            max_completion_tokens=4096,
            top_p=0.95,
            stream=False,
        )
        role['JD'] = completion.choices[0].message.content
    
    return render_template('add_applicant.html', roles=roles_list)

@app.route('/upload-pdf', methods=['POST'])
def upload_pdf():
    if 'file' not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400

    if not file.filename.endswith('.pdf'):
        return jsonify({"error": "Invalid file type"}), 400

    try:
        filename = secure_filename(file.filename)
        temp_path = os.path.join(tempfile.gettempdir(), filename)
        file.save(temp_path)
        extracted_text = extract_text_from_pdf(temp_path)
        os.remove(temp_path)
        print(f"✅ PDF extracted successfully: {len(extracted_text)} characters extracted.")
        return jsonify({"resume_content": extracted_text})
    
    except Exception as e:
        print(f"❌ Error extracting text from PDF: {e}")
        return jsonify({"error": "Failed to extract text from PDF"}), 500
    
@app.route('/submit-applicant', methods=['POST'])
def submit_applicant():
    try:
        print("Received Form Data:", request.form)
        name = request.form.get('name')
        email = request.form.get('email')
        role = request.form.get('role')
        resume_content = request.form.get('resume_content')

        if not all([name, email, role, resume_content]):
            return jsonify({"error": "Missing required fields", "received_data": request.form}), 400
        
        existing_app = hrdb["applicants"].find_one({"email": email, "role": role})
        if existing_app is not None:
            return jsonify({"error": "Application already exists for this role."}), 400

        role_doc = hrdb["roles"].find_one({"Role": role})
        if role_doc is None:
            return jsonify({"error": f"Role '{role}' not found in database."}), 404

        jd = role_doc.get("JD", "")
        weights_dict = role_doc.get("weights", {})
        threshold = 60

        score_prompt = f"""This is the desired job description:
            '{jd}'
            ---------------------------------------------------------
            This is the text extracted from the provided resume:
            '{resume_content}'
            ---------------------------------------------------------
            Here is the weightage of mark splitup : {weights_dict}
            ---------------------------------------------------------
            Score threshold to get selected: {threshold}
            ---------------------------------------------------------
            Based on the provided information, I want you to formulate a score for the provided resume on a scale of 100 and also with a reason of why that score is awarded.
            Note that synonyms or shortforms of the topics from the weightage list may have been used in the resume (for example: ML instead of Machine Learning, etc.).
            Do not search for exact words in the job description, but analyse the contents of the weightage as well as the resume contents thoroughly and check if it might be relevant to the topic in the weightage.
            Consider only the points that are relevant to the job description and weightage topics for providing the reasons. 
            Return only the following as a json text:
            ```json
            {{
                "resume_score": <integer (0-100)>,
                "recommendation": "<Approved/Rejected>",
                "key_strengths: ["<strength 1>", "<strength 2>", "<strength 3>"],
                "missing_requirements": ["<missing requirement 1>", "<missing requirement 2>"],
                "skill_scores": [
                    {{
                        "skill": "<skill name>",
                        "score": <integer (0-100)>,
                        "required": <integer (0-100)>,
                        "category": "<category name>"
                    }}
                ],
                "category_scores": [
                    {{
                        "category": "<category name>",
                        "score": <integer (0-100)>,
                        "weight": <integer (0-100)>
                    }}
                ],
                "experience": <integer (0-100)>,
            }}
            ```

            Guidelines:
            1. Basic info must include name, email, overall score, and recommendation and (Ensure that Key strengths and missing requirements should be aligned with job requirements.)
            2. Skills should be evaluated individually with scores compared to job requirements
            3. Categorize skills into groups like "Technical", "Soft Skills", etc., based on the resume content. Don't stick to only these, adapt as required.
            4. Calculate category scores as weighted averages of skill scores in each category that has been provided in the weightage list.
            5. Score breakdown should include main components of the overall score (e.g., Skills, Experience, Education)
            6. Make sure that the keypoints and missing requirements are complete sentences and are relevant to the job description and weightage topics.
            7. All fields must be included even if values are empty
            8. Ensure JSON is valid and properly formatted
            9. Return just the json enclosed within triple backticks followed by the word json, and no other explanatory text or text of any kind.
            10. If no experience is mentioned then consider it as 0 years of experience. Internships and projects are not considered as experience.
            Do not add any additional note or text or comments in the response.
        """
        groq_client = Groq(api_key=GROQ_API_KEY)
        completion = groq_client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": score_prompt}],
            temperature=0.5,
            max_completion_tokens=4096,
            top_p=0.95,
            stream=False,
        )
        result = completion.choices[0].message.content
        print(f"\n\n\nScore Result: {result}")
        # print(result[8:-3])
        score_result = json.loads(result[7:-3])
        applicant = {
            "name": name,
            "email": email,
            "role": role,
            "resume_content": resume_content,
            "score": score_result["resume_score"],
            "key_strengths": score_result["key_strengths"],
            "missing_requirements": score_result["missing_requirements"],
            "skill_scores": score_result["skill_scores"],
            "category_scores": score_result["category_scores"],
            "resume_filtering": score_result["recommendation"],
            "experience": score_result["experience"],
        }

        hrdb["applicants"].insert_one(applicant)

        print(f"✅ Applicant submitted successfully: {applicant}")

        return jsonify({
            "message": "Application submitted successfully!",
            "name": name,
            "email": email,
            "role": role,
            "resume_content": resume_content,
            "score": score_result["resume_score"],
            "key_strengths": score_result["key_strengths"],
            "missing_requirements": score_result["missing_requirements"],
            "skill_scores": score_result["skill_scores"],
            "category_scores": score_result["category_scores"],
            "resume_filtering": score_result["recommendation"]
        })
    
    except Exception as e:
        print(f"❌ Error submitting applicant: {e}")
        return jsonify({"error": "Application submission failed"}), 500

@app.route('/create-role')
def create_role():
    return render_template('create_role.html')

@app.route('/enhance-role', methods=['POST'])
def enhance_role():
    try:
        data = request.get_json()
        role = data.get('role')
        salary_package = data.get('salary_package')
        job_description = data.get('job_description')
        experience = data.get('experience')
        print(f"Received Data: {data}")
        if not role or not job_description:
            return jsonify({"error": "Missing required data"}), 400

        prompt = f"""You are an expert HR consultant and technical recruiter. 
            For the job role '{role}', create a highly detailed and structured job description that includes:
            1. A clear summary of the role and responsibilities.
            2. A detailed list of technical skills, tools, and certifications required. Be very specific(For example in case of AI/ML, mention the exact AI/ML frameworks and libraries required).
            3. A breakdown of responsibilities and expectations.
            4. At least 5 key topics or skills that are crucial for the role, along with a recommended weight
            (ensuring the total sums to 100%).
            Use the following input as context: '{job_description}'
            This is the mentioned salary package in lakhs per annum: {salary_package}
            This is the mentioned experience in years: {experience}
            Return your response in as text formatted as JSON with two keys:
            - 'enhanced_description': a string containing the enhanced job description.
            - 'skills': an array of objects, each with 'skill' (string) and 'weight' (number, as percentage).
            
            The json must be enclosed within triple backticks followed by the word json, and no other explanatory text or text of any kind.
            Here is the json format:
            ```json
            {{
                "enhanced_description": "<text>",
                "skills": [
                    {{
                        "skill": "<skill name>",
                        "weight": <integer (0-100)>
                    }}
                ]
            }}
            ```
            Ensure JSON is valid and properly formatted.
            DO NOT GIVE ANY ADDITIONAL TEXT OR EXPLANATION, JUST RETURN THE JSON."""

        groq_client = Groq(api_key=GROQ_API_KEY)
        completion = groq_client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5,
            max_completion_tokens=4096,
            top_p=0.95,
            stream=False,
        )
        response_text = completion.choices[0].message.content
        print(f"Response Text: {response_text[7:-3]}")
        result = json.loads(response_text[7:-3])
        print(result)
        return jsonify(result)
    
    except Exception as e:
        print(f"❌ Error in enhance_role: {e}")
        return jsonify({"error": "Failed to enhance job description"}), 500

@app.route('/publish-role', methods=['POST'])
def publish_role():
    try:
        data = request.get_json()
        role_name = data.get('role_name')
        exp = data.get('experience')
        salary_package = data.get('salary_package')
        job_description = data.get('job_description')
        weights = data.get('weights')
        
        if not role_name or not job_description or not weights:
            return jsonify({"error": "Missing required fields"}), 400

        role_doc = {
            "Role": role_name,
            "Salary_package": salary_package,
            "JD": job_description,
            "Weights": weights,
            "Experience": exp,
        }

        hrdb["roles"].insert_one(role_doc)
        return jsonify({"message": "Role published successfully!"})
    except Exception as e:
        print(f"❌ Error publishing role: {e}")
        return jsonify({"error": "Failed to publish role"}), 500
    
@app.route('/dashboard')
def dashboard():
    roles_cursor = hrdb["roles"].find({}, {"_id": 0, "Role": 1})
    roles_list = list(roles_cursor)
    return render_template('dashboard.html', roles=roles_list)


@app.route('/get-applicants', methods=['GET'])
def get_applicants():
    role = request.args.get("role")
    if role and role != "all":
        applicants_cursor = hrdb["applicants"].find({"role": role})
    else:
        applicants_cursor = hrdb["applicants"].find()
    applicants = list(applicants_cursor)
    # Convert ObjectId to string for JSON serialization if necessary
    for app in applicants:
        app["_id"] = str(app["_id"])
    return jsonify({"applicants": applicants})

SENDER_EMAIL = os.getenv("EMAIL_SENDER")
SENDER_PASSWORD = os.getenv("EMAIL_APP_PASSWORD")

@app.route('/update-applicant', methods=['POST'])
def update_applicant():
    try:
        data = request.get_json()
        applicant_id = data.get("applicant_id")
        new_status = data.get("round_1_results")

        if not applicant_id or not new_status:
            return jsonify({"error": "Missing required data"}), 400

        applicant = hrdb["applicants"].find_one({"_id": ObjectId(applicant_id)})
        if not applicant:
            return jsonify({"error": "Applicant not found"}), 404
        
        result = hrdb["applicants"].update_one(
            {"_id": ObjectId(applicant_id)},
            {"$set": {"round_1_results": new_status}}
        )
        if result.modified_count != 1:
            return jsonify({"error": "Failed to update status"}), 500

        if new_status == "Approved":
            subject = "You Have Been Selected for the Next Round!"
            body = (
                f"Dear {applicant.get('name', 'Applicant')},\n\n"
                "Congratulations! We are pleased to inform you that you have been selected for the next round of interviews.\n"
                "We will reach out to you shortly with further details.\n\n"
                "Best Regards,\nFuture Tech.AI"
            )
            receiver_email = applicant.get("email")
            if receiver_email:
                send_email_gmail(SENDER_EMAIL, SENDER_PASSWORD, receiver_email, subject, body)

        return jsonify({"message": "Status updated successfully!"})

    except Exception as e:
        print(f"❌ Error updating applicant: {e}")
        return jsonify({"error": "Failed to update applicant"}), 500

@app.route('/hrlogin')
def hrlogin():
    return render_template('hrlogin.html')

@app.route('/schedule-interview', methods=['POST'])
def schedule_interview():
    data = request.get_json()
    applicant_id = data["applicant_id"]
    interview_datetime = data["interview_datetime"]
    interviewers = data["interviewers"]
    interview_datetime = data.get("interview_datetime")  # e.g. "2025-03-15T10:00"

    if not applicant_id or not interview_datetime:
        return jsonify({"error": "Missing required data"}), 400

    applicant = hrdb["applicants"].find_one({"_id": ObjectId(applicant_id)})
    if not applicant:
        return jsonify({"error": "Applicant not found"}), 404

    # Calculate interview count and next interview number
    no_of_interviews = applicant.get("no_of_interviews", 0) + 1

    local_time = datetime.strptime(interview_datetime, "%Y-%m-%dT%H:%M")
    local_tz = pytz.timezone("Asia/Kolkata")
    localized_time = local_tz.localize(local_time)
    utc_time = localized_time.astimezone(pytz.utc)
    iso_start_time = utc_time.strftime('%Y-%m-%dT%H:%M:%S') + 'Z'
    meet_event = schedule_google_meet(
        applicant_name=applicant.get("name"),
        role_name=applicant.get("role"),
        applicant_email=applicant.get("email"),
        iso_start_time=iso_start_time,
        invitee_emails=interviewers
    )
    meet_link = meet_event.get("hangoutLink")
    # 3. Send the email with the real meeting link
    subject = "Interview Scheduled"
    body = (
        f"Dear {applicant.get('name', 'Applicant')},\n\n"
        f"Your interview is scheduled at {interview_datetime}.\n"
        f"Please join using the following Google Meet link: {meet_link}\n\n"
        "Best Regards,\nFuture Tech.AI"
    )
    receiver_email = applicant.get("email")
    if receiver_email:
        send_email_gmail(SENDER_EMAIL, SENDER_PASSWORD, receiver_email, subject, body)

    # 4. Update the applicant record
    interview_doc = {
        "applicant_id": ObjectId(applicant_id),
        "interview_no": no_of_interviews,
        "interview_datetime": interview_datetime,
        "meeting_link": meet_link,
        "meeting_captions": [],
        "interview_summary": {}
    }
    hrdb["interviews"].insert_one(interview_doc)

    # Update applicant: increment interview count
    hrdb["applicants"].update_one(
        {"_id": ObjectId(applicant_id)},
        {"$set": {"no_of_interviews": no_of_interviews,"round_1_results": "Approved"}}
    )
    schedule_bot(meet_link, applicant_id, datetime.fromisoformat(interview_datetime), no_of_interviews, 1)
    return jsonify({"message": "Interview scheduled", "meet_link": meet_event.get("hangoutLink")})

@app.route('/craft-questions')
def upload_files():
    return render_template('craft_questions.html')

@app.route('/add-kb', methods=['POST'])
def add_kb():
    topic = request.form.get("topic")

    if not topic:
        return jsonify({'error': 'Topic is required.'}), 400

    # If no document is uploaded, allow it and return success
    if 'document' not in request.files or request.files['document'].filename == '':
        return jsonify({'message': 'Topic received without file. No document uploaded.'}), 200

    file = request.files['document']

    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        topic_path = os.path.join(app.config['UPLOAD_FOLDER'], topic)
        os.makedirs(topic_path, exist_ok=True)
        file_path = os.path.join(topic_path, filename)
        file.save(file_path)

        # generate_data_store(topic)  # Optional if you want to process now

        return jsonify({'message': 'File uploaded successfully!'}), 200
    else:
        return jsonify({'error': 'Invalid file type'}), 400


@app.route('/generate-questions', methods=['POST'])
def generate_questions():
    data = request.get_json()
    topic = data.get("topic")
    n = data.get("num_questions", 10)

    context_text = ""
    context_section = ""
    topic_path = os.path.join(UPLOAD_FOLDER, topic)

    # Load documents only if the folder exists
    if os.path.exists(topic_path):
        documents = load_documents(topic)
        if documents:
            chunks = split_text(documents)
            context_text = "\n\n".join([chunk.page_content for chunk in chunks])
            context_section = f"\n\nCONTENT:\n{context_text}"

    # Now build prompt whether or not context exists
    prompt = f"""You are an expert technical interviewer.
    Based on the topic "{topic}", generate {n} interview questions along with respective answers.
    The questions should be medium to hard difficulty and test the candidate's understanding deeply.
    The questions and answers must be in the following format:

    1. Question:
    Answer:

    2. Question:
    Answer:

    ...

    Do not include any intro or outro text. Just give the questions and answers.
    -----------------------------------------------------------------------------------------------------------------------------------------
    {context_section}
    """

    groq_client = Groq(api_key=GROQ_API_KEY)
    completion = groq_client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.5,
        max_completion_tokens=4096,
        top_p=0.95,
        stream=False,
    )
    result = completion.choices[0].message.content
    print(result)
    return jsonify({"message": "Questions generated successfully!", "questions": result}), 200

@app.route("/interviewers", methods=["GET"])
def get_interviewers():
    interviewers = os.getenv("INTERVIEWERS", "")
    email_list = [email.strip() for email in interviewers.split(",") if email.strip()]
    return jsonify({"interviewers": email_list})

@app.route("/send-email", methods=["POST"])
def handle_send_email():
    data = request.get_json()
    recipients = data.get("recipients", [])
    subject = data.get("subject", "Generated Interview Questions")
    body = data.get("body", "")

    sender_email = os.getenv("EMAIL_SENDER")
    sender_password = os.getenv("EMAIL_APP_PASSWORD")

    if not sender_email or not sender_password:
        return jsonify({"error": "Email credentials not set in environment."}), 500

    for recipient in recipients:
        send_email_gmail(sender_email, sender_password, recipient, subject, body)

    return jsonify({"success": True, "message": "Emails sent successfully!"}), 200

@app.route('/summarize-interview', methods=['POST'])
def summarize_interview():
    data = request.get_json()
    applicant_id = data.get("applicant_id")
    if not applicant_id:
        return jsonify({"error": "Missing applicant_id"}), 400

    # 1️⃣ Load the applicant
    applicant = hrdb["applicants"].find_one({"_id": ObjectId(applicant_id)})
    if not applicant:
        return jsonify({"error": "Applicant not found"}), 404

    # 2️⃣ Build all interview summaries (exactly as you had)
    no_of_interviews = applicant.get("no_of_interviews", 0)
    if no_of_interviews == 0:
        return jsonify({"error": "No interviews found for this applicant"}), 400

    all_summaries = []
    for interview_no in range(1, no_of_interviews + 1):
        interview = hrdb["interviews"].find_one({
            "applicant_id": ObjectId(applicant_id),
            "interview_no": interview_no
        })
        if not interview or not interview.get("meeting_captions"):
            continue

        captions = interview.get("meeting_captions")
        if not captions:
            print(f"Interview {interview_no} has no captions.")
            continue

        existing = interview.get("interview_summary")
        if existing:
            all_summaries.append({
                "interview_no": interview_no,
                "summary": existing
            })
            continue

        # Generate summary from captions
        transcript = "\n".join(f"{c['speaker']}: {c['caption']}" for c in captions)

        score_prompt = f"""
        You are an expert technical recruiter and talent evaluator. Below is the verbatim interview transcript:

        {transcript}

        ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

        CANDIDATE NAME: {applicant.get("name")}
        Only {applicant.get("name")} is the candidate and the other participants are all interviewers, so please analyze and review only the candidate's performance in the interview.

        Based solely on this transcript, produce an in-depth, recruitment-ready assessment. Your response should include clearly labeled, concise paragraphs covering:

        1. Communication & Clarity: how well the candidate expressed ideas and answered questions.  
        2. Technical Mastery: depth of understanding of concepts discussed.  
        3. Problem-Solving & Critical Thinking: how they approached challenges.  
        4. Soft Skills & Professionalism: confidence, adaptability, listening skills.  
        5. Key Strengths: specific highlights.
        6. Concerns or Gaps: areas needing improvement.

        **IMPORTANT**: NOTE THAT THE PROVIDED TRANSCRIPT IS A DOWNLOADED CAPTION AND MAY CONTAIN ERRORS OR INACCURACIES, SO TRY TO MAKE OUT THE BEST OF IT, AS IT MAY NOT FULLY BE ACCURATE.
        AN OVERALL SUMMARY IS SUFFICIENT, AND NO NEED TO GO INTO THE DETAILS OF EACH AND EVERY POINT DISCUSSED IN THE TRANSCRIPT.
        ENSURE THAT THE MAIN HIGHLIGHTS AND MINUS POINTS OF THE CANDIDATE ARE CLEARLY MENTIONED.
        STRICTLY DO NOT INCLUDE ANY EXAMPLE OR REFERENCES FROM THE TRANSCRIPT.
        NEVER MENTION ANYTHING ABOUT THE TRANSCRIPTION OR ITS ERRORS, IF ANY, DO NOT TELL ABOUT IT.
        Please ensure that the response is well-structured and easy to read, with clear headings for each section.

        Return **only** that SUMMARY AS A JSON enclosed in triple backticks followed by the word json, and no other explanatory text or text of any kind, no extra commentary.
        Here is the json format:

        ```json
        {{
            "communication_clarity": "<text>",
            "technical_mastery": "<text>",
            "problem_solving": "<text>",
            "soft_skills": "<text>",
            "key_strengths": ["<strength 1>", "<strength 2>", "<strength 3>"],
            "concerns_gaps": ["<concern 1>", "<concern 2>"]
        }}
        ```

        Note that each field must give detailed information and be a complete sentence, and all fields must be included even if values are empty.
        Ensure JSON is valid and properly formatted.
        """

        completion = groq_client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": score_prompt}],
            temperature=0.5,
            max_completion_tokens=4096,
            top_p=0.95,
            stream=False,
        )

        summary = completion.choices[0].message.content.strip()

        try:
            json_data = summary[7:-3]
            parsed_summary = json.loads(json_data)
        except Exception as e:
            print(f"Error parsing summary for interview {interview_no}: {e}")
            print("Raw response was:", summary)
            continue

        # Save back into DB
        hrdb["interviews"].update_one(
            {"_id": interview["_id"]},
            {"$set": {"interview_summary": parsed_summary}}
        )

        all_summaries.append({
            "interview_no": interview_no,
            "summary": parsed_summary
        })
    final_recommendation = applicant.get("recommendation_score")
    if final_recommendation is None:
        # 1. Fetch job role details
        job_role = applicant.get("job_role")
        role = hrdb["roles"].find_one({"role_name": job_role}) if job_role else None

        # 2. Format role requirements
        if role and "requirements" in role:
            role_weights = role["requirements"]  # assuming dict: {skill: weight}
            requirements_text = "\n".join(
                f"{skill}: {weight}%" for skill, weight in role_weights.items()
            )
        else:
            role_weights = {}
            requirements_text = "Not Available"

        # 3. Format all interview summaries for the prompt
        combined_summary_text = "\n\n".join(
            f"Interview {s['interview_no']} Summary:\n"
            f"Communication & Clarity: {s['summary'].get('communication_clarity')}\n"
            f"Technical Mastery: {s['summary'].get('technical_mastery')}\n"
            f"Problem Solving: {s['summary'].get('problem_solving')}\n"
            f"Soft Skills: {s['summary'].get('soft_skills')}\n"
            f"Key Strengths: {', '.join(s['summary'].get('key_strengths', []))}\n"
            f"Concerns or Gaps: {', '.join(s['summary'].get('concerns_gaps', []))}"
            for s in all_summaries
        )

        # 4. Construct the final LLM prompt
        recommendation_prompt = f"""
        You are an expert hiring decision maker. Based on the candidate's full profile, job role expectations, and interview summaries, provide a final recruitment recommendation.

        CANDIDATE DETAILS:
        - Name: {applicant.get("name")}
        - Email: {applicant.get("email")}
        - Applied Role: {job_role}
        - Education: {applicant.get("education", "Not provided")}
        - Experience: {applicant.get("experience", "Not provided")} years
        - Additional Notes: {applicant.get("notes", "")}

        ROLE REQUIREMENTS (with skill weights indicating importance):
        {requirements_text}

        INTERVIEW PERFORMANCE SUMMARIES:
        {combined_summary_text}

        ---

        Final Decision:
        Based on the job expectations, skill weightage, and how the candidate performed in interviews, recommend a mark out of 100 for the candidate.

        Be very lineant in the recommendation, and do not be too strict.
        Do not be too strict, you can be lenient if the candidate is good in most areas but lacks in some and if the candidate may seem to have good potential.
        Remember this is just a recommendation and not a final decision.
        Respond with **only the marks** (no notes or explanation)
        """

        # 5. Call LLM
        completion = groq_client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": recommendation_prompt}],
            temperature=0.5,
            max_completion_tokens=1024,
            top_p=0.95,
            stream=False,
        )

        # 6. Parse and handle JSON
        recommendation_raw = completion.choices[0].message.content.strip()

        try:
            final_recommendation = recommendation_raw
        except Exception as e:
            print("Error parsing final recommendation:", e)
            print("Raw recommendation:", recommendation_raw)
            final_recommendation = "Could not generate a recommendation."

        # 7. Final Response
        response = {
            "interview_summaries": all_summaries,
            "final_recommendation": final_recommendation
        }
        hrdb["applicants"].update_one(
            {"_id": applicant["_id"]},
            {"$set": {"recommendation_score": final_recommendation}}
        )
        print("Final Recommendation:", final_recommendation)
        return jsonify(response)
    
    return jsonify({
        "interview_summaries": all_summaries,
        "final_recommendation": final_recommendation
    })

@app.route('/onboard', methods=['POST'])
def onboard():
    data = request.get_json()
    applicant_id = data.get("applicant_id")
    if not applicant_id:
        return jsonify({"error": "Missing applicant_id"}), 400

    # 1️⃣ Load the applicant
    applicant = hrdb["applicants"].find_one({"_id": ObjectId(applicant_id)})
    if not applicant:
        return jsonify({"error": "Applicant not found"}), 404

    # 2️⃣ Send onboarding email
    subject = "Welcome to Future Tech.AI!"
    body = (
        f"Dear {applicant.get('name', 'Applicant')},\n\n"
        "Congratulations on your successful interview process! We are excited to welcome you to Future Tech.AI.\n"
        "Please find the onboarding details attached.\n\n"
        "Best Regards,\nFuture Tech.AI"
    )
    receiver_email = applicant.get("email")
    if receiver_email:
        send_email_gmail(SENDER_EMAIL, SENDER_PASSWORD, receiver_email, subject, body)

    # 3️⃣ Update the applicant record
    hrdb["applicants"].update_one(
        {"_id": ObjectId(applicant_id)},
        {"$set": {"round_1_results": "Onboarded"}}
    )

    return jsonify({"message": "Onboarding email sent successfully!"})

@app.route('/reject', methods=['POST'])
def reject():
    data = request.get_json()
    applicant_id = data.get("applicant_id")
    if not applicant_id:
        return jsonify({"error": "Missing applicant_id"}), 400
    #Update round_1_results to Rejected
    hrdb["applicants"].update_one(
        {"_id": ObjectId(applicant_id)},
        {"$set": {"round_1_results": "Rejected"}}
    )
    return jsonify({"status": "success"}), 200

if __name__ == "__main__":
    app.run(debug=True)