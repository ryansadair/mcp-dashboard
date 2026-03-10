"""
Martin Capital Partners — Notion Proprietary Metrics Fetcher
data/notion_metrics.py

Pulls MCP-proprietary fields from the "MCP Master Holdings" Notion database:
  - MCP Dividend Baseline  (number, e.g. 4, 6, 8, 10, 12)
  - MCP Style Bucket       (select: DG, HG, TC, HY)

Designed to merge into the holdings table by ticker symbol.

Setup:
  1. Store your Notion integration token in Streamlit secrets:
         [notion]
         token = "ntn_..."
  2. Ensure the integration has access to the "MCP Universe Proprietary Metrics" page.
  3. The database ID is hardcoded below (stable unless you recreate the DB).

Data is cached for 5 minutes via @st.cache_data.
"""

import requests
import streamlit as st

# ── Notion database config ─────────────────────────────────────────────────
NOTION_DATABASE_ID = "29cff1792e3c461d978af87ca1bea797"
NOTION_API_VERSION = "2022-06-28"
NOTION_BASE_URL = "https://api.notion.com/v1"


def _get_notion_token():
    """
    Retrieve Notion token from Streamlit secrets.
    Supports both flat and nested secret formats:
      NOTION_TOKEN = "ntn_..."          (flat)
      [notion]
      token = "ntn_..."                 (nested)
    """
    # Try nested first
    try:
        return st.secrets["notion"]["token"]
    except (KeyError, TypeError):
        pass
    # Try flat
    try:
        return st.secrets["NOTION_TOKEN"]
    except (KeyError, TypeError):
        pass
    return None


def _query_all_pages(token, database_id):
    """
    Query all pages from a Notion database, handling pagination.
    Returns list of raw page objects from the Notion API.
    """
    url = f"{NOTION_BASE_URL}/databases/{database_id}/query"
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_API_VERSION,
        "Content-Type": "application/json",
    }

    all_results = []
    has_more = True
    start_cursor = None

    while has_more:
        payload = {"page_size": 100}
        if start_cursor:
            payload["start_cursor"] = start_cursor

        resp = requests.post(url, headers=headers, json=payload, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        all_results.extend(data.get("results", []))
        has_more = data.get("has_more", False)
        start_cursor = data.get("next_cursor")

    return all_results


def _extract_title(prop):
    """Extract plain text from a Notion title property."""
    if not prop or prop.get("type") != "title":
        return ""
    parts = prop.get("title", [])
    return "".join(p.get("plain_text", "") for p in parts).strip()


def _extract_number(prop):
    """Extract number from a Notion number property."""
    if not prop or prop.get("type") != "number":
        return None
    return prop.get("number")


def _extract_select(prop):
    """Extract select name from a Notion select property."""
    if not prop or prop.get("type") != "select":
        return None
    sel = prop.get("select")
    if sel:
        return sel.get("name", "")
    return None


def _extract_multi_select(prop):
    """Extract list of names from a Notion multi_select property."""
    if not prop or prop.get("type") != "multi_select":
        return []
    return [item.get("name", "") for item in prop.get("multi_select", [])]


@st.cache_data(ttl=300, show_spinner=False)
def fetch_notion_metrics():
    """
    Fetch all rows from MCP Master Holdings and return a dict keyed by
    uppercase ticker symbol.

    Returns:
        {
            "MSFT": {
                "div_baseline": 10,
                "style_bucket": "HG",
                "cld_source": "Switch",
                "mcp_target": 563,
                "strategies": ["QDVD", "DAC", "OR"],
            },
            ...
        }

    Returns empty dict if token is missing or API call fails.
    """
    token = _get_notion_token()
    if not token:
        return {}

    try:
        pages = _query_all_pages(token, NOTION_DATABASE_ID)
    except Exception:
        return {}

    result = {}
    for page in pages:
        props = page.get("properties", {})

        symbol = _extract_title(props.get("Symbol", {}))
        if not symbol:
            continue

        sym = symbol.upper().strip()
        result[sym] = {
            "div_baseline":  _extract_number(props.get("MCP Dividend Baseline", {})),
            "style_bucket":  _extract_select(props.get("MCP Style Bucket", {})),
            "cld_source":    _extract_select(props.get("CLD Source", {})),
            "mcp_target":    _extract_number(props.get("MCP Target", {})),
            "strategies":    _extract_multi_select(props.get("Strategies", {})),
        }

    return result


def get_metrics_for_ticker(ticker):
    """
    Get Notion metrics for a single ticker.
    Returns dict with keys: div_baseline, style_bucket, cld_source, mcp_target, strategies
    Returns empty dict if not found.
    """
    data = fetch_notion_metrics()
    return data.get(ticker.upper(), {})


def get_metrics_for_tickers(tickers):
    """
    Get Notion metrics for a list of tickers.
    Returns: {ticker: {div_baseline, style_bucket, ...}}
    Missing tickers will have empty dicts.
    """
    data = fetch_notion_metrics()
    return {t: data.get(t.upper(), {}) for t in tickers}
