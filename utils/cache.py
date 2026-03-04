"""
SQLite caching layer for market data, holdings, and performance.
"""

import sqlite3
import pandas as pd
from pathlib import Path
from utils.config import DB_PATH


def get_connection() -> sqlite3.Connection:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(DB_PATH, check_same_thread=False)


def init_db():
    """Create tables if they don't exist."""
    con = get_connection()
    cur = con.cursor()

    cur.executescript("""
        CREATE TABLE IF NOT EXISTS daily_prices (
            ticker TEXT,
            date TEXT,
            open REAL, high REAL, low REAL, close REAL,
            volume INTEGER, adj_close REAL,
            PRIMARY KEY (ticker, date)
        );

        CREATE TABLE IF NOT EXISTS fundamentals (
            ticker TEXT PRIMARY KEY,
            name TEXT,
            sector TEXT,
            market_cap REAL,
            pe_ratio REAL,
            forward_pe REAL,
            peg_ratio REAL,
            div_yield REAL,
            div_amount REAL,
            div_growth_5y REAL,
            payout_ratio REAL,
            consecutive_years INTEGER,
            beta REAL,
            roe REAL,
            debt_equity REAL,
            quality_score INTEGER,
            div_culture_grade TEXT,
            updated_at TEXT
        );

        CREATE TABLE IF NOT EXISTS holdings (
            strategy TEXT,
            ticker TEXT,
            name TEXT,
            weight REAL,
            shares REAL,
            market_value REAL,
            cost_basis REAL,
            sector TEXT,
            updated_at TEXT,
            PRIMARY KEY (strategy, ticker)
        );

        CREATE TABLE IF NOT EXISTS strategy_performance (
            strategy TEXT,
            date TEXT,
            nav REAL,
            daily_return REAL,
            ytd_return REAL,
            PRIMARY KEY (strategy, date)
        );

        CREATE TABLE IF NOT EXISTS dividend_history (
            ticker TEXT,
            ex_date TEXT,
            amount REAL,
            pay_date TEXT,
            PRIMARY KEY (ticker, ex_date)
        );

        CREATE TABLE IF NOT EXISTS alerts_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alert_type TEXT,
            ticker TEXT,
            message TEXT,
            severity TEXT,
            created_at TEXT,
            read INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS data_refresh_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT,
            status TEXT,
            message TEXT,
            rows_updated INTEGER,
            timestamp TEXT
        );
    """)
    con.commit()
    con.close()


def query(sql: str, params=None) -> pd.DataFrame:
    con = get_connection()
    df = pd.read_sql_query(sql, con, params=params)
    con.close()
    return df


def execute(sql: str, params=None):
    con = get_connection()
    cur = con.cursor()
    if params:
        cur.execute(sql, params)
    else:
        cur.execute(sql)
    con.commit()
    con.close()


def upsert_df(df: pd.DataFrame, table: str, if_exists: str = "append"):
    """Write a DataFrame to SQLite, replacing on conflict."""
    con = get_connection()
    df.to_sql(table, con, if_exists=if_exists, index=False)
    con.close()