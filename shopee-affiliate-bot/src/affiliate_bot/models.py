"""跨模組共用的資料結構。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Product:
    """一件候選商品。不同來源（蝦皮 API / CSV / 示範資料）都轉成這個格式。"""

    item_id: str
    name: str
    price: float
    image_urls: list[str]
    affiliate_link: str
    commission_rate: float = 0.0     # 0.10 代表 10%
    sales: int = 0                   # 近期銷量
    rating: float = 0.0              # 0~5
    discount_rate: float = 0.0       # 0.30 代表打七折
    shop_name: str = ""
    category: str = ""
    product_link: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def estimated_commission(self) -> float:
        """單件預估佣金（台幣）。"""
        return round(self.price * self.commission_rate, 2)

    def summary(self) -> str:
        return (
            f"{self.name}｜單件賺 NT${self.estimated_commission:,.0f}"
            f"（售價 NT${self.price:,.0f} × {self.commission_rate * 100:.1f}%）"
            f"｜銷量 {self.sales:,}｜評分 {self.rating:.1f}"
        )


@dataclass
class ScriptSegment:
    """腳本的一句話，對應影片中的一個畫面。"""

    text: str          # 旁白/字幕文字
    on_screen: str     # 畫面上的大字標題（可為空）
    seconds: float = 0.0   # 實際配音長度，由 TTS 產生後回填


@dataclass
class VideoScript:
    """一支短影音的完整腳本。"""

    hook: str                     # 前 3 秒的鉤子
    segments: list[ScriptSegment]
    caption: str                  # 貼文文案
    hashtags: list[str]
    cta: str                      # 結尾行動呼籲

    def full_narration(self) -> str:
        return " ".join(seg.text for seg in self.segments)
