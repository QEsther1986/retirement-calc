"""下載商品圖片，並整理成影片可用的素材。"""

from __future__ import annotations

import hashlib
from pathlib import Path

import requests

from ..logging_setup import get_logger

log = get_logger(__name__)

_HEADERS = {
    # 有些圖床會擋沒有 User-Agent 的請求
    "User-Agent": "Mozilla/5.0 (compatible; affiliate-bot/0.1)",
}


def download_images(urls: list[str], dest_dir: Path, timeout: int = 20) -> list[Path]:
    """取得商品圖，回傳可用的本機檔案路徑清單。

    每一筆可以是網址，也可以是本機圖片檔的路徑 —— 想用自己拍的照片時很方便。
    失敗的圖會被跳過（不會讓整個流程中斷），只要至少有一張成功就繼續。
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []

    for index, url in enumerate(urls):
        if not url:
            continue

        # 本機圖片：直接使用，不用下載。
        if not url.startswith(("http://", "https://")):
            local = Path(url).expanduser()
            if local.exists() and local.is_file():
                saved.append(local)
            else:
                log.warning("第 %d 張圖既不是網址、本機也找不到這個檔案，已略過：%s",
                            index + 1, url)
            continue

        # 用網址的雜湊當檔名，重跑時可以重複使用已下載的圖。
        stem = hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]
        target = dest_dir / f"{index:02d}_{stem}.jpg"
        if target.exists() and target.stat().st_size > 1024:
            saved.append(target)
            continue

        try:
            resp = requests.get(url, headers=_HEADERS, timeout=timeout)
            resp.raise_for_status()
        except requests.RequestException as exc:
            log.warning("下載第 %d 張圖失敗（%s），略過。", index + 1, exc)
            continue

        if len(resp.content) < 1024:
            log.warning("第 %d 張圖檔案太小，可能不是有效圖片，略過。", index + 1)
            continue

        target.write_bytes(resp.content)
        saved.append(target)

    if not saved:
        log.error("所有商品圖都下載失敗，這件商品無法製作影片。")
    else:
        log.info("成功下載 %d / %d 張商品圖。", len(saved), len(urls))
    return saved


def pick_for_segments(images: list[Path], segment_count: int) -> list[Path]:
    """替每一段旁白配一張圖。圖不夠就循環使用。"""
    if not images:
        return []
    return [images[i % len(images)] for i in range(segment_count)]
