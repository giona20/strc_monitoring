# The Four Horsemen - Crypto Liquidity Rotation Dashboard

Four signals that matter when liquidity is leaving crypto, in one screen.
**Everything is fetched live. No manual inputs, no default values, no mock data.**
If a source is unreachable, that card shows `NO DATA` and is excluded from the composite —
the app never invents a number.

1. **STRC** - Strategy's perpetual preferred; below $100 par = dividend stress / doom-loop risk
2. **MSTR mNAV** - premium/discount to NAV, shown both ways (Enterprise Value + Equity)
3. **Spot BTC ETF flows** - net creation/redemption (billions out = institutional exit)
4. **Coinbase premium** - US spot demand proxy (negative = US selling)

Plus a scrolling **STRC/MSTR news bar**, a plain-English **situation summary**, a live
**fundamentals strip**, and a **for-dummies guide** (Italian).

## Every value is live (all free, no API key)

| Data | Source | How | Refresh |
|---|---|---|---|
| Coinbase premium | Coinbase vs Binance spot (OKX fallback) | REST | 15s |
| ETF flows | Coinglass (key) -> Farside -> SoSoValue | API / browser-header scrape / JSON | 15m |
| STRC / MSTR price | Stooq (Yahoo fallback) | CSV / chart API | 2m |
| **BTC holdings** | SEC EDGAR | regex scrape of Strategy's latest 8-K | 30m |
| **Convertible debt** | SEC EDGAR | 8-K capital-structure update | 30m |
| **Preferred outstanding** | SEC EDGAR | 8-K capital-structure update | 30m |
| **USD reserve** | SEC EDGAR | 8-K | 30m |
| **STRC dividend rate** | SEC EDGAR | 8-K | 30m |
| Diluted shares | SEC EDGAR XBRL | `companyconcept` API | 1h |
| News | Yahoo Finance RSS (MSTR+STRC) | feed | 15m |
| mNAV (EV + equity) | computed from the above | — | live |

### How the SEC scraper works

Strategy files an 8-K almost every week. The app calls the SEC submissions API
(`data.sec.gov/submissions/CIK0001050446.json`), walks the most recent 8-K filings newest-first,
strips HTML, and regex-extracts each metric. It takes the newest value found per field — so BTC
holdings / reserve / STRC rate come from the latest weekly filing, while debt and preferred come
from the most recent capital-structure update that mentioned them. It stops as soon as all fields
are filled. Verified against the filings dated 1 Jun 2026 and 26 May 2026:
BTC 843,706 · debt $6.7B · preferred $15.5B · reserve $900M · STRC 11.50% → **mNAV EV 1.21× / equity 0.84×**.

### mNAV, both ways

```
EV mNAV     = (market cap + debt + preferred - cash) / (BTC holdings x BTC price)
Equity mNAV =  market cap                            / (BTC holdings x BTC price)
```

EV matches Strategy.com (~1.21×). Equity is stricter (~0.84×) — below 1.0 the common is worth
less than its bare bitcoin, the classic capitulation signal. The card flags red if either crosses 1.0.

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Deploy on Streamlit Community Cloud

1. Push to a **public** GitHub repo (commands below).
2. [share.streamlit.io](https://share.streamlit.io) -> New app -> pick repo -> `app.py` -> Deploy.

## Push to GitHub

```bash
git add .
git commit -m "v3: fully live, SEC 8-K scraper, no defaults/mock"
git push
```

(First time: `git init && git branch -M main && git remote add origin <url> && git push -u origin main`.
GitHub HTTPS needs a Personal Access Token instead of a password.)

## Gotchas

- **SEC User-Agent**: `data.sec.gov` requires a descriptive User-Agent and rate-limits to ~10 req/s
  (already handled; results cached 30m). If SEC blocks, the fundamentals strip shows `n/a` and the
  mNAV card shows `NO DATA` rather than a guess.
- **Binance geoblock** on US-based Streamlit Cloud (HTTP 451) -> auto-falls back to OKX.
- **8-K wording changes**: if Strategy changes its press-release phrasing, update the regexes in
  `fetch_strategy_fundamentals` (`_btc_holdings`, `_debt_m`, `_pref_m`, `_reserve_m`, `_strc_rate`).
- **Farside layout change** -> adjust `fetch_etf_flows`.

## Debugging NO DATA (read this first)

Turn on **"Show data-source diagnostics"** in the sidebar. It prints exactly which source
succeeded or failed and the HTTP code — no more guessing. Most likely causes on Streamlit Cloud:

- **SEC 8-K shows HTTP 403**: SEC rejects generic User-Agents and fake emails, and has blocked
  cloud IP ranges. Set a *real* email in the `UA` string at the top of `app.py`
  (e.g. `"YourName yourreal@email.com"`). Wait 10 min if you were already blocked.
- **mNAV NO DATA was caused by shares**: fixed. Share count is now derived directly from the
  "Bitcoin Per Share (in sats)" figure in the same 8-K (shares = holdings x 1e8 / BPS_sats),
  so it no longer depends on Yahoo or SEC-XBRL — both of which block cloud IPs. mNAV now needs
  only the 8-K (holdings, BPS, debt, pref, reserve) + the live BTC price + MSTR price (Stooq).
- **ETF NO DATA**: Farside is behind Cloudflare and SoSoValue's public endpoint can rate-limit
  cloud IPs. The robust fix is a free **Coinglass API key** in the sidebar — it's tried first.

## If a card shows NO DATA

The app never fakes a number — if a source is unreachable that card goes grey. Common cases:

- **ETF flows NO DATA**: Farside sits behind Cloudflare and sometimes blocks server IPs
  (this is why it failed before). The app now sends real browser headers, retries 3x, then
  falls back to SoSoValue's JSON. For a rock-solid feed, paste a free **Coinglass API key**
  in the sidebar — it's tried first.
- **mNAV NO DATA**: needs market cap + BTC holdings + BTC price. Market cap now comes from
  MSTR price x SEC share count, and if SEC's share endpoint is down it falls back to Yahoo's
  market cap directly — so mNAV survives a single source outage. It only goes NO DATA if the
  live BTC price or SEC holdings are both unavailable.

---

*Not financial advice.*
