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

~~AR, Progress Billing~~ AP (Bill.com), Commission, Payroll (BambooHR), Job Costing, Profitability, Change Order, Sub Compliance, Cash Flow

### Built Agents

- **AR Agent**: AR aging, overdue tracking, payment matching, collections drafts, lien rights alerts
- **Progress Billing Agent**: Job setup, deposit/milestone/final/retainage invoicing, billing-behind alerts

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

Copy the example file and fill in your values:

```bash
cp .env.example .env
```

See [.env.example](.env.example) for all required variables.

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
| `/finance/ar/summary` | GET | AR summary (outstanding, overdue) |
| `/finance/ar/aging` | GET | AR aging buckets (7/14/30/60 day) |
| `/finance/ar/overdue` | GET | Overdue invoices |
| `/finance/ar/collections` | POST | Draft collections emails for overdue |
| `/finance/ar/lien-rights` | GET | Lien rights deadline alert |
| `/finance/jobs` | POST/GET | Create/list jobs |
| `/finance/jobs/{id}/invoice/deposit` | POST | Invoice contract deposit |
| `/finance/jobs/{id}/invoice/milestone/{name}` | POST | Invoice milestone draw |
| `/finance/jobs/{id}/invoice/final` | POST | Final invoice (less retainage) |
| `/finance/jobs/{id}/invoice/retainage` | POST | Retainage release invoice |
| `/finance/jobs/alerts` | GET | Jobs where billing is behind completion |
| `/chat/webhook` | POST | Google Chat CARD_CLICKED handler |

## Critical Guardrails

- **Human-in-the-loop**: All payments require human approval via Google Chat or Gmail
- **No bank access**: Agents read Chase data only through QuickBooks bank register
- **Draft-only email**: Customer/vendor emails are drafts, never auto-sent
- **First action wins**: Dual-channel approvals sync automatically

## Architecture Doc

Full 13-agent plan: [docs/FINANCE_ARCHITECTURE.md](docs/FINANCE_ARCHITECTURE.md)
