// TradeVerse market page logic (Indian Stock Market / US Stock Exchange / Crypto)

const REFRESH_INTERVAL_MS = 10 * 60 * 1000; // 10 minutes, matches backend price cache
const MARKET = window.TRADEVERSE_MARKET;
const CURRENCY_SYMBOL = window.TRADEVERSE_CURRENCY_SYMBOL;
const COLUMN_COUNT = 9;

function formatMoney(value) {
    if (value === null || value === undefined || isNaN(value)) return "--";
    const num = Number(value);
    return CURRENCY_SYMBOL + num.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function formatQuantity(value) {
    if (value === null || value === undefined || isNaN(value)) return "--";
    const num = Number(value);
    // Crypto holdings can be fractional (e.g. 0.1 BTC) - show up to 4 decimals, but
    // don't pad whole-share stock quantities with trailing zeros.
    return Number.isInteger(num) ? String(num) : num.toLocaleString(undefined, { maximumFractionDigits: 4 });
}

function formatDate(isoDateStr) {
    if (!isoDateStr) return "--";
    const d = new Date(isoDateStr + "T00:00:00Z");
    if (isNaN(d.getTime())) return isoDateStr;
    return d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
}

function setLoadingRow(message) {
    document.getElementById("portfolioBody").innerHTML =
        '<tr><td colspan="' + COLUMN_COUNT + '" class="loading-row">' + message + "</td></tr>";
}

function renderHoldingRow(h) {
    const plUp = h.profit_loss >= 0;
    const plSign = plUp ? "+" : "";
    const plClass = plUp ? "up" : "down";

    return (
        "<tr>" +
            "<td>" + h.name + "</td>" +
            "<td>" + formatDate(h.bought_date) + "</td>" +
            "<td class=\"num\">" + formatMoney(h.bought_price) + "</td>" +
            "<td class=\"num\">" + formatMoney(h.price) + "</td>" +
            "<td class=\"num\">" + formatQuantity(h.quantity) + "</td>" +
            "<td class=\"num\">" + formatMoney(h.total_amount) + "</td>" +
            "<td class=\"num pl-cell " + plClass + "\">" + plSign + formatMoney(h.profit_loss) + "</td>" +
            "<td class=\"num pl-cell " + plClass + "\">" + plSign + h.profit_loss_percent.toFixed(2) + "%</td>" +
            "<td class=\"actions-cell\">" +
                "<button type=\"button\" class=\"btn-sell-now\" data-action=\"sell\" data-symbol=\"" + h.name + "\" data-lot-id=\"" + (h.lot_id || "") + "\" data-price=\"" + h.price + "\" data-quantity=\"" + h.quantity + "\">Sell Now</button>" +
                "<button type=\"button\" class=\"btn-sell-limit\" data-action=\"sell-limit\" data-symbol=\"" + h.name + "\">Sell Limit</button>" +
            "</td>" +
        "</tr>"
    );
}


function bindTradeButtons(data) {
    document.querySelectorAll("[data-action='sell']").forEach(function (button) {
        button.addEventListener("click", function () {
            const maxQuantity = Number(button.dataset.quantity);
            const price = Number(button.dataset.price);
            if (!button.dataset.lotId) {
                loadPortfolio();
                return;
            }
            TradeModal.open({
                action: "sell",
                market: MARKET,
                assetType: MARKET === "CCME" ? "crypto" : "stock",
                symbol: button.dataset.symbol,
                lotId: button.dataset.lotId,
                maxQuantity: maxQuantity,
                currentPrice: price,
                currencySymbol: CURRENCY_SYMBOL,
                onSuccess: function () {
                    loadPortfolio();
                    loadMarketTransactions();
                }
            });
        });
    });

    document.querySelectorAll("[data-action='sell-limit']").forEach(function (button) {
        button.addEventListener("click", function () {
            alert("Limit orders are not available yet. Use Sell Now for an immediate paper trade.");
        });
    });
}

function loadPortfolio() {
    setLoadingRow("Loading portfolio...");

    fetch("/api/portfolio/" + MARKET)
        .then((res) => res.json())
        .then((data) => {
            if (data.error) {
                setLoadingRow(data.error);
                return;
            }

            document.getElementById("walletAmount").textContent = formatMoney(data.wallet);

            if (!data.holdings || data.holdings.length === 0) {
                setLoadingRow("No holdings yet in this portfolio.");
                return;
            }

            document.getElementById("portfolioBody").innerHTML = data.holdings.map(renderHoldingRow).join("");
            bindTradeButtons(data);
        })
        .catch(() => {
            setLoadingRow("Could not load portfolio. Please try again.");
        });
}

function loadMarketTransactions() {
    const tbody = document.getElementById("marketTransactionsBody");
    if (!tbody) return;

    fetch("/api/portfolio/transactions?market=" + encodeURIComponent(MARKET))
        .then((res) => res.json())
        .then((data) => {
            if (data.error) {
                tbody.innerHTML = '<tr><td colspan="8" class="loading-row">' + data.error + '</td></tr>';
                return;
            }

            const txs = data.transactions || [];
            if (txs.length === 0) {
                tbody.innerHTML = '<tr><td colspan="8" class="loading-row">No buy or sell trades recorded yet in ' + MARKET + '.</td></tr>';
                return;
            }

            tbody.innerHTML = txs.map(function (t) {
                const isBuy = t.type === "BUY";
                const typeBadge = isBuy
                    ? '<span class="badge badge-buy">BUY</span>'
                    : '<span class="badge badge-sell">SELL</span>';
                const qtyStr = isBuy
                    ? '<span class="text-green font-bold">+' + formatQuantity(t.quantity) + '</span>'
                    : '<span class="text-red font-bold">-' + formatQuantity(t.quantity) + '</span>';

                let plHtml = "--";
                if (!isBuy && t.profit_loss !== null && t.profit_loss !== undefined) {
                    const plUp = t.profit_loss >= 0;
                    const plClass = plUp ? "up" : "down";
                    const plSign = plUp ? "+" : "";
                    plHtml = '<span class="pl-cell ' + plClass + '">' + plSign + formatMoney(t.profit_loss) + '</span>';
                }

                return (
                    "<tr>" +
                        "<td><span class=\"tx-date\">" + (t.date || t.timestamp || "--") + "</span></td>" +
                        "<td>" + typeBadge + "</td>" +
                        "<td><strong>" + t.symbol + "</strong></td>" +
                        "<td class=\"num\">" + qtyStr + "</td>" +
                        "<td class=\"num\">" + formatMoney(t.price) + "</td>" +
                        "<td class=\"num\">" + formatMoney(t.total_amount) + "</td>" +
                        "<td class=\"num\">" + plHtml + "</td>" +
                        "<td><span class=\"badge badge-status\">" + (t.status || "Executed") + "</span></td>" +
                    "</tr>"
                );
            }).join("");
        })
        .catch(function () {
            tbody.innerHTML = '<tr><td colspan="8" class="loading-row">Could not load trade records.</td></tr>';
        });
}

document.addEventListener("DOMContentLoaded", function () {
    // Hamburger dropdown toggle (links navigate normally, so we only need open/close)
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

    loadPortfolio();
    loadMarketTransactions();

    setInterval(function () {
        loadPortfolio();
        loadMarketTransactions();
    }, REFRESH_INTERVAL_MS);
});
