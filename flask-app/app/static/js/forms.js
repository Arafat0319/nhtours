/**
 * 表单处理逻辑
 * 通过Flask路由提交表单到AWS Lambda
 */

/**
 * 通用表单提交处理函数
 * @param {HTMLFormElement} form - 表单元素
 * @param {HTMLElement} statusElement - 状态显示元素
 * @param {HTMLElement} spinnerElement - 加载动画元素（可选）
 */
async function handleFormSubmit(form, statusElement, spinnerElement = null) {
	// 隐藏状态消息
	statusElement.classList.add("hidden");
	
	// 显示加载动画（如果有）
	if (spinnerElement) {
		spinnerElement.classList.remove("hidden");
	}
	
	// 构建表单数据对象
	const formData = new FormData(form);
	const data = {};
	
	for (const [key, value] of formData.entries()) {
		const allValues = formData.getAll(key);
		data[key] = allValues.length > 1 ? allValues : value;
	}
	
	try {
		// 使用表单的action属性作为提交URL，如果没有则使用当前页面URL
		const submitUrl = form.getAttribute('action') || window.location.pathname;
		
		const response = await fetch(submitUrl, {
			method: "POST",
			headers: {
				"Content-Type": "application/json"
			},
			body: JSON.stringify(data)
		});
		
		const result = await response.json();
		
		// 隐藏加载动画
		if (spinnerElement) {
			spinnerElement.classList.add("hidden");
		}
		
		if (result.success) {
			// 成功
			statusElement.textContent = result.message || "Success!";
			// 根据表单类型设置不同的成功消息样式
			if (form.id === 'contact-form') {
				statusElement.className = "text-green-700 bg-green-100 px-3 py-2 rounded shadow-sm mt-4 mb-4";
			} else {
				statusElement.className = "text-green-700 bg-green-100 px-3 py-2 rounded shadow-sm";
			}
			statusElement.classList.remove("hidden");
			form.reset();
		} else {
			// 失败
			throw new Error(result.error || "Something went wrong.");
		}
	} catch (error) {
		// 隐藏加载动画
		if (spinnerElement) {
			spinnerElement.classList.add("hidden");
		}
		
		// 显示错误消息
		statusElement.textContent = error.message || "Oops!";
		// 根据表单类型设置不同的错误消息样式
		if (form.id === 'contact-form') {
			statusElement.className = "text-red-700 bg-red-100 px-3 py-2 rounded shadow-sm mt-4 mb-4";
		} else {
			statusElement.className = "text-red-700 bg-red-100 px-3 py-2 rounded shadow-sm";
		}
		statusElement.classList.remove("hidden");
	}
}

// Newsletter表单处理
document.addEventListener("DOMContentLoaded", () => {
	const newsletterForm = document.getElementById("newsletter-form");
	
	if (newsletterForm) {
		const statusElement = document.getElementById("newsletter-form-status");
		
		newsletterForm.addEventListener("submit", async (e) => {
			e.preventDefault();
			await handleFormSubmit(newsletterForm, statusElement);
		});
	}
	
		// Contact表单处理
	const contactForm = document.getElementById("contact-form");
	
	if (contactForm) {
		const statusElement = document.getElementById("form-status");
		const spinnerElement = document.getElementById("form-spinner");
		
		contactForm.addEventListener("submit", async (e) => {
			e.preventDefault();
			await handleFormSubmit(contactForm, statusElement, spinnerElement);
		});
	}
});

