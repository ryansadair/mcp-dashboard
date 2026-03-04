"""
Holdings data layer.
Primary source: Tamarac export (Excel/CSV)
Fallback: Notion API, then hardcoded config
"""

import pandas as pd
import streamlit as st
from pathlib import Path
from datetime import datetime
from utils.config import STRATEGIES
from utils import cache


# ── Tamarac Import ─────────────────────────────────────────────────────────

def load_tamarac_export(filepath: str) -> pd.DataFrame:
    """
    Parse Tamarac Holdings export.
    Expects one sheet per strategy (QDVD, SMID, DAC, OR, DCP).
    Columns: As of Date, Data For, Weight, Symbol, CUSIP, Description, Quantity
    """
    filepath = Path(filepath)
    if not filepath.exists():
        return pd.DataFrame()

    try:
        # Read all sheets
        xl = pd.ExcelFile(filepath)
        all_sheets = []

        strategy_map = {
            "QDVD": "QDVD",
            "SMID": "SMID",
            "DAC":  "DAC",
            "OR":   "OR",
            "DCP":  "DCP",
        }

        for sheet in xl.sheet_names:
            strategy = strategy_map.get(sheet.strip().upper())
            if not strategy:
                continue

            df = xl.parse(sheet, header=0)
            df.columns = [str(c).strip() for c in df.columns]

            # Rename to internal names
            df = df.rename(columns={
                "Symbol":      "ticker",
                "Description": "name",
                "Weight":      "weight",
                "Quantity":    "shares",
                "Data For":    "strategy_raw",
                "As of Date":  "as_of_date",
                "CUSIP":       "cusip",
            })

            # Convert weight from decimal to percentage if needed
            if "weight" in df.columns:
                sample = df["weight"].dropna().iloc[0] if not df["weight"].dropna().empty else 0
                if float(sample) < 1.0:
                    df["weight"] = df["weight"] * 100

            df["strategy"] = strategy
            df["updated_at"] = datetime.now().isoformat()

            # Drop rows with no ticker
            df = df[df["ticker"].notna() & (df["ticker"] != "")]

            all_sheets.append(df)

        if not all_sheets:
            return pd.DataFrame()

        combined = pd.concat(all_sheets, ignore_index=True)
        return combined

    except Exception as e:
        st.error(f"Error loading Tamarac file: {e}")
        return pd.DataFrame()

def save_tamarac_to_db(df: pd.DataFrame):
    """Write parsed Tamarac data to SQLite holdings table."""
    if df.empty:
        return
    keep_cols = ["strategy", "ticker", "name", "weight", "shares", 
                 "cusip", "as_of_date", "updated_at"]
    df = df[[c for c in keep_cols if c in df.columns]].copy()
    cache.upsert_df(df, "holdings", if_exists="replace")

# ── Query Layer ─────────────────────────────────────────────────────────────

@st.cache_data(ttl=900)
def get_holdings(strategy: str) -> pd.DataFrame:
    """Get holdings for a strategy from DB, or fallback to demo data."""
    try:
        df = cache.query(
            "SELECT * FROM holdings WHERE strategy = ? ORDER BY weight DESC",
            params=(strategy,)
        )
        if not df.empty:
            return df
    except Exception:
        pass

    # Fallback: demo data (matches JSX mock — replace once Tamarac is wired)
    return _demo_holdings(strategy)


def get_all_strategies_summary() -> pd.DataFrame:
    """AUM, holding count, etc. per strategy."""
    try:
        return cache.query("""
            SELECT strategy,
                   COUNT(*) as holdings,
                   SUM(market_value) as aum,
                   SUM(weight) as total_weight
            FROM holdings
            GROUP BY strategy
        """)
    except Exception:
        return pd.DataFrame()


# ── Demo Data (Sprint 1 fallback) ─────────────────────────────────────────

