"""環境健檢：一次檢查所有東西有沒有裝好、設定對不對。

執行：python run.py doctor

設計原則是「不要只說錯了，要說怎麼修」。每一個檢查失敗都會附上下一步該做什麼。
"""

from __future__ import annotations

import importlib.util
import platform
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from .config import Config, ConfigError

OK = "✅"
WARN = "⚠️ "
FAIL = "❌"


@dataclass
class Check:
    level: str      # OK / WARN / FAIL
    title: str
    detail: str = ""

    def render(self) -> str:
        line = f"{self.level} {self.title}"
        if self.detail:
            indented = "\n".join(f"      {l}" for l in self.detail.splitlines())
            line += f"\n{indented}"
        return line


def _check_python() -> Check:
    version = sys.version_info
    if version >= (3, 10):
        return Check(OK, f"Python 版本 {version.major}.{version.minor}.{version.micro}")
    return Check(FAIL, f"Python 版本太舊（{version.major}.{version.minor}）",
                 "請安裝 Python 3.10 以上版本：https://www.python.org/downloads/")


def _check_packages() -> list[Check]:
    needed = {
        "anthropic": "產生腳本文案（pip install anthropic）",
        "requests": "呼叫各平台 API（pip install requests）",
        "yaml": "讀取設定檔（pip install PyYAML）",
        "edge_tts": "中文配音（pip install edge-tts）",
        "PIL": "圖片處理（pip install Pillow）",
    }
    checks = []
    missing = []
    for module, why in needed.items():
        if importlib.util.find_spec(module) is None:
            missing.append(module)
            checks.append(Check(FAIL, f"缺少套件 {module}", why))
    if not missing:
        checks.append(Check(OK, "Python 套件齊全"))
    else:
        checks.append(Check(FAIL, "請一次補齊所有套件",
                            "pip install -r requirements.txt"))
    return checks


def _check_ffmpeg() -> list[Check]:
    checks = []
    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool):
            checks.append(Check(OK, f"{tool} 已安裝"))
        else:
            system = platform.system()
            how = {
                "Darwin": "brew install ffmpeg",
                "Windows": "winget install Gyan.FFmpeg（裝完要重開終端機）",
            }.get(system, "sudo apt update && sudo apt install -y ffmpeg")
            checks.append(Check(FAIL, f"找不到 {tool}（沒有它就不能做影片）", how))
    return checks


def _check_font(config: Config) -> Check:
    from .media.render import RenderError, find_font
    try:
        font = find_font(str(config.get("video.font_path", "") or ""))
        return Check(OK, "中文字型可用", font)
    except RenderError as exc:
        return Check(FAIL, "找不到中文字型（字幕會變成空白方塊）", str(exc))


def _check_source(config: Config) -> list[Check]:
    mode = str(config.get("source.mode", "demo")).lower()
    checks = [Check(OK, f"商品來源模式：{mode}")]

    if mode == "shopee":
        for key in ("SHOPEE_APP_ID", "SHOPEE_APP_SECRET"):
            if config.has_secret(key):
                checks.append(Check(OK, f".env 已設定 {key}"))
            else:
                checks.append(Check(FAIL, f".env 缺少 {key}",
                                    "請到蝦皮聯盟後台申請開放 API，或把 source.mode 改成 csv"))
    elif mode == "csv":
        path = (config.paths.root / str(config.get("source.csv.path", "products.csv"))).resolve()
        if path.exists():
            checks.append(Check(OK, f"商品清單檔存在：{path.name}"))
        else:
            checks.append(Check(FAIL, f"找不到商品清單檔 {path.name}",
                                "請複製 products.example.csv 並改名，填入你自己的商品"))
    else:
        checks.append(Check(WARN, "目前是示範模式（demo）",
                            "用的是假商品資料，連結不會有佣金。\n"
                            "測試沒問題後，請把 config.yaml 的 source.mode 改成 csv 或 shopee。"))
    return checks


def _check_claude(config: Config) -> Check:
    if config.has_secret("ANTHROPIC_API_KEY"):
        return Check(OK, "Claude API 金鑰已設定", f"使用模型：{config.get('content.model')}")
    return Check(WARN, "沒有設定 ANTHROPIC_API_KEY（會改用內建樣板文案）",
                 "想要 AI 幫你寫腳本的話，到 https://console.anthropic.com 申請金鑰，\n"
                 "然後填進 .env 的 ANTHROPIC_API_KEY=")


