// TradeVerse unified portfolio and transaction history logic

const REFRESH_INTERVAL_MS = 10 * 60 * 1000;

let portfolioState = {
    summary: null,
    holdings: [],
    transactions: [],
    holdingsFilter: 'ALL',
    txTypeFilter: 'ALL',
    txMarketFilter: 'ALL',
};

function formatMoney(value, currencySymbol) {
    if (value === null || value === undefined || isNaN(value)) return '--';
    const sym = currencySymbol || '$';
    return sym + Number(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function formatQuantity(value) {
    if (value === null || value === undefined || isNaN(value)) return '--';
    const num = Number(value);
    return Number.isInteger(num) ? String(num) : num.toLocaleString(undefined, { maximumFractionDigits: 4 });
}

function formatDate(dateStr) {
    if (!dateStr) return '--';
    return dateStr;
}

function renderHoldings() {
    const tbody = document.getElementById('holdingsBody');
    if (!tbody) return;

    let items = portfolioState.holdings || [];
    if (portfolioState.holdingsFilter !== 'ALL') {
        items = items.filter(h => h.market === portfolioState.holdingsFilter);
    }

    if (items.length === 0) {
        tbody.innerHTML = '<tr><td colspan="10" class="loading-row">No active holdings found in this view. Use the button above to buy stocks or crypto!</td></tr>';
        return;
    }

    tbody.innerHTML = items.map(h => {
        const sym = h.currency_symbol || (h.market === 'ISE' ? '₹' : '$');
        const plUp = (h.profit_loss || 0) >= 0;
        const plClass = plUp ? 'up' : 'down';
        const plSign = plUp ? '+' : '';

        return '<tr>' +
            '<td><strong>' + h.name + '</strong></td>' +
            '<td><span class="badge badge-market badge-' + (h.market || 'USE').toLowerCase() + '">' + h.market + '</span></td>' +
            '<td>' + formatDate(h.bought_date) + '</td>' +
            '<td class="num">' + formatMoney(h.bought_price, sym) + '</td>' +
            '<td class="num">' + formatMoney(h.price, sym) + '</td>' +
            '<td class="num font-bold">' + formatQuantity(h.quantity) + '</td>' +
            '<td class="num">' + formatMoney(h.total_amount, sym) + '</td>' +
            '<td class="num pl-cell ' + plClass + '">' + plSign + formatMoney(h.profit_loss, sym) + '</td>' +
            '<td class="num pl-cell ' + plClass + '">' + plSign + (h.profit_loss_percent || 0).toFixed(2) + '%</td>' +
            '<td class="actions-cell">' +
                '<button type="button" class="btn-sell-now" data-action="sell-holding" data-market="' + h.market + '" data-symbol="' + h.name + '" data-lot-id="' + (h.lot_id || '') + '" data-price="' + h.price + '" data-quantity="' + h.quantity + '">Sell Now</button>' +
                '<button type="button" class="btn-buy-more" data-action="buy-more" data-market="' + h.market + '" data-symbol="' + h.name + '" data-price="' + h.price + '">Buy More</button>' +
            '</td>' +
        '</tr>';
    }).join('');

    bindHoldingActionButtons();
}

function renderTransactions() {
    const tbody = document.getElementById('transactionsBody');
    if (!tbody) return;

    let items = portfolioState.transactions || [];
    if (portfolioState.txTypeFilter !== 'ALL') {
        items = items.filter(t => t.type === portfolioState.txTypeFilter);
    }
    if (portfolioState.txMarketFilter !== 'ALL') {
        items = items.filter(t => t.market === portfolioState.txMarketFilter);
    }

    if (items.length === 0) {
        tbody.innerHTML = '<tr><td colspan="9" class="loading-row">No transactions recorded yet for this filter.</td></tr>';
        return;
    }

    tbody.innerHTML = items.map(t => {
        const isBuy = t.type === 'BUY';
        const typeBadge = isBuy
            ? '<span class="badge badge-buy">BUY</span>'
            : '<span class="badge badge-sell">SELL</span>';
        const sym = t.currency === 'INR' || t.market === 'ISE' ? '₹' : '$';
        const qtyFormatted = isBuy
            ? '<span class="text-green font-bold">+' + formatQuantity(t.quantity) + '</span>'
            : '<span class="text-red font-bold">-' + formatQuantity(t.quantity) + '</span>';

        let plCell = '--';
        if (!isBuy && t.profit_loss !== null && t.profit_loss !== undefined) {
            const plUp = t.profit_loss >= 0;
            const plClass = plUp ? 'up' : 'down';
            const plSign = plUp ? '+' : '';
            plCell = '<span class="pl-cell ' + plClass + '">' + plSign + formatMoney(t.profit_loss, sym) + '</span>';
        }

        return '<tr>' +
            '<td><span class="tx-date">' + (t.date || t.timestamp || '--') + '</span></td>' +
            '<td>' + typeBadge + '</td>' +
            '<td><strong>' + t.symbol + '</strong></td>' +
            '<td><span class="badge badge-market badge-' + (t.market || 'USE').toLowerCase() + '">' + t.market + '</span></td>' +
            '<td class="num">' + qtyFormatted + '</td>' +
            '<td class="num">' + formatMoney(t.price, sym) + '</td>' +
            '<td class="num">' + formatMoney(t.total_amount, sym) + '</td>' +
            '<td class="num">' + plCell + '</td>' +
            '<td><span class="badge badge-status">' + (t.status || 'Completed') + '</span></td>' +
        '</tr>';
    }).join('');
}

function bindHoldingActionButtons() {
    document.querySelectorAll('[data-action="sell-holding"]').forEach(btn => {
        btn.addEventListener('click', function () {
            const market = btn.dataset.market;
            const symbol = btn.dataset.symbol;
            const lotId = btn.dataset.lotId;
            const maxQuantity = Number(btn.dataset.quantity);
            const currentPrice = Number(btn.dataset.price);
            const currencySymbol = market === 'ISE' ? '₹' : '$';

            if (!lotId) {
                loadPortfolioData();
                return;
            }

            TradeModal.open({
                action: 'sell',
                market: market,
                assetType: market === 'CCME' ? 'crypto' : 'stock',
                symbol: symbol,
                lotId: lotId,
                maxQuantity: maxQuantity,
                currentPrice: currentPrice,
                currencySymbol: currencySymbol,
                onSuccess: function () {
                    loadPortfolioData();
                }
            });
        });
    });

    document.querySelectorAll('[data-action="buy-more"]').forEach(btn => {
        btn.addEventListener('click', function () {
            const symbol = btn.dataset.symbol;
            openQuickBuyModal(symbol);
        });
    });
}

function loadPortfolioData() {
    fetch('/api/portfolio/summary')
        .then(res => res.json())
        .then(data => {
            if (data.error) {
                console.error(data.error);
                return;
            }

            portfolioState.summary = data;
            portfolioState.holdings = data.holdings || [];
            portfolioState.transactions = data.transactions || [];

            // Update wallet pills
            const wallets = data.wallet || {};
            document.getElementById('walletISE').textContent = '₹' + Number(wallets.ISE || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
            document.getElementById('walletUSE').textContent = '$' + Number(wallets.USE || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
            document.getElementById('walletCCME').textContent = '$' + Number(wallets.CCME || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });

            // Update stats
            const stats = data.stats || {};
            document.getElementById('holdingsCount').textContent = stats.holdings_count !== undefined ? stats.holdings_count : portfolioState.holdings.length;
            document.getElementById('tradesCount').textContent = stats.total_trades || 0;
            document.getElementById('buyCount').textContent = stats.buy_count || 0;
            document.getElementById('sellCount').textContent = stats.sell_count || 0;

            const iseHoldings = portfolioState.holdings.filter(h => h.market === 'ISE').length;
            const useHoldings = portfolioState.holdings.filter(h => h.market === 'USE').length;
            const ccmeHoldings = portfolioState.holdings.filter(h => h.market === 'CCME').length;
            document.getElementById('countISE').textContent = iseHoldings;
            document.getElementById('countUSE').textContent = useHoldings;
            document.getElementById('countCCME').textContent = ccmeHoldings;

            // Badges
            document.getElementById('badgeHoldings').textContent = portfolioState.holdings.length;
            document.getElementById('badgeTransactions').textContent = portfolioState.transactions.length;

            // Realized P/L
            const plUSD = stats.realized_pl_usd || 0;
            const plINR = stats.realized_pl_inr || 0;
            document.getElementById('realizedPLUSD').textContent = (plUSD >= 0 ? '+$' : '-$') + Math.abs(plUSD).toFixed(2);
            document.getElementById('realizedPLUSD').className = plUSD >= 0 ? 'text-green' : 'text-red';
            document.getElementById('realizedPLINR').textContent = (plINR >= 0 ? '+₹' : '-₹') + Math.abs(plINR).toFixed(2);
            document.getElementById('realizedPLINR').className = plINR >= 0 ? 'text-green' : 'text-red';

            const plCombined = plUSD + (plINR / 83.0);
            const plSign = plCombined >= 0 ? '+' : '-';
            const plEl = document.getElementById('realizedPL');
            plEl.textContent = plSign + '$' + Math.abs(plCombined).toFixed(2) + ' net';
            plEl.className = 'sc-value ' + (plCombined >= 0 ? 'up' : 'down');

            renderHoldings();
            renderTransactions();
        })
        .catch(err => {
            console.error('Error loading portfolio data:', err);
        });
}

// Quick Buy Modal Handling
let quickBuyState = {
    symbol: '',
    market: 'USE',
    price: 0,
    currencySymbol: '$',
    balance: 0,
};

function resolveMarketForSymbol(symbol) {
    const s = symbol.trim().toUpperCase();
    if (s.endsWith('.NS') || s.endsWith('.BO')) return 'ISE';
    if (s.endsWith('-USD')) return 'CCME';
    return 'USE';
}

function openQuickBuyModal(prefilledSymbol) {
    const modal = document.getElementById('quickTradeModal');
    const input = document.getElementById('quickSymbol');
    const qtyInput = document.getElementById('quickQuantity');
    const errorEl = document.getElementById('quickTradeError');

    errorEl.classList.add('hidden');
    modal.classList.remove('hidden');

    if (prefilledSymbol) {
        input.value = prefilledSymbol;
        fetchPriceForQuickBuy(prefilledSymbol);
    } else {
        input.value = '';
        document.getElementById('quickUnitPrice').textContent = '--';
        document.getElementById('quickTotalCost').textContent = '--';
        document.getElementById('quickWalletBalance').textContent = '--';
    }
    qtyInput.value = '1';
    input.focus();
}

function closeQuickBuyModal() {
    const modal = document.getElementById('quickTradeModal');
    modal.classList.add('hidden');
}

function updateQuickBuyEstimates() {
    const qtyInput = document.getElementById('quickQuantity');
    const qty = Number(qtyInput.value);
    const totalEl = document.getElementById('quickTotalCost');
    const errorEl = document.getElementById('quickTradeError');

    if (!quickBuyState.price || qty <= 0 || !Number.isFinite(qty)) {
        totalEl.textContent = '--';
        return;
    }

    const total = quickBuyState.price * qty;
    totalEl.textContent = formatMoney(total, quickBuyState.currencySymbol);

    if (total > quickBuyState.balance + 1e-9) {
        errorEl.textContent = 'Insufficient purse balance for this quantity.';
        errorEl.classList.remove('hidden');
    } else {
        errorEl.classList.add('hidden');
    }
}

function fetchPriceForQuickBuy(symbol) {
    if (!symbol || !symbol.trim()) return;
    const cleanSym = symbol.trim().toUpperCase();
    const market = resolveMarketForSymbol(cleanSym);
    const currencySym = market === 'ISE' ? '₹' : '$';

    quickBuyState.symbol = cleanSym;
    quickBuyState.market = market;
    quickBuyState.currencySymbol = currencySym;

    const unitPriceEl = document.getElementById('quickUnitPrice');
    const walletBalanceEl = document.getElementById('quickWalletBalance');
    unitPriceEl.textContent = 'Fetching price...';

    const wallets = (portfolioState.summary && portfolioState.summary.wallet) || {};
    quickBuyState.balance = Number(wallets[market] || 0);
    walletBalanceEl.textContent = formatMoney(quickBuyState.balance, currencySym) + ' (' + market + ')';

    const assetType = market === 'CCME' ? 'crypto' : 'stock';
    fetch('/api/asset/' + assetType + '/' + encodeURIComponent(cleanSym) + '/chart?range=24H')
        .then(res => res.json())
        .then(data => {
            if (data.error) {
                unitPriceEl.textContent = 'Unavailable';
                return;
            }
            quickBuyState.price = Number(data.current_price);
            unitPriceEl.textContent = formatMoney(quickBuyState.price, currencySym);
            updateQuickBuyEstimates();
        })
        .catch(() => {
            unitPriceEl.textContent = 'Unavailable';
        });
}

function submitQuickBuy() {
    const qtyInput = document.getElementById('quickQuantity');
    const qty = Number(qtyInput.value);
    const errorEl = document.getElementById('quickTradeError');
    const submitBtn = document.getElementById('quickTradeSubmit');

    if (!quickBuyState.symbol) {
        errorEl.textContent = 'Please enter or select an asset symbol.';
        errorEl.classList.remove('hidden');
        return;
    }

    if (!qty || qty <= 0 || !Number.isFinite(qty)) {
        errorEl.textContent = 'Please enter a valid quantity greater than 0.';
        errorEl.classList.remove('hidden');
        return;
    }

    if (quickBuyState.market !== 'CCME' && !Number.isInteger(qty)) {
        errorEl.textContent = 'Stock quantity must be a whole number.';
        errorEl.classList.remove('hidden');
        return;
    }

    const total = quickBuyState.price * qty;
    if (total > quickBuyState.balance + 1e-9) {
        errorEl.textContent = 'Insufficient purse balance.';
        errorEl.classList.remove('hidden');
        return;
    }

    submitBtn.disabled = true;
    submitBtn.textContent = 'Executing Buy...';
    errorEl.classList.add('hidden');

    fetch('/api/trade/buy', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            symbol: quickBuyState.symbol,
            quantity: qty,
            market: quickBuyState.market,
            asset_type: quickBuyState.market === 'CCME' ? 'crypto' : 'stock',
            current_price: quickBuyState.price
        })
    })
    .then(res => res.json())
    .then(data => {
        submitBtn.disabled = false;
        submitBtn.textContent = 'Confirm Buy';

        if (data.error) {
            errorEl.textContent = data.error;
            errorEl.classList.remove('hidden');
            return;
        }

        closeQuickBuyModal();
        alert('Order executed successfully! Bought ' + qty + ' of ' + quickBuyState.symbol + ' for ' + formatMoney(data.total_amount, quickBuyState.currencySymbol));
        loadPortfolioData();
    })
    .catch(() => {
        submitBtn.disabled = false;
        submitBtn.textContent = 'Confirm Buy';
        errorEl.textContent = 'Network error while executing trade. Please try again.';
        errorEl.classList.remove('hidden');
    });
}

