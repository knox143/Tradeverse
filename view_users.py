#!/usr/bin/env python3
"""
TradeVerse Database Inspector CLI
Usage:
    python view_users.py
    python view_users.py --json
"""
import sys
import json
import sqlite3
import os

try:
    import portfolio_db
except ImportError:
    portfolio_db = None

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tradeverse.db")


def main():
    if not os.path.exists(DB_PATH):
        print(f"Error: Database file '{DB_PATH}' not found.")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    try:
        cur.execute("SELECT id, username, email, phone, session_token FROM users ORDER BY id ASC")
        rows = cur.fetchall()
    except Exception as e:
        print(f"Database error: {e}")
        conn.close()
        sys.exit(1)

    conn.close()

    users_data = []
    for r in rows:
        wallets = {"ISE": 0, "USE": 0, "CCME": 0}
        holdings_count = 0
        if portfolio_db:
            doc = portfolio_db.get_portfolio_doc(r["id"])
            if doc:
                wallets = doc.get("wallets", wallets)
                for m in portfolio_db.MARKETS:
                    holdings_count += len(doc.get(f"{m}_portfolio", []))

        users_data.append({
            "id": r["id"],
            "username": r["username"],
            "email": r["email"],
            "phone": r["phone"],
            "has_active_session": bool(r["session_token"]),
            "holdings_count": holdings_count,
            "wallets": wallets,
        })

    if "--json" in sys.argv:
        print(json.dumps(users_data, indent=2))
        return

    print("=" * 86)
    print("                    TRADEVERSE REGISTERED USERS DIRECTORY")
    print("=" * 86)
    print(f"{'ID':<4} | {'LOGIN ID (USERNAME)':<20} | {'EMAIL ADDRESS':<26} | {'PHONE NUMBER':<16} | {'SESSION'}")
    print("-" * 86)

    for u in users_data:
        session_status = "Active" if u["has_active_session"] else "Idle"
        print(f"{u['id']:<4} | {u['username']:<20} | {u['email']:<26} | {u['phone']:<16} | {session_status}")

    print("-" * 86)
    print(f"Total Users Registered: {len(users_data)}")
    print("=" * 86)
    print("\nHow to see users in your browser:")
    print("  1. Start the server (python app.py)")
    print("  2. Open: http://127.0.0.1:5000/admin/users")
    print("  3. Raw JSON API: http://127.0.0.1:5000/api/admin/users\n")


if __name__ == "__main__":
    main()
