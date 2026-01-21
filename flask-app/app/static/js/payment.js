const {
    bookingId,
    installmentId,
    clientSecret,
    publishableKey,
    successUrl,
    baseAmountCents,
    remainingAmountCents,
    paymentPlan,
    paymentStep,
} = window.checkoutConfig || {};

const messageElement = document.getElementById("payment-message");
const placeOrderButton = document.getElementById("place-order-btn");
const payoffCheckbox = document.getElementById("payoff-checkbox");

let stripe = null;
let elements = null;
let paymentElement = null;
let lastPaymentMethodId = null;
let quoteInFlight = false;
let quoteTimer = null;
let lastQuote = null;
let isPayoffMode = false;

const formatMoney = (cents) => `$${(cents / 100).toFixed(2)}`;

const updateSummary = (quote) => {
    const summaryBase = document.getElementById("summary-base");
    const summaryFee = document.getElementById("summary-fee");
    const summaryTotal = document.getElementById("summary-total");
    
    if (summaryBase) summaryBase.textContent = formatMoney(quote.base_amount);
    if (summaryFee) summaryFee.textContent = formatMoney(quote.fee);
    if (summaryTotal) summaryTotal.textContent = formatMoney(quote.final_amount);
};

const showMessage = (text) => {
    if (messageElement) {
        messageElement.textContent = text;
        messageElement.classList.remove("hidden");
    }
};

const showPreSubmitError = () => {
    showMessage("Please complete your card details before continuing.");
};

const showPaymentFailed = () => {
    showMessage("Payment failed. Please try again.");
};

const clearMessage = () => {
    if (messageElement) {
        messageElement.textContent = "";
        messageElement.classList.add("hidden");
    }
};

// 初始化 Stripe Elements
if (clientSecret && publishableKey) {
    try {
        stripe = Stripe(publishableKey);
        elements = stripe.elements({
            clientSecret,
            paymentMethodCreation: "manual",
        });
        paymentElement = elements.create("payment", {
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
    } catch (error) {
        console.error("Failed to initialize Stripe Elements:", error);
        let errorMsg = "Payment is not ready. Please refresh the page.";
        if (error.message) {
            errorMsg += ` Error: ${error.message}`;
        }
        showMessage(errorMsg);
        if (placeOrderButton) {
            placeOrderButton.disabled = true;
        }
    }
} else {
    let errorMsg = "Payment is not ready. ";
    if (!publishableKey) {
        errorMsg += "Stripe publishable key is missing. ";
    }
    if (!clientSecret) {
        errorMsg += "Payment intent client secret is missing. ";
    }
    errorMsg += "Please check your configuration or refresh the page.";
    showMessage(errorMsg);
    console.error("Payment initialization failed:", {
        hasPublishableKey: !!publishableKey,
        hasClientSecret: !!clientSecret,
        publishableKey: publishableKey ? publishableKey.substring(0, 20) + "..." : null,
        clientSecret: clientSecret ? clientSecret.substring(0, 20) + "..." : null
    });
    if (placeOrderButton) {
        placeOrderButton.disabled = true;
    }
}

const requestQuote = async (silent = false) => {
    if (quoteInFlight || !elements || !stripe) {
        console.log("requestQuote blocked:", { quoteInFlight, hasElements: !!elements, hasStripe: !!stripe });
        return false;
    }
    quoteInFlight = true;
    clearMessage();

    console.log("Submitting elements...");
    const { error: submitError } = await elements.submit();
    if (submitError) {
        console.error("Elements submit error:", submitError);
        quoteInFlight = false;
        if (!silent) {
            showPreSubmitError();
        }
        return false;
    }

    console.log("Creating payment method...");
    const { error, paymentMethod } = await stripe.createPaymentMethod({
        elements,
    });

    if (error) {
        console.error("Payment method creation error:", error);
        quoteInFlight = false;
        if (!silent) {
            showPreSubmitError();
        }
        return false;
    }

    if (!paymentMethod || !paymentMethod.id) {
        console.error("Payment method is null or has no id:", paymentMethod);
        quoteInFlight = false;
        if (!silent) {
            showPreSubmitError();
        }
        return false;
    }

    console.log("Payment method created:", paymentMethod.id);

    if (paymentMethod.id === lastPaymentMethodId) {
        quoteInFlight = false;
        return true;
    }

    lastPaymentMethodId = paymentMethod.id;

    try {
        // 如果勾选了 payoff，使用剩余余额作为基础金额，并且优先使用 booking_id
        const currentPaymentStep = isPayoffMode ? 'payoff' : (paymentStep || null);
        const currentBaseAmount = isPayoffMode && remainingAmountCents ? remainingAmountCents : baseAmountCents;
        
        // 在 payoff 模式下，如果同时有 booking_id 和 installment_id，优先使用 booking_id
        const requestBody = {
            booking_id: (isPayoffMode && bookingId) ? bookingId : (bookingId || null),
            installment_id: (isPayoffMode && bookingId) ? null : (installmentId || null),  // payoff 模式下不使用 installment_id
            payment_method_id: paymentMethod.id,
            payment_step: currentPaymentStep,
            base_amount_cents: currentBaseAmount || null,  // 用于测试场景或 payoff 模式
        };
        console.log("Sending quote request:", requestBody);
        const response = await fetch("/api/payment/quote", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(requestBody),
        });
        console.log("Quote response status:", response.status, response.statusText);
        const result = await response.json();
        if (!response.ok) {
            throw new Error(result.error || "Quote failed");
        }
        console.log("Quote received:", result);
        lastQuote = result;
        updateSummary(result);
    } catch (err) {
        console.error("Quote request failed:", err);
        if (!silent) {
            showPaymentFailed();
        }
    } finally {
        quoteInFlight = false;
    }
    return true;
};

// 勾选框事件监听器
if (payoffCheckbox) {
    let payoffUpdateTimer = null;
    
    payoffCheckbox.addEventListener("change", async (e) => {
        isPayoffMode = e.target.checked;
        
        // 立即更新基础金额显示，提供即时反馈
        const currentBaseAmount = isPayoffMode && remainingAmountCents ? remainingAmountCents : baseAmountCents;
        
        // 立即更新 summary_items 中的金额显示
        const summaryItemAmount = document.getElementById("summary-item-amount");
        if (summaryItemAmount) {
            if (isPayoffMode && remainingAmountCents) {
                summaryItemAmount.textContent = formatMoney(remainingAmountCents);
            } else {
                const baseAmount = summaryItemAmount.getAttribute("data-base-amount");
                if (baseAmount) {
                    summaryItemAmount.textContent = formatMoney(parseInt(baseAmount));
                } else {
                    summaryItemAmount.textContent = formatMoney(baseAmountCents);
                }
            }
        }
        
        // 立即更新 total（使用当前 fee，如果有的话）
        const currentFee = lastQuote ? lastQuote.fee : 0;
        const finalAmount = currentBaseAmount + currentFee;
        updateSummary({
            base_amount: currentBaseAmount,
            fee: currentFee,
            final_amount: finalAmount,
        });
        
        // 清除之前的定时器
        if (payoffUpdateTimer) {
            clearTimeout(payoffUpdateTimer);
        }
        
        // 延迟重新计算 fee（防抖处理，避免频繁请求）
        payoffUpdateTimer = setTimeout(async () => {
            // 如果之前有 payment method，直接使用它重新计算 fee
            if (lastPaymentMethodId) {
                try {
                    const currentPaymentStep = isPayoffMode ? 'payoff' : (paymentStep || null);
                    const requestBody = {
                        booking_id: (isPayoffMode && bookingId) ? bookingId : (bookingId || null),
                        installment_id: (isPayoffMode && bookingId) ? null : (installmentId || null),
                        payment_method_id: lastPaymentMethodId,
                        payment_step: currentPaymentStep,
                        base_amount_cents: currentBaseAmount || null,
                    };
                    const response = await fetch("/api/payment/quote", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify(requestBody),
                    });
                    const result = await response.json();
                    if (response.ok) {
                        lastQuote = result;
                        updateSummary(result);
                        return;
                    }
                } catch (err) {
                    console.error("Quote request error:", err);
                }
            }
            
            // 如果卡片信息已填写，尝试获取新的 payment method 并重新计算 fee
            if (paymentElement && elements && stripe && !lastPaymentMethodId) {
                try {
                    const { error: submitError } = await elements.submit();
                    if (!submitError) {
                        const { error, paymentMethod } = await stripe.createPaymentMethod({
                            elements,
                        });
                        if (!error && paymentMethod && paymentMethod.id) {
                            lastPaymentMethodId = paymentMethod.id;
                            await requestQuote(true);
                            return;
                        }
                    }
                } catch (err) {
                    console.log("Could not get payment method:", err);
                }
            }
        }, 100); // 100ms 防抖延迟
    });
}

