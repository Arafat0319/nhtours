/**
 * Homepage: testimonials carousel + philosophy modal
 */

function initPhilosophyModal() {
	const openBtn = document.getElementById("homePreviewPhilosophyOpen");
	const modal = document.getElementById("homePreviewPhilosophyModal");
	if (!openBtn || !modal) return;

	const closeTargets = modal.querySelectorAll("[data-philosophy-close]");
	let lastFocus = null;

	function openModal() {
		lastFocus = document.activeElement;
		modal.hidden = false;
		document.body.classList.add("home-preview-philosophy-modal-open");
		modal.querySelector(".home-preview-philosophy-modal__close")?.focus();
	}

	function closeModal() {
		modal.hidden = true;
		document.body.classList.remove("home-preview-philosophy-modal-open");
		if (lastFocus instanceof HTMLElement) {
			lastFocus.focus();
		}
	}

	openBtn.addEventListener("click", openModal);
	closeTargets.forEach((el) => {
		el.addEventListener("click", closeModal);
	});

	modal.addEventListener("keydown", (event) => {
		if (event.key === "Escape") {
			closeModal();
		}
	});
}

function initTestimonialsCarousel() {
	const section = document.getElementById("home-preview-testimonials");
	if (!section) return;

	const carousel = section.querySelector(".home-preview-testimonials__carousel");
	const slides = section.querySelectorAll(".home-preview-testimonials__slide");
	const prevBtn = section.querySelector("[data-testimonial-prev]");
	const nextBtn = section.querySelector("[data-testimonial-next]");
	const AUTOPLAY_MS = 5000;
	const RESUME_AFTER_MS = 10000;
	const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
	let current = 0;
	let autoplayTimer = null;
	let resumeTimer = null;

	function show(index) {
		const total = slides.length;
		if (total === 0) return;
		current = ((index % total) + total) % total;
		slides.forEach((slide, i) => {
			slide.classList.toggle("is-active", i === current);
		});
	}

	function stopAutoplay() {
		if (autoplayTimer) {
			clearInterval(autoplayTimer);
			autoplayTimer = null;
		}
	}

	function startAutoplay() {
		if (prefersReducedMotion || slides.length <= 1) return;
		stopAutoplay();
		autoplayTimer = setInterval(() => show(current + 1), AUTOPLAY_MS);
	}

	function pauseAutoplay() {
		stopAutoplay();
		if (resumeTimer) {
			clearTimeout(resumeTimer);
			resumeTimer = null;
		}
	}

	function pauseAndScheduleResume() {
		pauseAutoplay();
		if (prefersReducedMotion || slides.length <= 1) return;
		resumeTimer = setTimeout(startAutoplay, RESUME_AFTER_MS);
	}

	function onUserNavigate(index) {
		show(index);
		pauseAndScheduleResume();
	}

	prevBtn?.addEventListener("click", () => onUserNavigate(current - 1));
	nextBtn?.addEventListener("click", () => onUserNavigate(current + 1));

	if (carousel) {
		carousel.addEventListener("mouseenter", pauseAutoplay);
		carousel.addEventListener("mouseleave", startAutoplay);
		carousel.addEventListener("focusin", pauseAutoplay);
		carousel.addEventListener("focusout", (event) => {
			if (!carousel.contains(event.relatedTarget)) {
				startAutoplay();
			}
		});
	}

	document.addEventListener("visibilitychange", () => {
		if (document.hidden) {
			pauseAutoplay();
		} else {
			startAutoplay();
		}
	});

	show(0);
	startAutoplay();
}

document.addEventListener("DOMContentLoaded", () => {
	initPhilosophyModal();
	initTestimonialsCarousel();
});
