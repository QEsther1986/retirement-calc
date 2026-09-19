"""用 ffmpeg 合成 1080x1920 直式短影音。

做法（拆成小步驟，方便出錯時定位）：
  1. 每一段旁白配一張商品圖，各自輸出成一小段 mp4
     － 背景：商品圖放大模糊，填滿整個直式畫面（避免上下黑邊）
     － 前景：商品圖完整置中，不會被裁掉
     － 緩慢推近的鏡頭運動，讓靜態圖看起來不呆板
     － 畫面上方大字重點 + 下方字幕
  2. 把所有小段接起來
  3. 疊上配音，需要的話再混入背景音樂
  4. 輸出成各平台都吃得下的格式（H.264 + AAC + faststart）

字幕文字是寫到暫存檔再用 drawtext 的 textfile 參數讀取，
這樣就不用處理中文標點、冒號、引號在 ffmpeg 裡的跳脫問題。
"""

from __future__ import annotations

import platform
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ..logging_setup import get_logger

log = get_logger(__name__)

WIDTH, HEIGHT, FPS = 1080, 1920, 30

# 各作業系統常見的中文字型位置，由上往下找第一個存在的。
_FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
    "/System/Library/Fonts/PingFang.ttc",                    # macOS
    "/System/Library/Fonts/Supplemental/Songti.ttc",         # macOS
    "C:/Windows/Fonts/msjh.ttc",                             # Windows 微軟正黑體
    "C:/Windows/Fonts/msjhbd.ttc",
    "C:/Windows/Fonts/mingliu.ttc",
]


class RenderError(Exception):
    """影片合成失敗，訊息會直接顯示給使用者。"""


@dataclass
class Clip:
    """一段畫面：一張圖 + 一段配音 + 要顯示的文字。"""

    image: Path
    audio: Path
    duration: float
    headline: str      # 畫面上方的大字
    subtitle: str      # 畫面下方的字幕


def check_ffmpeg() -> None:
    """確認 ffmpeg / ffprobe 可以使用，否則給出安裝指示。"""
    missing = [name for name in ("ffmpeg", "ffprobe") if shutil.which(name) is None]
    if not missing:
        return
    system = platform.system()
    if system == "Darwin":
        how = "brew install ffmpeg"
    elif system == "Windows":
        how = "winget install Gyan.FFmpeg    （安裝後請重開命令提示字元）"
    else:
        how = "sudo apt update && sudo apt install -y ffmpeg"
    raise RenderError(
        f"找不到 {'、'.join(missing)}，沒有它就沒辦法做影片。\n"
        f"請先安裝 ffmpeg：\n    {how}\n"
        "安裝完成後再執行一次。"
    )


def find_font(configured: str = "") -> str:
    """找一個可用的中文字型檔。找不到會拋錯，因為沒字型中文字幕會變成空白方塊。"""
    if configured:
        if Path(configured).exists():
            return configured
        log.warning("設定的字型檔 %s 不存在，改用系統預設中文字型。", configured)

    for candidate in _FONT_CANDIDATES:
        if Path(candidate).exists():
            return candidate

    system = platform.system()
    if system == "Linux":
        how = "sudo apt install -y fonts-noto-cjk"
    elif system == "Darwin":
        how = "macOS 內建就有中文字型，請確認 /System/Library/Fonts/PingFang.ttc 存在"
    else:
        how = "Windows 內建微軟正黑體，請確認 C:/Windows/Fonts/msjh.ttc 存在"
    raise RenderError(
        "找不到中文字型檔，字幕會變成空白方塊。\n"
        f"請安裝中文字型：\n    {how}\n"
        "或在 config.yaml 的 video.font_path 直接指定字型檔位置。"
    )


def _escape_for_drawtext(path: str) -> str:
    """drawtext 參數裡的路徑要把反斜線與冒號跳脫（Windows 路徑常遇到）。"""
    return path.replace("\\", "/").replace(":", r"\:")


def _wrap_cjk(text: str, per_line: int) -> str:
    """中文不會自動換行，這裡按字數手動斷行。"""
    text = text.strip()
    if not text:
        return ""
    lines, current = [], ""
    for char in text:
        current += char
        # 遇到標點就優先在這裡斷，讀起來比較順
        if len(current) >= per_line or (len(current) >= per_line - 3 and char in "，。！？、,."):
            lines.append(current)
            current = ""
    if current:
        lines.append(current)
    return "\n".join(lines)


def _run(cmd: list[str], what: str) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        tail = "\n".join(result.stderr.strip().splitlines()[-15:])
        raise RenderError(f"{what} 失敗。\nffmpeg 錯誤訊息：\n{tail}")


