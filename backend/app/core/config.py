"""
Watchlist configuration.

- STOCKS: 50 large/mid-cap Indian stocks. ".BO" = BSE listing on Yahoo Finance.
  (If a .BO ticker returns patchy data, switch that one to ".NS" — same company,
  NSE listing, usually cleaner data on Yahoo.)
- ETFS: Indian ETFs. These are far more liquid on NSE, so ".NS" is used.
- MUTUAL_FUNDS: Indian MFs are NOT on Yahoo Finance. We use the free mfapi.in
  API (official AMFI NAV data). Each entry needs a scheme code.
  Find codes with:  python downloader.py --search "parag parikh flexi"
  Then verify the name printed on first download matches what you expect.
"""

# ---------------------------------------------------------------- 50 stocks
STOCKS = [
    # Banking & Financials
    "HDFCBANK.BO", "ICICIBANK.BO", "SBIN.BO", "KOTAKBANK.BO", "AXISBANK.BO",
    "BAJFINANCE.BO", "BAJAJFINSV.BO", "INDUSINDBK.BO", "PNB.BO", "BANKBARODA.BO",
    # IT
    "TCS.BO", "INFY.BO", "WIPRO.BO", "HCLTECH.BO", "TECHM.BO", "LTIM.BO",
    # Energy / Oil & Gas / Power
    "RELIANCE.BO", "ONGC.BO", "NTPC.BO", "POWERGRID.BO", "TATAPOWER.BO",
    "BPCL.BO", "IOC.BO", "COALINDIA.BO", "ADANIGREEN.BO",
    # Auto
    "TATAMOTORS.BO", "MARUTI.BO", "M&M.BO", "BAJAJ-AUTO.BO", "EICHERMOT.BO",
    "HEROMOTOCO.BO",
    # FMCG & Consumer
    "HINDUNILVR.BO", "ITC.BO", "NESTLEIND.BO", "BRITANNIA.BO", "DABUR.BO",
    "TITAN.BO", "ASIANPAINT.BO",
    # Pharma & Healthcare
    "SUNPHARMA.BO", "DRREDDY.BO", "CIPLA.BO", "DIVISLAB.BO", "APOLLOHOSP.BO",
    # Infra / Cement / Metals
    "LT.BO", "ULTRACEMCO.BO", "GRASIM.BO", "TATASTEEL.BO", "JSWSTEEL.BO",
    "HINDALCO.BO",
    # Telecom
    "BHARTIARTL.BO",
]

# ---------------------------------------------------------------- ETFs (NSE)
ETFS = [
    "NIFTYBEES.NS",   # Nippon India Nifty 50 ETF
    "JUNIORBEES.NS",  # Nifty Next 50 ETF
    "BANKBEES.NS",    # Nifty Bank ETF
    "GOLDBEES.NS",    # Gold ETF
    "SILVERBEES.NS",  # Silver ETF
    "ITBEES.NS",      # Nifty IT ETF
    "MON100.NS",      # Motilal Oswal Nasdaq 100 ETF (US exposure)
]

# ------------------------------------------------------- Mutual funds (mfapi)
# Format: {"scheme_code": int, "label": "your own nickname"}
# IMPORTANT: verify each code with the --search tool before trusting it.
# The downloader prints the official scheme name on first fetch — check it.
MUTUAL_FUNDS = [
    {"scheme_code": 122639, "label": "Parag Parikh Flexi Cap Dir-G"},
    {"scheme_code": 120503, "label": "VERIFY-ME large cap fund"},
    {"scheme_code": 118989, "label": "VERIFY-ME index fund"},
]

# ------------------------------------------------------- new-account starter
# Every account after the first starts with these, so the ribbon, Home and
# Watchlists are not empty on first sign-in. (The first account inherits
# the STOCKS/ETFS/MUTUAL_FUNDS lists above instead.)
#
# Stocks are base symbols; the exchange suffix is chosen when the account
# is created, preferring whichever listing already has price history so
# the new user sees prices at once.
STARTER_STOCKS = [
    "RELIANCE", "HDFCBANK", "TCS", "ICICIBANK", "INFY",
    "BHARTIARTL", "SBIN", "ITC", "LT", "HINDUNILVR",
]

