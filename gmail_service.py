import os, logging, json, re
from datetime import datetime

logger = logging.getLogger(__name__)

KEYWORDS = [
    'supply', 'ticket', 'hubble', 'request', 'urgent', 'help',
    'issue', 'support', 'order', 'delivery', 'complaint', 'refund',
    'broken', 'problem', 'assist', 'accommodation', 'error', 'bug'
]

def _get_gmail_service():
    import requests
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    creds = Credentials(
        token=None,
        refresh_token=os.environ.get('GMAIL_REFRESH_TOKEN'),
        client_id=os.environ.get('GMAIL_CLIENT_ID'),
        client_secret=os.environ.get('GMAIL_CLIENT_SECRET'),
        token_uri='https://oauth2.googleapis.com/token'
    )
    return build('gmail', 'v1', credentials=creds)

def _extract_body(payload):
    """Recursively extract plain text body from email payload."""
    import base64
    if payload.get('mimeType') == 'text/plain':
        data = payload.get('body', {}).get('data', '')
        if data:
            return base64.urlsafe_b64decode(data + '==').decode('utf-8', errors='ignore')
    for part in payload.get('parts', []):
        result = _extract_body(part)
        if result:
            return result
    return ''

def _matches_keywords(subject, body):
    text = (subject + ' ' + body).lower()
    return any(kw in text for kw in KEYWORDS)

def poll_gmail_and_create_tickets(ticket_service):
    """
    Poll Gmail for new unread emails matching keywords.
    Marks processed emails with label to avoid duplicates.
    Returns number of tickets created.
    """
    try:
        service = _get_gmail_service()
        created = 0

        # Search unread emails not yet processed by Hubble
        query = 'is:unread -label:hubble-processed'
        results = service.users().messages().list(
            userId='me', q=query, maxResults=20
        ).execute()

        messages = results.get('messages', [])
        if not messages:
            return 0

        # Ensure hubble-processed label exists
        label_id = _ensure_label(service, 'hubble-processed')

        for msg_ref in messages:
            msg_id = msg_ref['id']
            try:
                msg = service.users().messages().get(
                    userId='me', id=msg_id, format='full'
                ).execute()

                headers = {h['name'].lower(): h['value'] for h in msg['payload'].get('headers', [])}
                subject = headers.get('subject', '(no subject)')
                sender  = headers.get('from', 'unknown')
                body    = _extract_body(msg['payload'])
                date    = headers.get('date', '')

                if not _matches_keywords(subject, body):
                    # Mark as processed so we don't re-check it
                    _apply_label(service, msg_id, label_id)
                    continue

                # Clean sender display name
                name_match = re.match(r'^"?([^"<]+)"?\s*<?', sender)
                requester_name = name_match.group(1).strip() if name_match else sender

                # Create ticket
                description = f"[Email] From: {sender}\nSubject: {subject}\n\n{body[:1000]}"
                ticket_id = ticket_service.create_ticket(
                    message_text=description,
                    requester_id=sender,
                    requester_name=requester_name,
                    timestamp=date,
                    thread_ts=msg_id,
                    channel_id='EMAIL',
                    priority='Medium',
                    source='Email'
                )

                if ticket_id:
                    logger.info(f"✅ Created ticket #{ticket_id} from email: {subject}")
                    created += 1

                # Mark email as processed
                _apply_label(service, msg_id, label_id)

            except Exception as e:
                logger.error(f"Error processing email {msg_id}: {e}")

        return created

    except Exception as e:
        logger.error(f"Gmail poll error: {e}")
        return 0

def _ensure_label(service, name):
    """Get or create a Gmail label, return its ID."""
    labels = service.users().labels().list(userId='me').execute().get('labels', [])
    for l in labels:
        if l['name'] == name:
            return l['id']
    created = service.users().labels().create(userId='me', body={'name': name}).execute()
    return created['id']

def _apply_label(service, msg_id, label_id):
    """Apply label and mark as read."""
    service.users().messages().modify(
        userId='me', id=msg_id,
        body={'addLabelIds': [label_id], 'removeLabelIds': ['UNREAD']}
    ).execute()
