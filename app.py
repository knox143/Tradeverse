from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from concurrent.futures import ThreadPoolExecutor
import sqlite3
import os
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv

load_dotenv()

from storage_paths import IS_VERCEL, prepare_storage

import portfolio_db
import price_service

app = Flask(__name__, static_folder="public/static", static_url_path="/static")

FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "").strip() or "tradeverse-secret-production-key-2026-safe"
app.secret_key = FLASK_SECRET_KEY
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=IS_VERCEL,
    SESSION_COOKIE_NAME="tradeverse_session",
)

DB_PATH, _TINYDB_RUNTIME_PATH = prepare_storage()

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin@123"
ADMIN_EMAIL = "admin@gmail.com"
ADMIN_PHONE = "1234567890"

MARKET_FULL_NAMES = {
    "ISE": "Indian Stock Exchange",
    "USE": "US Stock Exchange",
    "CCME": "Crypto Currency Market Exchange",
}

MARKET_CURRENCY_SYMBOL = {
    "ISE": "\u20B9",   # INR
    "USE": "$",
    "CCME": "$",
}


# Initialize the file-backed stores when the module is imported. Vercel imports
# the Flask module instead of executing the __main__ block.
init_db_ready = False

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            phone TEXT NOT NULL,
            password TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


def ensure_admin_account():
    """Creates the default admin login (SQLite) + its demo portfolio (tinymongo), if missing."""
    conn = get_db_connection()
    admin = conn.execute(
        "SELECT * FROM users WHERE username = ?", (ADMIN_USERNAME,)
    ).fetchone()

    if admin is None:
        hashed_password = generate_password_hash(ADMIN_PASSWORD)
        conn.execute(
            "INSERT INTO users (username, email, phone, password) VALUES (?, ?, ?, ?)",
            (ADMIN_USERNAME, ADMIN_EMAIL, ADMIN_PHONE, hashed_password),
        )
        conn.commit()
        admin = conn.execute(
            "SELECT * FROM users WHERE username = ?", (ADMIN_USERNAME,)
        ).fetchone()

    conn.close()
    portfolio_db.ensure_admin_portfolio(admin["id"], admin["username"])


# Run initialization at import time for Vercel and other WSGI/serverless hosts.
init_db()
if os.getenv("TRADEVERSE_BOOTSTRAP_ADMIN", "0") == "1":
    ensure_admin_account()


@app.route("/")
def home():
    if "username" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "")

        if not username or not email or not phone or not password:
            flash("Please fill in all fields.", "error")
            return render_template("register.html")

        if len(password) < 6:
            flash("Password must be at least 6 characters long.", "error")
            return render_template("register.html")

        hashed_password = generate_password_hash(password)

        conn = get_db_connection()
        try:
            cur = conn.execute(
                "INSERT INTO users (username, email, phone, password) VALUES (?, ?, ?, ?)",
                (username, email, phone, hashed_password),
            )
            conn.commit()
            new_user_id = cur.lastrowid
            conn.close()

            # Every new user starts with empty portfolios + the default wallet amounts:
            # ISE: 10,00,000 INR | USE: 10,000 USD | CCME: 10,000 USD
            portfolio_db.create_default_portfolio(new_user_id, username)

            flash("Account created successfully! Please log in.", "success")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            conn.close()
            flash("Username or email already exists.", "error")
            return render_template("register.html")

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        conn = get_db_connection()
        user = conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()
        conn.close()

        if user and check_password_hash(user["password"], password):
            session["username"] = user["username"]
            session["user_id"] = user["id"]
            flash("Welcome back, " + user["username"] + "!", "success")
            return redirect(url_for("dashboard"))
        else:
            flash("Invalid username or password.", "error")
            return render_template("login.html")

    return render_template("login.html")


@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        flash("If this account exists, password reset instructions have been noted. (Demo feature)", "success")
        return redirect(url_for("login"))
    return render_template("forgot_password.html")


@app.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        return redirect(url_for("login"))
    return render_template("dashboard.html", username=session["username"])


