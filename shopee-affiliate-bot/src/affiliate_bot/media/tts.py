"""中文配音（Text-To-Speech）。

用微軟 Edge 的免費語音服務（edge-tts 套件），不需要註冊、不需要金鑰，
音質對短影音來說相當夠用。台灣中文可用的聲音：
    zh-TW-HsiaoChenNeural  女聲，自然親切（預設）
    zh-TW-HsiaoYuNeural    女聲，較年輕
    zh-TW-YunJheNeural     男聲，沉穩

如果配音服務連不上（例如沒網路），會退而產生等長的「靜音」音軌，
讓影片還是做得出來，你可以之後自己配音；同時會在日誌警告你。
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

from ..logging_setup import get_logger

log = get_logger(__name__)


def probe_duration(path: Path) -> float:
    """用 ffprobe 取得音訊/影片長度（秒）。"""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, check=True,
        )
        return float(out.stdout.strip())
    except (subprocess.CalledProcessError, ValueError, FileNotFoundError):
        return 0.0


def _estimate_seconds(text: str) -> float:
    """中文語音大約每秒 4.5 個字，用來估算靜音備援的長度。"""
    return max(1.5, len(text) / 4.5)


def _write_silence(path: Path, seconds: float) -> bool:
    # 不指定 -c:a，讓 ffmpeg 依副檔名挑對應的編碼器
    # （寫 .mp3 就用 mp3 編碼、寫 .m4a 就用 aac）。
    # 之前寫死 aac 會導致存成 .mp3 時失敗。
    try:
        result = subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i",
             "anullsrc=channel_layout=mono:sample_rate=24000",
             "-t", f"{seconds:.2f}", "-b:a", "96k", str(path)],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            log.debug("產生靜音音軌失敗：%s", result.stderr.strip()[-300:])
            return False
        return path.exists() and path.stat().st_size > 0
    except FileNotFoundError:
        return False


async def _synthesize(text: str, out_path: Path, voice: str, rate: str, volume: str) -> None:
    import edge_tts

    communicate = edge_tts.Communicate(text=text, voice=voice, rate=rate, volume=volume)
    await communicate.save(str(out_path))


def synthesize(text: str, out_path: Path, voice: str = "zh-TW-HsiaoChenNeural",
               rate: str = "+8%", volume: str = "+0%") -> float:
    """把文字轉成語音檔，回傳音檔長度（秒）。失敗時回傳靜音檔的長度。"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    text = text.strip()
    if not text:
        return 0.0

    try:
        asyncio.run(_synthesize(text, out_path, voice, rate, volume))
        duration = probe_duration(out_path)
        if duration > 0:
            return duration
        log.warning("配音檔產生了但長度為 0，改用靜音替代。")
    except ImportError:
        log.warning("找不到 edge-tts 套件，改用靜音音軌。請執行 pip install -r requirements.txt")
    except Exception as exc:  # edge-tts 的例外型別不固定，統一攔截避免整批中斷
        log.warning("配音失敗（%s），改用靜音音軌。這支影片需要你自己補配音。", exc)

    fallback_seconds = _estimate_seconds(text)
    if _write_silence(out_path, fallback_seconds):
        return fallback_seconds
    log.error("連靜音音軌都產生失敗，請確認 ffmpeg 是否安裝成功。")
    return 0.0


def pad_audio(src: Path, dest: Path, pad_seconds: float) -> float:
    """在音檔尾端補一段靜音（讓畫面停留一下，不會切太快），回傳新長度。"""
    if pad_seconds <= 0:
        dest.write_bytes(src.read_bytes())
        return probe_duration(dest)
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(src),
             "-af", f"apad=pad_dur={pad_seconds:.2f}",
             "-c:a", "aac", "-b:a", "128k", str(dest)],
            capture_output=True, check=True,
        )
        return probe_duration(dest)
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        log.warning("補靜音失敗（%s），沿用原始音檔。", exc)
        dest.write_bytes(src.read_bytes())
        return probe_duration(dest)
