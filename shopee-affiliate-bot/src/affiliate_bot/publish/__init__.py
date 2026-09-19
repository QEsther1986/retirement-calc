"""發佈模組：把做好的影片送上各社群平台。

支援的平台與所需條件：
  manual    — 不上傳，只把影片+文案整理好，你自己手動發（零風險，建議先用這個）
  facebook  — Facebook 粉絲專頁 Reels（需要 Meta 開發者應用程式 + 粉專權杖）
  instagram — Instagram Reels（需要商業帳號 + 連結粉專 + 影片要有公開網址）
  tiktok    — TikTok（預設發到草稿匣，不需要應用程式審核）

「矩陣式」多帳號：在 config.yaml 的 publish.<平台>.accounts 底下列出多組帳號，
程式會依序發佈，每組之間會間隔一段時間（避免被判定為機器人洗版）。
"""

from __future__ import annotations

from ..config import Config
from ..logging_setup import get_logger
from .base import Account, PublishResult, Publisher
from .facebook import FacebookPublisher
from .instagram import InstagramPublisher
from .manual import ManualPublisher
from .tiktok import TikTokPublisher

log = get_logger(__name__)

_REGISTRY = {
    "manual": ManualPublisher,
    "facebook": FacebookPublisher,
    "instagram": InstagramPublisher,
    "tiktok": TikTokPublisher,
}

__all__ = ["Account", "PublishResult", "Publisher", "build_publishers", "_REGISTRY"]


def build_publishers(config: Config) -> list[Publisher]:
    """依照 config.yaml 建立所有「有啟用」的發佈器。"""
    publishers: list[Publisher] = []
    publish_cfg = config.get("publish", {}) or {}

    for platform, cls in _REGISTRY.items():
        section = publish_cfg.get(platform) or {}
        if not section.get("enabled"):
            continue
        accounts = [
            Account(
                label=str(acc.get("label") or f"{platform}-{i + 1}"),
                settings=acc,
            )
            for i, acc in enumerate(section.get("accounts") or [])
        ]
        if not accounts and platform != "manual":
            log.warning("平台 %s 已啟用，但沒有設定任何帳號，將略過。", platform)
            continue
        if platform == "manual" and not accounts:
            accounts = [Account(label="manual", settings={})]
        publishers.append(cls(config, accounts, section))

    if not publishers:
        log.warning("config.yaml 裡沒有啟用任何發佈平台，影片只會存在 output 資料夾。")
    return publishers
