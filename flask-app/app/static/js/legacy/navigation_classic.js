/**
 * 存档：旧版全站导航脚本（经典透明导航）
 */
/**
 * 导航栏交互逻辑
 * 主站：原版逻辑（仅 hidden 控制显隐，向上滚动时移除 -translate-y-full）
 * 付款页（booking-layout / installment-modal-page）：当前逻辑（hidden + -translate-y-full，初始根据 scrollY 隐藏）
 */

const pageNav = document.getElementById("pageNav");
const navLogo = document.getElementById("navLogo");
let lastScrollTop = 0;

const isBookingLayout =
	document.body.classList.contains("booking-layout") ||
	document.body.classList.contains("installment-modal-page");

// 桌面端导航栏滚动控制
window.addEventListener("scroll", () => {
	if (!pageNav) return;
	const scrollTop = window.scrollY;

	if (isBookingLayout) {
		// 付款页：现有逻辑（防小范围抖动、hidden + -translate-y-full）
		if (document.body.style.position !== "fixed") {
			if (scrollTop > lastScrollTop && scrollTop < 50) {
				lastScrollTop = scrollTop;
				return;
			}
			if (scrollTop > lastScrollTop && scrollTop > 80) {
				pageNav.classList.add("hidden");
				pageNav.classList.add("-translate-y-full");
			} else if (scrollTop <= 80 || scrollTop < lastScrollTop) {
				pageNav.classList.remove("hidden");
				pageNav.classList.remove("-translate-y-full");
				if (scrollTop > 0) {
					pageNav.classList.add("shadow-md");
					pageNav.classList.add("bg-indigo-800/90");
					navLogo?.classList.add("w-[200px]");
					navLogo?.classList.remove("w-[256px]");
				} else {
					pageNav.classList.remove("shadow-md");
					pageNav.classList.remove("bg-indigo-800/90");
					navLogo?.classList.remove("w-[200px]");
					navLogo?.classList.add("w-[256px]");
				}
			}
			lastScrollTop = scrollTop;
		}
	} else {
		// 主站：原版逻辑（仅 hidden；向上滚动时显示并移除 -translate-y-full）
		if (scrollTop > lastScrollTop) {
			pageNav.classList.add("hidden");
		} else {
			pageNav.classList.remove("hidden");
			pageNav.classList.remove("-translate-y-full");
		}
		lastScrollTop = scrollTop;
	}
});

document.addEventListener("DOMContentLoaded", () => {
	const scrollY = window.scrollY;
	lastScrollTop = scrollY;

	if (isBookingLayout && pageNav) {
		if (scrollY >= 80) {
			pageNav.classList.add("hidden");
			pageNav.classList.add("-translate-y-full");
		} else {
			pageNav.classList.remove("hidden");
			pageNav.classList.remove("-translate-y-full");
		}
	}

	const smNavBtn = document.getElementById("smNavBtn");
	const smNav = document.getElementById("smNav");
	const navOpen = document.getElementById("nav-open");
	const navClose = document.getElementById("nav-close");
	let scrollPosition = 0;

	function lockBody() {
		scrollPosition = window.scrollY;
		document.body.style.position = "fixed";
		document.body.style.top = `-${scrollPosition}px`;
		document.body.style.left = "0";
		document.body.style.right = "0";
	}

	function unlockBody() {
		document.body.style.position = "";
		document.body.style.top = "";
		document.body.style.left = "";
		document.body.style.right = "";
		window.scrollTo(0, scrollPosition);
	}

	if (!smNavBtn || !smNav) return;
	smNavBtn.addEventListener("click", () => {
		if (smNav.classList.contains("hidden")) {
			smNav.classList.remove("hidden");
			smNav.classList.add("flex");
			pageNav?.classList.add("h-full", "bg-indigo-800/90");
			navOpen?.classList.add("hidden");
			navClose?.classList.remove("hidden");
			document.body.classList.add("overflow-hidden");
			if (isBookingLayout) lockBody();
		} else {
			smNav.classList.add("hidden");
			smNav.classList.remove("flex");
			pageNav?.classList.remove("h-full", "bg-indigo-800/90");
			navOpen?.classList.remove("hidden");
			navClose?.classList.add("hidden");
			document.body.classList.remove("overflow-hidden");
			if (isBookingLayout) unlockBody();
		}
	});
});
