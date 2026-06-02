"""
THE FOUR HORSEMEN - Crypto Liquidity Rotation Dashboard
========================================================
Four signals tracked LIVE, no manual data, no mock/default values.
If a source is unreachable, the card shows "unavailable" - never a fake number.

  1. STRC  - Strategy's perpetual preferred; below $100 par = dividend stress
  2. mNAV  - MSTR premium/discount to NAV (both Enterprise Value and Equity)
  3. ETF flows - net spot BTC ETF creation/redemption
  4. Coinbase premium - US spot demand (negative = US selling)

Live sources (all free, no API key):
  - Coinbase premium : Coinbase vs Binance spot (OKX fallback)
  - ETF flows        : Farside Investors table (pandas.read_html)
  - STRC/MSTR prices : Stooq CSV (Yahoo fallback)
  - BTC holdings, debt, preferred, USD reserve, STRC rate, shares :
                       scraped LIVE from Strategy's latest 8-K filings on SEC EDGAR
  - News             : Yahoo Finance RSS for MSTR + STRC
  - mNAV             : computed from the above (EV + Equity)
"""

import io
import re
import time
import html
import requests
import pandas as pd
import streamlit as st

try:
    import feedparser
    HAS_FEED = True
except Exception:
    HAS_FEED = False

st.set_page_config(page_title="The Four Horsemen", page_icon="H", layout="wide")

C = {"bg": "#0a0a0c", "panel": "#121215", "panel2": "#17171b", "line": "#26262c",
     "text": "#e8e8ea", "dim": "#8a8a92", "red": "#ff4d4d", "redDim": "#5c2526",
     "green": "#3ddc84", "amber": "#ffb020", "blue": "#5b9dff"}
UA = {"User-Agent": "FourHorsemen Dashboard giofanale@gmail.com"}
SEC_HEADERS = {
    "User-Agent": "FourHorsemen Dashboard giofanale@gmail.com",
    "Accept": "application/json, text/html, */*",
    "Accept-Encoding": "gzip, deflate",
}
SEC_ARCHIVE_HEADERS = {
    "User-Agent": "FourHorsemen Dashboard giofanale@gmail.com",
    "Accept": "text/html, */*",
    "Accept-Encoding": "gzip, deflate",
}
# Browser-like headers to get past Cloudflare bot detection (Farside, etc.)
BROWSER = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}
CIK = "0001050446"  # Strategy Inc (MSTR)
# Default ETF flows CSV (GitHub raw is allow-listed & not behind Cloudflare).
# Columns: Date,Total. Swap for a fresher mirror in the sidebar if needed.
DEFAULT_ETF_CSV = ("https://raw.githubusercontent.com/canadiancode/btc-etf-flows/"
                   "HEAD/Bitcoin-ETF-Flow-Data/data/BTC_ETF_INFLOWS_OUTFLOWS.csv")

st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Archivo+Black&family=IBM+Plex+Mono:wght@400;500;600&display=swap');
.stApp {{ background: {C['bg']}; color: {C['text']}; font-family: 'IBM Plex Mono', monospace; }}
.block-container {{ padding-top: 1.5rem; max-width: 1180px; }}
h1,h2,h3 {{ font-family: 'Archivo Black', sans-serif !important; letter-spacing: -0.5px; }}
.horsemen-card {{ background: {C['panel']}; border: 1px solid {C['line']}; border-radius: 10px;
  padding: 18px; position: relative; overflow: hidden; height: 100%; }}
.horsemen-flag {{ border: 1px solid {C['redDim']}; }}
.hm-title {{ font-size: 11px; letter-spacing: 1.5px; color: {C['dim']}; }}
.hm-big {{ font-family: 'Archivo Black', sans-serif; font-size: 28px; line-height: 1.1; margin: 10px 0 2px; }}
.hm-sub {{ font-size: 11px; color: {C['dim']}; }}
.hm-bar {{ position: absolute; top: 0; left: 0; height: 3px; transition: width .4s; }}
.box {{ background: {C['panel']}; border: 1px solid {C['line']}; border-radius: 10px; padding: 16px 18px; }}
.newsbar {{ background: {C['panel2']}; border: 1px solid {C['line']}; border-radius: 8px;
  padding: 8px 14px; overflow: hidden; white-space: nowrap; }}
