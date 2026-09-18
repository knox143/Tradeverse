"""
portfolio_db.py
----------------
NoSQL storage layer for TradeVerse user wallets & portfolios, using tinymongo
(a MongoDB-like wrapper around TinyDB, stored as local JSON files).

One document per user, shaped like:

{
    "user_id": 1,                # matches the SQLite users.id
    "username": "admin",
    "wallet": {
        "ISE": 1000000.0,        # INR
        "USE": 10000.0,          # USD
        "CCME": 10000.0          # USD
    },
    "ISE_portfolio": [
        {"name": "RELIANCE.NS", "bought_price": 2400.0, "price": 2400.0,
         "quantity": 20, "total_amount": 48000.0},
        ...
    ],
    "USE_portfolio": [...],
    "CCME_portfolio": [...]
}

ISE  = Indian Stock Exchange             (currency: INR)
USE  = US Stock Exchange                 (currency: USD)
CCME = Crypto Currency Market Exchange   (currency: USD)
"""

import os
import uuid
from decimal import Decimal, InvalidOperation
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

from tinymongo import TinyMongoClient

from storage_paths import prepare_storage

import price_service

_, STORAGE_FOLDER = prepare_storage()

_client = TinyMongoClient(str(STORAGE_FOLDER))
_db = _client.tradeverse
portfolios = _db.portfolios

MARKETS = ("ISE", "USE", "CCME")
CURRENCY_BY_MARKET = {"ISE": "INR", "USE": "USD", "CCME": "USD"}

DEFAULT_WALLET = {
    "ISE": 1000000.0,   # 10,00,000 INR
    "USE": 10000.0,     # 10,000 USD
    "CCME": 10000.0,    # 10,000 USD
}


def _empty_portfolio_doc(user_id, username, wallet=None, holdings=None, transactions=None):
    holdings = holdings or {"ISE": [], "USE": [], "CCME": []}
    return {
        "user_id": user_id,
        "username": username,
        "wallet": dict(wallet or DEFAULT_WALLET),
        "ISE_portfolio": holdings.get("ISE", []),
        "USE_portfolio": holdings.get("USE", []),
        "CCME_portfolio": holdings.get("CCME", []),
        "transactions": list(transactions or []),
    }


def get_portfolio_doc(user_id):
    return portfolios.find_one({"user_id": user_id})


def create_default_portfolio(user_id, username):
    """Called whenever a brand new user registers. All portfolios start empty."""
    if get_portfolio_doc(user_id):
        return
    doc = _empty_portfolio_doc(user_id, username)
    portfolios.insert_one(doc)


def _holding(name, bought_price, quantity, bought_days_ago=0):
    total = round(bought_price * quantity, 2)
    bought_date = (datetime.utcnow() - timedelta(days=bought_days_ago)).strftime("%Y-%m-%d")
    return {
        "lot_id": uuid.uuid4().hex,
        "name": name,
        "bought_date": bought_date,
        "bought_at": bought_date + "T10:00:00Z",
        "bought_price": round(bought_price, 2),
        "price": round(bought_price, 2),
        "quantity": quantity,
        "total_amount": total,
    }


