#!/usr/bin/env python3
"""Facebook / Instagram 金鑰取得小幫手。

這是整個設定流程裡最容易卡住的一段，所以寫成工具自動幫你做完。

你只需要提供一個「短期使用者權杖」（從 Graph API Explorer 複製，有效期只有 1~2 小時），
這支程式會自動幫你做完剩下四件事：
    1. 把短期權杖換成長期權杖（約 60 天）
    2. 列出你管理的所有粉絲專頁，並取得每個粉專的「粉專權杖」
    3. 找出每個粉專連結的 Instagram 商業帳號 ID
    4. 印出你該貼進 .env 的內容

執行方式（在專案資料夾底下）：
    python tools/meta_setup.py

詳細的前置步驟請看 docs/04-申請各平台API.md。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import requests  # noqa: E402

GRAPH = "https://graph.facebook.com/v21.0"


def ask(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        print("\n已取消。")
        sys.exit(1)


def die(message: str) -> None:
    print(f"\n❌ {message}\n")
    sys.exit(1)


def explain_error(payload: dict) -> str:
    error = payload.get("error") or {}
    code = error.get("code")
    message = error.get("message", str(payload)[:300])
    hints = {
        190: "權杖無效或已過期。Graph API Explorer 的權杖只有 1~2 小時，請重新產生一個再貼。",
        100: "參數有誤，通常是 App ID 或 App Secret 打錯了。",
        200: "權限不足。請在 Graph API Explorer 重新勾選所有需要的權限再產生權杖。",
    }
    hint = hints.get(code, "")
    return f"{message}" + (f"\n   建議：{hint}" if hint else "")


def main() -> int:
    print()
    print("=" * 60)
    print("  Facebook / Instagram 金鑰取得小幫手")
    print("=" * 60)
    print()
    print("開始之前，你需要先完成 docs/04-申請各平台API.md 的「步驟 A」，")
    print("也就是建立 Meta 應用程式、並在 Graph API Explorer 產生一個使用者權杖。")
    print()

    app_id = ask("1. 請貼上你的 App ID（一串數字）：")
    app_secret = ask("2. 請貼上你的 App Secret：")
    short_token = ask("3. 請貼上 Graph API Explorer 產生的使用者權杖：")

    if not (app_id and app_secret and short_token):
        die("三個值都要填才能繼續。")

    # --- 1. 換成長期權杖 ---
    print("\n正在把短期權杖換成長期權杖…")
    try:
        resp = requests.get(f"{GRAPH}/oauth/access_token", params={
            "grant_type": "fb_exchange_token",
            "client_id": app_id,
            "client_secret": app_secret,
            "fb_exchange_token": short_token,
        }, timeout=60)
    except requests.RequestException as exc:
        die(f"連線 Facebook 失敗：{exc}")

    data = resp.json()
    long_token = data.get("access_token")
    if not long_token:
        die(f"換發長期權杖失敗：\n   {explain_error(data)}")
    print("✅ 長期使用者權杖取得成功（約 60 天有效）")

    # --- 2. 列出粉專與粉專權杖 ---
    print("\n正在查詢你管理的粉絲專頁…")
    try:
        resp = requests.get(f"{GRAPH}/me/accounts", params={
            "fields": "id,name,access_token",
            "access_token": long_token,
        }, timeout=60)
    except requests.RequestException as exc:
        die(f"連線 Facebook 失敗：{exc}")

    data = resp.json()
    pages = data.get("data")
    if pages is None:
        die(f"查詢粉絲專頁失敗：\n   {explain_error(data)}")
    if not pages:
        die("查不到任何粉絲專頁。\n   請確認：(1) 你有粉專且是管理員 "
            "(2) 產生權杖時有勾選 pages_show_list 權限")

    print(f"✅ 找到 {len(pages)} 個粉絲專頁\n")

    lines: list[str] = []
    for index, page in enumerate(pages, start=1):
        page_id = page.get("id", "")
        page_name = page.get("name", "未命名")
        page_token = page.get("access_token", "")

        print(f"--- 第 {index} 個粉專：{page_name} ---")

        # --- 3. 查這個粉專連結的 IG 商業帳號 ---
        ig_id = ""
        try:
            ig_resp = requests.get(f"{GRAPH}/{page_id}", params={
                "fields": "instagram_business_account",
                "access_token": page_token,
            }, timeout=60)
            ig_account = (ig_resp.json().get("instagram_business_account") or {})
            ig_id = ig_account.get("id", "")
        except requests.RequestException:
            pass

        if ig_id:
            print(f"    已連結 Instagram 商業帳號（ID {ig_id}）")
        else:
            print("    沒有連結 Instagram 商業帳號")
            print("    （如果你想自動發 IG，請先到 IG App 把帳號切成商業帳號並連結這個粉專）")

        suffix = "" if index == 1 else f"_{index}"
        lines.append(f"# --- 粉專：{page_name} ---")
        lines.append(f"FB_PAGE_ID{suffix}={page_id}")
        lines.append(f"FB_PAGE_ACCESS_TOKEN{suffix}={page_token}")
        if ig_id:
            lines.append(f"IG_USER_ID{suffix}={ig_id}")
            lines.append(f"IG_ACCESS_TOKEN{suffix}={page_token}")
        lines.append("")
        print()

    # --- 4. 印出要貼進 .env 的內容 ---
    print("=" * 60)
    print("  請把下面這段整個複製，貼到專案根目錄的 .env 檔案裡")
    print("  （取代掉原本 FB_ / IG_ 開頭的那幾行）")
    print("=" * 60)
    print()
    for line in lines:
        print(line)
    print("=" * 60)
    print()
    print("貼好之後，記得：")
    print("  1. 在 config.yaml 把 publish.facebook.enabled 改成 true")
    print("  2. 執行 python run.py doctor 確認每一項都打勾")
    print()
    print("⚠️  這些權杖等同你的帳號密碼，不要傳給任何人、不要上傳到網路。")
    print("⚠️  長期權杖約 60 天會過期，到時候再執行一次這支程式重新取得即可。")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