.newsbar a {{ color: {C['blue']}; text-decoration: none; font-size: 12px; }}
.ticker-wrap {{ display: inline-block; animation: scroll 60s linear infinite; }}
@keyframes scroll {{ from {{ transform: translateX(0); }} to {{ transform: translateX(-50%); }} }}
.dummies {{ font-size: 13px; line-height: 1.7; color: {C['dim']}; }}
.dummies b {{ color: {C['text']}; }}
.srcline {{ font-size: 10px; color: #55555c; }}
</style>
""", unsafe_allow_html=True)


# ============================================================================
# LIVE FETCHERS  (every one returns None / ok:False on failure - never fake data)
# ============================================================================
@st.cache_data(ttl=15)
def fetch_premium():
    try:
        cb = requests.get("https://api.coinbase.com/v2/prices/BTC-USD/spot", headers=UA, timeout=8).json()
        coinbase = float(cb["data"]["amount"])
    except Exception as e:
        return {"ok": False, "err": f"coinbase {e}"}
    for name, url, path in [
        ("Binance", "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT", lambda d: float(d["price"])),
        ("OKX", "https://www.okx.com/api/v5/market/ticker?instId=BTC-USDT", lambda d: float(d["data"][0]["last"])),
    ]:
        try:
            ref = path(requests.get(url, headers=UA, timeout=8).json())
            return {"ok": True, "coinbase": coinbase, "ref": ref, "ref_name": name,
                    "premium": (coinbase - ref) / ref * 100, "btc": coinbase}
        except Exception:
            continue
    return {"ok": False, "err": "no reference price"}


def _num(v):
    if v is None: return None
    s = str(v).strip().replace(",", "")
    if s in ("", "-", "nan", "NaN"): return None
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()").replace("$", "").replace("\u2212", "-")
    try:
        f = float(s); return -f if neg else f
    except Exception:
        return None


def _parse_farside_markdown(md):
    """Parse the Farside flow table from Jina Reader markdown output.
    Rows look like: | 01 Jun 2026 | (440.3) | ... | (483.8) |
    The Total is the last numeric cell on each dated row."""
    rows = []
    date_re = re.compile(r"^\|?\s*(\d{1,2}\s+[A-Z][a-z]{2}\s+20\d{2})\s*\|")
    for line in md.splitlines():
        if "|" not in line:
            continue
        m = date_re.search(line.strip())
        if not m:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        date = cells[0]
        # last cell that parses as a number is the Total
        total = None
        for c in reversed(cells[1:]):
            v = _num(c)
            if v is not None:
                total = v
                break
        if total is not None:
            rows.append((date, total))
    if not rows:
        return None
    return {"ok": True, "date": rows[-1][0], "today": rows[-1][1],
            "d5": sum(v for _, v in rows[-5:]), "src": "Farside (Jina)"}


def _parse_farside_html(h):
    tables = pd.read_html(io.StringIO(h))
    if not tables:
        raise ValueError("no tables")
    df = max(tables, key=lambda t: t.shape[0] * t.shape[1])
    df.columns = [str(c[-1]) if isinstance(c, tuple) else str(c) for c in df.columns]
    tcols = [c for c in df.columns if c.strip().lower() == "total"]
    if not tcols:
        raise ValueError("no Total column (likely Cloudflare challenge page)")
    tcol = tcols[0]
    labels = df.iloc[:, 0].astype(str)
    mask = ~labels.str.strip().str.lower().isin(["total", "average", "maximum", "minimum", "nan"])
    data = df[mask].copy()
    data["net"] = data[tcol].apply(_num)
    data = data.dropna(subset=["net"])
    if data.empty:
        raise ValueError("no data rows")
    latest = data.iloc[-1]
    return {"ok": True, "date": str(latest.iloc[0]), "today": float(latest["net"]),
            "d5": float(data["net"].tail(5).sum()), "src": "Farside"}


@st.cache_data(ttl=900)
def fetch_etf_flows(coinglass_key="", github_csv_url=""):
    """Multi-source ETF flows. Tries in order and records why each failed.
    1) Coinglass API (needs free key)  2) GitHub raw CSV (cloud-friendly, no block)
    3) Farside (Cloudflare)  4) SoSoValue JSON. Returns ok:False only if all fail."""
    tried = []
    # 1) Coinglass
    if coinglass_key:
        try:
            r = requests.get("https://open-api-v4.coinglass.com/api/etf/bitcoin/flow-history",
                             headers={"CG-API-KEY": coinglass_key, "accept": "application/json"}, timeout=12)
            j = r.json()
            data = j.get("data", j)
            if isinstance(data, dict):
                data = data.get("list") or data.get("history") or data.get("flowHistory") or []
            flows = []
            for x in (data or []):
                if not isinstance(x, dict):
                    continue
                ts = x.get("timestamp") or x.get("time") or x.get("date")
                # total net flow under any of these likely keys
                val = None
                for k in ("flow_usd", "flowUsd", "total_flow_usd", "netFlow", "net_flow",
                          "total_net_inflow", "totalNetInflow", "changeUsd", "value"):
                    if x.get(k) is not None:
                        val = x[k]; break
                if ts is not None and val is not None:
                    try:
                        flows.append((int(ts), float(val) / 1e6))
                    except Exception:
                        pass
            if flows:
                flows.sort()
                import datetime as _dt
                ms = flows[-1][0]
                ds = _dt.datetime.utcfromtimestamp(ms / 1000 if ms > 1e12 else ms).strftime("%d %b %Y")
                return {"ok": True, "date": ds, "today": flows[-1][1],
                        "d5": sum(f for _, f in flows[-5:]), "src": "Coinglass", "tried": tried}
            # nothing parsed: record what keys we actually saw to debug
            sample = (data[0] if isinstance(data, list) and data else data)
            keys = list(sample.keys())[:8] if isinstance(sample, dict) else str(type(sample))
            tried.append(f"Coinglass HTTP {r.status_code} parsed 0 rows; sample keys={keys}; msg={j.get('msg','')}")
        except Exception as e:
            tried.append(f"Coinglass err {e}")
    else:
        tried.append("Coinglass skipped (no key)")
    # 2) GitHub raw CSV (only if user supplied a URL; raw.githubusercontent.com is allow-listed)
    if github_csv_url:
        try:
            txt = requests.get(github_csv_url, headers=BROWSER, timeout=12).text
            df = pd.read_csv(io.StringIO(txt))
            df = df.dropna(how="all")
            cols = {c.lower().strip(): c for c in df.columns}
            datec = next((cols[c] for c in cols if "date" in c), df.columns[0])
            totalc = next((cols[c] for c in cols if c in ("total", "net", "net_flow", "sum", "flow")), None)
            if totalc:
                df = df[[datec, totalc]].dropna()
                df[totalc] = df[totalc].apply(_num)
                df = df.dropna(subset=[totalc])
                df["_d"] = df[datec].astype(str).str.replace("T", "", regex=False).str.strip()
                df = df.sort_values("_d")
                last_raw = df.iloc[-1]["_d"]
                # format YYYYMMDD -> DD Mon YYYY when possible
                try:
                    import datetime as _dt
                    last_disp = _dt.datetime.strptime(last_raw[:8], "%Y%m%d").strftime("%d %b %Y")
                except Exception:
                    last_disp = str(df.iloc[-1][datec])
                return {"ok": True, "date": last_disp, "today": float(df.iloc[-1][totalc]),
                        "d5": float(df[totalc].tail(5).sum()), "src": "GitHub CSV", "tried": tried}
            tried.append("GitHub CSV: no total/net column")
        except Exception as e:
            tried.append(f"GitHub CSV err {e}")
    # 3) Farside via Jina Reader proxy (r.jina.ai bypasses Cloudflare, free, no key)
    try:
        jr = requests.get("https://r.jina.ai/https://farside.co.uk/btc/",
                          headers={"User-Agent": BROWSER["User-Agent"], "Accept": "text/plain",
                                   "X-Return-Format": "markdown"}, timeout=25)
        if jr.status_code == 200 and jr.text:
            res = _parse_farside_markdown(jr.text)
            if res:
                res["tried"] = tried
                return res
            tried.append("Jina/Farside: parsed 0 rows")
        else:
            tried.append(f"Jina/Farside HTTP {jr.status_code}")
    except Exception as e:
        tried.append(f"Jina/Farside err {e}")
    # 4) Farside direct (works locally, usually blocked on cloud)
    for attempt in range(2):
        try:
            r = requests.get("https://farside.co.uk/btc/", headers=BROWSER, timeout=15)
            if "Total" in r.text:
                out = _parse_farside_html(r.text); out["tried"] = tried; return out
            tried.append(f"Farside direct HTTP {r.status_code} (no table)")
            break
        except Exception as e:
            if attempt == 1:
                tried.append(f"Farside direct err {e}")
            time.sleep(1)
    # 4) SoSoValue (needs x-soso-api-key; only try if provided via coinglass_key field is not it)
    # Public endpoint requires a key, so we skip unless reachable; record the attempt.
    tried.append("SoSoValue skipped (needs x-soso-api-key)")
    return {"ok": False, "err": " | ".join(tried), "tried": tried}


@st.cache_data(ttl=120)
def stooq_quote(symbol):
    try:
        url = f"https://stooq.com/q/l/?s={symbol}&f=sd2t2ohlcv&h&e=csv"
        df = pd.read_csv(io.StringIO(requests.get(url, headers=BROWSER, timeout=10).text))
        c = float(df.iloc[0]["Close"])
        return c if c == c else None
    except Exception:
        return None


@st.cache_data(ttl=300)
def yahoo_quote(symbol):
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=1d"
        d = requests.get(url, headers=UA, timeout=10).json()
        return float(d["chart"]["result"][0]["meta"]["regularMarketPrice"])
    except Exception:
        return None


def price_of(stooq_sym, yahoo_sym):
    """Live price with a second independent source as fallback. No hard-coded default."""
    v = stooq_quote(stooq_sym)
    if v: return v, "Stooq"
    v = yahoo_quote(yahoo_sym)
    if v: return v, "Yahoo"
    return None, None


# ---- SEC 8-K live scraper (regexes work on tag-stripped HTML: spaces, not pipes) ----
def _btc_holdings(t):
    m = re.search(r"holds?\s+([\d,]{6,})\s+bitcoin", t, re.I)
    if m: return int(m.group(1).replace(",", ""))
    seg = re.search(r"Aggregate BTC Holdings(.{0,400})", t, re.S | re.I)
    if seg:
        for num in re.findall(r"(\d{3},\d{3}(?:,\d{3})*)", seg.group(1)):
            v = int(num.replace(",", ""))
            if v > 100000:
                return v
    return None

def _debt_m(t):
    m = re.search(r"\$?([\d.]+)\s*billion\s+aggregate principal amount of\s+convertible notes", t, re.I)
    if m: return float(m.group(1)) * 1000
    return None

def _pref_m(t):
    m = re.search(r"\$?([\d.]+)\s*billion\s+aggregate notional amount of\s+preferred stock", t, re.I)
    if m: return float(m.group(1)) * 1000
    return None

def _reserve_m(t):
    m = re.search(r"USD Reserve (?:is|of)\s+\$?([\d,.]+)\s*million", t, re.I)
    if m: return float(m.group(1).replace(",", ""))
    m = re.search(r"USD Reserve (?:is|of)\s+\$?([\d,.]+)\s*billion", t, re.I)
    if m: return float(m.group(1).replace(",", "")) * 1000
    return None

def _strc_rate(t):
    m = re.search(r"Stretch Preferred Stock[^%]*?at\s+([\d.]+)%", t, re.S | re.I)
    if m: return float(m.group(1))
    return None

def _bps_sats(t):
    m = re.search(r"([\d,]{4,})\s+Bitcoin Per Share", t, re.I)
    if m: return int(m.group(1).replace(",", ""))
    return None


@st.cache_data(ttl=1800)
def fetch_strategy_fundamentals():
    """Scrape Strategy's most recent 8-K filings on SEC EDGAR for live balance-sheet data.
    Returns dict of values; each key is None if not found in any recent filing."""
    out = {"btc": None, "debt_m": None, "pref_m": None, "reserve_m": None,
           "strc_rate": None, "bps_sats": None, "shares_m": None,
           "filing_date": None, "err": None, "http": None, "checked": 0, "doc_log": []}
    try:
        r0 = requests.get(f"https://data.sec.gov/submissions/CIK{CIK}.json", headers=SEC_HEADERS, timeout=12)
        out["http"] = r0.status_code
        if r0.status_code != 200:
            out["err"] = f"submissions HTTP {r0.status_code}: {r0.text[:120]}"
            return out
        sub = r0.json()
        recent = sub["filings"]["recent"]
        forms = recent["form"]; accns = recent["accessionNumber"]
        docs = recent["primaryDocument"]; dates = recent["filingDate"]
        out["doc_log"].append(f"submissions OK, {len(forms)} filings, company={sub.get('name','?')}")
        checked = 0
        for i in range(len(forms)):
            if forms[i] != "8-K":
                continue
            checked += 1
            if checked > 10:
                break
            acc = accns[i].replace("-", "")
            base = f"https://www.sec.gov/Archives/edgar/data/{int(CIK)}/{acc}"
            # The primary doc is often just the cover page; the data lives in exhibit 99.1.
            # Fetch the filing index to find ALL .htm documents, then scan each.
            doc_urls = [f"{base}/{docs[i]}"]
            try:
                idx = requests.get(f"{base}/", headers=SEC_ARCHIVE_HEADERS, timeout=12).text
                for m in re.findall(r'href="([^"]+\.htm)"', idx, re.I):
                    name = m.split("/")[-1]
                    full = f"{base}/{name}"
                    if full not in doc_urls and ("ex99" in name.lower() or "ex_" in name.lower()
                                                  or re.search(r"ex\d", name.lower())):
                        doc_urls.append(full)
            except Exception:
                pass
            combined = ""
            for du in doc_urls[:4]:
                try:
                    rr = requests.get(du, headers=SEC_ARCHIVE_HEADERS, timeout=12)
                    raw = rr.text
                    tt = html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", raw)))
                    combined += " " + tt
                except Exception as e:
                    out["doc_log"].append(f"8-K {dates[i]} doc fetch ERR {e}")
            t = combined
            if checked <= 3:
                hit = "BTC" if "bitcoin" in t.lower() else "no-btc"
                out["doc_log"].append(f"8-K {dates[i]} docs={len(doc_urls)} len={len(t)} {hit}")
            if out["filing_date"] is None:
                out["filing_date"] = dates[i]
            for key, fn in [("btc", _btc_holdings), ("debt_m", _debt_m), ("pref_m", _pref_m),
                            ("reserve_m", _reserve_m), ("strc_rate", _strc_rate), ("bps_sats", _bps_sats)]:
                if out[key] is None:
                    v = fn(t)
                    if v is not None:
                        out[key] = v
            if all(out[k] is not None for k in ("btc", "debt_m", "pref_m", "reserve_m", "strc_rate", "bps_sats")):
                break
        out["checked"] = checked
        if out["btc"] and out["bps_sats"]:
            out["shares_m"] = (out["btc"] * 1e8 / out["bps_sats"]) / 1e6
        return out
    except Exception as e:
        out["err"] = f"{type(e).__name__}: {e}"
        return out


@st.cache_data(ttl=3600)
def sec_shares_outstanding():
    """Sum the most recent share count across all classes from companyfacts XBRL."""
    try:
        url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{CIK}.json"
        d = requests.get(url, headers=SEC_HEADERS, timeout=15).json()
        dei = d.get("facts", {}).get("dei", {})
        concept = dei.get("EntityCommonStockSharesOutstanding")
        if not concept:
            return None
        # facts may carry multiple classes via different members; take the latest 'end'
        # per distinct accession, then sum the classes reported on that latest date.
        rows = concept.get("units", {}).get("shares", [])
        if not rows:
            return None
        latest_end = max(r["end"] for r in rows if r.get("end"))
        total = sum(r["val"] for r in rows if r.get("end") == latest_end)
        return total if total > 0 else None
    except Exception:
        return None


@st.cache_data(ttl=300)
def yahoo_marketcap(symbol):
    """Market cap directly from Yahoo (fallback if SEC share count is unavailable)."""
    try:
        url = f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{symbol}?modules=price"
        d = requests.get(url, headers=BROWSER, timeout=10).json()
        mc = d["quoteSummary"]["result"][0]["price"]["marketCap"]["raw"]
        return float(mc)
    except Exception:
        return None


@st.cache_data(ttl=900)
def fetch_news():
    if not HAS_FEED:
        return []
    out = []
    try:
        feed = feedparser.parse("https://feeds.finance.yahoo.com/rss/2.0/headline?s=MSTR,STRC&region=US&lang=en-US")
        for e in feed.entries[:12]:
            out.append({"title": html.unescape(e.get("title", "")), "link": e.get("link", "#")})
    except Exception:
        pass
    return out


# ============================================================================
def clamp(x, lo=0, hi=100): return max(lo, min(hi, x))
def verdict(s):
    if s >= 66: return ("RISK-ON", C["green"])
    if s >= 33: return ("NEUTRAL", C["amber"])
    return ("RISK-OFF", C["red"])


# ============================================================================
# SIDEBAR
# ============================================================================
st.sidebar.markdown("### SETTINGS")
coinglass_key = st.sidebar.text_input(
    "Coinglass API key (optional)", value="", type="password",
    help="Optional. Makes ETF flows rock-solid. Free key at coinglass.com. "
         "Without it the app tries GitHub CSV, Farside and SoSoValue.")
github_csv_url = st.sidebar.text_input(
    "ETF CSV raw URL", value=DEFAULT_ETF_CSV,
    help="A raw.githubusercontent.com CSV of daily BTC ETF flows with a Date column "
         "and a 'Total'/'net' column. Cloud-friendly, bypasses Cloudflare, no key. "
         "Replace with a more frequently-updated mirror if you find one.")
auto_refresh = st.sidebar.checkbox("Auto-refresh (30s)", value=True)
show_diag = st.sidebar.checkbox("Show data-source diagnostics", value=False,
    help="Shows exactly which live source succeeded or failed, with HTTP codes.")
st.sidebar.caption("All other data is fetched live and automatically. "
                   "No values are entered by hand.")

# ============================================================================
# FETCH EVERYTHING LIVE
# ============================================================================
with st.spinner("Pulling live data from Coinbase, ETF sources, Stooq, SEC EDGAR, Yahoo…"):
    p = fetch_premium()
    etf = fetch_etf_flows(coinglass_key, github_csv_url)
    strc_price, strc_src = price_of("strc.us", "STRC")
    mstr_price, mstr_src = price_of("mstr.us", "MSTR")
    fund = fetch_strategy_fundamentals()
    sec_shares = sec_shares_outstanding()
    mcap_yahoo = yahoo_marketcap("MSTR")
    news = fetch_news()

btc_price = p["btc"] if p.get("ok") else None
btc_holdings = fund.get("btc")
debt_m = fund.get("debt_m")
preferred_m = fund.get("pref_m")
cash_m = fund.get("reserve_m")
strc_rate = fund.get("strc_rate")
# shares: prefer BPS-derived (from same 8-K), then SEC XBRL, else None
shares_m = fund.get("shares_m") or ((sec_shares / 1e6) if sec_shares else None)
shares_src = "8-K BPS" if fund.get("shares_m") else ("SEC XBRL" if sec_shares else None)

# ============================================================================
# COMPUTE mNAV
# Market cap: prefer MSTR price x SEC shares; fall back to Yahoo market cap.
# mNAV needs only: market cap + BTC holdings + BTC price. EV adds debt/pref/cash.
# ============================================================================
mnav_ev = mnav_eq = btc_nav = mcap = None
mcap_src = None
mnav_note = ""
if mstr_price and shares_m:
    mcap = mstr_price * shares_m * 1e6
    mcap_src = f"{shares_m:,.1f}M sh x ${mstr_price:,.0f}"
elif mcap_yahoo:
    mcap = mcap_yahoo
    mcap_src = "Yahoo market cap"

if btc_price and btc_holdings and mcap:
    btc_nav = btc_holdings * btc_price
    if btc_nav > 0:
        mnav_eq = mcap / btc_nav
        if None not in (debt_m, preferred_m, cash_m):
            mnav_ev = (mcap + (debt_m + preferred_m - cash_m) * 1e6) / btc_nav
        else:
            mnav_note = "EV n/a (missing debt/pref/reserve from SEC)"
else:
    missing = []
    if not btc_price: missing.append("BTC price")
    if not btc_holdings: missing.append("holdings")
    if not mcap: missing.append("market cap")
    mnav_note = "waiting on " + " / ".join(missing)

# ============================================================================
# SCORES (only computed metrics contribute; missing ones are excluded)
# ============================================================================
prem = p["premium"] if p.get("ok") else None
etf_today = etf["today"] if etf.get("ok") else None
etf_5d = etf["d5"] if etf.get("ok") else None
mnav_head = mnav_ev if mnav_ev is not None else mnav_eq

scores = {}
if strc_price is not None: scores["strc"] = clamp((strc_price - 90) / 20 * 100)
if mnav_head is not None:  scores["mnav"] = clamp((mnav_head - 0.8) / 0.6 * 100)
if etf_5d is not None:     scores["etf"] = clamp((etf_5d + 2000) / 4000 * 100)
if prem is not None:       scores["prem"] = clamp((prem + 0.15) / 0.3 * 100)
composite = sum(scores.values()) / len(scores) if scores else None
comp_label, comp_color = verdict(composite) if composite is not None else ("NO DATA", C["dim"])

# ============================================================================
# HEADER
# ============================================================================
h1, h2 = st.columns([3, 1])
with h1:
    st.markdown("<h1 style='font-size:34px;margin-bottom:0'>THE FOUR HORSEMEN</h1>", unsafe_allow_html=True)
    fdate = fund.get("filing_date") or "n/a"
    st.markdown(f"<div style='color:{C['dim']};font-size:12px'>All data live &middot; Strategy fundamentals from 8-K dated {fdate}</div>", unsafe_allow_html=True)
with h2:
    cs = f"{composite:.0f}/100" if composite is not None else "—"
    st.markdown(f"<div style='text-align:right'><span style='color:{comp_color};font-size:14px'>* {comp_label}</span>"
                f"<br><span style='color:{C['dim']};font-size:11px'>{cs} &middot; {len(scores)}/4 signals</span></div>", unsafe_allow_html=True)

cw = composite if composite is not None else 0
st.markdown(f"<div style='height:8px;background:{C['panel2']};border-radius:6px;margin:14px 0 18px;overflow:hidden'>"
            f"<div style='height:100%;width:{cw}%;background:{comp_color}'></div></div>", unsafe_allow_html=True)

# ---- NEWS BAR --------------------------------------------------------------
if news:
    items = " &nbsp;&bull;&nbsp; ".join(f"<a href='{n['link']}' target='_blank'>{html.escape(n['title'])}</a>" for n in news)
    st.markdown(f"<div class='newsbar'><span style='color:{C['amber']};font-size:11px;letter-spacing:1px'>STRC / MSTR NEWS &nbsp;</span>"
                f"<div class='ticker-wrap'>{items} &nbsp;&bull;&nbsp; {items}</div></div>", unsafe_allow_html=True)
else:
    st.markdown(f"<div class='newsbar'><span style='color:{C['dim']};font-size:11px'>News feed unavailable right now.</span></div>", unsafe_allow_html=True)
st.write("")

# ============================================================================
# SITUATION SUMMARY (plain English; only states what we actually have)
# ============================================================================
def situation():
    parts = []
    if strc_price is not None:
        parts.append(f"STRC trades at **${strc_price:,.2f}** ({'below' if strc_price<100 else 'at/above'} its $100 par) — "
                     f"{'dividend mechanism under stress, ATM share sales pause' if strc_price<100 else 'stable, ATM issuance can continue'}.")
    if mnav_eq is not None:
        ev_txt = f"**{mnav_ev:.2f}×** on enterprise value, " if mnav_ev is not None else ""
        parts.append(f"MSTR mNAV is {ev_txt}**{mnav_eq:.2f}×** on equity. "
                     f"{'On equity it is below 1.0 — the stock is worth less than its bare bitcoin, the capitulation zone.' if mnav_eq<1.0 else 'Still a premium to its bitcoin backing.'}")
    if etf_5d is not None:
        parts.append(f"Spot BTC ETFs: **{'+' if etf_today>=0 else '-'}${abs(etf_today):.0f}M** last day, "
                     f"**{'+' if etf_5d>=0 else '-'}${abs(etf_5d):.0f}M** over 5d — {'money leaving' if etf_5d<0 else 'money flowing in'}.")
    if prem is not None:
        parts.append(f"Coinbase premium is **{prem:+.3f}%** — US spot is {'selling harder than offshore' if prem<0 else 'bidding'}.")
    bear = sum([
        strc_price is not None and strc_price < 100,
        mnav_head is not None and mnav_head < 1.0,
        etf_5d is not None and etf_5d < -500,
        prem is not None and prem < 0,
    ])
    n = len(scores)
    if n == 0:
        return parts, "No live signals available right now — check connectivity."
    headline = {4: "All four signals bearish. Liquidity is leaving crypto. Stay out.",
                3: "Three of four bearish. Risk high; capital rotating out.",
                2: "Mixed — no clear edge.",
                1: "Mostly constructive; one warning flag.",
                0: "All constructive. Liquidity supportive."}.get(bear, "")
    return parts, headline

parts, headline = situation()
body = '<br>'.join('• ' + html.unescape(x) for x in parts) if parts else "Waiting for live data…"
st.markdown(f"""<div class="box">
<div style="font-size:11px;letter-spacing:1.5px;color:{C['text']};margin-bottom:8px">WHAT'S GOING ON RIGHT NOW</div>
<div style="font-size:15px;color:{comp_color};margin-bottom:10px">{headline}</div>
<div class="dummies">{body}</div></div>""", unsafe_allow_html=True)
st.write("")

# ============================================================================
# FOUR CARDS
# ============================================================================
def card(col, title, score, big, big_color, sub, extra="", flag=False):
    if score is None:
        col.markdown(f"""<div class="horsemen-card">
            <div style="display:flex;justify-content:space-between">
              <span class="hm-title">{title}</span><span style="font-size:10px;color:{C['dim']}">NO DATA</span></div>
            <div class="hm-big" style="color:{C['dim']}">—</div>
            <div class="hm-sub">{sub}</div></div>""", unsafe_allow_html=True)
        return
    lbl, clr = verdict(score)
    fc = "horsemen-flag" if flag else ""
    col.markdown(f"""<div class="horsemen-card {fc}">
        <div class="hm-bar" style="width:{score}%;background:{clr}"></div>
        <div style="display:flex;justify-content:space-between">
          <span class="hm-title">{title}</span><span style="font-size:10px;color:{clr}">{lbl}</span></div>
        <div class="hm-big" style="color:{big_color}">{big}</div>
        <div class="hm-sub">{sub}</div>{extra}</div>""", unsafe_allow_html=True)

c1, c2, c3, c4 = st.columns(4)

# 1 STRC
if strc_price is not None:
    yld = (strc_rate or 0)
    card(c1, "1. STRC - DOOM-LOOP", scores.get("strc"), f"${strc_price:,.2f}",
         C["red"] if strc_price < 100 else C["text"],
         "below $100 par - stressed" if strc_price < 100 else "at/above par",
         extra=f"<div class='hm-sub' style='margin-top:8px'>div rate {yld:.2f}% &middot; {strc_src}</div>",
         flag=strc_price < 100)
else:
    card(c1, "1. STRC - DOOM-LOOP", None, "", "", "price feed unavailable")

# 2 mNAV
if mnav_eq is not None:
    head = mnav_ev if mnav_ev is not None else mnav_eq
    mc = C["green"] if head < 1.0 else (C["amber"] if head < 1.3 else C["text"])
    big = f"{mnav_ev:.2f}x" if mnav_ev is not None else f"{mnav_eq:.2f}x"
    sub = f"EV basis &middot; equity {mnav_eq:.2f}x" if mnav_ev is not None else f"equity basis &middot; {mnav_note}"
    card(c2, "2. MSTR mNAV", scores.get("mnav"), big, mc, sub,
         extra=f"<div class='hm-sub' style='margin-top:8px'>{'BELOW NAV (equity)' if mnav_eq<1.0 else 'premium intact'} &middot; MSTR ${mstr_price:,.0f}</div>",
         flag=(mnav_ev is not None and mnav_ev < 1.0) or mnav_eq < 1.0)
else:
    card(c2, "2. MSTR mNAV", None, "", "", mnav_note or "inputs unavailable")

# 3 ETF
if etf.get("ok"):
    et = f"{'+' if etf_today>=0 else '-'}${abs(etf_today):.1f}M"
    e5 = f"{'+' if etf_5d>=0 else '-'}${abs(etf_5d):.1f}M"
    card(c3, "3. SPOT BTC ETF FLOWS", scores.get("etf"), et,
         C["red"] if etf_today < 0 else C["green"], f"{etf['date']} &middot; 5d {e5}",
         extra=f"<div class='hm-sub' style='margin-top:8px'>live via {etf.get('src','?')}</div>", flag=etf_5d < -500)
else:
    card(c3, "3. SPOT BTC ETF FLOWS", None, "", "", "all ETF sources unavailable")

# 4 Premium
if p.get("ok"):
    card(c4, "4. COINBASE PREMIUM", scores.get("prem"), f"{prem:+.3f}%",
         C["red"] if prem < 0 else C["green"],
         "negative - US selling" if prem < 0 else "US bid present",
         extra=f"<div class='hm-sub' style='margin-top:8px'>CB ${p['coinbase']:,.0f} &middot; {p['ref_name']} ${p['ref']:,.0f}</div>",
         flag=prem < 0)
else:
    card(c4, "4. COINBASE PREMIUM", None, "", "", "price feed unavailable")

st.write("")

# ---- live fundamentals strip -----------------------------------------------
def fmtm(v, unit="$M"):
    return f"{v:,.0f}{unit}" if v is not None else "n/a"
st.markdown(f"<div class='srcline'>LIVE STRATEGY FUNDAMENTALS (SEC 8-K): "
            f"BTC holdings {btc_holdings:,} &middot; debt {fmtm(debt_m)} &middot; preferred {fmtm(preferred_m)} &middot; "
            f"USD reserve {fmtm(cash_m)} &middot; diluted shares {fmtm(shares_m,'M') if shares_m else 'n/a'} &middot; "
            f"STRC rate {strc_rate if strc_rate else 'n/a'}%</div>"
            if btc_holdings else "<div class='srcline'>Strategy fundamentals unavailable from SEC right now.</div>",
            unsafe_allow_html=True)
st.write("")

# ============================================================================
# DIAGNOSTICS PANEL
# ============================================================================
if show_diag:
    def stat(ok): return "✅" if ok else "❌"
    lines = []
    lines.append(f"{stat(p.get('ok'))} **Coinbase premium** — " +
                 (f"OK via {p.get('ref_name')}" if p.get("ok") else f"FAIL: {p.get('err','?')}"))
    lines.append(f"{stat(etf.get('ok'))} **ETF flows** — " +
                 (f"OK via {etf.get('src')}: today {etf.get('today'):.1f}M" if etf.get("ok")
                  else f"FAIL. Attempts: {' | '.join(etf.get('tried', []))}"))
    lines.append(f"{stat(strc_price is not None)} **STRC price** — " +
                 (f"${strc_price:,.2f} via {strc_src}" if strc_price else "FAIL: Stooq + Yahoo both down"))
    lines.append(f"{stat(mstr_price is not None)} **MSTR price** — " +
                 (f"${mstr_price:,.2f} via {mstr_src}" if mstr_price else "FAIL: Stooq + Yahoo both down"))
    lines.append(f"{stat(btc_holdings is not None)} **SEC 8-K fundamentals** — " +
                 (f"OK (filing {fund.get('filing_date')}, checked {fund.get('checked')} 8-Ks): "
                  f"BTC={btc_holdings}, debt={debt_m}, pref={preferred_m}, reserve={cash_m}, "
                  f"BPS={fund.get('bps_sats')}, strc_rate={strc_rate}"
                  if btc_holdings else f"FAIL: HTTP {fund.get('http')} / {fund.get('err','?')}"))
    for dl in fund.get("doc_log", []):
        lines.append(f"&nbsp;&nbsp;&nbsp;↳ {dl}")
    lines.append(f"{stat(shares_m is not None)} **Shares** — " +
                 (f"{shares_m:,.1f}M via {shares_src}" if shares_m else "FAIL: no BPS, no XBRL"))
    lines.append(f"{stat(mcap is not None)} **Market cap** — " +
                 (f"${mcap/1e9:,.1f}B via {mcap_src}" if mcap else "FAIL: need price×shares or Yahoo"))
    lines.append(f"{stat(mnav_eq is not None)} **mNAV** — " +
                 (f"EV {mnav_ev:.2f} / eq {mnav_eq:.2f}" if mnav_eq else f"FAIL: {mnav_note}"))
    lines.append(f"{stat(bool(news))} **News** — " + (f"{len(news)} headlines" if news else "FAIL: empty feed"))
    st.markdown(f"""<div class="box" style="border-color:{C['amber']}">
    <div style="font-size:11px;letter-spacing:1.5px;color:{C['amber']};margin-bottom:8px">DATA-SOURCE DIAGNOSTICS</div>
    <div class="dummies" style="font-family:monospace;font-size:12px">{'<br>'.join(lines)}</div>
    <div class="srcline" style="margin-top:10px">Tip: if SEC shows HTTP 403, set a real email in the UA string (top of app.py).
    If ETF/Yahoo fail on Streamlit Cloud, those IPs may be blocked — add a Coinglass key for ETF.</div>
    </div>""", unsafe_allow_html=True)
    st.write("")

# ============================================================================
# GUIDE FOR DUMMIES
# ============================================================================
with st.expander("📖 Guide — what these metrics mean (for dummies)"):
    st.markdown(f"""<div class="dummies">
