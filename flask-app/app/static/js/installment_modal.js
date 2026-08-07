(function() {
    /** 大屏下强制左右两列（左 PAYMENT，右 Your Booking），用内联样式覆盖 beijing.css 的 w-full/flex-col */
    function applyInstallmentModalLayout() {
        var scrollEl = document.getElementById('booking-modal-scroll');
        var leftCol = document.getElementById('booking-modal-left-col');
        var leftInner = document.getElementById('booking-modal-left-inner');
        var rightEl = document.getElementById('booking-modal-right');
        if (!scrollEl || !leftCol || !rightEl) return;
        var isWide = window.innerWidth >= 1024;
        if (isWide) {
            scrollEl.style.display = 'flex';
            scrollEl.style.flexDirection = 'row';
            leftCol.style.width = '0';
            leftCol.style.minWidth = '0';
            leftCol.style.flex = '1 1 0%';
            if (leftInner) leftInner.style.maxWidth = '535px';
            rightEl.style.width = '335px';
            rightEl.style.minWidth = '335px';
            rightEl.style.flexShrink = '0';
        } else {
            scrollEl.style.display = '';
            scrollEl.style.flexDirection = '';
            leftCol.style.width = '';
            leftCol.style.minWidth = '';
            leftCol.style.flex = '';
            if (leftInner) leftInner.style.maxWidth = '';
            rightEl.style.width = '';
            rightEl.style.minWidth = '';
            rightEl.style.flexShrink = '';
        }
    }

    var config = window.installmentConfig || {};
    var bookingId = config.bookingId;
    const installmentId = config.installmentId;
    const clientSecret = config.clientSecret;
    const publishableKey = config.publishableKey;
    const paymentIntentId = config.paymentIntentId;
    const successUrl = config.successUrl;
    let baseAmountCents = config.baseAmountCents || 0;
    const remainingAmountCents = config.remainingAmountCents || 0;
    const paymentStep = config.paymentStep || 'installment';
    const previewOnly = config.previewOnly === true;
    const achProcessingLocked = config.achProcessingLocked === true;

    const messageEl = document.getElementById('payment-message');
    const placeOrderBtn = document.getElementById('place-order-btn');
    const payoffCheckbox = document.getElementById('payoff-checkbox');
    const resultWrap = document.getElementById('booking-modal-result');
    const formArea = document.getElementById('modal-form-area');
    const btnBar = document.getElementById('booking-modal-btn-bar');
    const loadingEl = document.getElementById('booking-result-loading');
    const successEl = document.getElementById('booking-result-success');
    const processingEl = document.getElementById('booking-result-processing');
    const failureEl = document.getElementById('booking-result-failure');
    const receiptLink = document.getElementById('booking-result-receipt-link');
    const receiptWrap = document.getElementById('booking-result-receipt-wrap');
    const tryAgainBtn = document.getElementById('booking-result-try-again-btn');
    const closeBtn = document.getElementById('booking-result-close-btn');
    const processingCloseBtn = document.getElementById('booking-result-processing-close-btn');
    const homeUrl = (config.homeUrl || '/');

    let stripe = null;
    let elements = null;
    let paymentElement = null;
    let lastPaymentMethodId = null;
    let lastQuote = null;
    let isPayoffMode = false;
    let quoteInFlight = false;

    function formatCents(cents) {
        const n = typeof cents === 'number' ? cents : parseFloat(cents);
        if (isNaN(n)) return '$0.00';
        return '$' + (Math.round(n) / 100).toFixed(2);
    }

    function setPaymentElementLoading(show) {
        var el = document.getElementById('payment-element-loading');
        if (!el) return;
        el.setAttribute('aria-hidden', show ? 'false' : 'true');
        if (show) {
            el.classList.remove('hidden');
        } else {
            el.classList.add('hidden');
        }
    }

    function updateSummary(quote) {
        const base = quote && quote.base_amount != null ? quote.base_amount : baseAmountCents;
        const fee = quote && quote.fee != null ? quote.fee : 0;
        const total = quote && quote.final_amount != null ? quote.final_amount : base + fee;
        const tripTotalEl = document.getElementById('trip-total-amount');
        const feeEl = document.getElementById('fee-amount');
        const totalEl = document.getElementById('total-amount');
        const summaryItemEl = document.getElementById('summary-item-amount');
        if (tripTotalEl) tripTotalEl.textContent = formatCents(base);
        if (feeEl) feeEl.textContent = formatCents(fee);
        if (totalEl) totalEl.textContent = formatCents(total);
        if (summaryItemEl) {
            summaryItemEl.textContent = formatCents(base);
            summaryItemEl.setAttribute('data-base-amount', String(Math.round(base)));
        }
    }

    function showMessage(text) {
        if (messageEl) {
            messageEl.textContent = text;
            messageEl.classList.remove('hidden');
        }
    }

    function clearMessage() {
        if (messageEl) {
            messageEl.textContent = '';
            messageEl.classList.add('hidden');
        }
    }

    var PAYMENT_FAILURE_FALLBACK = 'Your payment could not be completed. Please try again.';

    function formatPaymentFailureMessage(errorOrMsg) {
        if (!errorOrMsg) return PAYMENT_FAILURE_FALLBACK;
        if (typeof errorOrMsg === 'string') {
            var s = errorOrMsg.trim();
            return s || PAYMENT_FAILURE_FALLBACK;
        }
        var msg = (errorOrMsg.message && String(errorOrMsg.message).trim()) || '';
        if (msg) return msg;
        var code = errorOrMsg.decline_code || errorOrMsg.code;
        var map = {
            insufficient_funds: 'Your card has insufficient funds.',
            expired_card: 'Your card has expired.',
            incorrect_cvc: 'Your card’s security code is incorrect.',
            incorrect_number: 'Your card number is incorrect.',
            card_declined: 'Your card was declined. Please try another card or contact your bank.',
            processing_error: 'We could not process your card. Please try again.',
            generic_decline: 'Your card was declined. Please try another card or contact your bank.'
        };
        return (code && map[code]) || PAYMENT_FAILURE_FALLBACK;
    }

    function setFailureReason(errorOrMsg) {
        var reasonWrap = document.getElementById('booking-result-failure-reason');
        var detailEl = document.getElementById('booking-result-failure-detail');
        var text = formatPaymentFailureMessage(errorOrMsg);
        if (detailEl) detailEl.textContent = text;
        if (reasonWrap) {
            if (text) reasonWrap.removeAttribute('hidden');
            else reasonWrap.setAttribute('hidden', '');
        }
    }

    function showResult(state, data) {
        if (!resultWrap || !formArea || !btnBar) return;

        if (state === null) {
            resultWrap.classList.add('hidden');
            resultWrap.setAttribute('aria-hidden', 'true');
            resultWrap.style.minHeight = '';
            resultWrap.classList.remove('is-visible');
            formArea.classList.remove('hidden');
            btnBar.classList.remove('hidden');
            if (loadingEl) loadingEl.classList.add('hidden');
            if (successEl) successEl.classList.add('hidden');
            if (processingEl) processingEl.classList.add('hidden');
            if (failureEl) failureEl.classList.add('hidden');
            return;
        }

        var RESULT_HEIGHT_FLOOR = 280;
        var leftInner = document.getElementById('booking-modal-left-inner');
        var scrollEl = document.getElementById('booking-modal-scroll');

        formArea.classList.add('hidden');
        btnBar.classList.add('hidden');
        resultWrap.classList.remove('hidden');
        resultWrap.setAttribute('aria-hidden', 'false');
        resultWrap.style.minHeight = RESULT_HEIGHT_FLOOR + 'px';
        resultWrap.classList.remove('is-visible');
        void resultWrap.offsetWidth;
        resultWrap.classList.add('is-visible');
        if (loadingEl) loadingEl.classList.add('hidden');
        if (successEl) successEl.classList.add('hidden');
        if (processingEl) processingEl.classList.add('hidden');
        if (failureEl) failureEl.classList.add('hidden');

        if (state === 'loading') {
            if (loadingEl) loadingEl.classList.remove('hidden');
        } else if (state === 'processing') {
            if (processingEl) processingEl.classList.remove('hidden');
            var copyEl = document.getElementById('booking-result-processing-copy');
            if (copyEl && data && data.locked) {
                copyEl.innerHTML = 'A US bank account (ACH) payment for this order is already processing. Please wait until it clears before making another payment. Confirmation and receipt will follow by email.';
            }
            var payoffSec = document.getElementById('installment-payoff-section');
            if (payoffSec) payoffSec.classList.add('hidden');
        } else if (state === 'success') {
            if (successEl) successEl.classList.remove('hidden');
            const bid = data && data.booking_id;
            if (receiptLink && bid) {
                receiptLink.href = (data && data.receipt_url) || ('/booking/' + bid + '/receipt');
                receiptLink.setAttribute('download', 'NHTours-Order-' + bid + '.pdf');
                receiptLink.removeAttribute('target');
                if (receiptWrap) receiptWrap.classList.remove('hidden');
            } else if (receiptWrap) {
                receiptWrap.classList.add('hidden');
            }
            var payoffSecPaid = document.getElementById('installment-payoff-section');
            if (payoffSecPaid) payoffSecPaid.classList.add('hidden');
        } else if (state === 'failure') {
            if (failureEl) failureEl.classList.remove('hidden');
            setFailureReason(
                (data && (data.message || data.error_message || data.error)) || PAYMENT_FAILURE_FALLBACK
            );
        }

        if (scrollEl && window.innerWidth >= 1024) {
            var rightEl = document.getElementById('booking-modal-right');
            requestAnimationFrame(function() {
                var h = RESULT_HEIGHT_FLOOR;
                if (leftInner) h = Math.max(h, leftInner.offsetHeight);
                if (rightEl) h = Math.max(h, rightEl.offsetHeight);
                scrollEl.style.minHeight = h + 'px';
            });
        }
    }

    function pollPaymentStatus(piId) {
        const statusUrl = '/api/payment/status?payment_intent_id=' + encodeURIComponent(piId);
        var polls = 0;
        function poll() {
            fetch(statusUrl)
                .then(function(res) { return res.json(); })
                .then(function(data) {
                    if (data.status === 'succeeded') {
                        showResult('success', {
                            booking_id: data.booking_id,
                            receipt_url: data.receipt_url
                        });
                        if (placeOrderBtn) {
                            placeOrderBtn.disabled = false;
                            placeOrderBtn.textContent = 'Confirm payment';
                        }
                        return;
                    }
                    if (data.status === 'processing') {
                        showResult('processing', { booking_id: data.booking_id });
                        if (placeOrderBtn) {
                            placeOrderBtn.disabled = false;
                            placeOrderBtn.textContent = 'Confirm payment';
                        }
                        return;
                    }
                    if (data.status === 'failed') {
                        showResult('failure', {
                            message: data.error_message || data.message || PAYMENT_FAILURE_FALLBACK
                        });
                        if (placeOrderBtn) {
                            placeOrderBtn.disabled = false;
                            placeOrderBtn.textContent = 'Confirm payment';
                        }
                        return;
                    }
                    polls += 1;
                    if (polls > 45) {
                        showResult('processing', { booking_id: data.booking_id || null });
                        return;
                    }
                    setTimeout(poll, 2000);
                })
                .catch(function() { setTimeout(poll, 2000); });
        }
        poll();
    }

    async function requestQuote(silent) {
        if (quoteInFlight || !elements || !stripe) return false;
        quoteInFlight = true;
        clearMessage();

        const submitResult = await elements.submit();
        if (submitResult && submitResult.error) {
            quoteInFlight = false;
            if (!silent) showMessage('Please complete your card details before continuing.');
            return false;
        }

        const { error, paymentMethod } = await stripe.createPaymentMethod({ elements });
        if (error || !paymentMethod || !paymentMethod.id) {
            quoteInFlight = false;
            if (!silent) showMessage(error ? error.message : 'Could not create payment method.');
            return false;
        }

        lastPaymentMethodId = paymentMethod.id;

        const currentStep = isPayoffMode ? 'payoff' : paymentStep;
        const currentBase = isPayoffMode && remainingAmountCents ? remainingAmountCents : baseAmountCents;

        try {
            const body = {
                booking_id: isPayoffMode ? bookingId : null,
                installment_id: isPayoffMode ? null : installmentId,
                payment_method_id: paymentMethod.id,
                payment_plan: 'installment',
                payment_step: currentStep,
            };
            const response = await fetch('/api/payment/quote', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            const result = await response.json();
            if (!response.ok) throw new Error(result.error || 'Quote failed');
            lastQuote = result;
            updateSummary(result);
        } catch (err) {
            if (!silent) showMessage(err.message || 'Unable to get fee.');
        } finally {
            quoteInFlight = false;
        }
        return true;
    }

    if (tryAgainBtn) {
        tryAgainBtn.addEventListener('click', function() {
            showResult(null);
        });
    }

    if (payoffCheckbox) {
        payoffCheckbox.addEventListener('change', function() {
            isPayoffMode = this.checked;
            const currentBase = isPayoffMode && remainingAmountCents ? remainingAmountCents : baseAmountCents;
            updateSummary({ base_amount: currentBase, fee: lastQuote ? lastQuote.fee : 0, final_amount: currentBase + (lastQuote ? lastQuote.fee : 0) });
            if (lastPaymentMethodId) {
                const currentStep = isPayoffMode ? 'payoff' : paymentStep;
                const body = {
                    booking_id: isPayoffMode ? bookingId : null,
                    installment_id: isPayoffMode ? null : installmentId,
                    payment_method_id: lastPaymentMethodId,
                    payment_plan: 'installment',
                    payment_step: currentStep,
                };
                fetch('/api/payment/quote', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body),
                })
                    .then(function(r) { return r.json(); })
                    .then(function(result) {
                        if (result.fee != null) {
                            lastQuote = result;
                            updateSummary(result);
                        }
                    })
                    .catch(function() {});
            }
        });
    }

    if (placeOrderBtn) {
        placeOrderBtn.addEventListener('click', async function() {
            clearMessage();
            if (!stripe || !elements) {
                showMessage('Payment is not ready. Please refresh the page.');
                return;
            }

            if (!lastQuote) {
                var ok = await requestQuote(false);
                if (!ok || !lastQuote) return;
            }

            placeOrderBtn.disabled = true;
            placeOrderBtn.textContent = 'Processing…';
            showResult('loading');

            try {
                const currentStep = isPayoffMode ? 'payoff' : paymentStep;
                const res = await fetch('/api/payment/intent', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        booking_id: isPayoffMode ? bookingId : null,
                        installment_id: isPayoffMode ? null : installmentId,
                        payment_method_id: lastPaymentMethodId,
                        payment_plan: 'installment',
                        payment_step: currentStep,
                    }),
                });
                const result = await res.json();
                if (!res.ok) throw new Error(result.error || 'Payment update failed');

                const { error, paymentIntent } = await stripe.confirmPayment({
                    elements,
                    confirmParams: { return_url: successUrl },
                    redirect: 'if_required',
                });

                if (error) {
                    showResult('failure', { error: error });
                } else {
                    var pi = paymentIntentId || (result && result.payment_intent_id)
                        || (paymentIntent && paymentIntent.id);
                    if (paymentIntent && paymentIntent.status === 'processing') {
                        showResult('processing', { booking_id: bookingId });
                        if (pi) pollPaymentStatus(pi);
                    } else if (pi) {
                        pollPaymentStatus(pi);
                    } else {
                        showResult('failure', {
                            message: 'Payment confirmation did not return a session. Please try again.'
                        });
                    }
                }
            } catch (err) {
                showResult('failure', {
                    message: (err && err.message) || PAYMENT_FAILURE_FALLBACK
                });
            } finally {
                placeOrderBtn.disabled = false;
                placeOrderBtn.textContent = 'Confirm payment';
            }
        });
    }

    function initStripe() {
        var container = document.getElementById('payment-element');
        if (!container) {
            setPaymentElementLoading(false);
            showMessage('Payment form container not found.');
            return;
        }
        if (!clientSecret || !publishableKey) {
            setPaymentElementLoading(false);
            container.innerHTML = '<p class="text-sm text-amber-700 p-3 bg-amber-50 rounded border border-amber-200">Payment is not ready. Missing configuration. Please use the payment link from your email.</p>';
            container.style.minHeight = '80px';
            showMessage('Payment is not ready. Missing configuration.');
            return;
        }
        try {
            // 保证容器可见、有尺寸，Stripe 才能渲染
            container.style.minHeight = '120px';
            container.style.visibility = 'visible';
            container.style.display = 'block';
            var wrapper = container.closest('.payment-element-wrapper');
            if (wrapper) {
                wrapper.style.minHeight = '120px';
                wrapper.style.overflow = 'visible';
            }
            stripe = Stripe(publishableKey);
            elements = stripe.elements({
                clientSecret: clientSecret,
                paymentMethodCreation: 'manual',
                appearance: {
                    variables: { fontFamily: '"Source Sans Pro", sans-serif' },
                },
            });
            paymentElement = elements.create('payment', {
                paymentMethodOrder: ['card', 'us_bank_account'],
                wallets: { applePay: 'never', googlePay: 'never' },
                fields: { billingDetails: { name: 'auto', email: 'auto', phone: 'auto', address: 'auto' } },
            });
            paymentElement.mount('#payment-element');
            setPaymentElementLoading(false);

            paymentElement.on('change', function(event) {
                var hint = document.getElementById('ach-payment-hint');
                if (hint) {
                    var type = (event && event.value && event.value.type) || '';
                    hint.classList.toggle('hidden', type !== 'us_bank_account');
                }
                if (!event.complete) {
                    lastPaymentMethodId = null;
                    lastQuote = null;
                    updateSummary({ base_amount: baseAmountCents, fee: 0, final_amount: baseAmountCents });
                    return;
                }
                setTimeout(function() { requestQuote(true); }, 500);
            });

            updateSummary({ base_amount: baseAmountCents, fee: 0, final_amount: baseAmountCents });
        } catch (e) {
            console.error('Stripe init error:', e);
            setPaymentElementLoading(false);
            container.innerHTML = '<p class="text-sm text-red-600 p-3 bg-red-50 rounded border border-red-200">Payment form could not load. Please refresh the page.</p>';
            container.style.minHeight = '80px';
            showMessage('Payment could not be loaded. Please refresh.');
        }
    }

    function checkReturnFrom3DS() {
        var params = new URLSearchParams(window.location.search);
        var pi = params.get('payment_intent_id');
        if (pi) {
            showResult('loading');
            pollPaymentStatus(pi);
            return true;
        }
        return false;
    }

    applyInstallmentModalLayout();
    window.addEventListener('resize', function() { applyInstallmentModalLayout(); });

    if (closeBtn) {
        closeBtn.addEventListener('click', function() {
            window.location.href = homeUrl;
        });
    }
    if (processingCloseBtn) {
        processingCloseBtn.addEventListener('click', function() {
            window.location.href = homeUrl;
        });
    }

    if (previewOnly) {
        setPaymentElementLoading(false);
        if (placeOrderBtn) {
            placeOrderBtn.disabled = true;
            placeOrderBtn.textContent = 'Confirm payment';
        }
    } else if (achProcessingLocked) {
        setPaymentElementLoading(false);
        showResult('processing', { locked: true, booking_id: bookingId });
        if (placeOrderBtn) {
            placeOrderBtn.disabled = true;
            placeOrderBtn.textContent = 'Confirm payment';
        }
    } else if (checkReturnFrom3DS()) {
        setPaymentElementLoading(false);
    } else {
        // 与原版一致：在加载 Stripe 期间显示 “Loading payment form…” + 旋转动画，挂载完成后隐藏
        setPaymentElementLoading(true);
        // 等 Stripe.js 加载完成且布局 reflow 后再挂载（两帧），否则容器可能宽度为 0 导致不渲染
        var stripeLoadDeadline = Date.now() + 10000;
        function tryInitStripe() {
            if (typeof window.Stripe !== 'function') {
                if (Date.now() < stripeLoadDeadline) {
                    requestAnimationFrame(tryInitStripe);
                } else {
                    setPaymentElementLoading(false);
                    var c = document.getElementById('payment-element');
                    if (c) { c.innerHTML = '<p class="text-sm text-amber-700 p-3 bg-amber-50 rounded border border-amber-200">Payment form could not load. Please refresh or check your connection.</p>'; c.style.minHeight = '80px'; }
                    showMessage('Payment form could not load. Please refresh or check your connection.');
                }
                return;
            }
            requestAnimationFrame(function() {
                requestAnimationFrame(function() {
                    initStripe();
                });
            });
        }
        tryInitStripe();
    }
})();
