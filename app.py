import os
import threading
import json
import uuid
import io
import hashlib
import logging
import re
import urllib.request
import tarfile
import tempfile
import shutil
from flask import (
    Flask, request, jsonify, redirect, url_for, send_file, render_template, session
)
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import (
    LoginManager, UserMixin, login_user, login_required, logout_user, current_user
)
from dotenv import load_dotenv
from datetime import datetime
from fpdf import FPDF
from flask_session import Session

# --- Library Imports ---
import google.generativeai as genai
from gtts import gTTS
import pdfplumber

# --- Basic Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
app = Flask(__name__)
app.config.update(
    SECRET_KEY = os.getenv("SECRET_KEY"),          # you already have this
    SESSION_TYPE = 'filesystem',
    SESSION_PERMANENT = False,
    
    # Very important security settings – add these:
    SESSION_COOKIE_HTTPONLY    = True,
    SESSION_COOKIE_SECURE      = True,          # ← change to False only during local dev without https
    SESSION_COOKIE_SAMESITE    = 'Lax',         # 'Strict' is also fine, but 'Lax' is more practical
    SESSION_COOKIE_NAME        = 'yourapp_session',   # optional – makes it harder to guess
    PERMANENT_SESSION_LIFETIME = 3600 * 24 * 14,      # 14 days example
    SESSION_REFRESH_EACH_REQUEST = True,
)

# Then continue with the rest...
Session(app)

# --- Configuration ---
try:
    load_dotenv('gemini.env')
    app.config['SECRET_KEY'] = os.getenv("SECRET_KEY")
    app.config['SESSION_TYPE'] = 'filesystem'
    app.config['SESSION_PERMANENT'] = False
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY not found in environment variables")
    genai.configure(api_key=GEMINI_API_KEY)
except Exception as e:
    logging.error(f"Configuration Error: {str(e)}")
    raise

Session(app)
TTS_CACHE_DIR = 'tts_cache'
os.makedirs(TTS_CACHE_DIR, exist_ok=True)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# --- In-Memory Data Stores ---
users = {'user1': {'password_hash': generate_password_hash('password123'), 'username': 'user1'}}
translation_tasks = {}
user_history = {}

class User(UserMixin):
    def __init__(self, id, username, password_hash):
        self.id = id
        self.username = username
        self.password_hash = password_hash

@login_manager.user_loader
def load_user(user_id):
    user_data = users.get(user_id)
    if user_data:
        return User(user_id, user_data['username'], user_data['password_hash'])
    return None

# --- Font Setup (Download once at startup) ---
FONT_DIR = os.path.join(app.root_path, 'fonts')
os.makedirs(FONT_DIR, exist_ok=True)
REGULAR_FONT = os.path.join(FONT_DIR, 'DejaVuSans.ttf')
BOLD_FONT = os.path.join(FONT_DIR, 'DejaVuSans-Bold.ttf')

def download_dejavu_fonts():
    if os.path.exists(REGULAR_FONT) and os.path.exists(BOLD_FONT):
        return  # Already present

    url = "https://github.com/dejavu-fonts/dejavu-fonts/releases/download/version_2_37/dejavu-fonts-ttf-2.37.tar.bz2"
    print("Downloading DejaVu fonts at startup for proper ₹ symbol support...")
    try:
        with tempfile.TemporaryDirectory() as tmp:
            tar_path = os.path.join(tmp, "dejavu.tar.bz2")
            urllib.request.urlretrieve(url, tar_path)
            with tarfile.open(tar_path, "r:bz2") as tar:
                tar.extractall(path=tmp)
            src_dir = os.path.join(tmp, "dejavu-fonts-ttf-2.37", "ttf")
            shutil.copy(os.path.join(src_dir, "DejaVuSans.ttf"), REGULAR_FONT)
            shutil.copy(os.path.join(src_dir, "DejaVuSans-Bold.ttf"), BOLD_FONT)
        print("DejaVu fonts downloaded successfully!")
    except Exception as e:
        print(f"Font download failed: {e}. PDFs will fall back to Helvetica (₹ may appear broken).")

# Run font download once when the app starts
download_dejavu_fonts()

# --- Utility Functions ---
def add_to_history(username, activity_type, content, result=None):
    if username not in user_history:
        user_history[username] = []
    
    history_item = {
        'type': activity_type,
        'content_preview': content[:100] + ('...' if len(content) > 100 else ''),
        'result': result,
        'timestamp': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')
    }
    user_history[username].insert(0, history_item)