def ensure_admin_portfolio(user_id, username="admin"):
    """Creates a demo portfolio for the built-in admin account, if it doesn't exist yet."""
    existing = get_portfolio_doc(user_id)
    if existing:
        _ensure_transactions(user_id, existing)
        return

    ise_holdings = [
        _holding("RELIANCE.NS", 2400.0, 20, bought_days_ago=45),
        _holding("TCS.NS", 3500.0, 10, bought_days_ago=120),
        _holding("INFY.NS", 1450.0, 15, bought_days_ago=200),
    ]
    use_holdings = [
        _holding("AAPL", 180.0, 15, bought_days_ago=60),
        _holding("MSFT", 320.0, 10, bought_days_ago=150),
        _holding("TSLA", 250.0, 8, bought_days_ago=30),
    ]
    ccme_holdings = [
        _holding("BTC-USD", 45000.0, 0.10, bought_days_ago=90),
        _holding("ETH-USD", 2500.0, 1.5, bought_days_ago=20),
    ]

    ise_spent = sum(h["total_amount"] for h in ise_holdings)
    use_spent = sum(h["total_amount"] for h in use_holdings)
    ccme_spent = sum(h["total_amount"] for h in ccme_holdings)

    wallet = {
        "ISE": round(DEFAULT_WALLET["ISE"] - ise_spent, 2),
        "USE": round(DEFAULT_WALLET["USE"] - use_spent, 2),
        "CCME": round(DEFAULT_WALLET["CCME"] - ccme_spent, 2),
    }

    initial_tx = []
    for h in ise_holdings:
        initial_tx.append({
            "id": uuid.uuid4().hex[:10],
            "type": "BUY",
            "symbol": h["name"],
            "market": "ISE",
            "quantity": h["quantity"],
            "price": h["bought_price"],
            "total_amount": h["total_amount"],
            "profit_loss": None,
            "currency": "INR",
            "lot_id": h["lot_id"],
            "timestamp": h["bought_at"],
            "date": h["bought_date"] + " 10:00:00",
            "status": "COMPLETED",
        })
    for h in use_holdings:
        initial_tx.append({
            "id": uuid.uuid4().hex[:10],
            "type": "BUY",
            "symbol": h["name"],
            "market": "USE",
            "quantity": h["quantity"],
            "price": h["bought_price"],
            "total_amount": h["total_amount"],
            "profit_loss": None,
            "currency": "USD",
            "lot_id": h["lot_id"],
            "timestamp": h["bought_at"],
            "date": h["bought_date"] + " 14:30:00",
            "status": "COMPLETED",
        })
    for h in ccme_holdings:
        initial_tx.append({
            "id": uuid.uuid4().hex[:10],
            "type": "BUY",
            "symbol": h["name"],
            "market": "CCME",
            "quantity": h["quantity"],
            "price": h["bought_price"],
            "total_amount": h["total_amount"],
            "profit_loss": None,
            "currency": "USD",
            "lot_id": h["lot_id"],
            "timestamp": h["bought_at"],
            "date": h["bought_date"] + " 12:00:00",
            "status": "COMPLETED",
        })

    doc = _empty_portfolio_doc(
        user_id,
        username,
        wallet=wallet,
        holdings={"ISE": ise_holdings, "USE": use_holdings, "CCME": ccme_holdings},
        transactions=initial_tx,
    )
    portfolios.insert_one(doc)



def _new_lot_id():
    """Create a unique identifier for every purchase lot."""
    return uuid.uuid4().hex


def _normalise_quantity(value):
    """Validate and normalise a positive quantity without allowing 0/negative values."""
    try:
        quantity = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("Quantity must be a valid number.")
    if not quantity.is_finite() or quantity <= 0:
        raise ValueError("Quantity must be greater than 0.")
    # Keep fractional crypto quantities while avoiding excessive precision.
    quantity = quantity.quantize(Decimal("0.00000001"))
    if quantity <= 0:
        raise ValueError("Quantity must be greater than 0.")
    return float(quantity)


def _money(value):
    try:
        amount = Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("Invalid price.")
    if not amount.is_finite() or amount <= 0:
        raise ValueError("Current price is unavailable.")
    return float(amount)


def _ensure_lot_ids(user_id, market, doc=None):
    """Migrate old holdings in-place by assigning lot IDs without changing their quantities."""
    if market not in MARKETS:
        raise ValueError("Unknown market: " + market)
    if doc is None:
        doc = get_portfolio_doc(user_id)
    if not doc:
        return None

    field = market + "_portfolio"
    holdings = list(doc.get(field, []))
    changed = False
    migrated = []
    for holding in holdings:
        item = dict(holding)
        if not item.get("lot_id"):
            item["lot_id"] = _new_lot_id()
            # Existing lots have a date but no timestamp. Keep the original date
            # and use a migration timestamp only for uniqueness/audit purposes.
            item.setdefault("bought_at", item.get("bought_date"))
            changed = True
        migrated.append(item)

    if changed:
        portfolios.update_one({"user_id": user_id}, {"$set": {field: migrated}})
        doc[field] = migrated
    return doc


