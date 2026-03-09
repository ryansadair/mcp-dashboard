"""
Tamarac Holdings Excel Parser
Reads multi-sheet Tamarac export files and returns structured holdings data.
Handles the =\"value\" quoting format from Tamarac exports.
"""
import pandas as pd
import openpyxl
import os
import sqlite3
from datetime import datetime

# Strategy display names
STRATEGY_NAMES = {
    "QDVD": "Quality Dividend",
    "SMID": "Quality SMID Dividend",
    "DAC": "Quality All-Cap Dividend",
    "OR": "Oregon Dividend",
    "DCP": "Dividend Core Plus",
}

STRATEGY_COLORS = {
    "QDVD": "#569542",
    "SMID": "#C9A84C",
    "DAC": "#07415A",
    "OR": "#569542",
    "DCP": "#07415A",
}

# Benchmarks for each strategy
STRATEGY_BENCHMARKS = {
    "QDVD": {"name": "S&P 500", "ticker": "^GSPC"},
    "SMID": {"name": "Russell 2500", "ticker": "^SP600"},  # proxy
    "DAC":  {"name": "S&P 500", "ticker": "^GSPC"},
    "OR":   {"name": "S&P 500", "ticker": "^GSPC"},
    "DCP":  {"name": "S&P 500", "ticker": "^GSPC"},
}


def clean_tamarac_value(val):
    """Strip the =\"...\" quoting that Tamarac exports use."""
    if val is None:
        return ""
    s = str(val).strip()
    if s.startswith('="') and s.endswith('"'):
        return s[2:-1]
    if s.startswith('*'):
        return s  # strategy name field
    return s


def parse_tamarac_excel(filepath):
    """
    Parse a Tamarac Holdings Excel export.
    Returns dict: {strategy_code: DataFrame} where each DF has columns:
        as_of_date, strategy, weight, symbol, cusip, description, quantity
    """
    wb = openpyxl.load_workbook(filepath, read_only=True)
    result = {}

    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        rows = list(ws.iter_rows(values_only=True))

        if len(rows) < 2:
            continue

        # Parse header
        headers_raw = rows[0]
        headers = [clean_tamarac_value(h).lower().replace(" ", "_") for h in headers_raw]

        # Parse data rows
        data = []
        for row in rows[1:]:
            record = {}
            for j, val in enumerate(row):
                col = headers[j] if j < len(headers) else f"col_{j}"
                if col == "as_of_date":
                    record[col] = val if isinstance(val, datetime) else None
                elif col == "weight":
                    try:
                        str_val = str(val).strip() if val else ""
                        if str_val.endswith("%"):
                            record[col] = float(str_val.rstrip("%")) / 100
                        else:
                            record[col] = float(val) if val else 0.0
                    except (ValueError, TypeError):
                        record[col] = 0.0
                elif col in ("quantity", "yield_at_cost", "current_yield", "unit_cost", "cost_basis", "value", "price", "annual_income", "cumulative_income"):
                    try:
                        # Handle percentage strings like "5.58%" from Tamarac
                        str_val = str(val).strip() if val else ""
                        if str_val.endswith("%"):
                            record[col] = float(str_val.rstrip("%")) / 100
                        else:
                            record[col] = float(val) if val else 0.0
                    except (ValueError, TypeError):
                        record[col] = 0.0
                else:
                    record[col] = clean_tamarac_value(val)
            data.append(record)

        df = pd.DataFrame(data)

        # Rename columns to standard names
        col_map = {
            "as_of_date": "as_of_date",
            "data_for": "strategy_raw",
            "weight": "weight",
            "symbol": "symbol",
            "cusip": "cusip",
            "description": "description",
            "quantity": "quantity",
            "open_date": "open_date",
            "value": "value",
            "price": "price",
            "unit_cost": "unit_cost",
            "cost_basis": "cost_basis",
            "annual_income": "annual_income",
            "cumulative_income": "cumulative_income",
            "yield_at_cost": "yield_at_cost",
            "current_yield": "current_yield",
        }
        df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})

        # Filter out CASH rows for holdings display (keep for weight calc)
        df["is_cash"] = df["symbol"].str.upper() == "CASH"

        result[sheet_name] = df

    wb.close()
    return result


def get_holdings_for_strategy(parsed_data, strategy_code, include_cash=False):
    """Get holdings DataFrame for a specific strategy, optionally excluding cash."""
    if strategy_code not in parsed_data:
        return pd.DataFrame()

    df = parsed_data[strategy_code].copy()
    if not include_cash:
        df = df[~df["is_cash"]].copy()

    # Convert weight from decimal to percentage for display
    df["weight_pct"] = df["weight"] * 100

    return df.sort_values("weight", ascending=False).reset_index(drop=True)


def get_cash_weight(parsed_data, strategy_code):
    """Get cash weight for a strategy."""
    if strategy_code not in parsed_data:
        return 0.0
    df = parsed_data[strategy_code]
    cash_rows = df[df["is_cash"]]
    if len(cash_rows) > 0:
        return float(cash_rows["weight"].iloc[0]) * 100
    return 0.0


def get_all_unique_tickers(parsed_data):
    """Get sorted list of all unique non-cash tickers across all strategies."""
    tickers = set()
    for strategy_code, df in parsed_data.items():
        non_cash = df[~df["is_cash"]]
        tickers.update(non_cash["symbol"].str.upper().tolist())
    return sorted(tickers)


def save_holdings_to_db(parsed_data, db_path="data/portfolio.db"):
    """Cache parsed holdings to SQLite."""
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)

    for strategy_code, df in parsed_data.items():
        df_save = df.copy()
        df_save["strategy_code"] = strategy_code
        if "as_of_date" in df_save.columns:
            df_save["as_of_date"] = df_save["as_of_date"].astype(str)
        df_save.to_sql("holdings", conn, if_exists="append", index=False)

    conn.close()


def get_as_of_date(parsed_data):
    """Get the as-of date from the first available strategy."""
    for code, df in parsed_data.items():
        if "as_of_date" in df.columns and len(df) > 0:
            val = df["as_of_date"].iloc[0]
            if isinstance(val, datetime):
                return val
    return None