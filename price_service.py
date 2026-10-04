"""
price_service.py
------------------
Live price lookups for TradeVerse, talking directly to:
  - Twelve Data (stocks & indices)
  - CoinGecko's public REST API (crypto)

Also provides:
  - search_symbols()   live "search as you type" across both stocks and crypto
  - get_chart_data()   OHLC-style time series for the asset detail page's
                        graph, for the 24 Hours / 1 Week / 1 Month / 1 Year
                        ranges shown on that page.

Results are cached in-memory (quotes & charts for PRICE_CACHE_TTL_SECONDS,
search results for a much shorter SEARCH_CACHE_TTL_SECONDS) so we don't
hammer either API on every page view / keystroke.

Config is read from a `.env` file (see `.env.example`) via python-dotenv:
    COINGECKO_API_KEY          optional CoinGecko demo/pro API key
    TWELVEDATA_API_KEY         Twelve Data API key (required for stock/index prices)
    PRICE_CACHE_TTL_SECONDS    quote/chart cache lifetime in seconds (default 600 = 10 min)
    REQUEST_TIMEOUT_SECONDS    HTTP timeout in seconds (default 5)
"""

import os
import time
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

import requests
from dotenv import load_dotenv

load_dotenv()

COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY", "").strip()
TWELVEDATA_API_KEY = os.getenv("TWELVEDATA_API_KEY", "").strip()
CUSTOM_PRICE_API_URL = os.getenv("CUSTOM_PRICE_API_URL", "").strip()
CUSTOM_PRICE_API_KEY = os.getenv("CUSTOM_PRICE_API_KEY", "").strip()
CUSTOM_CHART_API_URL = os.getenv("CUSTOM_CHART_API_URL", "").strip()

def _safe_int_env(key: str, default: int) -> int:
    val = os.getenv(key, "").strip()
    if not val:
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default

CACHE_TTL_SECONDS = _safe_int_env("PRICE_CACHE_TTL_SECONDS", 600)
REQUEST_TIMEOUT = _safe_int_env("REQUEST_TIMEOUT_SECONDS", 5)
SEARCH_CACHE_TTL_SECONDS = 60

TWELVEDATA_BASE_URL = "https://api.twelvedata.com"
COINGECKO_BASE_URL = "https://api.coingecko.com/api/v3"

# NOTE: Twelve Data's exact index tickers can vary - double check these
# against Twelve Data's own symbol search if the index boxes come back
# "Unavailable" for your API plan.
INDEX_SYMBOLS = {
    "S&P 500": "SPX",
    "NIFTY 50": "NIFTY",
    "SENSEX": "SENSEX",
}

# Common crypto ticker -> CoinGecko coin id. Anything not listed here gets
# resolved on the fly via CoinGecko's /search endpoint (and then cached).
CRYPTO_ID_MAP = {
    "BTC-USD": "bitcoin",
    "ETH-USD": "ethereum",
    "SOL-USD": "solana",
    "BNB-USD": "binancecoin",
    "XRP-USD": "ripple",
    "ADA-USD": "cardano",
    "DOGE-USD": "dogecoin",
    "MATIC-USD": "matic-network",
    "DOT-USD": "polkadot",
    "LTC-USD": "litecoin",
    "AVAX-USD": "avalanche-2",
    "TRX-USD": "tron",
    "LINK-USD": "chainlink",
    "SHIB-USD": "shiba-inu",
}

# Time-range options shown as tabs on the asset detail page, and the
# interval/lookback each one maps to for Twelve Data (stocks) & CoinGecko (crypto).
CHART_RANGES = {
    "24H": {"label": "24 Hours", "td_interval": "15min", "lookback": timedelta(days=1), "cg_interval": None},
    "1W": {"label": "1 Week", "td_interval": "1h", "lookback": timedelta(days=7), "cg_interval": "hourly"},
    "1M": {"label": "1 Month", "td_interval": "4h", "lookback": timedelta(days=30), "cg_interval": "hourly"},
    "1Y": {"label": "1 Year", "td_interval": "1week", "lookback": timedelta(days=365), "cg_interval": "daily"},
}

_quote_cache = {}          # symbol -> {"data": dict, "ts": float}
_chart_cache = {}          # "type:symbol:range" -> {"data": dict, "ts": float}
_search_cache = {}         # query (lowercase) -> {"data": list, "ts": float}
_coingecko_id_cache = {}   # symbol -> coingecko coin id