def extract_text_from_file(file):
    filename = file.filename
    if not filename or not filename.lower().endswith(('.txt', '.pdf')):
        return None, "Unsupported file type."
    file.seek(0)
    text = ""
    try:
        if filename.lower().endswith('.txt'):
            text = file.read().decode('utf-8')
        elif filename.lower().endswith('.pdf'):
            with pdfplumber.open(io.BytesIO(file.read())) as pdf:
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text + "\n"
        if not text.strip():
            return None, "Could not extract any text from the document."
        return text, None
    except Exception as e:
        logging.error(f"File extraction failed for {filename}: {str(e)}")
        return None, "Failed to process the file."

def run_translation_task(task_id, user_id, content, languages, is_file):
    try:
        if is_file:
            text_to_translate, error = extract_text_from_file(content)
            if error:
                raise ValueError(error)
        else:
            text_to_translate = content

        language_map = {
            'es': 'Spanish', 'fr': 'French', 'de': 'German',
            'hi': 'Hindi', 'ja': 'Japanese', 'ko': 'Korean',
            'zh-CN': 'Chinese (Simplified)'
        }
        
        translations = {}
        model = genai.GenerativeModel('gemini-2.5-flash')

        for lang_code in languages:
            try:
                lang_name = language_map.get(lang_code, lang_code)
                prompt = f"Translate the following legal document text to {lang_name}. Provide only the translated text as the output:\n\n---\n\n{text_to_translate}"
                response = model.generate_content(prompt)
                translations[lang_code] = {'translated': response.text}
            except Exception as e:
                logging.error(f"Translation to {lang_code} failed: {str(e)}")
                translations[lang_code] = {'error': f"Translation to {lang_name} failed."}

        translation_tasks[task_id] = {'status': 'completed', 'result': {'translations': translations}}
        add_to_history(user_id, 'Translation', text_to_translate, result={'translations': translations})

    except Exception as e:
        logging.error(f"Translation task {task_id} failed entirely: {str(e)}")
        translation_tasks[task_id] = {'status': 'failed', 'result': {'error': str(e)}}

# --- Frontend & Auth Routes ---
@app.route('/')
@login_required
def index():
    return render_template('index.html')

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/demystify')
@login_required
def demystify():
    return render_template('demystify.html')

@app.route('/translate')
@login_required
def translate():
    return render_template('translate.html')

@app.route('/chatbot')
@login_required
def chatbot_page():
    return render_template('chatbot.html')

@app.route('/tools')
@login_required
def tools():
    return render_template('tools.html')

@app.route('/lawyer-links')
@login_required
def lawyer_links():
    return render_template('lawyer_links.html')

@app.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user_data = users.get(username)
        if user_data and check_password_hash(user_data['password_hash'], password):
            session.clear()
            user = User(id=username, username=username, password_hash=user_data['password_hash'])
            login_user(user)
            return jsonify({'message': 'Login successful'}), 200
        return jsonify({'error': 'Invalid username or password'}), 401
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        if not username or not password:
            return jsonify({'error': 'All fields are required'}), 400
        if username in users:
            return jsonify({'error': 'Username already exists'}), 409
        users[username] = {'password_hash': generate_password_hash(password), 'username': username}
        return jsonify({'message': 'Registration successful'}), 200
    return render_template('register.html')

@app.route('/logout')
@login_required
def logout():
    session.clear()
    logout_user()
    return redirect(url_for('login'))

# --- API Routes ---
@app.route('/api/demystify', methods=['POST'])
@login_required
def demystify_api():
    text, error = extract_text_from_file(request.files['file']) if 'file' in request.files and request.files['file'].filename else (request.form.get('text'), None)
    if error or not text:
        return jsonify({'error': error or 'No text or file provided'}), 400
    try:
        model = genai.GenerativeModel('gemini-2.5-flash')
        explanation_prompt = f"Explain the following legal text in simple, clear terms for a non-lawyer:\n\n{text}"
        explanation_response = model.generate_content(explanation_prompt)
        mindmap_prompt = f"""Analyze the legal text and generate a concise mind map as a JSON object. Focus on the 4-6 most critical themes. The JSON must have a 'title' and a 'children' array. Example: {{"title": "Summary", "children": [{{"title": "Theme 1"}}]}}. Provide only the JSON object. Text:\n\n{text}"""
        mindmap_response = model.generate_content(mindmap_prompt)
        mindmap_data = json.loads(mindmap_response.text.strip().replace('```json', '').replace('```', ''))
        
        session['document_context'] = text
        add_to_history(current_user.id, 'Demystification', text, result={'explanation': explanation_response.text})

        return jsonify({'explanation': explanation_response.text, 'mindmap_data': mindmap_data})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/translate', methods=['POST'])