def _check_publishers(config: Config) -> list[Check]:
    checks: list[Check] = []
    publish_cfg = config.get("publish", {}) or {}
    enabled = [name for name in ("manual", "facebook", "instagram", "tiktok")
               if (publish_cfg.get(name) or {}).get("enabled")]

    if not enabled:
        checks.append(Check(WARN, "沒有啟用任何發佈平台",
                            "影片只會存在 output 資料夾。至少建議先啟用 manual。"))
        return checks

    checks.append(Check(OK, f"已啟用的發佈平台：{'、'.join(enabled)}"))

    if config.get("publish.require_approval", True):
        checks.append(Check(OK, "已開啟「發佈前人工審核」（建議保持開啟）"))
    else:
        checks.append(Check(WARN, "已關閉人工審核，影片會直接發出去",
                            "剛開始建議開著，確認文案品質沒問題再關掉。"))

    required_env = {
        "facebook": [("page_id_env", "FB_PAGE_ID"), ("access_token_env", "FB_PAGE_ACCESS_TOKEN")],
        "instagram": [("user_id_env", "IG_USER_ID"), ("access_token_env", "IG_ACCESS_TOKEN")],
        "tiktok": [("client_key_env", "TIKTOK_CLIENT_KEY"),
                   ("client_secret_env", "TIKTOK_CLIENT_SECRET"),
                   ("refresh_token_env", "TIKTOK_REFRESH_TOKEN")],
    }

    for platform_name in enabled:
        if platform_name == "manual":
            continue
        section = publish_cfg.get(platform_name) or {}
        accounts = section.get("accounts") or []
        if not accounts:
            checks.append(Check(FAIL, f"{platform_name} 已啟用但沒有設定任何帳號",
                                f"請在 config.yaml 的 publish.{platform_name}.accounts 底下加上帳號"))
            continue

        for account in accounts:
            label = account.get("label", "未命名")
            for setting_key, default_env in required_env[platform_name]:
                env_name = account.get(setting_key, default_env)
                if config.has_secret(env_name):
                    checks.append(Check(OK, f"{platform_name}／{label}：{env_name} 已設定"))
                else:
                    checks.append(Check(FAIL, f"{platform_name}／{label}：.env 缺少 {env_name}",
                                        "請參考 docs/04-申請各平台API.md 取得這組金鑰"))

        if platform_name == "instagram" and not section.get("video_url_base"):
            checks.append(Check(FAIL, "Instagram 缺少 video_url_base",
                                "Instagram API 只能從公開網址抓影片。\n"
                                "請見 docs/04-申請各平台API.md，或改用 manual 手動發 IG。"))

    return checks


def run_doctor(config: Config | None, root: Path) -> int:
    """執行所有檢查，回傳 exit code（0 = 沒有致命問題）。"""
    print()
    print("=" * 56)
    print("  蝦皮聯盟自動化工具 — 環境健檢")
    print("=" * 56)
    print()

    checks: list[Check] = [_check_python()]
    checks += _check_packages()
    checks += _check_ffmpeg()

    if config is None:
        checks.append(Check(FAIL, "還沒有設定檔 config.yaml",
                            f"請執行：cp {root / 'config.example.yaml'} {root / 'config.yaml'}"))
    else:
        checks.append(Check(OK, f"設定檔已讀取：{config.config_path.name}"))
        checks.append(_check_font(config))
        checks += _check_source(config)
        checks.append(_check_claude(config))
        checks += _check_publishers(config)

    for check in checks:
        print(check.render())

    failures = sum(1 for c in checks if c.level == FAIL)
    warnings = sum(1 for c in checks if c.level == WARN)

    print()
    print("-" * 56)
    if failures:
        print(f"{FAIL} 有 {failures} 個問題必須先解決，程式現在還不能正常運作。")
        print("   請照上面每一項的說明處理，然後再執行一次 doctor。")
    elif warnings:
        print(f"{WARN}有 {warnings} 個提醒，但程式可以跑了。")
        print("   下一步：python run.py run")
    else:
        print(f"{OK} 全部檢查通過，可以開始了！")
        print("   下一步：python run.py run")
    print("-" * 56)
    print()
    return 1 if failures else 0


def safe_load_config(root: Path) -> Config | None:
    try:
        from .config import load_config
        return load_config(root)
    except ConfigError:
        return None
