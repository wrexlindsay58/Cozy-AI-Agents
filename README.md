# Personal Executive Assistant

An autonomous multi-agent system built with Python, LangGraph, and Gemini to manage your digital life.

## Features

- **Triage Agent**: Classifies incoming emails and extracts action items to Google Tasks.
- **Bookkeeper Agent**: Automatically extracts expense data from receipts and appends them to Google Sheets and Drive.
- **Scheduling Agent**: Checks availability and drafts meeting replies.
- **Second Brain Agent**: Uses RAG (Retrieval-Augmented Generation) to provide context to email drafts.
- **Voice Note Ingestion**: FastAPI webhook to process transcribed text from voice notes.

## Architecture

- **LangGraph**: Orchestrates the multi-agent workflow.
- **Gemini API**: Flash for triage, Pro for complex reasoning.
- **Google Workspace APIs**: Gmail, Calendar, Tasks, Drive, Sheets.
- **SQLite**: Local state tracking to prevent duplicate processing.
- **ChromaDB**: Local vector store for RAG.

## Setup Instructions

### 1. Google Cloud Console Setup

1.  Go to the [Google Cloud Console](https://console.cloud.google.com/).
2.  Create a new project.
3.  Enable the following APIs:
    - Gmail API
    - Google Calendar API
    - Google Tasks API
    - Google Drive API
    - Google Sheets API
4.  Configure the **OAuth Consent Screen**:
    - Select "External".
    - Add the necessary scopes: `.../auth/gmail.modify`, `.../auth/calendar`, `.../auth/tasks`, `.../auth/drive.file`, `.../auth/spreadsheets`.
5.  Create **OAuth 2.0 Client IDs**:
    - Select "Desktop App".
    - Download the JSON file and rename it to `credentials.json` in the project root.

### 2. Environment Variables

Create a `.env` file in the root directory:

```env
GEMINI_API_KEY=your_gemini_api_key
RECEIPTS_SHEET_ID=your_google_sheet_id
RECEIPTS_FOLDER_ID=your_google_drive_folder_id
DB_PATH=assistant.db
CHROMA_DB_DIR=./chroma_db
```

### 3. Installation

```bash
pip install -r requirements.txt
```

### 4. Running the Assistant

Run the main FastAPI server:

```bash
python -m src.main
```

- **Sync Emails**: `GET /sync` will trigger the processing of unread emails.
- **Voice Note**: `POST /voice-note` with `{"text": "your transcribed voice note"}`.
- **Ingest Knowledge**: `POST /ingest-knowledge` with `{"content": "...", "metadata": {}}`.

## Critical Guardrails

- **Human-in-the-Loop**: The assistant only creates *drafts* in Gmail and *unconfirmed* events in Calendar. It never hits "Send" or confirms a meeting automatically.
- **Read-Only Financials**: No access to banking or payment gateways. Expense tracking is limited to scraping emails and receipts.
- **AI-Archived**: Spam is moved to an "AI-Archived" folder instead of being deleted.
