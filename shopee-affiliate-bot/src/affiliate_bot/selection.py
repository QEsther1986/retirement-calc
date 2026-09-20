"""自動選品：把候選商品篩選 + 評分 + 排序，挑出今天要做影片的那幾件。

預設的評分邏輯對應「利潤高、分潤高、銷售量高」這個選品規則：

  分數 = 單件佣金金額 × w1   ← 「利潤高」：你每賣一件實際入袋多少錢
       + 佣金率       × w2   ← 「分潤高」：抽成比例
       + 熱銷度       × w3   ← 「銷售量高」：市場已經驗證有人買
       + 評價         × w4   ← 保護帳號聲譽，避免推到爛東西
       + 折扣         × w5   ← 影片鉤子好不好寫
       + 價格帶       × w6   ← 預設關閉，見下方說明

為什麼「單件佣金金額」和「佣金率」要分開算：
    NT$299 的商品抽 15% = 你賺 45 元
    NT$1500 的商品抽 8% = 你賺 120 元
  後者分潤率低一半，但實際賺的多 2.7 倍。只看佣金率會讓你一直推小東西。

所有參數都在 config.yaml 的 selection 區塊，可以自己調。
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import Config
from .logging_setup import get_logger
from .models import Product

log = get_logger(__name__)


@dataclass
class ScoredProduct:
    product: Product
    score: float
    breakdown: dict[str, float]

    def explain(self) -> str:
        parts = "、".join(f"{k} {v:.2f}" for k, v in self.breakdown.items() if v > 0)
        return f"總分 {self.score:.2f}（{parts}）"


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _price_band_score(price: float, sweet_low: float, sweet_high: float) -> float:
    """價格落在甜蜜帶給滿分，離得越遠分數越低。"""
    if price <= 0:
        return 0.0
    if sweet_low <= price <= sweet_high:
        return 1.0
    if price < sweet_low:
        return _clamp01(price / sweet_low)
    # 高於甜蜜帶：每超過一倍就掉一半
    return _clamp01(sweet_high / price)


class ProductSelector:
    def __init__(self, config: Config):
        sel = config.get("selection", {}) or {}

        # --- 硬性門檻 ---
        self.min_commission_rate = float(sel.get("min_commission_rate", 0.05))
        self.min_commission_amount = float(sel.get("min_commission_amount", 30))
        self.min_sales = int(sel.get("min_sales", 500))
        self.min_rating = float(sel.get("min_rating", 4.0))
        self.min_price = float(sel.get("min_price", 100))
        self.max_price = float(sel.get("max_price", 5000))
        self.exclude_keywords = [k for k in (sel.get("exclude_keywords") or []) if k]

        # --- 正規化基準：達到這個數字就算滿分 ---
        self.commission_amount_full_mark = max(
            1.0, float(sel.get("commission_amount_full_mark", 150))
        )
        self.commission_rate_full_mark = max(
            0.01, float(sel.get("commission_rate_full_mark", 0.20))
        )
        self.sales_full_mark = max(1, int(sel.get("sales_full_mark", 10000)))
        self.price_sweet_low = float(sel.get("price_sweet_low", 250))
        self.price_sweet_high = float(sel.get("price_sweet_high", 1500))

        # --- 權重：預設對應「利潤高、分潤高、銷售量高」 ---
        weights = sel.get("weights", {}) or {}
        self.w_commission_amount = float(weights.get("commission_amount", 0.35))
        self.w_commission = float(weights.get("commission", 0.25))
        self.w_sales = float(weights.get("sales", 0.25))
        self.w_rating = float(weights.get("rating", 0.10))
        self.w_discount = float(weights.get("discount", 0.05))
        self.w_price = float(weights.get("price_band", 0.0))

    # ---------- 篩選 ----------

    def _rejection_reason(self, p: Product) -> str | None:
        if p.commission_rate < self.min_commission_rate:
            return (f"佣金率 {p.commission_rate * 100:.1f}% "
                    f"低於門檻 {self.min_commission_rate * 100:.1f}%")
        if p.estimated_commission < self.min_commission_amount:
            return (f"單件只賺 NT${p.estimated_commission:.0f}，"
                    f"低於門檻 NT${self.min_commission_amount:.0f}")
        if p.sales < self.min_sales:
            return f"銷量 {p.sales} 低於門檻 {self.min_sales}"
        if p.rating and p.rating < self.min_rating:
            return f"評分 {p.rating:.1f} 低於門檻 {self.min_rating}"
        if not (self.min_price <= p.price <= self.max_price):
            return f"價格 {p.price:.0f} 不在 {self.min_price:.0f}~{self.max_price:.0f} 範圍"
        if not p.image_urls:
            return "沒有商品圖片，無法做影片"
        if not p.affiliate_link:
            return "沒有分潤連結"
        lowered = p.name.lower()
        for word in self.exclude_keywords:
            if word.lower() in lowered:
                return f"商品名稱含排除關鍵字「{word}」"
        return None

    # ---------- 評分 ----------

    def _score(self, p: Product) -> ScoredProduct:
        # 利潤高：單件實際入袋金額
        amount_score = _clamp01(p.estimated_commission / self.commission_amount_full_mark)
        # 分潤高：抽成比例
        commission_score = _clamp01(p.commission_rate / self.commission_rate_full_mark)
        # 銷售量高：市場已驗證
        sales_score = _clamp01(p.sales / self.sales_full_mark)

        rating_score = _clamp01((p.rating - 3.0) / 2.0) if p.rating else 0.5
        discount_score = _clamp01(p.discount_rate / 0.60)   # 打四折視為滿分
        price_score = _price_band_score(p.price, self.price_sweet_low, self.price_sweet_high)

        breakdown = {
            "單件利潤": amount_score * self.w_commission_amount,
            "分潤率": commission_score * self.w_commission,
            "熱銷": sales_score * self.w_sales,
            "評價": rating_score * self.w_rating,
            "折扣": discount_score * self.w_discount,
            "價格帶": price_score * self.w_price,
        }
        return ScoredProduct(product=p, score=sum(breakdown.values()), breakdown=breakdown)

    # ---------- 對外入口 ----------

    def select(self, products: list[Product], count: int,
               exclude_ids: set[str] | None = None) -> list[ScoredProduct]:
        exclude_ids = exclude_ids or set()
        kept: list[ScoredProduct] = []
        rejected = 0

        for p in products:
            if p.item_id in exclude_ids:
                log.debug("略過 %s：最近已經做過影片。", p.name)
                rejected += 1
                continue
            reason = self._rejection_reason(p)
            if reason:
                log.debug("略過 %s：%s", p.name, reason)
                rejected += 1
                continue
            kept.append(self._score(p))

        kept.sort(key=lambda s: s.score, reverse=True)
        log.info("選品完成：候選 %d 件、通過篩選 %d 件、淘汰 %d 件，取前 %d 件製作影片。",
                 len(products), len(kept), rejected, min(count, len(kept)))

        for i, item in enumerate(kept[:count], start=1):
            log.info("  第%d名 %s", i, item.product.summary())
            log.info("        %s", item.explain())

        return kept[:count]
