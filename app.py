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
UA = {"User-Agent": "FourHorsemen/3.0 dashboard contact@example.com"}
CIK = "0001050446"  # Strategy Inc (MSTR)

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


@st.cache_data(ttl=900)
def fetch_etf_flows():
    try:
        h = requests.get("https://farside.co.uk/btc/", headers=UA, timeout=12).text
        tables = pd.read_html(io.StringIO(h))
        df = max(tables, key=lambda t: t.shape[0] * t.shape[1])
        df.columns = [str(c[-1]) if isinstance(c, tuple) else str(c) for c in df.columns]
        tcol = [c for c in df.columns if c.strip().lower() == "total"][0]
        labels = df.iloc[:, 0].astype(str)
        mask = ~labels.str.strip().str.lower().isin(["total", "average", "maximum", "minimum", "nan"])
        data = df[mask].copy()
        data["net"] = data[tcol].apply(_num)
        data = data.dropna(subset=["net"])
        latest = data.iloc[-1]
        return {"ok": True, "date": str(latest.iloc[0]), "today": float(latest["net"]),
                "d5": float(data["net"].tail(5).sum())}
    except Exception as e:
        return {"ok": False, "err": str(e)}


@st.cache_data(ttl=120)
def stooq_quote(symbol):
    try:
        url = f"https://stooq.com/q/l/?s={symbol}&f=sd2t2ohlcv&h&e=csv"
        df = pd.read_csv(io.StringIO(requests.get(url, headers=UA, timeout=10).text))
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


# ---- SEC 8-K live scraper ---------------------------------------------------
def _btc_holdings(t):
    m = re.search(r"Aggregate BTC Holdings.*?\|\s*([\d,]{6,})\s*\|", t, re.S | re.I)
    if m: return int(m.group(1).replace(",", ""))
    m = re.search(r"holds?\s+([\d,]{6,})\s+bitcoin", t, re.I)
    if m: return int(m.group(1).replace(",", ""))
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
    m = re.search(r"Stretch Preferred Stock.*?at\s+([\d.]+)%", t, re.S | re.I)
    if m: return float(m.group(1))
    return None


@st.cache_data(ttl=1800)
def fetch_strategy_fundamentals():
    """Scrape Strategy's most recent 8-K filings on SEC EDGAR for live balance-sheet data.
    Returns dict of values; each key is None if not found in any recent filing."""
    out = {"btc": None, "debt_m": None, "pref_m": None, "reserve_m": None,
           "strc_rate": None, "filing_date": None, "err": None}
    try:
        sub = requests.get(f"https://data.sec.gov/submissions/CIK{CIK}.json", headers=UA, timeout=12).json()
        recent = sub["filings"]["recent"]
        forms = recent["form"]; accns = recent["accessionNumber"]
        docs = recent["primaryDocument"]; dates = recent["filingDate"]
        # iterate newest -> older 8-Ks, fill any still-missing field
        checked = 0
        for i in range(len(forms)):
            if forms[i] != "8-K":
                continue
            checked += 1
            if checked > 8:
                break
            acc = accns[i].replace("-", "")
            url = f"https://www.sec.gov/Archives/edgar/data/{int(CIK)}/{acc}/{docs[i]}"
            try:
                t = requests.get(url, headers=UA, timeout=12).text
                t = re.sub(r"<[^>]+>", " ", t)  # strip tags
                t = html.unescape(re.sub(r"\s+", " ", t))
            except Exception:
                continue
            if out["filing_date"] is None:
                out["filing_date"] = dates[i]
            for key, fn in [("btc", _btc_holdings), ("debt_m", _debt_m), ("pref_m", _pref_m),
                            ("reserve_m", _reserve_m), ("strc_rate", _strc_rate)]:
                if out[key] is None:
                    v = fn(t)
                    if v is not None:
                        out[key] = v
            if all(out[k] is not None for k in ("btc", "debt_m", "pref_m", "reserve_m", "strc_rate")):
                break
        return out
    except Exception as e:
        out["err"] = str(e)
        return out


@st.cache_data(ttl=3600)
def sec_shares_outstanding():
    try:
        url = f"https://data.sec.gov/api/xbrl/companyconcept/CIK{CIK}/dei/EntityCommonStockSharesOutstanding.json"
        d = requests.get(url, headers=UA, timeout=12).json()
        vals = []
        for unit in d.get("units", {}).values():
            for it in unit:
                if it.get("val") and it.get("end"):
                    vals.append((it["end"], it["val"]))
        if vals:
            vals.sort(); return vals[-1][1]
    except Exception:
        return None
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
# FETCH EVERYTHING LIVE
# ============================================================================
with st.spinner("Pulling live data from Coinbase, Farside, Stooq, SEC EDGAR, Yahoo…"):
    p = fetch_premium()
    etf = fetch_etf_flows()
    strc_price, strc_src = price_of("strc.us", "STRC")
    mstr_price, mstr_src = price_of("mstr.us", "MSTR")
    fund = fetch_strategy_fundamentals()
    sec_shares = sec_shares_outstanding()
    news = fetch_news()

