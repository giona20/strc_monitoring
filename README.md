# 🐎 The Four Horsemen — Crypto Liquidity Rotation Dashboard

Tracks the four signals that matter when liquidity is leaving crypto:

1. **STRC** — Strategy's perpetual preferred, dividend doom-loop watch (below $100 par = stressed)
2. **MSTR mNAV** — premium/discount to NAV (sub-1.0× = capitulation / bottoming zone)
3. **Spot BTC ETF flows** — net creation/redemption (billions out = institutional exit)
4. **Coinbase premium** — US spot demand proxy (deeply negative = US selling)

A composite score rolls all four into a single RISK-OFF / NEUTRAL / RISK-ON readout.

## Live vs. manual

- **Coinbase premium** is fetched server-side every 15s (Coinbase spot vs. Binance spot) — no CORS issues.
- **STRC, mNAV, ETF flows** are manual inputs in the sidebar — no clean free API exists for them. Update from your own feeds; ETF flows link out to [Farside Investors](https://farside.co.uk/btc/).

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Deploy on Streamlit Community Cloud

1. Push this folder to a **public** GitHub repo (see below).
2. Go to [share.streamlit.io](https://share.streamlit.io) and sign in with GitHub.
3. Click **New app**, pick your repo, set **Main file path** to `app.py`, deploy.

## Push to GitHub

```bash
cd four-horsemen
git init
git add .
git commit -m "Four Horsemen dashboard"
git branch -M main
git remote add origin https://github.com/<your-username>/four-horsemen.git
git push -u origin main
```

---

*Not financial advice. Premium feed depends on Coinbase/Binance public APIs being reachable.*
