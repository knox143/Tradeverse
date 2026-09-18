/* Shared TradeVerse buy/sell quantity modal. */
(function () {
    function ensureModal() {
        let modal = document.getElementById("tradeModal");
        if (modal) return modal;

        modal = document.createElement("div");
        modal.id = "tradeModal";
        modal.className = "trade-modal hidden";
        modal.innerHTML = `
            <div class="trade-modal-backdrop" data-trade-close="1"></div>
            <div class="trade-modal-card" role="dialog" aria-modal="true" aria-labelledby="tradeModalTitle">
                <button type="button" class="trade-modal-close" id="tradeModalClose" aria-label="Close">&times;</button>
                <h3 id="tradeModalTitle">Trade</h3>
                <p id="tradeModalAsset" class="trade-modal-asset"></p>
                <label for="tradeQuantity">Quantity</label>
                <input id="tradeQuantity" type="number" min="0.00000001" step="1" value="1" inputmode="decimal">
                <div class="trade-modal-price-row"><span>Current price</span><strong id="tradeCurrentPrice">--</strong></div>
                <div class="trade-modal-price-row"><span id="tradeTotalLabel">Total amount</span><strong id="tradeTotalAmount">--</strong></div>
                <div class="trade-modal-price-row" id="tradeBalanceRow"><span>Wallet balance</span><strong id="tradeBalance">--</strong></div>
                <p id="tradeModalError" class="trade-modal-error hidden"></p>
                <div class="trade-modal-actions">
                    <button type="button" class="btn btn-navy" id="tradeModalCancel">Cancel</button>
                    <button type="button" class="btn-buy" id="tradeModalSubmit">Confirm</button>
                </div>
            </div>`;
        document.body.appendChild(modal);

        document.getElementById("tradeModalClose").addEventListener("click", closeModal);
        document.getElementById("tradeModalCancel").addEventListener("click", closeModal);
        modal.querySelector("[data-trade-close]").addEventListener("click", closeModal);
        document.getElementById("tradeQuantity").addEventListener("input", updateTotal);
        document.getElementById("tradeModalSubmit").addEventListener("click", submitTrade);
        return modal;
    }

    let state = null;

    function money(value, symbol) {
        if (value === null || value === undefined || Number.isNaN(Number(value))) return "--";
        return symbol + Number(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 8 });
    }

    function showError(message) {
        const el = document.getElementById("tradeModalError");
        el.textContent = message || "The trade could not be completed.";
        el.classList.remove("hidden");
    }

    function clearError() {
        document.getElementById("tradeModalError").classList.add("hidden");
    }

    function updateTotal() {
        if (!state) return;
        const input = document.getElementById("tradeQuantity");
        const quantity = Number(input.value);
        const totalEl = document.getElementById("tradeTotalAmount");
        if (!Number.isFinite(quantity) || quantity <= 0 || !Number.isFinite(state.currentPrice)) {
            totalEl.textContent = "--";
            return;
        }
        totalEl.textContent = money(state.currentPrice * quantity, state.currencySymbol);

        if (state.action === "buy" && Number.isFinite(state.balance) && quantity * state.currentPrice > state.balance + 1e-9) {
            showError("Insufficient wallet balance for this quantity.");
        } else if (state.action === "sell" && Number.isFinite(state.maxQuantity) && quantity > state.maxQuantity + 1e-9) {
            showError("You cannot sell more than the quantity in this lot.");
        } else {
            clearError();
        }
    }

    function openModal(options) {
        ensureModal();
        state = options;
        const modal = document.getElementById("tradeModal");
        const input = document.getElementById("tradeQuantity");
        const isStock = options.assetType === "stock" || options.market === "USE";

        document.getElementById("tradeModalTitle").textContent = options.action === "buy" ? "Buy" : "Sell";
        document.getElementById("tradeModalAsset").textContent = options.symbol + " · " + (options.action === "buy" ? "Buy" : "Sell");
        document.getElementById("tradeCurrentPrice").textContent = money(options.currentPrice, options.currencySymbol);
        document.getElementById("tradeBalance").textContent = options.balance === undefined ? "--" : money(options.balance, options.currencySymbol);
        document.getElementById("tradeTotalLabel").textContent = options.action === "sell" ? "Sale proceeds" : "Total amount";
        document.getElementById("tradeModalSubmit").textContent = options.action === "sell" ? "Confirm Sell" : "Confirm Buy";
        document.getElementById("tradeModalSubmit").classList.toggle("btn-sell-now", options.action === "sell");
        document.getElementById("tradeBalanceRow").classList.toggle("hidden", options.action === "sell");
        input.step = isStock ? "1" : "0.00000001";
        input.min = isStock ? "1" : "0.00000001";
        input.value = "1";
        clearError();
        modal.classList.remove("hidden");
        input.focus();
        input.select();
        updateTotal();
    }

    function closeModal() {
        const modal = document.getElementById("tradeModal");
        if (modal) modal.classList.add("hidden");
        state = null;
    }

    async function submitTrade() {
        if (!state) return;
        const input = document.getElementById("tradeQuantity");
        const quantity = Number(input.value);
        const isStock = state.assetType === "stock" || state.market === "USE";
        if (!Number.isFinite(quantity) || quantity <= 0) {
            showError("Quantity must be greater than 0.");
            return;
        }
        if (isStock && !Number.isInteger(quantity)) {
            showError("Stock quantity must be a whole number.");
            return;
        }
        if (state.action === "buy" && Number.isFinite(state.balance) && quantity * state.currentPrice > state.balance + 1e-9) {
            showError("Insufficient wallet balance for this quantity.");
            return;
        }
        if (state.action === "sell" && quantity > state.maxQuantity + 1e-9) {
            showError("You cannot sell more than the quantity in this lot.");
            return;
        }

        const submit = document.getElementById("tradeModalSubmit");
        submit.disabled = true;
        submit.textContent = "Processing...";
        clearError();

        const payload = state.action === "buy"
            ? { asset_type: state.assetType, symbol: state.symbol, quantity: quantity, current_price: state.currentPrice }
            : { market: state.market, lot_id: state.lotId, quantity: quantity, current_price: state.currentPrice };

        try {
            const response = await fetch("/api/trade/" + state.action, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });
            const data = await response.json();
            if (!response.ok || data.error) {
                showError(data.error || "The trade could not be completed.");
                return;
            }

            const onSuccess = state.onSuccess;
            closeModal();
            if (typeof onSuccess === "function") onSuccess(data);
        } catch (error) {
            showError("Network error. Please try again.");
        } finally {
            submit.disabled = false;
            submit.textContent = state && state.action === "sell" ? "Confirm Sell" : "Confirm Buy";
        }
    }

    window.TradeModal = { open: openModal, close: closeModal };
})();