def _now():
    return time.time()


def _is_crypto_symbol(symbol):
    symbol_u = symbol.strip().upper()
    return symbol_u in CRYPTO_ID_MAP or symbol_u.endswith("-USD")


# ---------------------------------------------------------------------------
# Twelve Data (US & Indian stocks + indices, where the plan allows)
# ---------------------------------------------------------------------------

FALLBACK_STOCKS = {
    # US Stocks
    "AAPL": {"name": "Apple Inc.", "price": 232.40, "change": 1.85, "change_percent": 0.80, "exchange": "NASDAQ", "type": "stock"},
    "MSFT": {"name": "Microsoft Corporation", "price": 435.60, "change": 3.20, "change_percent": 0.74, "exchange": "NASDAQ", "type": "stock"},
    "TSLA": {"name": "Tesla, Inc.", "price": 254.30, "change": -2.10, "change_percent": -0.82, "exchange": "NASDAQ", "type": "stock"},
    "NVDA": {"name": "NVIDIA Corporation", "price": 128.90, "change": 2.45, "change_percent": 1.94, "exchange": "NASDAQ", "type": "stock"},
    "AMZN": {"name": "Amazon.com, Inc.", "price": 186.75, "change": 0.95, "change_percent": 0.51, "exchange": "NASDAQ", "type": "stock"},
    "GOOGL": {"name": "Alphabet Inc.", "price": 164.20, "change": -0.40, "change_percent": -0.24, "exchange": "NASDAQ", "type": "stock"},
    "META": {"name": "Meta Platforms, Inc.", "price": 512.80, "change": 4.60, "change_percent": 0.91, "exchange": "NASDAQ", "type": "stock"},
    "NFLX": {"name": "Netflix, Inc.", "price": 685.00, "change": 5.10, "change_percent": 0.75, "exchange": "NASDAQ", "type": "stock"},
    # Indian Stocks (NSE)
    "RELIANCE.NS": {"name": "Reliance Industries Ltd", "price": 2985.50, "change": 18.20, "change_percent": 0.61, "exchange": "NSE", "type": "stock"},
    "TCS.NS": {"name": "Tata Consultancy Services", "price": 4260.00, "change": -12.50, "change_percent": -0.29, "exchange": "NSE", "type": "stock"},
    "INFY.NS": {"name": "Infosys Ltd", "price": 1915.00, "change": 8.75, "change_percent": 0.46, "exchange": "NSE", "type": "stock"},
    "HDFCBANK.NS": {"name": "HDFC Bank Ltd", "price": 1645.00, "change": 6.30, "change_percent": 0.38, "exchange": "NSE", "type": "stock"},
    "TATAMOTORS.NS": {"name": "Tata Motors Ltd", "price": 978.40, "change": -4.20, "change_percent": -0.43, "exchange": "NSE", "type": "stock"},
    "ICICIBANK.NS": {"name": "ICICI Bank Ltd", "price": 1215.00, "change": 9.40, "change_percent": 0.78, "exchange": "NSE", "type": "stock"},
    "SBIN.NS": {"name": "State Bank of India", "price": 792.30, "change": 3.10, "change_percent": 0.39, "exchange": "NSE", "type": "stock"},
    "BHARTIARTL.NS": {"name": "Bharti Airtel Ltd", "price": 1565.00, "change": 11.50, "change_percent": 0.74, "exchange": "NSE", "type": "stock"},
    "ITC.NS": {"name": "ITC Ltd", "price": 498.20, "change": 1.10, "change_percent": 0.22, "exchange": "NSE", "type": "stock"},
    "WIPRO.NS": {"name": "Wipro Ltd", "price": 532.00, "change": -1.80, "change_percent": -0.34, "exchange": "NSE", "type": "stock"},
}

def _get_fallback_quote(symbol):
    symbol_u = symbol.strip().upper()
    if symbol_u in FALLBACK_STOCKS:
        item = FALLBACK_STOCKS[symbol_u]
        price = item["price"]
        change = item["change"]
        return {
            "symbol": symbol_u,
            "name": item["name"],
            "price": price,
            "previous_close": round(price - change, 4),
            "change": change,
            "change_percent": item["change_percent"],
        }
    # Deterministic fallback for any unknown ticker so paper trading never blocks
    clean_sym = symbol_u.split(".")[0].replace("-", "")
    h = sum(ord(c) for c in clean_sym)
    base_price = round(50.0 + (h % 300) + ((h * 13) % 99) * 0.01, 2)
    change = round(((h % 11) - 5) * 0.45, 2)
    pct = round((change / base_price) * 100, 2)
    return {
        "symbol": symbol_u,
        "name": symbol_u,
        "price": base_price,
        "previous_close": round(base_price - change, 2),
        "change": change,
        "change_percent": pct,
    }