@app.route("/portfolio")
def portfolio_page():
    if "user_id" not in session:
        return redirect(url_for("login"))
    return render_template("portfolio.html", username=session["username"])


@app.route("/market/<market>")
def market_page(market):
    if "user_id" not in session:
        return redirect(url_for("login"))

    market = market.upper()
    if market not in portfolio_db.MARKETS:
        flash("Unknown market.", "error")
        return redirect(url_for("dashboard"))

    return render_template(
        "market.html",
        username=session["username"],
        market=market,
        market_name=MARKET_FULL_NAMES[market],
        currency_symbol=MARKET_CURRENCY_SYMBOL[market],
    )


@app.route("/logout")
def logout():
    session.pop("username", None)
    session.pop("user_id", None)
    flash("You have been logged out.", "success")
    return redirect(url_for("login"))


# ---------------------------------------------------------------------------
# JSON APIs used by the dashboard's JavaScript
# ---------------------------------------------------------------------------

@app.route("/api/portfolio/<market>")
def api_portfolio(market):
    if "user_id" not in session:
        return jsonify({"error": "not logged in"}), 401

    market = market.upper()
    if market not in portfolio_db.MARKETS:
        return jsonify({"error": "invalid market"}), 400

    snapshot = portfolio_db.get_market_snapshot(session["user_id"], market)
    snapshot["market"] = market
    return jsonify(snapshot)



def _json_error(message, status=400):
    return jsonify({"error": message}), status


def _trading_market_for_asset(asset_type, symbol):
    """Map supported asset types to their wallet: crypto -> CCME, Indian stocks (.NS/.BO) -> ISE, other stocks -> USE."""
    asset_type = (asset_type or "").lower().strip()
    symbol = (symbol or "").upper().strip()
    if asset_type == "crypto" or symbol.endswith("-USD"):
        return "CCME"
    if symbol.endswith(".NS") or symbol.endswith(".BO"):
        return "ISE"
    return "USE"


@app.route("/api/portfolio/summary")
def api_portfolio_summary():
    if "user_id" not in session:
        return jsonify({"error": "not logged in"}), 401
    summary = portfolio_db.get_portfolio_summary(session["user_id"])
    return jsonify(summary)


@app.route("/api/portfolio/transactions")
def api_portfolio_transactions():
    if "user_id" not in session:
        return jsonify({"error": "not logged in"}), 401
    market = request.args.get("market", "").strip() or None
    tx_type = request.args.get("type", "").strip() or None
    txs = portfolio_db.get_user_transactions(session["user_id"], market=market, tx_type=tx_type)
    return jsonify({"transactions": txs, "count": len(txs)})


@app.route("/api/trade/buy", methods=["POST"])
@app.route("/api/portfolio/buy", methods=["POST"])
def api_buy():
    if "user_id" not in session:
        return _json_error("not logged in", 401)

    data = request.get_json(silent=True) or {}
    asset_type = str(data.get("asset_type", "")).lower().strip()
    symbol = str(data.get("symbol", "")).upper().strip()
    quantity = data.get("quantity")
    market = str(data.get("market", "")).upper().strip()

    if not market or market not in portfolio_db.MARKETS:
        market = _trading_market_for_asset(asset_type, symbol)

    if market not in portfolio_db.MARKETS:
        return _json_error("Invalid market or unsupported asset.")

    try:
        current_price = data.get("current_price") or data.get("price")
        result = portfolio_db.buy_asset(
            session["user_id"], market, symbol, quantity, current_price
        )
        return jsonify({"success": True, **result})
    except ValueError as exc:
        return _json_error(str(exc))
    except Exception:
        app.logger.exception("Buy transaction failed")
        return _json_error("The trade could not be completed. Please try again.", 500)


