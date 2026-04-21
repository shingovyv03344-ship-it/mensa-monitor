"""
MENSA入会試験 自動申込スクリプト（Tier 3）
- config.json の個人情報をフォームに自動入力
- CAPTCHAのみ手動入力が必要
- 使い方: python register.py <試験ID>
  例: python register.py 715
"""

import asyncio
import json
import sys
from pathlib import Path
from playwright.async_api import async_playwright

CONFIG_FILE = "config.json"
BASE_URL = "https://mensa.jp"

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


def load_config() -> dict:
    config_path = Path(CONFIG_FILE)
    if not config_path.exists():
        print(f"エラー: {CONFIG_FILE} が見つかりません。")
        print(f"config.json.example をコピーして {CONFIG_FILE} を作成してください。")
        sys.exit(1)
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


async def register(exam_id: str) -> None:
    config = load_config()

    # 都道府県を英語に変換（日本語で入力されていた場合）
    pref = config["pref"]
    if pref in PREF_MAP:
        pref = PREF_MAP[pref]

    photo_path = Path(config["photo_path"])
    if not photo_path.exists():
        print(f"エラー: 顔写真ファイルが見つかりません: {config['photo_path']}")
        sys.exit(1)

    print(f"試験ID {exam_id} の申込を開始します...")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=100)
        page = await browser.new_page()

        # Step 1: 注意事項ページ
        notice_url = f"{BASE_URL}/exam/index/notice/id/{exam_id}/"
        print(f"注意事項ページを開きます: {notice_url}")
        await page.goto(notice_url)
        await page.wait_for_load_state("networkidle")

        # 注意事項のチェックボックスにチェック
        await page.check("input[name='notice_move']")
        await page.wait_for_timeout(500)

        # 「申込画面に進む」をクリック
        await page.click("a[href*='detail']")
        await page.wait_for_load_state("networkidle")

        # Step 2: 申込フォームに入力
        print("フォームに個人情報を入力中...")

        await page.fill("input[name='name1']", config["name1"])
        await page.fill("input[name='name2']", config["name2"])
        await page.fill("input[name='nameEn1']", config["nameEn1"])
        await page.fill("input[name='nameEn2']", config["nameEn2"])
        await page.fill("input[name='zip']", config["zip"])
        await page.select_option("select[name='pref']", pref)
        await page.fill("input[name='address']", config["address"])
        await page.select_option("select[name='birthY']", config["birthY"])
        await page.select_option("select[name='birthM']", config["birthM"])
        await page.select_option("select[name='birthD']", config["birthD"])
        await page.fill("input[name='tel']", config["tel"])
        if config.get("mobileTel"):
            await page.fill("input[name='mobileTel']", config["mobileTel"])
        await page.fill("input[name='mail']", config["mail"])
        await page.fill("input[name='mail2']", config["mail"])
        if config.get("mobileMail"):
            await page.fill("input[name='mobileMail']", config["mobileMail"])
        await page.select_option("select[name='enquete']", config.get("enquete", "上記以外"))
        await page.select_option("select[name='testCount']", str(config.get("testCount", "1")))
        if config.get("prevTest"):
            await page.fill("input[name='prevTest']", config["prevTest"])

        # 顔写真アップロード
        await page.set_input_files("input[name='attach']", str(photo_path.resolve()))

        # 同意チェックボックス
        await page.check("input[name='accept']")

        if config.get("remark"):
            await page.fill("textarea[name='remark']", config["remark"])

        # CAPTCHAフィールドにフォーカス
        await page.focus("input[name='digit']")

        print("\n" + "="*50)
        print("【手動操作が必要です】")
        print("ブラウザでCAPTCHA（画像の数字）を入力し、")
        print("送信ボタンを押してください。")
        print("="*50)

        # 確認ページへの遷移を待つ（最大10分）
        try:
            await page.wait_for_url("**/confirm/**", timeout=600000)
            print("\n申込が送信されました！確認メールをご確認ください。")
        except Exception:
            print("\nタイムアウトまたはエラーが発生しました。ブラウザを確認してください。")

        # ブラウザを自動で閉じない（確認のため）
        input("\nEnterキーを押すとブラウザを閉じます...")
        await browser.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("使い方: python register.py <試験ID>")
        print("例: python register.py 715")
        print("\n試験IDはLINE通知のURLから確認できます。")
        print("例: https://mensa.jp/exam/index/notice/id/715/ → ID は 715")
        exam_id = input("\n試験IDを入力してください: ").strip()
    else:
        exam_id = sys.argv[1]

    asyncio.run(register(exam_id))
