// TradeVerse dashboard (landing page) logic with Checksum verification & Touch Trading

const REFRESH_INTERVAL_MS = 60 * 1000; // 1 minute auto-refresh for real-time pricing
const SEARCH_DEBOUNCE_MS = 300;

let searchDebounceTimer = null;
let searchRequestSeq = 0; // guards against a slow older request overwriting a newer one
let currentBtcData = null;

// Local Checksum cache to mitigate latency and avoid redundant DOM re-renders
const checksumCache = {
    btc: null,
    indices: null,
    hotAssets: null,
};

window._cachedPortfolio = null;

function loadBtcHero() {
    const headers = {};
    if (checksumCache.btc) {
        headers["If-None-Match"] = checksumCache.btc;
    }

    fetch("/api/btc", { headers: headers })
        .then((res) => {
            if (res.status === 304) {
                return null; // Not modified, use cached data
            }
            const checksum = res.headers.get("X-Checksum") || res.headers.get("ETag");
            if (checksum) checksumCache.btc = checksum;
            return res.json();
        })
        .then((data) => {
            if (!data) return;
            currentBtcData = data;
            const priceEl = document.getElementById("btcPrice");
            const changeEl = document.getElementById("btcChange");
            applyQuoteToElements(data, priceEl, changeEl, true);
        })
        .catch(() => {
            const priceEl = document.getElementById("btcPrice");
            if (priceEl && !currentBtcData) priceEl.textContent = "Unavailable";
        });
}

function applyQuoteToElements(quote, priceEl, changeEl, isBtc) {
    if (!quote || quote.price === null || quote.price === undefined) {
        if (priceEl) priceEl.textContent = "Unavailable";
        if (changeEl) changeEl.textContent = "";
        return;
    }

    var prefix = "";
    if (isBtc || quote.symbol === "BTC-USD" || quote.name === "S&P 500") {
        prefix = "$";
    } else if (quote.name === "NIFTY 50" || quote.name === "SENSEX") {
        prefix = "₹";
    }

    if (priceEl) {
        priceEl.textContent = prefix + Number(quote.price).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }

    if (changeEl) {
        if (quote.change !== null && quote.change !== undefined) {
            const sign = quote.change >= 0 ? "+" : "";
            changeEl.textContent = sign + Number(quote.change).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + " (" + sign + Number(quote.change_percent).toFixed(2) + "%)";
            changeEl.className = "idx-change " + (quote.change >= 0 ? "up" : "down");
        } else {
            changeEl.textContent = "";
        }
    }
}

// Maps the /api/indices response (S&P 500 / NIFTY 50 / SENSEX) onto index boxes
function loadIndices() {
    const boxIdByName = {
        "S&P 500": "idx-sp500",
        "NIFTY 50": "idx-nifty50",
        "SENSEX": "idx-sensex",
    };

    const headers = {};
    if (checksumCache.indices) {
        headers["If-None-Match"] = checksumCache.indices;
    }

    fetch("/api/indices", { headers: headers })
        .then((res) => {
            if (res.status === 304) return null;
            const checksum = res.headers.get("X-Checksum") || res.headers.get("ETag");
            if (checksum) checksumCache.indices = checksum;
            return res.json();
        })
        .then((data) => {
            if (!data) return;
            const list = Array.isArray(data) ? data : (data.data || []);
            list.forEach(function (idx) {
                const boxId = boxIdByName[idx.name];
                const box = boxId ? document.getElementById(boxId) : null;
                if (!box) return;

                const priceEl = box.querySelector(".idx-price");
                const changeEl = box.querySelector(".idx-change");
                applyQuoteToElements(idx, priceEl, changeEl, false);
            });
        })
        .catch(() => {});
}

// ---------------------------------------------------------------------------
// Touch Trading: Hot Assets on Dashboard
// ---------------------------------------------------------------------------