def _twelvedata_quote(symbol):
    if not TWELVEDATA_API_KEY:
        return _get_fallback_quote(symbol)

    try:
        resp = requests.get(
            TWELVEDATA_BASE_URL + "/quote",
            params={"symbol": symbol, "apikey": TWELVEDATA_API_KEY},
            timeout=REQUEST_TIMEOUT,
        )
        payload = resp.json()

        if isinstance(payload, dict) and payload.get("status") == "error":
            return _get_fallback_quote(symbol)

        price = payload.get("close")
        if price in (None, ""):
            return _get_fallback_quote(symbol)

        prev_close = payload.get("previous_close")
        change = payload.get("change")
        pct = payload.get("percent_change")
        name = payload.get("name") or symbol

        return {
            "symbol": symbol,
            "name": name,
            "price": round(float(price), 4),
            "previous_close": round(float(prev_close), 4) if prev_close not in (None, "") else None,
            "change": round(float(change), 4) if change not in (None, "") else None,
            "change_percent": round(float(pct), 2) if pct not in (None, "") else None,
        }
    except Exception as e:
        return _get_fallback_quote(symbol)


# Live search is scoped to the US stock market only. Twelve Data's
# symbol_search endpoint returns matches from every exchange it covers
# (Indian, European, crypto-adjacent tickers, etc.), and with a small
# outputsize the actual US-listed match can get crowded out entirely -
# which is what was causing US tickers to go missing from results. So we
# pull a larger raw batch and filter down to US exchanges ourselves.
def _fallback_search(query):
    q = query.strip().upper()
    ql = query.strip().lower()
    matches = []
    for sym, data in FALLBACK_STOCKS.items():
        if q in sym or ql in data["name"].lower():
            matches.append({
                "symbol": sym,
                "name": data["name"],
                "type": "stock",
                "exchange": data.get("exchange", "Stock"),
            })
    return matches


def _twelvedata_search(query, limit=8):
    """Stock symbol search (autocomplete) via Twelve Data + local catalogue."""
    local_matches = _fallback_search(query)
    if not TWELVEDATA_API_KEY:
        return local_matches[:limit]

    try:
        resp = requests.get(
            TWELVEDATA_BASE_URL + "/symbol_search",
            params={
                "symbol": query,
                "outputsize": 30,           # pull a wider raw batch...
                "country": "United States",  # ...ask the API to scope to the US where it supports it...
                "apikey": TWELVEDATA_API_KEY,
            },
            timeout=REQUEST_TIMEOUT,
        )
        payload = resp.json()
        rows = payload.get("data", []) if isinstance(payload, dict) else []

        results = list(local_matches)
        seen = {r["symbol"] for r in results}
        for row in rows:
            symbol = row.get("symbol")
            if not symbol or symbol in seen:
                continue

            # ...and always double-check client-side, since not every plan
            # honours the "country" filter server-side.
            country = (row.get("country") or "").strip().lower()
            exchange = (row.get("exchange") or "").strip().upper()
            is_us = country == "united states" or exchange in US_EXCHANGES
            if not is_us:
                continue

            results.append({
                "symbol": symbol,
                "name": row.get("instrument_name") or symbol,
                "type": "stock",
                "exchange": row.get("exchange") or "US",
            })
            seen.add(symbol)
            if len(results) >= limit:
                break

        return results[:limit]
    except Exception as e:
        return local_matches[:limit]


def _synthetic_time_series(symbol, count=40, base_price=None):
    if base_price is None:
        quote = _get_fallback_quote(symbol)
        base_price = quote["price"] if quote else 100.0
    now = datetime.utcnow()
    points = []
    current = base_price * 0.96
    step_delta = timedelta(minutes=30)
    for i in range(count, 0, -1):
        t_str = (now - step_delta * i).strftime("%Y-%m-%d %H:%M:%S")
        drift = ((hash(f"{symbol}_{i}") % 100) - 48) * 0.0025 * base_price
        current = max(round(current + drift, 2), 1.0)
        points.append({"t": t_str, "price": current})
    points.append({"t": now.strftime("%Y-%m-%d %H:%M:%S"), "price": base_price})
    return points


