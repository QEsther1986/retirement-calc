"""發佈到 TikTok。

需要準備（詳細步驟見 docs/04-申請各平台API.md）：
  1. 一個 TikTok 開發者應用程式（developers.tiktok.com）
  2. Client Key / Client Secret
  3. 使用者授權後取得的 access_token 與 refresh_token

【兩種模式，請看清楚差別】
  draft（草稿，預設）
      影片會送到你 TikTok App 的「草稿匣」，你在手機上點一下就能發。
      好處：不需要通過 TikTok 的應用程式審核，申請完就能用。
      需要的權限範圍（scope）：video.upload

  direct（直接發佈）
      影片直接公開發佈，完全不用碰手機。
      但是：TikTok 要求你的應用程式通過「Content Posting API 審核」才會開放。
      審核沒過之前，你就算呼叫成功，影片也只會是「僅自己可見」。
      需要的權限範圍（scope）：video.publish

建議：先用 draft 模式跑，等流程穩定、確定要放大規模，再去送審。

【權杖會過期】
TikTok 的 access_token 只有 24 小時效力，所以程式每次執行都會先用
refresh_token 換一張新的。refresh_token 本身約 365 天有效，過期要重新授權。
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import requests

from ..logging_setup import get_logger
from ..models import VideoScript
from .base import Account, Publisher, PublishResult, build_caption

log = get_logger(__name__)

API_BASE = "https://open.tiktokapis.com/v2"
TOKEN_URL = f"{API_BASE}/oauth/token/"


class TikTokPublisher(Publisher):
    platform = "tiktok"

    def _refresh_access_token(self, account: Account) -> tuple[str, str]:
        """用 refresh_token 換一張新的 access_token。回傳 (token, 錯誤訊息)。"""
        client_key = self.config.secret(account.env("client_key_env", "TIKTOK_CLIENT_KEY"))
        client_secret = self.config.secret(account.env("client_secret_env", "TIKTOK_CLIENT_SECRET"))
        refresh_token = self.config.secret(account.env("refresh_token_env", "TIKTOK_REFRESH_TOKEN"))

        if not (client_key and client_secret and refresh_token):
            return "", (
                f"缺少 .env 設定：{account.env('client_key_env', 'TIKTOK_CLIENT_KEY')}、"
                f"{account.env('client_secret_env', 'TIKTOK_CLIENT_SECRET')} 或 "
                f"{account.env('refresh_token_env', 'TIKTOK_REFRESH_TOKEN')}"
            )

        try:
            resp = requests.post(
                TOKEN_URL,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data={
                    "client_key": client_key,
                    "client_secret": client_secret,
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                },
                timeout=60,
            )
        except requests.RequestException as exc:
            return "", f"連線 TikTok 取得權杖失敗：{exc}"

        data = _json(resp)
        token = data.get("access_token", "")
        if not token:
            return "", (
                f"TikTok 換發權杖失敗（HTTP {resp.status_code}）：{data}\n"
                "    最常見原因：refresh_token 過期（約 365 天）或被撤銷，需要重新走一次授權流程。"
            )

        new_refresh = data.get("refresh_token")
        if new_refresh and new_refresh != refresh_token:
            log.warning(
                "TikTok 發了新的 refresh_token。請把 .env 裡的 %s 更新成：\n%s",
                account.env("refresh_token_env", "TIKTOK_REFRESH_TOKEN"), new_refresh,
            )
        return token, ""

    def publish_one(self, account: Account, video_path: Path,
                    script: VideoScript, link: str) -> PublishResult:
        token, error = self._refresh_access_token(account)
        if not token:
            return PublishResult(self.platform, account.label, False, message=error)

        mode = str(account.settings.get("mode", self.settings.get("mode", "draft"))).lower()
        file_size = video_path.stat().st_size
        timeout = int(self.settings.get("timeout_seconds", 300))

        # TikTok 要求單一分塊時，整支影片當成一塊上傳。
        source_info = {
            "source": "FILE_UPLOAD",
            "video_size": file_size,
            "chunk_size": file_size,
            "total_chunk_count": 1,
        }

        if mode == "direct":
            init_url = f"{API_BASE}/post/publish/video/init/"
            title = build_caption(script, link, max_length=2100)
            privacy = str(account.settings.get("privacy_level", "SELF_ONLY")).upper()
            payload = {
                "post_info": {
                    "title": title,
                    "privacy_level": privacy,
                    "disable_duet": bool(account.settings.get("disable_duet", False)),
                    "disable_comment": bool(account.settings.get("disable_comment", False)),
                    "disable_stitch": bool(account.settings.get("disable_stitch", False)),
                },
                "source_info": source_info,
            }
        else:
            # 草稿模式：TikTok 不接受文案，文案要你在 App 裡自己貼上。
            init_url = f"{API_BASE}/post/publish/inbox/video/init/"
            payload = {"source_info": source_info}

        try:
            init = requests.post(
                init_url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json; charset=UTF-8",
                },
                data=json.dumps(payload),
                timeout=timeout,
            )
        except requests.RequestException as exc:
            return PublishResult(self.platform, account.label, False,
                                 message=f"連線 TikTok 失敗：{exc}")

        init_data = _json(init)
        body = init_data.get("data") or {}
        publish_id = body.get("publish_id")
        upload_url = body.get("upload_url")
        if not (publish_id and upload_url):
            return PublishResult(self.platform, account.label, False,
                                 message=_explain_tiktok_error(init_data, init.status_code, mode))

        # --- 上傳影片本體 ---
        try:
            upload = requests.put(
                upload_url,
                headers={
                    "Content-Type": "video/mp4",
                    "Content-Range": f"bytes 0-{file_size - 1}/{file_size}",
                },
                data=video_path.read_bytes(),
                timeout=timeout,
            )
        except requests.RequestException as exc:
            return PublishResult(self.platform, account.label, False,
                                 message=f"上傳影片到 TikTok 失敗：{exc}")

        if upload.status_code not in (200, 201, 204):
            return PublishResult(
                self.platform, account.label, False,
                message=f"TikTok 影片上傳回應 HTTP {upload.status_code}：{upload.text[:300]}",
            )

        # --- 查詢處理結果 ---
        status_text = self._wait_for_status(token, publish_id, timeout)

        if mode == "direct":
            note = "已送出發佈"
            if str(account.settings.get("privacy_level", "SELF_ONLY")).upper() == "SELF_ONLY":
                note += "（目前設定為「僅自己可見」；通過 TikTok 審核後才建議改成 PUBLIC_TO_EVERYONE）"
        else:
            note = "已送到 TikTok App 的草稿匣，請開 App 完成發佈並貼上文案"
            manual_caption = self.config.paths.output / "待發佈" / f"{video_path.stem}_tiktok文案.txt"
            manual_caption.parent.mkdir(parents=True, exist_ok=True)
            manual_caption.write_text(build_caption(script, link), encoding="utf-8")

        return PublishResult(self.platform, account.label, True, remote_id=str(publish_id),
                             message=f"{note}。{status_text}")

    def _wait_for_status(self, token: str, publish_id: str, timeout: int) -> str:
        """查一下 TikTok 端的處理狀態，查不到也不算失敗（影片已經傳上去了）。"""
        for _ in range(6):
            time.sleep(5)
            try:
                resp = requests.post(
                    f"{API_BASE}/post/publish/status/fetch/",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json; charset=UTF-8",
                    },
                    data=json.dumps({"publish_id": publish_id}),
                    timeout=timeout,
                )
            except requests.RequestException:
                continue
            data = (_json(resp).get("data") or {})
            status = data.get("status")
            if status in ("PUBLISH_COMPLETE", "SEND_TO_USER_INBOX"):
                return f"TikTok 狀態：{status}"
            if status == "FAILED":
                return f"TikTok 回報處理失敗：{data.get('fail_reason', '未提供原因')}"
        return "TikTok 仍在處理中，稍後可在 App 確認。"


def _json(response: requests.Response) -> dict:
    try:
        data = response.json()
        return data if isinstance(data, dict) else {"raw": data}
    except ValueError:
        return {"raw_text": response.text[:400]}


def _explain_tiktok_error(data: dict, status_code: int, mode: str) -> str:
    error = data.get("error") or {}
    code = str(error.get("code") or "")
    message = error.get("message") or data.get("raw_text") or str(data)[:300]

    hints = {
        "access_token_invalid": "存取權杖無效，請確認 .env 的 TikTok 金鑰是否正確。",
        "scope_not_authorized": (
            f"你的應用程式沒有這個模式需要的權限。"
            f"{'direct 模式需要 video.publish 且要通過 TikTok 內容發佈審核。' if mode == 'direct' else 'draft 模式需要 video.upload 權限。'}"
        ),
        "rate_limit_exceeded": "已達 API 呼叫上限，請降低發文頻率或稍後再試。",
        "spam_risk_too_many_posts": "今天發太多了，TikTok 暫時擋下，請明天再試。",
        "spam_risk_user_banned_from_posting": "這個帳號目前被禁止發文，請先到 App 確認帳號狀態。",
        "unaudited_client_can_only_post_to_private_accounts": (
            "應用程式尚未通過審核，只能發到私人帳號。請改用 draft 模式，"
            "或先向 TikTok 送出 Content Posting API 審核。"
        ),
    }
    hint = hints.get(code, "")
    return (f"TikTok 錯誤（HTTP {status_code}，代碼 {code}）：{message}"
            + (f"\n    建議：{hint}" if hint else ""))
