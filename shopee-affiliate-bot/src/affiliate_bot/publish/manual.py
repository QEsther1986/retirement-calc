"""人工發佈模式：不呼叫任何平台 API，只把要發的東西整理好。

強烈建議你「前兩週」都先用這個模式：
  * 完全沒有帳號被封的風險
  * 你可以先確認 AI 寫的文案品質、影片好不好看
  * 確認哪種內容有流量之後，再開自動發佈

執行後會在 output/待發佈/ 產生：
    2026-09-19_商品名稱.mp4        影片本身
    2026-09-19_商品名稱.txt        文案（可直接複製貼上）
    2026-09-19_商品名稱.jpg        封面圖
"""

from __future__ import annotations

from pathlib import Path

from ..logging_setup import get_logger
from ..models import VideoScript
from .base import Account, Publisher, PublishResult, build_caption

log = get_logger(__name__)


class ManualPublisher(Publisher):
    platform = "manual"

    def publish_one(self, account: Account, video_path: Path,
                    script: VideoScript, link: str) -> PublishResult:
        folder = self.config.paths.output / "待發佈"
        folder.mkdir(parents=True, exist_ok=True)

        caption = build_caption(script, link)
        text_path = folder / f"{video_path.stem}.txt"
        content = (
            f"=== 貼文文案（複製下面這段）===\n\n{caption}\n\n"
            f"=== 影片檔 ===\n{video_path}\n\n"
            f"=== 分潤連結 ===\n{link}\n\n"
            f"=== 建議 ===\n"
            f"Instagram 不能在貼文內放可點擊連結，請把連結放在個人簡介或限時動態。\n"
            f"Facebook / TikTok 可以直接放在文案或留言區。\n"
        )
        text_path.write_text(content, encoding="utf-8")

        # 把影片複製一份到待發佈資料夾，方便你用手機同步
        target_video = folder / video_path.name
        if target_video.resolve() != video_path.resolve():
            target_video.write_bytes(video_path.read_bytes())

        log.info("已整理好待發佈檔案：%s", folder)
        return PublishResult(self.platform, account.label, True,
                             message=f"已輸出到 {folder}，請自行上傳")
