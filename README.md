<p align="center">
 <i align="center" href="https://demystilex.onrender.com"> Demystilex</i>
  <br><br>
  <h1>🧠 DemystiLex</h1>
  <h3>Legal documents finally made simple • AI-powered • Bengaluru vibes</h3>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python"/>
  <img src="https://img.shields.io/badge/Flask-000000?style=for-the-badge&logo=flask&logoColor=white" alt="Flask"/>
  <img src="https://img.shields.io/badge/Powered%20by-Gemini%20AI-8B5CF6?style=for-the-badge&logo=google-gemini&logoColor=white" alt="Gemini"/>
  <img src="https://img.shields.io/badge/Generates-PDFs-FF9800?style=for-the-badge&logo=adobeacrobatreader&logoColor=white" alt="PDF"/>
</p>

<br>

<p align="center">
  <strong>Say goodbye to scary legal documents and confusing clauses forever!</strong><br>
  <em>"Is this document trust worthy to sign?" → never again.</em>
</p>

<br>

## 🌟 What DemystiLex Actually Does

| Feature                              | Description                                                                 | Why you'll love it                     |
|--------------------------------------|-----------------------------------------------------------------------------|----------------------------------------|
| 📄 **Demystify**                     | Turns complicated legal text into simple, everyday language + mindmap      | Finally understand what you’re signing |
| ✨ **AI Clause Wizard**              | Generate fair, modern, practical rental clauses instantly                   | No more copy-paste from shady websites |
| 🏠 **Rental Agreement Generator**    | Beautiful, ready-to-print 11-month agreement PDF in seconds                | Karnataka-style, professional look     |
| 💬 **LexiCounsel Chatbot**           | Ask questions — answers **only** from your uploaded document                | Your personal document paralegal       |
| 🌐 **Multi-language Translation**    | Translate legal docs to Hindi, Tamil, Kannada-friendly versions & more     | Real multilingual support              |
| ⚠️ **Risky Clause Scanner**          | Quick health-check — finds unfair or risky clauses in rental agreements    | Protect yourself from bad deals        |
| 🔍 **E-Stamp Detector**              | Instantly finds and highlights e-stamp numbers                              | Easy verification                      |
| 📊 **Daily Dashboard**               | See everything you did **today** — disappears after logout (privacy first) | Clean, no creepy long-term tracking    |

<br>

## 🚀 Quick Start (Local Development)

```bash
# 1. Clone the repository
git clone https://github.com/Adan-2128/demystilex.git
cd demystilex

# 2. Create virtual environment
python -m venv venv
source venv/bin/activate          # ← Windows users: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Set up environment variables (very important!)
cp .env.example .env

# 5. Edit .env file and add your keys:
# GEMINI_API_KEY=your-gemini-api-key-here
# SECRET_KEY=some-very-long-random-secret-string

# 6. Create required folders (important!)
mkdir -p uploads instance

# 7. Run the application 🎉
python app.py