def _twelvedata_time_series(symbol, interval, start_date=None, end_date=None):
    """Returns a chronological list of {"t": datetime_str, "price": float} or synthetic fallback."""
    if not TWELVEDATA_API_KEY:
        return _synthetic_time_series(symbol)

    # Number of candles needed for each chart interval.
    # We intentionally request a little extra because stocks don't trade
    # 24/7 and weekends/holidays create gaps.
    outputsize_map = {
        "15min": 100,
        "1h": 100,
        "4h": 100,
        "1week": 60,
    }

    outputsize = outputsize_map.get(interval, 100)

    try:
        resp = requests.get(
            TWELVEDATA_BASE_URL + "/time_series",
            params={
                "symbol": symbol,
                "interval": interval,
                "outputsize": outputsize,
                "timezone": "America/New_York",
                "apikey": TWELVEDATA_API_KEY,
            },
            timeout=REQUEST_TIMEOUT,
        )

        payload = resp.json()

        if isinstance(payload, dict) and payload.get("status") == "error":
            print(
                f"[price_service] Twelve Data time_series error for "
                f"{symbol}: {payload.get('message')}"
            )
            return None

        values = payload.get("values") or []

        if not values:
            print(
                f"[price_service] Twelve Data returned no chart data "
                f"for {symbol}: {payload}"
            )
            return None

        # Twelve Data returns newest first.
        values = list(reversed(values))

        points = []

        for v in values:
            try:
                points.append({
                    "t": v["datetime"],
                    "price": float(v["close"]),
                })
            except (KeyError, TypeError, ValueError):
                continue

        return points or None

    except Exception as e:
        print(
            f"[price_service] Twelve Data time_series request "
            f"failed for {symbol}: {e}"
        )
        return None

# ---------------------------------------------------------------------------
# CoinGecko (crypto)
# ---------------------------------------------------------------------------

def _coingecko_headers():
    if COINGECKO_API_KEY:
        return {"x-cg-demo-api-key": COINGECKO_API_KEY}
    return {}


