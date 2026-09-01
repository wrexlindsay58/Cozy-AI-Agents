# Finance Agent Architecture — Home Services / Home Improvement

## Executive Summary

**13 agents total:** 1 orchestrator + 12 specialists.

Your stack is **QuickBooks Online (system of record) + Bill.com (AP/payments) + BambooHR (payroll)**. Approvals flow through **Google Chat and Gmail** (dual-channel — approver picks either). Agents never touch Chase directly.

**Scrap:** Google Sheets receipt tracking and the old Bookkeeper Agent (`extract_expense_details` / `expense_node`).

---

## Security Model: Capable Agents, No Bank Access

### The Golden Rule

> **Agents operate on accounting and approval systems, never on bank credentials.**

```mermaid
flowchart TB
    subgraph humanOnly [HumanOnlyZone]
        Chase[ChaseBank]
        BillApprove[Bill.comApprovalUI]
        BambooApprove[BambooHRPayrollRun]
    end

    subgraph agentZone [AgentZone_ReadWrite]
        QBO[QuickBooksOnline]
        BillAPI[Bill.comAPI]
        BambooAPI[BambooHRAPI]
    end

    subgraph agents [AIAgents]
        Orch[FinanceOrchestrator]
        Specialists[12SpecialistAgents]
    end

    subgraph comms [CommunicationAndApproval]
        GChat[GoogleChatCards]
        EmailDrafts[GmailDraftsAndFallback]
        ApprovalQueue[ApprovalQueue_DB]
    end

    Chase -->|"Native QBO bank feed (human connects once)"| QBO
    Orch --> Specialists
    Specialists --> QBO
    Specialists --> BillAPI
    Specialists --> BambooAPI
    Specialists --> ApprovalQueue
    ApprovalQueue --> GChat
    ApprovalQueue --> EmailDrafts
    Specialists --> EmailDrafts

    BillAPI -->|"Payment proposal only"| BillApprove
    BambooAPI -->|"Payroll proposal only"| BambooApprove
    BillApprove -->|"Human executes payment"| Chase
    BambooApprove -->|"Human runs payroll"| Chase
```

### Chase: QuickBooks, Not Plaid (for agents)

| Approach | Who connects | Agent access | Recommendation |
|---|---|---|---|
| **QBO native bank feed** | You or your bookkeeper, once, in QBO settings | None — agent reads transactions from QBO API only | **Use this** |
| **Plaid → your app** | Your app holds Plaid tokens | Agent could read balances/transactions directly | **Skip** — unnecessary attack surface |
| **Plaid → QBO** | QBO uses Plaid under the hood for Chase | Same as row 1 — agent still only sees QBO | This is what QBO already does |

**Why QuickBooks is enough:** Chase transactions appear in QBO within 24–48 hours. Your Controller Agent reconciles against QBO bank register data. For AP payments, Bill.com handles disbursement after human approval — the agent never initiates a wire/ACH.

**When you might add Plaid later (still no agent access):** A separate read-only cash dashboard service (not an LLM agent) with scoped Plaid tokens for real-time balance display. Keep it outside the agent loop.

### Permission Tiers

| Tier | Systems | Agent can do | Human must do |
|---|---|---|---|
| **Read** | QBO, Bill.com, BambooHR | Query invoices, bills, jobs, payroll, bank register (via QBO) | — |
| **Propose** | QBO, Bill.com, BambooHR | Create draft bills, invoices, JEs, payment batches, commission accruals | — |
| **Approve** | Bill.com, BambooHR, Approval Queue | — | Approve/reject every payment and payroll run |
| **Execute** | Chase | — | All money movement |

### Audit Trail Requirements

Every agent action logs: `agent_name`, `action`, `entity_id`, `before_state`, `after_state`, `timestamp`, `human_approver` (if applicable). No silent writes to QBO or Bill.com.

---

## Integration Architecture

```mermaid
flowchart LR
    subgraph sources [DataSources]
        Email[Email/Gmail]
        JobSystem[JobCRM]
        Time[BambooHRTime]
    end

    subgraph core [CoreStack]
        QBO[QuickBooksOnline]
        Bill[Bill.com]
        Bamboo[BambooHR]
    end

    subgraph agents [AgentLayer]
        Orch[Orchestrator]
        Specs[Specialists]
    end

    subgraph output [CommsAndApproval]
        GChat[GoogleChat]
        Gmail[Gmail]
        Approvals[ApprovalQueue]
    end

    Email --> Orch
    JobSystem --> Orch
    Orch --> Specs
    Specs --> QBO
    Specs --> Bill
    Specs --> Bamboo
    Bill <-->|"2-way sync"| QBO
    Bamboo -->|"Payroll JE sync"| QBO
    Specs --> Approvals
    Approvals --> GChat
    Approvals --> Gmail
```

