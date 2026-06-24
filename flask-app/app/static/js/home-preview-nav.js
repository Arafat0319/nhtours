/**
 * 全站主导航（Modern V1 浅色实底）
 */

const homePreviewNav = document.getElementById("homePreviewNav");
const homePreviewNavToggle = document.getElementById("homePreviewNavToggle");
const homePreviewNavPanel = document.getElementById("homePreviewNavPanel");
const homePreviewNavOpen = document.getElementById("homePreviewNavOpen");
const homePreviewNavClose = document.getElementById("homePreviewNavClose");

let lastScrollTop = 0;
let mobileScrollLock = 0;

function setMobileNavOpen(isOpen) {
	if (!homePreviewNavToggle || !homePreviewNavPanel || !homePreviewNav) return;

	homePreviewNavToggle.setAttribute("aria-expanded", String(isOpen));
	homePreviewNavPanel.hidden = !isOpen;
	homePreviewNav.classList.toggle("home-preview-nav--menu-open", isOpen);
	homePreviewNavOpen?.classList.toggle("home-preview-nav__toggle-icon--hidden", isOpen);
	homePreviewNavClose?.classList.toggle("home-preview-nav__toggle-icon--hidden", !isOpen);

	if (isOpen) {
		mobileScrollLock = window.scrollY;
		document.body.classList.add("home-preview-nav-body-lock");
		document.body.style.top = `-${mobileScrollLock}px`;
	} else {
		document.body.classList.remove("home-preview-nav-body-lock");
		document.body.style.top = "";
		window.scrollTo(0, mobileScrollLock);
	}
}

window.addEventListener("scroll", () => {
	if (!homePreviewNav || document.body.classList.contains("home-preview-nav-body-lock")) return;

	const scrollTop = window.scrollY;
	homePreviewNav.classList.toggle("home-preview-nav--scrolled", scrollTop > 0);
	lastScrollTop = scrollTop;
});

homePreviewNavToggle?.addEventListener("click", () => {
	const isOpen = homePreviewNavToggle.getAttribute("aria-expanded") === "true";
	setMobileNavOpen(!isOpen);
});

homePreviewNavPanel?.querySelectorAll("a").forEach((link) => {
	link.addEventListener("click", () => setMobileNavOpen(false));
});

document.addEventListener("DOMContentLoaded", () => {
	lastScrollTop = window.scrollY;
	if (window.scrollY > 0) {
		homePreviewNav?.classList.add("home-preview-nav--scrolled");
	}
});
