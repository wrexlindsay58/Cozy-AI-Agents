import datetime
import logging
from src.tools.google_auth import get_calendar_service

logger = logging.getLogger(__name__)

def get_calendar_availability(time_min=None, time_max=None):
    try:
        service = get_calendar_service()
        if not time_min:
            time_min = datetime.datetime.utcnow().isoformat() + 'Z'
        if not time_max:
            time_max = (datetime.datetime.utcnow() + datetime.timedelta(days=7)).isoformat() + 'Z'

        events_result = service.events().list(
            calendarId='primary', timeMin=time_min, timeMax=time_max,
            singleEvents=True, orderBy='startTime'
        ).execute()
        return events_result.get('items', [])
    except Exception as e:
        logger.error(f"Error getting calendar availability: {e}")
        return []

def create_calendar_event(summary, start_time, end_time, description="", attendees=[]):
    try:
        service = get_calendar_service()
        event = {
            'summary': summary,
            'description': description,
            'start': {'dateTime': start_time},
            'end': {'dateTime': end_time},
            'attendees': [{'email': email} for email in attendees],
            'status': 'tentative' # Save as unconfirmed/draft-like
        }
        event = service.events().insert(calendarId='primary', body=event).execute()
        return event
    except Exception as e:
        logger.error(f"Error creating calendar event: {e}")
        return None