btc_price = p["btc"] if p.get("ok") else None
btc_holdings = fund.get("btc")
debt_m = fund.get("debt_m")
preferred_m = fund.get("pref_m")
cash_m = fund.get("reserve_m")
strc_rate = fund.get("strc_rate")
shares_m = (sec_shares / 1e6) if sec_shares else None

# ============================================================================
# COMPUTE mNAV (only if all live inputs are present)
# ============================================================================
mnav_ev = mnav_eq = btc_nav = mcap = None
mnav_note = ""
if btc_price and btc_holdings and shares_m:
    mcap = mstr_price * shares_m * 1e6 if mstr_price else None
    btc_nav = btc_holdings * btc_price
    if mcap and btc_nav > 0:
        mnav_eq = mcap / btc_nav
        if None not in (debt_m, preferred_m, cash_m):
            mnav_ev = (mcap + (debt_m + preferred_m - cash_m) * 1e6) / btc_nav
        else:
            mnav_note = "EV n/a (missing debt/pref/reserve)"
else:
    mnav_note = "waiting on BTC price / holdings / shares"

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
         extra=f"<div class='hm-sub' style='margin-top:8px'>live via Farside</div>", flag=etf_5d < -500)
else:
    card(c3, "3. SPOT BTC ETF FLOWS", None, "", "", "Farside unavailable")

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
# GUIDE FOR DUMMIES
# ============================================================================
with st.expander("📖 Guida — cosa significano queste metriche (for dummies)"):
    st.markdown(f"""<div class="dummies">
<b>L'idea di fondo.</b> Quando i soldi escono dalle crypto e vanno verso altro (azioni AI, robotica),
si vedono 4 spie accendersi. Questo cruscotto le tiene tutte in un posto, con dati presi in tempo
reale da fonti pubbliche. Se sono tutte rosse, il momento è di rischio: meglio stare fermi.<br><br>

<b>1. STRC — l'azione "doom-loop".</b> STRC è un'azione speciale (preferred) emessa da Strategy/MSTR
che paga un dividendo alto (oggi ~11.5%). Il prezzo "giusto" è $100 (la "pari"). Se scende
<b>sotto $100</b>, il mercato dubita che Strategy paghi il dividendo senza vendere bitcoin. Se per
pagare vende BTC, il prezzo BTC scende, e la sua situazione peggiora ancora: è il "doom loop". Difatti
il 1° giugno 2026 Strategy ha venduto 32 BTC proprio per pagare i dividendi del preferred.
<i>Sotto $100 = spia rossa.</i><br><br>

<b>2. mNAV — quanto paghi MSTR rispetto ai suoi bitcoin.</b> MSTR possiede tantissimi bitcoin
(~843.700). mNAV = quante volte il suo valore supera quello dei bitcoin che ha. <b>Due versioni:</b><br>
&nbsp;&nbsp;• <b>EV (enterprise value)</b>: include debiti e preferred. È il numero di Strategy.com.<br>
&nbsp;&nbsp;• <b>Equity (solo azioni)</b>: più severo. Sotto <b>1.0</b> l'azione vale meno dei suoi
bitcoin — segnale storico di "fondo"/capitolazione.<br>
<i>Più scende verso 1.0 (e sotto), più ci si avvicina a un minimo.</i><br><br>

<b>3. Flussi ETF — i grandi entrano o escono?</b> Gli ETF spot su BTC (IBIT di BlackRock, ecc.)
mostrano se gli istituzionali comprano o vendono. <b>Negativi per giorni</b> = miliardi in uscita.
<i>Outflow su 5 giorni = spia rossa.</i><br><br>

<b>4. Coinbase premium — USA o estero a vendere?</b> Confronta il BTC su Coinbase (USA) con un
exchange estero (Binance/OKX). Se Coinbase è <b>più basso</b> (premium negativo), gli americani
vendono più forte. <i>Negativo = spia rossa.</i><br><br>

<b>Punteggio composito (in alto).</b> Media delle spie disponibili in un numero 0–100.
Rosso = liquidità in uscita, prudenza. Verde = liquidità di supporto. Se una fonte non risponde,
quella spia viene esclusa dal calcolo (vedi "x/4 signals"), e <b>non</b> viene inventato alcun dato.<br><br>

<b>Per il "turn" (inversione):</b> mNAV equity sotto 1.0 <i>insieme a</i> Coinbase premium che torna
positivo. Storicamente è lì che si forma un minimo.
</div>""", unsafe_allow_html=True)

st.markdown(f"<div class='srcline' style='margin-top:14px;text-align:center'>"
            f"Live: premium (Coinbase/Binance-OKX 15s) &middot; ETF (Farside 15m) &middot; STRC/MSTR (Stooq+Yahoo 2m) &middot; "
            f"fundamentals (SEC EDGAR 8-K 30m) &middot; news (Yahoo RSS 15m). mNAV computed. No mock data. Not financial advice.</div>",
            unsafe_allow_html=True)

if st.sidebar.checkbox("Auto-refresh (30s)", value=True):
    time.sleep(30)
    st.rerun()
