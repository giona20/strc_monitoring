"""
THE FOUR HORSEMEN — Crypto Liquidity Rotation Dashboard
========================================================
Tracks the four signals that matter when liquidity is leaving crypto:
  1. STRC  — Strategy's perpetual preferred, dividend doom-loop watch
  2. mNAV  — MSTR premium/discount to NAV (sub-1.0 = capitulation zone)
  3. ETF flows — net spot BTC ETF creation/redemption (billions out = bad)
  4. Coinbase premium — US spot demand proxy (deeply negative = US selling)

Live where free APIs allow (Coinbase premium fetched server-side, no CORS).
Manual inputs (your feeds) where they don't.
"""

import time
import requests
import streamlit as st

# ----------------------------------------------------------------------------
# Page config + theme
# ----------------------------------------------------------------------------
st.set_page_config(page_title="The Four Horsemen", page_icon="🐎", layout="wide")

C = {
    "bg": "#0a0a0c", "panel": "#121215", "panel2": "#17171b", "line": "#26262c",
    "text": "#e8e8ea", "dim": "#8a8a92", "red": "#ff4d4d", "redDim": "#5c2526",
    "green": "#3ddc84", "amber": "#ffb020", "blue": "#5b9dff",
}

st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Archivo+Black&family=IBM+Plex+Mono:wght@400;500;600&display=swap');
.stApp {{ background: {C['bg']}; color: {C['text']}; font-family: 'IBM Plex Mono', monospace; }}
.block-container {{ padding-top: 2rem; max-width: 1150px; }}
h1, h2, h3 {{ font-family: 'Archivo Black', sans-serif !important; letter-spacing: -0.5px; }}
.horsemen-card {{
  background: {C['panel']}; border: 1px solid {C['line']}; border-radius: 10px;
  padding: 18px; position: relative; overflow: hidden; height: 100%;
}}
.horsemen-flag {{ border: 1px solid {C['redDim']}; }}
.hm-title {{ font-size: 11px; letter-spacing: 1.5px; color: {C['dim']}; }}
.hm-big {{ font-family: 'Archivo Black', sans-serif; font-size: 30px; line-height: 1.1; margin: 10px 0 2px; }}
.hm-sub {{ font-size: 11px; color: {C['dim']}; }}
.hm-bar {{ position: absolute; top: 0; left: 0; height: 3px; transition: width .4s; }}
.thesis {{
  background: {C['panel']}; border: 1px solid {C['line']}; border-radius: 10px;
  padding: 16px 18px; font-size: 13px; line-height: 1.7; color: {C['dim']}; margin-top: 22px;
}}
[data-testid="stMetricValue"] {{ font-family: 'Archivo Black', sans-serif; }}
section[data-testid="stSidebar"] {{ background: {C['panel2']}; }}
</style>
""", unsafe_allow_html=True)


# ----------------------------------------------------------------------------
# Live data: Coinbase premium (Coinbase spot − Binance spot)
# ----------------------------------------------------------------------------
@st.cache_data(ttl=15)
def fetch_premium():
    try:
        cb = requests.get("https://api.coinbase.com/v2/prices/BTC-USD/spot", timeout=8).json()
        bn = requests.get("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT", timeout=8).json()
        coinbase = float(cb["data"]["amount"])
        binance = float(bn["price"])
        premium = (coinbase - binance) / binance * 100
        return {"coinbase": coinbase, "binance": binance, "premium": premium, "ok": True}
    except Exception as e:
        return {"coinbase": None, "binance": None, "premium": None, "ok": False, "err": str(e)}


# ----------------------------------------------------------------------------
# Scoring helpers (0..100, lower = more bearish for crypto)
# ----------------------------------------------------------------------------
def clamp(x, lo=0, hi=100):
    return max(lo, min(hi, x))

def verdict(score):
    if score >= 66: return ("RISK-ON", C["green"])
    if score >= 33: return ("NEUTRAL", C["amber"])
    return ("RISK-OFF", C["red"])


# ----------------------------------------------------------------------------
# Sidebar — manual inputs (wire to your own feeds)
# ----------------------------------------------------------------------------
st.sidebar.markdown("### MANUAL FEEDS")
st.sidebar.caption("No free API for these — update from your sources.")
strc = st.sidebar.number_input("STRC price ($)", value=96.58, step=0.01, format="%.2f")
strc_div = st.sidebar.number_input("STRC annual dividend ($)", value=10.0, step=0.1, format="%.2f")
mnav = st.sidebar.number_input("MSTR mNAV (×)", value=1.21, step=0.01, format="%.2f")
mstr = st.sidebar.number_input("MSTR price ($)", value=137.24, step=0.01, format="%.2f")
etf_today = st.sidebar.number_input("ETF net flow today ($M)", value=-483.8, step=1.0, format="%.1f")
etf_5d = st.sidebar.number_input("ETF net flow 5d ($M)", value=-1641.6, step=1.0, format="%.1f")
st.sidebar.markdown(f"[→ Update ETF flows from Farside](https://farside.co.uk/btc/)")
auto = st.sidebar.checkbox("Auto-refresh (15s)", value=True)

# ----------------------------------------------------------------------------
# Compute
# ----------------------------------------------------------------------------
p = fetch_premium()
prem = p["premium"] if p["ok"] else 0.0

strc_score = clamp((strc - 90) / 20 * 100)
mnav_score = clamp((mnav - 0.8) / 0.6 * 100)
etf_score = clamp((etf_5d + 2000) / 4000 * 100)
prem_score = clamp((prem + 0.15) / 0.3 * 100)
composite = (strc_score + mnav_score + etf_score + prem_score) / 4
comp_label, comp_color = verdict(composite)

# ----------------------------------------------------------------------------
# Header
# ----------------------------------------------------------------------------
hcol1, hcol2 = st.columns([3, 1])
with hcol1:
    st.markdown("<h1 style='font-size:34px;margin-bottom:0'>THE FOUR HORSEMEN</h1>", unsafe_allow_html=True)
    st.markdown(f"<div style='color:{C['dim']};font-size:12px'>Liquidity-rotation watch — if you're not tracking these, don't touch it.</div>", unsafe_allow_html=True)
with hcol2:
    feed = "live" if p["ok"] else "feed blocked"
    st.markdown(
        f"<div style='text-align:right'><span style='color:{comp_color};font-size:14px;letter-spacing:1px'>● {comp_label}</span>"
        f"<br><span style='color:{C['dim']};font-size:11px'>{composite:.0f}/100 · {feed}</span></div>",
        unsafe_allow_html=True,
    )

st.markdown(
    f"<div style='height:8px;background:{C['panel2']};border-radius:6px;margin:16px 0 24px;overflow:hidden'>"
    f"<div style='height:100%;width:{composite}%;background:{comp_color}'></div></div>",
    unsafe_allow_html=True,
)


# ----------------------------------------------------------------------------
# Card renderer
# ----------------------------------------------------------------------------
def card(col, title, score, big, big_color, sub, extra="", flag=False):
    lbl, clr = verdict(score)
    flag_cls = "horsemen-flag" if flag else ""
    col.markdown(
        f"""<div class="horsemen-card {flag_cls}">
        <div class="hm-bar" style="width:{score}%;background:{clr}"></div>
        <div style="display:flex;justify-content:space-between">
          <span class="hm-title">{title}</span>
          <span style="font-size:10px;color:{clr};letter-spacing:1px">{lbl}</span>
        </div>
        <div class="hm-big" style="color:{big_color}">{big}</div>
        <div class="hm-sub">{sub}</div>
        {extra}
        </div>""",
        unsafe_allow_html=True,
    )


c1, c2, c3, c4 = st.columns(4)

# 1. STRC
eff_yield = (strc_div / strc * 100) if strc else 0
card(
    c1, "① STRC — DOOM-LOOP", strc_score,
    f"${strc:,.2f}", C["red"] if strc < 100 else C["text"],
    "▼ below $100 par — dividend stressed" if strc < 100 else "at/above par",
    extra=f"<div class='hm-sub' style='margin-top:8px'>effective yield: {eff_yield:.2f}%</div>",
    flag=strc < 100,
)

# 2. mNAV
mnav_color = C["green"] if mnav < 1.0 else (C["amber"] if mnav < 1.3 else C["text"])
card(
    c2, "② MSTR mNAV", mnav_score,
    f"{mnav:.2f}×", mnav_color,
    "◆ BELOW NAV — bottoming zone" if mnav < 1.0 else "premium to NAV intact",
    extra=f"<div class='hm-sub' style='margin-top:8px'>MSTR ${mstr:,.2f} · watch for sub-1.0</div>",
    flag=mnav < 1.0,
)

# 3. ETF
etf_str = f"{'+' if etf_today >= 0 else '-'}${abs(etf_today):.1f}M"
etf5_str = f"{'+' if etf_5d >= 0 else '-'}${abs(etf_5d):.1f}M"
card(
    c3, "③ SPOT BTC ETF FLOWS", etf_score,
    etf_str, C["red"] if etf_today < 0 else C["green"],
    f"latest daily · 5d net {etf5_str}",
    extra=f"<div class='hm-sub' style='margin-top:8px'><a href='https://farside.co.uk/btc/' style='color:{C['blue']};text-decoration:none'>→ Farside Investors</a></div>",
    flag=etf_5d < -500,
)

# 4. Coinbase premium (LIVE)
if p["ok"]:
    prem_big = f"{'+' if prem >= 0 else ''}{prem:.3f}%"
    prem_sub = ("▼ negative — US spot selling" if prem < 0 else "US bid present")
    prem_extra = f"<div class='hm-sub' style='margin-top:8px'>CB ${p['coinbase']:,.0f} · BN ${p['binance']:,.0f}</div>"
else:
    prem_big, prem_sub, prem_extra = "—", "feed unavailable", ""
card(
    c4, "④ COINBASE PREMIUM", prem_score,
    prem_big, C["red"] if prem < 0 else C["green"],
    prem_sub, extra=prem_extra, flag=prem < 0,
)

# ----------------------------------------------------------------------------
# Thesis
# ----------------------------------------------------------------------------
st.markdown(
    f"""<div class="thesis">
    <div style="font-size:11px;letter-spacing:1.5px;color:{C['text']};margin-bottom:8px">THE ROTATION THESIS</div>
    Liquidity is draining out of crypto into AI/Robotics equities. STRC below par with an unsustainable
    dividend threatens a reflexive doom loop; MSTR's mNAV compressing toward (and ideally below) 1.0 marks
    capitulation; ETFs bleeding billions confirms institutional exit; a deeply negative Coinbase premium shows
    US spot is the one doing the selling. All four aligned bearish = stay out. Watch for mNAV &lt; 1.0 +
    premium flipping positive as the turn.
    </div>""",
    unsafe_allow_html=True,
)
st.markdown(
    f"<div style='font-size:10px;color:#55555c;margin-top:12px;text-align:center'>"
    f"Live: Coinbase/Binance spot premium (15s cache). Manual: STRC, mNAV, ETF flows. Not financial advice.</div>",
    unsafe_allow_html=True,
)

# ----------------------------------------------------------------------------
# Auto-refresh
# ----------------------------------------------------------------------------
if auto:
    time.sleep(15)
    st.rerun()
