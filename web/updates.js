(() => {
	"use strict";

	let info;
	let dialog;
	let checking = false;
	let installing = false;
	let announcement = false;

	async function api(path = "", method = "GET") {
		const headers = path.startsWith("/install?") ? { "X-Tarkov-Update": "install" } : {};
		const response = await fetch("/api/updates" + path, { method, headers });
		if (!response.ok) {
			throw new Error("本地更新服务暂不可用");
		}
		return response.json();
	}

	function part(name) {
		return dialog.querySelector(".update_" + name);
	}

	function initialize() {
		dialog = document.createElement("dialog");
		dialog.className = "update_dialog";
		dialog.setAttribute("aria-labelledby", "update_title");
		dialog.innerHTML = `<div class="update_head"><h2 id="update_title"></h2><button class="update_close" aria-label="关闭" type="button">×</button></div>
			<div class="update_details"><strong>塔科夫百科</strong><span class="update_version"></span></div>
			<p class="update_intro">游戏资料和交互地图数据来自 tarkov.dev，中文任务攻略来自 OPtarkov。任务进度保存在本机。</p>
			<label class="update_pref"><input class="update_auto" type="checkbox">每 24 小时自动检查更新</label>
			<div class="update_proxy"><label for="update_proxy_address">更新代理</label><div><input id="update_proxy_address" class="update_proxy_address" type="text" placeholder="如 127.0.0.1:7890" autocomplete="off"><button type="button" class="update_proxy_save">保存</button></div></div>
			<section class="update_release" hidden><h3 class="update_release_title"></h3><div class="update_date"></div><p class="update_notes"></p></section>
			<p class="update_status" role="status"></p>
			<div class="update_actions"><button type="button" class="update_later" hidden>稍后</button><button type="button" class="update_check">检查更新</button><button type="button" class="update_install" hidden>下载安装更新</button></div>`;
		document.body.append(dialog);
		part("close").addEventListener("click", () => dialog.close());
		part("later").addEventListener("click", () => dialog.close());
		part("check").addEventListener("click", () => check(true));
		part("install").addEventListener("click", install);
		part("proxy_save").addEventListener("click", async () => {
			try {
				const response = await fetch("/api/updates/proxy", {
					method: "POST", headers: { "Content-Type": "application/json" },
					body: JSON.stringify({ proxy: part("proxy_address").value })
				});
				const result = await response.json();
				if (result.ok) {
					info = result;
					part("proxy_address").value = result.proxy;
				}
				part("status").textContent = result.ok ? "更新代理已保存。" : result.error;
			} catch (error) {
				part("status").textContent = "未能保存更新代理。";
			}
		});
		part("auto").addEventListener("change", async () => {
			try {
				info = await api("/auto?enabled=" + part("auto").checked, "POST");
				render();
			} catch (error) {
				part("auto").checked = !!info?.auto;
				part("status").textContent = error.message;
			}
		});
		dialog.addEventListener("close", () => {
			if (announcement && info?.available) {
				api("/dismiss?version=" + encodeURIComponent(info.release.version), "POST").catch(() => {});
			}
			announcement = false;
		});
		dialog.addEventListener("keydown", (event) => {
			if (event.key === "Escape") {
				event.stopPropagation();
			}
		});
	}

	function render() {
		dialog.querySelector("h2").textContent = announcement ? "发现新版本" : "关于我们";
		part("intro").hidden = announcement;
		part("pref").hidden = announcement;
		part("proxy").hidden = announcement;
		part("auto").checked = !!info?.auto;
		part("version").textContent = info ? "当前版本 " + info.version : "";
		part("release").hidden = !info?.available;
		part("install").hidden = !info?.available;
		part("check").hidden = announcement;
		part("later").hidden = !announcement;
		part("check").disabled = checking || installing;
		part("install").disabled = checking || installing;
		if (info?.available) {
			part("release_title").textContent = "版本 " + info.release.version + " 更新公告";
			part("date").textContent = info.release.publishedAt ? "发布日期 " + info.release.publishedAt : "";
			part("notes").textContent = info.release.notes;
			part("install").textContent = installing ? "正在下载并校验…" : "下载安装更新";
		}
		part("status").textContent = checking ? "正在检查更新…" : info?.error || (
			info?.lastChecked ? (info.available ? "" : "已是最新版本。") + "上次检查 " + new Date(info.lastChecked * 1000).toLocaleString("zh-CN") : "尚未检查更新"
		);
	}

	async function openUpdateAbout() {
		announcement = false;
		if (!dialog.open) {
			dialog.showModal();
		}
		render();
		try {
			info = await api();
			part("proxy_address").value = info.proxy || "";
			render();
		} catch (error) {
			part("status").textContent = error.message;
		}
	}

	async function check(manual) {
		if (checking || installing) {
			return;
		}
		checking = true;
		if (dialog.open) {
			render();
		}
		try {
			info = await api("/check?manual=" + manual, "POST");
			if (info.available && !info.error && (manual || (info.auto && info.notify && !dialog.open))) {
				announcement = true;
				if (!dialog.open) {
					dialog.showModal();
				}
			}
		} catch (error) {
			if (dialog.open) {
				part("status").textContent = error.message;
			}
			checking = false;
			part("check").disabled = false;
			return;
		}
		checking = false;
		render();
	}

	async function install() {
		if (!info?.available || installing) {
			return;
		}
		installing = true;
		render();
		try {
			const result = await api("/install?version=" + encodeURIComponent(info.release.version), "POST");
			part("status").textContent = result.ok ? "安装程序已打开。请关闭塔科夫百科，再继续安装。" : result.error;
		} catch (error) {
			part("status").textContent = error.message;
		} finally {
			installing = false;
			part("check").disabled = false;
			part("install").disabled = false;
			part("install").textContent = "下载安装更新";
		}
	}

	initialize();
	window.openUpdateAbout = openUpdateAbout;
	document.getElementById("settings_about")?.addEventListener("click", openUpdateAbout);
	window.setTimeout(() => check(false), 1800);
	window.setInterval(() => check(false), 60 * 60 * 1000);
})();