def _render_clip(clip: Clip, out_path: Path, work_dir: Path, font: str,
                 index: int, style: dict) -> None:
    """把一張圖 + 文字算成一小段影片（沒有聲音，聲音最後統一貼上）。"""
    font_arg = _escape_for_drawtext(font)

    headline_file = work_dir / f"headline_{index}.txt"
    subtitle_file = work_dir / f"subtitle_{index}.txt"
    headline_file.write_text(_wrap_cjk(clip.headline, style["headline_chars"]), encoding="utf-8")
    subtitle_file.write_text(_wrap_cjk(clip.subtitle, style["subtitle_chars"]), encoding="utf-8")

    # 背景：放大裁切填滿 + 模糊壓暗；前景：完整縮放置中，不裁切商品。
    filters = [
        f"[0:v]scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
        f"crop={WIDTH}:{HEIGHT},boxblur=28:3,eq=brightness=-0.15:saturation=0.75,setsar=1[bg]",

        # 緩慢推近：zoompan 的 d=1 代表「每張輸入影格產生一張輸出影格」，
        # 搭配 on（輸出影格序號）就能做出平順的鏡頭運動。
        f"[0:v]scale={style['fg_size']}:{style['fg_size']}:"
        f"force_original_aspect_ratio=decrease,setsar=1,"
        f"zoompan=z='min(1+0.0007*on,1.09)':d=1:"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
        f"s={style['fg_size']}x{style['fg_size']}:fps={FPS}[fg]",

        f"[bg][fg]overlay=(W-w)/2:{style['fg_top']}[base]",
    ]

    draw = (
        f"[base]drawtext=fontfile='{font_arg}':textfile='{_escape_for_drawtext(str(headline_file))}':"
        f"fontsize={style['headline_size']}:fontcolor={style['headline_color']}:"
        f"borderw=8:bordercolor=black@0.85:line_spacing=18:"
        f"x=(w-text_w)/2:y={style['headline_top']}[withhead]"
    )
    filters.append(draw)

    filters.append(
        f"[withhead]drawtext=fontfile='{font_arg}':textfile='{_escape_for_drawtext(str(subtitle_file))}':"
        f"fontsize={style['subtitle_size']}:fontcolor=white:"
        f"borderw=7:bordercolor=black@0.9:line_spacing=14:"
        f"x=(w-text_w)/2:y=h-text_h-{style['subtitle_bottom']}[v]"
    )

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-framerate", str(FPS), "-t", f"{clip.duration:.3f}",
        "-i", str(clip.image),
        "-filter_complex", ";".join(filters),
        "-map", "[v]",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-pix_fmt", "yuv420p", "-r", str(FPS),
        str(out_path),
    ]
    _run(cmd, f"合成第 {index + 1} 段畫面")


def render_video(clips: list[Clip], out_path: Path, work_dir: Path,
                 config_video: dict, bgm_path: Path | None = None) -> float:
    """把所有片段合成一支完整短影音，回傳影片長度（秒）。"""
    check_ffmpeg()
    if not clips:
        raise RenderError("沒有任何畫面片段，無法合成影片。")

    work_dir.mkdir(parents=True, exist_ok=True)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    font = find_font(str(config_video.get("font_path", "") or ""))

    style = {
        "headline_size": int(config_video.get("headline_size", 82)),
        "headline_color": str(config_video.get("headline_color", "#FFE14D")),
        "headline_top": int(config_video.get("headline_top", 200)),
        "headline_chars": int(config_video.get("headline_chars_per_line", 9)),
        "subtitle_size": int(config_video.get("subtitle_size", 56)),
        "subtitle_bottom": int(config_video.get("subtitle_bottom", 260)),
        "subtitle_chars": int(config_video.get("subtitle_chars_per_line", 15)),
        "fg_size": int(config_video.get("product_image_size", 900)),
        "fg_top": int(config_video.get("product_image_top", 440)),
    }

    # --- 1. 逐段算圖 ---
    clip_paths: list[Path] = []
    for index, clip in enumerate(clips):
        clip_out = work_dir / f"clip_{index:02d}.mp4"
        _render_clip(clip, clip_out, work_dir, font, index, style)
        clip_paths.append(clip_out)
    log.info("已合成 %d 段畫面。", len(clip_paths))

    # --- 2. 接起來（影像） ---
    video_list = work_dir / "video_list.txt"
    video_list.write_text(
        "\n".join(f"file '{p.resolve().as_posix()}'" for p in clip_paths),
        encoding="utf-8",
    )
    merged_video = work_dir / "merged_video.mp4"
    _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(video_list),
          "-c", "copy", str(merged_video)], "串接畫面片段")

    # --- 3. 接起來（配音） ---
    audio_list = work_dir / "audio_list.txt"
    audio_list.write_text(
        "\n".join(f"file '{c.audio.resolve().as_posix()}'" for c in clips),
        encoding="utf-8",
    )
    merged_audio = work_dir / "merged_audio.m4a"
    _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(audio_list),
          "-c:a", "aac", "-b:a", "160k", str(merged_audio)], "串接配音")

    # --- 4. 影音合併（含背景音樂） ---
    if bgm_path and bgm_path.exists():
        bgm_volume = float(config_video.get("bgm_volume", 0.12))
        cmd = [
            "ffmpeg", "-y",
            "-i", str(merged_video),
            "-i", str(merged_audio),
            "-stream_loop", "-1", "-i", str(bgm_path),
            "-filter_complex",
            f"[2:a]volume={bgm_volume}[bg];"
            f"[1:a][bg]amix=inputs=2:duration=first:dropout_transition=0[a]",
            "-map", "0:v", "-map", "[a]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
            "-shortest", "-movflags", "+faststart",
            str(out_path),
        ]
        _run(cmd, "合併影像、配音與背景音樂")
    else:
        cmd = [
            "ffmpeg", "-y",
            "-i", str(merged_video), "-i", str(merged_audio),
            "-map", "0:v", "-map", "1:a",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
            "-shortest", "-movflags", "+faststart",
            str(out_path),
        ]
        _run(cmd, "合併影像與配音")

    from .tts import probe_duration
    duration = probe_duration(out_path)
    size_mb = out_path.stat().st_size / (1024 * 1024)
    log.info("影片完成：%s（%.1f 秒、%.1f MB）", out_path.name, duration, size_mb)
    return duration


def make_thumbnail(video_path: Path, out_path: Path, at_second: float = 1.0) -> bool:
    """從影片抓一張封面圖，發文時可以用。"""
    try:
        _run(["ffmpeg", "-y", "-ss", f"{at_second:.2f}", "-i", str(video_path),
              "-frames:v", "1", "-q:v", "2", str(out_path)], "擷取封面圖")
        return True
    except RenderError as exc:
        log.warning("擷取封面圖失敗：%s", exc)
        return False