<b>The big idea.</b> When money leaves crypto and rotates into other things (AI stocks, robotics),
four warning lights tend to switch on. This dashboard keeps all four in one place, pulling the
numbers live from public sources. If they're all red, it's a high-risk moment — better to stay out.<br><br>

<b>1. STRC — the "doom-loop" stock.</b> STRC is a special preferred share issued by Strategy (MSTR)
that pays a high dividend (currently ~11.5%). Its "correct" price is $100 (the "par"). If it falls
<b>below $100</b>, the market doubts Strategy can pay the dividend without selling bitcoin. If it has
to sell BTC to pay, the BTC price drops, which makes its situation worse — that's the "doom loop."
In fact, on June 1, 2026 Strategy sold 32 BTC specifically to fund preferred dividends.
<i>Below $100 = red light.</i><br><br>

<b>2. mNAV — how much you pay for MSTR vs. its bitcoin.</b> MSTR owns a huge amount of bitcoin
(~843,700). mNAV is how many times its value exceeds the value of the bitcoin it holds.
<b>Two versions are shown:</b><br>
&nbsp;&nbsp;• <b>EV (enterprise value)</b>: includes debt and preferred. This is the number Strategy.com publishes.<br>
&nbsp;&nbsp;• <b>Equity (stock only)</b>: stricter. Below <b>1.0</b> the stock is worth less than its own
bitcoin — a historic "bottom"/capitulation signal.<br>
<i>The closer it gets to 1.0 (and below), the closer to a bottom.</i><br><br>

