from typing import TypedDict, List, Optional
from langgraph.graph import StateGraph, END
from src.agents import Agents
from src.tools.gmail_tools import create_draft, move_to_folder, download_attachment
from src.tools.tasks_tools import create_task
from src.tools.drive_sheets_tools import upload_to_drive, append_to_sheet
from src.tools.calendar_tools import get_calendar_availability, create_calendar_event
from src.tools.rag import query_vector_store
from src.config import RECEIPTS_SHEET_ID, RECEIPTS_FOLDER_ID

class AgentState(TypedDict):
    email: dict
    triage: dict
    draft: str
    expense_details: dict
    calendar_slots: str
    context: str
    confirmation: dict

agents = Agents()

def triage_node(state: AgentState):
    email = state['email']
    triage = agents.triage_email(f"Subject: {email['subject']}\nBody: {email['body']}")
    return {"triage": triage}

def task_node(state: AgentState):
    triage = state['triage']
    email = state['email']
    if triage.get('category') == 'ACTION_REQUIRED' or triage.get('task_title'):
        create_task(triage.get('task_title', email['subject']), notes=f"From: {email['sender']}\nID: {email['id']}")
    return {}

def spam_node(state: AgentState):
    move_to_folder(state['email']['id'], "AI-Archived")
    return {}

def expense_node(state: AgentState):
    email = state['email']
    details = agents.extract_expense_details(f"Subject: {email['subject']}\nBody: {email['body']}")

    # Append to Sheet
    append_to_sheet(RECEIPTS_SHEET_ID, [details.get('date'), details.get('vendor'), details.get('amount'), details.get('tax'), details.get('currency')])

    # Upload attachments to Drive if they exist
    for att in email.get('attachments', []):
        if 'pdf' in att['mimeType'] or 'image' in att['mimeType']:
            content = download_attachment(email['id'], att['id'])
            if content:
                upload_to_drive(att['filename'], content, att['mimeType'], RECEIPTS_FOLDER_ID)

    return {"expense_details": details}

def rag_node(state: AgentState):
    email = state['email']
    try:
        results = query_vector_store("personal_knowledge", email['body'])
        context = "\n".join(results['documents'][0]) if results.get('documents') and results['documents'][0] else ""
    except Exception:
        context = ""
    return {"context": context}

def draft_node(state: AgentState):
    email = state['email']
    context = state.get('context', "")
    draft = agents.draft_reply(email['body'], context)
    create_draft(email['threadId'], email['sender'], f"Re: {email['subject']}", draft)
    return {"draft": draft}

def scheduling_node(state: AgentState):
    email = state['email']
    triage = state['triage']

    if triage.get('is_confirmation'):
        conf = agents.parse_confirmation(email['body'])
        if conf.get('is_confirmed'):
            create_calendar_event(
                conf['summary'],
                conf['start_time'],
                conf['end_time'],
                attendees=conf.get('attendees', [email['sender']])
            )
            return {"confirmation": conf}

    # Default to proposing slots
    availability = get_calendar_availability()
    slots_draft = agents.propose_slots(availability, email['body'])
    create_draft(email['threadId'], email['sender'], f"Re: {email['subject']}", slots_draft)
    return {"calendar_slots": slots_draft}

def router(state: AgentState):
    triage = state.get('triage', {})
    category = triage.get('category')
    if category == 'SPAM':
        return 'spam'
    elif category == 'RECEIPT':
        return 'expense'
    elif category == 'SCHEDULING' or triage.get('is_scheduling') or triage.get('is_confirmation'):
        return 'scheduling'
    elif category == 'ACTION_REQUIRED':
        return 'rag'
    else:
        return 'end'

workflow = StateGraph(AgentState)

workflow.add_node("triage", triage_node)
workflow.add_node("task", task_node)
workflow.add_node("spam", spam_node)
workflow.add_node("expense", expense_node)
workflow.add_node("rag", rag_node)
workflow.add_node("draft", draft_node)
workflow.add_node("scheduling", scheduling_node)

workflow.set_entry_point("triage")

workflow.add_conditional_edges(
    "triage",
    router,
    {
        "spam": "spam",
        "expense": "expense",
        "scheduling": "scheduling",
        "rag": "rag",
        "end": END
    }
)

workflow.add_edge("rag", "draft")
workflow.add_edge("draft", "task")
workflow.add_edge("expense", "task")
workflow.add_edge("scheduling", "task")
workflow.add_edge("task", END)
workflow.add_edge("spam", END)

app = workflow.compile()
