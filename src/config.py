import os
from dotenv import load_dotenv

load_dotenv()

# LLM Provider (Grok/xAI primary, Ollama open-source fallback)
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "xai")  # xai | ollama | auto
XAI_API_KEY = os.getenv("XAI_API_KEY")
GROK_FAST_MODEL = os.getenv("GROK_FAST_MODEL", "grok-4.20-0309-non-reasoning")
GROK_PRO_MODEL = os.getenv("GROK_PRO_MODEL", "grok-4.6")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_FAST_MODEL = os.getenv("OLLAMA_FAST_MODEL", "llama3.2")
OLLAMA_PRO_MODEL = os.getenv("OLLAMA_PRO_MODEL", "llama3.1:8b")
LLM_FALLBACK_ENABLED = os.getenv("LLM_FALLBACK_ENABLED", "true").lower() == "true"

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

# AR / Collections
COLLECTIONS_FROM_EMAIL = os.getenv("COLLECTIONS_FROM_EMAIL")
LIEN_RIGHTS_STATE = os.getenv("LIEN_RIGHTS_STATE", "CA")

# Progress Billing defaults
DEFAULT_DEPOSIT_PERCENT = float(os.getenv("DEFAULT_DEPOSIT_PERCENT", "40"))
DEFAULT_RETAINAGE_PERCENT = float(os.getenv("DEFAULT_RETAINAGE_PERCENT", "10"))

# AP approval thresholds
AP_AUTO_APPROVE_THRESHOLD = float(os.getenv("AP_AUTO_APPROVE_THRESHOLD", "500"))
AP_MANAGER_THRESHOLD = float(os.getenv("AP_MANAGER_THRESHOLD", "5000"))

# Commission defaults
DEFAULT_SALES_REP_SPLIT = float(os.getenv("DEFAULT_SALES_REP_SPLIT", "80"))
DEFAULT_LEAD_SETTER_SPLIT = float(os.getenv("DEFAULT_LEAD_SETTER_SPLIT", "20"))
COMMISSION_CLAWBACK_DAYS = int(os.getenv("COMMISSION_CLAWBACK_DAYS", "90"))
PAYROLL_OVERTIME_THRESHOLD = int(os.getenv("PAYROLL_OVERTIME_THRESHOLD", "40"))
LABOR_BURDEN_RATE = float(os.getenv("LABOR_BURDEN_RATE", "1.35"))

# Cash flow & profitability
CASH_FLOW_ALERT_THRESHOLD = float(os.getenv("CASH_FLOW_ALERT_THRESHOLD", "25000"))
CASH_FLOW_STARTING_BALANCE = float(os.getenv("CASH_FLOW_STARTING_BALANCE", "0"))
FORECAST_WEEKS = int(os.getenv("FORECAST_WEEKS", "13"))
