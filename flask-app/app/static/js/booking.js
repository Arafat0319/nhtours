/**
 * 多步骤报名表单 JavaScript
 * 处理：购买者信息 → 选择套餐 → 选择附加项 → 参与者信息 → 支付
 */

(function() {
    'use strict';

    /** 金额显示：整数不显示小数，有小数时显示（最多两位，去掉尾随零） */
    function formatMoneyAmount(num) {
        var n = typeof num === 'number' ? num : parseFloat(num);
        if (isNaN(n)) return '0';
        if (Math.abs(n - Math.round(n * 100) / 100) < 1e-9) return String(Math.round(n));
        var s = n.toFixed(2);
        return s.replace(/\.?0+$/, '');
    }

    /** 客户可见金额一律保留两位小数，避免被误认为多收（如 $39.00、$2285.50） */
    function formatCurrency(num) {
        var n = typeof num === 'number' ? num : parseFloat(num);
        if (isNaN(n)) return '0.00';
        return (Math.round(n * 100) / 100).toFixed(2);
    }

    function formatPlanDate(iso) {
        if (!iso) return '';
        var s = String(iso).substring(0, 10);
        if (s.length !== 10) return String(iso);
        var d = new Date(s + 'T12:00:00');
        if (isNaN(d.getTime())) return s;
        return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
    }

    // 全局状态
    let currentStep = 1;
    let bookingData = {
        buyer_info: {},
        packages: [],
        addons: [],
        participants: [],
        discount_code: null,
        discount_code_id: null,
        discount_amount: 0,
        payment_method: 'full',
        parental_waiver: null
    };

    // DOM 元素
    let stepContainers = [];
    let stepButtons = [];
    let nextButton, submitButton;
    let participantsContainer;
    let orderSummaryEl, totalAmountEl;
    let participantCount = 0;
    let embeddedPaymentSession = null;
    let embeddedPaymentSignature = null;
    let stripeInstance = null;
    let elementsInstance = null;
    let paymentElementInstance = null;
    let lastPaymentMethodId = null;
    let quoteInFlight = false;
    let lastQuote = null;
    let quoteTimer = null;

    // Trip 数据（从 window.tripData 获取）
    let tripData = window.tripData || {};

    /**
     * 将单个原生 select 替换为与 Package 一致的 Uiverse 下拉组件
     */
    function convertSelectToUiverse(selectEl) {
        if (!selectEl || selectEl.getAttribute('data-booking-uiverse') === 'true') return;
        var options = [];
        for (var i = 0; i < selectEl.options.length; i++) {
            var o = selectEl.options[i];
            // 跳过占位项（空 value / disabled / hidden），避免下拉里出现 “Select...”
            if (o.disabled || o.hidden) continue;
            if (!(o.value || '').trim()) continue;
            options.push({ value: o.value, text: o.text });
        }
        var selectedText = '';
        if (selectEl.value && selectEl.selectedIndex >= 0 && selectEl.options[selectEl.selectedIndex]) {
            selectedText = selectEl.options[selectEl.selectedIndex].text || '';
        }
        var wrap = document.createElement('div');
        wrap.className = 'booking-select-uiverse select';
        wrap.setAttribute('data-for-select', selectEl.name || '');
        var arrowSvg = '<svg xmlns="http://www.w3.org/2000/svg" height="1em" viewBox="0 0 512 512" class="arrow" aria-hidden="true"><path d="M233.4 406.6c12.5 12.5 32.8 12.5 45.3 0l192-192c12.5-12.5 12.5-32.8 0-45.3s-32.8-12.5-45.3 0L256 338.7 86.6 169.4c-12.5-12.5-32.8-12.5-45.3 0s-12.5 32.8 0 45.3l192 192z"></path></svg>';
        var optionsHtml = options.map(function(opt) {
            return '<div class="option" data-value="' + (opt.value || '').replace(/"/g, '&quot;') + '" role="option">' + (opt.text || '').replace(/</g, '&lt;') + '</div>';
        }).join('');
        wrap.innerHTML = '<div class="selected" tabindex="0" role="combobox" aria-expanded="false" aria-haspopup="listbox"><span class="selected-value">' + (selectedText || '').replace(/</g, '&lt;') + '</span>' + arrowSvg + '</div><div class="options" role="listbox">' + optionsHtml + '</div>';
        selectEl.setAttribute('data-booking-uiverse', 'true');
        selectEl.classList.add('booking-select-native-hidden');
        selectEl.parentNode.insertBefore(wrap, selectEl);
        wrap.appendChild(selectEl);
        var selectedVal = wrap.querySelector('.selected-value');
        var optionsDiv = wrap.querySelector('.options');
        var selectedDiv = wrap.querySelector('.selected');
        selectedDiv.addEventListener('click', function(e) {
            e.stopPropagation();
            var open = wrap.classList.toggle('is-open');
            selectedDiv.setAttribute('aria-expanded', open);
        });
        selectedDiv.addEventListener('keydown', function(e) {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                var open = wrap.classList.toggle('is-open');
                selectedDiv.setAttribute('aria-expanded', open);
            }
        });
        var filledBg = 'rgba(0, 102, 255, 0.1)';
        function updateSelectHasValue() {
            if (selectEl.value && selectEl.value.trim()) {
                wrap.classList.add('booking-select-has-value');
                if (selectedDiv) selectedDiv.style.setProperty('background-color', filledBg, 'important');
            } else {
                wrap.classList.remove('booking-select-has-value');
                if (selectedDiv) selectedDiv.style.removeProperty('background-color');
            }
        }
        updateSelectHasValue();
        optionsDiv.querySelectorAll('.option').forEach(function(optEl) {
            optEl.addEventListener('click', function(e) {
                e.stopPropagation();
                var val = this.getAttribute('data-value') || '';
                selectEl.value = val;
                selectedVal.textContent = this.textContent;
                updateSelectHasValue();
                wrap.classList.remove('is-open');
                selectedDiv.setAttribute('aria-expanded', 'false');
                selectEl.dispatchEvent(new Event('change', { bubbles: true }));
            });
        });
        document.addEventListener('click', function closeDropdown(e) {
            if (!wrap.contains(e.target)) {
                wrap.classList.remove('is-open');
                selectedDiv.setAttribute('aria-expanded', 'false');
            }
        });
    }

    /**
     * 弹窗内所有未转换的 select 转为 Uiverse 下拉（与 Package 一致）
     */
    function convertAllModalSelects() {
        var modal = document.getElementById('booking-modal');
        if (!modal) return;
        modal.querySelectorAll('select').forEach(function(sel) {
            if (sel.closest('.quantity-select-uiverse')) return;
            /* addon 数量用步进器，不把 addon 的 select 转成 Uiverse 下拉 */
            if (sel.classList.contains('addon-quantity') || sel.closest('.addon-card')) return;
            if (sel.getAttribute('data-booking-uiverse') !== 'true') convertSelectToUiverse(sel);
        });
    }

    /** 弹窗内任意文本类输入/文本框：有内容时加淡蓝背景（与下拉/日期一致），.fp-date 由日期逻辑单独处理 */
    function updateBookingInputFilled(el) {
        if (!el || (el.tagName !== 'INPUT' && el.tagName !== 'TEXTAREA')) return;
        if (el.classList && el.classList.contains('fp-date')) return;
        var hasValue = el.value && el.value.trim();
        if (hasValue) {
            el.classList.add('booking-input-filled');
            el.style.setProperty('background-color', 'rgba(0, 102, 255, 0.1)', 'important');
        } else {
            el.classList.remove('booking-input-filled');
            el.style.removeProperty('background-color');
        }
    }

    /** 弹窗内所有文本类输入刷新填完态（步骤切换、恢复数据、自动填充后调用） */
    function refreshAllBookingInputsFilled() {
        var modal = document.getElementById('booking-modal');
        if (!modal) return;
        modal.querySelectorAll('input[type="text"]:not(.fp-date), input[type="email"], input[type="tel"], textarea').forEach(updateBookingInputFilled);
    }

    /**
     * 初始化
     */
    function init() {
        // 确保 tripData 已从 window.tripData 获取
        tripData = window.tripData || {};
        console.log('init: tripData loaded', tripData);
        console.log('init: tripData.packages', tripData.packages);
        console.log('init: tripData.addons', tripData.addons);
        
        // 获取所有步骤容器
        stepContainers = document.querySelectorAll('.booking-step');
        stepButtons = document.querySelectorAll('.step-indicator');
        console.log('init: found', stepContainers.length, 'step containers');

        // 获取按钮
        nextButton = document.getElementById('nextBtn');
        submitButton = document.getElementById('submitBtn');
        participantsContainer = document.getElementById('participants-container');
        orderSummaryEl = document.getElementById('order-summary');
        totalAmountEl = document.getElementById('total-amount');
        
        console.log('init: DOM elements', {
            orderSummaryEl: !!orderSummaryEl,
            totalAmountEl: !!totalAmountEl,
            stepContainers: stepContainers.length
        });

        // 绑定事件
        if (nextButton) nextButton.addEventListener('click', handleNext);
        if (submitButton) submitButton.addEventListener('click', handleSubmit);
        document.querySelectorAll('.modal-step-tab').forEach(function(tab) {
            tab.addEventListener('click', function() {
                const targetStep = parseInt(this.getAttribute('data-step'), 10);
                if (targetStep < 1 || targetStep > stepContainers.length) return;
                if (targetStep === currentStep) return;
                // 仅在前进一步时校验当前步骤；退回任意前序步骤均不校验（能到当前页说明前面已填过）
                if (targetStep > currentStep && !validateCurrentStep()) {
                    return;
                }
                saveCurrentStepData();
                showStep(targetStep);
            });
        });

        // 折扣码应用按钮
        const applyDiscountBtn = document.getElementById('apply-discount-btn');
        if (applyDiscountBtn) {
            applyDiscountBtn.addEventListener('click', applyDiscountCode);
        }
        
        // 移除折扣码按钮
        const removeDiscountBtn = document.getElementById('remove-discount-btn');
        if (removeDiscountBtn) {
            removeDiscountBtn.addEventListener('click', removeDiscountCode);
        }
        
        // 弹窗内所有文本类输入：填完后淡蓝背景（委托，含姓名/邮箱/电话/YesNo 说明等；.fp-date 由日期逻辑处理）
        var bookingModal = document.getElementById('booking-modal');
        if (bookingModal) {
            ['input', 'change', 'blur'].forEach(function(ev) {
                bookingModal.addEventListener(ev, function(e) {
                    var t = e.target;
                    if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA') && !t.classList.contains('fp-date')) {
                        if (t.type === 'text' || t.type === 'email' || t.type === 'tel' || t.tagName === 'TEXTAREA') {
                            updateBookingInputFilled(t);
                        }
                    }
                });
            });
        }

        // 回车键应用折扣码
        const discountCodeInput = document.getElementById('discount-code-input');
        if (discountCodeInput) {
            discountCodeInput.addEventListener('keypress', function(e) {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    applyDiscountCode();
                }
            });
        }

        // 监听 package quantity 变化（input 或 select），更新卡片样式并同步 select -> hidden
        document.addEventListener('input', function(e) {
            if (e.target.matches('input.package-quantity')) {
                syncPackageQuantityFromInput(e.target);
            }
            if (e.target.matches('input.addon-quantity')) {
                const quantityInput = e.target;
                const quantity = parseInt(quantityInput.value) || 0;
                const addonCard = quantityInput.closest('.addon-card');
                if (addonCard) {
                    if (quantity > 0) addonCard.classList.add('selected');
                    else addonCard.classList.remove('selected');
                }
            }
            if (e.target.matches('select.addon-quantity')) {
                const quantitySelect = e.target;
                const quantity = parseInt(quantitySelect.value) || 0;
                const addonCard = quantitySelect.closest('.addon-card');
                if (addonCard) {
                    if (quantity > 0) addonCard.classList.add('selected');
                    else addonCard.classList.remove('selected');
                }
            }
        });
        document.addEventListener('change', function(e) {
            if (e.target.matches('select.package-quantity-select')) {
                const sel = e.target;
                const packageId = sel.getAttribute('data-package-id');
                const hidden = document.querySelector('input.package-quantity[data-package-id="' + packageId + '"]');
                if (hidden) {
                    hidden.value = sel.value;
                    syncPackageQuantityFromInput(hidden);
                    hidden.classList.remove('border-red-500', 'border-2');
                    hidden.style.borderColor = '';
                    hidden.style.borderWidth = '';
                }
                sel.classList.remove('border-red-500', 'border-2');
                sel.style.borderColor = '';
                sel.style.borderWidth = '';
                var step1 = document.querySelector('.booking-step[data-step="1"]');
                if (step1) savePackagesData(step1);
                updateParticipantCount();
                if (typeof updateOrderSummary === 'function') updateOrderSummary();
            }
            if (e.target.matches('input.package-pay-radio')) {
                var step1Pay = document.querySelector('.booking-step[data-step="1"]');
                if (step1Pay) savePackagesData(step1Pay);
                if (typeof updateOrderSummary === 'function') updateOrderSummary();
            }
            // Uiverse 数量单选：同步到 hidden、更新显示、移除错误态、触发订单逻辑
            if (e.target.matches('input.quantity-radio')) {
                var radio = e.target;
                var pid = radio.getAttribute('data-package-id');
                var hid = document.querySelector('input.package-quantity[data-package-id="' + pid + '"]');
                var uiverse = radio.closest('.quantity-select-uiverse');
                var val = radio.value;
                if (hid && uiverse) {
                    hid.value = val;
                    hid.classList.remove('border-red-500', 'border-2');
                    hid.style.borderColor = '';
                    hid.style.borderWidth = '';
                    uiverse.querySelector('.selected-value').textContent = val;
                    uiverse.classList.remove('quantity-error');
                    syncPackageQuantityFromInput(hid);
                    if (typeof returnQuantityOptionsToOwner === 'function') returnQuantityOptionsToOwner();
                    var step1 = document.querySelector('.booking-step[data-step="1"]');
                    if (step1) savePackagesData(step1);
                    updateParticipantCount();
                    if (typeof updateOrderSummary === 'function') updateOrderSummary();
                }
            }
        });

        function syncPackageQuantityFromInput(quantityInput) {
            const quantity = parseInt(quantityInput.value) || 0;
            const packageCard = quantityInput.closest('.package-card');
            if (packageCard) {
                if (quantity > 0) packageCard.classList.add('selected');
                else packageCard.classList.remove('selected');
            }
        }

        // Yes/No with details: 选择 Yes 时显示文本框（Participant 和 Buyer 共用）
        document.addEventListener('change', function(e) {
            if (e.target.matches('input.yesno-radio, input.participant-yesno-radio')) {
                const field = e.target.closest('.participant-yesno-field, .buyer-yesno-field, .participant-default-yesno');
                if (field) {
                    const detailsDiv = field.querySelector('.yesno-details');
                    const detailsInput = field.querySelector('.yesno-details input, input.participant-yesno-details-input');
                    if (detailsDiv) {
                        const isYes = e.target.value === 'yes';
                        detailsDiv.classList.toggle('hidden', !isYes);
                        if (detailsInput) detailsInput.required = isYes;
                    }
                }
            }
        });
        
        // 监听套餐和附加项变化，更新订单总结和参与者数量
        document.addEventListener('change', function(e) {
            if (e.target.matches('.addon-quantity')) {
                var quantity = parseInt(e.target.value) || 0;
                var addonCard = e.target.closest('.addon-card');
                if (addonCard) {
                    if (quantity > 0) addonCard.classList.add('selected');
                    else addonCard.classList.remove('selected');
                }
            }
            if (e.target.matches('input.package-quantity, .addon-quantity')) {
                // 如果是在步骤1（套餐），更新参与者数量并自动更新订单总结（含分期逾期计算）
                if (currentStep === 1) {
                    const step1Container = document.querySelector('.booking-step[data-step="1"]');
                    if (step1Container) {
                        savePackagesData(step1Container);
                        updateParticipantCount();
                        var hasAny = false;
                        step1Container.querySelectorAll('input.package-quantity').forEach(function(inp) {
                            if ((parseInt(inp.value, 10) || 0) > 0) hasAny = true;
                        });
                        if (hasAny && typeof clearStep1ValidationError === 'function') clearStep1ValidationError(step1Container);
                    }
                    if (typeof updateOrderSummary === 'function') updateOrderSummary();
                }
                // 如果在步骤3（附加项），保存 addon 数据并立即更新订单总结
                if (currentStep === 3) {
                    const step3Container = document.querySelector('.booking-step[data-step="3"]');
                    if (step3Container) {
                        saveAddonsData(step3Container);
                    }
                    if (typeof updateOrderSummary === 'function') updateOrderSummary();
                }
                // 如果在步骤4（支付），更新订单总结
                if (currentStep === 4) {
                    if (typeof updateOrderSummary === 'function') updateOrderSummary();
                }
            }
        });

        // 初始化第一步 - 确保步骤1正确显示
        currentStep = 1;
        showStep(1);
        
        // 初始化 package quantity：从 hidden 同步卡片选中态
        const packageQuantityInputs = document.querySelectorAll('input.package-quantity');
        packageQuantityInputs.forEach(input => {
            const quantity = parseInt(input.value) || 0;
            const packageCard = input.closest('.package-card');
            if (packageCard) {
                if (quantity > 0) packageCard.classList.add('selected');
                else packageCard.classList.remove('selected');
            }
        });

        /** Add-on 数量步进器（与 package card 同款风格）：+/- 更新 hidden 并触发 change */
        function initAddonSteppers() {
            var modal = document.getElementById('booking-modal');
            if (!modal) return;
            modal.querySelectorAll('.addon-stepper-wrapper').forEach(function(wrap) {
                if (wrap.getAttribute('data-addon-stepper-inited') === '1') return;
                wrap.setAttribute('data-addon-stepper-inited', '1');
                var addonId = wrap.getAttribute('data-addon-id');
                var maxQty = parseInt(wrap.getAttribute('data-max-qty'), 10) || 10;
                var hidden = wrap.querySelector('input.addon-quantity');
                var display = wrap.querySelector('.addon-qty-display');
                var minusBtn = wrap.querySelector('.addon-stepper-minus');
                var plusBtn = wrap.querySelector('.addon-stepper-plus');
                function setQty(n) {
                    n = Math.max(0, Math.min(maxQty, n));
                    if (hidden) hidden.value = String(n);
                    if (display) display.textContent = n;
                    var card = wrap.closest('.addon-card');
                    if (card) {
                        if (n > 0) card.classList.add('selected');
                        else card.classList.remove('selected');
                    }
                    if (hidden) hidden.dispatchEvent(new Event('change', { bubbles: true }));
                }
                if (minusBtn) minusBtn.addEventListener('click', function(e) {
                    e.preventDefault();
                    setQty((parseInt(hidden && hidden.value, 10) || 0) - 1);
                });
                if (plusBtn) plusBtn.addEventListener('click', function(e) {
                    e.preventDefault();
                    setQty((parseInt(hidden && hidden.value, 10) || 0) + 1);
                });
                if (hidden) {
                    var n = parseInt(hidden.value, 10) || 0;
                    if (display) display.textContent = n;
                }
            });
        }
        initAddonSteppers();

        // 将已挂到 body 的下拉移回原处
        var quantityDropdownCloseTimeout = null;
        function returnQuantityOptionsToOwner() {
            if (quantityDropdownCloseTimeout) clearTimeout(quantityDropdownCloseTimeout);
            quantityDropdownCloseTimeout = null;
            document.querySelectorAll('.quantity-options-portal').forEach(function(op) {
                var wrap = op._ownerWrap;
                if (wrap && op.parentNode !== wrap) {
                    wrap.appendChild(op);
                    op.classList.remove('quantity-options-portal');
                    op.style.cssText = '';
                }
                if (wrap) wrap.classList.remove('is-open');
            });
        }
        function scheduleQuantityDropdownClose() {
            if (quantityDropdownCloseTimeout) clearTimeout(quantityDropdownCloseTimeout);
            quantityDropdownCloseTimeout = setTimeout(returnQuantityOptionsToOwner, 150);
        }
        function openQuantityDropdown(uiverse) {
            var opts = uiverse.querySelector('.options');
            if (!opts || opts.classList.contains('quantity-options-portal')) return;
            var rect = uiverse.getBoundingClientRect();
            var w = Math.max(96, rect.width);
            opts._ownerWrap = uiverse;
            document.body.appendChild(opts);
            opts.classList.add('quantity-options-portal');
            opts.style.position = 'fixed';
            opts.style.left = (rect.right - w) + 'px';
            opts.style.top = rect.bottom + 'px';
            opts.style.width = w + 'px';
            opts.style.maxHeight = 'min(220px, 45vh)';
            opts.style.opacity = '1';
            opts.style.pointerEvents = 'auto';
            opts.style.zIndex = '10001';
            uiverse.classList.add('is-open');
            if (!opts._portalListenersAttached) {
                opts._portalListenersAttached = true;
                opts.addEventListener('mouseenter', function() { if (quantityDropdownCloseTimeout) clearTimeout(quantityDropdownCloseTimeout); quantityDropdownCloseTimeout = null; });
                opts.addEventListener('mouseleave', function(ev) {
                    if (ev.relatedTarget && opts._ownerWrap && opts._ownerWrap.contains(ev.relatedTarget)) return;
                    scheduleQuantityDropdownClose();
                });
            }
        }
        // Uiverse 数量下拉：初始化；点击或 hover 打开时都挂到 body 防溢出
        document.querySelectorAll('.quantity-select-uiverse').forEach(function(el) {
            var checked = el.querySelector('.options input[type="radio"]:checked');
            var valEl = el.querySelector('.selected-value');
            if (checked && valEl) valEl.textContent = checked.value;
            el.addEventListener('mouseenter', function(ev) {
                if (quantityDropdownCloseTimeout) clearTimeout(quantityDropdownCloseTimeout);
                quantityDropdownCloseTimeout = null;
                var opts = el.querySelector('.options');
                if (opts && opts.parentNode === el) openQuantityDropdown(el);
            });
            el.addEventListener('mouseleave', function(ev) {
                var portal = document.querySelector('.quantity-options-portal');
                if (ev.relatedTarget && portal && portal.contains(ev.relatedTarget)) return;
                scheduleQuantityDropdownClose();
            });
        });
        document.addEventListener('click', function(e) {
            var uiverse = e.target.closest('.quantity-select-uiverse');
            if (e.target.closest('.quantity-select-uiverse .selected')) {
                returnQuantityOptionsToOwner();
                if (uiverse) {
                    var wasOpen = uiverse.classList.contains('is-open');
                    uiverse.classList.toggle('is-open');
                    if (!wasOpen && uiverse.classList.contains('is-open')) openQuantityDropdown(uiverse);
                }
                return;
            }
            if (!e.target.closest('.quantity-select-uiverse .options')) {
                returnQuantityOptionsToOwner();
            }
        });
        var modalEl = document.getElementById('booking-modal');
        var modalScrollEl = document.getElementById('booking-modal-scroll-viewport') || modalEl;
        if (modalScrollEl) {
            modalScrollEl.addEventListener('scroll', function() { if (typeof returnQuantityOptionsToOwner === 'function') returnQuantityOptionsToOwner(); }, true);
        }

        // 初始化 addon quantity 状态，更新卡片样式（支持 input 或 select）
        const addonQuantityEls = document.querySelectorAll('.addon-quantity');
        addonQuantityEls.forEach(function(el) {
            const quantity = parseInt(el.value) || 0;
            const addonCard = el.closest('.addon-card');
            if (addonCard) {
                if (quantity > 0) addonCard.classList.add('selected');
                else addonCard.classList.remove('selected');
            }
        });
        
        // 强制设置按钮显示状态（使用setTimeout确保DOM完全加载）
        setTimeout(function() {
            if (nextButton) {
                nextButton.style.display = 'flex';
                nextButton.style.visibility = 'visible';
                nextButton.style.opacity = '1';
                nextButton.classList.remove('hidden');
                // 强制显示
                nextButton.setAttribute('style', 'display: flex !important; visibility: visible !important; opacity: 1 !important;');
            }
            if (submitButton) {
                submitButton.style.display = 'none';
                submitButton.classList.add('hidden');
            }
            // 延迟调用updateStepButtons，确保样式已应用
            setTimeout(function() {
                updateStepButtons();
            }, 50);
        }, 100);
        
        // 强制更新步骤1的显示状态
        const step1Indicator = document.querySelector('.step-indicator[data-step="1"]');
        if (step1Indicator) {
            step1Indicator.classList.add('active');
            step1Indicator.classList.remove('completed');
        }

        // 付款结果区：Close / Try Again
        var resultCloseBtn = document.getElementById('booking-result-close-btn');
        var resultProcessingCloseBtn = document.getElementById('booking-result-processing-close-btn');
        var resultTryAgainBtn = document.getElementById('booking-result-try-again-btn');
        function closeResultModal() {
            prepareNewBooking({ keepFormData: false });
            var m = document.getElementById('booking-modal');
            if (m) {
                m.classList.add('hidden');
                document.documentElement.style.overflow = '';
                document.body.style.overflow = '';
            }
        }
        if (resultCloseBtn) {
            resultCloseBtn.addEventListener('click', closeResultModal);
        }
        if (resultProcessingCloseBtn) {
            resultProcessingCloseBtn.addEventListener('click', closeResultModal);
        }
        if (resultTryAgainBtn) {
            resultTryAgainBtn.addEventListener('click', function() {
                // 失败重试：保留已填表单，只清支付会话并回到付款步
                prepareNewBooking({ keepFormData: true, goToPayment: true });
            });
        }

        // 弹窗内所有下拉框改为与 Package 一致的 Uiverse 组件
        convertAllModalSelects();

        // 3DS 返回：URL 带 modal=1&payment_intent_id=xxx 时自动打开弹窗并显示处理中 → 轮询结果
        (function checkPaymentReturnUrl() {
            var params = new URLSearchParams(window.location.search);
            if (params.get('modal') !== '1') return;
            var pi = params.get('payment_intent_id');
            if (!pi) return;
            var m = document.getElementById('booking-modal');
            if (!m) return;
            m.classList.remove('hidden');
            document.documentElement.style.overflow = 'hidden';
            document.body.style.overflow = 'hidden';
            showBookingModalResult('loading');
            pollPaymentStatusThenShowResult(pi);
            try {
                history.replaceState({}, '', window.location.pathname + (window.location.hash || ''));
            } catch (e) {}
        })();

        // DEBUG：真实行程页预览付款成功 / 失败弹窗（服务端仅 debug 时打 data-preview-*）
        (function previewBookingResultModal() {
            var m = document.getElementById('booking-modal');
            if (!m) return;
            var previewFail = m.getAttribute('data-preview-booking-failure') === '1';
            var previewOk = m.getAttribute('data-preview-booking-success') === '1';
            if (!previewFail && !previewOk) return;
            m.classList.remove('hidden');
            document.documentElement.style.overflow = 'hidden';
            document.body.style.overflow = 'hidden';
            if (previewFail) {
                showBookingModalResult('failure', {
                    message: 'Your card has insufficient funds.'
                });
            } else {
                // booking_id 须为真值，否则收据按钮会被隐藏（与真实成功态同一分支）
                showBookingModalResult('success', {
                    booking_id: 999001,
                    receipt_url: '#'
                });
            }
            try {
                history.replaceState({}, '', window.location.pathname + (window.location.hash || ''));
            } catch (e) {}
        })();

        // 桌面端弹窗内容区高度取左右最大：resize 时重新同步
        var syncMinHeightTimer = null;
        window.addEventListener('resize', function() {
            if (syncMinHeightTimer) clearTimeout(syncMinHeightTimer);
            syncMinHeightTimer = setTimeout(function() {
                syncMinHeightTimer = null;
                syncBookingModalBodyMinHeight();
            }, 150);
        });
    }

    /**
     * 显示指定步骤
     */
    function showStep(step) {
        // 隐藏所有步骤
        stepContainers.forEach((container, index) => {
            if (index + 1 === step) {
                container.classList.remove('hidden');
            } else {
                container.classList.add('hidden');
            }
        });

        // 更新步骤指示器
        stepButtons.forEach((button, index) => {
            const stepNum = index + 1;
            const circle = button.querySelector('.step-circle'); // 步骤圆圈
            const stepLabel = button.querySelector('.step-label'); // 标签
            const stepNumber = button.querySelector('.step-number');
            const stepCheck = button.querySelector('.step-check');
            const stepConnector = document.querySelector(`.step-connector[data-step="${stepNum}"]`);
            const stepProgress = stepConnector ? stepConnector.querySelector('.step-progress') : null;
            
            if (stepNum < step) {
                // 已完成
                button.classList.add('completed');
                button.classList.remove('active');
                if (circle) {
                    circle.style.background = '#d59961';
                    circle.style.color = 'white';
                    circle.style.boxShadow = 'none';
                }
                if (stepLabel) stepLabel.style.color = '#1f2937';
                if (stepNumber) stepNumber.style.display = 'none';
                if (stepCheck) stepCheck.classList.remove('hidden');
                if (stepProgress) stepProgress.style.width = '100%';
            } else if (stepNum === step) {
                // 当前步骤
                button.classList.add('active');
                button.classList.remove('completed');
                if (circle) {
                    circle.style.background = '#d59961';
                    circle.style.color = 'white';
                    circle.style.boxShadow = '0 2px 8px rgba(213, 153, 97, 0.25)';
                }
                if (stepLabel) stepLabel.style.color = '#1f2937';
                if (stepNumber) stepNumber.style.display = 'block';
                if (stepCheck) stepCheck.classList.add('hidden');
                if (stepProgress) stepProgress.style.width = '0%';
            } else {
                // 未完成
                button.classList.remove('active', 'completed');
                if (circle) {
                    circle.style.background = '#f3f4f6';
                    circle.style.color = '#6b7280';
                    circle.style.boxShadow = 'none';
                }
                if (stepLabel) stepLabel.style.color = '#9ca3af';
                if (stepNumber) stepNumber.style.display = 'block';
                if (stepCheck) stepCheck.classList.add('hidden');
                if (stepProgress) stepProgress.style.width = '0%';
            }
        });

        currentStep = step;
        updateStepButtons();

        // 更新 WeTravel 风格步骤 Tab（深色头下仅文字色：当前白、其余灰）
        document.querySelectorAll('.modal-step-tab').forEach(function(tab) {
            const tabStep = parseInt(tab.getAttribute('data-step'), 10);
            tab.style.color = (tabStep === step) ? '#1f2937' : '#9ca3af';
            tab.setAttribute('aria-selected', tabStep === step ? 'true' : 'false');
        });

        if (step === 4) {
            initEmbeddedPaymentSession();
        } else {
            resetEmbeddedPaymentSession();
        }
        
        // 如果到了第2步（参与者信息），根据package数量生成表单，并转换下拉与日期
        if (step === 2) {
            updateParticipantCount();
            setTimeout(function() {
                convertAllModalSelects();
                if (typeof window.initFlatpickrOnDates === 'function') window.initFlatpickrOnDates();
                refreshAllBookingInputsFilled();
                setTimeout(refreshAllBookingInputsFilled, 300);
            }, 0);
        }
        // 步骤 3（Add-ons）显示时初始化 addon 步进器并刷新填完态
        if (step === 3) {
            setTimeout(function() {
                if (typeof initAddonSteppers === 'function') initAddonSteppers();
                refreshAllBookingInputsFilled();
                setTimeout(refreshAllBookingInputsFilled, 300);
            }, 0);
        }
        
        // 每次显示步骤时刷新订单总价（自动计算 Trip Total / Due at Booking，含分期逾期）
        if (step === 1 || step === 2 || step === 3) {
            setTimeout(function() { if (typeof updateOrderSummary === 'function') updateOrderSummary(); }, 0);
        }
        // 如果到了第4步（支付），保存数据并更新订单总结
        if (step === 4) {
            saveAllStepsData();
            setTimeout(() => {
                updateOrderSummary();
            }, 150);
        }

        // 根据当前步骤左右列高度动态同步 body 高度，避免 Add-ons 等短步骤底部大块空白
        requestAnimationFrame(function() {
            syncBookingModalBodyMinHeight();
        });
    }

    /**
     * 更新按钮状态
     */
    function updateStepButtons() {
        if (nextButton) {
            const isLastStep = currentStep === stepContainers.length;
            // 最后一步仍显示同一按钮，文案改为 Confirm Booking；其他步骤为 Continue
            nextButton.style.display = 'flex';
            nextButton.style.visibility = 'visible';
            nextButton.classList.remove('hidden');
            nextButton.textContent = isLastStep ? 'Confirm Booking' : 'Continue';
        }

        // 只保留一个按钮：不再显示单独的 Confirm 按钮
        if (submitButton) {
            submitButton.style.display = 'none';
            submitButton.classList.add('hidden');
        }
    }

    /**
     * 处理下一步
     */
    function handleNext(e) {
        e.preventDefault();
        
        // 验证当前步骤
        if (!validateCurrentStep()) {
            return;
        }

        // 保存当前步骤数据（在切换步骤前保存）
        saveCurrentStepData();
        
        console.log('handleNext: saved current step data, bookingData:', bookingData);

        // 最后一步（Payment）：同一按钮执行提交
        if (currentStep === stepContainers.length) {
            handleSubmit(e);
            return;
        }

        // 显示下一步
        if (currentStep < stepContainers.length) {
            let nextStep = currentStep + 1;
            // 无 add-ons 时跳过步骤3
            if (nextStep === 3 && (!tripData.hasAddons || !(tripData.addons && tripData.addons.length))) {
                nextStep = 4;
            }
            showStep(nextStep);
            
            // 如果下一步是步骤4（支付），确保所有数据都已保存
            if (nextStep === 4) {
                // 再次保存所有步骤数据，确保数据完整
                setTimeout(() => {
                    saveAllStepsData();
                    updateOrderSummary();
                }, 200);
            }
        }
    }

    /**
     * 清除步骤1「未选套餐」的红色提示（错误信息 + 卡片边框）
     */
    function clearStep1ValidationError(step1Container) {
        if (!step1Container) return;
        step1Container.classList.remove('step1-validation-error');
        step1Container.querySelectorAll('.package-card').forEach(function(card) {
            card.classList.remove('package-card-validation-error');
        });
        step1Container.querySelectorAll('input.package-quantity').forEach(function(input) {
            input.classList.remove('border-red-500', 'border-2');
            input.style.borderColor = '';
            input.style.borderWidth = '';
            var uiverse = input.closest('.package-card') && input.closest('.package-card').querySelector('.quantity-select-uiverse');
            if (uiverse) uiverse.classList.remove('quantity-error');
        });
        var step1ErrorMsg = document.getElementById('step1-error-message');
        if (step1ErrorMsg) step1ErrorMsg.classList.add('hidden');
    }

    /**
     * 验证当前步骤
     */
    function validateCurrentStep() {
        const currentContainer = stepContainers[currentStep - 1];
        if (!currentContainer) {
            console.error('Current container not found');
            return false;
        }
        
        const requiredFields = currentContainer.querySelectorAll('[required]');
        let isValid = true;
        const invalidFields = [];

        requiredFields.forEach(field => {
            // 检查不同类型的字段
            let isEmpty = false;
            if (field.type === 'checkbox' || field.type === 'radio') {
                isEmpty = !field.checked;
            } else if (field.tagName === 'SELECT') {
                isEmpty = !field.value || field.value === '';
            } else {
                isEmpty = !field.value || !field.value.trim();
            }
            
            if (isEmpty) {
                // 添加错误样式
                field.classList.add('border-red-500');
                field.classList.add('border-2');
                field.style.borderColor = '#ef4444';
                field.style.borderWidth = '2px';
                // 必填下拉：可见的是 Uiverse 的 .selected，给包装加错误类以显示红框
                var uiverseWrap = field.closest('.booking-select-uiverse');
                if (uiverseWrap) uiverseWrap.classList.add('booking-select-validation-error');
                
                // 添加错误提示 - 在输入框后面插入
                const fieldContainer = field.closest('.flex.flex-col');
                if (fieldContainer) {
                    // 检查是否已经存在错误提示
                    let errorMsg = fieldContainer.querySelector('.error-message');
                    if (!errorMsg) {
                        errorMsg = document.createElement('span');
                        errorMsg.className = 'error-message text-red-500 text-xs mt-1 block';
                        errorMsg.textContent = 'This field is required';
                        // 在输入框后面插入错误提示（使用 insertAfter 逻辑）
                        if (field.nextSibling) {
                            field.parentElement.insertBefore(errorMsg, field.nextSibling);
                        } else {
                            field.parentElement.appendChild(errorMsg);
                        }
                    }
                }
                
                invalidFields.push(field);
                isValid = false;
                
                // 滚动到第一个错误字段
                if (invalidFields.length === 1) {
                    var scrollEl = uiverseWrap ? uiverseWrap : field;
                    scrollEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
                    if (uiverseWrap) uiverseWrap.querySelector('.selected').focus(); else field.focus();
                }
            } else {
                // 移除错误样式
                field.classList.remove('border-red-500');
                field.classList.remove('border-2');
                field.style.borderColor = '';
                field.style.borderWidth = '';
                var uiverseWrap = field.closest('.booking-select-uiverse');
                if (uiverseWrap) uiverseWrap.classList.remove('booking-select-validation-error');
                
                // 移除错误提示 - 从字段容器中查找并移除
                const fieldContainer = field.closest('.flex.flex-col');
                if (fieldContainer) {
                    const errorMsg = fieldContainer.querySelector('.error-message');
                    if (errorMsg) {
                        errorMsg.remove();
                    }
                }
            }
        });
        
        // 监听输入事件，实时移除错误样式
        invalidFields.forEach(field => {
            const clearError = () => {
                var isEmpty = false;
                if (field.tagName === 'SELECT') {
                    isEmpty = !field.value || field.value === '';
                } else {
                    isEmpty = !field.value || !field.value.trim();
                }
                if (isEmpty) return;
                field.classList.remove('border-red-500');
                field.classList.remove('border-2');
                field.style.borderColor = '';
                field.style.borderWidth = '';
                var wrap = field.closest('.booking-select-uiverse');
                if (wrap) wrap.classList.remove('booking-select-validation-error');
                const errorMsg = field.closest('.flex.flex-col')?.querySelector('.error-message');
                if (errorMsg) errorMsg.remove();
                field.removeEventListener('input', clearError);
                field.removeEventListener('change', clearError);
            };
            field.addEventListener('input', clearError);
            field.addEventListener('change', clearError);
        });

        // 特殊验证：步骤1（套餐选择）- 检查是否有quantity > 0的package
        if (currentStep === 1) {
            const packageQuantityInputs = currentContainer.querySelectorAll('input.package-quantity');
            let hasSelectedPackage = false;
            packageQuantityInputs.forEach(input => {
                const quantity = parseInt(input.value) || 0;
                if (quantity > 0) {
                    hasSelectedPackage = true;
                }
            });
            if (!hasSelectedPackage) {
                // 高亮套餐数量控件（Uiverse 下拉）
                packageQuantityInputs.forEach(input => {
                    input.classList.add('border-red-500', 'border-2');
                    input.style.borderColor = '#ef4444';
                    var card = input.closest('.package-card');
                    var uiverse = card ? card.querySelector('.quantity-select-uiverse') : null;
                    if (uiverse) uiverse.classList.add('quantity-error');
                    if (card) card.classList.add('package-card-validation-error');
                });
                // 显示「请至少选择一个套餐」提示（实验弹窗）
                var step1ErrorMsg = document.getElementById('step1-error-message');
                if (step1ErrorMsg) {
                    step1ErrorMsg.classList.remove('hidden');
                }
                currentContainer.classList.add('step1-validation-error');
                isValid = false;
            } else {
                clearStep1ValidationError(currentContainer);
            }
        }
        
        // 步骤3（附加项）不需要验证，可以跳过
        // 步骤2（参与者信息）的验证
        if (currentStep === 2) {
            const participantForms = currentContainer.querySelectorAll('.participant-form');
            const participantFormsWithInvalidFields = new Set();
            participantForms.forEach((form, index) => {
                const requiredFields = form.querySelectorAll('[required]');
                requiredFields.forEach(field => {
                    let isEmpty = false;
                    if (field.tagName === 'SELECT') {
                        isEmpty = !field.value || field.value === '';
                    } else {
                        isEmpty = !field.value || !field.value.trim();
                    }
                    
                    if (isEmpty) {
                        field.classList.add('border-red-500');
                        field.classList.add('border-2');
                        field.style.borderColor = '#ef4444';
                        field.style.borderWidth = '2px';
                        
                        // 添加错误提示 - 在输入框后面插入
                        const fieldContainer = field.closest('.flex.flex-col') || field.closest('.participant-form');
                        if (fieldContainer) {
                            let errorMsg = fieldContainer.querySelector('.error-message');
                            if (!errorMsg) {
                                errorMsg = document.createElement('span');
                                errorMsg.className = 'error-message text-red-500 text-xs mt-1 block';
                                errorMsg.textContent = 'This field is required';
                                // 在输入框后面插入错误提示
                                if (field.nextSibling) {
                                    field.parentElement.insertBefore(errorMsg, field.nextSibling);
                                } else {
                                    field.parentElement.appendChild(errorMsg);
                                }
                            }
                        }
                        
                        participantFormsWithInvalidFields.add(form);
                        isValid = false;
                    }
                });
            });
            // 有未填项且位于折叠的 Participant 卡片内时：自动展开该卡片并提示
            if (participantFormsWithInvalidFields.size > 0) {
                const participantsWrap = currentContainer.querySelector('#participants-container');
                let hintEl = participantsWrap && participantsWrap.querySelector('.participant-step-validation-hint');
                if (!hintEl && participantsWrap) {
                    hintEl = document.createElement('p');
                    hintEl.className = 'participant-step-validation-hint text-sm text-red-600 mb-3';
                    hintEl.setAttribute('role', 'alert');
                    participantsWrap.insertBefore(hintEl, participantsWrap.firstChild);
                }
                if (hintEl) {
                    hintEl.textContent = 'Please complete the required fields in the section(s) below.';
                    hintEl.classList.remove('hidden');
                }
                participantFormsWithInvalidFields.forEach(function(form) {
                    const headerEl = form.querySelector('.participant-section-header');
                    const bodyEl = form.querySelector('.participant-form-body');
                    if (headerEl && bodyEl && headerEl.getAttribute('aria-expanded') !== 'true') {
                        headerEl.setAttribute('aria-expanded', 'true');
                        bodyEl.style.display = '';
                        var chevron = headerEl.querySelector('.participant-chevron');
                        if (chevron) chevron.style.transform = 'rotate(0deg)';
                        form.classList.add('participant-form-validation-error');
                    }
                });
                var firstInvalidForm = participantFormsWithInvalidFields.values().next().value;
                if (firstInvalidForm) {
                    firstInvalidForm.scrollIntoView({ behavior: 'smooth', block: 'start' });
                }
            } else {
                var wrap = currentContainer.querySelector('#participants-container');
                var hint = wrap && wrap.querySelector('.participant-step-validation-hint');
                if (hint) hint.classList.add('hidden');
                currentContainer.querySelectorAll('.participant-form-validation-error').forEach(function(el) {
                    el.classList.remove('participant-form-validation-error');
                });
            }
        }
        
        // 步骤4（支付）需要验证参与者信息
        if (currentStep === 4) {
            const participants = bookingData.participants || [];
            if (participants.length === 0) {
                // 不显示 alert，只阻止继续
                isValid = false;
            }
        }

        // 格式校验（邮箱/电话/姓名/生日/邮编）：必填非空通过后再查格式
        if (!validateFieldFormats(currentContainer, invalidFields)) {
            isValid = false;
        }

        return isValid;
    }

    /**
     * 字段格式规则（与后端 booking_validation 对齐）
     */
    var BOOKING_FIELD_RE = {
        email: /^[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}$/i,
        phoneAllowed: /^[\d\s+\-().]+$/,
        name: /^[\w\s\-'·.\u00C0-\u024F\u0400-\u04FF\u4E00-\u9FFF\u3040-\u30FF\uAC00-\uD7AF]{1,64}$/u,
        zip: /^[A-Z0-9\s\-]{3,12}$/i,
        dob: /^\d{4}-\d{2}-\d{2}$/
    };

    function bookingFormatMessage(kind) {
        if (kind === 'email') return 'Please enter a valid email address.';
        if (kind === 'phone') return 'Please enter a valid phone number.';
        if (kind === 'name') return 'Please enter a valid name.';
        if (kind === 'dob') return 'Please enter a valid date of birth.';
        if (kind === 'zip') return 'Please enter a valid ZIP/postal code.';
        return 'Invalid value.';
    }

    function checkBookingFormat(kind, value) {
        var s = (value || '').trim();
        if (!s) return true;
        if (kind === 'email') return BOOKING_FIELD_RE.email.test(s);
        if (kind === 'phone') {
            if (!BOOKING_FIELD_RE.phoneAllowed.test(s)) return false;
            var digits = s.replace(/\D/g, '');
            return digits.length >= 7 && digits.length <= 15;
        }
        if (kind === 'name') return BOOKING_FIELD_RE.name.test(s);
        if (kind === 'zip') return BOOKING_FIELD_RE.zip.test(s);
        if (kind === 'dob') {
            if (!BOOKING_FIELD_RE.dob.test(s)) return false;
            var parts = s.split('-');
            var y = parseInt(parts[0], 10);
            var m = parseInt(parts[1], 10);
            var d = parseInt(parts[2], 10);
            var dt = new Date(y, m - 1, d);
            if (dt.getFullYear() !== y || dt.getMonth() !== m - 1 || dt.getDate() !== d) return false;
            var today = new Date();
            today.setHours(0, 0, 0, 0);
            if (dt > today) return false;
            var maxAge = new Date(today.getFullYear() - 120, today.getMonth(), today.getDate());
            if (dt < maxAge) return false;
            return true;
        }
        return true;
    }

    function inferFormatKind(field) {
        var name = (field.getAttribute('name') || '').toLowerCase();
        var type = (field.getAttribute('type') || '').toLowerCase();
        var qtype = (field.getAttribute('data-question-type') || '').toLowerCase();
        if (qtype === 'email' || type === 'email' || name.indexOf('email') !== -1) return 'email';
        if (qtype === 'phone' || qtype === 'tel' || type === 'tel' || name.indexOf('phone') !== -1) return 'phone';
        if (qtype === 'date' || qtype === 'dob' || name.indexOf('_dob') !== -1 || name.indexOf('date_of_birth') !== -1) return 'dob';
        if (name.indexOf('zip') !== -1 || name.indexOf('postal') !== -1) return 'zip';
        if (
            name.indexOf('first_name') !== -1 ||
            name.indexOf('last_name') !== -1 ||
            name.indexOf('middle_name') !== -1 ||
            name === 'buyer_emergency_contact_name' ||
            /emergency_contact_name/.test(name)
        ) return 'name';
        return null;
    }

    function markFormatError(field, message, invalidFields) {
        field.classList.add('border-red-500', 'border-2');
        field.style.borderColor = '#ef4444';
        field.style.borderWidth = '2px';
        var fieldContainer = field.closest('.flex.flex-col') || field.parentElement;
        if (fieldContainer) {
            var errorMsg = fieldContainer.querySelector('.error-message');
            if (!errorMsg) {
                errorMsg = document.createElement('span');
                errorMsg.className = 'error-message text-red-500 text-xs mt-1 block';
                if (field.nextSibling) {
                    field.parentElement.insertBefore(errorMsg, field.nextSibling);
                } else {
                    field.parentElement.appendChild(errorMsg);
                }
            }
            errorMsg.textContent = message;
        }
        if (invalidFields && invalidFields.indexOf(field) === -1) {
            invalidFields.push(field);
            if (invalidFields.length === 1) {
                field.scrollIntoView({ behavior: 'smooth', block: 'center' });
                try { field.focus(); } catch (e) { /* ignore */ }
            }
        }
        var clearError = function() {
            if (!checkBookingFormat(inferFormatKind(field), field.value) && (field.value || '').trim()) return;
            field.classList.remove('border-red-500', 'border-2');
            field.style.borderColor = '';
            field.style.borderWidth = '';
            var msg = field.closest('.flex.flex-col')?.querySelector('.error-message');
            if (msg) msg.remove();
            field.removeEventListener('input', clearError);
            field.removeEventListener('change', clearError);
        };
        field.addEventListener('input', clearError);
        field.addEventListener('change', clearError);
    }

    function validateFieldFormats(container, invalidFields) {
        if (!container) return true;
        var ok = true;
        var fields = container.querySelectorAll('input, textarea, select');
        fields.forEach(function(field) {
            if (field.disabled || field.type === 'hidden' || field.type === 'checkbox' || field.type === 'radio' || field.type === 'file') return;
            var kind = inferFormatKind(field);
            if (!kind) return;
            var val = field.value || '';
            if (!val.trim()) return;
            if (!checkBookingFormat(kind, val)) {
                markFormatError(field, bookingFormatMessage(kind), invalidFields);
                ok = false;
            }
        });
        // Custom question types via data attribute on generated inputs
        container.querySelectorAll('[data-question-type]').forEach(function(field) {
            var kind = inferFormatKind(field);
            if (!kind) return;
            var val = field.value || '';
            if (!val.trim()) return;
            if (!checkBookingFormat(kind, val)) {
                markFormatError(field, bookingFormatMessage(kind), invalidFields);
                ok = false;
            }
        });
        return ok;
    }

    /**
     * 保存当前步骤数据
     */
    function saveCurrentStepData() {
        const currentContainer = stepContainers[currentStep - 1];
        if (!currentContainer) return;

        switch (currentStep) {
            case 1: // 套餐选择
                savePackagesData(currentContainer);
                break;
            case 2: // 参与者信息（含购买者）
                saveBuyerInfoData(currentContainer);
                saveParticipantsData(currentContainer);
                break;
            case 3: // 附加项选择
                saveAddonsData(currentContainer);
                break;
            case 4: // 支付总结
                break;
        }
    }
    
    /**
     * 保存所有步骤的数据（用于在显示步骤4支付前确保数据完整）
     */
    function saveAllStepsData() {
        console.log('saveAllStepsData: saving all steps data');
        
        // 步骤1：套餐
        const step1Container = stepContainers[0] || document.querySelector('.booking-step[data-step="1"]');
        if (step1Container) savePackagesData(step1Container);
        
        // 步骤2：参与者（含购买者）
        const step2Container = stepContainers[1] || document.querySelector('.booking-step[data-step="2"]');
        if (step2Container) {
            saveBuyerInfoData(step2Container);
            saveParticipantsData(step2Container);
        }
        
        // 步骤3：附加项
        const step3Container = stepContainers[2] || document.querySelector('.booking-step[data-step="3"]');
        if (step3Container) saveAddonsData(step3Container);
        
        console.log('saveAllStepsData: final bookingData', bookingData);
    }

    /**
     * Resolve payment_plan_type for a package from DOM + tripData config.
     * enabled + allow_full_payment (default true) → customer radio; else forced.
     */
    function resolvePaymentPlanTypeForPackage(packageId) {
        const packageData = (tripData.packages || []).find(function(p) {
            return Number(p.id) === Number(packageId);
        });
        const ppc = packageData && packageData.payment_plan_config;
        if (!ppc || !ppc.enabled) {
            return 'full';
        }
        if (ppc.allow_full_payment === false) {
            return 'deposit_installment';
        }
        const card = document.querySelector('.package-card[data-package-id="' + packageId + '"]');
        if (card) {
            const checked = card.querySelector('input.package-pay-radio[type="radio"]:checked');
            if (checked && checked.value) {
                return checked.value;
            }
            const hidden = card.querySelector('input.package-pay-radio[type="hidden"]');
            if (hidden && hidden.value) {
                return hidden.value;
            }
        }
        return 'full';
    }

    /**
     * 保存套餐数据
     */
    function savePackagesData(container) {
        if (!container) {
            console.warn('savePackagesData: container is null');
            return;
        }
        
        bookingData.packages = [];
        // 即使容器被隐藏，querySelectorAll 仍然可以工作
        const packageQuantityInputs = container.querySelectorAll('input.package-quantity');
        
        console.log('savePackagesData: found', packageQuantityInputs.length, 'package inputs');
        
        packageQuantityInputs.forEach(input => {
            const packageId = parseInt(input.getAttribute('data-package-id'));
            const quantity = parseInt(input.value) || 0;
            
            console.log('Package input:', { packageId, quantity, value: input.value });
            
            // 只保存数量大于0的套餐
            if (quantity > 0 && packageId) {
                const payment_plan_type = resolvePaymentPlanTypeForPackage(packageId);
                console.log(`Package ${packageId} payment_plan_type=${payment_plan_type}`);
                
                bookingData.packages.push({
                    package_id: packageId,
                    quantity: quantity,
                    payment_plan_type: payment_plan_type
                });
            }
        });
        
        console.log('savePackagesData: saved packages', bookingData.packages);
        
        // 更新参与者数量（根据套餐数量）
        updateParticipantCount();
        
        // 如果当前在步骤4（支付），更新订单总结
        if (currentStep === 4) {
            updateOrderSummary();
        }
    }

    /**
     * 保存附加项数据
     */
    function saveAddonsData(container) {
        if (!container) {
            console.warn('saveAddonsData: container is null');
            return;
        }
        
        bookingData.addons = [];
        const addonQuantityEls = container.querySelectorAll('.addon-quantity');
        
        addonQuantityEls.forEach(function(el) {
            const addonId = parseInt(el.getAttribute('data-addon-id'));
            const quantity = parseInt(el.value) || 0;
            
            // 只保存数量大于0的附加项
            if (quantity > 0 && addonId) {
                bookingData.addons.push({
                    addon_id: addonId,
                    package_id: null,
                    participant_id: null,
                    quantity: quantity
                });
            }
        });
        
        // 如果当前在步骤4（支付），更新订单总结
        if (currentStep === 4) {
            updateOrderSummary();
        }
    }

    /**
     * 保存参与者数据
     */
    function saveParticipantsData(container) {
        bookingData.participants = [];
        const participantForms = container.querySelectorAll('.participant-form');
        
        participantForms.forEach((form) => {
            const dataIndex = form.getAttribute('data-index');
            const participant = {
                // 默认必填字段（系统默认收集）
                first_name: form.querySelector('[name*="participant_first_name"]')?.value || '',
                middle_name: form.querySelector('[name*="participant_middle_name"]')?.value || '',
                last_name: form.querySelector('[name*="participant_last_name"]')?.value || '',
                gender: form.querySelector('[name*="participant_gender"]')?.value || '',
                dob: form.querySelector('[name*="participant_dob"]')?.value || '',
                registration_type: form.querySelector('[name*="participant_registration_type"]')?.value || '',
                dietary_restrictions_or_allergies: (() => {
                    const radio = form.querySelector('input[name="participant_dietary_' + dataIndex + '"]:checked');
                    const details = form.querySelector('input[name="participant_dietary_' + dataIndex + '_details"]');
                    return { value: radio ? radio.value : 'no', details: details ? details.value : '' };
                })(),
                medical_conditions: (() => {
                    const radio = form.querySelector('input[name="participant_medical_' + dataIndex + '"]:checked');
                    const details = form.querySelector('input[name="participant_medical_' + dataIndex + '_details"]');
                    return { value: radio ? radio.value : 'no', details: details ? details.value : '' };
                })(),
                // 构造器配置的自定义问题答案
                custom_answers: {}
            };
            
            // 收集所有构造器配置的问题答案
            if (window.tripData && window.tripData.custom_questions) {
                window.tripData.custom_questions.forEach(question => {
                    if (question.type === 'yesno_text') {
                        const radio = form.querySelector(`input[name="participant_question_${question.id}_${dataIndex}"]:checked`);
                        const detailsInput = form.querySelector(`input[name="participant_question_${question.id}_${dataIndex}_details"]`);
                        participant.custom_answers[question.id] = {
                            question_id: question.id,
                            label: question.label,
                            value: radio ? radio.value : 'no',
                            details: detailsInput ? detailsInput.value : ''
                        };
                    } else if (question.type === 'file') {
                        const fieldName = `participant_question_${question.id}_${dataIndex}`;
                        const input = form.querySelector(`[name="${fieldName}"]`);
                        participant.custom_answers[question.id] = {
                            question_id: question.id,
                            label: question.label,
                            type: 'file',
                            value: input ? (input.value || '') : '',
                            original_filename: input ? (input.dataset.originalFilename || '') : ''
                        };
                    } else {
                        const fieldName = `participant_question_${question.id}_${dataIndex}`;
                        const input = form.querySelector(`[name="${fieldName}"]`);
                        if (input) {
                            participant.custom_answers[question.id] = {
                                question_id: question.id,
                                label: question.label,
                                type: question.type || 'text',
                                value: input.value || ''
                            };
                        }
                    }
                });
            }
            
            bookingData.participants.push(participant);
        });
    }

    /**
     * 保存购买者信息
     * 动态收集所有字段，确保与构造器配置一致
     */
    function saveBuyerInfoData(container) {
        bookingData.buyer_info = {
            // 标准字段（如果存在）
            first_name: container.querySelector('[name="buyer_first_name"]')?.value || '',
            last_name: container.querySelector('[name="buyer_last_name"]')?.value || '',
            email: container.querySelector('[name="buyer_email"]')?.value || '',
            phone: container.querySelector('[name="buyer_phone"]')?.value || '',
            address: container.querySelector('[name="buyer_address"]')?.value || '',
            city: container.querySelector('[name="buyer_city"]')?.value || '',
            state: container.querySelector('[name="buyer_state"]')?.value || '',
            zip_code: container.querySelector('[name="buyer_zip_code"]')?.value || '',
            country: container.querySelector('[name="buyer_country"]')?.value || '',
            emergency_contact_name: container.querySelector('[name="buyer_emergency_contact_name"]')?.value || '',
            emergency_contact_phone: container.querySelector('[name="buyer_emergency_contact_phone"]')?.value || '',
            emergency_contact_email: container.querySelector('[name="buyer_emergency_contact_email"]')?.value || '',
            emergency_contact_relationship: container.querySelector('[name="buyer_emergency_contact_relationship"]')?.value || '',
            home_phone: container.querySelector('[name="buyer_home_phone"]')?.value || '',
            work_phone: container.querySelector('[name="buyer_work_phone"]')?.value || '',
        };
        
        // 收集所有自定义字段（包括通过构造器配置的字段）
        const customFields = container.querySelectorAll('.custom-field');
        const customInfo = {};
        customFields.forEach(field => {
            const fieldId = field.getAttribute('data-field-id');
            const fieldType = field.getAttribute('data-field-type');
            if (fieldId) {
                if (fieldType === 'yesno_text') {
                    const radio = field.querySelector('input[type="radio"]:checked');
                    const detailsInput = field.querySelector('input[name$="_details"]');
                    customInfo[fieldId] = {
                        value: radio ? radio.value : 'no',
                        details: detailsInput ? detailsInput.value : ''
                    };
                } else {
                    const input = field.querySelector('input:not([type="radio"]), textarea, select');
                    if (input) {
                        customInfo[fieldId] = input.value || '';
                    }
                }
            }
        });
        bookingData.buyer_info.custom_info = customInfo;
    }

    /**
     * 添加参与者表单
     */
    function addParticipant() {
        if (!participantsContainer) return;
        
        participantCount++;
        const participantIndex = participantCount;
        
        // 根据构造器设计：默认必填字段 + 自定义问题
        let fieldsHtml = '';
        
        // 1. 默认必填字段（系统默认收集，不需要在构造器中配置）
        const reqStar = '<span class="required-asterisk">*</span>';
        fieldsHtml += `
            <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
                <div class="flex flex-col">
                    <label class="text-sm font-medium mb-1">Legal First Name${reqStar}</label>
                    <input type="text" name="participant_first_name_${participantIndex}" 
                        class="w-full min-w-0" required>
                </div>
                <div class="flex flex-col">
                    <label class="text-sm font-medium mb-1">Legal Middle Name</label>
                    <input type="text" name="participant_middle_name_${participantIndex}" 
                        class="w-full min-w-0" placeholder="Optional">
                </div>
                <div class="flex flex-col">
                    <label class="text-sm font-medium mb-1">Legal Last Name${reqStar}</label>
                    <input type="text" name="participant_last_name_${participantIndex}" 
                        class="w-full min-w-0" required>
                </div>
            </div>
            <div class="mt-4 grid grid-cols-1 md:grid-cols-2 gap-4">
                <div class="flex flex-col">
                    <label class="text-sm font-medium mb-1">Gender${reqStar}</label>
                    <select name="participant_gender_${participantIndex}" 
                        class="w-full min-w-0" required>
                        <option value="" disabled selected hidden></option>
                        <option value="Male">Male</option>
                        <option value="Female">Female</option>
                    </select>
                </div>
                <div class="flex flex-col">
                    <label class="text-sm font-medium mb-1">Date of Birth${reqStar}</label>
                    <input type="text" name="participant_dob_${participantIndex}" 
                        class="fp-date w-full min-w-0" 
                        placeholder="YYYY-MM-DD" required>
                </div>
                <div class="flex flex-col">
                    <label class="text-sm font-medium mb-1">Registration Type${reqStar}</label>
                    <select name="participant_registration_type_${participantIndex}" 
                        class="w-full min-w-0" required>
                        <option value="" disabled selected hidden></option>
                        <option value="Student">Student</option>
                        <option value="Faculty">Faculty</option>
                        <option value="Parent">Parent</option>
                    </select>
                </div>
            </div>
            <div class="mt-4 participant-yesno-field participant-default-yesno" data-field="dietary">
                <label class="text-sm font-medium mb-1">Dietary restrictions or allergies${reqStar}</label>
                <div class="flex gap-4 mb-2">
                    <label class="inline-flex items-center cursor-pointer">
                        <input type="radio" name="participant_dietary_${participantIndex}" value="no" checked class="participant-yesno-radio">
                        <span class="ml-2">No</span>
                    </label>
                    <label class="inline-flex items-center cursor-pointer">
                        <input type="radio" name="participant_dietary_${participantIndex}" value="yes" class="participant-yesno-radio">
                        <span class="ml-2">Yes</span>
                    </label>
                </div>
                <div class="yesno-details hidden mt-2">
                    <label class="block text-sm text-gray-700 mb-1">If yes, please explain:</label>
                    <input type="text" name="participant_dietary_${participantIndex}_details" 
                        class="w-full min-w-0 participant-yesno-details-input" 
                        placeholder="e.g. allergies, dietary restrictions">
                </div>
            </div>
            <div class="mt-4 participant-yesno-field participant-default-yesno" data-field="medical">
                <label class="text-sm font-medium mb-1">Medical conditions${reqStar}</label>
                <div class="flex gap-4 mb-2">
                    <label class="inline-flex items-center cursor-pointer">
                        <input type="radio" name="participant_medical_${participantIndex}" value="no" checked class="participant-yesno-radio">
                        <span class="ml-2">No</span>
                    </label>
                    <label class="inline-flex items-center cursor-pointer">
                        <input type="radio" name="participant_medical_${participantIndex}" value="yes" class="participant-yesno-radio">
                        <span class="ml-2">Yes</span>
                    </label>
                </div>
                <div class="yesno-details hidden mt-2">
                    <label class="block text-sm text-gray-700 mb-1">If yes, please explain:</label>
                    <input type="text" name="participant_medical_${participantIndex}_details" 
                        class="w-full min-w-0 participant-yesno-details-input" 
                        placeholder="e.g. medical conditions">
                </div>
            </div>
        `;
        
        // 2. 根据构造器配置的自定义问题生成字段
        if (window.tripData && window.tripData.custom_questions && window.tripData.custom_questions.length > 0) {
            window.tripData.custom_questions.forEach((question, qIndex) => {
                const fieldName = `participant_question_${question.id}_${participantIndex}`;
                const requiredAttr = question.required ? 'required' : '';
                const requiredMark = question.required ? '<span class="required-asterisk">*</span>' : '';
                
                // 根据问题类型生成对应的输入字段
                if (question.type === 'textarea') {
                    fieldsHtml += `
                        <div class="mt-4">
                            <label class="text-sm font-medium mb-1">${question.label}${requiredMark}</label>
                            <textarea name="${fieldName}" 
                                class="w-full min-w-0" rows="4" ${requiredAttr}></textarea>
                        </div>
                    `;
                } else if ((question.type === 'select' || question.type === 'choice') && question.options) {
                    const options = Array.isArray(question.options) ? question.options : JSON.parse(question.options || '[]');
                    let optionsHtml = '<option value="">Select an option</option>';
                    options.forEach(option => {
                        optionsHtml += `<option value="${option}">${option}</option>`;
                    });
                    fieldsHtml += `
                        <div class="mt-4">
                            <label class="text-sm font-medium mb-1">${question.label}${requiredMark}</label>
                            <select name="${fieldName}" 
                                class="w-full min-w-0" ${requiredAttr}>
                                ${optionsHtml}
                            </select>
                        </div>
                    `;
                } else if (question.type === 'number') {
                    fieldsHtml += `
                        <div class="mt-4">
                            <label class="text-sm font-medium mb-1">${question.label}${requiredMark}</label>
                            <input type="number" name="${fieldName}" 
                                class="w-full min-w-0" ${requiredAttr}>
                        </div>
                    `;
                } else if (question.type === 'date') {
                    fieldsHtml += `
                        <div class="mt-4">
                            <label class="text-sm font-medium mb-1">${question.label}${requiredMark}</label>
                            <input type="text" name="${fieldName}" 
                                class="fp-date w-full min-w-0" 
                                data-question-type="date"
                                placeholder="YYYY-MM-DD" ${requiredAttr}>
                        </div>
                    `;
                } else if (question.type === 'file') {
                    const acceptAttr = 'image/jpeg,image/png,image/webp,application/pdf,.jpg,.jpeg,.png,.webp,.pdf';
                    const fileInputId = `participant-file-${question.id}-${participantIndex}`;
                    fieldsHtml += `
                        <div class="mt-4 participant-file-field" data-question-id="${question.id}">
                            <label class="text-sm font-medium mb-1 block" for="${fileInputId}">${question.label}${requiredMark}</label>
                            <div class="participant-file-dropzone">
                                <input type="file" id="${fileInputId}" class="participant-file-input"
                                    accept="${acceptAttr}"
                                    data-question-id="${question.id}">
                                <div class="participant-file-idle">
                                    <div class="participant-file-idle-icon" aria-hidden="true">
                                        <svg width="22" height="22" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.75" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"/>
                                        </svg>
                                    </div>
                                    <p class="participant-file-idle-title">Upload a file</p>
                                    <p class="participant-file-idle-hint">JPG, PNG, WEBP or PDF · max 10MB</p>
                                    <label for="${fileInputId}" class="participant-file-browse-btn">Choose file</label>
                                </div>
                                <div class="participant-file-selected hidden">
                                    <div class="participant-file-selected-main">
                                        <span class="participant-file-selected-icon" aria-hidden="true">
                                            <svg width="18" height="18" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/>
                                            </svg>
                                        </span>
                                        <div class="participant-file-selected-text">
                                            <a class="participant-file-name" href="#" target="_blank" rel="noopener"></a>
                                            <p class="participant-file-selected-meta">Ready to submit</p>
                                        </div>
                                    </div>
                                    <div class="participant-file-selected-actions">
                                        <button type="button" class="participant-file-change-btn">Change</button>
                                        <button type="button" class="participant-file-clear-btn">Remove</button>
                                    </div>
                                </div>
                            </div>
                            <input type="hidden" name="${fieldName}" value=""
                                class="participant-file-path"
                                data-original-filename=""
                                ${requiredAttr}>
                            <p class="participant-file-status text-xs text-gray-500 mt-2">No file selected yet.</p>
                        </div>
                    `;
                } else if (question.type === 'yesno_text') {
                    fieldsHtml += `
                        <div class="mt-4 participant-yesno-field" data-question-id="${question.id}">
                            <label class="text-sm font-medium mb-1">${question.label}${requiredMark}</label>
                            <div class="flex gap-4 mb-2">
                                <label class="inline-flex items-center cursor-pointer">
                                    <input type="radio" name="${fieldName}" value="no" checked class="participant-yesno-radio">
                                    <span class="ml-2">No</span>
                                </label>
                                <label class="inline-flex items-center cursor-pointer">
                                    <input type="radio" name="${fieldName}" value="yes" class="participant-yesno-radio">
                                    <span class="ml-2">Yes</span>
                                </label>
                            </div>
                            <div class="yesno-details hidden mt-2">
                                <label class="block text-sm text-gray-700 mb-1">If yes, please explain:</label>
                                <input type="text" name="${fieldName}_details" 
                                    class="w-full min-w-0 participant-yesno-details-input" 
                                    placeholder="e.g. Allergens, dietary restrictions">
                            </div>
                        </div>
                    `;
                } else {
                    // text, email, phone 等文本类型
                    const inputType = question.type === 'email' ? 'email' : (question.type === 'phone' ? 'tel' : 'text');
                    const qTypeAttr = (question.type === 'email' || question.type === 'phone')
                        ? ` data-question-type="${question.type}"`
                        : '';
                    fieldsHtml += `
                        <div class="mt-4">
                            <label class="text-sm font-medium mb-1">${question.label}${requiredMark}</label>
                            <input type="${inputType}" name="${fieldName}" 
                                class="w-full min-w-0"${qTypeAttr} ${requiredAttr}>
                        </div>
                    `;
                }
            });
        }
        
        const chevronSvg = '<svg class="participant-chevron w-5 h-5 text-gray-500 flex-shrink-0 transition-transform" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 15l7-7 7 7"/></svg>';
        const participantHtml = `
            <div class="participant-form mb-4" data-index="${participantIndex}">
                <div class="flex justify-between items-center mb-4">
                    <div class="participant-section-header flex items-center gap-2 cursor-pointer flex-1" role="button" tabindex="0" aria-expanded="true">
                        <span class="participant-num-badge">${participantIndex}</span>
                        <span>Participant Information</span>
                        ${chevronSvg}
                    </div>
                </div>
                <div class="participant-form-body">${fieldsHtml}</div>
            </div>
        `;
        
        participantsContainer.insertAdjacentHTML('beforeend', participantHtml);
        
        // 对动态添加的日期字段初始化 Flatpickr（与 trip basics 一致）
        if (typeof window.initFlatpickrOnDates === 'function') {
            window.initFlatpickrOnDates();
        }

        // 报名文件上传（护照等）
        const formEl = participantsContainer.querySelector(`.participant-form[data-index="${participantIndex}"]`);
        if (formEl) {
            formEl.querySelectorAll('.participant-file-field').forEach(function(wrap) {
                bindParticipantFileField(wrap);
            });
        }
        
        // 第二章风格：折叠/展开 Participant Information
        const headerEl = formEl && formEl.querySelector('.participant-section-header');
        const bodyEl = formEl && formEl.querySelector('.participant-form-body');
        if (headerEl && bodyEl) {
            headerEl.addEventListener('click', function(e) {
                const collapsed = headerEl.getAttribute('aria-expanded') !== 'true';
                headerEl.setAttribute('aria-expanded', collapsed ? 'true' : 'false');
                bodyEl.style.display = collapsed ? '' : 'none';
                const chevron = headerEl.querySelector('.participant-chevron');
                if (chevron) chevron.style.transform = collapsed ? 'rotate(0deg)' : 'rotate(-180deg)';
            });
        }
    }

    /**
     * 绑定护照等文件上传控件（自定义按钮，隐藏原生 file input）
     */
    function bindParticipantFileField(wrap) {
        if (!wrap || wrap.getAttribute('data-file-bound') === '1') return;
        wrap.setAttribute('data-file-bound', '1');
        const fileInput = wrap.querySelector('.participant-file-input');
        const browseBtn = wrap.querySelector('.participant-file-browse-btn');
        const changeBtn = wrap.querySelector('.participant-file-change-btn');
        const clearBtn = wrap.querySelector('.participant-file-clear-btn');
        const dropzone = wrap.querySelector('.participant-file-dropzone');

        function openPicker(e) {
            if (e) e.preventDefault();
            if (fileInput && !fileInput.disabled) fileInput.click();
        }
        // Choose file 用 label[for]，浏览器原生就会打开选文件；勿再 click() 以免双弹窗
        if (browseBtn && browseBtn.tagName !== 'LABEL') {
            browseBtn.addEventListener('click', openPicker);
        }
        if (changeBtn) changeBtn.addEventListener('click', openPicker);
        if (clearBtn) {
            clearBtn.addEventListener('click', function(e) {
                e.preventDefault();
                if (fileInput) fileInput.value = '';
                const pathInput = wrap.querySelector('.participant-file-path');
                if (pathInput) {
                    pathInput.value = '';
                    pathInput.dataset.originalFilename = '';
                }
                syncParticipantFileUi(wrap, { status: 'No file selected yet.' });
            });
        }
        if (fileInput) fileInput.addEventListener('change', handleParticipantFileUpload);

        if (dropzone) {
            ['dragenter', 'dragover'].forEach(function(ev) {
                dropzone.addEventListener(ev, function(e) {
                    e.preventDefault();
                    e.stopPropagation();
                    dropzone.classList.add('is-dragover');
                });
            });
            ['dragleave', 'drop'].forEach(function(ev) {
                dropzone.addEventListener(ev, function(e) {
                    e.preventDefault();
                    e.stopPropagation();
                    dropzone.classList.remove('is-dragover');
                });
            });
            dropzone.addEventListener('drop', function(e) {
                const files = e.dataTransfer && e.dataTransfer.files;
                if (!files || !files.length || !fileInput || fileInput.disabled) return;
                try {
                    var dt = new DataTransfer();
                    dt.items.add(files[0]);
                    fileInput.files = dt.files;
                    fileInput.dispatchEvent(new Event('change', { bubbles: true }));
                } catch (err) {
                    // 无法程序化赋值时，提示用户点 Choose file
                    syncParticipantFileUi(wrap, { error: 'Please use Choose file to select your document.' });
                }
            });
        }
        syncParticipantFileUi(wrap);
    }

    function syncParticipantFileUi(wrap, opts) {
        if (!wrap) return;
        opts = opts || {};
        const idle = wrap.querySelector('.participant-file-idle');
        const selected = wrap.querySelector('.participant-file-selected');
        const nameEl = wrap.querySelector('.participant-file-name');
        const metaEl = wrap.querySelector('.participant-file-selected-meta');
        const statusEl = wrap.querySelector('.participant-file-status');
        const dropzone = wrap.querySelector('.participant-file-dropzone');
        const pathInput = wrap.querySelector('.participant-file-path');
        const path = (pathInput && pathInput.value) || '';
        const fname = (pathInput && pathInput.dataset.originalFilename) || (path ? path.split('/').pop() : '');

        if (dropzone) dropzone.classList.toggle('has-file', !!path);

        if (path) {
            if (idle) idle.classList.add('hidden');
            if (selected) selected.classList.remove('hidden');
            if (nameEl) {
                nameEl.textContent = fname || 'Uploaded file';
                nameEl.href = path.indexOf('http') === 0 ? path : ('/static/' + path);
            }
            if (metaEl) metaEl.textContent = opts.meta || 'Uploaded';
            if (statusEl && opts.status != null) {
                statusEl.textContent = opts.status;
            } else if (statusEl && !opts.keepStatus) {
                statusEl.textContent = 'File uploaded successfully.';
            }
            if (statusEl && !opts.error) {
                statusEl.classList.remove('text-red-600', 'text-gray-500', 'text-gray-600', 'is-error');
                statusEl.classList.add('is-success');
            }
        } else {
            if (idle) idle.classList.remove('hidden');
            if (selected) selected.classList.add('hidden');
            if (statusEl && opts.status != null) {
                statusEl.textContent = opts.status;
            } else if (statusEl && !opts.keepStatus) {
                statusEl.textContent = 'No file selected yet.';
            }
            if (statusEl && !opts.error) {
                statusEl.classList.remove('text-red-600', 'text-gray-600', 'is-success', 'is-error');
                statusEl.classList.add('text-gray-500');
            }
        }
        if (opts.error && statusEl) {
            statusEl.textContent = opts.error;
            statusEl.classList.add('text-red-600', 'is-error');
            statusEl.classList.remove('text-gray-500', 'text-gray-600', 'is-success');
        }
    }

    /**
     * 参与者自定义问题：上传文件到 /api/booking/upload，路径写入 hidden
     */
    async function handleParticipantFileUpload(event) {
        const fileInput = event.target;
        const wrap = fileInput.closest('.participant-file-field');
        if (!wrap) return;
        const pathInput = wrap.querySelector('.participant-file-path');
        const statusEl = wrap.querySelector('.participant-file-status');
        const browseBtn = wrap.querySelector('.participant-file-browse-btn');
        const changeBtn = wrap.querySelector('.participant-file-change-btn');
        const file = fileInput.files && fileInput.files[0];

        if (!file) {
            if (pathInput) {
                pathInput.value = '';
                pathInput.dataset.originalFilename = '';
            }
            syncParticipantFileUi(wrap, { status: 'No file selected yet.' });
            return;
        }

        const maxBytes = 10 * 1024 * 1024;
        if (file.size > maxBytes) {
            if (pathInput) {
                pathInput.value = '';
                pathInput.dataset.originalFilename = '';
            }
            fileInput.value = '';
            syncParticipantFileUi(wrap, { error: 'File too large (max 10MB).' });
            return;
        }

        if (statusEl) {
            statusEl.textContent = 'Uploading…';
            statusEl.classList.remove('text-red-600');
            statusEl.classList.add('text-gray-500');
        }
        fileInput.disabled = true;
        if (browseBtn) browseBtn.disabled = true;
        if (changeBtn) changeBtn.disabled = true;

        const formData = new FormData();
        formData.append('file', file);
        if (typeof tripData !== 'undefined' && tripData && tripData.id) {
            formData.append('trip_id', String(tripData.id));
        }

        try {
            const response = await fetch('/api/booking/upload', {
                method: 'POST',
                body: formData
            });
            const data = await response.json().catch(function() { return {}; });
            if (!response.ok) {
                throw new Error(data.error || 'Upload failed');
            }
            if (pathInput) {
                pathInput.value = data.path || '';
                pathInput.dataset.originalFilename = data.original_filename || file.name || '';
                pathInput.classList.remove('border-red-500');
                pathInput.style.borderColor = '';
                pathInput.style.borderWidth = '';
            }
            syncParticipantFileUi(wrap, {
                status: 'File uploaded successfully.',
                meta: 'Uploaded'
            });
        } catch (err) {
            if (pathInput) {
                pathInput.value = '';
                pathInput.dataset.originalFilename = '';
            }
            fileInput.value = '';
            syncParticipantFileUi(wrap, {
                error: (err && err.message) ? err.message : 'Upload failed. Please try again.'
            });
        } finally {
            fileInput.disabled = false;
            if (browseBtn) browseBtn.disabled = false;
            if (changeBtn) changeBtn.disabled = false;
        }
    }

    /**
     * 更新参与者编号
     */
    function updateParticipantNumbers() {
        const forms = participantsContainer.querySelectorAll('.participant-form');
        forms.forEach((form, index) => {
            form.setAttribute('data-index', String(index + 1));
            const badge = form.querySelector('.participant-num-badge');
            if (badge) badge.textContent = String(index + 1);
        });
    }

    /**
     * 更新参与者数量（根据选择的套餐）
     */
    function updateParticipantCount() {
        if (!participantsContainer) return;
        
        // 计算总数量
        const totalQuantity = bookingData.packages.reduce((sum, pkg) => sum + pkg.quantity, 0);
        
        // 保存当前表单数据（如果表单已存在）
        if (participantsContainer.children.length > 0) {
            saveParticipantsData(participantsContainer.closest('.booking-step'));
        }
        
        // 清空现有表单
        participantsContainer.innerHTML = '';
        participantCount = 0;
        
        // 根据数量生成参与者表单
        for (let i = 0; i < totalQuantity; i++) {
            addParticipant();
        }
        
        // 恢复之前保存的数据
        if (bookingData.participants && bookingData.participants.length > 0) {
            const participantForms = participantsContainer.querySelectorAll('.participant-form');
            participantForms.forEach((form, index) => {
                const participant = bookingData.participants[index];
                if (participant) {
                    // 恢复默认字段
                    const firstNameInput = form.querySelector('[name*="participant_first_name"]');
                    const middleNameInput = form.querySelector('[name*="participant_middle_name"]');
                    const lastNameInput = form.querySelector('[name*="participant_last_name"]');
                    const genderSelect = form.querySelector('[name*="participant_gender"]');
                    const dobInput = form.querySelector('[name*="participant_dob"]');
                    const regTypeSelect = form.querySelector('[name*="participant_registration_type"]');
                    
                    if (firstNameInput) firstNameInput.value = participant.first_name || '';
                    if (middleNameInput) middleNameInput.value = participant.middle_name || '';
                    if (lastNameInput) lastNameInput.value = participant.last_name || '';
                    if (genderSelect) genderSelect.value = participant.gender || '';
                    if (dobInput) dobInput.value = participant.dob || '';
                    if (regTypeSelect) regTypeSelect.value = participant.registration_type || '';
                    
                    // 恢复 Dietary / Medical (yesno)
                    const dataIndex = form.getAttribute('data-index');
                    ['dietary', 'medical'].forEach(field => {
                        const data = participant[field === 'dietary' ? 'dietary_restrictions_or_allergies' : 'medical_conditions'];
                        if (data && typeof data === 'object') {
                            const isYes = (data.value || 'no') === 'yes';
                            const radio = form.querySelector(`input[name="participant_${field}_${dataIndex}"][value="${data.value || 'no'}"]`);
                            const detailsInput = form.querySelector(`input[name="participant_${field}_${dataIndex}_details"]`);
                            const detailsDiv = form.querySelector(`.participant-default-yesno[data-field="${field}"] .yesno-details`);
                            if (radio) radio.checked = true;
                            if (detailsInput) {
                                detailsInput.value = data.details || '';
                                detailsInput.required = isYes;
                            }
                            if (detailsDiv) detailsDiv.classList.toggle('hidden', !isYes);
                        }
                    });
                    
                    // 恢复自定义问题答案
                    if (participant.custom_answers && window.tripData && window.tripData.custom_questions) {
                        const dataIndex = (index + 1).toString();
                        window.tripData.custom_questions.forEach(question => {
                            const answer = participant.custom_answers[question.id];
                            if (!answer) return;
                            if (question.type === 'yesno_text') {
                                const radio = form.querySelector(`input[name="participant_question_${question.id}_${dataIndex}"][value="${answer.value || 'no'}"]`);
                                const detailsInput = form.querySelector(`input[name="participant_question_${question.id}_${dataIndex}_details"]`);
                                const detailsDiv = form.querySelector(`.participant-yesno-field[data-question-id="${question.id}"] .yesno-details`);
                                if (radio) radio.checked = true;
                                if (detailsInput) detailsInput.value = answer.details || '';
                                if (detailsDiv) detailsDiv.classList.toggle('hidden', (answer.value || 'no') !== 'yes');
                            } else if (question.type === 'file') {
                                const wrap = form.querySelector(`.participant-file-field[data-question-id="${question.id}"]`);
                                const pathInput = form.querySelector(`[name="participant_question_${question.id}_${dataIndex}"]`);
                                if (pathInput && answer.value) {
                                    pathInput.value = answer.value;
                                    pathInput.dataset.originalFilename = answer.original_filename || '';
                                    if (wrap) {
                                        bindParticipantFileField(wrap);
                                        syncParticipantFileUi(wrap, { status: 'File uploaded successfully.', meta: 'Uploaded' });
                                    }
                                }
                            } else {
                                const input = form.querySelector(`[name="participant_question_${question.id}_${dataIndex}"]`);
                                if (input) input.value = answer.value || '';
                            }
                        });
                    }
                }
            });
        }

        convertAllModalSelects();
    }

    /**
     * 从 DOM 同步当前套餐与附加项到 bookingData，保证 Your Booking 与页面选择一致
     */
    function syncBookingDataFromDOM() {
        const step1 = document.querySelector('.booking-step[data-step="1"]');
        const step3 = document.querySelector('.booking-step[data-step="3"]');
        tripData = window.tripData || tripData || {};
        if (step1) {
            bookingData.packages = [];
            step1.querySelectorAll('input.package-quantity').forEach(function(el) {
                var packageId = parseInt(el.getAttribute('data-package-id'), 10);
                var quantity = parseInt(el.value, 10) || 0;
                if (quantity <= 0 || !packageId) return;
                var payment_plan_type = resolvePaymentPlanTypeForPackage(packageId);
                bookingData.packages.push({ package_id: packageId, quantity: quantity, payment_plan_type: payment_plan_type });
            });
        }
        if (step3) {
            bookingData.addons = [];
            step3.querySelectorAll('.addon-quantity').forEach(function(el) {
                var addonId = parseInt(el.getAttribute('data-addon-id'), 10);
                var quantity = parseInt(el.value, 10) || 0;
                if (quantity <= 0 || !addonId) return;
                bookingData.addons.push({ addon_id: addonId, quantity: quantity });
            });
        }
    }

    /**
     * Scale pay-option labels + installment schedule amounts by traveler quantity.
     */
    function updatePackageScaledAmounts() {
        document.querySelectorAll('#booking-modal .package-card').forEach(function(card) {
            var pid = card.getAttribute('data-package-id');
            var input = card.querySelector('input.package-quantity[data-package-id="' + pid + '"]')
                || document.querySelector('input.package-quantity[data-package-id="' + pid + '"]');
            var qty = input ? (parseInt(input.value, 10) || 0) : 0;
            var scale = qty > 0 ? qty : 1;

            var fullLabel = card.querySelector('.pkg-pay-label-full');
            if (fullLabel && fullLabel.getAttribute('data-unit-amount') != null) {
                var fullUnit = parseFloat(fullLabel.getAttribute('data-unit-amount')) || 0;
                fullLabel.textContent = 'Pay in full ($' + formatCurrency(fullUnit * scale) + ')';
            }
            var depLabel = card.querySelector('.pkg-pay-label-deposit');
            if (depLabel && depLabel.getAttribute('data-unit-amount') != null) {
                var depUnit = parseFloat(depLabel.getAttribute('data-unit-amount')) || 0;
                depLabel.textContent = 'Deposit + installments (deposit $' + formatCurrency(depUnit * scale) + ')';
            }
            var depOnly = card.querySelector('.pkg-pay-label-deposit-only');
            if (depOnly && depOnly.getAttribute('data-unit-amount') != null) {
                var onlyUnit = parseFloat(depOnly.getAttribute('data-unit-amount')) || 0;
                depOnly.textContent = 'Installment plan required · Deposit $' + formatCurrency(onlyUnit * scale);
            }
            card.querySelectorAll('.installment-schedule-amount[data-unit-amount]').forEach(function(el) {
                var unit = parseFloat(el.getAttribute('data-unit-amount')) || 0;
                el.textContent = '$' + formatCurrency(unit * scale);
            });
        });
    }

    /**
     * 更新订单总结（Your Booking 价格计算）
     * 与后端对齐：Trip Total 对应 calculate_booking_total 的 subtotal（全价合计）；
     * Due at Booking 对应 calculate_initial_payment_amount（deposit×数量 + 逾期分期 + 附加项）- 折扣 + 手续费。
     * 逾期判定与 payments.py 一致：installments[].date 格式 YYYY-MM-DD，仅当 due_date < today 计入。
     * 有 lastQuote.final_amount 时优先用后端金额，保证 Due at Booking 与后台一致。
     */
    function updateOrderSummary() {
        if (!orderSummaryEl) orderSummaryEl = document.getElementById('order-summary');
        if (!totalAmountEl) totalAmountEl = document.getElementById('total-amount');
        if (!orderSummaryEl || !totalAmountEl) return;
        tripData = window.tripData || tripData || {};

        syncBookingDataFromDOM();
        if (!bookingData.packages) bookingData.packages = [];
        if (!bookingData.addons) bookingData.addons = [];

        // 按 package_id 合并并汇总 quantity，避免同一套餐多行时重复计费
        var mergedPackages = [];
        bookingData.packages.forEach(function(pkg) {
            var id = Number(pkg.package_id);
            var existing = mergedPackages.find(function(m) { return m.package_id === id; });
            if (existing) {
                existing.quantity = (parseInt(existing.quantity, 10) || 0) + (parseInt(pkg.quantity, 10) || 0);
            } else {
                mergedPackages.push({ package_id: pkg.package_id, quantity: pkg.quantity, payment_plan_type: pkg.payment_plan_type });
            }
        });
        bookingData.packages = mergedPackages;

        var tripTotalFull = 0;   // Trip Total = 全价合计（单价×数量）
        var dueNowTotal = 0;     // Due at Booking 的 subtotal = deposit×数量 + 逾期金额（分期）或 全价（全款）
        var html = '';

        bookingData.packages.forEach(function(pkg) {
            var packageData = tripData.packages && tripData.packages.find(function(p) { return Number(p.id) === Number(pkg.package_id); });
            if (!packageData) return;
            var price = parseFloat(packageData.price) || 0;
            var qty = Math.max(0, parseInt(pkg.quantity, 10) || 0);
            if (qty <= 0) return;
            tripTotalFull += price * qty;
            var lineDueNow = 0;
            var displayName = packageData.name;
            var ppc = packageData.payment_plan_config;

            if (pkg.payment_plan_type === 'deposit_installment' && ppc && ppc.enabled) {
                var depositAmount = parseFloat(ppc.deposit_amount || ppc.deposit || 0) || 0;
                lineDueNow = depositAmount * qty;
                displayName = packageData.name + ' (Deposit)';
                // 当今日期 YYYY-MM-DD，用于判断分期是否逾期（due_date < today 则计入 Due at Booking）
                var now = new Date();
                var todayStr = now.getFullYear() + '-' + String(now.getMonth() + 1).padStart(2, '0') + '-' + String(now.getDate()).padStart(2, '0');
                var installments = ppc.installments || [];
                for (var i = 0; i < installments.length; i++) {
                    var inst = installments[i];
                    if (inst && inst.date) {
                        var dueStr = String(inst.date).substring(0, 10);
                        if (dueStr.length === 10 && dueStr < todayStr) lineDueNow += (parseFloat(inst.amount) || 0) * qty;
                    }
                }
                if (lineDueNow !== depositAmount * qty) displayName = packageData.name + ' (Deposit + Overdue)';
            } else {
                lineDueNow = price * qty;
                if (ppc && ppc.enabled) displayName = packageData.name + ' (Pay in full)';
            }
            dueNowTotal += lineDueNow;
            html += '<div class="flex justify-between"><span>' + displayName + ' x' + qty + '</span><span>$' + formatCurrency(lineDueNow) + '</span></div>';
        });

        bookingData.addons.forEach(function(addon) {
            var addonData = tripData.addons && tripData.addons.find(function(a) { return Number(a.id) === Number(addon.addon_id); });
            if (!addonData) return;
            var lineTotal = (parseFloat(addonData.price) || 0) * (Math.max(0, parseInt(addon.quantity, 10)) || 0);
            tripTotalFull += lineTotal;
            dueNowTotal += lineTotal;
            html += '<div class="flex justify-between text-sm text-gray-600"><span>' + addonData.name + ' x' + addon.quantity + '</span><span>$' + formatCurrency(lineTotal) + '</span></div>';
        });

        tripTotalFull = Math.round(tripTotalFull * 100) / 100;
        dueNowTotal = Math.round(dueNowTotal * 100) / 100;
        var discountAmount = (bookingData.discount_code && bookingData.discount_amount > 0) ? parseFloat(bookingData.discount_amount) : 0;
        var totalAfterDiscount = Math.max(0, Math.round((dueNowTotal - discountAmount) * 100) / 100);

        if (html === '') {
            html = '<p class="text-gray-500">Select packages to see total.</p>';
        }
        orderSummaryEl.innerHTML = html;

        // Your Booking：选分期时直接显示 Payment plan（同日金额合并）
        var planWrap = document.getElementById('booking-payment-plan');
        if (planWrap) {
            var dueBuckets = {}; // key -> { label, amount, sort }
            function addDue(key, label, amount, sort) {
                if (!dueBuckets[key]) {
                    dueBuckets[key] = { label: label, amount: 0, sort: sort };
                }
                dueBuckets[key].amount += amount;
            }
            var hasPlan = false;
            bookingData.packages.forEach(function(pkg) {
                if (pkg.payment_plan_type !== 'deposit_installment') return;
                var packageData = tripData.packages && tripData.packages.find(function(p) {
                    return Number(p.id) === Number(pkg.package_id);
                });
                if (!packageData) return;
                var ppc = packageData.payment_plan_config;
                if (!ppc || !ppc.enabled) return;
                var qty = Math.max(0, parseInt(pkg.quantity, 10) || 0);
                if (qty <= 0) return;
                hasPlan = true;
                var depositAmount = parseFloat(ppc.deposit_amount || ppc.deposit || 0) || 0;
                addDue('deposit-today', 'Deposit · Due today', depositAmount * qty, '0');
                (ppc.installments || []).forEach(function(inst) {
                    if (!inst) return;
                    var dueStr = inst.date ? String(inst.date).substring(0, 10) : '';
                    if (!dueStr) return;
                    addDue(
                        'inst-' + dueStr,
                        formatPlanDate(dueStr),
                        (parseFloat(inst.amount) || 0) * qty,
                        dueStr
                    );
                });
            });
            if (hasPlan) {
                var rows = Object.keys(dueBuckets).map(function(k) { return dueBuckets[k]; });
                rows.sort(function(a, b) {
                    if (a.sort === b.sort) return 0;
                    return a.sort < b.sort ? -1 : 1;
                });
                var rowsHtml = rows.map(function(r) {
                    return '<div class="booking-payment-plan-row"><span>' + r.label + '</span><span class="amt">$' + formatCurrency(r.amount) + '</span></div>';
                }).join('');
                planWrap.classList.remove('hidden');
                planWrap.innerHTML =
                    '<div class="booking-payment-plan-title">Payment plan</div>' +
                    rowsHtml;
            } else {
                planWrap.classList.add('hidden');
                planWrap.innerHTML = '';
            }
        }

        // 弹窗内：数量 > 0 且选了分期时显示 Payment plan 明细；金额随人数缩放
        document.querySelectorAll('#booking-modal .package-card').forEach(function(card) {
            var pid = card.getAttribute('data-package-id');
            var input = document.querySelector('input.package-quantity[data-package-id="' + pid + '"]');
            var qty = input ? (parseInt(input.value, 10) || 0) : 0;
            var detailEl = card.querySelector('.package-installment-detail');
            var planType = resolvePaymentPlanTypeForPackage(pid);
            if (detailEl) {
                if (qty > 0 && planType === 'deposit_installment') detailEl.classList.remove('hidden');
                else detailEl.classList.add('hidden');
            }
        });
        updatePackageScaledAmounts();

        var tripTotalEl = document.getElementById('trip-total-amount');
        if (tripTotalEl) tripTotalEl.textContent = '$' + formatCurrency(tripTotalFull);

        var discountInputSection = document.getElementById('discount-input-section');
        var discountApplied = document.getElementById('discount-applied');
        var discountAmountDisplay = document.getElementById('discount-amount-display');
        // 付款结果态（loading/success/failure）时整块折扣 UI 保持隐藏，勿被摘要刷新重新打开
        var paymentResultActive = (function() {
            var wrap = document.getElementById('booking-modal-result');
            return !!(wrap && !wrap.classList.contains('hidden'));
        })();
        if (paymentResultActive) {
            if (discountInputSection) discountInputSection.classList.add('hidden');
            if (discountApplied) discountApplied.classList.add('hidden');
        } else if (bookingData.discount_code && discountAmount > 0) {
            if (discountInputSection) discountInputSection.classList.add('hidden');
            if (discountApplied) discountApplied.classList.remove('hidden');
            if (discountAmountDisplay) discountAmountDisplay.textContent = '-$' + formatCurrency(discountAmount);
        } else {
            if (discountInputSection) discountInputSection.classList.remove('hidden');
            if (discountApplied) discountApplied.classList.add('hidden');
        }

        var feeAmountEl = document.getElementById('fee-amount');
        var feeCents = (lastQuote && typeof lastQuote.fee === 'number') ? lastQuote.fee : 0;
        var feeDollars = feeCents / 100;
        if (feeAmountEl) {
            feeAmountEl.textContent = '$' + formatCurrency(feeDollars);
            feeAmountEl.classList.toggle('text-zinc-900', feeCents > 0);
            feeAmountEl.classList.toggle('text-zinc-500', feeCents <= 0);
        }

        // Due at Booking：与后端一致。有 lastQuote 时用后端 final_amount（已含折扣+手续费），保证与后台对上；一律两位小数
        var displayTotal = totalAfterDiscount + feeDollars;
        if (lastQuote && typeof lastQuote.final_amount === 'number') displayTotal = lastQuote.final_amount / 100;
        totalAmountEl.textContent = '$' + formatCurrency(Math.round(displayTotal * 100) / 100);
    }

    function updateEmbeddedSummary(quote) {
        if (!quote || typeof quote.final_amount !== 'number') {
            return;
        }
        if (totalAmountEl) {
            totalAmountEl.textContent = '$' + formatCurrency(quote.final_amount / 100);
        }
    }

    /**
     * 折扣码提示（不依赖 Tailwind 动态类，避免继承成黑色字）
     * kind: 'warn' | 'error'
     */
    function showDiscountMessage(text, kind) {
        var messageEl = document.getElementById('discount-message');
        if (!messageEl) return;
        messageEl.textContent = text || '';
        messageEl.className = 'discount-msg--' + (kind === 'warn' ? 'warn' : 'error');
        messageEl.classList.remove('hidden');
    }

    function hideDiscountMessage() {
        var messageEl = document.getElementById('discount-message');
        if (!messageEl) return;
        messageEl.textContent = '';
        messageEl.className = '';
        messageEl.classList.add('hidden');
    }

    /**
     * 应用折扣码
     */
    async function applyDiscountCode() {
        const codeInput = document.getElementById('discount-code-input');
        const applyBtn = document.getElementById('apply-discount-btn');
        const discountInputSection = document.getElementById('discount-input-section');
        const discountApplied = document.getElementById('discount-applied');
        const discountCodeDisplay = document.getElementById('discount-code-display');
        const discountAmountDisplay = document.getElementById('discount-amount-display');
        
        if (!codeInput || !codeInput.value.trim()) {
            showDiscountMessage('Please enter a discount code.', 'error');
            return;
        }

        // 未选套餐时不要调 API（固定额折扣会变成 $0 并显示已应用）
        var hasPackage = false;
        for (const pkg of (bookingData.packages || [])) {
            if ((parseInt(pkg.quantity, 10) || 0) > 0) {
                hasPackage = true;
                break;
            }
        }
        if (!hasPackage) {
            showDiscountMessage('Please select a package before applying a discount code.', 'warn');
            return;
        }
        
        const code = codeInput.value.trim().toUpperCase();
        
        // 计算订单金额（与 updateOrderSummary / Due at Booking 一致：分期时 = 定金×数量 + 逾期分期×数量）
        let orderAmount = 0;
        var now = new Date();
        var todayStr = now.getFullYear() + '-' + String(now.getMonth() + 1).padStart(2, '0') + '-' + String(now.getDate()).padStart(2, '0');
        for (const pkg of (bookingData.packages || [])) {
            const pkgData = tripData.packages?.find(p => p.id === pkg.package_id);
            if (!pkgData || !pkgData.price) continue;
            var qty = Math.max(0, parseInt(pkg.quantity, 10) || 0);
            if (qty <= 0) continue;
            var ppc = pkgData.payment_plan_config;
            if (pkg.payment_plan_type === 'deposit_installment' && ppc && ppc.enabled) {
                var depositAmount = parseFloat(ppc.deposit_amount || ppc.deposit || 0) || 0;
                orderAmount += depositAmount * qty;
                var installments = ppc.installments || [];
                for (var i = 0; i < installments.length; i++) {
                    var inst = installments[i];
                    if (inst && inst.date) {
                        var dueStr = String(inst.date).substring(0, 10);
                        if (dueStr.length === 10 && dueStr < todayStr) orderAmount += (parseFloat(inst.amount) || 0) * qty;
                    }
                }
            } else {
                orderAmount += (parseFloat(pkgData.price) || 0) * qty;
            }
        }
        for (const addon of (bookingData.addons || [])) {
            const addonData = tripData.addons?.find(a => a.id === addon.addon_id);
            if (addonData && addonData.price) {
                orderAmount += addonData.price * (addon.quantity || 1);
            }
        }
        
        // 显示加载状态
        if (applyBtn) {
            applyBtn.disabled = true;
            applyBtn.textContent = '...';
        }
        
        try {
            const response = await fetch('/api/discount/validate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    code: code,
                    trip_id: tripData.id,
                    order_amount: orderAmount
                })
            });
            
            const result = await response.json();
            
            if (result.valid) {
                // 保存折扣信息
                bookingData.discount_code = result.discount.code;
                bookingData.discount_code_id = result.discount.id;
                bookingData.discount_amount = result.discount.discount_amount;
                
                hideDiscountMessage();

                // 更新 UI - 隐藏输入框，显示已应用状态
                if (discountInputSection) discountInputSection.classList.add('hidden');
                if (discountApplied) {
                    discountApplied.classList.remove('hidden');
                    if (discountCodeDisplay) discountCodeDisplay.textContent = result.discount.code;
                    if (discountAmountDisplay) {
                        discountAmountDisplay.textContent = '-$' + formatCurrency(result.discount.discount_amount);
                    }
                }
                
                // 更新订单总结
                updateOrderSummary();
                
                // 如果支付已初始化，更新 PendingBooking 中的折扣信息并重新请求 quote
                if (embeddedPaymentSession && embeddedPaymentSession.payment_intent_id) {
                    console.log('Updating discount on PendingBooking...');
                    try {
                        const applyResponse = await fetch('/api/discount/apply', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({
                                payment_intent_id: embeddedPaymentSession.payment_intent_id,
                                discount_code_id: result.discount.id,
                                discount_amount: result.discount.discount_amount
                            })
                        });
                        const applyResult = await applyResponse.json();
                        console.log('Discount applied to PendingBooking:', applyResult);

                        if (applyResult.success && applyResult.payment_required === false) {
                            if (paymentElementInstance) {
                                try { paymentElementInstance.unmount(); } catch (e) { /* ignore */ }
                            }
                            paymentElementInstance = null;
                            elementsInstance = null;
                            stripeInstance = null;
                            lastPaymentMethodId = null;
                            embeddedPaymentSession.payment_required = false;
                            embeddedPaymentSession.client_secret = null;
                            embeddedPaymentSession.base_amount_cents = 0;
                            showFreePaymentUI();
                        } else if (paymentElementInstance && elementsInstance) {
                            console.log('Requesting new quote after discount applied...');
                            await requestEmbeddedQuote(true);
                        }
                    } catch (applyError) {
                        console.error('Error applying discount to PendingBooking:', applyError);
                    }
                }
                
                console.log('Discount applied:', result.discount);
            } else {
                showDiscountMessage(result.message || 'Invalid discount code.', 'error');
            }
        } catch (error) {
            console.error('Error validating discount code:', error);
            showDiscountMessage('Error validating discount code. Please try again.', 'error');
        } finally {
            if (applyBtn) {
                applyBtn.disabled = false;
                applyBtn.textContent = 'Apply';
            }
        }
    }
    
    /**
     * 移除折扣码
     */
    async function removeDiscountCode() {
        const codeInput = document.getElementById('discount-code-input');
        const discountInputSection = document.getElementById('discount-input-section');
        const discountApplied = document.getElementById('discount-applied');
        
        // 清除折扣数据
        bookingData.discount_code = null;
        bookingData.discount_code_id = null;
        bookingData.discount_amount = 0;
        
        // 更新 UI - 显示输入框，隐藏已应用状态
        if (discountInputSection) discountInputSection.classList.remove('hidden');
        if (codeInput) {
            codeInput.value = '';
        }
        if (discountApplied) discountApplied.classList.add('hidden');
        hideDiscountMessage();
        
        // 更新订单总结
        updateOrderSummary();
        
        // 如果支付已初始化，更新 PendingBooking 中的折扣信息并重新请求 quote
        if (embeddedPaymentSession && embeddedPaymentSession.payment_intent_id) {
            console.log('Removing discount from PendingBooking...');
            try {
                const applyResponse = await fetch('/api/discount/apply', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        payment_intent_id: embeddedPaymentSession.payment_intent_id,
                        discount_code_id: null,
                        discount_amount: 0
                    })
                });
                const applyResult = await applyResponse.json();
                console.log('Discount removed from PendingBooking:', applyResult);

                // 从 $0 免改回需付款：整段支付会话重初始化
                if (embeddedPaymentSession.payment_required === false || !paymentElementInstance) {
                    resetEmbeddedPaymentSession();
                    await initEmbeddedPaymentSession();
                } else if (paymentElementInstance && elementsInstance) {
                    console.log('Requesting new quote after discount removed...');
                    await requestEmbeddedQuote(true);
                }
            } catch (applyError) {
                console.error('Error removing discount from PendingBooking:', applyError);
            }
        }
        
        console.log('Discount removed');
    }

    /**
     * 处理提交
     */
    function handleSubmit(e) {
        e.preventDefault();
        
        // 验证最后一步
        if (!validateCurrentStep()) {
            return;
        }

        // 保存最后一步数据
        saveCurrentStepData();

        // 显示加载状态（最后一步唯一按钮为 nextButton）
        var confirmBtn = submitButton || nextButton;
        if (confirmBtn) {
            confirmBtn.disabled = true;
            confirmBtn.textContent = 'Processing...';
        }

        if (document.getElementById('payment-element')) {
            submitEmbeddedPayment();
        } else {
            submitBooking();
        }
    }

    /**
     * 提交报名数据到服务器
     */
    async function submitBooking() {
        try {
            const form = document.getElementById('bookingForm');
            const formData = new FormData(form);
            
            // 添加 JSON 数据
            if (!bookingData.parental_waiver && window.__parentalWaiverAcceptance) {
                bookingData.parental_waiver = window.__parentalWaiverAcceptance;
            }
            formData.append('booking_data', JSON.stringify(bookingData));

            const response = await fetch(form.action || window.location.href, {
                method: 'POST',
                body: formData,
                headers: {
                    'X-Requested-With': 'XMLHttpRequest'
                }
            });

            const result = await response.json();

            if (result.success) {
                if (result.payment_url) {
                    window.location.href = result.payment_url;
                } else if (result.checkout_url) {
                    window.location.href = result.checkout_url;
                } else {
                    window.location.href = result.redirect_url || '/booking/success';
                }
            } else {
                showCustomAlert(result.error || 'Booking submission failed. Please try again.');
                var btn = submitButton || nextButton;
                if (btn) { btn.disabled = false; btn.textContent = 'Confirm Booking'; }
            }
        } catch (error) {
            console.error('Booking submission error:', error);
            showCustomAlert('An error occurred. Please try again.');
            var btn = submitButton || nextButton;
            if (btn) { btn.disabled = false; btn.textContent = 'Confirm Booking'; }
        }
    }

    function getBookingSignature() {
        return JSON.stringify({
            buyer_info: bookingData.buyer_info,
            packages: bookingData.packages,
            addons: bookingData.addons,
            participants: bookingData.participants,
            payment_method: bookingData.payment_method,
            discount_code: bookingData.discount_code || null,
            discount_amount: bookingData.discount_amount || 0,
        });
    }

    function showFreePaymentUI() {
        const paymentContainer = document.getElementById('payment-element');
        if (paymentContainer) {
            paymentContainer.classList.add('is-free-checkout');
            paymentContainer.innerHTML = `
                <div class="free-checkout-card" role="status">
                    <div class="free-checkout-icon" aria-hidden="true">
                        <svg width="28" height="28" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/>
                        </svg>
                    </div>
                    <div class="free-checkout-body">
                        <p class="free-checkout-title">No payment due right now</p>
                        <p class="free-checkout-text">Your discount covers the amount due at booking. Click <strong>Confirm Booking</strong> to reserve your spot.</p>
                        <p class="free-checkout-note">Any remaining balance will be collected later as scheduled.</p>
                    </div>
                </div>
            `;
        }
        var feeHint = document.querySelector('.payment-card-fee-hint');
        if (feeHint) feeHint.classList.add('is-free-hidden');
        setPaymentElementLoading(false);
        clearPaymentMessage();
        lastQuote = { base_amount: 0, fee: 0, tax_amount: 0, final_amount: 0 };
        updateOrderSummary();
    }

    async function initEmbeddedPaymentSession() {
        const paymentContainer = document.getElementById('payment-element');
        if (!paymentContainer) return;

        if (!validateCurrentStep()) {
            return;
        }

        saveCurrentStepData();
        const signature = getBookingSignature();
        if (embeddedPaymentSession && embeddedPaymentSignature === signature) {
            setPaymentElementLoading(false);
            return;
        }

        resetEmbeddedPaymentSession();
        embeddedPaymentSignature = signature;
        setPaymentElementLoading(true);

        try {
            const response = await fetch(window.location.href, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-Requested-With': 'XMLHttpRequest'
                },
                body: JSON.stringify({
                    booking_data: {
                        ...bookingData,
                        parental_waiver: bookingData.parental_waiver
                            || window.__parentalWaiverAcceptance
                            || null,
                        payment_flow: 'embedded',
                    }
                })
            });
            const result = await response.json();
            if (!response.ok || !result.success) {
                throw new Error(result.message || result.error || 'Payment initialization failed.');
            }

            const paymentRequired = result.payment_required !== false
                && (result.base_amount_cents == null || result.base_amount_cents > 0)
                && !!result.client_secret;

            embeddedPaymentSession = {
                booking_id: result.booking_id || null,
                payment_intent_id: result.payment_intent_id,
                client_secret: result.client_secret || null,
                payment_plan: result.payment_plan,
                success_url: result.success_url,
                publishable_key: result.publishable_key || window.paymentConfig?.publishableKey,
                payment_required: paymentRequired,
                base_amount_cents: result.base_amount_cents != null ? result.base_amount_cents : null,
            };

            console.log("Embedded payment session initialized:", {
                booking_id: embeddedPaymentSession.booking_id,
                payment_intent_id: embeddedPaymentSession.payment_intent_id,
                payment_required: paymentRequired,
                base_amount_cents: embeddedPaymentSession.base_amount_cents,
                has_client_secret: !!embeddedPaymentSession.client_secret
            });

            if (!paymentRequired) {
                showFreePaymentUI();
                return;
            }

            if (!embeddedPaymentSession.client_secret || !embeddedPaymentSession.publishable_key) {
                throw new Error('Payment is not ready. Please refresh the page.');
            }

            stripeInstance = Stripe(embeddedPaymentSession.publishable_key);
            elementsInstance = stripeInstance.elements({
                clientSecret: embeddedPaymentSession.client_secret,
                paymentMethodCreation: "manual",
                appearance: {
                    variables: {
                        fontFamily: '"Source Sans Pro", sans-serif',
                    },
                },
            });
            paymentElementInstance = elementsInstance.create("payment", {
                paymentMethodOrder: ["card", "us_bank_account"],
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
            paymentElementInstance.on("ready", () => {
                setPaymentElementLoading(false);
            });
            paymentElementInstance.mount("#payment-element");

            paymentElementInstance.on("change", (event) => {
                updateAchPaymentHint(event);
                if (!event.complete) {
                    lastPaymentMethodId = null;
                    lastQuote = null;
                    updateOrderSummary();
                    return;
                }
                if (quoteTimer) {
                    clearTimeout(quoteTimer);
                }
                quoteTimer = setTimeout(() => {
                    requestEmbeddedQuote(true);
                }, 500);
            });
        } catch (error) {
            console.error('Embedded payment init error:', error);
            setPaymentElementLoading(false);
            showCustomAlert(error.message || 'Payment is not ready. Please try again.');
            resetEmbeddedPaymentSession();
        }
    }

    async function requestEmbeddedQuote(silent = false) {
        if (embeddedPaymentSession && embeddedPaymentSession.payment_required === false) {
            lastQuote = { base_amount: 0, fee: 0, tax_amount: 0, final_amount: 0 };
            updateOrderSummary();
            return true;
        }
        if (quoteInFlight || !elementsInstance) {
            console.log("Quote request blocked:", { quoteInFlight, hasElements: !!elementsInstance });
            return false;
        }
        
        // 确保 embeddedPaymentSession 已初始化
        if (!embeddedPaymentSession) {
            console.log("Embedded payment session not initialized, initializing...");
            await initEmbeddedPaymentSession();
            if (!embeddedPaymentSession) {
                console.error("Failed to initialize embedded payment session");
                if (!silent) {
                    showPaymentMessage('Payment is not ready. Please refresh the page.');
                }
                return false;
            }
        }
        
        quoteInFlight = true;
        clearPaymentMessage();

        const { error: submitError } = await elementsInstance.submit();
        if (submitError) {
            quoteInFlight = false;
            if (!silent) {
                showPaymentMessage('Please complete your card details before continuing.');
            }
            return false;
        }

        const { error, paymentMethod } = await stripeInstance.createPaymentMethod({
            elements: elementsInstance,
        });

        if (error || !paymentMethod || !paymentMethod.id) {
            quoteInFlight = false;
            if (!silent) {
                showPaymentMessage('Please complete your card details before continuing.');
            }
            return false;
        }

        if (paymentMethod.id === lastPaymentMethodId) {
            quoteInFlight = false;
            return true;
        }
        lastPaymentMethodId = paymentMethod.id;

        try {
            // 新流程：使用 payment_intent_id（还没有创建Booking）
            const requestBody = {
                payment_method_id: paymentMethod.id,
                payment_step: "initial",
            };
            
            // 如果有 payment_intent_id，使用它（新流程）
            if (embeddedPaymentSession && embeddedPaymentSession.payment_intent_id) {
                requestBody.payment_intent_id = embeddedPaymentSession.payment_intent_id;
                console.log("Using payment_intent_id for quote:", embeddedPaymentSession.payment_intent_id);
            } 
            // 如果有 booking_id，使用它（旧流程或已存在的Booking）
            else if (embeddedPaymentSession && embeddedPaymentSession.booking_id) {
                requestBody.booking_id = embeddedPaymentSession.booking_id;
                console.log("Using booking_id for quote:", embeddedPaymentSession.booking_id);
            } else {
                console.error("No payment_intent_id or booking_id in embeddedPaymentSession:", embeddedPaymentSession);
                if (!silent) {
                    showPaymentMessage('Payment session not initialized. Please refresh the page.');
                }
                quoteInFlight = false;
                return false;
            }
            
            console.log("Sending quote request:", requestBody);
            const response = await fetch("/api/payment/quote", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(requestBody),
            });
            console.log("Quote response status:", response.status, response.statusText);
            const result = await response.json();
            if (!response.ok) {
                console.error("Quote request failed:", result);
                throw new Error(result.error || result.message || "Quote failed");
            }
            console.log("Quote received:", result);
            lastQuote = result;
            updateOrderSummary();
            updateEmbeddedSummary(result);
        } catch (err) {
            console.error("Quote request error:", err);
            if (!silent) {
                showPaymentMessage(err.message || 'Payment failed. Please try again.');
            }
        } finally {
            quoteInFlight = false;
        }
        return true;
    }

    async function submitEmbeddedPayment() {
        if (!embeddedPaymentSession) {
            await initEmbeddedPaymentSession();
            if (!embeddedPaymentSession) {
                var btn = submitButton || nextButton;
                if (btn) { btn.disabled = false; btn.textContent = 'Confirm Booking'; }
                return;
            }
        }

        // $0 首付（免定金 / 折扣覆盖 Due at Booking）：不走 Stripe
        const isFreeCheckout = embeddedPaymentSession.payment_required === false
            || (embeddedPaymentSession.base_amount_cents != null && embeddedPaymentSession.base_amount_cents <= 0)
            || (typeof embeddedPaymentSession.payment_intent_id === 'string'
                && embeddedPaymentSession.payment_intent_id.indexOf('free_') === 0);

        if (isFreeCheckout && embeddedPaymentSession.payment_intent_id) {
            console.log('$0 payment detected, creating booking directly...');
            showBookingModalResult('loading');
            try {
                const response = await fetch('/api/booking/create-free', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        payment_intent_id: embeddedPaymentSession.payment_intent_id
                    })
                });
                const result = await response.json();
                
                if (result.success && result.booking_id) {
                    console.log('Free booking created successfully:', result);
                    showBookingModalResult('success', {
                        booking_id: result.booking_id,
                        receipt_url: result.receipt_url,
                        payment_intent_id: embeddedPaymentSession.payment_intent_id
                    });
                    var btn = submitButton || nextButton;
                    if (btn) { btn.disabled = false; btn.textContent = 'Confirm Booking'; }
                    return;
                } else {
                    throw new Error(result.message || 'Failed to create booking');
                }
            } catch (error) {
                console.error('Error creating free booking:', error);
                showBookingModalResult('failure', {
                    message: (error && error.message) || 'We could not complete your booking. Please try again.'
                });
                var btn = submitButton || nextButton;
                if (btn) { btn.disabled = false; btn.textContent = 'Confirm Booking'; }
                return;
            }
        }

        if (!lastQuote) {
            await requestEmbeddedQuote(false);
            if (!lastQuote) {
                var btn = submitButton || nextButton;
                if (btn) { btn.disabled = false; btn.textContent = 'Confirm Booking'; }
                return;
            }
        }

        showBookingModalResult('loading');
        try {
            // 新流程：使用 payment_intent_id（还没有创建Booking）
            const requestBody = {
                installment_id: null,
                payment_method_id: lastPaymentMethodId,
                payment_plan: embeddedPaymentSession.payment_plan || "full",
                payment_step: "initial",
            };
            
            // 如果有 payment_intent_id，使用它（新流程）
            if (embeddedPaymentSession.payment_intent_id) {
                requestBody.payment_intent_id = embeddedPaymentSession.payment_intent_id;
            } 
            // 如果有 booking_id，使用它（旧流程或已存在的Booking）
            else if (embeddedPaymentSession.booking_id) {
                requestBody.booking_id = embeddedPaymentSession.booking_id;
            }
            
            const response = await fetch("/api/payment/intent", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(requestBody),
            });
            const result = await response.json();
            if (!response.ok) {
                throw new Error(result.error || "Payment update failed");
            }

            const { error, paymentIntent } = await stripeInstance.confirmPayment({
                elements: elementsInstance,
                confirmParams: {
                    return_url: embeddedPaymentSession.success_url,
                },
                redirect: 'if_required',
            });
            if (error) {
                showBookingModalResult('failure', { error: error });
            } else {
                const pi = embeddedPaymentSession.payment_intent_id
                    || (paymentIntent && paymentIntent.id);
                if (paymentIntent && paymentIntent.status === 'processing') {
                    showBookingModalResult('processing', {
                        booking_id: null,
                        payment_intent_id: pi,
                    });
                    if (pi) pollPaymentStatusThenShowResult(pi);
                } else if (pi) {
                    pollPaymentStatusThenShowResult(pi);
                } else {
                    showBookingModalResult('failure', {
                        message: 'Payment confirmation did not return a session. Please try again.'
                    });
                }
            }
        } catch (err) {
            showBookingModalResult('failure', {
                message: (err && err.message) || PAYMENT_FAILURE_FALLBACK
            });
        } finally {
            var btn = submitButton || nextButton;
            if (btn) { btn.disabled = false; btn.textContent = 'Confirm Booking'; }
        }
    }

    function setPaymentElementLoading(show) {
        const el = document.getElementById('payment-element-loading');
        if (!el) return;
        el.setAttribute('aria-hidden', show ? 'false' : 'true');
    }

    function updateAchPaymentHint(event) {
        var hint = document.getElementById('ach-payment-hint');
        if (!hint) return;
        var type = (event && event.value && event.value.type) || '';
        hint.classList.toggle('hidden', type !== 'us_bank_account');
    }

    function resetEmbeddedPaymentSession() {
        if (paymentElementInstance) {
            try {
                paymentElementInstance.unmount();
            } catch (err) {
                console.warn('Payment element unmount failed', err);
            }
        }
        const paymentContainer = document.getElementById('payment-element');
        if (paymentContainer) {
            paymentContainer.innerHTML = '';
            paymentContainer.classList.remove('is-free-checkout');
        }
        document.querySelectorAll('.payment-card-fee-hint.is-free-hidden').forEach(function(el) {
            el.classList.remove('is-free-hidden');
        });
        embeddedPaymentSession = null;
        embeddedPaymentSignature = null;
        stripeInstance = null;
        elementsInstance = null;
        paymentElementInstance = null;
        lastPaymentMethodId = null;
        lastQuote = null;
        setPaymentElementLoading(false);
    }

    /**
     * 关闭成功页 / 再开 Book Now 时调用：退出结果态并清掉已完成的支付会话，
     * 避免再次打开仍停在「Booking Confirmed」或复用已完成的 free_/pi_。
     * @param {{ keepFormData?: boolean, goToPayment?: boolean }} opts
     */
    function prepareNewBooking(opts) {
        opts = opts || {};
        var keepFormData = !!opts.keepFormData;
        var goToPayment = !!opts.goToPayment;

        showBookingModalResult(null);
        resetEmbeddedPaymentSession();

        if (!keepFormData) {
            bookingData.discount_code = null;
            bookingData.discount_code_id = null;
            bookingData.discount_amount = 0;
            bookingData.parental_waiver = null;
            window.__parentalWaiverAcceptance = null;
            var codeInput = document.getElementById('discount-code-input');
            if (codeInput) codeInput.value = '';
            var discountInputSection = document.getElementById('discount-input-section');
            var discountApplied = document.getElementById('discount-applied');
            var discountMessage = document.getElementById('discount-message');
            if (discountInputSection) discountInputSection.classList.remove('hidden');
            if (discountApplied) discountApplied.classList.add('hidden');
            if (discountMessage) {
                discountMessage.textContent = '';
                discountMessage.className = '';
                discountMessage.classList.add('hidden');
            }
        }

        if (goToPayment && stepContainers && stepContainers.length) {
            showStep(stepContainers.length);
        } else {
            showStep(1);
        }

        if (typeof updateOrderSummary === 'function') {
            try { updateOrderSummary(); } catch (e) {}
        }
        requestAnimationFrame(function() {
            syncBookingModalBodyMinHeight();
        });
    }

    /**
     * 桌面端（lg）下将 #booking-modal-scroll 的 minHeight 设为
     * max(#booking-modal-left-inner, #booking-modal-right)，避免右侧 Your Booking 被折叠。
     * 先清空 minHeight 让左右列按内容自然高度 reflow，再测量并设置。
     * options.preserveMin：结果态用合理下限（如 280），按内容伸缩，不再锁死付款表单高度。
     */
    function syncBookingModalBodyMinHeight(options) {
        options = options || {};
        var preserveMin = Number(options.preserveMin) || 0;
        var scrollEl = document.getElementById('booking-modal-scroll');
        var leftInner = document.getElementById('booking-modal-left-inner');
        var rightEl = document.getElementById('booking-modal-right');
        if (!scrollEl) return;
        if (!leftInner || !rightEl) {
            scrollEl.style.minHeight = '';
            return;
        }
        if (window.innerWidth < 1024) {
            scrollEl.style.minHeight = '';
            return;
        }
        scrollEl.style.minHeight = '';
        requestAnimationFrame(function() {
            var h = Math.max(leftInner.offsetHeight, rightEl.offsetHeight, preserveMin);
            scrollEl.style.minHeight = h + 'px';
        });
    }

    /** 结果态高度下限：防塌陷，但不沿用付款表单的超高 minHeight */
    var BOOKING_RESULT_HEIGHT_FLOOR = 280;

    var PAYMENT_FAILURE_FALLBACK = 'Your payment could not be completed. Please try again.';

    /**
     * Stripe error / 字符串 → 对客可读原因（不展示技术 code）
     */
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
            lost_card: 'Your card was declined. Please contact your bank.',
            stolen_card: 'Your card was declined. Please contact your bank.',
            expired_card: 'Your card has expired.',
            incorrect_cvc: 'Your card’s security code is incorrect.',
            incorrect_number: 'Your card number is incorrect.',
            card_declined: 'Your card was declined. Please try another card or contact your bank.',
            processing_error: 'We could not process your card. Please try again.',
            generic_decline: 'Your card was declined. Please try another card or contact your bank.'
        };
        return (code && map[code]) || PAYMENT_FAILURE_FALLBACK;
    }

    function setBookingFailureReason(errorOrMsg) {
        var reasonWrap = document.getElementById('booking-result-failure-reason');
        var detailEl = document.getElementById('booking-result-failure-detail');
        var text = formatPaymentFailureMessage(errorOrMsg);
        if (detailEl) detailEl.textContent = text;
        if (reasonWrap) {
            if (text) reasonWrap.removeAttribute('hidden');
            else reasonWrap.setAttribute('hidden', '');
        }
    }

    /**
     * 在弹窗左侧显示付款结果：loading | success | failure，传 null 则恢复表单
     * data: { booking_id, receipt_url, message / error }
     */
    function showBookingModalResult(state, data) {
        const resultWrap = document.getElementById('booking-modal-result');
        const formArea = document.getElementById('modal-form-area');
        const btnBar = document.getElementById('booking-modal-btn-bar');
        const loadingEl = document.getElementById('booking-result-loading');
        const successEl = document.getElementById('booking-result-success');
        const processingEl = document.getElementById('booking-result-processing');
        const failureEl = document.getElementById('booking-result-failure');
        const receiptLink = document.getElementById('booking-result-receipt-link');
        const receiptWrap = document.getElementById('booking-result-receipt-wrap');
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
            var amountPaidRow = document.getElementById('amount-paid-row');
            if (amountPaidRow) amountPaidRow.classList.add('hidden');
            // 恢复折扣码（已应用则继续隐藏输入框，仅显示已应用行）
            var discountInputSection = document.getElementById('discount-input-section');
            var discountApplied = document.getElementById('discount-applied');
            var removeDiscountBtn = document.getElementById('remove-discount-btn');
            if (bookingData && bookingData.discount_code) {
                if (discountInputSection) discountInputSection.classList.add('hidden');
                if (discountApplied) discountApplied.classList.remove('hidden');
            } else {
                if (discountInputSection) discountInputSection.classList.remove('hidden');
                if (discountApplied) discountApplied.classList.add('hidden');
            }
            if (removeDiscountBtn) removeDiscountBtn.classList.remove('hidden');
            requestAnimationFrame(function() { syncBookingModalBodyMinHeight(); });
            return;
        }

        // 结果态：按内容测高 + 合理下限，避免沿用付款表单高度造成大块空白
        formArea.classList.add('hidden');
        btnBar.classList.add('hidden');
        resultWrap.classList.remove('hidden');
        resultWrap.setAttribute('aria-hidden', 'false');
        resultWrap.style.minHeight = BOOKING_RESULT_HEIGHT_FLOOR + 'px';
        resultWrap.classList.remove('is-visible');
        // 强制 reflow 后再加淡入，避免瞬间闪切
        void resultWrap.offsetWidth;
        resultWrap.classList.add('is-visible');
        if (loadingEl) loadingEl.classList.add('hidden');
        if (successEl) successEl.classList.add('hidden');
        if (processingEl) processingEl.classList.add('hidden');
        if (failureEl) failureEl.classList.add('hidden');

        // 付款结果页：整块折扣 UI 不显示（输入 / 已应用 / Remove / 提示）
        var discountInputSection = document.getElementById('discount-input-section');
        var discountApplied = document.getElementById('discount-applied');
        var discountMessage = document.getElementById('discount-message');
        var removeDiscountBtn = document.getElementById('remove-discount-btn');
        if (discountInputSection) discountInputSection.classList.add('hidden');
        if (discountApplied) discountApplied.classList.add('hidden');
        if (discountMessage) discountMessage.classList.add('hidden');
        if (removeDiscountBtn) removeDiscountBtn.classList.add('hidden');

        if (state === 'loading') {
            if (loadingEl) loadingEl.classList.remove('hidden');
        } else if (state === 'processing') {
            if (processingEl) processingEl.classList.remove('hidden');
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
        } else if (state === 'failure') {
            if (failureEl) failureEl.classList.remove('hidden');
            setBookingFailureReason(
                (data && (data.message || data.error_message || data.error)) || PAYMENT_FAILURE_FALLBACK
            );
        }
        // 付款结果页：有 booking_id 时用接口拉取金额填充 Your Booking，否则用 updateOrderSummary；高亮 Payment 步骤
        requestAnimationFrame(function() {
            syncBookingModalBodyMinHeight({ preserveMin: BOOKING_RESULT_HEIGHT_FLOOR });
            var bid = state === 'success' && data && data.booking_id ? data.booking_id : null;
            if (bid) {
                var summaryUrl = '/api/booking/' + bid + '/summary';
                var piForSummary = (data && data.payment_intent_id)
                    || (typeof embeddedPaymentSession !== 'undefined' && embeddedPaymentSession && embeddedPaymentSession.payment_intent_id)
                    || null;
                if (piForSummary) {
                    summaryUrl += '?payment_intent_id=' + encodeURIComponent(piForSummary);
                } else if (data && data.receipt_token) {
                    summaryUrl += '?token=' + encodeURIComponent(data.receipt_token);
                }
                fetch(summaryUrl)
                    .then(function(r) { return r.ok ? r.json() : null; })
                    .then(function(summary) {
                        if (!summary) return;
                        var orderSummaryEl = document.getElementById('order-summary');
                        var tripTotalEl = document.getElementById('trip-total-amount');
                        var feeAmountEl = document.getElementById('fee-amount');
                        var totalAmountEl = document.getElementById('total-amount');
                        if (orderSummaryEl && summary.order_summary_lines && summary.order_summary_lines.length) {
                            var html = summary.order_summary_lines.map(function(line) {
                                return '<div class="flex justify-between"><span>' + (line.label || '') + '</span><span>$' + formatCurrency(line.amount) + '</span></div>';
                            }).join('');
                            orderSummaryEl.innerHTML = html;
                        } else if (orderSummaryEl) {
                            orderSummaryEl.innerHTML = '<p class="text-gray-500">Booking total below.</p>';
                        }
                        if (tripTotalEl) tripTotalEl.textContent = '$' + formatCurrency(summary.trip_total);
                        if (feeAmountEl) {
                            feeAmountEl.textContent = '$' + formatCurrency(summary.fee);
                            feeAmountEl.classList.toggle('text-zinc-900', (summary.fee || 0) > 0);
                            feeAmountEl.classList.toggle('text-zinc-500', !(summary.fee > 0));
                        }
                        if (totalAmountEl) totalAmountEl.textContent = '$' + formatCurrency(summary.due_at_booking);
                        var amountPaidEl = document.getElementById('amount-paid');
                        var amountPaidRow = document.getElementById('amount-paid-row');
                        var paidDisplay = (summary.amount_paid != null) ? summary.amount_paid : summary.due_at_booking;
                        if (amountPaidEl) amountPaidEl.textContent = '$' + formatCurrency(paidDisplay);
                        if (amountPaidRow) amountPaidRow.classList.remove('hidden');
                        if (receiptLink && bid) {
                            var onum = summary.order_number || bid;
                            receiptLink.href = summary.receipt_url || ('/booking/' + bid + '/receipt');
                            receiptLink.setAttribute('download', 'NHTours-Order-' + onum + '.pdf');
                        }
                        syncBookingModalBodyMinHeight({ preserveMin: BOOKING_RESULT_HEIGHT_FLOOR });
                    })
                    .catch(function() { if (typeof updateOrderSummary === 'function') updateOrderSummary(); });
            } else {
                if (typeof updateOrderSummary === 'function') updateOrderSummary();
                syncBookingModalBodyMinHeight({ preserveMin: BOOKING_RESULT_HEIGHT_FLOOR });
            }
            var paymentStep = stepContainers.length;
            document.querySelectorAll('.modal-step-tab').forEach(function(tab) {
                var tabStep = parseInt(tab.getAttribute('data-step'), 10);
                tab.style.color = (tabStep === paymentStep) ? '#1f2937' : '#9ca3af';
                tab.setAttribute('aria-selected', tabStep === paymentStep ? 'true' : 'false');
            });
        });
    }

    /** 轮询支付状态，成功后显示结果在弹窗内 */
    function pollPaymentStatusThenShowResult(paymentIntentId) {
        const statusUrl = '/api/payment/status?payment_intent_id=' + encodeURIComponent(paymentIntentId);
        var polls = 0;
        function poll() {
            fetch(statusUrl)
                .then(function(res) { return res.json(); })
                .then(function(data) {
                    if (data.status === 'succeeded') {
                        showBookingModalResult('success', {
                            booking_id: data.booking_id,
                            receipt_url: data.receipt_url,
                            payment_intent_id: paymentIntentId || data.payment_intent_id
                        });
                        var btn = submitButton || nextButton;
                        if (btn) { btn.disabled = false; btn.textContent = 'Confirm Booking'; }
                        return;
                    }
                    if (data.status === 'processing') {
                        showBookingModalResult('processing', {
                            booking_id: data.booking_id,
                            payment_intent_id: paymentIntentId || data.payment_intent_id
                        });
                        var btnP = submitButton || nextButton;
                        if (btnP) { btnP.disabled = false; btnP.textContent = 'Confirm Booking'; }
                        return;
                    }
                    if (data.status === 'failed') {
                        showBookingModalResult('failure', {
                            message: data.error_message || data.message || PAYMENT_FAILURE_FALLBACK
                        });
                        var btn = submitButton || nextButton;
                        if (btn) { btn.disabled = false; btn.textContent = 'Confirm Booking'; }
                        return;
                    }
                    polls += 1;
                    if (polls > 45) {
                        // After ~90s still pending: show processing tip (ACH may lag webhook)
                        showBookingModalResult('processing', {
                            booking_id: data.booking_id || null,
                            payment_intent_id: paymentIntentId
                        });
                        return;
                    }
                    setTimeout(poll, 2000);
                })
                .catch(function() { setTimeout(poll, 2000); });
        }
        poll();
    }

    function showPaymentMessage(text) {
        const messageElement = document.getElementById('payment-message');
        if (!messageElement) return;
        messageElement.textContent = text;
        messageElement.classList.remove('hidden');
    }

    function clearPaymentMessage() {
        const messageElement = document.getElementById('payment-message');
        if (!messageElement) return;
        messageElement.textContent = '';
        messageElement.classList.add('hidden');
    }

    /**
     * 显示自定义提示框
     */
    function showCustomAlert(message, title = 'Notice') {
        // 移除已存在的提示框
        const existingAlert = document.getElementById('custom-alert');
        const existingOverlay = document.getElementById('custom-alert-overlay');
        if (existingAlert) existingAlert.remove();
        if (existingOverlay) existingOverlay.remove();
        
        // 创建遮罩层
        const overlay = document.createElement('div');
        overlay.id = 'custom-alert-overlay';
        overlay.className = 'custom-alert-overlay';
        overlay.addEventListener('click', function() {
            closeCustomAlert();
        });
        
        // 创建提示框
        const alert = document.createElement('div');
        alert.id = 'custom-alert';
        alert.className = 'custom-alert';
        alert.innerHTML = `
            <div class="custom-alert-title">${title}</div>
            <div class="custom-alert-message">${message}</div>
            <button class="custom-alert-button" onclick="closeCustomAlert()">OK</button>
        `;
        
        document.body.appendChild(overlay);
        document.body.appendChild(alert);
        
        // 按ESC键关闭
        const escHandler = function(e) {
            if (e.key === 'Escape') {
                closeCustomAlert();
                document.removeEventListener('keydown', escHandler);
            }
        };
        document.addEventListener('keydown', escHandler);
    }
    
    /**
     * 关闭自定义提示框
     */
    function closeCustomAlert() {
        const alert = document.getElementById('custom-alert');
        const overlay = document.getElementById('custom-alert-overlay');
        if (alert) {
            alert.style.animation = 'alertFadeIn 0.2s ease-out reverse';
            setTimeout(() => alert.remove(), 200);
        }
        if (overlay) {
            overlay.style.animation = 'overlayFadeIn 0.2s ease-out reverse';
            setTimeout(() => overlay.remove(), 200);
        }
    }
    
    // 将函数暴露到全局，以便HTML中的onclick可以调用
    window.closeCustomAlert = closeCustomAlert;

    // 页面加载完成后初始化
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    // 导出到全局（如果需要）
    window.BookingWizard = {
        getBookingData: () => bookingData,
        goToStep: (step) => showStep(step),
        getCurrentStep: () => currentStep,
        syncModalBodyMinHeight: syncBookingModalBodyMinHeight,
        prepareNewBooking: prepareNewBooking,
        resetEmbeddedPaymentSession: resetEmbeddedPaymentSession,
        showBookingModalResult: showBookingModalResult,
        setParentalWaiver: function(payload) {
            bookingData.parental_waiver = payload || null;
            if (payload) {
                window.__parentalWaiverAcceptance = payload;
            }
        }
    };

})();