@app.route("/api/trade/sell", methods=["POST"])
@app.route("/api/portfolio/sell", methods=["POST"])
def api_sell():
    if "user_id" not in session:
        return _json_error("not logged in", 401)

    data = request.get_json(silent=True) or {}
    market = str(data.get("market", "")).upper().strip()
    lot_id = str(data.get("lot_id", "")).strip()
    quantity = data.get("quantity")

    if not market or market not in portfolio_db.MARKETS:
        # Resolve market from lot_id
        doc = portfolio_db.get_portfolio_doc(session["user_id"])
        if doc:
            for m in portfolio_db.MARKETS:
                for h in doc.get(m + "_portfolio", []):
                    if str(h.get("lot_id")) == lot_id:
                        market = m
                        break
                if market in portfolio_db.MARKETS:
                    break

    if market not in portfolio_db.MARKETS:
        return _json_error("Invalid market.")

    try:
        current_price = data.get("current_price") or data.get("price")
        result = portfolio_db.sell_lot(
            session["user_id"], market, lot_id, quantity, current_price
        )
        return jsonify({"success": True, **result})
    except ValueError as exc:
        return _json_error(str(exc))
    except Exception:
        app.logger.exception("Sell transaction failed")
        return _json_error("The trade could not be completed. Please try again.", 500)


@app.route("/api/btc")
def api_btc():
    if "user_id" not in session:
        return jsonify({"error": "not logged in"}), 401

    quote = price_service.get_quote("BTC-USD")
    if quote is None:
        return jsonify({"price": None, "change": None, "change_percent": None})

    return jsonify(quote)


@app.route("/api/indices")
def api_indices():
    if "user_id" not in session:
        return jsonify({"error": "not logged in"}), 401

    labels = ("S&P 500", "NIFTY 50", "SENSEX")

    def _get_index(label):
        return jsonify([
            { "symbol": "SPX", "name": "S&P 500", "price": 6250.00, "change": 28.13, "change_percent": 0.45 },
            { "symbol": "NIFTY", "name": "NIFTY 50", "price": 25000.00, "change": 95.00, "change_percent": 0.38 },
            { "symbol": "SENSEX", "name": "SENSEX", "price": 82000.00, "change": 336.20, "change_percent": 0.41 }
        ])

    with ThreadPoolExecutor(max_workers=3) as executor:
        results = list(executor.map(_get_index, labels))
    return jsonify(results)

@app.route("/api/search")
def api_search():
    """Live search-as-you-type used by the dashboard search bar."""
    if "user_id" not in session:
        return jsonify({"error": "not logged in"}), 401

    query = request.args.get("q", "").strip()
    if len(query) < 1:
        return jsonify([])

    results = price_service.search_symbols(query)
    return jsonify(results)


# ---------------------------------------------------------------------------
# Asset detail page (price chart + stats for one stock or crypto coin)
# ---------------------------------------------------------------------------

@app.route("/asset/<asset_type>/<symbol>")
def asset_page(asset_type, symbol):
    if "user_id" not in session:
        return redirect(url_for("login"))

    asset_type = asset_type.lower()
    if asset_type not in ("stock", "crypto"):
        flash("Unknown asset type.", "error")
        return redirect(url_for("dashboard"))

    symbol = symbol.upper()
    display_name = request.args.get("name", "").strip() or symbol

    return render_template(
        "asset.html",
        username=session["username"],
        symbol=symbol,
        asset_type=asset_type,
        display_name=display_name,
    )


@app.route("/api/asset/<asset_type>/<symbol>/chart")
def api_asset_chart(asset_type, symbol):
    if "user_id" not in session:
        return jsonify({"error": "not logged in"}), 401

    asset_type = asset_type.lower()
    if asset_type not in ("stock", "crypto"):
        return jsonify({"error": "invalid asset type"}), 400

    range_key = request.args.get("range", "24H").upper()
    if range_key not in price_service.CHART_RANGES:
        return jsonify({"error": "invalid range"}), 400

    data = price_service.get_chart_data(symbol.upper(), asset_type, range_key)
    if data is None:
        return jsonify({"error": "Could not load chart data for this symbol right now."}), 502

    return jsonify(data)


if __name__ == "__main__":
    port_val = os.getenv("PORT", "").strip() or "5000"
    try:
        port = int(port_val)
    except (ValueError, TypeError):
        port = 5000
    app.run(host="0.0.0.0", port=port, debug=os.getenv("FLASK_DEBUG", "0") == "1")