### QuickBooks Online — System of Record

- Chart of accounts, customers, vendors, jobs (classes/projects)
- Invoices, bills, journal entries, bank register
- Job costing via **Classes** or **Projects** (enable Projects in QBO for home services)
- Bank reconciliation data (fed by Chase → QBO native connection)

**Agent API scope:** `com.intuit.quickbooks.accounting` — read all, write invoices/bills/JEs/expenses. No payment execution scope.

### Bill.com — AP and Payment Rail

- Vendor bill intake, approval workflows, payment scheduling
- Native 2-way sync with QBO (bills, vendors, payments post back to QBO)
- Built-in multi-step approval chains
- Slack integration for approval notifications
- Webhooks for bill-approved, payment-scheduled, payment-completed events

**Agent API scope:** Create/update bills, assign approvers, propose payment batches. **Never** call payment execution endpoints — route to Bill.com approval UI.

### BambooHR — Payroll (Salaries + Commissions)

- Employee records, time tracking, payroll runs
- Commission payments processed through BambooHR payroll (alongside salaries)
- Native QBO integration: payroll journal entries sync to QuickBooks (with QBO Classes for department/job allocation)
- Payroll must be approved and run by a human in BambooHR

**Agent API scope:** Read employee data, time entries, payroll preview. Propose commission amounts for payroll inclusion. **Never** trigger payroll execution.

### Communication and Approval Layer (Google Workspace)

**Decision: Dual-channel approvals via Google Chat and Gmail.**

Every approval proposal is delivered through **both** Google Chat and Gmail. Approvers choose whichever channel is convenient — the first action wins, and the other channel updates automatically. Your codebase already integrates Gmail; Google Chat adds real-time interactive cards.

| Channel | Role |
|---|---|
| **Google Chat** | Real-time approval cards with Approve / Reject / Ask Question buttons; exception alerts; daily financial summary |
| **Gmail** | Approval emails with secure link to a full-detail approval page; customer/vendor drafts (never auto-send); AR collections drafts |
| **Google Tasks** | Supplementary reminders for pending approvals ("3 bills awaiting your review") |
| **Approval Queue (internal DB)** | System of record — single source of truth regardless of which channel the approver uses |

#### Dual-Channel Approval Model

```mermaid
sequenceDiagram
    participant Agent as FinanceAgent
    participant Queue as ApprovalQueue_DB
    participant Chat as GoogleChat
    participant Gmail as Gmail
    participant Human as Approver
    participant Target as Bill.com_or_QBO

    Agent->>Queue: Create proposal (id, type, amount, details)
    par Deliver to both channels
        Queue->>Chat: Post interactive card
        Queue->>Gmail: Send approval email with secure link
    end
    alt Approver uses Chat
        Human->>Chat: Clicks Approve
        Chat->>Queue: Webhook updates status
    else Approver uses Gmail
        Human->>Gmail: Clicks approval page link
        Gmail->>Queue: Web page updates status
    end
    Queue->>Chat: Update card to "Approved by Jane via Gmail"
    Queue->>Gmail: Mark email thread resolved
    Queue->>Target: Route to Bill.com / QBO / BambooHR
```

**Key rules:**
1. **Both channels, every time** — Chat card and Gmail email are sent together for each approval request
2. **First action wins** — approving in Chat immediately invalidates the Gmail link (and vice versa)
3. **Cross-channel sync** — the channel not used shows who approved and when: *"Approved by Jane via Gmail at 2:34 PM"*
4. **Single audit trail** — the Approval Queue DB records the decision, channel used, approver, and timestamp
5. **No double-execution** — idempotent tokens prevent the same approval from processing twice

#### Channel Strengths (why both)

| | Google Chat | Gmail |
|---|---|---|
| **Best for** | Quick in-the-moment approvals, batch review, team visibility | Detailed review on desktop, forwarding to accountant, archival search |
| **Interaction** | Inline Approve/Reject buttons | Secure link to full approval page with attachments and line items |
| **Speed** | Push notification, one click | Email notification, click link, review details, approve |
| **Visibility** | Team space shows all pending items | Personal inbox, easy to search and forward |
| **Attachments** | Link to details | Full bill PDF, job P&L, commission breakdown inline on approval page |

#### Routing by Approval Type

