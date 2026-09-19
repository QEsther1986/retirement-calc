"""發佈到 Instagram Reels。

需要準備（詳細步驟見 docs/04-申請各平台API.md）：
  1. Instagram 必須是「商業帳號」或「創作者帳號」，而且已連結到一個 FB 粉絲專頁
  2. Meta 開發者應用程式，權限要有：instagram_basic, instagram_content_publish
  3. Instagram 商業帳號 ID（不是 @帳號名稱，是一串數字）

【最重要的限制，請務必理解】
Instagram 的發佈 API「不接受你直接上傳檔案」，它只接受一個「公開網址」，
由 Instagram 自己去把影片抓回去。也就是說，你的影片必須先放在一個
網際網路上任何人都能下載的網址。

解法有幾種（docs 有詳細教學）：
  a) 用免費的 Cloudflare Tunnel 把本機資料夾暫時變成公開網址（推薦，免費）
  b) 把影片上傳到你自己的網站空間 / 物件儲存（Cloudflare R2、AWS S3 等）
  c) 乾脆用 manual 模式手動發 IG（很多人就是這樣做，IG 演算法對手動發文沒有歧視）

設定好之後，在 config.yaml 填 publish.instagram.video_url_base，
程式會自動組出 {video_url_base}/{影片檔名} 這個網址交給 Instagram。
"""

from __future__ import annotations

import time
from pathlib import Path

import requests

from ..logging_setup import get_logger
from ..models import VideoScript
from .base import Account, Publisher, PublishResult, build_caption

log = get_logger(__name__)

GRAPH_VERSION = "v21.0"
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_VERSION}"


class InstagramPublisher(Publisher):
    platform = "instagram"

    def publish_one(self, account: Account, video_path: Path,
                    script: VideoScript, link: str) -> PublishResult:
        ig_user_id = self.config.secret(account.env("user_id_env", "IG_USER_ID"))
        token = self.config.secret(account.env("access_token_env", "IG_ACCESS_TOKEN"))

        if not ig_user_id or not token:
            return PublishResult(
                self.platform, account.label, False,
                message=(
                    f"缺少 .env 設定：{account.env('user_id_env', 'IG_USER_ID')} 或 "
                    f"{account.env('access_token_env', 'IG_ACCESS_TOKEN')}"
                ),
            )

        url_base = str(
            account.settings.get("video_url_base")
            or self.settings.get("video_url_base")
            or ""
        ).rstrip("/")
        if not url_base:
            return PublishResult(
                self.platform, account.label, False,
                message=(
                    "沒有設定 publish.instagram.video_url_base。\n"
                    "    Instagram 的 API 只能從公開網址抓影片，不能直接上傳檔案。\n"
                    "    請參考 docs/04-申請各平台API.md 的「Instagram 影片網址」章節，\n"
                    "    或先把 Instagram 改用 manual（手動）模式發佈。"
                ),
            )

        video_url = f"{url_base}/{video_path.name}"
        # IG 貼文內文的連結不能點，所以連結放進文案意義不大，改成引導看簡介。
        caption = build_caption(script, link, max_length=2200, link_in_caption=False)
        caption += "\n\n🔗 商品連結放在個人簡介（Bio）"
        timeout = int(self.settings.get("timeout_seconds", 120))

        # --- 步驟 1：建立媒體容器 ---
        try:
            create = requests.post(
                f"{GRAPH_BASE}/{ig_user_id}/media",
                data={
                    "media_type": "REELS",
                    "video_url": video_url,
                    "caption": caption,
                    "share_to_feed": "true",
                    "access_token": token,
                },
                timeout=timeout,
            )
        except requests.RequestException as exc:
            return PublishResult(self.platform, account.label, False,
                                 message=f"連線 Instagram 失敗：{exc}")

        data = _json(create)
        creation_id = data.get("id")
        if not creation_id:
            return PublishResult(self.platform, account.label, False,
                                 message=_explain_ig_error(data, create.status_code, video_url))

        # --- 步驟 2：等 Instagram 把影片抓回去處理完 ---
        max_wait = int(self.settings.get("processing_max_wait_seconds", 300))
        poll_every = 10
        waited = 0
        while waited < max_wait:
            time.sleep(poll_every)
            waited += poll_every
            try:
                status_resp = requests.get(
                    f"{GRAPH_BASE}/{creation_id}",
                    params={"fields": "status_code,status", "access_token": token},
                    timeout=timeout,
                )
            except requests.RequestException as exc:
                log.warning("查詢 Instagram 處理狀態失敗（%s），繼續等待…", exc)
                continue

            status = _json(status_resp)
            code = status.get("status_code")
            if code == "FINISHED":
                break
            if code == "ERROR":
                return PublishResult(
                    self.platform, account.label, False,
                    message=(
                        f"Instagram 處理影片時失敗：{status.get('status', '未提供細節')}\n"
                        f"    請確認 {video_url} 是否真的可以公開下載，"
                        f"且影片是 MP4/H.264、9:16、長度 3~900 秒。"
                    ),
                )
            log.info("Instagram 還在處理影片…（已等 %d 秒）", waited)
        else:
            return PublishResult(
                self.platform, account.label, False,
                message=f"等了 {max_wait} 秒 Instagram 還沒處理完，這次先跳過，稍後可重試。",
            )

        # --- 步驟 3：正式發佈 ---
        try:
            publish = requests.post(
                f"{GRAPH_BASE}/{ig_user_id}/media_publish",
                data={"creation_id": creation_id, "access_token": token},
                timeout=timeout,
            )
        except requests.RequestException as exc:
            return PublishResult(self.platform, account.label, False,
                                 message=f"Instagram 發佈步驟失敗：{exc}")

        result = _json(publish)
        media_id = result.get("id")
        if not media_id:
            return PublishResult(self.platform, account.label, False,
                                 message=_explain_ig_error(result, publish.status_code, video_url))

        return PublishResult(self.platform, account.label, True, remote_id=str(media_id),
                             message=f"Reels 已發佈，貼文 ID {media_id}")


def _json(response: requests.Response) -> dict:
    try:
        data = response.json()
        return data if isinstance(data, dict) else {"raw": data}
    except ValueError:
        return {"raw_text": response.text[:400]}


def _explain_ig_error(data: dict, status_code: int, video_url: str) -> str:
    error = data.get("error") or {}
    code = error.get("code")
    message = error.get("message") or data.get("raw_text") or str(data)[:300]

    hints = {
        190: "存取權杖失效或過期，請重新產生。",
        200: "權限不足。請確認應用程式有 instagram_content_publish 權限，"
             "且 IG 帳號是商業/創作者帳號並已連結粉專。",
        100: f"參數有誤。最常見是 IG_USER_ID 填錯，或 Instagram 抓不到影片網址：{video_url}",
        9007: "已達今日發文上限（Instagram 每 24 小時最多 50 則）。",
        24: "發文頻率過高被暫時限制，請把發文間隔拉長。",
    }
    hint = hints.get(code, "")
    prefix = f"Instagram 錯誤（HTTP {status_code}，代碼 {code}）：" if code else f"Instagram 錯誤（HTTP {status_code}）："
    return f"{prefix}{message}" + (f"\n    建議：{hint}" if hint else "")