@login_required
def translate_api():
    is_file = 'file' in request.files and request.files['file'].filename != ''
    try:
        if is_file:
            content_file = request.files['file']
            content_bytes = content_file.read()
            content = io.BytesIO(content_bytes)
            content.filename = content_file.filename
            languages = json.loads(request.form.get('languages', '[]'))
        else:
            data = request.get_json()
            content = data.get('text', '')
            languages = data.get('languages', [])
    except (json.JSONDecodeError, KeyError): 
        return jsonify({'error': 'Invalid request format.'}), 400
        
    if not (content if isinstance(content, str) else content.filename) or not languages: 
        return jsonify({'error': 'Missing content or languages.'}), 400
        
    task_id = str(uuid.uuid4())
    translation_tasks[task_id] = {'status': 'processing', 'result': None}
    thread = threading.Thread(target=run_translation_task, args=(task_id, current_user.id, content, languages, is_file))
    thread.start()
    
    return jsonify({'task_id': task_id}), 202

@app.route('/api/translation_status/<task_id>')
@login_required
def get_translation_status(task_id):
    task = translation_tasks.get(task_id)
    return jsonify(task) if task else (jsonify({'status': 'not_found'}), 404)

@app.route('/api/chat', methods=['POST'])
@login_required
def chat_api():
    question = request.get_json().get('question')
    if not question:
        return jsonify({'error': 'No question provided'}), 400
    
    document_context = session.get('document_context')
    
    if document_context:
        prompt = f"""
        SYSTEM INSTRUCTION:
        You are 'LexiCounsel', a specialized AI legal assistant. Your sole purpose is to analyze and answer questions based *strictly* on the legal document provided by the user.
        RULES:
        1.  **Strict Context Adherence:** Base your entire response on the text within the 'DOCUMENT CONTEXT' section. Do not use any external knowledge.
        2.  **No Assumptions:** If the document does not contain the answer, you must state that clearly.
        3.  **Persona:** Maintain a professional, helpful, and neutral tone. Do not give legal advice.
        4.  **Refusal:** If the user's question is unrelated to the document (e.g., general knowledge), politely refuse and state that your function is limited to analyzing the provided text.
        DOCUMENT CONTEXT:\n---\n{document_context}\n---\nUSER'S QUESTION: {question}
        """
    else:
        prompt = f"""
        SYSTEM INSTRUCTION:
        You are 'LexiCounsel', a helpful AI assistant specializing in legal and ethical topics. The user has not provided a specific document.
        RULES:
        1.  **Domain:** Answer the user's question based on your general knowledge of legal principles and ethical frameworks, particularly within the context of India.
        2.  **Disclaimer:** You MUST begin your response with the following disclaimer: "Disclaimer: I am an AI assistant and cannot provide legal advice. The following information is for educational purposes only. Please consult with a qualified professional for any legal concerns."
        3.  **Persona:** Maintain a professional, informative, and neutral tone.
        USER'S QUESTION: {question}
        """
        
    try:
        model = genai.GenerativeModel('gemini-2.5-flash')
        response = model.generate_content(prompt)
        return jsonify({'response': response.text})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/speak', methods=['POST'])
@login_required
def speak_api():
    text = request.get_json().get('text')
    if not text:
        return jsonify({'error': 'No text provided'}), 400

    try:
        text_hash = hashlib.md5(text.encode('utf-8')).hexdigest()
        filename = f"{text_hash}.mp3"
        filepath = os.path.join(TTS_CACHE_DIR, filename)

        if not os.path.exists(filepath):
            tts = gTTS(text=text, lang='en', slow=False)
            tts.save(filepath)
        
        return send_file(filepath, mimetype='audio/mpeg')

    except Exception as e:
        logging.error(f"Text-to-speech generation failed: {str(e)}")
        return jsonify({'error': f'Failed to generate audio: {str(e)}'}), 500

