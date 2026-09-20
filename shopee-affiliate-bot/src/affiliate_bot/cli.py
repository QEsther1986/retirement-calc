"""命令列介面。

常用指令：
    python run.py doctor        檢查環境有沒有問題（第一次一定要跑）
    python run.py pick          只看今天會選到哪些商品，不做影片
    python run.py run           完整執行：選品→影片→（審核後）發佈
    python run.py run --count 5 這次做 5 支
    python run.py run --no-publish  只做影片，完全不碰發佈
    python run.py approve all   把待審核的影片全部發出去
    python run.py status        看最近做了哪些影片、發佈成不成功
    python run.py test-shopee   測試蝦皮 API，看它到底給不給銷量、評分等欄位
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import ConfigError, load_config
from .logging_setup import setup_logging


def _project_root() -> Path:
    """專案根目錄 = 這個檔案往上兩層（src/affiliate_bot/cli.py -> 專案根）。"""
    return Path(__file__).resolve().parents[2]


def _cmd_doctor(args, root: Path) -> int:
    from .doctor import run_doctor, safe_load_config
    return run_doctor(safe_load_config(root), root)


def _cmd_pick(args, root: Path) -> int:
    from .db import Database
    from .selection import ProductSelector
    from .sources import build_source

    config = load_config(root)
    source = build_source(config)
    selector = ProductSelector(config)
    db = Database(config.paths.database)

    pool = int(config.get("general.candidate_pool", 40))
    count = args.count or int(config.get("general.videos_per_run", 3))
    dedupe_days = int(config.get("selection.dedupe_days", 30))

    products = source.fetch(pool)
    chosen = selector.select(products, count, db.used_item_ids(dedupe_days))

    if not chosen:
        print("\n沒有商品通過篩選。請放寬 config.yaml 的 selection 條件後再試。\n")
        return 1

    print("\n這次會做成影片的商品：\n")
    for index, scored in enumerate(chosen, start=1):
        p = scored.product
        print(f"  {index}. {p.name}")
        print(f"     💰 單件賺 NT${p.estimated_commission:,.0f}"
              f"（售價 NT${p.price:,.0f} × 分潤 {p.commission_rate * 100:.1f}%）")
        print(f"     📦 銷量 {p.sales:,} 件｜⭐ 評分 {p.rating:.1f}")
        print(f"     {scored.explain()}")
        print()
    print("確認沒問題的話，執行：python run.py run\n")
    return 0


def _cmd_run(args, root: Path) -> int:
    from .pipeline import Pipeline

    config = load_config(root)
    pipeline = Pipeline(config)
    jobs = pipeline.run(count=args.count, publish=not args.no_publish)
    return 0 if jobs else 1


def _cmd_approve(args, root: Path) -> int:
    from .pipeline import Pipeline

    config = load_config(root)
    pipeline = Pipeline(config)

    if args.ids and args.ids != ["all"]:
        try:
            ids = [int(i) for i in args.ids]
        except ValueError:
            print("影片編號必須是數字，例如：python run.py approve 3 4")
            return 1
    else:
        ids = None

    pipeline.approve(ids)
    return 0


def _cmd_test_shopee(args, root: Path) -> int:
    """實際打一次蝦皮 API，把回傳的欄位攤開來看。

    這支指令存在的理由：蝦皮的開放 API 會改版，官方文件也不見得同步。
    與其猜「它到底有沒有給銷量欄位」，不如直接打一次看結果。
    它會明確告訴你：你設定的三個篩選條件，用這份資料跑不跑得動。
    """
    import json

    from .sources.shopee_api import ShopeeApiSource

    config = load_config(root)

    print()
    print("=" * 60)
    print("  蝦皮 API 連線測試")
    print("=" * 60)
    print()

    if not (config.has_secret("SHOPEE_APP_ID") and config.has_secret("SHOPEE_APP_SECRET")):
        print("❌ .env 裡沒有 SHOPEE_APP_ID 或 SHOPEE_APP_SECRET。")
        print()
        print("   這代表你還沒申請到蝦皮開放 API 權限，或還沒把金鑰填進 .env。")
        print("   在拿到權限之前，請把 config.yaml 的 source.mode 設成 csv，")
        print("   用自己整理的商品清單，其他流程完全一樣自動。")
        print()
        return 1

    # 暫時放寬 mode 檢查，直接建立蝦皮來源
    original_mode = config.data.setdefault("source", {}).get("mode")
    config.data["source"]["mode"] = "shopee"
    try:
        source = ShopeeApiSource(config)
    except ConfigError as exc:
        print(f"❌ {exc}")
        return 1
    finally:
        if original_mode is not None:
            config.data["source"]["mode"] = original_mode

    print("正在向蝦皮要 3 件商品做測試…")
    print()
    try:
        products = source.fetch(3)
    except ConfigError as exc:
        print(f"❌ 連線失敗：\n{exc}")
        return 1

    if not products:
        print("⚠️  連線成功，但沒有回傳任何商品。")
        print("   可能是關鍵字太冷門，或你的帳號還沒有商品權限。")
        print("   試試把 config.yaml 的 source.shopee.keywords 設成 [] （不限關鍵字）。")
        return 1

    print(f"✅ 連線成功，取得 {len(products)} 件商品。")
    print()

    sample = products[0]
    print("--- 蝦皮實際回傳的原始欄位（第一件商品）---")
    print(json.dumps(sample.raw, ensure_ascii=False, indent=2)[:1500])
    print()

    # 逐項檢查你的篩選條件跑不跑得動
    print("--- 你的篩選條件能不能用 ---")
    print()

    checks = [
        ("利潤（售價 × 佣金率）",
         all(p.price > 0 and p.commission_rate > 0 for p in products),
         f"min_commission_amount = {config.get('selection.min_commission_amount', 50)}"),
        ("銷量",
         all(p.sales > 0 for p in products),
         f"min_sales = {config.get('selection.min_sales', 2000)}"),
        ("評分",
         all(p.rating > 0 for p in products),
         f"min_rating = {config.get('selection.min_rating', 4.5)}"),
        ("商品圖（做影片必要）",
         all(p.image_urls for p in products),
         "沒有圖就不能做影片"),
        ("分潤連結",
         all(p.affiliate_link for p in products),
         "沒有連結就賺不到佣金"),
    ]

    blocked = []
    for label, available, note in checks:
        mark = "✅" if available else "❌"
        state = "有資料" if available else "沒有資料"
        print(f"  {mark} {label}：{state}    （{note}）")
        if not available:
            blocked.append(label)

    print()
    print("--- 實際抓到的商品 ---")
    for i, p in enumerate(products, start=1):
        print(f"  {i}. {p.summary()}")

    print()
    print("-" * 60)
    if blocked:
        print(f"⚠️  蝦皮沒有回傳這些欄位：{'、'.join(blocked)}")
        print()
        print("   有兩個處理方向：")
        print("   (1) 上面印出的原始欄位裡，如果看得到對應的資料但名稱不一樣，")
        print("       把 config.yaml 的 source.shopee.query 改成正確的欄位名稱。")
        print("   (2) 如果蝦皮真的沒提供，就把對應的門檻設成 0 不篩選，")
        print("       或改用 csv 模式自己補上這些資料。")
    else:
        print("✅ 你的三個條件（利潤、銷量、評分）都有資料可以篩選，可以直接用。")
        print("   下一步：把 config.yaml 的 source.mode 改成 shopee，然後執行")
        print("       python run.py pick")
    print("-" * 60)
    print()
    return 0


def _cmd_status(args, root: Path) -> int:
    from .db import Database

    config = load_config(root)
    db = Database(config.paths.database)
    rows = db.recent_summary(args.limit)

    if not rows:
        print("\n目前還沒有做過任何影片。執行 python run.py run 開始吧。\n")
        return 0

    status_text = {
        "created": "已完成",
        "pending": "待審核",
        "published": "已發佈",
        "failed": "發佈失敗",
    }

    print(f"\n最近 {len(rows)} 支影片：\n")
    print(f"  {'編號':<6}{'狀態':<8}{'成功/失敗':<12}{'商品'}")
    print("  " + "-" * 62)
    for row in rows:
        state = status_text.get(row["status"], row["status"])
        counts = f"{row['ok_count']}/{row['fail_count']}"
        name = (row["product_name"] or "?")[:24]
        print(f"  {row['id']:<6}{state:<8}{counts:<12}{name}")

    pending = [r["id"] for r in rows if r["status"] == "pending"]
    if pending:
        print(f"\n有 {len(pending)} 支影片待審核。看過影片後執行：")
        print("    python run.py approve all")
    print()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="affiliate_bot",
        description="蝦皮聯盟行銷自動化：自動選品、自動做短影音、自動發佈。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="顯示除錯用的詳細訊息")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("doctor", help="檢查環境與設定（第一次使用請先跑這個）")

    pick = sub.add_parser("pick", help="只看這次會選到哪些商品，不做影片")
    pick.add_argument("--count", type=int, help="要挑幾件商品")

    run = sub.add_parser("run", help="完整執行：選品 → 做影片 → 發佈")
    run.add_argument("--count", type=int, help="這次要做幾支影片")
    run.add_argument("--no-publish", action="store_true", help="只做影片，不發佈")

    approve = sub.add_parser("approve", help="把待審核的影片發佈出去")
    approve.add_argument("ids", nargs="*", default=["all"],
                         help="影片編號（可多個），或 all 代表全部")

    status = sub.add_parser("status", help="查看最近的影片與發佈結果")
    status.add_argument("--limit", type=int, default=20, help="要看幾筆")

    sub.add_parser("test-shopee",
                   help="實際打一次蝦皮 API，檢查有沒有回傳銷量、評分等欄位")

    return parser


_COMMANDS = {
    "doctor": _cmd_doctor,
    "pick": _cmd_pick,
    "run": _cmd_run,
    "approve": _cmd_approve,
    "status": _cmd_status,
    "test-shopee": _cmd_test_shopee,
}


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    root = _project_root()

    setup_logging(root / "logs", verbose=args.verbose)

    try:
        return _COMMANDS[args.command](args, root)
    except ConfigError as exc:
        print(f"\n設定有問題：\n\n{exc}\n")
        return 1
    except KeyboardInterrupt:
        print("\n已中斷。\n")
        return 130
    except Exception as exc:
        print(f"\n發生未預期的錯誤：{exc}\n")
        print("完整錯誤紀錄在 logs/bot.log，如果看不懂可以把那個檔案內容貼給我看。\n")
        import logging
        logging.getLogger(__name__).exception("未預期的錯誤")
        return 1


if __name__ == "__main__":
    sys.exit(main())
