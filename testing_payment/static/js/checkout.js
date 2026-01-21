const { orderId, clientSecret, publishableKey, successUrl } = window.checkoutConfig;

const stripe = Stripe(publishableKey);
const elements = stripe.elements({
    clientSecret,
    paymentMethodCreation: "manual",
});
const paymentElement = elements.create("payment", {
    paymentMethodOrder: ["card"],
    wallets: {
        applePay: "never",
        googlePay: "never",
    },
    fields: {
        billingDetails: {
            name: "auto",
            email: "auto",
            phone: "auto",
            address: "auto",
        },
    },
});
paymentElement.mount("#payment-element");

const messageElement = document.getElementById("payment-message");
const placeOrderButton = document.getElementById("place-order-btn");

let lastPaymentMethodId = null;
let quoteInFlight = false;
let quoteTimer = null;
let lastQuote = null;
let baseAmountCents = null;
const formatMoney = (cents) => `$${(cents / 100).toFixed(2)}`;

const updateSummary = (quote) => {
    document.getElementById("summary-base").textContent = formatMoney(quote.base_amount);
    document.getElementById("summary-fee").textContent = formatMoney(quote.fee);
    document.getElementById("summary-tax").textContent = formatMoney(quote.tax_amount || 0);
    document.getElementById("summary-total").textContent = formatMoney(quote.final_amount);
    document.getElementById("summary-funding").textContent = quote.funding || "-";
};

const showMessage = (text) => {
    messageElement.textContent = text;
    messageElement.classList.remove("hidden");
};

const showPreSubmitError = () => {
    showMessage("支付信息不完整，请补全卡信息后再试。");
};

const showPaymentFailed = () => {
    showMessage("支付失败，请稍后重试。");
};

const showPaymentCreated = () => {
    showMessage("已创建待支付订单，请继续完成支付步骤。");
};

const clearMessage = () => {
    messageElement.textContent = "";
    messageElement.classList.add("hidden");
};

const loadOrderSummary = async () => {
    try {
        const response = await fetch("/api/order");
        const result = await response.json();
        if (!response.ok) {
            throw new Error(result.error || "加载订单失败");
        }
        baseAmountCents = result.base_amount;
        updateSummary({
            base_amount: result.base_amount,
            fee: 0,
            tax_amount: 0,
            final_amount: result.base_amount,
            funding: "-",
        });
    } catch (err) {
        showMessage(err.message || "加载订单失败");
    }
};

const requestQuote = async (silent = false) => {
    if (quoteInFlight) return;
    quoteInFlight = true;
    clearMessage();

    const { error: submitError } = await elements.submit();
    if (submitError) {
        console.warn("elements.submit error", submitError);
        quoteInFlight = false;
        if (!silent) {
            showPreSubmitError();
        }
        return false;
    }

    const { error, paymentMethod } = await stripe.createPaymentMethod({
        elements,
    });

    if (error) {
        console.warn("createPaymentMethod error", error);
        quoteInFlight = false;
        if (!silent) {
            showPreSubmitError();
        }
        return false;
    }

    if (!paymentMethod || !paymentMethod.id) {
        console.warn("createPaymentMethod missing paymentMethod", paymentMethod);
        quoteInFlight = false;
        if (!silent) {
            showPreSubmitError();
        }
        return false;
    }

    if (paymentMethod.id === lastPaymentMethodId) {
        quoteInFlight = false;
        return;
    }

    lastPaymentMethodId = paymentMethod.id;

    const billingAddress = paymentMethod.billing_details
        ? paymentMethod.billing_details.address
        : null;

    try {
        const response = await fetch("/api/quote", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                order_id: orderId,
                payment_method_id: paymentMethod.id,
                billing_address: billingAddress,
            }),
        });
        const result = await response.json();
        if (!response.ok) {
            throw new Error(result.error || "报价失败");
        }
        lastQuote = result;
        baseAmountCents = result.base_amount;
        updateSummary(result);
    } catch (err) {
        if (!silent) {
            showPaymentFailed();
        }
    } finally {
        quoteInFlight = false;
    }
    return true;
};

loadOrderSummary();

paymentElement.on("change", (event) => {
    if (!event.complete) {
        lastPaymentMethodId = null;
        lastQuote = null;
        updateSummary({
            base_amount: baseAmountCents ?? 0,
            fee: 0,
        tax_amount: 0,
            final_amount: baseAmountCents ?? 0,
            funding: "-",
        });
        return;
    }
    if (quoteTimer) {
        clearTimeout(quoteTimer);
    }
    quoteTimer = setTimeout(() => {
        requestQuote(true);
    }, 500);
});

placeOrderButton.addEventListener("click", async (e) => {
    e.preventDefault();
    clearMessage();

    if (!lastQuote) {
        await requestQuote(false);
        if (!lastQuote) {
            showPreSubmitError();
            return;
        }
    }

    placeOrderButton.disabled = true;
    placeOrderButton.textContent = "Processing...";

    try {
        const response = await fetch("/api/payment-intent", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ order_id: orderId }),
        });
        const result = await response.json();
        if (!response.ok) {
            throw new Error(result.error || "无法创建支付");
        }

        const { error } = await stripe.confirmPayment({
            elements,
            confirmParams: {
                return_url: successUrl,
            },
        });

        if (error) {
            showPaymentFailed();
            return;
        }
    } catch (err) {
        showPaymentFailed();
    } finally {
        placeOrderButton.disabled = false;
        placeOrderButton.textContent = "Place order";
    }
});