@app.route('/api/history')
@login_required
def get_history():
    return jsonify(user_history.get(current_user.id, []))

@app.route('/api/clear_context', methods=['POST'])
@login_required
def clear_context():
    session.pop('document_context', None)
    return jsonify({'message': 'Context cleared'}), 200

# --- Legal Tools API Routes ---
@app.route('/api/verify_estamp', methods=['POST'])
@login_required
def verify_estamp_api():
    text, error = extract_text_from_file(request.files['file']) if 'file' in request.files else (None, "A file is required.")
    if error or not text:
        return jsonify({'error': error or 'No text found in file'}), 400

    uin_pattern = r'IN-[A-Z]{2}\d{12}[A-Z]'
    match = re.search(uin_pattern, text)

    if not match:
        return jsonify({'status': 'not_found', 'reason': 'Could not find a valid E-Stamp Number (UIN) in the document.'})

    uin = match.group(0)
    
    return jsonify({
        'status': 'found',
        'uin': uin,
        'verification_url': 'https://www.shcilestamp.com/eStamp_en/verifyestamp.jsp'
    })

@app.route('/api/compare_clauses', methods=['POST'])
@login_required
def compare_clauses_api():
    data = request.get_json()
    user_document_text = data.get('text')
    if not user_document_text:
        return jsonify({'error': 'Document text is required.'}), 400

    try:
        model = genai.GenerativeModel('gemini-2.5-flash')
        prompt = f"""
        You are a legal document analyst. Compare the provided "User's Document" against standard principles for a residential rental agreement in India.
        Analyze and identify three categories, responding in a valid JSON format.
        1.  "missing_clauses": A list of important, standard clauses that are absent.
        2.  "risky_clauses": A list of clauses present that seem unfair or risky for a tenant.
        3.  "summary": A brief, one-paragraph overall assessment of the document.
        Standard Principles: Clearly defined parties, property, term, rent, deposit, a reasonable notice period (1-2 months), maintenance responsibilities.
        User's Document:\n---\n{user_document_text}\n---
        Provide a single, valid JSON object with the keys "missing_clauses", "risky_clauses", and "summary".
        """
        response = model.generate_content(prompt)
        cleaned_response = response.text.strip().replace('```json', '').replace('```', '')
        analysis_result = json.loads(cleaned_response)
        return jsonify(analysis_result)
        
    except Exception as e:
        logging.error(f"Clause comparison failed: {str(e)}")
        return jsonify({'error': f'AI analysis failed: {str(e)}'}), 500

