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


# ═══════════════════════════════════════════════════════════════════════════
# DIVIDEND COMMENTARY — fetched from MCP Wiki child pages
# ═══════════════════════════════════════════════════════════════════════════

def _extract_rich_text_plain(rich_text_list):
    """Extract plain text from a Notion rich_text array, preserving line breaks."""
    if not rich_text_list:
        return ""
    return "".join(rt.get("plain_text", "") for rt in rich_text_list)


def _extract_rich_text_html(rich_text_list):
    """
    Convert a Notion rich_text array to styled HTML, preserving
    bold, italic, underline, and links.
    """
    if not rich_text_list:
        return ""
    parts = []
    for rt in rich_text_list:
        text = rt.get("plain_text", "")
        if not text:
            continue
        # Escape HTML entities
        text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        # Preserve newlines
        text = text.replace("\n", "<br>")

        annotations = rt.get("annotations", {})
        href = rt.get("href")

        if annotations.get("bold"):
            text = f"<strong>{text}</strong>"
        if annotations.get("italic"):
            text = f"<em>{text}</em>"
        if annotations.get("underline"):
            text = f"<u>{text}</u>"
        if annotations.get("strikethrough"):
            text = f"<s>{text}</s>"
        if href:
            text = f'<a href="{href}" style="color:#C9A84C;" target="_blank">{text}</a>'

        parts.append(text)
    return "".join(parts)


@st.cache_data(ttl=300, show_spinner=False)
def fetch_dividend_commentary(ticker):
    """
    Search Notion for a page titled '{TICKER} - Dividend Commentary'
    and return its block content as a list of HTML strings.

    Uses paginated search to handle Notion's relevance-based ordering,
    which can bury exact title matches behind loosely related pages.

    Returns:
        list[str] — each entry is one block rendered as HTML, or
        empty list if page not found or token unavailable.
    """
    token = _get_notion_token()
    if not token:
        return []

    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_API_VERSION,
        "Content-Type": "application/json",
    }

    # Step 1: Search for the commentary page by title.
    # Notion search is fuzzy/relevance-ranked, so we paginate through
    # results looking for an exact title match.
    search_title = f"{ticker.upper()} - Dividend Commentary"
    page_id = None

    try:
        has_more = True
        start_cursor = None
        pages_checked = 0
        max_pages = 200  # safety limit

        while has_more and pages_checked < max_pages:
            payload = {
                "query": search_title,
                "filter": {"value": "page", "property": "object"},
                "page_size": 100,
            }
            if start_cursor:
                payload["start_cursor"] = start_cursor

            search_resp = requests.post(
                f"{NOTION_BASE_URL}/search",
                headers=headers,
                json=payload,
                timeout=15,
            )
            search_resp.raise_for_status()
            search_data = search_resp.json()

            for result in search_data.get("results", []):
                pages_checked += 1
                props = result.get("properties", {})
                for prop_val in props.values():
                    if prop_val.get("type") == "title":
                        title_text = _extract_title(prop_val)
                        if title_text.upper() == search_title.upper():
                            page_id = result["id"]
                            break
                if page_id:
                    break

            if page_id:
                break

            has_more = search_data.get("has_more", False)
            start_cursor = search_data.get("next_cursor")
    except Exception:
        return []

    if not page_id:
        return []

    # Step 2: Fetch all blocks from the page
    blocks = []
    has_more = True
    start_cursor = None

    try:
        while has_more:
            url = f"{NOTION_BASE_URL}/blocks/{page_id}/children?page_size=100"
            if start_cursor:
                url += f"&start_cursor={start_cursor}"

            resp = requests.get(url, headers=headers, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            blocks.extend(data.get("results", []))
            has_more = data.get("has_more", False)
            start_cursor = data.get("next_cursor")
    except Exception:
        return []

    # Step 3: Convert blocks to HTML
    html_parts = []
    for block in blocks:
        btype = block.get("type", "")
        bdata = block.get(btype, {})

        if btype in ("paragraph", "quote", "callout"):
            rich = bdata.get("rich_text", [])
            text_html = _extract_rich_text_html(rich)
            if text_html.strip():
                if btype == "quote":
                    html_parts.append(
                        f'<div style="border-left:3px solid #C9A84C; padding-left:12px; '
                        f'margin:8px 0; font-style:italic; color:rgba(255,255,255,0.6);">'
                        f'{text_html}</div>'
                    )
                else:
                    html_parts.append(
                        f'<div style="margin:8px 0; color:rgba(255,255,255,0.65); '
                        f'line-height:1.6; font-size:13px;">{text_html}</div>'
                    )

        elif btype.startswith("heading"):
            rich = bdata.get("rich_text", [])
            text_html = _extract_rich_text_html(rich)
            if text_html.strip():
                if btype == "heading_1":
                    # Skip the page title heading (redundant)
                    continue
                elif btype == "heading_2":
                    html_parts.append(
                        f'<div style="margin:16px 0 6px; font-size:13px; font-weight:700; '
                        f'color:rgba(255,255,255,0.75); border-bottom:1px solid rgba(255,255,255,0.06); '
                        f'padding-bottom:4px;">{text_html}</div>'
                    )
                else:  # heading_3
                    html_parts.append(
                        f'<div style="margin:12px 0 4px; font-size:12px; font-weight:600; '
                        f'color:rgba(255,255,255,0.7);">{text_html}</div>'
                    )

        elif btype == "bulleted_list_item":
            rich = bdata.get("rich_text", [])
            text_html = _extract_rich_text_html(rich)
            if text_html.strip():
                html_parts.append(
                    f'<div style="margin:4px 0 4px 16px; color:rgba(255,255,255,0.6); '
                    f'font-size:13px; line-height:1.5;">• {text_html}</div>'
                )

        elif btype == "numbered_list_item":
            rich = bdata.get("rich_text", [])
            text_html = _extract_rich_text_html(rich)
            if text_html.strip():
                html_parts.append(
                    f'<div style="margin:4px 0 4px 16px; color:rgba(255,255,255,0.6); '
                    f'font-size:13px; line-height:1.5;">{text_html}</div>'
                )

        elif btype == "divider":
            html_parts.append(
                '<div style="border-top:1px solid rgba(255,255,255,0.06); margin:12px 0;"></div>'
            )

        # Skip unsupported block types (images, embeds, etc.) silently

    return html_parts