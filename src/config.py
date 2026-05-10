import os
from dotenv import load_dotenv

load_dotenv()

# Gemini API Keys
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Google API Scopes
SCOPES = [
    'https://www.googleapis.com/auth/gmail.modify',
    'https://www.googleapis.com/auth/calendar',
    'https://www.googleapis.com/auth/tasks',
    'https://www.googleapis.com/auth/drive.file',
    'https://www.googleapis.com/auth/spreadsheets'
]

# Database
DB_PATH = os.getenv("DB_PATH", "assistant.db")

# Google Sheets / Drive
RECEIPTS_SHEET_ID = os.getenv("RECEIPTS_SHEET_ID")
RECEIPTS_FOLDER_ID = os.getenv("RECEIPTS_FOLDER_ID")

# RAG
CHROMA_DB_DIR = os.getenv("CHROMA_DB_DIR", "./chroma_db")