document.addEventListener('DOMContentLoaded', function () {
    const menuBtn = document.getElementById('menuBtn');
    const dropdownMenu = document.getElementById('dropdownMenu');
    if (menuBtn && dropdownMenu) {
        menuBtn.addEventListener('click', function (e) {
            e.stopPropagation();
            dropdownMenu.classList.toggle('hidden');
        });
        document.addEventListener('click', function (e) {
            if (!dropdownMenu.contains(e.target) && e.target !== menuBtn) {
                dropdownMenu.classList.add('hidden');
            }
        });
    }

    const tabHoldingsBtn = document.getElementById('tabHoldingsBtn');
    const tabTransactionsBtn = document.getElementById('tabTransactionsBtn');
    const holdingsTabContent = document.getElementById('holdingsTabContent');
    const transactionsTabContent = document.getElementById('transactionsTabContent');

    if (tabHoldingsBtn && tabTransactionsBtn) {
        tabHoldingsBtn.addEventListener('click', function () {
            tabHoldingsBtn.classList.add('active');
            tabTransactionsBtn.classList.remove('active');
            holdingsTabContent.classList.remove('hidden');
            transactionsTabContent.classList.add('hidden');
        });

        tabTransactionsBtn.addEventListener('click', function () {
            tabTransactionsBtn.classList.add('active');
            tabHoldingsBtn.classList.remove('active');
            transactionsTabContent.classList.remove('hidden');
            holdingsTabContent.classList.add('hidden');
        });
    }

    document.querySelectorAll('[data-market-filter]').forEach(btn => {
        btn.addEventListener('click', function () {
            document.querySelectorAll('[data-market-filter]').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            portfolioState.holdingsFilter = btn.dataset.marketFilter;
            renderHoldings();
        });
    });

    document.querySelectorAll('[data-type-filter]').forEach(btn => {
        btn.addEventListener('click', function () {
            document.querySelectorAll('[data-type-filter]').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            portfolioState.txTypeFilter = btn.dataset.typeFilter;
            renderTransactions();
        });
    });

    document.querySelectorAll('[data-tx-market-filter]').forEach(btn => {
        btn.addEventListener('click', function () {
            document.querySelectorAll('[data-tx-market-filter]').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            portfolioState.txMarketFilter = btn.dataset.txMarketFilter;
            renderTransactions();
        });
    });

    const quickTradeBtn = document.getElementById('quickTradeBtn');
    const quickTradeClose = document.getElementById('quickTradeClose');
    const quickTradeCancel = document.getElementById('quickTradeCancel');
    const quickTradeBackdrop = document.getElementById('quickTradeBackdrop');
    const quickSymbolInput = document.getElementById('quickSymbol');
    const quickQtyInput = document.getElementById('quickQuantity');
    const quickTradeSubmit = document.getElementById('quickTradeSubmit');

    if (quickTradeBtn) quickTradeBtn.addEventListener('click', () => openQuickBuyModal());
    if (quickTradeClose) quickTradeClose.addEventListener('click', closeQuickBuyModal);
    if (quickTradeCancel) quickTradeCancel.addEventListener('click', closeQuickBuyModal);
    if (quickTradeBackdrop) quickTradeBackdrop.addEventListener('click', closeQuickBuyModal);

    if (quickSymbolInput) {
        quickSymbolInput.addEventListener('change', () => fetchPriceForQuickBuy(quickSymbolInput.value));
        quickSymbolInput.addEventListener('blur', () => fetchPriceForQuickBuy(quickSymbolInput.value));
    }
    if (quickQtyInput) {
        quickQtyInput.addEventListener('input', updateQuickBuyEstimates);
    }
    if (quickTradeSubmit) {
        quickTradeSubmit.addEventListener('click', submitQuickBuy);
    }

    loadPortfolioData();
    setInterval(loadPortfolioData, REFRESH_INTERVAL_MS);
});