# Funds are looked up on mfapi.in by name when the account is created:
# the first search hit whose name contains every `must` word and none of
# the `avoid` words wins (so we get the Direct-plan Growth option, not a
# Regular/IDCW variant). `scheme_code` is only a fallback for when
# mfapi.in cannot be reached at that moment — verify it once with the
# fund search if you change this list.
STARTER_FUNDS = [
    {"label": "Parag Parikh Flexi Cap Fund",
     "query": "Parag Parikh Flexi Cap", "must": ["direct", "growth"],
     "scheme_code": 122639},
    {"label": "UTI Nifty 50 Index Fund",
     "query": "UTI Nifty 50 Index", "must": ["direct", "growth"],
     "scheme_code": 120716},
    {"label": "SBI Bluechip Fund",
     "query": "SBI Bluechip", "must": ["direct", "growth"],
     "scheme_code": 119598},
    {"label": "HDFC Mid-Cap Opportunities Fund",
     "query": "HDFC Mid-Cap Opportunities", "must": ["direct", "growth"],
     "scheme_code": 118989},
    {"label": "Nippon India Small Cap Fund",
     "query": "Nippon India Small Cap", "must": ["direct", "growth"],
     "scheme_code": 118778},
]
STARTER_FUND_AVOID = ["idcw", "dividend", "regular", "bonus", "reinvest"]

# ------------------------------------------------------------------ Settings
# DB lives NEXT TO THE CODE, not in whatever folder the server was started
# from. A bare relative path ("market_data.db") silently creates a second,
# empty database when uvicorn is launched from a different cwd — schema
# migrations then run on one file while requests read the other, which is
# how "no such column: username" happens.
from app.core import paths
DB_PATH = str(paths.DATA_DIR / "market_data.db")
# A dev machine can point at a copy without other people's data
# (scripts/make_dev_db.py; run.bat sets this when that copy exists).
# Only a bare file name inside data/ is accepted, so the database always
# stays next to the code (see above).
import os as _os
_dev = (_os.environ.get("LEDGERLINE_DB") or "").strip()
if _dev and _os.path.basename(_dev) == _dev and _dev.endswith(".db"):
    DB_PATH = str(paths.DATA_DIR / _dev)
HISTORY_PERIOD = "10y"      # how much history to pull on first run
SMA_FAST = 50
SMA_SLOW = 200
RSI_PERIOD = 14
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70

# Auto-refresh after market close (IST). Set False to disable.
AUTO_REFRESH = True
AUTO_REFRESH_TIME = "16:05"

# ------------------------------------------------------------- sector map
# Used by peers.py for the peer-comparison strip and by verdict.py.
SECTORS = {
    "Banking & Financials": ["HDFCBANK.BO", "ICICIBANK.BO", "SBIN.BO",
        "KOTAKBANK.BO", "AXISBANK.BO", "BAJFINANCE.BO", "BAJAJFINSV.BO",
        "INDUSINDBK.BO", "PNB.BO", "BANKBARODA.BO"],
    "IT": ["TCS.BO", "INFY.BO", "WIPRO.BO", "HCLTECH.BO", "TECHM.BO",
        "LTIM.BO"],
    "Energy & Power": ["RELIANCE.BO", "ONGC.BO", "NTPC.BO", "POWERGRID.BO",
        "TATAPOWER.BO", "BPCL.BO", "IOC.BO", "COALINDIA.BO",
        "ADANIGREEN.BO"],
    "Auto": ["TATAMOTORS.BO", "MARUTI.BO", "M&M.BO", "BAJAJ-AUTO.BO",
        "EICHERMOT.BO", "HEROMOTOCO.BO"],
    "FMCG & Consumer": ["HINDUNILVR.BO", "ITC.BO", "NESTLEIND.BO",
        "BRITANNIA.BO", "DABUR.BO", "TITAN.BO", "ASIANPAINT.BO"],
    "Pharma & Healthcare": ["SUNPHARMA.BO", "DRREDDY.BO", "CIPLA.BO",
        "DIVISLAB.BO", "APOLLOHOSP.BO"],
    "Infra, Cement & Metals": ["LT.BO", "ULTRACEMCO.BO", "GRASIM.BO",
        "TATASTEEL.BO", "JSWSTEEL.BO", "HINDALCO.BO"],
    "Telecom": ["BHARTIARTL.BO"],
}

def sector_of(symbol):
    for name, members in SECTORS.items():
        if symbol in members:
            return name, members
    return None, []
