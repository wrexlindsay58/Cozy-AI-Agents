from src.tools.google_auth import get_tasks_service
import logging

logger = logging.getLogger(__name__)

def create_task(title, notes=None, due=None):
    try:
        service = get_tasks_service()
        task = {
            'title': title,
            'notes': notes,
            'due': due
        }
        result = service.tasks().insert(tasklist='@default', body=task).execute()
        return result
    except Exception as e:
        logger.error(f"Error creating task: {e}")
        return None
