// TradeVerse asset detail page logic with TradingView Real-Time Chart

const ASSET_SYMBOL = window.TRADEVERSE_ASSET_SYMBOL;
const ASSET_TYPE = window.TRADEVERSE_ASSET_TYPE;

let currentPrice = null;
const isIndian = ASSET_SYMBOL.endsWith(".NS") || ASSET_SYMBOL.endsWith(".BO");
const CURRENCY_SYMBOL = isIndian ? "₹" : "$";

function formatMoney(value) {
    if (value === null || value === undefined || isNaN(value)) return "--";
    return CURRENCY_SYMBOL + Number(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 4 });
}

function setStatValue(elId, text, changeValue) {
    const el = document.getElementById(elId);
    if (!el) return;
    el.textContent = text;
    if (changeValue !== undefined) {
        el.classList.remove("up", "down");
        el.classList.add(changeValue >= 0 ? "up" : "down");
    }
}

function getTradingViewSymbol(symbol, assetType) {
    const s = symbol.trim().toUpperCase();
    if (s.endsWith(".NS")) {
        return "NSE:" + s.replace(".NS", "");
    }
    if (s.endsWith(".BO")) {
        return "BSE:" + s.replace(".BO", "");
    }
    if (assetType === "crypto" || s.endsWith("-USD")) {
        const coin = s.replace("-USD", "");
        if (coin === "BTC") return "COINBASE:BTCUSD";
        if (coin === "ETH") return "COINBASE:ETHUSD";
        if (coin === "SOL") return "COINBASE:SOLUSD";
        return "BINANCE:" + coin + "USDT";
    }
    const nyseList = ["IBM", "DIS", "BA", "GE", "JPM", "V", "WMT", "KO", "PFE", "NKE"];
    if (nyseList.includes(s)) {
        return "NYSE:" + s;
    }
    return "NASDAQ:" + s;
}

let customChartInstance = null;
let customCandleSeries = null;
let currentCustomRange = "24H";
let activeMode = "tv-widget"; // 'tv-widget' | 'custom-api'

// ---------------------------------------------------------------------------
// 1. TradingView Advanced Real-Time Chart Widget
// ---------------------------------------------------------------------------
function initTradingViewWidget() {
    const tvSymbol = getTradingViewSymbol(ASSET_SYMBOL, ASSET_TYPE);
    if (typeof TradingView !== "undefined") {
        new TradingView.widget({
            "autosize": true,
            "symbol": tvSymbol,
            "interval": "D",
            "timezone": "Etc/UTC",
            "theme": "light",
            "style": "1",
            "locale": "en",
            "toolbar_bg": "#f4f6f9",
            "enable_publishing": false,
            "allow_symbol_change": true,
            "container_id": "tradingview_chart",
            "hide_side_toolbar": false
        });
    }
}

// ---------------------------------------------------------------------------
// 2. Custom API Chart (Powered by Official TradingView Lightweight Charts)
// ---------------------------------------------------------------------------
function initCustomTradingViewChart(rangeKey) {
    rangeKey = rangeKey || currentCustomRange;
    const container = document.getElementById("custom_tradingview_container");
    if (!container) return;

    if (!customChartInstance && typeof LightweightCharts !== "undefined") {
        customChartInstance = LightweightCharts.createChart(container, {
            autoSize: true,
            layout: {
                background: { color: "#ffffff" },
                textColor: "#334155",
            },
            grid: {
                vertLines: { color: "#f1f5f9" },
                horzLines: { color: "#f1f5f9" },
            },
            crosshair: {
                mode: LightweightCharts.CrosshairMode.Normal,
            },
            rightPriceScale: {
                borderColor: "#cbd5e1",
            },
            timeScale: {
                borderColor: "#cbd5e1",
                timeVisible: true,
                secondsVisible: false,
            },
        });

        customCandleSeries = customChartInstance.addCandlestickSeries({
            upColor: "#089981",
            downColor: "#f23645",
            borderUpColor: "#089981",
            borderDownColor: "#f23645",
            wickUpColor: "#089981",
            wickDownColor: "#f23645",
        });

        window.addEventListener("resize", function () {
            if (customChartInstance && container.clientWidth) {
                customChartInstance.applyOptions({
                    width: container.clientWidth,
                    height: container.clientHeight,
                });
            }
        });
    }

    loadCustomChartData(rangeKey);
}

function loadCustomChartData(rangeKey) {
    const customApiUrl = window.TRADEVERSE_CUSTOM_CHART_API;
    const fetchUrl = customApiUrl
        ? customApiUrl + (customApiUrl.includes("?") ? "&" : "?") + "symbol=" + encodeURIComponent(ASSET_SYMBOL) + "&range=" + rangeKey
        : "/api/asset/" + ASSET_TYPE + "/" + encodeURIComponent(ASSET_SYMBOL) + "/chart?range=" + rangeKey;

    fetch(fetchUrl)
        .then(res => res.json())
        .then(data => {
            if (data.error) return;

            currentPrice = Number(data.current_price || (data.candles && data.candles.length ? data.candles[data.candles.length - 1].close : 0));
            if (data.current_price !== undefined) {
                setStatValue("statCurrent", formatMoney(data.current_price));
            }
            if (data.period_low !== undefined) {
                setStatValue("statLow", formatMoney(data.period_low));
            }
            if (data.period_high !== undefined) {
                setStatValue("statHigh", formatMoney(data.period_high));
            }
            if (data.change_percent !== undefined) {
                const pctSign = data.change_percent >= 0 ? "+" : "";
                setStatValue("statChangePercent", pctSign + Number(data.change_percent).toFixed(2) + "%", data.change_percent);
            }
            if (data.change_value !== undefined) {
                const valSign = data.change_value >= 0 ? "+" : "-";
                setStatValue("statChangeValue", valSign + formatMoney(Math.abs(data.change_value)), data.change_value);
            }

            if (customCandleSeries && data.candles && data.candles.length) {
                const formatted = data.candles.map(c => ({
                    time: typeof c.time === "number" ? c.time : Math.floor(new Date(c.time).getTime() / 1000),
                    open: Number(c.open !== undefined ? c.open : (c.close !== undefined ? c.close : c.price)),
                    high: Number(c.high !== undefined ? c.high : (c.close !== undefined ? c.close : c.price)),
                    low: Number(c.low !== undefined ? c.low : (c.close !== undefined ? c.close : c.price)),
                    close: Number(c.close !== undefined ? c.close : c.price),
                })).sort((a, b) => a.time - b.time);

                customCandleSeries.setData(formatted);
                if (customChartInstance) {
                    customChartInstance.timeScale().fitContent();
                }
            }
        })
        .catch(err => {
            console.error("Custom chart fetch error:", err);
        });
}

