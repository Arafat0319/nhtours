/**
 * 导航栏交互逻辑
 * 处理桌面端滚动隐藏/显示和移动端菜单切换
 */

// 滚动控制变量
let lastScrollTop = 0;
const pageNav = document.getElementById("pageNav");
const navLogo = document.getElementById("navLogo");

// 桌面端导航栏滚动控制
window.addEventListener("scroll", () => {
	const scrollTop = window.scrollY;
	
	if (document.body.style.position !== "fixed") {
		// 防止小范围滚动触发
		if (scrollTop > lastScrollTop && scrollTop < 50) {
			lastScrollTop = scrollTop;
			return;
		}
		
		// 向下滚动隐藏，向上滚动显示
		if (scrollTop > lastScrollTop) {
			pageNav.classList.add("hidden");
		} else {
			pageNav.classList.remove("hidden");
			pageNav.classList.add("-translate-y-full");
			
			// 根据滚动位置调整样式
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
});

// 移动端菜单控制
document.addEventListener("DOMContentLoaded", () => {
	const smNavBtn = document.getElementById("smNavBtn");
	const smNav = document.getElementById("smNav");
	const navOpen = document.getElementById("nav-open");
	const navClose = document.getElementById("nav-close");
	let scrollPosition = 0;
	
	// 固定body位置（防止滚动）
	function lockBody() {
		scrollPosition = window.scrollY;
		document.body.style.position = "fixed";
		document.body.style.top = `-${scrollPosition}px`;
		document.body.style.left = "0";
		document.body.style.right = "0";
	}
	
	// 解锁body位置
	function unlockBody() {
		document.body.style.position = "";
		document.body.style.top = "";
		document.body.style.left = "";
		document.body.style.right = "";
		window.scrollTo(0, scrollPosition);
	}
	
	// 菜单按钮点击事件
	smNavBtn.addEventListener("click", () => {
		if (smNav.classList.contains("hidden")) {
			// 打开菜单
			smNav.classList.remove("hidden");
			smNav.classList.add("flex");
			pageNav.classList.add("h-full", "bg-indigo-800/90");
			navOpen?.classList.add("hidden");
			navClose?.classList.remove("hidden");
			document.body.classList.add("overflow-hidden");
			lockBody();
		} else {
			// 关闭菜单
			smNav.classList.add("hidden");
			smNav.classList.remove("flex");
			pageNav.classList.remove("h-full", "bg-indigo-800/90");
			navOpen?.classList.remove("hidden");
			navClose?.classList.add("hidden");
			document.body.classList.remove("overflow-hidden");
			unlockBody();
		}
	});
});


