"""從 CSV 檔讀商品清單。

這是「還沒申請到蝦皮開放 API」時的正式作法，而且很多人長期都用這種方式：
你自己在蝦皮聯盟後台挑好商品、產生分潤連結，貼進一個 CSV 檔，
剩下的（寫腳本、配音、做影片、發佈）全部自動。

CSV 欄位（第一列是標題，順序不拘，缺的欄位會用預設值）：
    item_id          必填，自己編也行，例如 a001
    name             必填，商品名稱
    price            必填，價格數字，例如 799
    affiliate_link   必填，你的蝦皮分潤連結
    image_urls       必填，商品圖網址，多張用 | 分隔
    commission_rate  選填，0.12 代表 12%
    sales            選填，銷量
    rating           選填，評分 0~5
    discount_rate    選填，0.45 代表打 55 折
    category         選填，分類

範例見 products.example.csv。
"""

from __future__ import annotations

import csv
from pathlib import Path

from ..config import ConfigError
from ..logging_setup import get_logger
from ..models import Product
from .base import ProductSource

log = get_logger(__name__)

REQUIRED = ("item_id", "name", "price", "affiliate_link", "image_urls")


def _num(row: dict[str, str], key: str, default: float = 0.0) -> float:
    raw = (row.get(key) or "").strip().replace(",", "").replace("%", "")
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        log.warning("CSV 欄位 %s 的值「%s」不是數字，已當成 %s 處理。", key, raw, default)
        return default


class CsvSource(ProductSource):
    name = "csv（自行整理的商品清單）"

    def __init__(self, config):
        super().__init__(config)
        rel = config.get("source.csv.path", "products.csv")
        self.csv_path: Path = (config.paths.root / rel).resolve()

    def fetch(self, limit: int) -> list[Product]:
        if not self.csv_path.exists():
            raise ConfigError(
                f"找不到商品清單檔 {self.csv_path}。\n"
                "請複製範本並填入你自己的商品：\n"
                f"    cp products.example.csv {self.csv_path.name}\n"
                "每一列填一件商品，記得把 affiliate_link 換成你自己的蝦皮分潤連結。"
            )

        products: list[Product] = []
        with self.csv_path.open("r", encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            missing = [c for c in REQUIRED if c not in (reader.fieldnames or [])]
            if missing:
                raise ConfigError(
                    f"{self.csv_path.name} 缺少必要欄位：{'、'.join(missing)}\n"
                    f"第一列必須包含這些欄位名稱：{'、'.join(REQUIRED)}"
                )

            for line_no, row in enumerate(reader, start=2):
                item_id = (row.get("item_id") or "").strip()
                name = (row.get("name") or "").strip()
                link = (row.get("affiliate_link") or "").strip()
                images = [u.strip() for u in (row.get("image_urls") or "").split("|") if u.strip()]

                if not (item_id and name and link and images):
                    log.warning("第 %d 列資料不完整（缺 item_id/name/affiliate_link/image_urls），已略過。",
                                line_no)
                    continue

                commission = _num(row, "commission_rate")
                if commission > 1:
                    commission /= 100.0
                discount = _num(row, "discount_rate")
                if discount > 1:
                    discount /= 100.0

                products.append(
                    Product(
                        item_id=item_id,
                        name=name,
                        price=_num(row, "price"),
                        image_urls=images,
                        affiliate_link=link,
                        commission_rate=commission,
                        sales=int(_num(row, "sales")),
                        rating=_num(row, "rating"),
                        discount_rate=discount,
                        category=(row.get("category") or "").strip(),
                        raw=dict(row),
                    )
                )

        log.info("從 %s 讀到 %d 件商品。", self.csv_path.name, len(products))
        if not products:
            raise ConfigError(f"{self.csv_path.name} 裡沒有任何有效商品，請檢查內容。")
        return products