function switchChartMode(mode) {
    activeMode = mode;
    const tvWrap = document.getElementById("tradingview_widget_wrap");
    const customWrap = document.getElementById("custom_api_chart_wrap");
    const tfBar = document.getElementById("customTimeframes");
    const btnTv = document.getElementById("modeTradingViewWidget");
    const btnCustom = document.getElementById("modeCustomApi");

    if (mode === "tv-widget") {
        if (tvWrap) tvWrap.style.display = "block";
        if (customWrap) customWrap.style.display = "none";
        if (tfBar) tfBar.style.display = "none";
        if (btnTv) btnTv.classList.add("active");
        if (btnCustom) btnCustom.classList.remove("active");
    } else {
        if (tvWrap) tvWrap.style.display = "none";
        if (customWrap) customWrap.style.display = "block";
        if (tfBar) tfBar.style.display = "flex";
        if (btnTv) btnTv.classList.remove("active");
        if (btnCustom) btnCustom.classList.add("active");

        initCustomTradingViewChart(currentCustomRange);
        if (customChartInstance) {
            setTimeout(() => {
                const container = document.getElementById("custom_tradingview_container");
                if (container && container.clientWidth) {
                    customChartInstance.applyOptions({
                        width: container.clientWidth,
                        height: container.clientHeight,
                    });
                    customChartInstance.timeScale().fitContent();
                }
            }, 50);
        }
    }
}

function loadStats() {
    fetch("/api/asset/" + ASSET_TYPE + "/" + encodeURIComponent(ASSET_SYMBOL) + "/chart?range=24H")
        .then(res => res.json())
        .then(data => {
            if (data.error) return;
            currentPrice = Number(data.current_price);
            setStatValue("statCurrent", formatMoney(data.current_price));
            setStatValue("statLow", formatMoney(data.period_low));
            setStatValue("statHigh", formatMoney(data.period_high));

            const pctSign = data.change_percent >= 0 ? "+" : "";
            setStatValue("statChangePercent", pctSign + Number(data.change_percent).toFixed(2) + "%", data.change_percent);

            const valSign = data.change_value >= 0 ? "+" : "-";
            setStatValue("statChangeValue", valSign + formatMoney(Math.abs(data.change_value)), data.change_value);
        })
        .catch(() => {});
}

function openBuyModal() {
    if (!Number.isFinite(currentPrice) || currentPrice <= 0) {
        alert("Current price is not loaded yet. Please wait a moment and try again.");
        return;
    }

    let market = "USE";
    if (isIndian) {
        market = "ISE";
    } else if (ASSET_TYPE === "crypto" || ASSET_SYMBOL.endsWith("-USD")) {
        market = "CCME";
    }

    const currencySymbol = market === "ISE" ? "₹" : "$";

    fetch("/api/portfolio/" + market)
        .then(res => res.json())
        .then(data => {
            if (data.error) {
                alert(data.error);
                return;
            }
            TradeModal.open({
                action: "buy",
                assetType: ASSET_TYPE,
                market: market,
                symbol: ASSET_SYMBOL,
                currentPrice: currentPrice,
                currencySymbol: currencySymbol,
                balance: Number(data.wallet || 0),
                onSuccess: function (result) {
                    alert("Buy completed successfully! Bought " + ASSET_SYMBOL + ".\nNew " + market + " wallet balance: " + currencySymbol + Number(result.wallet).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
                }
            });
        })
        .catch(() => {
            alert("Could not load your wallet balance. Please try again.");
        });
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

    initTradingViewWidget();
    loadStats();

    // Chart Mode Toggle Buttons
    const btnTv = document.getElementById("modeTradingViewWidget");
    const btnCustom = document.getElementById("modeCustomApi");
    if (btnTv) {
        btnTv.addEventListener("click", () => switchChartMode("tv-widget"));
    }
    if (btnCustom) {
        btnCustom.addEventListener("click", () => switchChartMode("custom-api"));
    }

    // Custom Timeframe Buttons
    document.querySelectorAll(".tf-btn").forEach(btn => {
        btn.addEventListener("click", function () {
            document.querySelectorAll(".tf-btn").forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            currentCustomRange = btn.dataset.range || "24H";
            loadCustomChartData(currentCustomRange);
        });
    });

    const buyBtn = document.getElementById("assetBuyBtn") || document.querySelector(".btn-buy");
    if (buyBtn) {
        buyBtn.addEventListener("click", openBuyModal);
    }
});