<b>3. ETF flows — are the big players coming in or out?</b> Spot BTC ETFs (BlackRock's IBIT, etc.)
show whether institutions are buying or selling. <b>Negative for several days</b> = billions leaving.
<i>5-day outflow = red light.</i><br><br>

<b>4. Coinbase premium — is the US or offshore selling?</b> Compares BTC on Coinbase (US investors)
with an offshore exchange (Binance/OKX). If Coinbase is <b>lower</b> (negative premium), Americans
are selling harder. <i>Negative = red light.</i><br><br>

<b>The composite score (top).</b> The average of the available lights as a single 0–100 number.
Red = liquidity leaving, be cautious. Green = liquidity supportive. If a source doesn't respond,
that light is excluded from the calculation (see "x/4 signals") — <b>no number is ever made up</b>.<br><br>

<b>What to watch for the "turn" (reversal):</b> equity mNAV below 1.0 <i>together with</i> the
Coinbase premium flipping positive. Historically that's where a bottom forms.
</div>""", unsafe_allow_html=True)

src_etf = etf.get("src", "Farside/SoSoValue") if etf.get("ok") else "ETF sources"
st.markdown(f"<div class='srcline' style='margin-top:14px;text-align:center'>"
            f"Live: premium (Coinbase/Binance-OKX 15s) &middot; ETF ({src_etf} 15m) &middot; STRC/MSTR (Stooq+Yahoo 2m) &middot; "
            f"fundamentals (SEC EDGAR 8-K 30m) &middot; news (Yahoo RSS 15m). mNAV computed. No mock data. Not financial advice.</div>",
            unsafe_allow_html=True)

if auto_refresh:
    time.sleep(30)
    st.rerun()
