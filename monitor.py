"""
MENSA入会試験 監視スクリプト
- 新しい試験日程の追加を検知
- 満員だった枠に空きが出たことを検知
- LINEで即時通知
"""

import os
import json
import hashlib
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from urllib.parse import urljoin

BASE_URL = "https://mensa.jp"
EXAM_URL = f"{BASE_URL}/exam/"
STATE_FILE = "state.json"

# 通知対象の都道府県（関東のみ）
TARGET_PREFS = ["東京都", "神奈川県", "埼玉県", "千葉県", "茨城県", "栃木県", "群馬県"]


def fetch_page() -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
    }
    resp = requests.get(EXAM_URL, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.text


def parse_exams(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    exams = []

    for ul in soup.find_all("ul", class_="list"):
        li_pref = ul.find("li", class_="pref")
        li_date = ul.find("li", class_="date")
        li_link = ul.find("li", class_="link")
        if not all([li_pref, li_date, li_link]):
            continue

        pref_text = li_pref.get_text(separator=" ").strip()
        date_text = li_date.get_text(separator=" ").strip()

        img = li_link.find("img")
        link_tag = li_link.find("a")

        if link_tag and img and "entry_out" in img.get("src", ""):
            status = "available"
            href = link_tag.get("href", "")
            url = urljoin(BASE_URL + "/", href.lstrip("/"))
        elif img and "entry_quota" in img.get("src", ""):
            status = "full"
            url = ""
        else:
            status = "unknown"
            url = ""

        # IDはテキスト内容からハッシュ生成（URLのIDより安定）
        exam_id = hashlib.md5(f"{pref_text}|{date_text}".encode()).hexdigest()[:12]

        exams.append({
            "id": exam_id,
            "pref": pref_text,
            "date": date_text,
            "status": status,
            "url": url,
        })

    return exams


def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"exams": {}, "last_checked": None}


def save_state(state: dict) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def send_line_message(text: str) -> None:
    token = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
    user_id = os.environ["LINE_USER_ID"]

    resp = requests.post(
        "https://api.line.me/v2/bot/message/push",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json={
            "to": user_id,
            "messages": [{"type": "text", "text": text}],
        },
        timeout=30,
    )
    resp.raise_for_status()


def build_message(exam: dict, reason: str) -> str:
    if reason == "new_available":
        header = "【MENSA】新しい試験日程が公開されました！"
        body = (
            f"{exam['pref']}\n"
            f"{exam['date']}\n\n"
            f"今すぐ申し込む:\n{exam['url']}"
        )
    elif reason == "new_full":
        header = "【MENSA】新しい試験日程（満員）が追加されました"
        body = f"{exam['pref']}\n{exam['date']}"
    elif reason == "slot_opened":
        header = "【MENSA】キャンセルで空きが出ました！"
        body = (
            f"{exam['pref']}\n"
            f"{exam['date']}\n\n"
            f"今すぐ申し込む:\n{exam['url']}"
        )
    else:
        header = "【MENSA】試験日程の変更"
        body = f"{exam['pref']}\n{exam['date']}"

    return f"{header}\n\n{body}"


def main() -> None:
    print(f"[{datetime.utcnow().isoformat()}] Checking {EXAM_URL} ...")

    html = fetch_page()
    current_exams = parse_exams(html)
    print(f"  Found {len(current_exams)} exam slots.")

    state = load_state()
    prev_exams: dict = state.get("exams", {})

    notifications = []
    new_state_exams = {}

    for exam in current_exams:
        eid = exam["id"]
        new_state_exams[eid] = exam
        prev = prev_exams.get(eid)

        # 関東以外はスキップ
        if not any(pref in exam["pref"] for pref in TARGET_PREFS):
            continue

        if prev is None:
            # 新しい試験枠
            reason = "new_available" if exam["status"] == "available" else "new_full"
            notifications.append((exam, reason))
            print(f"  NEW ({reason}): {exam['pref']} {exam['date']}")
        elif prev["status"] == "full" and exam["status"] == "available":
            # 満員 → 空きあり
            notifications.append((exam, "slot_opened"))
            print(f"  SLOT OPENED: {exam['pref']} {exam['date']}")

    state["exams"] = new_state_exams
    state["last_checked"] = datetime.utcnow().isoformat()
    save_state(state)

    if not notifications:
        print("  No changes detected.")
        return

    for exam, reason in notifications:
        msg = build_message(exam, reason)
        send_line_message(msg)
        print(f"  Notified via LINE: [{reason}]")


if __name__ == "__main__":
    main()
