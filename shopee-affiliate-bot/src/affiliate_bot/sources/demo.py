"""示範用的假商品資料。

目的：讓你在還沒申請到任何 API 金鑰之前，就能把整條流程（選品→腳本→配音→
影片→（模擬）發佈）完整跑一次，確認電腦環境沒問題。

示範圖片是程式自己在本機畫出來的，所以完全不需要網路也能測試。

注意：這裡的商品連結是假的，不會有任何佣金，也不要真的發到社群平台。
"""

from __future__ import annotations

from pathlib import Path

from ..logging_setup import get_logger
from ..models import Product
from .base import ProductSource

log = get_logger(__name__)

_DEMO_PRODUCTS = [
    {
        "item_id": "demo-001",
        "name": "無線藍牙耳機 降噪入耳式 超長續航",
        "price": 799.0,
        "commission_rate": 0.12,
        "sales": 8420,
        "rating": 4.8,
        "discount_rate": 0.45,
        "category": "3C配件",
        "colors": [(38, 70, 118), (24, 44, 78), (60, 96, 150)],
    },
    {
        "item_id": "demo-002",
        "name": "不鏽鋼保溫瓶 316 大容量 附提繩",
        "price": 459.0,
        "commission_rate": 0.10,
        "sales": 3210,
        "rating": 4.7,
        "discount_rate": 0.30,
        "category": "居家生活",
        "colors": [(150, 90, 60), (110, 64, 42), (186, 122, 84)],
    },
    {
        "item_id": "demo-003",
        "name": "折疊收納箱 車用後車廂整理箱 大容量",
        "price": 299.0,
        "commission_rate": 0.15,
        "sales": 12980,
        "rating": 4.6,
        "discount_rate": 0.50,
        "category": "居家生活",
        "colors": [(70, 120, 90), (48, 88, 66), (98, 152, 118)],
    },
    {
        "item_id": "demo-004",
        "name": "手持掛燙機 蒸氣熨斗 旅行便攜",
        "price": 690.0,
        "commission_rate": 0.11,
        "sales": 5640,
        "rating": 4.5,
        "discount_rate": 0.38,
        "category": "家電",
        "colors": [(120, 70, 130), (88, 50, 98), (152, 100, 166)],
    },
    {
        "item_id": "demo-005",
        "name": "LED 護眼檯燈 無藍光 三段調光 USB 供電",
        "price": 520.0,
        "commission_rate": 0.13,
        "sales": 7150,
        "rating": 4.7,
        "discount_rate": 0.42,
        "category": "居家生活",
        "colors": [(180, 150, 60), (140, 114, 40), (208, 182, 96)],
    },
]


def _make_demo_images(item_id: str, colors: list[tuple[int, int, int]],
                      dest_dir: Path) -> list[str]:
    """在本機畫幾張色塊圖當成商品圖，不需要網路。"""
    dest_dir.mkdir(parents=True, exist_ok=True)
    paths: list[str] = []

    try:
        from PIL import Image, ImageDraw
    except ImportError:
        log.error("找不到 Pillow 套件，無法產生示範圖片。請執行 pip install -r requirements.txt")
        return []

    for index, color in enumerate(colors):
        target = dest_dir / f"{item_id}_{index}.jpg"
        if not target.exists():
            image = Image.new("RGB", (900, 900), color)
            draw = ImageDraw.Draw(image)
            # 畫幾個簡單的幾何形狀，讓畫面不要只是一片純色。
            lighter = tuple(min(255, c + 55) for c in color)
            draw.rounded_rectangle((140, 140, 760, 760), radius=60, fill=lighter)
            draw.ellipse((260, 260, 640, 640), fill=color)
            draw.rounded_rectangle((330, 330, 570, 570), radius=30, fill=lighter)
            image.save(target, quality=88)
        paths.append(str(target))

    return paths


class DemoSource(ProductSource):
    name = "demo（示範假資料）"

    def fetch(self, limit: int) -> list[Product]:
        image_dir = self.config.paths.work / "demo_images"
        products = []

        for row in _DEMO_PRODUCTS[:limit]:
            images = _make_demo_images(row["item_id"], row["colors"], image_dir)
            if not images:
                continue
            products.append(
                Product(
                    item_id=row["item_id"],
                    name=row["name"],
                    price=row["price"],
                    image_urls=images,
                    # 假連結，僅供流程測試，不會有任何佣金。
                    affiliate_link=f"https://example.invalid/demo/{row['item_id']}",
                    commission_rate=row["commission_rate"],
                    sales=row["sales"],
                    rating=row["rating"],
                    discount_rate=row["discount_rate"],
                    shop_name="示範商店",
                    category=row["category"],
                    raw={k: v for k, v in row.items() if k != "colors"},
                )
            )

        log.info("示範模式：準備了 %d 件假商品（圖片是本機產生的，不需要網路）。", len(products))
        return products
