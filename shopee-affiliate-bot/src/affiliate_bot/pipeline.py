"""把所有步驟串成一條完整流程。

一次執行會做這些事：
    選品 → 寫腳本 → 下載圖 → 配音 → 合成影片 → 記錄 → 發佈（或等你審核）

設計上每一件商品都是獨立處理的：其中一件失敗（例如圖片掛了、API 超時），
不會影響其他商品，程式會記下錯誤然後繼續做下一件。
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from .config import Config
from .db import Database
from .logging_setup import get_logger
from .media import images as image_utils
from .media import tts as tts_utils
from .media.render import Clip, RenderError, make_thumbnail, render_video
from .models import Product, VideoScript
from .publish import build_publishers
from .publish.base import PublishResult
from .scriptwriter import ScriptWriter
from .selection import ProductSelector
from .sources import build_source

log = get_logger(__name__)

_UNSAFE_FILENAME = re.compile(r'[\\/:*?"<>|\s]+')


def _safe_name(text: str, max_length: int = 28) -> str:
    """把商品名稱變成安全的檔名。"""
    cleaned = _UNSAFE_FILENAME.sub("_", text).strip("_")
    return cleaned[:max_length] or "product"


@dataclass
class VideoJob:
    """一件商品的產出結果。"""

    product: Product
    script: VideoScript
    video_path: Path
    duration: float
    video_id: int


class Pipeline:
    def __init__(self, config: Config):
        self.config = config
        self.db = Database(config.paths.database)
        self.source = build_source(config)
        self.selector = ProductSelector(config)
        self.writer = ScriptWriter(config)
        self.publishers = build_publishers(config)

    # ---------- 影片製作 ----------

    def _build_clips(self, product: Product, script: VideoScript,
                     work_dir: Path) -> list[Clip]:
        """把腳本 + 圖片 + 配音組成影片片段清單。"""
        voice = self.config.get("video.voice", "zh-TW-HsiaoChenNeural")
        rate = self.config.get("video.voice_rate", "+8%")
        gap = float(self.config.get("video.segment_gap_seconds", 0.35))

        downloaded = image_utils.download_images(product.image_urls, work_dir / "images")
        if not downloaded:
            raise RenderError("沒有任何商品圖下載成功，無法製作影片。")

        # 第一段用鉤子，中間是內容，最後是行動呼籲。
        lines: list[tuple[str, str]] = []
        if script.hook:
            lines.append((script.hook, script.hook))
        for seg in script.segments:
            lines.append((seg.on_screen or "", seg.text))
        if script.cta:
            lines.append((script.cta, script.cta))

        picked = image_utils.pick_for_segments(downloaded, len(lines))
        clips: list[Clip] = []

        for index, (headline, narration) in enumerate(lines):
            raw_audio = work_dir / f"voice_{index:02d}.mp3"
            padded_audio = work_dir / f"voice_{index:02d}_padded.m4a"
            tts_utils.synthesize(narration, raw_audio, voice=voice, rate=rate)
            duration = tts_utils.pad_audio(raw_audio, padded_audio, gap)
            if duration <= 0:
                log.warning("第 %d 段配音長度為 0，略過這一段。", index + 1)
                continue
            clips.append(Clip(
                image=picked[index],
                audio=padded_audio,
                duration=duration,
                headline=headline,
                subtitle=narration,
            ))

        if not clips:
            raise RenderError("所有段落的配音都失敗了，無法製作影片。")
        return clips

    def make_video(self, product: Product, script: VideoScript) -> VideoJob:
        stamp = datetime.now().strftime("%Y%m%d_%H%M")
        name = f"{stamp}_{_safe_name(product.name)}"
        work_dir = self.config.paths.work / name
        work_dir.mkdir(parents=True, exist_ok=True)
        video_path = self.config.paths.output / f"{name}.mp4"

        clips = self._build_clips(product, script, work_dir)

        bgm_path = None
        bgm_setting = str(self.config.get("video.bgm_path", "") or "")
        if bgm_setting:
            candidate = (self.config.paths.root / bgm_setting).resolve()
            if candidate.exists():
                bgm_path = candidate
            else:
                log.warning("設定的背景音樂檔不存在：%s（這次不加背景音樂）", candidate)

        duration = render_video(
            clips, video_path, work_dir,
            self.config.get("video", {}) or {}, bgm_path,
        )

        make_thumbnail(video_path, video_path.with_suffix(".jpg"))

        # 把腳本與連結存成同名的 .json，之後審核發佈時可以直接讀回來。
        sidecar = video_path.with_suffix(".json")
        sidecar.write_text(json.dumps({
            "product": asdict(product),
            "script": asdict(script),
            "affiliate_link": product.affiliate_link,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }, ensure_ascii=False, indent=2), encoding="utf-8")

        video_id = self.db.record_video(
            product.item_id, str(video_path), script.caption,
            script.hashtags, duration,
        )
        self.db.mark_product_used(product.item_id)
        return VideoJob(product, script, video_path, duration, video_id)

    # ---------- 發佈 ----------

    def publish_job(self, job: VideoJob) -> list[PublishResult]:
        if not self.publishers:
            log.warning("沒有啟用任何發佈平台，影片留在 %s", job.video_path)
            return []

        all_results: list[PublishResult] = []
        for publisher in self.publishers:
            results = publisher.publish(job.video_path, job.script,
                                        job.product.affiliate_link)
            for result in results:
                self.db.record_post(job.video_id, result.platform, result.account_label,
                                    "success" if result.success else "failed",
                                    result.remote_id, result.message)
            all_results.extend(results)

        ok = sum(1 for r in all_results if r.success)
        self.db.set_video_status(job.video_id, "published" if ok else "failed")
        return all_results

    # ---------- 主流程 ----------

    def run(self, count: int | None = None, publish: bool = True) -> list[VideoJob]:
        count = count or int(self.config.get("general.videos_per_run", 3))
        pool_size = int(self.config.get("general.candidate_pool", 40))
        dedupe_days = int(self.config.get("selection.dedupe_days", 30))
        require_approval = bool(self.config.get("publish.require_approval", True))

        log.info("=" * 56)
        log.info("開始執行：商品來源 = %s，這次要做 %d 支影片", self.source.describe(), count)
        log.info("=" * 56)

        candidates = self.source.fetch(pool_size)
        if not candidates:
            log.error("沒有取得任何候選商品，流程結束。")
            return []

        chosen = self.selector.select(candidates, count, self.db.used_item_ids(dedupe_days))
        if not chosen:
            log.error(
                "沒有商品通過篩選條件。\n"
                "建議：放寬 config.yaml 的 selection 條件（例如降低 min_sales 或 "
                "min_commission_rate），或增加 source 的商品數量。"
            )
            return []

        for scored in chosen:
            self.db.remember_product(
                scored.product.item_id, scored.product.name, scored.product.price,
                scored.product.commission_rate, scored.product.sales,
                scored.product.rating, scored.product.affiliate_link, scored.score,
            )

        jobs: list[VideoJob] = []
        for index, scored in enumerate(chosen, start=1):
            product = scored.product
            log.info("")
            log.info("--- 第 %d/%d 件：%s ---", index, len(chosen), product.name)
            try:
                script = self.writer.write(product)
                job = self.make_video(product, script)
                jobs.append(job)
            except RenderError as exc:
                log.error("這件商品做影片失敗，跳過：%s", exc)
                continue
            except Exception as exc:
                log.exception("處理「%s」時發生未預期錯誤，跳過：%s", product.name, exc)
                continue

            if not publish:
                continue
            if require_approval:
                self.db.set_video_status(job.video_id, "pending")
                log.info("影片已完成，等你審核。確認沒問題後執行："
                         "python run.py approve %d", job.video_id)
            else:
                self.publish_job(job)

        log.info("")
        log.info("=" * 56)
        log.info("執行完畢：成功產出 %d / %d 支影片，檔案在 %s",
                 len(jobs), len(chosen), self.config.paths.output)
        if require_approval and publish and jobs:
            log.info("目前設定為「需人工審核」。看過影片後，執行下面指令就會發佈：")
            log.info("    python run.py approve all")
        log.info("=" * 56)
        return jobs

    # ---------- 審核後發佈 ----------

    def approve(self, video_ids: list[int] | None) -> None:
        """把待審核的影片實際發佈出去。video_ids 為 None 代表全部。"""
        with self.db.connect() as conn:
            if video_ids:
                placeholders = ",".join("?" for _ in video_ids)
                rows = conn.execute(
                    f"SELECT * FROM videos WHERE id IN ({placeholders})", video_ids
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM videos WHERE status = 'pending' ORDER BY id"
                ).fetchall()

        if not rows:
            log.info("沒有待發佈的影片。")
            return

        for row in rows:
            video_path = Path(row["file_path"])
            sidecar = video_path.with_suffix(".json")
            if not video_path.exists() or not sidecar.exists():
                log.error("影片 %s 的檔案或腳本資料不見了，略過。", row["id"])
                continue

            data = json.loads(sidecar.read_text(encoding="utf-8"))
            product = Product(**data["product"])
            script_data = data["script"]
            from .models import ScriptSegment
            script = VideoScript(
                hook=script_data["hook"],
                segments=[ScriptSegment(**s) for s in script_data["segments"]],
                caption=script_data["caption"],
                hashtags=script_data["hashtags"],
                cta=script_data["cta"],
            )
            job = VideoJob(product, script, video_path, row["duration_sec"], row["id"])
            log.info("發佈影片 #%s：%s", row["id"], video_path.name)
            self.publish_job(job)
