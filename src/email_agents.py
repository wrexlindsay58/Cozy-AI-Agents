import json
import logging
from langchain_core.messages import HumanMessage
from src.llm import invoke_with_fallback
import re

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def extract_json(text):
    try:
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            return json.loads(match.group())
        return json.loads(text)
    except Exception as e:
        logger.error(f"Failed to parse JSON from text: {text}. Error: {e}")
        return {}


class Agents:
    def triage_email(self, email_content):
        prompt = f"""
        Analyze the following email and classify it into one of these categories:
        SPAM, FYI, BILL, INVOICE, VENDOR_DOC, CHANGE_ORDER, ACTION_REQUIRED, SCHEDULING.

        Financial categories:
        - BILL: vendor bill or invoice we need to pay
        - INVOICE: customer invoice or payment we are receiving
        - VENDOR_DOC: receipt, statement, or financial document from a vendor
        - CHANGE_ORDER: scope change, extra work request, or change order from customer/field crew

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
            response = invoke_with_fallback([HumanMessage(content=prompt)], tier="fast")
            return extract_json(response.content)
        except Exception as e:
            logger.error(f"Error in triage_email: {e}")
            return {"category": "FYI", "reason": "Error in processing"}

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
            response = invoke_with_fallback([HumanMessage(content=prompt)], tier="pro")
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
            response = invoke_with_fallback([HumanMessage(content=prompt)], tier="pro")
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
            response = invoke_with_fallback([HumanMessage(content=prompt)], tier="pro")
            return extract_json(response.content)
        except Exception as e:
            logger.error(f"Error in parse_confirmation: {e}")
            return {"is_confirmed": False}