function loadHotAssets() {
    const grid = document.getElementById("touchAssetsGrid");
    if (!grid) return;

    const headers = {};
    if (checksumCache.hotAssets) {
        headers["If-None-Match"] = checksumCache.hotAssets;
    }

    fetch("/api/hot-assets", { headers: headers })
        .then((res) => {
            if (res.status === 304) return null;
            const checksum = res.headers.get("X-Checksum") || res.headers.get("ETag");
            if (checksum) checksumCache.hotAssets = checksum;
            return res.json();
        })
        .then((resp) => {
            if (!resp) return;
            const items = resp.data || (Array.isArray(resp) ? resp : []);
            if (!items.length) {
                grid.innerHTML = '<div class="tts-empty">No hot assets available currently.</div>';
                return;
            }

            grid.innerHTML = items.map((asset) => {
                const sym = asset.currency_symbol || (asset.market === "ISE" ? "₹" : "$");
                const priceFormatted = asset.price !== null && asset.price !== undefined
                    ? sym + Number(asset.price).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
                    : "Unavailable";
                const isUp = (asset.change || 0) >= 0;
                const sign = isUp ? "+" : "";
                const changeFormatted = asset.change !== null && asset.change !== undefined
                    ? `${sign}${Number(asset.change).toFixed(2)} (${sign}${Number(asset.change_percent).toFixed(2)}%)`
                    : "--";

                return `
                    <div class="touch-card" data-symbol="${asset.symbol}">
                        <div class="tc-top">
                            <div>
                                <div class="tc-symbol">${asset.symbol}</div>
                                <div class="tc-name">${asset.name}</div>
                            </div>
                            <span class="badge badge-market badge-${(asset.market || 'USE').toLowerCase()}">${asset.market}</span>
                        </div>
                        <div class="tc-mid">
                            <div class="tc-price">${priceFormatted}</div>
                            <div class="tc-change ${isUp ? 'up' : 'down'}">${changeFormatted}</div>
                        </div>
                        <div class="tc-actions">
                            <button type="button" class="btn-touch-action btn-touch-buy"
                                onclick="handleDashboardTrade('buy', '${asset.symbol}', '${asset.type}', '${asset.market}', '${sym}', ${asset.price || 0})">
                                Buy
                            </button>
                            <button type="button" class="btn-touch-action btn-touch-sell"
                                onclick="handleDashboardTrade('sell', '${asset.symbol}', '${asset.type}', '${asset.market}', '${sym}', ${asset.price || 0})">
                                Sell
                            </button>
                        </div>
                    </div>
                `;
            }).join("");
        })
        .catch(() => {});
}

function handleDashboardTrade(action, symbol, assetType, market, currencySymbol, price) {
    if (!window.TradeModal) {
        alert("Trading interface is loading. Please try again in a moment.");
        return;
    }

    const portfolio = window._cachedPortfolio || {};
    const wallets = portfolio.wallet || {};
    const holdings = portfolio.holdings || [];

    if (action === "buy") {
        const balance = wallets[market] !== undefined ? wallets[market] : 10000;
        window.TradeModal.open({
            action: "buy",
            symbol: symbol,
            assetType: assetType,
            market: market,
            currencySymbol: currencySymbol,
            currentPrice: Number(price),
            balance: balance,
            onSuccess: function () {
                loadDashboardPortfolioPreview();
            }
        });
    } else {
        // Find if user holds this symbol
        const holding = holdings.find((h) => h.symbol === symbol || (h.symbol && h.symbol.toUpperCase() === symbol.toUpperCase()));
        if (!holding || holding.quantity <= 0) {
            alert(`You do not own any units of ${symbol} in your portfolio yet. Use "Buy" to purchase units first!`);
            return;
        }

        window.TradeModal.open({
            action: "sell",
            symbol: symbol,
            assetType: assetType,
            market: market,
            currencySymbol: currencySymbol,
            lotId: holding.lot_id,
            currentPrice: Number(price),
            maxQuantity: holding.quantity,
            onSuccess: function () {
                loadDashboardPortfolioPreview();
            }
        });
    }
}

