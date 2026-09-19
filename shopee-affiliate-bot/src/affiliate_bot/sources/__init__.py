"""商品來源：決定「要推薦哪些商品」的原始資料從哪裡來。

目前支援三種，在 config.yaml 的 source.mode 切換：
  * demo   — 內建假資料，沒有任何金鑰也能跑完整流程（第一次測試用這個）
  * csv    — 你自己從蝦皮後台匯出/手動整理的 CSV
  * shopee — 蝦皮聯盟開放 API（需要申請 App ID / Secret）
"""

from __future__ import annotations

from ..config import Config, ConfigError
from .base import ProductSource
from .csv_source import CsvSource
from .demo import DemoSource
from .shopee_api import ShopeeApiSource

__all__ = ["ProductSource", "CsvSource", "DemoSource", "ShopeeApiSource", "build_source"]


def build_source(config: Config) -> ProductSource:
    mode = str(config.get("source.mode", "demo")).lower()
    if mode == "demo":
        return DemoSource(config)
    if mode == "csv":
        return CsvSource(config)
    if mode == "shopee":
        return ShopeeApiSource(config)
    raise ConfigError(
        f"config.yaml 的 source.mode 寫成「{mode}」，但只接受 demo / csv / shopee 三種。"
    )