| Approval type | Google Chat | Gmail | Notes |
|---|---|---|---|
| Vendor bills (< $5K) | Card in #finance-approvals | Email to approver | Either channel works |
| Vendor bills (> $5K) | Card + @mention owner | Email with full bill PDF | Gmail better for document review |
| Commission payouts | Card with rep name + amount | Email with commission statement | Both for visibility |
| Journal entries | Card with JE summary | Email with full JE detail | Gmail for complex entries |
| Change orders | Card with margin impact | Email with change order doc | Gmail for customer-facing review |
| Payroll pre-validation | Card with total + flags | Email with payroll summary | BambooHR still runs actual payroll |
| Month-end close items | Card with checklist progress | Email with exception report | Both for CFO review |

#### Google Chat vs Gmail Technical Comparison

| | Google Chat | Gmail (approval page link) |
|---|---|---|
| **Interactive Approve/Reject** | Yes — native card buttons | Yes — web page with Approve/Reject/View details |
| **Setup complexity** | Medium — Chat app + HTTPS webhook | Low — extends existing Gmail tools |
| **Real-time alerts** | Yes — push to space or DM | Yes — email notification |
| **Audit trail** | Webhook logs + approval queue DB | Web page logs + approval queue DB |
| **Batch approvals** | Yes — card lists multiple items | Yes — approval page with checkboxes |
| **Already in codebase** | New integration needed | Partially built (`gmail_tools.py`) |

### Approval Layer

| Workflow | Where approval happens |
|---|---|
| Vendor bills under threshold | Bill.com auto-route + dual-channel notification |
| Vendor bills over threshold | Bill.com → owner/CFO chain + dual-channel notification |
| Commission payouts | Dual-channel → human adds to BambooHR payroll |
| Payroll run | BambooHR native approval (agent pre-validates via dual-channel) |
| Journal entries / adjustments | Dual-channel → human posts to QBO |
| Customer credit memos | Dual-channel |

---

## The 13 Agents

### Tier 1: Core Financial Agents (8)

#### 1. Finance Orchestrator

Routes all financial events to the correct specialist. Enforces permission tiers and deduplication.

**Triggers:** Email, Bill.com webhooks, QBO webhooks, BambooHR events, scheduled jobs (daily close check, weekly AR aging).

**Enhanced capabilities:**
- Priority scoring (overdue AR > routine AP > reporting)
- Cross-agent conflict detection (duplicate bill in QBO and Bill.com)
- Policy enforcement (no payment proposal without approved bill)
- Event bus for agent-to-agent handoffs

---

#### 2. AR Agent (Accounts Receivable)

**Enhanced capabilities:**
- Create QBO progress invoices from job milestones
- Track customer deposits and apply to final invoice
- AR aging with homeowner-specific follow-up cadence (7/14/30/60 day)
- Payment matching (QBO bank deposit → open invoice)
- Draft collections emails (never auto-send)
- Lien rights tracking alerts (state-specific deadlines for home improvement)
- Integration with job system for "job complete → final invoice" trigger

---

#### 3. AP Agent (Accounts Payable) — Bill.com Powered

Replaces the old Bookkeeper Agent entirely.

**Enhanced capabilities:**
- Receive vendor bills via email → create in Bill.com with GL + job coding
- 3-way match: PO/receipt/bill (for material orders)
- Route to correct approver based on amount, vendor, job
- Propose payment batches in Bill.com (human approves in Bill.com UI)
- Track 1099-eligible vendor spend
- Subcontractor bill validation (requires COI on file — handoff to Compliance Agent)
- Sync status monitoring (Bill.com ↔ QBO)

---

#### 4. Commission Agent

**Enhanced capabilities:**
- Rules engine: % of sale, % of gross margin, tiered by job size, split between sales rep and lead setter
- Attribution: tie commission to QBO job/project and sales rep
- Clawback rules (cancelled jobs, warranty callbacks within 90 days)
- Accrual at job milestone (% complete or job close)
- Monthly commission statement generation
- Propose commission amounts to Payroll Agent (does not pay directly)
- Dispute tracking and resolution workflow

---

#### 5. Payroll Agent (NEW)

Coordinates all compensation disbursement. Separate from Commission Agent (calculates) and AP Agent (vendor payments).

**Enhanced capabilities:**
- Read BambooHR employee data, time entries, PTO
- Receive approved commission amounts from Commission Agent
- Pre-validate payroll: total labor cost vs. job budget, overtime flags
- Allocate payroll costs to QBO jobs/classes (via BambooHR → QBO JE sync)
- Propose payroll adjustments (bonus, commission additions, corrections)
- Reconcile BambooHR payroll JEs in QBO after each run
- Certified payroll reporting support (if you do government/Prevailing Wage work)
- **Human runs payroll in BambooHR** — agent only prepares and validates

