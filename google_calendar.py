"""
Google Calendar 空き確認ヘルパー
"""

import os
import re
from datetime import datetime

import pytz
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
CREDENTIALS_FILE = "credentials.json"
TOKEN_FILE = "token.json"
JST = pytz.timezone("Asia/Tokyo")


def get_calendar_service():
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
    return build("calendar", "v3", credentials=creds)


def check_availability(date_text: str) -> tuple[bool, list[str]]:
    """
    試験日時テキストからGoogleカレンダーの空きを確認する。

    Args:
        date_text: state.jsonの "date" フィールド
                   例: "日時 ： 2026/06/13(土)　11:00~12:00 ..."
    Returns:
        (is_free, conflicting_event_titles)
    """
    m = re.search(r"(\d{4}/\d{2}/\d{2}).*?(\d{2}:\d{2})~(\d{2}:\d{2})", date_text)
    if not m:
        return True, []

    date_str, start_str, end_str = m.group(1), m.group(2), m.group(3)
    start = JST.localize(datetime.strptime(f"{date_str} {start_str}", "%Y/%m/%d %H:%M"))
    end   = JST.localize(datetime.strptime(f"{date_str} {end_str}",   "%Y/%m/%d %H:%M"))

    service = get_calendar_service()
    result = service.events().list(
        calendarId="primary",
        timeMin=start.isoformat(),
        timeMax=end.isoformat(),
        singleEvents=True,
        orderBy="startTime",
    ).execute()

    events = result.get("items", [])
    titles = [e.get("summary", "（タイトルなし）") for e in events]
    return len(events) == 0, titles
