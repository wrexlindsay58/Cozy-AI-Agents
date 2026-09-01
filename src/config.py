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
    'https://www.googleapis.com/auth/chat.messages',
    'https://www.googleapis.com/auth/chat.spaces',
]

# Database
DB_PATH = os.getenv("DB_PATH", "assistant.db")

# Google Drive (document storage)
RECEIPTS_FOLDER_ID = os.getenv("RECEIPTS_FOLDER_ID")

# RAG
CHROMA_DB_DIR = os.getenv("CHROMA_DB_DIR", "./chroma_db")

# QuickBooks Online
QUICKBOOKS_CLIENT_ID = os.getenv("QUICKBOOKS_CLIENT_ID")
QUICKBOOKS_CLIENT_SECRET = os.getenv("QUICKBOOKS_CLIENT_SECRET")
QUICKBOOKS_REALM_ID = os.getenv("QUICKBOOKS_REALM_ID")
QUICKBOOKS_REFRESH_TOKEN = os.getenv("QUICKBOOKS_REFRESH_TOKEN")
QUICKBOOKS_ENVIRONMENT = os.getenv("QUICKBOOKS_ENVIRONMENT", "sandbox")

# Bill.com
BILLCOM_DEV_KEY = os.getenv("BILLCOM_DEV_KEY")
BILLCOM_ORG_ID = os.getenv("BILLCOM_ORG_ID")
BILLCOM_USERNAME = os.getenv("BILLCOM_USERNAME")
BILLCOM_PASSWORD = os.getenv("BILLCOM_PASSWORD")
BILLCOM_ENVIRONMENT = os.getenv("BILLCOM_ENVIRONMENT", "sandbox")

# BambooHR
BAMBOOHR_SUBDOMAIN = os.getenv("BAMBOOHR_SUBDOMAIN")
BAMBOOHR_API_KEY = os.getenv("BAMBOOHR_API_KEY")

# Google Chat
GOOGLE_CHAT_SPACE = os.getenv("GOOGLE_CHAT_SPACE")  # e.g. spaces/AAAA...
APPROVAL_BASE_URL = os.getenv("APPROVAL_BASE_URL", "http://localhost:3000")

# Approval routing
DEFAULT_APPROVER_EMAIL = os.getenv("DEFAULT_APPROVER_EMAIL")
APPROVAL_ESCALATION_HOURS = int(os.getenv("APPROVAL_ESCALATION_HOURS", "24"))
