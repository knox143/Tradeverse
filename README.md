# TradeVerse - Paper Trading & Portfolio Platform

TradeVerse is a complete Flask paper-trading application with real-time portfolio management, buy & sell execution tracking, TradingView advanced charts, custom API support, and full Vercel serverless deployment compatibility.

---

## Key Features

1. **Portfolio & Buy/Sell Transaction History (/portfolio)**
   - Track active holdings across 3 markets:
     - **ISE**: Indian Stock Exchange (Currency: ₹ INR)
     - **USE**: US Stock Exchange (Currency: $ USD)
     - **CCME**: Crypto Currency Market Exchange (Currency: $ USD)
   - **Audit Record of Every Trade**:
     - Shows exact quantities bought (+Qty) and sold (-Qty).
     - Execution price and total transaction value.
     - Realized Profit/Loss calculated automatically on every SELL.
     - Filter by Transaction Type (All, Buy, Sell) and Market (ISE, USE, CCME).
   - Instant paper trade execution modal to buy and sell stocks/crypto with real-time wallet balance validation.

2. **TradingView Advanced Charts**
   - Real-time interactive TradingView candlestick and technical indicator charts on all asset pages (/asset/stock/<SYMBOL> and /asset/crypto/<SYMBOL>).
   - Automatically maps tickers to their real market exchange:
     - Indian Stocks: NSE:RELIANCE, NSE:TCS, NSE:INFY, BSE:SENSEX, etc.
     - US Stocks: NASDAQ:AAPL, NASDAQ:MSFT, NASDAQ:NVDA, NYSE:TSLA, etc.
     - Cryptocurrencies: COINBASE:BTCUSD, COINBASE:ETHUSD, BINANCE:SOLUSDT, etc.

3. **Free Live Market API + Custom API Drop-In Ready**
   - **Out-of-the-Box**: Works 100% free with real live market prices (Indian Stocks from NSE/BSE, US Stocks from NYSE/NASDAQ, Crypto from Binance/CoinGecko) without requiring any paid keys!
   - **How to drop in your own custom API**:
     - **Method 1 (Zero-Code / Environment Variables)**:
       In `.env` or Vercel Environment Variables:
       ```bash
       CUSTOM_PRICE_API_URL=https://your-api.com/api/v1/quote
       CUSTOM_PRICE_API_KEY=your_api_key_here
       CUSTOM_CHART_API_URL=https://your-api.com/api/v1/chart
       ```
     - **Method 2 (Direct Python Code Hook)**:
       Open `price_service.py` and drop your API code directly into `_user_direct_api_quote(symbol)` and `_user_direct_api_chart(symbol, range_key)`.
   - When set, TradeVerse queries your custom API first. If not configured or if a symbol fails, it falls back seamlessly to the free live market endpoints and deterministic fallbacks so trading never breaks.

4. **Vercel Serverless Ready (Zero Errors)**
   - Configured with pi/index.py and ercel.json (version 2 with rewrites).
   - Storage handling in storage_paths.py: on Vercel's read-only lambda filesystem, runtime SQLite and TinyDB data are automatically copied to /tmp/tradeverse for safe execution.
   - Static assets served directly from public/static/ via Vercel CDN.

---

## Running Locally

1. **Setup Environment**:
   ```bash
   python -m venv .venv
   # Windows:
   .venv\Scripts\activate
   # macOS/Linux:
   source .venv/bin/activate

   pip install -r requirements.txt
   ```

2. **Run Application**:
   ```bash
   python app.py
   ```
   Open http://127.0.0.1:5000 in your browser.

3. **Default Demo Credentials**:
   - **Username**: admin
   - **Password**: admin@123

---

## Deploying to Vercel

### Step 1: Push or Upload to GitHub / Vercel
Ensure your project contains:
- `api/index.py` (Vercel WSGI entrypoint)
- `vercel.json` (routing configuration)
- `app.py`
- `portfolio_db.py`
- `price_service.py`
- `storage_paths.py`
- `requirements.txt`
- `templates/`
- `public/static/`
- `tradeverse.db` (seed database)
- `tinydb_storage/tradeverse.json` (seed portfolios & transactions)

### Step 2: Configure Environment Variables in Vercel
In your Vercel Project Settings -> **Environment Variables**:
- FLASK_SECRET_KEY: Any long random secret string
- TWELVEDATA_API_KEY: *(Optional)* TwelveData API key for US stocks
- COINGECKO_API_KEY: *(Optional)* CoinGecko API key
- CUSTOM_PRICE_API_URL: *(Optional)* Your custom stock/crypto API URL
- CUSTOM_PRICE_API_KEY: *(Optional)* Your custom API key

### Step 3: Deploy
Deploy directly with Vercel CLI or via GitHub:
```bash
vercel --prod
```

---

## API Reference

- GET /api/portfolio/summary: Returns full user portfolio summary, total net worth, active holdings count, and recent transactions.
- GET /api/portfolio/transactions: Returns chronological audit records of all buys and sells with optional query params ?market=ISE|USE|CCME and ?type=BUY|SELL.
- GET /api/portfolio/<MARKET>: Returns current holdings and wallet purse for ISE, USE, or CCME.
- POST /api/portfolio/buy: Execute a paper buy order (symbol, market, quantity, price).
- POST /api/portfolio/sell: Execute a paper sell order (lot_id, quantity, price).