def _ensure_transactions(user_id, doc=None):
    """Ensure existing user docs have initial transactions seeded if they have holdings."""
    if doc is None:
        doc = get_portfolio_doc(user_id)
    if not doc:
        return None
    txs = doc.get("transactions")
    if txs is not None and len(txs) > 0:
        return doc

    seeded_tx = []
    for market in MARKETS:
        field = market + "_portfolio"
        holdings = doc.get(field, [])
        currency = CURRENCY_BY_MARKET.get(market, "USD")
        for h in holdings:
            date_val = h.get("bought_date") or datetime.utcnow().strftime("%Y-%m-%d")
            seeded_tx.append({
                "id": uuid.uuid4().hex[:10],
                "type": "BUY",
                "symbol": h.get("name", "").upper(),
                "market": market,
                "quantity": h.get("quantity", 0),
                "price": h.get("bought_price", h.get("price", 0)),
                "total_amount": h.get("total_amount", 0),
                "profit_loss": None,
                "currency": currency,
                "lot_id": h.get("lot_id"),
                "timestamp": h.get("bought_at") or (date_val + "T10:00:00Z"),
                "date": date_val + " 10:00:00",
                "status": "COMPLETED",
            })
    portfolios.update_one({"user_id": user_id}, {"$set": {"transactions": seeded_tx}})
    doc["transactions"] = seeded_tx
    return doc


def record_transaction(user_id, tx_type, symbol, market, quantity, price, total_amount, currency=None, profit_loss=None, lot_id=None):
    doc = get_portfolio_doc(user_id)
    if not doc:
        return None
    market = market.upper()
    currency = currency or CURRENCY_BY_MARKET.get(market, "USD")
    now_utc = datetime.utcnow()
    tx = {
        "id": uuid.uuid4().hex[:10],
        "type": tx_type.upper(),
        "symbol": symbol.upper(),
        "market": market,
        "quantity": quantity,
        "price": round(float(price), 2),
        "total_amount": round(float(total_amount), 2),
        "profit_loss": round(float(profit_loss), 2) if profit_loss is not None else None,
        "currency": currency,
        "lot_id": lot_id,
        "timestamp": now_utc.isoformat(timespec="milliseconds") + "Z",
        "date": now_utc.strftime("%Y-%m-%d %H:%M:%S"),
        "status": "COMPLETED",
    }
    transactions = list(doc.get("transactions", []))
    transactions.append(tx)
    portfolios.update_one({"user_id": user_id}, {"$set": {"transactions": transactions}})
    doc["transactions"] = transactions
    return tx


def buy_asset(user_id, market, symbol, quantity, current_price=None):
    """Buy a new independent lot and deduct its cost from the market wallet."""
    market = market.upper()
    if market not in MARKETS:
        raise ValueError(f"Unknown market: {market}")

    quantity = _normalise_quantity(quantity)
    if market in ("USE", "ISE") and not quantity.is_integer():
        raise ValueError(f"{market} stock quantity must be a whole number.")
    symbol = symbol.strip().upper()
    if not symbol:
        raise ValueError("Asset symbol is required.")

    # Use live price or provided current_price fallback
    live_price = None
    if current_price is not None:
        try:
            live_price = _money(current_price)
        except Exception:
            pass
    if live_price is None:
        live_price = price_service.get_price(symbol)
    if live_price is None:
        raise ValueError("Current market price is unavailable. Please try again.")
    price = _money(live_price)
    total = round(price * quantity, 2)

    doc = get_portfolio_doc(user_id)
    if not doc:
        raise ValueError("Portfolio not found.")

    wallet = dict(doc.get("wallet", {}))
    balance = round(float(wallet.get(market, 0)), 2)
    if total > balance + 1e-9:
        currency_sym = "₹" if market == "ISE" else "$"
        raise ValueError(
            f"Insufficient balance. Required {currency_sym}{total:.2f}, available {currency_sym}{balance:.2f}."
        )

    new_lot_id = _new_lot_id()
    now_utc = datetime.utcnow()
    lot = {
        "lot_id": new_lot_id,
        "name": symbol,
        "bought_date": now_utc.strftime("%Y-%m-%d"),
        "bought_at": now_utc.isoformat(timespec="seconds") + "Z",
        "bought_price": price,
        "price": price,
        "quantity": quantity,
        "total_amount": total,
    }

    field = market + "_portfolio"
    holdings = list(doc.get(field, []))
    holdings.append(lot)  # Never merge lots, even when symbol/price/time are identical.
    wallet[market] = round(balance - total, 2)

    portfolios.update_one(
        {"user_id": user_id},
        {"$set": {field: holdings, "wallet": wallet}},
    )

    # Record buy transaction in audit trail
    tx = record_transaction(
        user_id,
        "BUY",
        symbol,
        market,
        quantity,
        price,
        total,
        currency=CURRENCY_BY_MARKET[market],
        lot_id=new_lot_id,
    )

    return {
        "market": market,
        "lot": lot,
        "wallet": wallet[market],
        "total_amount": total,
        "currency": CURRENCY_BY_MARKET[market],
        "transaction": tx,
    }