if (paymentElement) {
    paymentElement.on("change", (event) => {
        console.log("Payment element changed:", { complete: event.complete, empty: event.empty });
        if (!event.complete) {
            lastPaymentMethodId = null;
            lastQuote = null;
            const currentBaseAmount = isPayoffMode && remainingAmountCents ? remainingAmountCents : baseAmountCents;
            updateSummary({
                base_amount: currentBaseAmount ?? 0,
                fee: 0,
                final_amount: currentBaseAmount ?? 0,
            });
            return;
        }
        if (quoteTimer) {
            clearTimeout(quoteTimer);
        }
        quoteTimer = setTimeout(() => {
            console.log("Triggering quote request...");
            requestQuote(true);
        }, 500);
    });
}

if (placeOrderButton) {
    placeOrderButton.addEventListener("click", async (e) => {
        e.preventDefault();
        clearMessage();

        if (!stripe || !elements) {
            showMessage("Payment is not ready. Please refresh the page.");
            return;
        }

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
            // 使用和 Quote 一样的逻辑处理 payoff 模式
            const currentPaymentStep = isPayoffMode ? 'payoff' : (paymentStep || null);
            const currentInstallmentId = (isPayoffMode && bookingId) ? null : (installmentId || null);
            
            const response = await fetch("/api/payment/intent", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    booking_id: bookingId || null,
                    installment_id: currentInstallmentId,
                    payment_method_id: lastPaymentMethodId,
                    payment_plan: paymentPlan || "full",
                    payment_step: currentPaymentStep,
                }),
            });
            const result = await response.json();
            if (!response.ok) {
                throw new Error(result.error || "Payment update failed");
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
            showMessage(err.message || "Payment failed. Please try again.");
        } finally {
            if (placeOrderButton) {
                placeOrderButton.disabled = false;
                placeOrderButton.textContent = "Place Order";
            }
        }
    });
}
