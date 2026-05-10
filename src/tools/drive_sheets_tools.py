from googleapiclient.http import MediaIoBaseUpload
import io
import logging
from src.tools.google_auth import get_drive_service, get_sheets_service
from src.config import RECEIPTS_SHEET_ID, RECEIPTS_FOLDER_ID

logger = logging.getLogger(__name__)

def upload_to_drive(filename, content, mimetype, folder_id=None):
    try:
        service = get_drive_service()
        file_metadata = {'name': filename}
        if folder_id:
            file_metadata['parents'] = [folder_id]

        fh = io.BytesIO(content)
        media = MediaIoBaseUpload(fh, mimetype=mimetype, resumable=True)
        file = service.files().create(body=file_metadata, media_body=media, fields='id').execute()
        return file.get('id')
    except Exception as e:
        logger.error(f"Error uploading to Drive: {e}")
        return None

def append_to_sheet(sheet_id, values):
    try:
        if not sheet_id:
            logger.warning("No sheet_id provided for append_to_sheet")
            return
        service = get_sheets_service()
        body = {'values': [values]}
        service.spreadsheets().values().append(
            spreadsheetId=sheet_id, range="Sheet1!A1",
            valueInputOption="USER_ENTERED", body=body
        ).execute()
    except Exception as e:
        logger.error(f"Error appending to Sheet: {e}")
