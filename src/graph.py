from typing import TypedDict, List, Optional
from langgraph.graph import StateGraph, END
from src.email_agents import Agents
from src.tools.gmail_tools import create_draft, move_to_folder
from src.tools.tasks_tools import create_task
from src.tools.calendar_tools import get_calendar_availability, create_calendar_event
from src.tools.rag import query_vector_store

class AgentState(TypedDict):
    email: dict
    triage: dict
    draft: str
    calendar_slots: str
    context: str
    confirmation: dict

agents = None

def _get_agents():
    global agents
    if agents is None:
        agents = Agents()
    return agents

def triage_node(state: AgentState):
    email = state['email']
    triage = _get_agents().triage_email(f"Subject: {email['subject']}\nBody: {email['body']}")
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

def finance_node(state: AgentState):
    """Route financial emails to the Approval Gateway for review."""
    from src.agents.approval_gateway_agent import ApprovalGatewayAgent
    email = state['email']
    triage = state['triage']
    gateway = ApprovalGatewayAgent()

    category = triage.get('category', 'BILL')
    gateway.submit(
        approval_type=category.lower(),
        title=f"{email['subject']} — from {email['sender']}",
        description=email['body'][:500],
        agent_name="finance_orchestrator",
    )
    return {}

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
    draft = _get_agents().draft_reply(email['body'], context)
    create_draft(email['threadId'], email['sender'], f"Re: {email['subject']}", draft)
    return {"draft": draft}

def scheduling_node(state: AgentState):
    email = state['email']
    triage = state['triage']

    if triage.get('is_confirmation'):
        conf = _get_agents().parse_confirmation(email['body'])
        if conf.get('is_confirmed'):
            create_calendar_event(
                conf['summary'],
                conf['start_time'],
                conf['end_time'],
                attendees=conf.get('attendees', [email['sender']])
            )
            return {"confirmation": conf}

    availability = get_calendar_availability()
    slots_draft = _get_agents().propose_slots(availability, email['body'])
    create_draft(email['threadId'], email['sender'], f"Re: {email['subject']}", slots_draft)
    return {"calendar_slots": slots_draft}

def router(state: AgentState):
    triage = state.get('triage', {})
    category = triage.get('category')
    if category == 'SPAM':
        return 'spam'
    elif category in ('BILL', 'INVOICE', 'VENDOR_DOC', 'RECEIPT'):
        return 'finance'
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
workflow.add_node("finance", finance_node)
workflow.add_node("rag", rag_node)
workflow.add_node("draft", draft_node)
workflow.add_node("scheduling", scheduling_node)

workflow.set_entry_point("triage")

workflow.add_conditional_edges(
    "triage",
    router,
    {
        "spam": "spam",
        "finance": "finance",
        "scheduling": "scheduling",
        "rag": "rag",
        "end": END
    }
)

workflow.add_edge("rag", "draft")
workflow.add_edge("draft", "task")
workflow.add_edge("finance", "task")
workflow.add_edge("scheduling", "task")
workflow.add_edge("task", END)
workflow.add_edge("spam", END)

app = workflow.compile()
