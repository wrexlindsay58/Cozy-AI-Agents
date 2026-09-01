# Cozy Finance Agents

An autonomous multi-agent finance system for home services / home improvement companies. Built with Python, LangGraph, Gemini, and Google Workspace.

## Features

- **Finance Orchestrator**: Routes financial emails to specialist agents
- **Approval Gateway**: Dual-channel approvals via Google Chat AND Gmail
- **Controller Agent**: Bank reconciliation checks, month-end close checklist, data quality
- **Triage Agent**: Classifies incoming emails (bills, invoices, vendor docs, scheduling, etc.)
- **Scheduling Agent**: Checks availability and drafts meeting replies
- **Second Brain Agent**: RAG-powered context for email drafts

### Planned Agents (see [docs/FINANCE_ARCHITECTURE.md](docs/FINANCE_ARCHITECTURE.md))

AR, AP (Bill.com), Commission, Payroll (BambooHR), Job Costing, Profitability, Progress Billing, Change Order, Sub Compliance, Cash Flow

## Architecture

- **LangGraph**: Multi-agent workflow orchestration
- **Gemini API**: Flash for triage, Pro for complex reasoning
- **QuickBooks Online**: System of record (invoices, bills, bank register)
- **Bill.com**: AP and payment proposals (planned)
- **BambooHR**: Payroll and commissions (planned)
- **Google Chat + Gmail**: Dual-channel approval queue
- **SQLite**: Approval queue and state tracking

## Setup

### 1. Google Cloud Console

Enable APIs: Gmail, Calendar, Tasks, Drive, **Google Chat**

OAuth scopes are configured in `src/config.py`. Download `credentials.json` to project root.

### 2. Environment Variables

```env
GEMINI_API_KEY=your_gemini_api_key
DB_PATH=assistant.db

# QuickBooks Online
QUICKBOOKS_CLIENT_ID=
QUICKBOOKS_CLIENT_SECRET=
QUICKBOOKS_REALM_ID=
QUICKBOOKS_REFRESH_TOKEN=
QUICKBOOKS_ENVIRONMENT=sandbox

# Bill.com (Phase 3)
BILLCOM_DEV_KEY=
BILLCOM_ORG_ID=
BILLCOM_USERNAME=
BILLCOM_PASSWORD=

# BambooHR (Phase 5)
BAMBOOHR_SUBDOMAIN=
BAMBOOHR_API_KEY=

# Google Chat approvals
GOOGLE_CHAT_SPACE=spaces/AAAA...
DEFAULT_APPROVER_EMAIL=owner@company.com
APPROVAL_BASE_URL=https://your-domain.com
```

### 3. Install and Run

```bash
pip install -r requirements.txt
python -m src.main
```

## API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/sync` | GET | Process unread emails |
| `/finance/approvals` | POST | Submit approval proposal (dual-channel) |
| `/finance/approvals/pending` | GET | List pending approvals |
| `/approve/{token}` | GET | Gmail approval page |
| `/finance/reconciliation` | GET | Run reconciliation check |
| `/finance/close-checklist` | GET | Month-end close checklist |
| `/finance/data-quality` | GET | Data quality scan |
| `/chat/webhook` | POST | Google Chat CARD_CLICKED handler |

## Critical Guardrails

- **Human-in-the-loop**: All payments require human approval via Google Chat or Gmail
- **No bank access**: Agents read Chase data only through QuickBooks bank register
- **Draft-only email**: Customer/vendor emails are drafts, never auto-sent
- **First action wins**: Dual-channel approvals sync automatically

## Architecture Doc

Full 13-agent plan: [docs/FINANCE_ARCHITECTURE.md](docs/FINANCE_ARCHITECTURE.md)