---

#### 6. Job Costing Agent

**Enhanced capabilities:**
- Real-time job P&L: estimated vs. actual for labor, materials, subs, permits
- Cost allocation from QBO expenses tagged to job class/project
- Labor cost from BambooHR time × burden rate
- Material cost from vendor bills (Bill.com → QBO)
- Subcontractor cost tracking per job
- Overhead allocation (vehicle, insurance, office) by revenue or labor hours
- Budget variance alerts at 80%/100%/120% of estimate
- WIP (work-in-progress) asset tracking for jobs spanning multiple months

---

#### 7. Profitability Agent (Reporting / Analytics)

**Enhanced capabilities:**
- Company P&L, balance sheet, cash flow statement (from QBO)
- Gross margin and net margin by job type (kitchen, bath, roofing, etc.)
- Rep/crew profitability ranking
- Seasonal trend analysis (home services is highly seasonal)
- Estimate-to-actual variance reports
- Dashboard pushed to Google Chat daily/weekly
- Board-ready monthly financial package

---

#### 8. Controller Agent (Reconciliation and Clean Financials)

**Enhanced capabilities:**
- Bank reconciliation using QBO bank register (Chase data, no direct Chase access)
- Match QBO transactions to AR receipts, AP payments, payroll JEs
- Month-end close checklist (15+ steps, tracked to completion)
- Propose adjusting journal entries (with Approval Queue)
- Data quality: uncoded transactions, duplicate bills, orphaned payments
- Intercompany/account balance verification
- Audit trail review and exception queue
- 1099 prep support (cross-reference AP Agent vendor data)

---

### Tier 2: Home Services / Home Improvement Agents (4)

#### 9. Progress Billing Agent

Home improvement jobs run weeks to months. This agent handles milestone-based revenue.

