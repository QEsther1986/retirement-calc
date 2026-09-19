"""發佈器的共同介面。"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..config import Config
from ..logging_setup import get_logger
from ..models import VideoScript

log = get_logger(__name__)


@dataclass
class Account:
    """一個社群帳號。settings 來自 config.yaml 裡該帳號的設定區塊。"""

    label: str
    settings: dict[str, Any] = field(default_factory=dict)

    def env(self, key: str, default: str = "") -> str:
        """取得這個帳號在 config.yaml 指定的環境變數名稱。"""
        return str(self.settings.get(key, default) or default)


@dataclass
class PublishResult:
    platform: str
    account_label: str
    success: bool
    remote_id: str = ""
    message: str = ""

    def describe(self) -> str:
        mark = "成功" if self.success else "失敗"
        detail = f"（{self.message}）" if self.message else ""
        return f"[{self.platform}/{self.account_label}] {mark}{detail}"


class Publisher(ABC):
    platform = "base"

    def __init__(self, config: Config, accounts: list[Account], settings: dict[str, Any]):
        self.config = config
        self.accounts = accounts
        self.settings = settings
        # 多帳號之間的間隔秒數：同一秒對多個帳號發一樣的內容，
        # 非常容易被平台判定成機器人洗版。
        self.gap_seconds = int(settings.get("gap_seconds", 90))

    @abstractmethod
    def publish_one(self, account: Account, video_path: Path,
                    script: VideoScript, link: str) -> PublishResult:
        """發佈到單一帳號。實作時請自行處理例外並回傳 PublishResult。"""

    def publish(self, video_path: Path, script: VideoScript, link: str) -> list[PublishResult]:
        results: list[PublishResult] = []
        for index, account in enumerate(self.accounts):
            if index > 0 and self.gap_seconds > 0:
                log.info("等待 %d 秒後再發下一個帳號（避免被判定洗版）…", self.gap_seconds)
                time.sleep(self.gap_seconds)
            log.info("正在發佈到 %s／%s …", self.platform, account.label)
            try:
                result = self.publish_one(account, video_path, script, link)
            except Exception as exc:  # 單一帳號失敗不應該讓整批中斷
                result = PublishResult(self.platform, account.label, False,
                                       message=f"未預期的錯誤：{exc}")
            log.info("  %s", result.describe())
            results.append(result)
        return results


def build_caption(script: VideoScript, link: str, max_length: int = 2000,
                  link_in_caption: bool = True) -> str:
    """組出貼文文案：正文 + 連結 + 標籤。"""
    parts = [script.caption.strip()]
    if link_in_caption and link:
        parts.append(f"\n🛒 商品連結：{link}")
    if script.hashtags:
        parts.append("\n" + " ".join(f"#{tag}" for tag in script.hashtags))
    caption = "\n".join(p for p in parts if p).strip()
    if len(caption) > max_length:
        caption = caption[: max_length - 1] + "…"
    return caption
