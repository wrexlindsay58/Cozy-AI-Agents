import base64
import logging
from email.mime.text import MIMEText
from src.tools.google_auth import get_gmail_service

logger = logging.getLogger(__name__)

def list_unread_emails():
    try:
        service = get_gmail_service()
        results = service.users().messages().list(userId='me', q='is:unread').execute()
        messages = results.get('messages', [])
        return messages
    except Exception as e:
        logger.error(f"Error listing unread emails: {e}")
        return []

def get_body_from_payload(payload):
    """Recursively extract the plain text body from the Gmail payload."""
    if 'body' in payload and payload['body'].get('data'):
        return base64.urlsafe_b64decode(payload['body']['data']).decode('utf-8')

    if 'parts' in payload:
        for part in payload['parts']:
            if part['mimeType'] == 'text/plain':
                if 'data' in part['body']:
                    return base64.urlsafe_b64decode(part['body']['data']).decode('utf-8')
            elif part['mimeType'] == 'multipart/alternative' or part['mimeType'] == 'multipart/mixed':
                body = get_body_from_payload(part)
                if body:
                    return body
    return ""

def get_email_details(msg_id):
    try:
        service = get_gmail_service()
        message = service.users().messages().get(userId='me', id=msg_id, format='full').execute()
        payload = message.get('payload', {})
        headers = payload.get('headers', [])

        subject = next((h['value'] for h in headers if h['name'].lower() == 'subject'), 'No Subject')
        sender = next((h['value'] for h in headers if h['name'].lower() == 'from'), 'Unknown Sender')

        body = get_body_from_payload(payload)

        attachments = []
        def extract_attachments(p):
            if 'parts' in p:
                for part in p['parts']:
                    if part.get('filename'):
                        attachments.append({
                            'id': part['body'].get('attachmentId'),
                            'filename': part['filename'],
                            'mimeType': part['mimeType']
                        })
                    extract_attachments(part)

        extract_attachments(payload)

        return {
            'id': msg_id,
            'subject': subject,
            'sender': sender,
            'body': body,
            'attachments': attachments,
            'threadId': message.get('threadId')
        }
    except Exception as e:
        logger.error(f"Error getting email details for {msg_id}: {e}")
        return None

def create_draft(thread_id, recipient, subject, body):
    try:
        service = get_gmail_service()
        message = MIMEText(body)
        message['to'] = recipient
        message['subject'] = subject

        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
        create_message = {
            'message': {
                'threadId': thread_id,
                'raw': raw_message
            }
        }
        draft = service.users().drafts().create(userId='me', body=create_message).execute()
        return draft
    except Exception as e:
        logger.error(f"Error creating draft: {e}")
        return None

def move_to_folder(msg_id, label_name):
    try:
        service = get_gmail_service()

        # Get or create label
        labels = service.users().labels().list(userId='me').execute().get('labels', [])
        label_id = next((l['id'] for l in labels if l['name'] == label_name), None)

        if not label_id:
            label_body = {
                'name': label_name,
                'labelListVisibility': 'labelShow',
                'messageListVisibility': 'show'
            }
            label = service.users().labels().create(userId='me', body=label_body).execute()
            label_id = label['id']

        service.users().messages().modify(
            userId='me',
            id=msg_id,
            body={
                'addLabelIds': [label_id],
                'removeLabelIds': ['INBOX', 'UNREAD']
            }
        ).execute()
    except Exception as e:
        logger.error(f"Error moving email {msg_id} to {label_name}: {e}")

def download_attachment(msg_id, attachment_id):
    try:
        service = get_gmail_service()
        attachment = service.users().messages().attachments().get(
            userId='me', messageId=msg_id, id=attachment_id
        ).execute()
        data = base64.urlsafe_b64decode(attachment['data'])
        return data
    except Exception as e:
        logger.error(f"Error downloading attachment {attachment_id}: {e}")
        return None