**Capabilities:**
- Deposit invoice at contract signing (typically 30–50%)
- Progress/draw invoices at defined milestones (demo complete, rough-in, finish)
- Retainage holdback tracking (5–10% until punch list complete)
- Final invoice minus deposits and retainage
- Sync all invoices to QBO, linked to job/project
- Alert when billing is behind job completion % (you've done 60% of work but only billed 30%)

---

#### 10. Change Order Agent

Scope changes are the #1 margin killer in home improvement.

**Capabilities:**
- Intake change orders from email, job system, or field reports
- Calculate margin impact (additional revenue vs. additional cost)
- Generate change order invoice in QBO
- Update job budget in Job Costing Agent
- Require customer approval before work begins (draft email with change order doc)
- Track unsigned change orders as risk items on job P&L

---

#### 11. Subcontractor Compliance Agent

Home services relies heavily on subs. Non-compliance = liability.

**Capabilities:**
- Track Certificate of Insurance (COI) expiration per sub
- Block AP Agent from approving sub bills if COI expired
- Lien waiver collection: conditional at payment, unconditional after clearance
- 1099 tracking and year-end prep (feeds Controller Agent)
- Subcontractor W-9 on file verification
- Compliance dashboard and expiration alerts via Google Chat

---

#### 12. Cash Flow Agent

Home improvement is cash-intensive (materials upfront, labor weekly, customer pays on milestones).

**Capabilities:**
- 13-week rolling cash flow forecast (from QBO AR/AP/payroll data)
- "Can we afford this job?" analysis before signing (materials + labor outflow vs. billing schedule)
- Seasonal cash planning (slow winter months)
- Alert when projected cash drops below threshold
- Model impact of accelerating AR collections or deferring AP
- **Reads from QBO only** — no direct bank access

---

### Tier 3: Orchestration Support (1)

#### 13. Approval Gateway Agent

Not a domain specialist — a cross-cutting workflow agent.

**Capabilities:**
- Central approval queue for all agent proposals
- Route to correct approver by type, amount, and urgency
- **Dual-channel delivery:** every proposal posts to Google Chat AND sends a Gmail approval email simultaneously
- Google Chat interactive cards (Approve / Reject / Ask Question)
- Gmail approval emails with secure links to a full-detail approval page
- Cross-channel sync: first action wins, other channel updates automatically
- Idempotent approval tokens prevent double-execution
- Escalation on timeout (24h → manager, 48h → owner) via both channels
- Full audit log: approver, channel used, timestamp, before/after state
- Batch approvals for routine items (e.g., 15 small material bills)

---

## Agent Interaction Map

```mermaid
flowchart TD
    Orch[FinanceOrchestrator]
    AR[ARAgent]
    AP[APAgent]
    Comm[CommissionAgent]
    Pay[PayrollAgent]
    Job[JobCostingAgent]
    Profit[ProfitabilityAgent]
    Ctrl[ControllerAgent]
    ProgBill[ProgressBillingAgent]
    ChgOrder[ChangeOrderAgent]
    SubComp[SubComplianceAgent]
    CashFlow[CashFlowAgent]
    Approval[ApprovalGatewayAgent]

    Orch --> AR
    Orch --> AP
    Orch --> Comm
    Orch --> Pay
    Orch --> Job
    Orch --> Profit
    Orch --> Ctrl
    Orch --> ProgBill
    Orch --> ChgOrder
    Orch --> SubComp
    Orch --> CashFlow

    ProgBill --> AR
    ChgOrder --> Job
    ChgOrder --> AR
    Comm --> Pay
    AP --> SubComp
    SubComp --> Approval
    AP --> Approval
    Comm --> Approval
    Pay --> Approval
    Ctrl --> Approval
    Job --> Profit
    AR --> CashFlow
    AP --> CashFlow
    Pay --> CashFlow
    Profit --> CashFlow
```

---

## What to Scrap from Current Codebase

| Remove | Replace with |
|---|---|
| `extract_expense_details()` in `src/agents.py` | AP Agent → Bill.com bill creation |
| `expense_node` in `src/graph.py` | AP Agent node |
| `RECEIPT` triage category | `BILL`, `INVOICE`, `VENDOR_DOC` categories |
| `append_to_sheet()` calls | QBO API + Bill.com API |
| `RECEIPTS_SHEET_ID` config | `QUICKBOOKS_REALM_ID`, `BILLCOM_ORG_ID`, `BAMBOOHR_SUBDOMAIN` |
| Google Sheets scope in `SCOPES` | Remove `spreadsheets` scope (keep Drive for document storage if needed) |

---

## Recommended Build Order

| Phase | Agents | Integrations |
|---|---|---|
| **1 — Foundation** | Controller, Approval Gateway | QBO API, Google Chat app, Chase→QBO bank feed (manual setup) |
| **2 — Money In** | AR, Progress Billing | QBO invoicing, job system |
| **3 — Money Out** | AP, Sub Compliance | Bill.com API, Bill.com↔QBO sync |
| **4 — Jobs** | Job Costing, Change Order | QBO Projects/Classes, job system |
| **5 — People** | Commission, Payroll | BambooHR API, BambooHR→QBO JE sync |
| **6 — Intelligence** | Profitability, Cash Flow | QBO reporting, Google Chat dashboards |
| **7 — Orchestration** | Finance Orchestrator | Wire all agents, webhooks, event bus |

---

## Agent Count Summary

| # | Agent | Tier | Primary integration |
|---|---|---|---|
| 1 | Finance Orchestrator | Core | All systems |
| 2 | AR Agent | Core | QBO |
| 3 | AP Agent | Core | Bill.com → QBO |
| 4 | Commission Agent | Core | QBO + job system |
| 5 | Payroll Agent | Core | BambooHR → QBO |
| 6 | Job Costing Agent | Core | QBO Projects/Classes |
| 7 | Profitability Agent | Core | QBO (read-only) |
| 8 | Controller Agent | Core | QBO (bank register) |
| 9 | Progress Billing Agent | Home services | QBO + job system |
| 10 | Change Order Agent | Home services | QBO + job system |
| 11 | Subcontractor Compliance Agent | Home services | Bill.com + document store |
| 12 | Cash Flow Agent | Home services | QBO (read-only) |
| 13 | Approval Gateway Agent | Cross-cutting | Google Chat + Gmail + approval queue DB |

**Total: 13 agents.**

---

## Open Questions for Implementation

1. **Job system of record** — What do you use today? (Jobber, ServiceTitan, Buildertrend, HubSpot, spreadsheets?) Job Costing and Progress Billing agents need this.
2. **Commission rules** — Flat % of sale, % of gross margin, or tiered by job size? Paid at contract signing, milestone, or job completion?
3. **Approval thresholds** — Dollar amounts that trigger different approval chains (e.g., <$500 auto-approve, $500–$5K manager, >$5K owner).
4. **Google Chat space for approvals** — Which Chat space should receive approval cards? (e.g., `#finance-approvals`) DMs to specific approvers can also be used for high-value items.
5. **Prevailing wage / certified payroll** — Do you do any government or commercial work requiring certified payroll reports?