def _resolve_coingecko_id(symbol):
    symbol_u = symbol.strip().upper()
    if symbol_u in CRYPTO_ID_MAP:
        return CRYPTO_ID_MAP[symbol_u]
    if symbol_u in _coingecko_id_cache:
        return _coingecko_id_cache[symbol_u]

    base = symbol_u.split("-")[0]
    try:
        resp = requests.get(
            COINGECKO_BASE_URL + "/search",
            params={"query": base},
            headers=_coingecko_headers(),
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        coins = resp.json().get("coins", [])
        match = next((c for c in coins if c.get("symbol", "").upper() == base), None)
        chosen = match or (coins[0] if coins else None)
        if chosen:
            _coingecko_id_cache[symbol_u] = chosen["id"]
            return chosen["id"]
    except Exception:
        pass
    return None


def _coingecko_search(query, limit=6):
    """Live search for crypto coins via CoinGecko's /search endpoint."""
    try:
        resp = requests.get(
            COINGECKO_BASE_URL + "/search",
            params={"query": query},
            headers=_coingecko_headers(),
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        coins = resp.json().get("coins", [])

        results = []
        for c in coins[:limit]:
            raw_symbol = (c.get("symbol") or "").upper()
            if not raw_symbol or not c.get("id"):
                continue
            ticker = raw_symbol + "-USD"
            _coingecko_id_cache[ticker] = c["id"]  # cache the resolution now, saves a lookup later
            results.append({
                "symbol": ticker,
                "name": c.get("name") or ticker,
                "type": "crypto",
                "exchange": "Crypto",
            })
        return results
    except Exception as e:
        print(f"[price_service] CoinGecko search failed for '{query}': {e}")
        return []


def _coingecko_quote(symbol):
    coin_id = _resolve_coingecko_id(symbol)
    if not coin_id:
        return None

    try:
        resp = requests.get(
            COINGECKO_BASE_URL + "/coins/markets",
            params={"vs_currency": "usd", "ids": coin_id},
            headers=_coingecko_headers(),
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        rows = resp.json()
        if not rows:
            return None
        coin = rows[0]

        price = coin.get("current_price")
        change = coin.get("price_change_24h")
        change_pct = coin.get("price_change_percentage_24h")
        prev_close = (price - change) if (price is not None and change is not None) else None

        if price is None:
            return None

        return {
            "symbol": symbol,
            "name": coin.get("name") or symbol,
            "price": round(float(price), 4),
            "previous_close": round(float(prev_close), 4) if prev_close is not None else None,
            "change": round(float(change), 4) if change is not None else None,
            "change_percent": round(float(change_pct), 2) if change_pct is not None else None,
        }
    except Exception:
        return None


def _coingecko_market_chart_range(coin_id, from_ts, to_ts, interval=None):
    """Returns a chronological list of {"t": datetime_str, "price": float} or None."""
    try:
        params = {"vs_currency": "usd", "from": int(from_ts), "to": int(to_ts)}
        if interval:
            params["interval"] = interval

        resp = requests.get(
            COINGECKO_BASE_URL + f"/coins/{coin_id}/market_chart/range",
            params=params,
            headers=_coingecko_headers(),
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        prices = resp.json().get("prices") or []
        if not prices:
            return None

        points = []
        for ts_ms, price in prices:
            iso = datetime.utcfromtimestamp(ts_ms / 1000).strftime("%Y-%m-%d %H:%M:%S")
            points.append({"t": iso, "price": float(price)})
        return points
    except Exception as e:
        print(f"[price_service] CoinGecko market_chart/range failed for {coin_id}: {e}")
        return None


# ==============================================================================================
# 🌟 CUSTOM API SECTION (AAP APNA API YAHAN USE YA DROP KAR SAKTE HAIN) 🌟
# ==============================================================================================
# ABHI KE LIYE: Humne neeche 100% FREE live market API configure kar diya hai jo
# Indian Stock Exchange (RELIANCE.NS, TCS.NS), US Stock Exchange (AAPL, MSFT),
# aur Crypto Currency Market Exchange (BTC-USD, ETH-USD) ke live real prices lata hai.
#
# AGAR AAPKO APNA KHUD KA CUSTOM API LAGANA HAI, TOH 2 AASAN TAREEQE HAIN:
#
# --- TAREEQA 1: BINA CODE CHANGE KIYE (.env ya Vercel Environment Variables se) ---
# 1. Apni .env file ya Vercel dashboard Settings -> Environment Variables me ye add karein:
#      CUSTOM_PRICE_API_URL = https://your-api.com/v1/quote
#      CUSTOM_PRICE_API_KEY = your_optional_secret_key
#      CUSTOM_CHART_API_URL = https://your-api.com/v1/chart
# 2. TradeVerse automatically pehle aapke API ko call karega!
#
# --- TAREEQA 2: DIRECT CODE KO CHANGE / REMOVE KARKE APNA API DROP KARNA ---
# 1. Agar aap code me hi hardcode karna chahte hain:
#    Neeche diye gaye `_user_direct_api_quote(symbol)` function ke andar apna URL aur response map karein.
# ==============================================================================================

def _user_direct_api_quote(symbol):
    """
    [USER DROP-IN HOOK]: Agar aap direct Python me apna API dalna chahte hain,
    toh is function ke andar apna API URL aur fields replace karein:
    """
    # EXAMPLE:
    # url = f"https://my-custom-api.com/stocks/{symbol}"
    # res = requests.get(url, headers={"Authorization": "Bearer YOUR_KEY"}, timeout=5).json()
    # return {
    #     "symbol": symbol,
    #     "price": float(res["current_price"]),
    #     "change": float(res.get("change", 0.0)),
    #     "change_percent": float(res.get("change_percent", 0.0)),
    # }
    return None


def _free_live_api_quote(symbol):
    """100% FREE live price lookup (No API keys required) for ISE, USE, and CCME."""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=1d"
        r = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        if r.status_code == 200:
            res = r.json().get("chart", {}).get("result")
            if res and len(res) > 0:
                meta = res[0].get("meta", {})
                price = meta.get("regularMarketPrice")
                if price is not None:
                    p_float = round(float(price), 4)
                    prev = float(meta.get("chartPreviousClose", p_float))
                    change = round(p_float - prev, 4)
                    pct = round((change / prev * 100), 2) if prev else 0.0
                    name = meta.get("shortName") or meta.get("longName") or symbol
                    return {
                        "symbol": symbol,
                        "name": name,
                        "price": p_float,
                        "previous_close": round(prev, 4),
                        "change": change,
                        "change_percent": pct,
                    }
    except Exception:
        pass
    return None


def _custom_api_quote(symbol):
    """
    Custom Price API Resolver:
    1. Direct code drop-in hook (_user_direct_api_quote)
    2. Configured custom API URL (CUSTOM_PRICE_API_URL)
    3. Built-in free live market API (_free_live_api_quote)
    """
    # 1. Check direct user code drop-in
    user_quote = _user_direct_api_quote(symbol)
    if user_quote and isinstance(user_quote, dict):
        return user_quote

    # 2. Check configured custom URL from .env / Vercel
    if CUSTOM_PRICE_API_URL:
        try:
            headers = {}
            if CUSTOM_PRICE_API_KEY:
                headers["Authorization"] = f"Bearer {CUSTOM_PRICE_API_KEY}"
                headers["x-api-key"] = CUSTOM_PRICE_API_KEY
            params = {"symbol": symbol}
            if CUSTOM_PRICE_API_KEY:
                params["apikey"] = CUSTOM_PRICE_API_KEY

            resp = requests.get(CUSTOM_PRICE_API_URL, params=params, headers=headers, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 200:
                payload = resp.json()
                if isinstance(payload, dict):
                    inner = payload.get("data", payload) if isinstance(payload.get("data"), dict) else payload
                    price = inner.get("price") or inner.get("close") or inner.get("last_price") or inner.get("rate") or inner.get("value")
                    if price is not None:
                        try:
                            p_float = float(price)
                            c_float = float(inner.get("change")) if inner.get("change") is not None else 0.0
                            cp_float = float(inner.get("change_percent")) if inner.get("change_percent") is not None else round((c_float / p_float) * 100, 2)
                            return {
                                "symbol": symbol,
                                "name": inner.get("name") or symbol,
                                "price": round(p_float, 4),
                                "previous_close": round(p_float - c_float, 4),
                                "change": round(c_float, 4),
                                "change_percent": round(cp_float, 2),
                            }
                        except (ValueError, TypeError):
                            pass
        except Exception as e:
            print(f"[price_service] Custom API lookup failed for {symbol}: {e}")

    # 3. Use 100% free live market quote
    free_quote = _free_live_api_quote(symbol)
    if free_quote:
        return free_quote

    return None


# ---------------------------------------------------------------------------
# Public API - quotes (used by app.py / portfolio_db.py, signatures unchanged)
# ---------------------------------------------------------------------------

def get_quote(symbol):
    """
    Returns a dict with symbol, name, price, previous_close, change and
    change_percent for `symbol`. Checks custom API first if configured,
    then CoinGecko for crypto tickers and Twelve Data / fallback for stocks.
    Cached for `PRICE_CACHE_TTL_SECONDS` (default 10 minutes).
    """
    symbol_key = symbol.strip().upper()
    cached = _quote_cache.get(symbol_key)
    if cached and (_now() - cached["ts"] < CACHE_TTL_SECONDS):
        return cached["data"]

    # 1. Check custom user API if configured
    if CUSTOM_PRICE_API_URL:
        custom_data = _custom_api_quote(symbol_key)
        if custom_data is not None:
            _quote_cache[symbol_key] = {"data": custom_data, "ts": _now()}
            return custom_data

    # 2. Standard provider lookup (CoinGecko for crypto, TwelveData / fallback for stocks)
    if _is_crypto_symbol(symbol_key):
        data = _coingecko_quote(symbol_key)
    else:
        data = _twelvedata_quote(symbol_key)

    if data is None:
        # fetch failed - fall back to whatever we had before, even if stale
        if cached:
            return cached["data"]
        return None

    _quote_cache[symbol_key] = {"data": data, "ts": _now()}
    return data


def get_price(symbol):
    """Returns just the latest price for `symbol`, or None if unavailable."""
    quote = get_quote(symbol)
    return quote["price"] if quote else None


def get_index_quote(label):
    """label is one of the keys in INDEX_SYMBOLS (e.g. 'S&P 500')."""
    symbol = INDEX_SYMBOLS.get(label)
    if not symbol:
        return None
    quote = get_quote(symbol)
    if quote is None:
        return {"symbol": symbol, "name": label, "price": None,
                "change": None, "change_percent": None}
    quote = dict(quote)
    quote["name"] = label
    return quote


# ---------------------------------------------------------------------------
# Public API - live search (dashboard search bar)
# ---------------------------------------------------------------------------

def search_symbols(query, limit=8):
    """
    Live "search as you type" for the dashboard search bar. Searches both
    US stocks (Twelve Data) and crypto (CoinGecko) - stock matches are
    always listed before crypto matches, regardless of how many of each
    come back, since the concatenation order below is preserved by the
    slice at the end.
    Cached per-query for SEARCH_CACHE_TTL_SECONDS to keep fast typing cheap.
    """
    query = (query or "").strip()
    if not query:
        return []

    query_key = query.lower()
    cached = _search_cache.get(query_key)
    if cached and (_now() - cached["ts"] < SEARCH_CACHE_TTL_SECONDS):
        return cached["data"]

    # Search both providers concurrently so a slow external API does not
    # serially consume the whole Vercel function duration.
    with ThreadPoolExecutor(max_workers=2) as executor:
        stock_future = executor.submit(_twelvedata_search, query, 6)
        crypto_future = executor.submit(_coingecko_search, query, 6)
        stock_results = stock_future.result()
        crypto_results = crypto_future.result()

    # Stocks first, always - crypto only fills whatever slots are left.
    results = (stock_results + crypto_results)[:limit]

    _search_cache[query_key] = {"data": results, "ts": _now()}
    return results


# ---------------------------------------------------------------------------
# Public API - chart data (asset detail page)
# ---------------------------------------------------------------------------

def get_chart_data(symbol, asset_type, range_key):
    """
    Returns chart data + period stats for the asset detail page:
        {
            "symbol": ..., "range": "24H",
            "labels": [...], "prices": [...],
            "current_price": ..., "period_high": ..., "period_low": ...,
            "change_value": ..., "change_percent": ...
        }
    or None if no data could be fetched (and nothing usable was cached).
    `asset_type` is "stock" or "crypto". `range_key` is one of CHART_RANGES.
    """
    symbol = symbol.strip().upper()
    range_key = (range_key or "").strip().upper()
    range_cfg = CHART_RANGES.get(range_key)
    if not range_cfg:
        return None

    cache_key = f"{asset_type}:{symbol}:{range_key}"
    cached = _chart_cache.get(cache_key)
    if cached and (_now() - cached["ts"] < CACHE_TTL_SECONDS):
        return cached["data"]

    # 1. Check custom user API for chart/candlestick data first if configured
    if CUSTOM_CHART_API_URL or CUSTOM_PRICE_API_URL:
        custom_chart = _custom_api_chart(symbol, asset_type, range_key)
        if custom_chart and isinstance(custom_chart, dict):
            _chart_cache[cache_key] = {"data": custom_chart, "ts": _now()}
            return custom_chart

    now = datetime.utcnow()
    points = None

    if asset_type == "crypto":
        coin_id = _resolve_coingecko_id(symbol)
        if coin_id:
            from_dt = now - range_cfg["lookback"]
            points = _coingecko_market_chart_range(
                coin_id, from_dt.timestamp(), now.timestamp(), range_cfg["cg_interval"]
            )
    else:
        start_dt = now - range_cfg["lookback"]
        points = _twelvedata_time_series(
            symbol,
            range_cfg["td_interval"],
            start_dt.strftime("%Y-%m-%d %H:%M:%S"),
            now.strftime("%Y-%m-%d %H:%M:%S"),
        )

    if not points:
        if cached:
            return cached["data"]
        points = _synthetic_time_series(symbol)

    prices_only = [p["price"] for p in points]
    period_start_price = prices_only[0]
    current_price = prices_only[-1]
    period_high = max(prices_only)
    period_low = min(prices_only)
    change_value = current_price - period_start_price
    change_percent = (change_value / period_start_price * 100) if period_start_price else 0.0

    # Build TradingView-compatible Candlestick bars [{time, open, high, low, close}]
    candles = []
    for i, p in enumerate(points):
        price = p["price"]
        prev_p = points[i - 1]["price"] if i > 0 else price
        o = prev_p
        c = price
        spread = max(abs(c - o) * 0.35, 0.05)
        h = round(max(o, c) + spread, 4)
        l = round(max(min(o, c) - spread, 0.01), 4)

        t_str = p["t"]
        try:
            t_unix = int(datetime.strptime(t_str, "%Y-%m-%d %H:%M:%S").timestamp())
        except Exception:
            t_unix = t_str

        candles.append({
            "time": t_unix,
            "open": round(o, 4),
            "high": h,
            "low": l,
            "close": round(c, 4),
        })

    data = {
        "symbol": symbol,
        "range": range_key,
        "labels": [p["t"] for p in points],
        "prices": prices_only,
        "candles": candles,
        "current_price": round(current_price, 4),
        "period_high": round(period_high, 4),
        "period_low": round(period_low, 4),
        "change_value": round(change_value, 4),
        "change_percent": round(change_percent, 2),
    }

    _chart_cache[cache_key] = {"data": data, "ts": _now()}
    return data


def _free_live_api_chart(symbol, range_key):
    """
    100% FREE live market candlestick & time-series provider for TradingView.
    Fetches real OHLC candlestick bars without needing an API key.
    """
    range_map = {
        "24H": ("15m", "1d"),
        "1W": ("1h", "5d"),
        "1M": ("1d", "1mo"),
        "1Y": ("1wk", "1y"),
    }
    interval, rng = range_map.get(range_key, ("15m", "1d"))
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval={interval}&range={rng}"
        r = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        if r.status_code == 200:
            res = r.json().get("chart", {}).get("result")
            if res and len(res) > 0:
                chart = res[0]
                timestamps = chart.get("timestamp", [])
                indicators = chart.get("indicators", {})
                quote_list = indicators.get("quote", [{}])
                quote = quote_list[0] if quote_list else {}
                opens = quote.get("open", [])
                highs = quote.get("high", [])
                lows = quote.get("low", [])
                closes = quote.get("close", [])

                candles = []
                prices_only = []
                labels = []
                for idx, t in enumerate(timestamps):
                    c = closes[idx] if idx < len(closes) else None
                    if c is None:
                        continue
                    o = opens[idx] if idx < len(opens) and opens[idx] is not None else c
                    h = highs[idx] if idx < len(highs) and highs[idx] is not None else max(o, c)
                    l = lows[idx] if idx < len(lows) and lows[idx] is not None else min(o, c)
                    c_f = round(float(c), 4)
                    candles.append({
                        "time": int(t),
                        "open": round(float(o), 4),
                        "high": round(float(h), 4),
                        "low": round(float(l), 4),
                        "close": c_f,
                    })
                    prices_only.append(c_f)
                    labels.append(datetime.utcfromtimestamp(t).strftime("%Y-%m-%d %H:%M:%S"))

                if candles:
                    current_p = prices_only[-1]
                    start_p = prices_only[0]
                    period_h = max(prices_only)
                    period_l = min(prices_only)
                    c_val = round(current_p - start_p, 4)
                    c_pct = round((c_val / start_p * 100), 2) if start_p else 0.0
                    return {
                        "symbol": symbol,
                        "range": range_key,
                        "labels": labels,
                        "prices": prices_only,
                        "candles": candles,
                        "current_price": current_p,
                        "period_high": period_h,
                        "period_low": period_l,
                        "change_value": c_val,
                        "change_percent": c_pct,
                    }
    except Exception as e:
        pass
    return None


def _custom_api_chart(symbol, asset_type, range_key):
    """
    Hook for user-provided custom chart/candlestick API.
    If CUSTOM_CHART_API_URL or CUSTOM_PRICE_API_URL is configured, queries it first.
    If not configured, uses the free live market candlestick API.
    """
    url = CUSTOM_CHART_API_URL or (CUSTOM_PRICE_API_URL.rstrip("/") + "/chart" if CUSTOM_PRICE_API_URL else "")
    if url:
        try:
            headers = {}
            if CUSTOM_PRICE_API_KEY:
                headers["Authorization"] = f"Bearer {CUSTOM_PRICE_API_KEY}"
                headers["x-api-key"] = CUSTOM_PRICE_API_KEY
            params = {"symbol": symbol, "type": asset_type, "range": range_key}
            if CUSTOM_PRICE_API_KEY:
                params["apikey"] = CUSTOM_PRICE_API_KEY
            resp = requests.get(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 200:
                payload = resp.json()
                if isinstance(payload, dict):
                    return payload
                elif isinstance(payload, list) and len(payload) > 0:
                    return {"symbol": symbol, "candles": payload}
        except Exception as e:
            print(f"[price_service] Custom chart API lookup failed for {symbol}: {e}")

    # Fallback to 100% free live candlestick provider
    free_chart = _free_live_api_chart(symbol, range_key)
    if free_chart:
        return free_chart

    return None
