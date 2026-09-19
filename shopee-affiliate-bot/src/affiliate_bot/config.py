"""設定檔讀取。

設定分兩處：
  * config.yaml — 一般設定（可放進版本控制）
  * .env        — 機密金鑰（絕對不要放進版本控制）

config.yaml 裡任何字串寫成 ${VAR_NAME} 都會被 .env / 環境變數的值取代，
這樣金鑰就只會出現在 .env 一個地方。
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class ConfigError(Exception):
    """設定檔有問題時拋出，訊息會直接顯示給使用者看。"""


def load_dotenv(path: Path) -> None:
    """把 .env 的內容讀進 os.environ（不覆蓋已存在的環境變數）。"""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _expand(value: Any) -> Any:
    """遞迴把 ${VAR} 換成環境變數的值。找不到就換成空字串。"""
    if isinstance(value, str):
        return _ENV_PATTERN.sub(lambda m: os.environ.get(m.group(1), ""), value)
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand(v) for v in value]
    return value


@dataclass
class Paths:
    """專案用到的所有資料夾，集中管理。"""

    root: Path
    output: Path
    work: Path
    assets: Path
    logs: Path
    database: Path

    @classmethod
    def from_root(cls, root: Path, output_dir: str = "output") -> "Paths":
        output = root / output_dir
        return cls(
            root=root,
            output=output,
            work=root / ".work",
            assets=root / "assets",
            logs=root / "logs",
            database=root / "data" / "bot.db",
        )

    def ensure(self) -> None:
        for p in (self.output, self.work, self.logs, self.database.parent):
            p.mkdir(parents=True, exist_ok=True)


@dataclass
class Config:
    """整份設定，用 dict 存，透過 get() 取值。"""

    data: dict[str, Any]
    paths: Paths
    config_path: Path
    _missing_keys: list[str] = field(default_factory=list)

    def get(self, dotted_key: str, default: Any = None) -> Any:
        """用 "selection.min_commission_rate" 這種路徑取值。"""
        node: Any = self.data
        for part in dotted_key.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node if node is not None else default

    def require(self, dotted_key: str) -> Any:
        value = self.get(dotted_key)
        if value in (None, "", [], {}):
            raise ConfigError(
                f"設定檔缺少必要項目「{dotted_key}」。\n"
                f"請打開 {self.config_path} 補上，或執行：python run.py doctor 查看完整檢查結果。"
            )
        return value

    def secret(self, env_name: str) -> str:
        """讀取 .env 的機密值，沒有就回空字串（由 doctor 統一回報）。"""
        return os.environ.get(env_name, "").strip()

    def has_secret(self, env_name: str) -> bool:
        return bool(self.secret(env_name))


def load_config(root: Path, config_file: str = "config.yaml") -> Config:
    """讀取 .env + config.yaml，回傳 Config 物件。"""
    root = root.resolve()
    load_dotenv(root / ".env")

    config_path = root / config_file
    if not config_path.exists():
        example = root / "config.example.yaml"
        raise ConfigError(
            f"找不到設定檔 {config_path}。\n"
            f"請先複製範本：cp {example.name} {config_file}\n"
            f"（Windows 請用：copy {example.name} {config_file}）"
        )

    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(
            f"設定檔 {config_path} 格式有誤，YAML 無法解析。\n"
            f"常見原因是冒號後面少了空白、或縮排用到 Tab。\n原始錯誤：{exc}"
        ) from exc

    if not isinstance(raw, dict):
        raise ConfigError(f"設定檔 {config_path} 最外層必須是設定項目，不能是清單或單一數值。")

    data = _expand(raw)
    paths = Paths.from_root(root, data.get("general", {}).get("output_dir", "output"))
    paths.ensure()
    return Config(data=data, paths=paths, config_path=config_path)
