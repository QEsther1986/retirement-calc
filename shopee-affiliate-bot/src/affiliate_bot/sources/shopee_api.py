"""蝦皮聯盟開放 API（Shopee Affiliate Open API）串接。

【重要說明，請務必先讀】
蝦皮的聯盟開放 API 不是每個分潤帳戶都自動開通，通常要在聯盟後台另外申請
「Open API / App ID」。申請通過後你會拿到兩組值：
    App ID      -> 填在 .env 的 SHOPEE_APP_ID
    App Secret  -> 填在 .env 的 SHOPEE_APP_SECRET

如果你申請不到、或還在審核中，請把 config.yaml 的 source.mode 改成 csv，
改用「手動整理商品清單」的方式，一樣可以跑完整條自動化流程。

【技術細節】
* 端點是 GraphQL，預設 https://open-api.affiliate.shopee.tw/graphql
* 驗證方式是在 Authorization 標頭放一段 SHA256 簽章：
      Signature = SHA256(AppId + Timestamp + RequestBody + AppSecret)
* 蝦皮偶爾會調整欄位名稱。本模組刻意寫得「寬容」：欄位讀不到就給預設值，
  並且整段查詢字串可以在 config.yaml 裡覆寫（source.shopee.query），
  這樣萬一官方改版，你不用改程式、只要改設定檔。
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any

import requests

from ..config import ConfigError
from ..logging_setup import get_logger
from ..models import Product
from .base import ProductSource

log = get_logger(__name__)

DEFAULT_ENDPOINT = "https://open-api.affiliate.shopee.tw/graphql"

# 預設查詢：依條件抓商品優惠。若官方改版，可在 config.yaml 覆寫。
DEFAULT_QUERY = """
query ProductOffer($page: Int, $limit: Int, $keyword: String, $sortType: Int) {
  productOfferV2(page: $page, limit: $limit, keyword: $keyword, sortType: $sortType) {
    nodes {
      itemId
      productName
      commissionRate
      price
      sales
      imageUrl
      shopName
      productLink
      offerLink
      ratingStar
      priceDiscountRate
    }
    pageInfo { page limit hasNextPage }
  }
}
""".strip()


def _sign(app_id: str, secret: str, payload: str, timestamp: int) -> str:
    """產生蝦皮要求的 SHA256 簽章。"""
    base = f"{app_id}{timestamp}{payload}{secret}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int = 0) -> int:
    return int(_as_float(value, default))


class ShopeeApiSource(ProductSource):
    name = "shopee（蝦皮聯盟開放 API）"

    def __init__(self, config):
        super().__init__(config)
        self.app_id = config.secret("SHOPEE_APP_ID")
        self.app_secret = config.secret("SHOPEE_APP_SECRET")
        self.endpoint = config.get("source.shopee.endpoint", DEFAULT_ENDPOINT)
        self.query = config.get("source.shopee.query", DEFAULT_QUERY)
        self.keywords: list[str] = list(config.get("source.shopee.keywords", []) or [])
        self.sort_type = int(config.get("source.shopee.sort_type", 2))
        self.sub_id = config.get("source.shopee.sub_id", "") or ""
        self.timeout = int(config.get("source.shopee.timeout_seconds", 30))

        if not self.app_id or not self.app_secret:
            raise ConfigError(
                "你把 source.mode 設成 shopee，但 .env 裡找不到 SHOPEE_APP_ID 或 "
                "SHOPEE_APP_SECRET。\n"
                "請到蝦皮聯盟後台申請開放 API 金鑰後填入 .env，\n"
                "或先把 config.yaml 的 source.mode 改成 csv 或 demo。"
            )

    # ---------- 底層請求 ----------

    def _post(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps({"query": query, "variables": variables},
                          separators=(",", ":"), ensure_ascii=False)
        timestamp = int(time.time())
        signature = _sign(self.app_id, self.app_secret, body, timestamp)
        headers = {
            "Content-Type": "application/json",
            "Authorization": (
                f"SHA256 Credential={self.app_id}, "
                f"Timestamp={timestamp}, Signature={signature}"
            ),
        }
        try:
            resp = requests.post(self.endpoint, data=body.encode("utf-8"),
                                 headers=headers, timeout=self.timeout)
        except requests.RequestException as exc:
            raise ConfigError(
                f"連線蝦皮 API 失敗：{exc}\n請檢查網路，或稍後再試。"
            ) from exc

        if resp.status_code == 401 or resp.status_code == 403:
            raise ConfigError(
                f"蝦皮 API 回應 {resp.status_code}（驗證失敗）。\n"
                "最常見的三個原因：\n"
                "  1. .env 的 SHOPEE_APP_ID / SHOPEE_APP_SECRET 打錯或多了空白\n"
                "  2. 你的聯盟帳號還沒開通開放 API 權限\n"
                "  3. 電腦時間不準（簽章有時效），請校正系統時間\n"
                f"蝦皮原始回應：{resp.text[:400]}"
            )
        if resp.status_code >= 400:
            raise ConfigError(
                f"蝦皮 API 回應 HTTP {resp.status_code}：{resp.text[:400]}"
            )

        try:
            data = resp.json()
        except ValueError as exc:
            raise ConfigError(f"蝦皮 API 回傳的不是 JSON：{resp.text[:400]}") from exc

        if data.get("errors"):
            raise ConfigError(
                "蝦皮 API 回報查詢錯誤（通常代表官方改了欄位名稱）：\n"
                f"{json.dumps(data['errors'], ensure_ascii=False)[:600]}\n"
                "你可以在 config.yaml 的 source.shopee.query 貼上官方最新的查詢語法來修正。"
            )
        return data.get("data") or {}

    # ---------- 轉成 Product ----------

    def _to_product(self, node: dict[str, Any]) -> Product | None:
        item_id = str(node.get("itemId") or node.get("item_id") or "").strip()
        name = str(node.get("productName") or node.get("name") or "").strip()
        if not item_id or not name:
            return None

        image = node.get("imageUrl") or node.get("image") or ""
        images = [image] if isinstance(image, str) and image else []
        if isinstance(node.get("imageUrls"), list):
            images = [str(u) for u in node["imageUrls"] if u]

        # 佣金率蝦皮有時給 0.12、有時給 12，這裡統一成小數。
        commission = _as_float(node.get("commissionRate"))
        if commission > 1:
            commission = commission / 100.0

        discount = _as_float(node.get("priceDiscountRate"))
        if discount > 1:
            discount = discount / 100.0

        link = str(node.get("offerLink") or node.get("productLink") or "")
        return Product(
            item_id=item_id,
            name=name,
            price=_as_float(node.get("price")),
            image_urls=images,
            affiliate_link=link,
            commission_rate=commission,
            sales=_as_int(node.get("sales")),
            rating=_as_float(node.get("ratingStar")),
            discount_rate=discount,
            shop_name=str(node.get("shopName") or ""),
            product_link=str(node.get("productLink") or ""),
            raw=node,
        )

    def fetch(self, limit: int) -> list[Product]:
        keywords = self.keywords or [""]
        per_keyword = max(1, limit // len(keywords) + 1)
        collected: dict[str, Product] = {}

        for keyword in keywords:
            variables = {
                "page": 1,
                "limit": per_keyword,
                "keyword": keyword or None,
                "sortType": self.sort_type,
            }
            log.info("向蝦皮查詢商品…關鍵字：%s", keyword or "（不指定）")
            data = self._post(self.query, variables)

            # 兼容 productOfferV2 / productOffer 兩種回傳鍵名
            block = data.get("productOfferV2") or data.get("productOffer") or {}
            nodes = block.get("nodes") or []
            if not nodes:
                log.warning("關鍵字「%s」沒有查到商品。", keyword or "（不指定）")
            for node in nodes:
                product = self._to_product(node)
                if product and product.item_id not in collected:
                    collected[product.item_id] = product
            time.sleep(0.5)  # 對 API 友善一點，避免被限流

        log.info("蝦皮 API 共取得 %d 件候選商品。", len(collected))
        return list(collected.values())[: limit * 3]
