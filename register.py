"""
MENSA入会試験 自動申込スクリプト（Tier 3）

動作フロー:
  1. MENSAサイトから最新の関東空き枠を取得
  2. Googleカレンダーと照合して空き状況を表示
  3. 申込む日程を選択
  4. ブラウザを起動してフォームを自動入力
  5. CAPTCHAだけ手動入力して送信

使い方:
  python register.py          # 対話モード（推奨）
  python register.py <試験ID>  # 試験IDを直接指定
"""

import asyncio
import json
import os
import re
import sys
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

CONFIG_FILE = "config.json"
BASE_URL = "https://mensa.jp"
EXAM_URL = f"{BASE_URL}/exam/"

TARGET_PREFS = ["東京都", "神奈川県", "埼玉県", "千葉県", "茨城県", "栃木県", "群馬県"]

PREF_MAP = {
    "北海道": "HOKKAIDO", "青森県": "AOMORI", "岩手県": "IWATE",
    "宮城県": "MIYAGI", "秋田県": "AKITA", "山形県": "YAMAGATA",
    "福島県": "FUKUSHIMA", "茨城県": "IBARAKI", "栃木県": "TOCHIGI",
    "群馬県": "GUNMA", "埼玉県": "SAITAMA", "千葉県": "CHIBA",
    "東京都": "TOKYO", "神奈川県": "KANAGAWA", "新潟県": "NIGATA",
    "富山県": "TOYAMA", "石川県": "ISHIKAWA", "福井県": "FUKUI",
    "山梨県": "YAMANASHI", "長野県": "NAGANO", "岐阜県": "GIFU",
    "静岡県": "SHIZUOKA", "愛知県": "AICHI", "三重県": "MIE",
    "滋賀県": "SHIGA", "京都府": "KYOTO", "大阪府": "OSAKA",
    "兵庫県": "HYOGO", "奈良県": "NARA", "和歌山県": "WAKAYAMA",
    "鳥取県": "TOTTORI", "島根県": "SHIMANE", "岡山県": "OKAYAMA",
    "広島県": "HIROSHIMA", "山口県": "YAMAGUCHI", "徳島県": "TOKUSHIMA",
    "香川県": "KAGAWA", "愛媛県": "EHIME", "高知県": "KOCHI",
    "福岡県": "FUKUOKA", "佐賀県": "SAGA", "長崎県": "NAGASAKI",
    "熊本県": "KUMAMOTO", "大分県": "OITA", "宮崎県": "MIYAZAKI",
    "鹿児島県": "KAGOSHIMA", "沖縄県": "OKINAWA",
}


# ─── ユーティリティ ────────────────────────────────────────────

def load_config() -> dict:
    if not Path(CONFIG_FILE).exists():
        print(f"エラー: {CONFIG_FILE} が見つかりません。")
        sys.exit(1)
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def fetch_kanto_available_slots() -> list[dict]:
    """MENSAサイトから最新の関東空き枠を直接取得する。"""
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    resp = requests.get(EXAM_URL, headers=headers, timeout=30)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    slots = []

    for ul in soup.find_all("ul", class_="list"):
        li_pref = ul.find("li", class_="pref")
        li_date = ul.find("li", class_="date")
        li_link = ul.find("li", class_="link")
        if not all([li_pref, li_date, li_link]):
            continue

        pref_text = li_pref.get_text(separator=" ").strip()
        date_text = li_date.get_text(separator=" ").strip()

        # 関東以外はスキップ
        if not any(pref in pref_text for pref in TARGET_PREFS):
            continue

        img = li_link.find("img")
        link_tag = li_link.find("a")

        if link_tag and img and "entry_out" in img.get("src", ""):
            href = link_tag.get("href", "")
            url = f"{BASE_URL}/{href.lstrip('/')}"
            exam_id = extract_exam_id(url)
            slots.append({
                "pref": pref_text,
                "date": date_text,
                "url":  url,
                "id":   exam_id,
            })

    return slots


def extract_exam_id(url: str) -> str:
    parts = [p for p in url.rstrip("/").split("/") if p]
    try:
        return parts[parts.index("id") + 1]
    except (ValueError, IndexError):
        return ""


def parse_date_display(date_text: str) -> str:
    """'日時 ： 2026/06/13(土)　11:00~12:00 ...' → '2026/06/13(土) 11:00~12:00'"""
    m = re.search(r"(\d{4}/\d{2}/\d{2}\([^)]+\))[　\s]+(\d{2}:\d{2}~\d{2}:\d{2})", date_text)
    if m:
        return f"{m.group(1)} {m.group(2)}"
    return date_text.split("\n")[0].replace("日時 ： ", "").strip()


def parse_location(date_text: str) -> str:
    m = re.search(r"場所 ： (.+?)(?:\n|　|$)", date_text)
    return m.group(1).strip() if m else ""


def check_calendar(date_text: str) -> str:
    """Googleカレンダーで空きを確認してステータス文字列を返す。"""
    try:
        from google_calendar import check_availability
        is_free, conflicts = check_availability(date_text)
        if is_free:
            return "○ 空き"
        titles = "、".join(conflicts[:2])
        return f"× 予定あり（{titles}）"
    except ImportError:
        return "（カレンダー未連携）"
    except Exception as e:
        return f"（カレンダー確認エラー: {e}）"


