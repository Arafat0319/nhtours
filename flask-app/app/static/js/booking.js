/**
 * 多步骤报名表单 JavaScript
 * 处理：购买者信息 → 选择套餐 → 选择附加项 → 参与者信息 → 支付
 */

(function() {
    'use strict';

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
        payment_method: 'full'
    };

    // DOM 元素
    let stepContainers = [];
    let stepButtons = [];
    let nextButton, prevButton, submitButton;
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
        prevButton = document.getElementById('prevBtn');
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
        if (prevButton) prevButton.addEventListener('click', handlePrev);
        if (submitButton) submitButton.addEventListener('click', handleSubmit);

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

        // 监听package quantity变化，更新卡片样式
        document.addEventListener('input', function(e) {
            if (e.target.matches('input.package-quantity')) {
                const quantityInput = e.target;
                const quantity = parseInt(quantityInput.value) || 0;
                const packageCard = quantityInput.closest('.package-card');
                
                if (packageCard) {
                    if (quantity > 0) {
                        packageCard.classList.add('selected');
                    } else {
                        packageCard.classList.remove('selected');
                    }
                }
            }
            
            // 监听addon quantity变化，更新卡片样式
            if (e.target.matches('input.addon-quantity')) {
                const quantityInput = e.target;
                const quantity = parseInt(quantityInput.value) || 0;
                const addonCard = quantityInput.closest('.addon-card');
                
                if (addonCard) {
                    if (quantity > 0) {
                        addonCard.classList.add('selected');
                    } else {
                        addonCard.classList.remove('selected');
                    }
                }
            }
        });
        
        // 监听套餐和附加项变化，更新订单总结和参与者数量
        document.addEventListener('change', function(e) {
            if (e.target.matches('input.package-quantity, input.addon-quantity')) {
                // 如果是在步骤2，更新参与者数量
                if (currentStep === 2) {
                    const step2Container = document.querySelector('.booking-step[data-step="2"]');
                    if (step2Container) {
                        savePackagesData(step2Container);
                        updateParticipantCount();
                    }
                }
                // 如果在步骤3，保存addon数据
                if (currentStep === 3) {
                    const step3Container = document.querySelector('.booking-step[data-step="3"]');
                    if (step3Container) {
                        saveAddonsData(step3Container);
                    }
                }
                // 如果在步骤4，更新订单总结
                if (currentStep === 4) {
                    updateOrderSummary();
                }
            }
        });

        // 初始化第一步 - 确保步骤1正确显示
        currentStep = 1;
        showStep(1);
        
        // 初始化package quantity状态，更新卡片样式
        const packageQuantityInputs = document.querySelectorAll('input.package-quantity');
        packageQuantityInputs.forEach(input => {
            const quantity = parseInt(input.value) || 0;
            const packageCard = input.closest('.package-card');
            if (packageCard) {
                if (quantity > 0) {
                    packageCard.classList.add('selected');
                } else {
                    packageCard.classList.remove('selected');
                }
            }
        });
        
        // 初始化addon quantity状态，更新卡片样式
        const addonQuantityInputs = document.querySelectorAll('input.addon-quantity');
        addonQuantityInputs.forEach(input => {
            const quantity = parseInt(input.value) || 0;
            const addonCard = input.closest('.addon-card');
            if (addonCard) {
                if (quantity > 0) {
                    addonCard.classList.add('selected');
                } else {
                    addonCard.classList.remove('selected');
                }
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
            if (prevButton) {
                prevButton.style.display = 'none';
                prevButton.classList.add('hidden');
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

        if (step === 5) {
            initEmbeddedPaymentSession();
        } else {
            resetEmbeddedPaymentSession();
        }
        
        // 如果到了第4步（参与者），根据package数量生成表单
        if (step === 4) {
            updateParticipantCount();
        }
        
        // 如果到了第5步（支付），更新订单总结
        if (step === 5) {
            // 确保所有步骤的数据都已保存（特别是步骤2、3、4）
            saveAllStepsData();
            
            // 延迟更新，确保DOM已完全渲染
            setTimeout(() => {
                updateOrderSummary();
            }, 150);
        }
    }

    /**
     * 更新按钮状态
     */
    function updateStepButtons() {
        if (prevButton) {
            // 第一页隐藏Previous按钮，从第二页开始显示
            if (currentStep === 1) {
                prevButton.style.display = 'none';
            } else {
                prevButton.style.display = 'inline-flex';
                prevButton.disabled = false;
                prevButton.classList.remove('opacity-50', 'cursor-not-allowed');
            }
        }

        if (nextButton) {
            const isLastStep = currentStep === stepContainers.length;
            // 最后一步隐藏Next按钮，其他步骤显示
            if (isLastStep) {
                nextButton.style.display = 'none';
            } else {
                nextButton.style.display = 'flex';
                nextButton.style.visibility = 'visible';
                nextButton.classList.remove('hidden');
            }
        }

        if (submitButton) {
            const isLastStep = currentStep === stepContainers.length;
            // 最后一步显示Submit按钮，其他步骤隐藏
            submitButton.style.display = isLastStep ? 'inline-flex' : 'none';
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

        // 显示下一步
        if (currentStep < stepContainers.length) {
            const nextStep = currentStep + 1;
            showStep(nextStep);
            
            // 如果下一步是步骤5，确保所有数据都已保存
            if (nextStep === 5) {
                // 再次保存所有步骤数据，确保数据完整
                setTimeout(() => {
                    saveAllStepsData();
                    updateOrderSummary();
                }, 200);
            }
        }
    }

    /**
     * 处理上一步
     */
    function handlePrev(e) {
        e.preventDefault();
        
        if (currentStep > 1) {
            showStep(currentStep - 1);
        }
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
                    field.scrollIntoView({ behavior: 'smooth', block: 'center' });
                    field.focus();
                }
            } else {
                // 移除错误样式
                field.classList.remove('border-red-500');
                field.classList.remove('border-2');
                field.style.borderColor = '';
                field.style.borderWidth = '';
                
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
            const handleInput = () => {
                if (field.value && field.value.trim()) {
                    field.classList.remove('border-red-500');
                    field.classList.remove('border-2');
                    field.style.borderColor = '';
                    field.style.borderWidth = '';
                    const errorMsg = field.closest('.flex.flex-col')?.querySelector('.error-message');
                    if (errorMsg) {
                        errorMsg.remove();
                    }
                    field.removeEventListener('input', handleInput);
                    field.removeEventListener('change', handleInput);
                }
            };
            field.addEventListener('input', handleInput);
            field.addEventListener('change', handleInput);
        });

        // 特殊验证：步骤2（套餐选择）- 检查是否有quantity > 0的package
        if (currentStep === 2) {
            const packageQuantityInputs = currentContainer.querySelectorAll('input.package-quantity');
            let hasSelectedPackage = false;
            packageQuantityInputs.forEach(input => {
                const quantity = parseInt(input.value) || 0;
                if (quantity > 0) {
                    hasSelectedPackage = true;
                }
            });
            if (!hasSelectedPackage) {
                // 高亮所有套餐数量输入框
                packageQuantityInputs.forEach(input => {
                    input.classList.add('border-red-500');
                    input.classList.add('border-2');
                    input.style.borderColor = '#ef4444';
                    input.style.borderWidth = '2px';
                });
                isValid = false;
            }
        }
        
        // 步骤3（附加项）不需要验证，可以跳过
        // 步骤4（参与者）的验证
        if (currentStep === 4) {
            const participantForms = currentContainer.querySelectorAll('.participant-form');
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
                        
                        isValid = false;
                    }
                });
            });
        }
        
        // 步骤5（支付）需要验证参与者信息
        if (currentStep === 5) {
            const participants = bookingData.participants || [];
            if (participants.length === 0) {
                // 不显示 alert，只阻止继续
                isValid = false;
            }
        }

        return isValid;
    }

    /**
     * 保存当前步骤数据
     */
    function saveCurrentStepData() {
        const currentContainer = stepContainers[currentStep - 1];
        if (!currentContainer) return;

        switch (currentStep) {
            case 1: // 购买者信息
                saveBuyerInfoData(currentContainer);
                break;
            case 2: // 套餐选择
                savePackagesData(currentContainer);
                break;
            case 3: // 附加项选择
                saveAddonsData(currentContainer);
                break;
            case 4: // 参与者信息
                saveParticipantsData(currentContainer);
                break;
            case 5: // 支付总结
                // 支付步骤不需要保存数据，只是展示总结
                break;
        }
    }
    
    /**
     * 保存所有步骤的数据（用于在显示步骤5前确保数据完整）
     */
    function saveAllStepsData() {
        console.log('saveAllStepsData: saving all steps data');
        console.log('stepContainers length:', stepContainers.length);
        
        // 保存步骤2（套餐）
        const step2Container = stepContainers[1];
        console.log('Step 2 container:', step2Container ? 'found' : 'not found');
        if (step2Container) {
            savePackagesData(step2Container);
        } else {
            // 如果通过索引找不到，尝试通过选择器查找
            const step2Alt = document.querySelector('.booking-step[data-step="2"]');
            if (step2Alt) {
                console.log('Step 2 container found via selector');
                savePackagesData(step2Alt);
            }
        }
        
        // 保存步骤3（附加项）
        const step3Container = stepContainers[2];
        console.log('Step 3 container:', step3Container ? 'found' : 'not found');
        if (step3Container) {
            saveAddonsData(step3Container);
        } else {
            // 如果通过索引找不到，尝试通过选择器查找
            const step3Alt = document.querySelector('.booking-step[data-step="3"]');
            if (step3Alt) {
                console.log('Step 3 container found via selector');
                saveAddonsData(step3Alt);
            }
        }
        
        // 保存步骤4（参与者）
        const step4Container = stepContainers[3];
        console.log('Step 4 container:', step4Container ? 'found' : 'not found');
        if (step4Container) {
            saveParticipantsData(step4Container);
        } else {
            // 如果通过索引找不到，尝试通过选择器查找
            const step4Alt = document.querySelector('.booking-step[data-step="4"]');
            if (step4Alt) {
                console.log('Step 4 container found via selector');
                saveParticipantsData(step4Alt);
            }
        }
        
        console.log('saveAllStepsData: final bookingData', bookingData);
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
                // 从 tripData 中获取套餐的支付计划配置
                const packageData = tripData.packages?.find(p => p.id === packageId);
                let payment_plan_type = 'full';
                
                // 如果套餐有启用的分期付款配置，使用 deposit_installment
                if (packageData && packageData.payment_plan_config && 
                    packageData.payment_plan_config.enabled) {
                    payment_plan_type = 'deposit_installment';
                    console.log(`Package ${packageId} has enabled payment plan, using deposit_installment`);
                }
                
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
        
        // 如果当前在步骤5，更新订单总结
        if (currentStep === 5) {
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
        // 即使容器被隐藏，querySelectorAll 仍然可以工作
        const addonQuantityInputs = container.querySelectorAll('input.addon-quantity');
        
        console.log('saveAddonsData: found', addonQuantityInputs.length, 'addon inputs');
        
        addonQuantityInputs.forEach(input => {
            const addonId = parseInt(input.getAttribute('data-addon-id'));
            const quantity = parseInt(input.value) || 0;
            
            console.log('Addon input:', { addonId, quantity, value: input.value });
            
            // 只保存数量大于0的附加项
            if (quantity > 0 && addonId) {
                bookingData.addons.push({
                    addon_id: addonId,
                    package_id: null, // Add-ons 现在不绑定到特定 package
                    participant_id: null, // 可以后续关联到特定参与者
                    quantity: quantity
                });
            }
        });
        
        console.log('saveAddonsData: saved addons', bookingData.addons);
        
        // 如果当前在步骤5，更新订单总结
        if (currentStep === 5) {
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
            const participant = {
                // 默认必填字段（系统默认收集）
                first_name: form.querySelector('[name*="participant_first_name"]')?.value || '',
                last_name: form.querySelector('[name*="participant_last_name"]')?.value || '',
                email: form.querySelector('[name*="participant_email"]')?.value || '',
                // 构造器配置的自定义问题答案
                custom_answers: {}
            };
            
            // 收集所有构造器配置的问题答案
            if (window.tripData && window.tripData.custom_questions) {
                window.tripData.custom_questions.forEach(question => {
                    const fieldName = `participant_question_${question.id}_`;
                    const input = form.querySelector(`[name^="${fieldName}"]`);
                    if (input) {
                        participant.custom_answers[question.id] = {
                            question_id: question.id,
                            label: question.label,
                            value: input.value || ''
                        };
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
            if (fieldId) {
                const input = field.querySelector('input, textarea, select');
                if (input) {
                    // 收集所有字段值，包括空值（如果字段存在）
                    customInfo[fieldId] = input.value || '';
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
        fieldsHtml += `
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div class="flex flex-col">
                    <label class="block text-sm font-medium mb-2">*First Name</label>
                    <input type="text" name="participant_first_name_${participantIndex}" 
                        class="px-2 py-2 w-full border border-zinc-400 rounded-xs" required>
                </div>
                <div class="flex flex-col">
                    <label class="block text-sm font-medium mb-2">*Last Name</label>
                    <input type="text" name="participant_last_name_${participantIndex}" 
                        class="px-2 py-2 w-full border border-zinc-400 rounded-xs" required>
                </div>
            </div>
            <div class="mt-4">
                <div class="flex flex-col">
                    <label class="block text-sm font-medium mb-2">*Email</label>
                    <input type="email" name="participant_email_${participantIndex}" 
                        class="px-2 py-2 w-full border border-zinc-400 rounded-xs" required>
                </div>
            </div>
        `;
        
        // 2. 根据构造器配置的自定义问题生成字段
        if (window.tripData && window.tripData.custom_questions && window.tripData.custom_questions.length > 0) {
            window.tripData.custom_questions.forEach((question, qIndex) => {
                const fieldName = `participant_question_${question.id}_${participantIndex}`;
                const requiredAttr = question.required ? 'required' : '';
                const requiredMark = question.required ? '<span class="text-red-500 ml-1">*</span>' : '';
                
                // 根据问题类型生成对应的输入字段
                if (question.type === 'textarea') {
                    fieldsHtml += `
                        <div class="mt-4">
                            <label class="block text-sm font-medium mb-2">${question.label}${requiredMark}</label>
                            <textarea name="${fieldName}" 
                                class="px-2 py-2 w-full border border-zinc-400 rounded-xs" rows="4" ${requiredAttr}></textarea>
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
                            <label class="block text-sm font-medium mb-2">${question.label}${requiredMark}</label>
                            <select name="${fieldName}" 
                                class="px-2 py-2 w-full border border-zinc-400 rounded-xs" ${requiredAttr}>
                                ${optionsHtml}
                            </select>
                        </div>
                    `;
                } else if (question.type === 'date') {
                    fieldsHtml += `
                        <div class="mt-4">
                            <label class="block text-sm font-medium mb-2">${question.label}${requiredMark}</label>
                            <input type="date" name="${fieldName}" 
                                class="px-2 py-2 w-full border border-zinc-400 rounded-xs" ${requiredAttr}>
                        </div>
                    `;
                } else {
                    // text, email, phone 等文本类型
                    const inputType = question.type === 'email' ? 'email' : (question.type === 'phone' ? 'tel' : 'text');
                    fieldsHtml += `
                        <div class="mt-4">
                            <label class="block text-sm font-medium mb-2">${question.label}${requiredMark}</label>
                            <input type="${inputType}" name="${fieldName}" 
                                class="px-2 py-2 w-full border border-zinc-400 rounded-xs" ${requiredAttr}>
                        </div>
                    `;
                }
            });
        }
        
        const participantHtml = `
            <div class="participant-form border border-zinc-300 p-6 mb-4" data-index="${participantIndex}">
                <div class="flex justify-between items-center mb-6">
                    <h3 class="text-lg font-medium text-zinc-800 uppercase tracking-wide">Participant ${participantIndex}</h3>
                    ${participantIndex > 1 ? `<button type="button" class="remove-participant px-4 py-2 text-red-600 hover:text-red-800 hover:bg-red-50 rounded-xs text-sm font-medium transition-colors">Remove</button>` : ''}
                </div>
                ${fieldsHtml}
            </div>
        `;
        
        participantsContainer.insertAdjacentHTML('beforeend', participantHtml);
        
        // 绑定删除按钮
        const removeBtn = participantsContainer.querySelector(`.participant-form[data-index="${participantIndex}"] .remove-participant`);
        if (removeBtn) {
            removeBtn.addEventListener('click', function() {
                this.closest('.participant-form').remove();
                updateParticipantNumbers();
            });
        }
    }

    /**
     * 更新参与者编号
     */
    function updateParticipantNumbers() {
        const forms = participantsContainer.querySelectorAll('.participant-form');
        forms.forEach((form, index) => {
            const title = form.querySelector('h3');
            if (title) {
                title.textContent = `Participant ${index + 1}`;
            }
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
                    const lastNameInput = form.querySelector('[name*="participant_last_name"]');
                    const emailInput = form.querySelector('[name*="participant_email"]');
                    
                    if (firstNameInput) firstNameInput.value = participant.first_name || '';
                    if (lastNameInput) lastNameInput.value = participant.last_name || '';
                    if (emailInput) emailInput.value = participant.email || '';
                    
                    // 恢复自定义问题答案
                    if (participant.custom_answers && window.tripData && window.tripData.custom_questions) {
                        window.tripData.custom_questions.forEach(question => {
                            const fieldName = `participant_question_${question.id}_${index + 1}`;
                            const input = form.querySelector(`[name="${fieldName}"]`);
                            if (input && participant.custom_answers[question.id]) {
                                input.value = participant.custom_answers[question.id].value || '';
                            }
                        });
                    }
                }
            });
        }
    }

    /**
     * 更新订单总结
     */
    function updateOrderSummary() {
        // 重新获取DOM元素，确保它们存在
        if (!orderSummaryEl) {
            orderSummaryEl = document.getElementById('order-summary');
        }
        if (!totalAmountEl) {
            totalAmountEl = document.getElementById('total-amount');
        }
        
        if (!orderSummaryEl || !totalAmountEl) {
            console.warn('Order summary elements not found');
            return;
        }
        
        // 确保 tripData 已初始化
        if (!tripData || !window.tripData) {
            tripData = window.tripData || {};
            console.warn('tripData not initialized, using window.tripData:', tripData);
        } else {
            // 同步 tripData
            tripData = window.tripData || tripData;
        }
        
        console.log('updateOrderSummary: tripData', tripData);
        console.log('updateOrderSummary: tripData.packages', tripData.packages);
        console.log('updateOrderSummary: tripData.addons', tripData.addons);
        
        let total = 0;
        let html = '';
        
        // 确保 bookingData.packages 存在
        if (!bookingData.packages) {
            bookingData.packages = [];
        }
        
        // 计算套餐金额
        // 对于分期付款，使用押金金额；对于全款，使用全价
        console.log('updateOrderSummary: bookingData.packages', bookingData.packages);
        console.log('updateOrderSummary: tripData.packages', tripData.packages);
        
        bookingData.packages.forEach(pkg => {
            console.log('Processing package:', pkg);
            const packageData = tripData.packages?.find(p => p.id === pkg.package_id);
            console.log('Found package data:', packageData);
            
            if (packageData) {
                let subtotal = 0;
                let displayName = packageData.name;
                
                // 如果是分期付款，使用押金金额
                if (pkg.payment_plan_type === 'deposit_installment' && 
                    packageData.payment_plan_config && 
                    packageData.payment_plan_config.enabled) {
                    const depositAmount = parseFloat(packageData.payment_plan_config.deposit_amount || 0);
                    subtotal = depositAmount * pkg.quantity;
                    displayName = `${packageData.name} (Deposit)`;
                    
                    // 检查是否有过期分期（需要合并到首付款）
                    const today = new Date();
                    today.setHours(0, 0, 0, 0);
                    const installments = packageData.payment_plan_config.installments || [];
                    let overdueTotal = 0;
                    
                    installments.forEach(inst => {
                        if (inst.date) {
                            const dueDate = new Date(inst.date);
                            dueDate.setHours(0, 0, 0, 0);
                            if (dueDate < today) {
                                overdueTotal += parseFloat(inst.amount || 0) * pkg.quantity;
                            }
                        }
                    });
                    
                    if (overdueTotal > 0) {
                        subtotal += overdueTotal;
                        displayName = `${packageData.name} (Deposit + Overdue)`;
                    }
                } else {
                    // 全款支付：使用套餐全价
                    subtotal = packageData.price * pkg.quantity;
                }
                
                total += subtotal;
                html += `
                    <div class="flex justify-between">
                        <span>${displayName} x${pkg.quantity}</span>
                        <span>$${subtotal.toFixed(2)}</span>
                    </div>
                `;
            } else {
                console.warn('Package data not found for package_id:', pkg.package_id);
            }
        });
        
        // 确保 bookingData.addons 存在
        if (!bookingData.addons) {
            bookingData.addons = [];
        }
        
        // 计算附加项金额
        console.log('updateOrderSummary: bookingData.addons', bookingData.addons);
        console.log('updateOrderSummary: tripData.addons', tripData.addons);
        
        bookingData.addons.forEach(addon => {
            console.log('Processing addon:', addon);
            const addonData = tripData.addons?.find(a => a.id === addon.addon_id);
            console.log('Found addon data:', addonData);
            
            if (addonData) {
                const subtotal = addonData.price * addon.quantity;
                total += subtotal;
                html += `
                    <div class="flex justify-between text-sm text-gray-600">
                        <span>+ ${addonData.name} x${addon.quantity}</span>
                        <span>$${subtotal.toFixed(2)}</span>
                    </div>
                `;
            } else {
                console.warn('Addon data not found for addon_id:', addon.addon_id);
            }
        });
        
        // 计算 subtotal（折扣前、fee前的金额）
        const subtotal = total;
        
        // 应用折扣（仅在计算 total 时减去，UI 由单独的元素显示）
        if (bookingData.discount_code && bookingData.discount_amount > 0) {
            total -= bookingData.discount_amount;
        }

        if (html === '') {
            html = '<p class="text-gray-500">No items selected</p>';
        }
        
        // 确保更新DOM
        if (orderSummaryEl) {
            orderSummaryEl.innerHTML = html;
        }
        
        // 更新 subtotal 显示
        const subtotalEl = document.getElementById('subtotal-amount');
        if (subtotalEl) {
            subtotalEl.textContent = '$' + subtotal.toFixed(2);
        }
        
        // 更新折扣显示状态
        const discountInputSection = document.getElementById('discount-input-section');
        const discountApplied = document.getElementById('discount-applied');
        const discountAmountDisplay = document.getElementById('discount-amount-display');
        
        if (bookingData.discount_code && bookingData.discount_amount > 0) {
            if (discountInputSection) discountInputSection.classList.add('hidden');
            if (discountApplied) discountApplied.classList.remove('hidden');
            if (discountAmountDisplay) {
                discountAmountDisplay.textContent = `-$${bookingData.discount_amount.toFixed(2)}`;
            }
        } else {
            if (discountInputSection) discountInputSection.classList.remove('hidden');
            if (discountApplied) discountApplied.classList.add('hidden');
        }
        
        // 更新 fee 显示
        const feeAmountEl = document.getElementById('fee-amount');
        const feeCents = (lastQuote && typeof lastQuote.fee === 'number') ? lastQuote.fee : 0;
        if (feeAmountEl) {
            feeAmountEl.textContent = '$' + (feeCents / 100).toFixed(2);
            // fee 大于 0 时显示为深色
            if (feeCents > 0) {
                feeAmountEl.classList.remove('text-zinc-500');
                feeAmountEl.classList.add('text-zinc-900');
            } else {
                feeAmountEl.classList.add('text-zinc-500');
                feeAmountEl.classList.remove('text-zinc-900');
            }
        }
        
        if (totalAmountEl) {
            // 优先使用后端返回的金额（包含追缴模式计算和折扣）
            let displayTotal = total;
            if (lastQuote && typeof lastQuote.final_amount === 'number') {
                // 后端已计算折扣后的 final_amount
                displayTotal = lastQuote.final_amount / 100;
            } else {
                // 无后端数据时，前端计算：(subtotal - discount) + fee
                const feeAmount = feeCents / 100;
                displayTotal = Math.max(0, total) + feeAmount;
            }
            totalAmountEl.textContent = '$' + displayTotal.toFixed(2);
        }
        
        console.log('Order summary updated:', { 
            packages: bookingData.packages, 
            addons: bookingData.addons, 
            total,
            packagesCount: bookingData.packages?.length || 0,
            addonsCount: bookingData.addons?.length || 0
        });
    }

    function updateEmbeddedSummary(quote) {
        if (!quote || typeof quote.final_amount !== 'number') {
            return;
        }
        if (totalAmountEl) {
            totalAmountEl.textContent = '$' + (quote.final_amount / 100).toFixed(2);
        }
    }

    /**
     * 应用折扣码
     */
    async function applyDiscountCode() {
        const codeInput = document.getElementById('discount-code-input');
        const messageEl = document.getElementById('discount-message');
        const applyBtn = document.getElementById('apply-discount-btn');
        const discountInputSection = document.getElementById('discount-input-section');
        const discountApplied = document.getElementById('discount-applied');
        const discountCodeDisplay = document.getElementById('discount-code-display');
        const discountAmountDisplay = document.getElementById('discount-amount-display');
        
        if (!codeInput || !codeInput.value.trim()) {
            if (messageEl) {
                messageEl.textContent = 'Please enter a discount code.';
                messageEl.className = 'text-sm text-red-600 mt-2';
                messageEl.classList.remove('hidden');
            }
            return;
        }
        
        const code = codeInput.value.trim().toUpperCase();
        
        // 计算订单原价
        let orderAmount = 0;
        for (const pkg of (bookingData.packages || [])) {
            const pkgData = tripData.packages?.find(p => p.id === pkg.package_id);
            if (pkgData && pkgData.price) {
                // 如果是分期付款，使用定金作为计算基础
                if (pkg.payment_plan_type === 'deposit_installment' && pkgData.payment_plan_config?.enabled) {
                    const deposit = pkgData.payment_plan_config.deposit_amount || pkgData.payment_plan_config.deposit || pkgData.price;
                    orderAmount += deposit * (pkg.quantity || 1);
                } else {
                    orderAmount += pkgData.price * (pkg.quantity || 1);
                }
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
                
                // 更新 UI - 隐藏输入框，显示已应用状态
                if (discountInputSection) discountInputSection.classList.add('hidden');
                if (discountApplied) {
                    discountApplied.classList.remove('hidden');
                    if (discountCodeDisplay) discountCodeDisplay.textContent = result.discount.code;
                    if (discountAmountDisplay) {
                        discountAmountDisplay.textContent = `-$${result.discount.discount_amount.toFixed(2)}`;
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
                        
                        // 重新请求 quote 以获取正确的 fee
                        if (paymentElementInstance && elementsInstance) {
                            console.log('Requesting new quote after discount applied...');
                            await requestEmbeddedQuote(true);
                        }
                    } catch (applyError) {
                        console.error('Error applying discount to PendingBooking:', applyError);
                    }
                }
                
                console.log('Discount applied:', result.discount);
            } else {
                // 显示错误
                if (messageEl) {
                    messageEl.textContent = result.message || 'Invalid discount code.';
                    messageEl.className = 'text-sm text-red-600 mt-2';
                    messageEl.classList.remove('hidden');
                }
            }
        } catch (error) {
            console.error('Error validating discount code:', error);
            if (messageEl) {
                messageEl.textContent = 'Error validating discount code. Please try again.';
                messageEl.className = 'text-sm text-red-600 mt-2';
                messageEl.classList.remove('hidden');
            }
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
                
                // 重新请求 quote 以获取正确的 fee
                if (paymentElementInstance && elementsInstance) {
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

        // 显示加载状态
        if (submitButton) {
            submitButton.disabled = true;
            submitButton.textContent = 'Processing...';
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
                if (submitButton) {
                    submitButton.disabled = false;
                    submitButton.textContent = 'Place Order';
                }
            }
        } catch (error) {
            console.error('Booking submission error:', error);
            showCustomAlert('An error occurred. Please try again.');
            if (submitButton) {
                submitButton.disabled = false;
                submitButton.textContent = 'Place Order';
            }
        }
    }

    function getBookingSignature() {
        return JSON.stringify({
            buyer_info: bookingData.buyer_info,
            packages: bookingData.packages,
            addons: bookingData.addons,
            participants: bookingData.participants,
            payment_method: bookingData.payment_method,
        });
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
            return;
        }

        resetEmbeddedPaymentSession();
        embeddedPaymentSignature = signature;

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
                        payment_flow: 'embedded',
                    }
                })
            });
            const result = await response.json();
            if (!response.ok || !result.success) {
                throw new Error(result.error || 'Payment initialization failed.');
            }

            embeddedPaymentSession = {
                booking_id: result.booking_id || null,  // 新流程中可能为null
                payment_intent_id: result.payment_intent_id,  // 新流程中必须有
                client_secret: result.client_secret,
                payment_plan: result.payment_plan,
                success_url: result.success_url,
                publishable_key: result.publishable_key || window.paymentConfig?.publishableKey,
            };
            
            console.log("Embedded payment session initialized:", {
                booking_id: embeddedPaymentSession.booking_id,
                payment_intent_id: embeddedPaymentSession.payment_intent_id,
                has_client_secret: !!embeddedPaymentSession.client_secret
            });

            if (!embeddedPaymentSession.client_secret || !embeddedPaymentSession.publishable_key) {
                throw new Error('Payment is not ready. Please refresh the page.');
            }

            stripeInstance = Stripe(embeddedPaymentSession.publishable_key);
            elementsInstance = stripeInstance.elements({
                clientSecret: embeddedPaymentSession.client_secret,
                paymentMethodCreation: "manual",
            });
            paymentElementInstance = elementsInstance.create("payment", {
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
            paymentElementInstance.mount("#payment-element");

            paymentElementInstance.on("change", (event) => {
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
            showCustomAlert(error.message || 'Payment is not ready. Please try again.');
            resetEmbeddedPaymentSession();
        }
    }

    async function requestEmbeddedQuote(silent = false) {
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
                if (submitButton) {
                    submitButton.disabled = false;
                    submitButton.textContent = 'Place Order';
                }
                return;
            }
        }

        // 检查是否为 $0 付款（例如 100% 折扣）
        // 计算折扣后的实际金额
        let actualPaymentAmount = 0;
        
        // 从 bookingData 计算 subtotal
        let subtotal = 0;
        for (const pkg of (bookingData.packages || [])) {
            const pkgData = tripData.packages?.find(p => p.id === pkg.package_id);
            if (pkgData) {
                if (pkg.payment_plan_type === 'deposit_installment' && pkgData.payment_plan_config?.enabled) {
                    const deposit = pkgData.payment_plan_config.deposit_amount || pkgData.payment_plan_config.deposit || pkgData.price;
                    subtotal += deposit * (pkg.quantity || 1);
                } else {
                    subtotal += pkgData.price * (pkg.quantity || 1);
                }
            }
        }
        for (const addon of (bookingData.addons || [])) {
            const addonData = tripData.addons?.find(a => a.id === addon.addon_id);
            if (addonData && addonData.price) {
                subtotal += addonData.price * (addon.quantity || 1);
            }
        }
        
        // 应用折扣
        const discountAmount = bookingData.discount_amount || 0;
        actualPaymentAmount = Math.max(0, subtotal - discountAmount);
        
        console.log('Payment amount check:', { subtotal, discountAmount, actualPaymentAmount });
        
        // 如果付款金额为 0，直接创建订单，不通过 Stripe
        if (actualPaymentAmount <= 0 && embeddedPaymentSession.payment_intent_id) {
            console.log('$0 payment detected, creating booking directly...');
            try {
                const response = await fetch('/api/booking/create-free', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        payment_intent_id: embeddedPaymentSession.payment_intent_id
                    })
                });
                const result = await response.json();
                
                if (result.success && result.redirect_url) {
                    console.log('Free booking created successfully:', result);
                    window.location.href = result.redirect_url;
                    return;
                } else {
                    throw new Error(result.message || 'Failed to create booking');
                }
            } catch (error) {
                console.error('Error creating free booking:', error);
                showPaymentMessage(error.message || 'Failed to create booking. Please try again.');
                if (submitButton) {
                    submitButton.disabled = false;
                    submitButton.textContent = 'Place Order';
                }
                return;
            }
        }

        if (!lastQuote) {
            await requestEmbeddedQuote(false);
            if (!lastQuote) {
                if (submitButton) {
                    submitButton.disabled = false;
                    submitButton.textContent = 'Place Order';
                }
                return;
            }
        }

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

            const { error } = await stripeInstance.confirmPayment({
                elements: elementsInstance,
                confirmParams: {
                    return_url: embeddedPaymentSession.success_url,
                },
            });
            if (error) {
                showPaymentMessage("Payment failed. Please try again.");
            }
        } catch (err) {
            showPaymentMessage(err.message || "Payment failed. Please try again.");
        } finally {
            if (submitButton) {
                submitButton.disabled = false;
                submitButton.textContent = 'Place Order';
            }
        }
    }

    function resetEmbeddedPaymentSession() {
        if (paymentElementInstance) {
            try {
                paymentElementInstance.unmount();
            } catch (err) {
                console.warn('Payment element unmount failed', err);
            }
        }
        embeddedPaymentSession = null;
        embeddedPaymentSignature = null;
        stripeInstance = null;
        elementsInstance = null;
        paymentElementInstance = null;
        lastPaymentMethodId = null;
        lastQuote = null;
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
        getCurrentStep: () => currentStep
    };

})();
