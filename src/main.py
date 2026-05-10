import time
from fastapi import FastAPI, BackgroundTasks
from pydantic import BaseModel
from src.db.sqlite import init_db, is_email_processed, mark_email_processed
from src.tools.gmail_tools import list_unread_emails, get_email_details
from src.graph import app as workflow_app
from src.tools.rag import add_to_vector_store
import uuid
import logging

logger = logging.getLogger(__name__)

app = FastAPI()

class VoiceNote(BaseModel):
    text: str

@app.on_event("startup")
def startup_event():
    init_db()

def process_email(email_details):
    if not is_email_processed(email_details['id']):
        logger.info(f"Processing email: {email_details['id']}")
        try:
            workflow_app.invoke({"email": email_details})
            mark_email_processed(email_details['id'])
        except Exception as e:
            logger.error(f"Error processing email {email_details['id']}: {e}")

@app.get("/sync")
def sync_emails(background_tasks: BackgroundTasks):
    emails = list_unread_emails()
    for email in emails:
        details = get_email_details(email['id'])
        if details:
            background_tasks.add_task(process_email, details)
    return {"status": "sync started", "emails_queued": len(emails)}

@app.post("/voice-note")
def receive_voice_note(note: VoiceNote, background_tasks: BackgroundTasks):
    # Treat voice note as an incoming "email" or task
    mock_email = {
        'id': f"voice-{uuid.uuid4()}",
        'subject': "Voice Note Ingestion",
        'sender': "Voice Assistant",
        'body': note.text,
        'attachments': [],
        'threadId': None
    }
    background_tasks.add_task(workflow_app.invoke, {"email": mock_email})
    return {"status": "voice note received and being processed"}

@app.post("/ingest-knowledge")
def ingest_knowledge(content: str, metadata: dict = {}):
    doc_id = str(uuid.uuid4())
    add_to_vector_store("personal_knowledge", [content], [metadata], [doc_id])
    return {"status": "knowledge ingested", "id": doc_id}

if __name__ == "__main__":
    import uvicorn
    # Initial sync
    init_db()
    uvicorn.run(app, host="0.0.0.0", port=8000)
