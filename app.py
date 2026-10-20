from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, Response
from concurrent.futures import ThreadPoolExecutor
import sqlite3
import os
import re
import secrets
import random
import time
import json
import hashlib
import smtplib
from email.mime.text import MIMEText
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
            password TEXT NOT NULL,
            session_token TEXT
        )
    """)
    # Ensure session_token column exists in existing database
    cursor = conn.execute("PRAGMA table_info(users)")
    columns = [col[1] for col in cursor.fetchall()]
    if "session_token" not in columns:
        conn.execute("ALTER TABLE users ADD COLUMN session_token TEXT")
    conn.commit()
    conn.close()


SMTP_USER = os.getenv("SMTP_USER", "").strip()
SMTP_PASS = os.getenv("SMTP_PASS", "").strip()
SMTP_HOST = os.getenv("SMTP_HOST", "").strip() or ("smtp.gmail.com" if SMTP_USER else "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_FROM = os.getenv("SMTP_FROM", "").strip() or SMTP_USER or "noreply@tradeverse.com"

def send_verification_otp(email, otp):
    """Sends OTP via SMTP if configured; always logs in console."""
    print(f"[OTP SERVICE] Email OTP for {email}: {otp}")
    if SMTP_HOST and SMTP_USER and SMTP_PASS:
        try:
            msg = MIMEText(
                f"Hello,\n\n"
                f"Your TradeVerse verification code is: {otp}\n\n"
                f"Enter this 6-digit code on the registration page to verify your email.\n"
                f"This code will expire in 10 minutes.\n\n"
                f"Happy Trading,\nTradeVerse Team"
            )
            msg["Subject"] = f"{otp} is your TradeVerse verification code"
            msg["From"] = SMTP_FROM
            msg["To"] = email

            if SMTP_PORT == 465:
                with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=10) as server:
                    server.login(SMTP_USER, SMTP_PASS)
                    server.sendmail(SMTP_FROM, [email], msg.as_string())
            else:
                with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
                    server.starttls()
                    server.login(SMTP_USER, SMTP_PASS)
                    server.sendmail(SMTP_FROM, [email], msg.as_string())
            return True
        except Exception as e:
            app.logger.warning(f"SMTP error sending OTP to {email}: {e}")
            return False
    return False

def generate_captcha_text():
    chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(random.choices(chars, k=5))

_login_failures = {} # ip -> [timestamps]

def is_ip_rate_limited(ip):
    now = time.time()
    attempts = [t for t in _login_failures.get(ip, []) if now - t < 300]
    _login_failures[ip] = attempts
    return len(attempts) >= 5

def record_login_failure(ip):
    now = time.time()
    attempts = [t for t in _login_failures.get(ip, []) if now - t < 300]
    attempts.append(now)
    _login_failures[ip] = attempts
    if len(attempts) >= 3:
        time.sleep(min(2 ** (len(attempts) - 3), 3))

def clear_login_failure(ip):
    _login_failures.pop(ip, None)


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


@app.before_request
def enforce_single_device_session():
    # Allow static assets and unauthenticated endpoints
    if request.path.startswith("/static") or request.endpoint in ("login", "register", "verify_otp", "resend_otp", "forgot_password", "api_captcha", "home", None):
        return

    # In serverless environments (like Vercel) where filesystem is ephemeral per lambda instance,
    # instance-local SQLite session checks cause false-positive logouts across concurrent lambdas.
    if IS_VERCEL:
        return

    # Never clear session on API calls
    if request.path.startswith("/api/"):
        return

    if "user_id" in session:
        conn = get_db_connection()
        user = conn.execute("SELECT session_token FROM users WHERE id = ?", (session["user_id"],)).fetchone()
        conn.close()
        current_token = session.get("session_token")
        if user and user["session_token"] and current_token and user["session_token"] != current_token:
            session.clear()
            flash("Your account was logged in from another device. For security, this session was terminated.", "error")
            return redirect(url_for("login"))



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
        country_code = request.form.get("country_code", "+91").strip()
        phone_input = request.form.get("phone", "").strip()
        password = request.form.get("password", "")

        if not username or not email or not phone_input or not password:
            flash("Please fill in all fields.", "error")
            return render_template("register.html")

        # Validate country code
        if not re.match(r"^\+\d{1,4}$", country_code):
            flash("Please select a valid country code.", "error")
            return render_template("register.html")

        # Strict validation: Mobile number must ONLY contain digits (10 to 14 digits)
        if not re.match(r"^\d{10,14}$", phone_input):
            flash("Mobile number must contain digits only (10 to 14 digits), without special characters, spaces, or letters.", "error")
            return render_template("register.html")

        full_phone = f"{country_code}{phone_input}"

        if len(password) < 6:
            flash("Password must be at least 6 characters long.", "error")
            return render_template("register.html")

        if not re.search(r"[a-z]", password):
            flash("Password must include at least one lowercase letter (a-z).", "error")
            return render_template("register.html")

        if not re.search(r"[A-Z]", password):
            flash("Password must include at least one uppercase letter (A-Z).", "error")
            return render_template("register.html")

        if not re.search(r"[0-9]", password):
            flash("Password must include at least one number (0-9).", "error")
            return render_template("register.html")

        if not re.search(r"[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>\/?`~]", password):
            flash("Password must include at least one special character (!@#$%^&*...).", "error")
            return render_template("register.html")

        # Check if username or email already exists in DB
        conn = get_db_connection()
        existing = conn.execute(
            "SELECT id FROM users WHERE LOWER(username) = LOWER(?) OR LOWER(email) = LOWER(?)",
            (username, email),
        ).fetchone()
        conn.close()
        if existing:
            flash("Username or email already exists. Please choose another.", "error")
            return render_template("register.html")

        hashed_password = generate_password_hash(password)
        otp = f"{secrets.randbelow(900000) + 100000}"

        session["pending_reg"] = {
            "username": username,
            "email": email,
            "phone": full_phone,
            "password": hashed_password,
            "otp": otp,
            "created_at": time.time(),
        }

        # Send Email OTP
        sent = send_verification_otp(email, otp)
        if sent:
            flash(f"A 6-digit verification code has been sent to {email}. Please check your inbox.", "info")
        else:
            flash(f"Unable to send email to {email}. Please ensure SMTP mail settings are configured.", "error")
        return redirect(url_for("verify_otp"))

    return render_template("register.html")


@app.route("/verify-otp", methods=["GET", "POST"])
def verify_otp():
    pending = session.get("pending_reg")
    if not pending:
        flash("No pending registration found. Please register first.", "error")
        return redirect(url_for("register"))

    if request.method == "POST":
        user_otp = request.form.get("otp", "").strip()
        now = time.time()
        if now - pending.get("created_at", 0) > 600:
            flash("Verification OTP has expired. Please request a new code.", "error")
            return render_template("verify_otp.html", email=pending["email"])

        if user_otp != pending.get("otp"):
            flash("Invalid OTP code. Please check your email and try again.", "error")
            return render_template("verify_otp.html", email=pending["email"])

        # OTP verified -> insert user into database
        conn = get_db_connection()
        try:
            cur = conn.execute(
                "INSERT INTO users (username, email, phone, password) VALUES (?, ?, ?, ?)",
                (pending["username"], pending["email"], pending["phone"], pending["password"]),
            )
            conn.commit()
            new_user_id = cur.lastrowid
            conn.close()

            portfolio_db.create_default_portfolio(new_user_id, pending["username"])

            # Persist registered user and portfolio to Vercel Blob cloud storage
            try:
                import cloud_sync
                cloud_sync.upload_to_cloud(["tradeverse.db", "tradeverse.json"])
            except Exception as e:
                app.logger.warning(f"Cloud sync upload error: {e}")

            session.pop("pending_reg", None)
            flash("Email verified successfully! Your account has been created. Please log in.", "success")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            conn.close()
            session.pop("pending_reg", None)
            flash("Username or email already exists.", "error")
            return render_template("register.html")

    return render_template("verify_otp.html", email=pending["email"])


@app.route("/resend-otp")
def resend_otp():
    pending = session.get("pending_reg")
    if not pending:
        flash("No registration in progress.", "error")
        return redirect(url_for("register"))

    new_otp = f"{secrets.randbelow(900000) + 100000}"
    pending["otp"] = new_otp
    pending["created_at"] = time.time()
    session["pending_reg"] = pending
    sent = send_verification_otp(pending["email"], new_otp)
    if sent:
        flash(f"A new verification code has been sent to {pending['email']}. Please check your inbox.", "info")
    else:
        flash("Unable to send email. Please ensure SMTP mail settings are configured.", "error")
    return redirect(url_for("verify_otp"))


@app.route("/api/captcha")
def api_captcha():
    code = generate_captcha_text()
    session["login_captcha"] = code
    return jsonify({"captcha": code})


@app.route("/login", methods=["GET", "POST"])
def login():
    ip = request.remote_addr or "127.0.0.1"

    if request.method == "POST":
        if is_ip_rate_limited(ip):
            flash("Too many failed attempts. Please wait 1 minute before trying again to prevent server overload.", "error")
            return render_template("login.html", captcha_text=session.get("login_captcha", generate_captcha_text()))

        # Verify Captcha
        user_captcha = request.form.get("captcha", "").strip().upper()
        expected_captcha = session.get("login_captcha", "").upper()
        if not user_captcha or user_captcha != expected_captcha:
            record_login_failure(ip)
            new_code = generate_captcha_text()
            session["login_captcha"] = new_code
            flash("Incorrect captcha security code. Please try again.", "error")
            return render_template("login.html", captcha_text=new_code)

        # Refresh captcha for subsequent attempts
        session["login_captcha"] = generate_captcha_text()

        identifier = (request.form.get("identifier") or request.form.get("username", "")).strip()
        password = request.form.get("password", "")

        conn = get_db_connection()
        phone_digits = re.sub(r"\D", "", identifier)
        user = conn.execute(
            """
            SELECT * FROM users
            WHERE LOWER(username) = LOWER(?)
               OR phone = ?
               OR (LENGTH(?) >= 10 AND phone LIKE ?)
            """,
            (identifier, identifier, phone_digits, f"%{phone_digits}"),
        ).fetchone()

        # If user is not found locally, try restoring from Vercel Blob in case account was created on another instance
        if not user:
            try:
                import cloud_sync
                if cloud_sync.is_cloud_enabled():
                    if cloud_sync.download_from_cloud(force=True):
                        conn.close()
                        conn = get_db_connection()
                        user = conn.execute(
                            """
                            SELECT * FROM users
                            WHERE LOWER(username) = LOWER(?)
                               OR phone = ?
                               OR (LENGTH(?) >= 10 AND phone LIKE ?)
                            """,
                            (identifier, identifier, phone_digits, f"%{phone_digits}"),
                        ).fetchone()
            except Exception as e:
                app.logger.warning(f"Cloud sync check error during login: {e}")

        if user and check_password_hash(user["password"], password):
            clear_login_failure(ip)
            # Enforce single active device session
            new_session_token = secrets.token_hex(24)
            conn.execute("UPDATE users SET session_token = ? WHERE id = ?", (new_session_token, user["id"]))
            conn.commit()
            conn.close()

            session.clear()
            session["username"] = user["username"]
            session["user_id"] = user["id"]
            session["session_token"] = new_session_token
            flash("Welcome back, " + user["username"] + "!", "success")
            return redirect(url_for("dashboard"))
        else:
            conn.close()
            record_login_failure(ip)
            flash("Invalid username/mobile number or password.", "error")
            return render_template("login.html", captcha_text=session.get("login_captcha", generate_captcha_text()))

    captcha_code = generate_captcha_text()
    session["login_captcha"] = captcha_code
    return render_template("login.html", captcha_text=captcha_code)


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
        quote = {"price": None, "change": None, "change_percent": None}

    checksum = price_service.compute_checksum(quote)
    if request.headers.get("If-None-Match") == checksum:
        return ("", 304)

    response = jsonify(quote)
    response.headers["ETag"] = checksum
    response.headers["X-Checksum"] = checksum
    return response


@app.route("/api/indices")
def api_indices():
    if "user_id" not in session:
        return jsonify({"error": "not logged in"}), 401
    data = price_service.get_indices()
    checksum = price_service.compute_checksum(data)

    if request.headers.get("If-None-Match") == checksum:
        return ("", 304)

    response = jsonify(data)
    response.headers["ETag"] = checksum
    response.headers["X-Checksum"] = checksum
    return response


@app.route("/api/hot-assets")
def api_hot_assets():
    if "user_id" not in session:
        return jsonify({"error": "not logged in"}), 401
    data = price_service.get_hot_assets()
    checksum = price_service.compute_checksum(data)

    if request.headers.get("If-None-Match") == checksum:
        return ("", 304)

    response = jsonify({"data": data, "checksum": checksum})
    response.headers["ETag"] = checksum
    response.headers["X-Checksum"] = checksum
    return response


@app.route("/admin/users")
def admin_users():
    if session.get("username") != "admin":
        flash("Access denied. Admin privileges required.", "error")
        return redirect(url_for("dashboard"))

    try:
        import cloud_sync
        cloud_sync.download_from_cloud()
    except Exception:
        pass

    conn = get_db_connection()
    users = conn.execute(
        "SELECT id, username, email, phone, session_token FROM users ORDER BY id ASC"
    ).fetchall()
    conn.close()

    user_list = []
    for u in users:
        doc = portfolio_db.get_portfolio_doc(u["id"])
        wallets = doc.get("wallets", {}) if doc else {}
        user_list.append({
            "id": u["id"],
            "username": u["username"],
            "email": u["email"],
            "phone": u["phone"],
            "has_active_session": bool(u["session_token"]),
            "wallets": wallets,
        })
    return render_template("admin_users.html", users=user_list)


@app.route("/api/admin/users")
def api_admin_users():
    if session.get("username") != "admin":
        return jsonify({"error": "unauthorized", "message": "Admin privileges required"}), 403

    try:
        import cloud_sync
        cloud_sync.download_from_cloud()
    except Exception:
        pass

    conn = get_db_connection()
    users = conn.execute(
        "SELECT id, username, email, phone, session_token FROM users ORDER BY id ASC"
    ).fetchall()
    conn.close()
    return jsonify([
        {
            "id": u["id"],
            "username": u["username"],
            "email": u["email"],
            "phone": u["phone"],
            "has_active_session": bool(u["session_token"]),
        }
        for u in users
    ])


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
