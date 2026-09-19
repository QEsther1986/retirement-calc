"""SQLite 資料庫：記錄選過的商品、產生的影片、發佈紀錄。

用途有三個：
  1. 避免重複推薦同一件商品（去重）
  2. 記錄每支影片發到哪些平台、成功或失敗
  3. 之後可以回頭看哪些商品帶來成效
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    item_id        TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    price          REAL,
    commission_rate REAL,
    sales          INTEGER,
    rating         REAL,
    affiliate_link TEXT,
    score          REAL,
    first_seen_at  TEXT NOT NULL,
    last_used_at   TEXT
);

CREATE TABLE IF NOT EXISTS videos (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id        TEXT NOT NULL,
    file_path      TEXT NOT NULL,
    caption        TEXT,
    hashtags       TEXT,
    duration_sec   REAL,
    status         TEXT NOT NULL DEFAULT 'created',
    created_at     TEXT NOT NULL,
    FOREIGN KEY (item_id) REFERENCES products(item_id)
);

CREATE TABLE IF NOT EXISTS posts (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id       INTEGER NOT NULL,
    platform       TEXT NOT NULL,
    account_label  TEXT NOT NULL,
    remote_id      TEXT,
    status         TEXT NOT NULL,
    message        TEXT,
    posted_at      TEXT NOT NULL,
    FOREIGN KEY (video_id) REFERENCES videos(id)
);

CREATE INDEX IF NOT EXISTS idx_posts_video ON posts(video_id);
CREATE INDEX IF NOT EXISTS idx_videos_item ON videos(item_id);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ---------- 商品 ----------

    def remember_product(self, item_id: str, name: str, price: float,
                         commission_rate: float, sales: int, rating: float,
                         affiliate_link: str, score: float) -> None:
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO products
                   (item_id, name, price, commission_rate, sales, rating,
                    affiliate_link, score, first_seen_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(item_id) DO UPDATE SET
                       name=excluded.name, price=excluded.price,
                       commission_rate=excluded.commission_rate,
                       sales=excluded.sales, rating=excluded.rating,
                       affiliate_link=excluded.affiliate_link,
                       score=excluded.score""",
                (item_id, name, price, commission_rate, sales, rating,
                 affiliate_link, score, _now()),
            )

    def mark_product_used(self, item_id: str) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE products SET last_used_at = ? WHERE item_id = ?",
                         (_now(), item_id))

    def used_item_ids(self, within_days: int) -> set[str]:
        """回傳最近 N 天內已經做過影片的商品 ID，用來避免重複。"""
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT item_id FROM products
                   WHERE last_used_at IS NOT NULL
                     AND julianday('now') - julianday(last_used_at) < ?""",
                (within_days,),
            ).fetchall()
        return {row["item_id"] for row in rows}

    # ---------- 影片 ----------

    def record_video(self, item_id: str, file_path: str, caption: str,
                     hashtags: list[str], duration_sec: float) -> int:
        with self.connect() as conn:
            cur = conn.execute(
                """INSERT INTO videos (item_id, file_path, caption, hashtags,
                                       duration_sec, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (item_id, file_path, caption, " ".join(hashtags), duration_sec, _now()),
            )
            return int(cur.lastrowid)

    def set_video_status(self, video_id: int, status: str) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE videos SET status = ? WHERE id = ?", (status, video_id))

    # ---------- 發佈紀錄 ----------

    def record_post(self, video_id: int, platform: str, account_label: str,
                    status: str, remote_id: str = "", message: str = "") -> None:
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO posts (video_id, platform, account_label, remote_id,
                                      status, message, posted_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (video_id, platform, account_label, remote_id, status, message, _now()),
            )

    def recent_summary(self, limit: int = 20) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(
                """SELECT v.id, v.created_at, v.file_path, v.status,
                          p.name AS product_name,
                          (SELECT COUNT(*) FROM posts WHERE video_id = v.id
                            AND status = 'success') AS ok_count,
                          (SELECT COUNT(*) FROM posts WHERE video_id = v.id
                            AND status != 'success') AS fail_count
                   FROM videos v LEFT JOIN products p ON p.item_id = v.item_id
                   ORDER BY v.id DESC LIMIT ?""",
                (limit,),
            ).fetchall()