def sell_lot(user_id, market, lot_id, quantity, current_price=None):
    """Sell part or all of one exact lot and credit proceeds to its market wallet."""
    market = market.upper()
    if market not in MARKETS:
        raise ValueError(f"Unknown market: {market}")

    quantity_to_sell = _normalise_quantity(quantity)
    if market in ("USE", "ISE") and not quantity_to_sell.is_integer():
        raise ValueError(f"{market} stock quantity must be a whole number.")
    lot_id = str(lot_id).strip()
    if not lot_id:
        raise ValueError("Lot ID is required.")

    doc = _ensure_lot_ids(user_id, market)
    if not doc:
        raise ValueError("Portfolio not found.")

    field = market + "_portfolio"
    holdings = list(doc.get(field, []))
    index = next((i for i, h in enumerate(holdings) if str(h.get("lot_id")) == lot_id), None)
    if index is None:
        raise ValueError("That holding lot no longer exists. Refresh the portfolio and try again.")

    lot = dict(holdings[index])
    available = _normalise_quantity(lot.get("quantity", 0))
    if quantity_to_sell > available + 1e-9:
        raise ValueError(f"You can sell at most {available:g} from this lot.")

    symbol = str(lot.get("name", "")).upper()
    live_price = None
    if current_price is not None:
        try:
            live_price = _money(current_price)
        except Exception:
            pass
    if live_price is None:
        live_price = price_service.get_price(symbol)
    if live_price is None:
        live_price = lot.get("price") or lot.get("bought_price")
    if live_price is None:
        raise ValueError("Current market price is unavailable. Please try again.")
    price = _money(live_price)
    proceeds = round(price * quantity_to_sell, 2)
    bought_price = float(lot.get("bought_price", price))
    realized_pl = round((price - bought_price) * quantity_to_sell, 2)

    wallet = dict(doc.get("wallet", {}))
    balance = round(float(wallet.get(market, 0)), 2)
    new_quantity = round(available - quantity_to_sell, 8)

    if new_quantity <= 0:
        holdings.pop(index)
    else:
        lot["quantity"] = new_quantity
        # Keep the lot's original bought price/date/id. Only the remaining
        # quantity and current valuation are changed.
        lot["price"] = price
        lot["total_amount"] = round(price * new_quantity, 2)
        holdings[index] = lot

    wallet[market] = round(balance + proceeds, 2)
    portfolios.update_one(
        {"user_id": user_id},
        {"$set": {field: holdings, "wallet": wallet}},
    )

    # Record sell transaction in audit trail
    tx = record_transaction(
        user_id,
        "SELL",
        symbol,
        market,
        quantity_to_sell,
        price,
        proceeds,
        currency=CURRENCY_BY_MARKET[market],
        profit_loss=realized_pl,
        lot_id=lot_id,
    )

    return {
        "market": market,
        "lot_id": lot_id,
        "symbol": symbol,
        "quantity_sold": quantity_to_sell,
        "proceeds": proceeds,
        "profit_loss": realized_pl,
        "remaining_quantity": new_quantity,
        "wallet": wallet[market],
        "currency": CURRENCY_BY_MARKET[market],
        "transaction": tx,
    }

