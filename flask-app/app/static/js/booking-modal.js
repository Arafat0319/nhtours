/**
 * 报名 Modal 逻辑 - Book Now 点击、Modal 开关
 */

(function() {
    'use strict';

    function initBookingModal() {
        const bookNowBtn = document.getElementById('bookNowBtn');
        const loadingOverlay = document.getElementById('booking-loading-overlay');
        const bookingModal = document.getElementById('booking-modal');
        const closeBtn = document.getElementById('closeBookingModal');
        const backdrop = document.getElementById('booking-modal-backdrop');

        function openBookingModal(ev) {
            if (!loadingOverlay || !bookingModal) return;
            if (window.registrationOpen === false) return;
            var btn = (ev && ev.currentTarget && ev.currentTarget.nodeType === 1)
                ? ev.currentTarget
                : (ev && ev.target && ev.target.closest)
                    ? ev.target.closest('button') || ev.target.closest('a') || ev.target
                    : null;
            if (btn && btn.disabled) return;
            if (btn && btn.classList) {
                btn.classList.add('is-loading');
                if (typeof btn.disabled !== 'undefined') btn.disabled = true;
            }
            // 若上次停在付款成功页，开新单前先清结果态与支付会话
            var resultWrap = document.getElementById('booking-modal-result');
            var stuckOnResult = resultWrap && !resultWrap.classList.contains('hidden');
            if (stuckOnResult && window.BookingWizard && typeof window.BookingWizard.prepareNewBooking === 'function') {
                window.BookingWizard.prepareNewBooking({ keepFormData: false });
            } else if (window.BookingWizard && typeof window.BookingWizard.showBookingModalResult === 'function') {
                window.BookingWizard.showBookingModalResult(null);
            }
            loadingOverlay.classList.remove('hidden');
            setTimeout(function() {
                loadingOverlay.classList.add('hidden');
                bookingModal.classList.remove('hidden');
                document.documentElement.style.overflow = 'hidden';
                document.body.style.overflow = 'hidden'; /* 背景不滚动，由弹窗层 #booking-modal 自身 overflow-y: auto 滚动 */
                if (typeof window.updateOrderSummary === 'function') window.updateOrderSummary();
                if (btn && btn.classList) {
                    btn.classList.remove('is-loading');
                    // 报名未开放时保持 disabled，不要被 loading 流程重新启用
                    if (typeof btn.disabled !== 'undefined' && window.registrationOpen !== false) {
                        btn.disabled = false;
                    }
                }
                requestAnimationFrame(function() {
                    if (window.BookingWizard && typeof window.BookingWizard.syncModalBodyMinHeight === 'function') {
                        window.BookingWizard.syncModalBodyMinHeight();
                    }
                });
            }, 500);
        }

        /* 滚轮在弹窗内时滚动 #booking-modal（卡片可溢出，整层滚动） */
        function onModalWheel(e) {
            if (!bookingModal || bookingModal.classList.contains('hidden')) return;
            if (!bookingModal.contains(e.target)) return;
            var el = bookingModal;
            var canDown = el.scrollTop < el.scrollHeight - el.clientHeight - 1;
            var canUp = el.scrollTop > 0;
            var delta = e.deltaY || e.detail || 0;
            if (delta > 0 && canDown) {
                e.preventDefault();
                el.scrollTop += delta;
            } else if (delta < 0 && canUp) {
                e.preventDefault();
                el.scrollTop += delta;
            }
        }
        document.addEventListener('wheel', onModalWheel, { passive: false });

        if (bookNowBtn && loadingOverlay && bookingModal) {
            bookNowBtn.addEventListener('click', function(e) {
                if (bookNowBtn.disabled || window.registrationOpen === false) return;
                openBookingModal(e);
            });
        }
        document.addEventListener('click', function(e) {
            var trigger = e.target && e.target.closest
                ? e.target.closest('.book-now-trigger')
                : (e.target && e.target.classList && e.target.classList.contains('book-now-trigger') ? e.target : null);
            if (!trigger) return;
            if (trigger.disabled || window.registrationOpen === false) return;
            openBookingModal(e);
        });


        // Close modal
        function closeModal() {
            var scrollEl = document.getElementById('booking-modal-scroll');
            if (scrollEl) scrollEl.style.minHeight = '';
            var resultWrap = document.getElementById('booking-modal-result');
            var onResult = resultWrap && !resultWrap.classList.contains('hidden');
            if (onResult && window.BookingWizard && typeof window.BookingWizard.prepareNewBooking === 'function') {
                // 成功/失败结果页关闭：清结果态 + 支付会话，下次可重新下单
                window.BookingWizard.prepareNewBooking({ keepFormData: false });
            } else if (window.BookingWizard && typeof window.BookingWizard.showBookingModalResult === 'function') {
                window.BookingWizard.showBookingModalResult(null);
            }
            if (bookingModal) {
                bookingModal.classList.add('hidden');
                bookingModal.style.display = '';
                bookingModal.style.visibility = '';
                bookingModal.style.opacity = '';
                document.documentElement.style.overflow = '';
                document.body.style.overflow = '';
                if (closeBtn) closeBtn.classList.remove('close-btn-hover', 'close-btn-active');
            }
        }
        if (closeBtn) closeBtn.addEventListener('click', function(e) { e.preventDefault(); e.stopPropagation(); closeModal(); });
        // 关闭判断：先看 target 是否是关闭键，再用点击坐标是否落在关闭键区域内（防止被其它层挡住时仍可关闭）
        function isClickOnCloseButton(e) {
            var t = e.target;
            if (t && (t.id === 'closeBookingModal' || (t.closest && t.closest('#closeBookingModal')))) return true;
            if (!closeBtn) return false;
            var rect = closeBtn.getBoundingClientRect();
            var x = e.clientX, y = e.clientY;
            return x >= rect.left && x <= rect.right && y >= rect.top && y <= rect.bottom;
        }
        function tryCloseFromEvent(e) {
            if (!bookingModal || bookingModal.classList.contains('hidden')) return;
            if (isClickOnCloseButton(e)) {
                e.preventDefault();
                e.stopPropagation();
                closeModal();
            }
        }
        document.addEventListener('click', tryCloseFromEvent, true);
        document.addEventListener('mousedown', tryCloseFromEvent, true);
        // 用坐标模拟 hover（因有层盖住按钮时 CSS :hover 不触发）
        var HOVER_CLASS = 'close-btn-hover';
        var ACTIVE_CLASS = 'close-btn-active';
        function isPointerOverCloseButton(clientX, clientY) {
            if (!closeBtn) return false;
            var rect = closeBtn.getBoundingClientRect();
            return clientX >= rect.left && clientX <= rect.right && clientY >= rect.top && clientY <= rect.bottom;
        }
        function updateCloseButtonHover(e) {
            if (!bookingModal || bookingModal.classList.contains('hidden') || !closeBtn) return;
            if (isPointerOverCloseButton(e.clientX, e.clientY)) {
                closeBtn.classList.add(HOVER_CLASS);
            } else {
                closeBtn.classList.remove(HOVER_CLASS);
                closeBtn.classList.remove(ACTIVE_CLASS);
            }
        }
        function updateCloseButtonActive(e) {
            if (!closeBtn) return;
            if (e.type === 'mousedown' && isPointerOverCloseButton(e.clientX, e.clientY)) {
                closeBtn.classList.add(ACTIVE_CLASS);
            } else {
                closeBtn.classList.remove(ACTIVE_CLASS);
            }
        }
        document.addEventListener('mousemove', updateCloseButtonHover, true);
        if (bookingModal) {
            bookingModal.addEventListener('mouseleave', function() {
                closeBtn && closeBtn.classList.remove(HOVER_CLASS, ACTIVE_CLASS);
            });
        }
        document.addEventListener('mousedown', updateCloseButtonActive, true);
        document.addEventListener('mouseup', updateCloseButtonActive, true);
        // 仅关闭键可关闭弹窗，点击灰色遮罩不关闭
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initBookingModal);
    } else {
        initBookingModal();
    }
})();
