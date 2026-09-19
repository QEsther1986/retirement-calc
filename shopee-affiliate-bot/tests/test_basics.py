"""基本邏輯測試（不需要網路、不需要任何 API 金鑰）。

執行方式：
    python tests/test_basics.py

這些測試在你改設定、改程式之後可以拿來確認沒有把東西弄壞。
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from affiliate_bot.config import load_config  # noqa: E402
from affiliate_bot.models import Product, ScriptSegment, VideoScript  # noqa: E402
from affiliate_bot.pipeline import _safe_name  # noqa: E402
from affiliate_bot.publish.base import build_caption  # noqa: E402
from affiliate_bot.selection import ProductSelector  # noqa: E402
from affiliate_bot.sources.csv_source import CsvSource  # noqa: E402

PASSED = 0
FAILED = 0


def check(condition: bool, label: str) -> None:
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  ✅ {label}")
    else:
        FAILED += 1
        print(f"  ❌ {label}")


def make_product(**overrides) -> Product:
    base = dict(
        item_id="t1", name="測試商品", price=500.0,
        image_urls=["https://example.com/a.jpg"],
        affiliate_link="https://example.com/link",
        commission_rate=0.10, sales=1000, rating=4.5, discount_rate=0.30,
    )
    base.update(overrides)
    return Product(**base)


def _config_in(tmp: Path, yaml_text: str):
    (tmp / "config.yaml").write_text(yaml_text, encoding="utf-8")
    return load_config(tmp)


def test_config() -> None:
    print("\n[設定檔]")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        (tmp / ".env").write_text("MY_SECRET=abc123\n", encoding="utf-8")
        config = _config_in(tmp, "general:\n  videos_per_run: 7\nsource:\n  mode: demo\n")

        check(config.get("general.videos_per_run") == 7, "能用點路徑讀巢狀設定")
        check(config.get("general.nothing", "預設") == "預設", "讀不到的鍵會回傳預設值")
        check(config.secret("MY_SECRET") == "abc123", ".env 的值讀得到")
        check(config.secret("NOT_SET") == "", "沒設定的金鑰回傳空字串")
        check(config.paths.output.exists(), "輸出資料夾會自動建立")


def test_selector_filters() -> None:
    print("\n[選品：硬性門檻]")
    with tempfile.TemporaryDirectory() as td:
        config = _config_in(Path(td), """
selection:
  min_commission_rate: 0.08
  min_sales: 500
  min_rating: 4.2
  min_price: 200
  max_price: 2000
  exclude_keywords: [二手, 藥]
""")
        selector = ProductSelector(config)

        check(len(selector.select([make_product()], 5)) == 1, "正常商品會通過")
        check(len(selector.select([make_product(commission_rate=0.03)], 5)) == 0, "佣金太低被淘汰")
        check(len(selector.select([make_product(sales=100)], 5)) == 0, "銷量太低被淘汰")
        check(len(selector.select([make_product(rating=3.9)], 5)) == 0, "評分太低被淘汰")
        check(len(selector.select([make_product(price=50)], 5)) == 0, "價格太低被淘汰")
        check(len(selector.select([make_product(price=5000)], 5)) == 0, "價格太高被淘汰")
        check(len(selector.select([make_product(name="二手測試品")], 5)) == 0, "排除關鍵字生效")
        check(len(selector.select([make_product(image_urls=[])], 5)) == 0, "沒有圖片被淘汰")
        check(len(selector.select([make_product(affiliate_link="")], 5)) == 0, "沒有分潤連結被淘汰")
        check(len(selector.select([make_product()], 5, exclude_ids={"t1"})) == 0,
              "最近做過的商品會被跳過")


def test_selector_ranking() -> None:
    print("\n[選品：排序]")
    with tempfile.TemporaryDirectory() as td:
        config = _config_in(Path(td), "selection:\n  min_sales: 0\n  min_commission_rate: 0\n")
        selector = ProductSelector(config)

        low = make_product(item_id="low", name="低分", commission_rate=0.05, sales=200)
        high = make_product(item_id="high", name="高分", commission_rate=0.18, sales=9000)
        result = selector.select([low, high], 2)

        check(result[0].product.item_id == "high", "分數高的排前面")
        check(result[0].score > result[1].score, "分數確實有差距")
        check(abs(sum(result[0].breakdown.values()) - result[0].score) < 1e-9,
              "各項加起來等於總分")

        top_only = selector.select([low, high], 1)
        check(len(top_only) == 1 and top_only[0].product.item_id == "high",
              "只要 N 件時會取分數最高的")


def test_caption() -> None:
    print("\n[貼文文案組裝]")
    script = VideoScript(
        hook="鉤子",
        segments=[ScriptSegment(text="內容", on_screen="重點")],
        caption="這是文案本文。",
        hashtags=["蝦皮", "好物"],
        cta="連結在留言",
    )

    caption = build_caption(script, "https://shp.ee/abc")
    check("這是文案本文。" in caption, "包含文案本文")
    check("https://shp.ee/abc" in caption, "包含分潤連結")
    check("#蝦皮" in caption and "#好物" in caption, "標籤有加上 # 符號")

    no_link = build_caption(script, "https://shp.ee/abc", link_in_caption=False)
    check("https://shp.ee/abc" not in no_link, "關閉連結時文案裡不會有連結（IG 用）")

    long_script = VideoScript(hook="", segments=[], caption="字" * 5000,
                              hashtags=[], cta="")
    check(len(build_caption(long_script, "", max_length=100)) <= 100, "過長的文案會被截斷")


def test_csv_source() -> None:
    print("\n[CSV 商品來源]")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        (tmp / "products.csv").write_text(
            "item_id,name,price,affiliate_link,image_urls,commission_rate,sales,rating\n"
            "a1,商品一,499,https://s.shopee.tw/a1,https://img/1.jpg|https://img/2.jpg,12,3000,4.6\n"
            "a2,商品二,299,https://s.shopee.tw/a2,https://img/3.jpg,0.08,1500,4.4\n"
            ",壞掉的列,100,,,,,\n",
            encoding="utf-8",
        )
        config = _config_in(tmp, "source:\n  mode: csv\n  csv:\n    path: products.csv\n")
        products = CsvSource(config).fetch(10)

        check(len(products) == 2, "資料不完整的列會被跳過")
        check(products[0].image_urls == ["https://img/1.jpg", "https://img/2.jpg"],
              "多張圖用 | 分隔會被正確拆開")
        check(abs(products[0].commission_rate - 0.12) < 1e-9,
              "佣金率填 12 會自動換算成 0.12")
        check(abs(products[1].commission_rate - 0.08) < 1e-9,
              "佣金率填 0.08 會維持原樣")


def test_safe_name() -> None:
    print("\n[檔名處理]")
    check("/" not in _safe_name("含/斜線:和*星號的商品"), "危險字元會被換掉")
    check(len(_safe_name("很長的商品名稱" * 20)) <= 28, "檔名長度會被限制")
    check(_safe_name("") == "product", "空名稱會有預設值")


def main() -> int:
    print("=" * 56)
    print("  基本邏輯測試")
    print("=" * 56)

    test_config()
    test_selector_filters()
    test_selector_ranking()
    test_caption()
    test_csv_source()
    test_safe_name()

    print()
    print("-" * 56)
    print(f"通過 {PASSED} 項，失敗 {FAILED} 項")
    print("-" * 56)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