// ---------------------------------------------------------------------------
// Live search
// ---------------------------------------------------------------------------

function renderSearchResults(results, query) {
    const dropdown = document.getElementById("searchResultsDropdown");

    if (!results || results.length === 0) {
        dropdown.innerHTML = '<div class="search-dropdown-empty">No matches for "' + query + '"</div>';
        dropdown.classList.remove("hidden");
        return;
    }

    dropdown.innerHTML = results.map(function (r) {
        const sub = r.type === "stock" ? (r.exchange || "Stock") : "Cryptocurrency";
        return (
            '<div class="search-dropdown-item" data-symbol="' + r.symbol + '" data-type="' + r.type + '" data-name="' + r.name.replace(/"/g, "&quot;") + '">' +
                '<div>' +
                    '<div class="sdi-name">' + r.symbol + ' &middot; ' + r.name + '</div>' +
                    '<div class="sdi-sub">' + sub + '</div>' +
                '</div>' +
                '<span class="sdi-type-badge ' + r.type + '">' + r.type + '</span>' +
            '</div>'
        );
    }).join("");

    dropdown.classList.remove("hidden");

    dropdown.querySelectorAll(".search-dropdown-item").forEach(function (item) {
        item.addEventListener("click", function () {
            const symbol = item.getAttribute("data-symbol");
            const type = item.getAttribute("data-type");
            const name = item.getAttribute("data-name");
            window.location.href = "/asset/" + type + "/" + encodeURIComponent(symbol) + "?name=" + encodeURIComponent(name);
        });
    });
}

function runSearch(query) {
    const dropdown = document.getElementById("searchResultsDropdown");

    if (!query) {
        dropdown.classList.add("hidden");
        dropdown.innerHTML = "";
        return;
    }

    dropdown.innerHTML = '<div class="search-dropdown-loading">Searching...</div>';
    dropdown.classList.remove("hidden");

    const seq = ++searchRequestSeq;
    fetch("/api/search?q=" + encodeURIComponent(query))
        .then(function (res) { return res.json(); })
        .then(function (data) {
            if (seq !== searchRequestSeq) return;
            renderSearchResults(data, query);
        })
        .catch(function () {
            if (seq !== searchRequestSeq) return;
            dropdown.innerHTML = '<div class="search-dropdown-empty">Search unavailable right now. Please try again.</div>';
        });
}

function loadDashboardPortfolioPreview() {
    fetch("/api/portfolio/summary")
        .then(function (res) { return res.json(); })
        .then(function (data) {
            if (data.error) return;
            window._cachedPortfolio = data;
            const stats = data.stats || {};
            const wallets = data.wallet || {};

            const holdingsEl = document.getElementById("dashHoldingsCount");
            const tradesEl = document.getElementById("dashTradesCount");
            const iseEl = document.getElementById("dashWalletISE");
            const useEl = document.getElementById("dashWalletUSE");
            const tbody = document.getElementById("dashRecentTradesBody");

            if (holdingsEl) holdingsEl.textContent = stats.holdings_count || (data.holdings ? data.holdings.length : 0);
            if (tradesEl) tradesEl.textContent = stats.total_trades || 0;
            if (iseEl) iseEl.textContent = "₹" + Number(wallets.ISE || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
            if (useEl) useEl.textContent = "$" + Number(wallets.USE || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });

            if (!tbody) return;
            const recent = data.recent_transactions || (data.transactions ? data.transactions.slice(0, 5) : []);
            if (recent.length === 0) {
                tbody.innerHTML = '<tr><td colspan="8" class="loading-row">No trades recorded yet. Start buying stocks to build your history!</td></tr>';
                return;
            }

            tbody.innerHTML = recent.map(function (t) {
                const isBuy = t.type === "BUY";
                const typeBadge = isBuy
                    ? '<span class="badge badge-buy">BUY</span>'
                    : '<span class="badge badge-sell">SELL</span>';
                const sym = t.currency === "INR" || t.market === "ISE" ? "₹" : "$";
                const qtyFormatted = isBuy
                    ? '<span class="text-green font-bold">+' + t.quantity + '</span>'
                    : '<span class="text-red font-bold">-' + t.quantity + '</span>';

                return "<tr>" +
                    '<td><span class="tx-date">' + (t.date || t.timestamp || "--") + "</span></td>" +
                    "<td>" + typeBadge + "</td>" +
                    "<td><strong>" + t.symbol + "</strong></td>" +
                    '<td><span class="badge badge-market badge-' + (t.market || 'USE').toLowerCase() + '">' + t.market + "</span></td>" +
                    '<td class="num">' + qtyFormatted + "</td>" +
                    '<td class="num">' + sym + Number(t.price).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + "</td>" +
                    '<td class="num">' + sym + Number(t.total_amount).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + "</td>" +
                    '<td><span class="badge badge-status">' + (t.status || 'Completed') + "</span></td>" +
                "</tr>";
            }).join("");
        })
        .catch(function () {});
}

document.addEventListener("DOMContentLoaded", function () {
    // Topbar Hamburger Dropdown
    const menuBtn = document.getElementById("menuBtn");
    const dropdownMenu = document.getElementById("dropdownMenu");
    if (menuBtn && dropdownMenu) {
        menuBtn.addEventListener("click", function (e) {
            e.stopPropagation();
            dropdownMenu.classList.toggle("hidden");
        });
        document.addEventListener("click", function (e) {
            if (!dropdownMenu.contains(e.target) && e.target !== menuBtn) {
                dropdownMenu.classList.add("hidden");
            }
        });
    }

    // Bitcoin Hero Touch Trading buttons
    const btcBuyBtn = document.getElementById("btcTouchBuy");
    const btcSellBtn = document.getElementById("btcTouchSell");
    if (btcBuyBtn) {
        btcBuyBtn.addEventListener("click", function () {
            const price = currentBtcData && currentBtcData.price ? currentBtcData.price : 95000;
            handleDashboardTrade("buy", "BTC-USD", "crypto", "CCME", "$", price);
        });
    }
    if (btcSellBtn) {
        btcSellBtn.addEventListener("click", function () {
            const price = currentBtcData && currentBtcData.price ? currentBtcData.price : 95000;
            handleDashboardTrade("sell", "BTC-USD", "crypto", "CCME", "$", price);
        });
    }

    // Live search wiring
    const searchInput = document.getElementById("searchInput");
    const searchBtn = document.getElementById("searchBtn");
    const searchDropdown = document.getElementById("searchResultsDropdown");

    searchInput.addEventListener("input", function () {
        const query = searchInput.value.trim();
        clearTimeout(searchDebounceTimer);
        searchDebounceTimer = setTimeout(function () {
            runSearch(query);
        }, SEARCH_DEBOUNCE_MS);
    });

    searchInput.addEventListener("focus", function () {
        if (searchInput.value.trim() && searchDropdown.innerHTML.trim()) {
            searchDropdown.classList.remove("hidden");
        }
    });

    searchInput.addEventListener("keydown", function (e) {
        if (e.key === "Escape") {
            searchDropdown.classList.add("hidden");
        } else if (e.key === "Enter") {
            clearTimeout(searchDebounceTimer);
            runSearch(searchInput.value.trim());
        }
    });

    searchBtn.addEventListener("click", function () {
        clearTimeout(searchDebounceTimer);
        runSearch(searchInput.value.trim());
    });

    document.addEventListener("click", function (e) {
        if (!searchDropdown.contains(e.target) && e.target !== searchInput && e.target !== searchBtn) {
            searchDropdown.classList.add("hidden");
        }
    });

    // Initial load
    loadBtcHero();
    loadIndices();
    loadHotAssets();
    loadDashboardPortfolioPreview();

    // Auto-refresh every 1 minute for live prices
    setInterval(function () {
        loadBtcHero();
        loadIndices();
        loadHotAssets();
        loadDashboardPortfolioPreview();
    }, REFRESH_INTERVAL_MS);
});