def get_market_snapshot(user_id, market):
    """
    Returns the wallet amount + holdings for one market (ISE/USE/CCME), with
    live prices refreshed through price_service (10-minute cache under the hood).
    Also persists the refreshed prices back into the document.
    """
    market = market.upper()
    if market not in MARKETS:
        raise ValueError("Unknown market: " + market)

    doc = get_portfolio_doc(user_id)
    if not doc:
        return {"wallet": 0, "currency": CURRENCY_BY_MARKET[market], "holdings": []}

    doc = _ensure_lot_ids(user_id, market, doc)
    field = market + "_portfolio"
    holdings = doc.get(field, [])

    def _refresh_holding(h):
        live_price = price_service.get_price(h["name"])
        price = live_price if live_price is not None else h.get("price", h.get("bought_price", 0))
        quantity = h.get("quantity", 0)
        bought_price = h.get("bought_price", 0)

        profit_loss = round(price - bought_price, 2)
        profit_loss_percent = round((profit_loss / bought_price) * 100, 2) if bought_price else 0.0

        return {
            "lot_id": h.get("lot_id"),
            "name": h["name"],
            "bought_date": h.get("bought_date"),
            "bought_at": h.get("bought_at"),
            "bought_price": bought_price,
            "price": round(price, 2),
            "quantity": quantity,
            "total_amount": round(price * quantity, 2),
            "profit_loss": profit_loss,
            "profit_loss_percent": profit_loss_percent,
        }

    # Fetch independent quotes concurrently. This matters on Vercel because
    # a market page can contain several holdings and each external API call
    # has network latency. Keeping them parallel avoids serial timeout buildup.
    if holdings:
        worker_count = min(6, len(holdings))
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            refreshed = list(executor.map(_refresh_holding, holdings))
    else:
        refreshed = []

    if refreshed:
        # Persist only the fields that are actually stored (not the derived
        # profit/loss numbers, which are recomputed fresh on every read).
        stored = [
            {k: r[k] for k in ("lot_id", "name", "bought_date", "bought_at", "bought_price", "price", "quantity", "total_amount")}
            for r in refreshed
        ]
        portfolios.update_one({"user_id": user_id}, {"$set": {field: stored}})

    wallet_amount = doc.get("wallet", {}).get(market, 0)

    return {
        "wallet": wallet_amount,
        "currency": CURRENCY_BY_MARKET[market],
        "holdings": refreshed,
    }


def get_user_transactions(user_id, market=None, tx_type=None):
    """Return transaction history for user, sorted newest first."""
    doc = _ensure_transactions(user_id)
    if not doc:
        return []
    txs = list(reversed(doc.get("transactions", [])))
    if market:
        m = market.upper()
        txs = [t for t in txs if t.get("market") == m]
    if tx_type:
        tt = tx_type.upper()
        txs = [t for t in txs if t.get("type") == tt]

    txs.sort(key=lambda t: t.get("timestamp") or t.get("date") or "", reverse=True)
    return txs


def get_portfolio_summary(user_id):
    """Comprehensive portfolio summary combining all markets, holdings, and transactions."""
    doc = get_portfolio_doc(user_id)
    if not doc:
        return {
            "wallet": DEFAULT_WALLET,
            "invested_by_market": {},
            "current_by_market": {},
            "pl_by_market": {},
            "holdings": [],
            "transactions": [],
            "stats": {"total_trades": 0, "buy_count": 0, "sell_count": 0, "holdings_count": 0}
        }

    _ensure_transactions(user_id, doc)
    all_holdings = []
    invested_by_market = {}
    current_by_market = {}
    pl_by_market = {}

    for market in MARKETS:
        snapshot = get_market_snapshot(user_id, market)
        m_holdings = snapshot.get("holdings", [])
        m_invested = sum(h.get("bought_price", 0) * h.get("quantity", 0) for h in m_holdings)
        m_current = sum(h.get("total_amount", 0) for h in m_holdings)
        m_pl = round(m_current - m_invested, 2)

        invested_by_market[market] = round(m_invested, 2)
        current_by_market[market] = round(m_current, 2)
        pl_by_market[market] = m_pl

        for h in m_holdings:
            h_copy = dict(h)
            h_copy["market"] = market
            h_copy["currency"] = CURRENCY_BY_MARKET[market]
            h_copy["currency_symbol"] = "₹" if market == "ISE" else "$"
            all_holdings.append(h_copy)

    transactions = get_user_transactions(user_id)
    buy_count = sum(1 for t in transactions if t.get("type") == "BUY")
    sell_count = sum(1 for t in transactions if t.get("type") == "SELL")

    total_realized_pl_usd = sum(t.get("profit_loss", 0) or 0 for t in transactions if t.get("type") == "SELL" and t.get("market") in ("USE", "CCME"))
    total_realized_pl_inr = sum(t.get("profit_loss", 0) or 0 for t in transactions if t.get("type") == "SELL" and t.get("market") == "ISE")

    return {
        "wallet": doc.get("wallet", DEFAULT_WALLET),
        "holdings": all_holdings,
        "invested_by_market": invested_by_market,
        "current_by_market": current_by_market,
        "pl_by_market": pl_by_market,
        "transactions": transactions,
        "recent_transactions": transactions[:10],
        "stats": {
            "total_trades": len(transactions),
            "buy_count": buy_count,
            "sell_count": sell_count,
            "realized_pl_usd": round(total_realized_pl_usd, 2),
            "realized_pl_inr": round(total_realized_pl_inr, 2),
            "holdings_count": len(all_holdings),
        }
    }
