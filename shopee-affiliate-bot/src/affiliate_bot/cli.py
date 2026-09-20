"""命令列介面。

常用指令：
    python run.py doctor        檢查環境有沒有問題（第一次一定要跑）
    python run.py pick          只看今天會選到哪些商品，不做影片
    python run.py run           完整執行：選品→影片→（審核後）發佈
    python run.py run --count 5 這次做 5 支
    python run.py run --no-publish  只做影片，完全不碰發佈
    python run.py approve all   把待審核的影片全部發出去
    python run.py status        看最近做了哪些影片、發佈成不成功
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

    return parser


_COMMANDS = {
    "doctor": _cmd_doctor,
    "pick": _cmd_pick,
    "run": _cmd_run,
    "approve": _cmd_approve,
    "status": _cmd_status,
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
