import json
import logging
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage
from src.config import GEMINI_API_KEY
import re

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_model(model_name="gemini-1.5-flash"):
    return ChatGoogleGenerativeAI(model=model_name, google_api_key=GEMINI_API_KEY)

def extract_json(text):
    try:
        # Find JSON block using regex
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            return json.loads(match.group())
        return json.loads(text)
    except Exception as e:
        logger.error(f"Failed to parse JSON from text: {text}. Error: {e}")
        return {}

class Agents:
    def __init__(self):
        self.triage_model = get_model("gemini-1.5-flash")
        self.pro_model = get_model("gemini-1.5-pro")

    def triage_email(self, email_content):
        prompt = f"""
        Analyze the following email and classify it into one of these categories:
        SPAM, FYI, BILL, INVOICE, VENDOR_DOC, ACTION_REQUIRED, SCHEDULING.

        Financial categories:
        - BILL: vendor bill or invoice we need to pay
        - INVOICE: customer invoice or payment we are receiving
        - VENDOR_DOC: receipt, statement, or financial document from a vendor

        Return a JSON object with:
        {{
            "category": "CATEGORY",
            "reason": "Brief explanation",
            "task_title": "Title for a task if applicable",
            "is_scheduling": boolean,
            "is_confirmation": boolean
        }}

        Email:
        {email_content}
        """
        try:
            response = self.triage_model.invoke([HumanMessage(content=prompt)])
            return extract_json(response.content)
        except Exception as e:
            logger.error(f"Error in triage_email: {e}")
            return {"category": "FYI", "reason": "Error in processing"}

    def extract_expense_details(self, email_content):
        """Deprecated — use AP Agent via Bill.com instead."""
        logger.warning("extract_expense_details is deprecated. Use /finance/approvals endpoint.")
        return {"vendor": "Unknown", "amount": 0, "date": "1970-01-01", "tax": 0, "currency": "USD"}

    def draft_reply(self, email_content, context=""):
        prompt = f"""
        Draft a professional reply to the following email.
        Use the provided context if available to make the reply more accurate.

        CRITICAL: Do not send the email. This is only a draft.

        Context: {context}

        Email:
        {email_content}

        Draft:
        """
        try:
            response = self.pro_model.invoke([HumanMessage(content=prompt)])
            return response.content
        except Exception as e:
            logger.error(f"Error in draft_reply: {e}")
            return "I will get back to you soon."

    def propose_slots(self, availability, email_content):
        prompt = f"""
        Based on the following calendar availability and the email request,
        suggest TWO open time slots for a meeting.

        Availability: {availability}
        Email: {email_content}

        Return the suggested slots in a friendly draft reply.
        """
        try:
            response = self.pro_model.invoke([HumanMessage(content=prompt)])
            return response.content
        except Exception as e:
            logger.error(f"Error in propose_slots: {e}")
            return "I am checking my calendar and will suggest some times soon."

    def parse_confirmation(self, email_content):
        prompt = f"""
        The following email might be a confirmation of a previously suggested meeting time.
        Extract the confirmed meeting details:
        Return a JSON object with:
        {{
            "is_confirmed": boolean,
            "summary": "Meeting title",
            "start_time": "ISO format datetime",
            "end_time": "ISO format datetime",
            "attendees": ["email@example.com"]
        }}

        Email:
        {email_content}
        """
        try:
            response = self.pro_model.invoke([HumanMessage(content=prompt)])
            return extract_json(response.content)
        except Exception as e:
            logger.error(f"Error in parse_confirmation: {e}")
            return {"is_confirmed": False}