def _demo_holdings(strategy: str) -> pd.DataFrame:
    DEMO = {
        "QDVD": [
            {"ticker":"JNJ","name":"Johnson & Johnson","weight":6.2,"price":158.42,"chg1d":0.34,"ytd":5.12,"div_yield":3.01,"div_growth_5y":5.8,"sector":"Healthcare","div_culture":"A+","quality":92},
            {"ticker":"PG","name":"Procter & Gamble","weight":5.8,"price":172.15,"chg1d":-0.21,"ytd":3.87,"div_yield":2.45,"div_growth_5y":6.1,"sector":"Consumer Staples","div_culture":"A+","quality":95},
            {"ticker":"MSFT","name":"Microsoft Corp","weight":5.5,"price":442.58,"chg1d":1.12,"ytd":12.34,"div_yield":0.72,"div_growth_5y":10.2,"sector":"Technology","div_culture":"A","quality":94},
            {"ticker":"KO","name":"Coca-Cola Co","weight":5.1,"price":62.87,"chg1d":0.08,"ytd":4.56,"div_yield":2.98,"div_growth_5y":3.4,"sector":"Consumer Staples","div_culture":"A+","quality":88},
            {"ticker":"PEP","name":"PepsiCo Inc","weight":4.9,"price":178.23,"chg1d":-0.45,"ytd":2.11,"div_yield":2.78,"div_growth_5y":7.1,"sector":"Consumer Staples","div_culture":"A","quality":87},
            {"ticker":"ABT","name":"Abbott Labs","weight":4.7,"price":118.90,"chg1d":0.67,"ytd":8.92,"div_yield":1.92,"div_growth_5y":12.8,"sector":"Healthcare","div_culture":"A","quality":90},
            {"ticker":"TXN","name":"Texas Instruments","weight":4.5,"price":195.34,"chg1d":-0.89,"ytd":6.45,"div_yield":2.67,"div_growth_5y":15.4,"sector":"Technology","div_culture":"A","quality":91},
            {"ticker":"MMM","name":"3M Company","weight":4.2,"price":108.67,"chg1d":1.45,"ytd":18.23,"div_yield":2.12,"div_growth_5y":-2.1,"sector":"Industrials","div_culture":"B+","quality":72},
            {"ticker":"ABBV","name":"AbbVie Inc","weight":4.0,"price":192.45,"chg1d":0.23,"ytd":9.67,"div_yield":3.34,"div_growth_5y":8.9,"sector":"Healthcare","div_culture":"A","quality":86},
            {"ticker":"ITW","name":"Illinois Tool Works","weight":3.8,"price":267.89,"chg1d":-0.12,"ytd":7.34,"div_yield":2.21,"div_growth_5y":7.3,"sector":"Industrials","div_culture":"A","quality":89},
            {"ticker":"EMR","name":"Emerson Electric","weight":3.6,"price":112.45,"chg1d":0.56,"ytd":10.12,"div_yield":1.87,"div_growth_5y":1.2,"sector":"Industrials","div_culture":"B+","quality":78},
            {"ticker":"CL","name":"Colgate-Palmolive","weight":3.4,"price":95.78,"chg1d":0.19,"ytd":6.78,"div_yield":2.15,"div_growth_5y":3.0,"sector":"Consumer Staples","div_culture":"A","quality":85},
        ],
        "DAC": [
            {"ticker":"JNJ","name":"Johnson & Johnson","weight":8.5,"price":158.42,"chg1d":0.34,"ytd":5.12,"div_yield":3.01,"div_growth_5y":5.8,"sector":"Healthcare","div_culture":"A+","quality":92},
            {"ticker":"PG","name":"Procter & Gamble","weight":8.2,"price":172.15,"chg1d":-0.21,"ytd":3.87,"div_yield":2.45,"div_growth_5y":6.1,"sector":"Consumer Staples","div_culture":"A+","quality":95},
            {"ticker":"KO","name":"Coca-Cola Co","weight":8.0,"price":62.87,"chg1d":0.08,"ytd":4.56,"div_yield":2.98,"div_growth_5y":3.4,"sector":"Consumer Staples","div_culture":"A+","quality":88},
            {"ticker":"MMM","name":"3M Company","weight":7.8,"price":108.67,"chg1d":1.45,"ytd":18.23,"div_yield":2.12,"div_growth_5y":-2.1,"sector":"Industrials","div_culture":"B+","quality":72},
        ],
    }
    rows = DEMO.get(strategy, DEMO["QDVD"])
    df = pd.DataFrame(rows)
    df["strategy"] = strategy
    return df