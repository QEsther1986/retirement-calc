#!/usr/bin/env python3
"""TikTok 授權小幫手。

TikTok 的授權流程對非技術使用者來說最麻煩：要開網頁授權、接住一個「授權碼」、
再拿那個碼去換權杖。這支程式把三件事都自動做完，你只要在瀏覽器點「同意」。

執行方式（在專案資料夾底下）：
    python tools/tiktok_auth.py

程式會：
    1. 在本機開一個臨時網頁伺服器接住 TikTok 回傳的授權碼
    2. 自動打開瀏覽器帶你到 TikTok 授權頁
    3. 你點「同意授權」之後，自動換成 access_token / refresh_token
    4. 印出你該貼進 .env 的內容

前置作業請看 docs/04-申請各平台API.md 的「步驟 C」。
最重要的是：TikTok 開發者後台的 Redirect URI 必須**完全一致**地填成
    http://localhost:8080/callback
"""

from __future__ import annotations

import sys
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import requests  # noqa: E402

REDIRECT_URI = "http://localhost:8080/callback"
AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
PORT = 8080

# 草稿模式需要 video.upload；直接公開發佈需要 video.publish（且要通過 TikTok 審核）。
SCOPES = "user.info.basic,video.upload,video.publish"

_received: dict[str, str] = {}


class CallbackHandler(BaseHTTPRequestHandler):
    """接住 TikTok 導回來的授權碼。"""

    def do_GET(self) -> None:  # noqa: N802（這是 http.server 規定的方法名）
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/callback":
            self.send_response(404)
            self.end_headers()
            return

        params = urllib.parse.parse_qs(parsed.query)
        _received["code"] = (params.get("code") or [""])[0]
        _received["error"] = (params.get("error_description") or params.get("error") or [""])[0]

        body = (
            "<html><head><meta charset='utf-8'></head><body "
            "style='font-family:sans-serif;text-align:center;padding-top:80px'>"
        )
        if _received["code"]:
            body += "<h2>✅ 授權成功</h2><p>可以關掉這個分頁，回到終端機看結果。</p>"
        else:
            body += f"<h2>❌ 授權失敗</h2><p>{_received['error']}</p>"
        body += "</body></html>"

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))

    def log_message(self, *args) -> None:
        """不要把 HTTP 存取紀錄印到畫面上，會干擾使用者。"""


def ask(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        print("\n已取消。")
        sys.exit(1)


def die(message: str) -> None:
    print(f"\n❌ {message}\n")
    sys.exit(1)


def main() -> int:
    print()
    print("=" * 60)
    print("  TikTok 授權小幫手")
    print("=" * 60)
    print()
    print("開始之前請先確認，你在 TikTok 開發者後台的 Redirect URI 已經填成：")
    print(f"    {REDIRECT_URI}")
    print("一個字都不能差（包含最後沒有斜線）。")
    print()

    client_key = ask("1. 請貼上你的 Client Key：")
    client_secret = ask("2. 請貼上你的 Client Secret：")

    if not (client_key and client_secret):
        die("兩個值都要填才能繼續。")

    # --- 開啟本機伺服器等 TikTok 導回來 ---
    try:
        server = HTTPServer(("localhost", PORT), CallbackHandler)
    except OSError as exc:
        die(f"無法在連接埠 {PORT} 開啟臨時伺服器：{exc}\n"
            f"   可能是有其他程式佔用了 {PORT}。關掉它之後再試一次。")

    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()

    params = {
        "client_key": client_key,
        "scope": SCOPES,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "state": "affiliate_bot",
    }
    auth_link = f"{AUTH_URL}?{urllib.parse.urlencode(params)}"

    print("\n正在打開瀏覽器，請在 TikTok 頁面上點「同意授權」…")
    print("\n如果瀏覽器沒有自動打開，請手動複製下面這個網址貼到瀏覽器：")
    print(f"\n{auth_link}\n")
    try:
        webbrowser.open(auth_link)
    except Exception:
        pass

    print("等待授權中…（最多等 5 分鐘）")
    thread.join(timeout=300)
    server.server_close()

    if not _received.get("code"):
        die("沒有收到授權碼。\n"
            f"   常見原因：Redirect URI 沒有填成 {REDIRECT_URI}，\n"
            "   或是你的應用程式還沒把自己加進測試使用者名單。")

    # --- 用授權碼換權杖 ---
    print("\n授權碼收到了，正在換發權杖…")
    try:
        resp = requests.post(TOKEN_URL, headers={
            "Content-Type": "application/x-www-form-urlencoded",
        }, data={
            "client_key": client_key,
            "client_secret": client_secret,
            "code": _received["code"],
            "grant_type": "authorization_code",
            "redirect_uri": REDIRECT_URI,
        }, timeout=60)
    except requests.RequestException as exc:
        die(f"連線 TikTok 失敗：{exc}")

    data = resp.json()
    refresh_token = data.get("refresh_token")
    if not refresh_token:
        die(f"換發權杖失敗（HTTP {resp.status_code}）：\n   {data}\n"
            "   常見原因：Client Secret 打錯，或 Redirect URI 跟後台設定的不一致。")

    granted = data.get("scope", "")

    print("✅ 權杖取得成功\n")
    print("=" * 60)
    print("  請把下面這三行貼到專案根目錄的 .env 檔案裡")
    print("  （取代掉原本 TIKTOK_ 開頭的那三行）")
    print("=" * 60)
    print()
    print(f"TIKTOK_CLIENT_KEY={client_key}")
    print(f"TIKTOK_CLIENT_SECRET={client_secret}")
    print(f"TIKTOK_REFRESH_TOKEN={refresh_token}")
    print()
    print("=" * 60)
    print()
    print(f"這次拿到的權限範圍：{granted or '（未回報）'}")
    if "video.publish" not in granted:
        print()
        print("⚠️  沒有 video.publish 權限，代表只能用草稿模式（config.yaml 的 mode: draft）。")
        print("    這是正常的，TikTok 要通過內容發佈審核才會給這個權限。")
        print("    草稿模式一樣能自動上傳，你只要在手機 App 點一下就能發佈。")
    print()
    print("貼好之後：")
    print("  1. 在 config.yaml 把 publish.tiktok.enabled 改成 true")
    print("  2. 執行 python run.py doctor 確認每一項都打勾")
    print()
    print("⚠️  refresh_token 等同你的帳號密碼，不要傳給任何人。")
    print("⚠️  它大約 365 天後會失效，到時候再執行一次這支程式即可。")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