def select_slot(slots: list[dict]) -> dict | None:
    """空き枠の一覧を表示してユーザーに選択させる。"""
    has_calendar = (
        Path("credentials.json").exists() or Path("token.json").exists()
    )

    print("\n" + "=" * 60)
    print("  関東の申込可能な試験日程")
    print("=" * 60)

    for i, slot in enumerate(slots, 1):
        date_disp = parse_date_display(slot["date"])
        location  = parse_location(slot["date"])
        cal_status = check_calendar(slot["date"]) if has_calendar else "（カレンダー未連携）"
        print(f"\n  [{i}] {date_disp}")
        print(f"       場所    : {location}")
        print(f"       カレンダー: {cal_status}")

    print("\n  [0] キャンセル")
    print("=" * 60)

    while True:
        choice = input("\n申込する番号を入力してください: ").strip()
        if choice == "0":
            return None
        if choice.isdigit() and 1 <= int(choice) <= len(slots):
            return slots[int(choice) - 1]
        print("無効な番号です。もう一度入力してください。")


# ─── Playwright フォーム入力 ──────────────────────────────────

async def fill_and_register(exam_id: str, config: dict) -> None:
    pref = config["pref"]
    if pref in PREF_MAP:
        pref = PREF_MAP[pref]

    photo_path = Path(config["photo_path"])
    if not photo_path.exists():
        print(f"エラー: 顔写真ファイルが見つかりません: {config['photo_path']}")
        sys.exit(1)

    print(f"\n試験ID {exam_id} の申込フォームを開きます...")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=80)
        page = await browser.new_page()

        # 注意事項ページ
        await page.goto(f"{BASE_URL}/exam/index/notice/id/{exam_id}/")
        await page.wait_for_load_state("networkidle")
        await page.check("input[name='notice_move']")
        await page.wait_for_timeout(500)
        await page.click("a[href*='detail']")
        await page.wait_for_load_state("networkidle")

        # フォーム入力
        print("フォームに個人情報を入力中...")
        await page.fill("input[name='name1']",   config["name1"])
        await page.fill("input[name='name2']",   config["name2"])
        await page.fill("input[name='nameEn1']", config["nameEn1"])
        await page.fill("input[name='nameEn2']", config["nameEn2"])
        await page.fill("input[name='zip']",     config["zip"])
        await page.select_option("select[name='pref']",   pref)
        await page.fill("input[name='address']", config["address"])
        await page.select_option("select[name='birthY']", config["birthY"])
        await page.select_option("select[name='birthM']", config["birthM"])
        await page.select_option("select[name='birthD']", config["birthD"])
        await page.fill("input[name='tel']",     config["tel"])
        if config.get("mobileTel"):
            await page.fill("input[name='mobileTel']", config["mobileTel"])
        await page.fill("input[name='mail']",  config["mail"])
        await page.fill("input[name='mail2']", config["mail"])
        if config.get("mobileMail"):
            await page.fill("input[name='mobileMail']", config["mobileMail"])
        await page.select_option("select[name='enquete']",   config.get("enquete",   "上記以外"))
        await page.select_option("select[name='testCount']", str(config.get("testCount", "1")))
        if config.get("prevTest"):
            await page.fill("input[name='prevTest']", config["prevTest"])

        await page.set_input_files("input[name='attach']", str(photo_path.resolve()))
        await page.check("input[name='accept']")

        if config.get("remark"):
            await page.fill("textarea[name='remark']", config["remark"])

        await page.focus("input[name='digit']")

        print("\n" + "=" * 50)
        print("【手動操作】CAPTCHAの数字を入力して送信ボタンを押してください。")
        print("=" * 50)

        try:
            await page.wait_for_url("**/confirm/**", timeout=600000)
            print("\n✓ 申込が送信されました！確認メールをご確認ください。")
        except Exception:
            print("\nタイムアウトまたはエラーが発生しました。ブラウザを確認してください。")

        input("\nEnterキーを押すとブラウザを閉じます...")
        await browser.close()


# ─── メイン ───────────────────────────────────────────────────

def main() -> None:
    config = load_config()

    # 試験IDが引数で渡された場合はそのまま使用
    if len(sys.argv) >= 2:
        exam_id = sys.argv[1]
        print(f"試験ID {exam_id} を直接指定して申込を開始します。")
        asyncio.run(fill_and_register(exam_id, config))
        return

    # 対話モード: サイトから最新の関東空き枠を取得
    print("MENSAサイトから最新の関東空き枠を確認中...")
    slots = fetch_kanto_available_slots()

    if not slots:
        print("現在、申込可能な関東の試験日程はありません。")
        return

    selected = select_slot(slots)
    if selected is None:
        print("キャンセルしました。")
        return

    print(f"\n選択: {parse_date_display(selected['date'])} {parse_location(selected['date'])}")
    asyncio.run(fill_and_register(selected["id"], config))


if __name__ == "__main__":
    main()
