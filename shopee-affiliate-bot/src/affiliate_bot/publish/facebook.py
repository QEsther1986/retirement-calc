"""發佈到 Facebook 粉絲專頁的 Reels。

需要準備（詳細步驟見 docs/04-申請各平台API.md）：
  1. 一個 Facebook 粉絲專頁（個人檔案不行，API 只支援粉專）
  2. 一個 Meta 開發者應用程式（developers.facebook.com）
  3. 一組「粉絲專頁存取權杖」(Page Access Token)，權限要有：
        pages_show_list, pages_read_engagement, pages_manage_posts
  4. 粉專的 Page ID

上傳流程是 Meta 規定的三步驟：
    start  -> 跟 Meta 要一個上傳網址
    upload -> 把影片檔傳上去
    finish -> 告訴 Meta「發佈吧」，同時帶上文案
"""

from __future__ import annotations

from pathlib import Path

import requests

from ..logging_setup import get_logger
from ..models import VideoScript
from .base import Account, Publisher, PublishResult, build_caption

log = get_logger(__name__)

GRAPH_VERSION = "v21.0"
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_VERSION}"
RUPLOAD_BASE = f"https://rupload.facebook.com/video-upload/{GRAPH_VERSION}"


class FacebookPublisher(Publisher):
    platform = "facebook"

    def publish_one(self, account: Account, video_path: Path,
                    script: VideoScript, link: str) -> PublishResult:
        page_id = self.config.secret(account.env("page_id_env", "FB_PAGE_ID"))
        token = self.config.secret(account.env("access_token_env", "FB_PAGE_ACCESS_TOKEN"))

        if not page_id or not token:
            return PublishResult(
                self.platform, account.label, False,
                message=(
                    f"缺少 .env 設定：{account.env('page_id_env', 'FB_PAGE_ID')} 或 "
                    f"{account.env('access_token_env', 'FB_PAGE_ACCESS_TOKEN')}"
                ),
            )

        caption = build_caption(script, link)
        timeout = int(self.settings.get("timeout_seconds", 180))

        # --- 步驟 1：要一個上傳網址 ---
        try:
            start = requests.post(
                f"{GRAPH_BASE}/{page_id}/video_reels",
                data={"upload_phase": "start", "access_token": token},
                timeout=timeout,
            )
        except requests.RequestException as exc:
            return PublishResult(self.platform, account.label, False,
                                 message=f"連線 Facebook 失敗：{exc}")

        start_data = _json(start)
        if "video_id" not in start_data:
            return PublishResult(self.platform, account.label, False,
                                 message=_explain_meta_error(start_data, start.status_code))

        video_id = str(start_data["video_id"])
        upload_url = start_data.get("upload_url") or f"{RUPLOAD_BASE}/{video_id}"

        # --- 步驟 2：上傳影片檔 ---
        file_bytes = video_path.read_bytes()
        try:
            upload = requests.post(
                upload_url,
                headers={
                    "Authorization": f"OAuth {token}",
                    "offset": "0",
                    "file_size": str(len(file_bytes)),
                    "Content-Type": "application/octet-stream",
                },
                data=file_bytes,
                timeout=timeout,
            )
        except requests.RequestException as exc:
            return PublishResult(self.platform, account.label, False,
                                 message=f"上傳影片到 Facebook 失敗：{exc}")

        upload_data = _json(upload)
        if not upload_data.get("success", upload.status_code == 200):
            return PublishResult(self.platform, account.label, False,
                                 message=_explain_meta_error(upload_data, upload.status_code))

        # --- 步驟 3：正式發佈 ---
        publish_as_draft = bool(account.settings.get("draft", False))
        try:
            finish = requests.post(
                f"{GRAPH_BASE}/{page_id}/video_reels",
                data={
                    "upload_phase": "finish",
                    "video_id": video_id,
                    "video_state": "DRAFT" if publish_as_draft else "PUBLISHED",
                    "description": caption,
                    "access_token": token,
                },
                timeout=timeout,
            )
        except requests.RequestException as exc:
            return PublishResult(self.platform, account.label, False,
                                 message=f"Facebook 發佈步驟失敗：{exc}")

        finish_data = _json(finish)
        if not finish_data.get("success", finish.status_code == 200):
            return PublishResult(self.platform, account.label, False,
                                 message=_explain_meta_error(finish_data, finish.status_code))

        state = "草稿" if publish_as_draft else "已發佈"
        return PublishResult(self.platform, account.label, True, remote_id=video_id,
                             message=f"Reels {state}，影片 ID {video_id}")


def _json(response: requests.Response) -> dict:
    try:
        data = response.json()
        return data if isinstance(data, dict) else {"raw": data}
    except ValueError:
        return {"raw_text": response.text[:400]}


def _explain_meta_error(data: dict, status_code: int) -> str:
    """把 Meta 的錯誤碼翻成看得懂的中文建議。"""
    error = data.get("error") or {}
    code = error.get("code")
    message = error.get("message") or data.get("raw_text") or str(data)[:300]

    hints = {
        190: "存取權杖失效或過期。請重新產生粉專權杖（長期權杖約 60 天要換一次）。",
        200: "權限不足。請確認應用程式已取得 pages_manage_posts 權限，且你是該粉專的管理員。",
        100: "參數有誤。最常見是 Page ID 填錯，或權杖不是「粉專權杖」而是「使用者權杖」。",
        368: "帳號暫時被限制發文，請過幾小時再試，並降低發文頻率。",
        4: "已達 API 呼叫次數上限，請稍後再試。",
        613: "已達 API 呼叫次數上限，請稍後再試。",
    }
    hint = hints.get(code, "")
    prefix = f"Facebook 錯誤（HTTP {status_code}，代碼 {code}）：" if code else f"Facebook 錯誤（HTTP {status_code}）："
    return f"{prefix}{message}" + (f"\n    建議：{hint}" if hint else "")