@app.route('/draft_pdf', methods=['POST'])
@login_required
def draft_pdf_route():
    data = request.form
    additional_clauses = data.get('additional_clauses', '').strip()

    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)

    # Font setup
    use_dejavu = os.path.exists(REGULAR_FONT)
    if use_dejavu:
        pdf.add_font('DejaVu', '', REGULAR_FONT, uni=True)
        pdf.add_font('DejaVu', 'B', BOLD_FONT if os.path.exists(BOLD_FONT) else REGULAR_FONT, uni=True)

    font_family = 'DejaVu' if use_dejavu else 'Helvetica'

    # ─── Safety constants ─────────────────────────────────────
    PAGE_WIDTH_MM = 210
    MARGIN = 15
    MAX_CONTENT_WIDTH = PAGE_WIDTH_MM - 2 * MARGIN  # ≈ 180mm
    MAX_NAME_WIDTH = 170                           # very safe value
    MAX_NAME_DISPLAY_LENGTH = 65                   # characters

    # ─── Helper function for safe name printing ───────────────
    def print_centered_bold_name(pdf, raw_name, suffix="(LANDLORD)", width=MAX_NAME_WIDTH):
        name = (raw_name or "________________________").strip()
        
        # Truncate extremely long names
        if len(name) > MAX_NAME_DISPLAY_LENGTH:
            name = name[:MAX_NAME_DISPLAY_LENGTH - 3] + "..."
            
        full_line = f"{name} {suffix}"
        
        pdf.set_font(font_family, 'B', 12)
        pdf.multi_cell(width, 10, full_line, align='C')

    # ─── Document content starts here ──────────────────────────
    # Title
    pdf.set_font(font_family, 'B', 18)
    pdf.cell(0, 15, 'RENTAL AGREEMENT', ln=True, align='C')
    pdf.ln(12)

    # Opening sentence
    pdf.set_font(font_family, '', 12)
    pdf.multi_cell(MAX_CONTENT_WIDTH, 10,
                   f"This Rental Agreement is made on {data.get('agreement_date', '____________')}",
                   align='L')

    pdf.ln(10)
    pdf.multi_cell(MAX_CONTENT_WIDTH, 10, "BETWEEN", align='C')

    # Landlord name
    print_centered_bold_name(pdf, data.get('landlord_name'), "(LANDLORD)")

    pdf.set_font(font_family, '', 12)
    pdf.ln(6)
    pdf.multi_cell(MAX_CONTENT_WIDTH, 10, "AND", align='C')

    # Tenant name
    print_centered_bold_name(pdf, data.get('tenant_name'), "(TENANT)")

    pdf.ln(14)

    # Property
    pdf.set_font(font_family, '', 12)
    pdf.multi_cell(MAX_CONTENT_WIDTH, 10,
                   f"Property: {data.get('property_address', 'Full Address of the Property')}",
                   align='L')

    pdf.ln(12)

    # Key terms
    pdf.set_font(font_family, 'B', 13)
    pdf.multi_cell(MAX_CONTENT_WIDTH, 11,
                   f"1. Lease Term          : {data.get('term_months', '11')} months",
                   align='L')
    pdf.multi_cell(MAX_CONTENT_WIDTH, 11,
                   f"2. Monthly Rent        : ₹ {data.get('rent_amount', '0')}/-",
                   align='L')
    pdf.multi_cell(MAX_CONTENT_WIDTH, 11,
                   f"3. Security Deposit    : ₹ {data.get('deposit_amount', '0')}/-",
                   align='L')

    # Additional clauses
    if additional_clauses:
        pdf.ln(14)
        pdf.set_font(font_family, '', 11)
        
        import textwrap
        for line in additional_clauses.splitlines():
            line = line.strip()
            if line:
                wrapped = textwrap.fill(line, width=95)
                pdf.multi_cell(MAX_CONTENT_WIDTH, 8, wrapped, align='L')

    # Closing
    pdf.ln(28)
    pdf.set_font(font_family, '', 12)
    pdf.multi_cell(MAX_CONTENT_WIDTH, 10,
                   "IN WITNESS WHEREOF, the parties hereto have executed this agreement on the day and year first above written.",
                   align='L')

    pdf.ln(35)

    pdf.set_font(font_family, '', 12)
    pdf.multi_cell(MAX_CONTENT_WIDTH, 10,
                   "_____________________________                  _____________________________",
                   align='C')
    pdf.multi_cell(MAX_CONTENT_WIDTH, 10,
                   "LANDLORD                                                            TENANT",
                   align='C')

    # ─── Output ────────────────────────────────────────────────
    pdf_bytes = pdf.output(dest='S').encode('latin-1')

    return send_file(
        io.BytesIO(pdf_bytes),
        as_attachment=True,
        download_name="Rental_Agreement_Draft.pdf",
        mimetype="application/pdf"
    )

@app.route('/api/extract_key_dates', methods=['POST'])
@login_required
def extract_key_dates_api():
    if 'file' not in request.files or not request.files['file'].filename:
        return jsonify({'error': 'No file was provided.'}), 400
        
    text, error = extract_text_from_file(request.files['file'])
    if error or not text:
        return jsonify({'error': error or 'No text or file provided'}), 400

    try:
        model = genai.GenerativeModel('gemini-2.5-flash')
        prompt = f"""
        Analyze the following legal document and extract all key dates.
        For each date found, identify its legal significance (e.g., "Agreement Start Date", "Lease Expiry Date", "Notice Date").
        Provide the result as a single, valid JSON array of objects, where each object has a "date" and a "significance" key.
        Example: [{{"date": "2024-01-01", "significance": "Effective Start Date"}}]

        --- DOCUMENT TEXT ---
        {text}
        """
        response = model.generate_content(prompt)
        cleaned_response = response.text.strip().replace('```json', '').replace('```', '')
        dates_result = json.loads(cleaned_response)
        
        return jsonify({'key_dates': dates_result})
        
    except Exception as e:
        logging.error(f"Key date extraction failed: {str(e)}")
        return jsonify({'error': f'AI date extraction failed: {str(e)}'}), 500

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=True)