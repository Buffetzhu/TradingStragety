#!/usr/bin/env python
# 用途：初始化策略工作台 SQLite 数据库
# 参数：--db-path <数据库路径>（可选，默认 data/strategy.db）
# 输出：数据库路径
# 退出码：0=成功，1=执行出错
# Known Issues: 仅创建 V1/V2 所需基础表，后续迁移需增加版本管理。

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS stock_pool (
    symbol TEXT PRIMARY KEY,
    name TEXT,
    tag TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS strategy_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    version TEXT NOT NULL,
    params_json TEXT NOT NULL,
    is_system INTEGER NOT NULL DEFAULT 0,
    is_following INTEGER NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS backtest_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_name TEXT NOT NULL,
    symbols_json TEXT NOT NULL,
    metrics_json TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS timeline_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    strategy_line_id INTEGER,
    simulated_state_json TEXT,
    live_state_json TEXT,
    deviation_score REAL,
    next_key_node_json TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(SCHEMA)
        conn.commit()


def main() -> int:
    parser = argparse.ArgumentParser(description="初始化策略工作台 SQLite 数据库")
    parser.add_argument("--db-path", default="data/strategy.db")
    args = parser.parse_args()

    try:
        db_path = Path(args.db_path)
        init_db(db_path)
        print(f"DB_INITIALIZED {db_path}")
        return 0
    except Exception as exc:
        print(f"ERROR {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())