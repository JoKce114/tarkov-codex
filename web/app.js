const numberFormat = new Intl.NumberFormat("zh-CN");

const MODULES = [
	{
		key: "items",
		name: "物品图鉴",
		icon: "◈",
		desc: "全部物品的属性、价格、兑换与制作来源",
		ready: true,
	},
	{
		key: "tasks",
		name: "商人任务",
		icon: "◆",
		desc: "任务目标、前置条件、奖励与完成地点",
		ready: true,
	},
	{
		key: "maps",
		name: "地图",
		icon: "▣",
		desc: "全部地图、撤离点、BOSS 刷新点",
		ready: true,
	},
	{
		key: "traders",
		name: "商人",
		icon: "◉",
		desc: "各商人的等级解锁与交易内容",
		ready: true,
	},
	{
		key: "barters",
		name: "兑换配方",
		icon: "⇄",
		desc: "全量以物易物配方一览",
		ready: true,
	},
	{
		key: "crafts",
		name: "藏身处制作",
		icon: "⚒",
		desc: "全部制作配方、设施等级与耗时",
		ready: true,
	},
	{
		key: "hideout",
		name: "藏身处升级",
		icon: "⌂",
		desc: "各设施每级所需材料与条件",
		ready: true,
	},
];

const state = {
	view: "home",
	mode: "",
	modes: [],
	category: "",
	query: "",
	sort: "name",
	offset: 0,
	limit: 60,
	total: 0,
	categoryNames: new Map(),
	searchTimer: null,
	requestId: 0,
	taskFilters: {
		hideCompleted: false,
		hideLocked: false,
		kappa: false,
		lightkeeper: false,
	},
	trader: "",
	taskQuery: "",
	taskOffset: 0,
	taskLimit: 60,
	taskTotal: 0,
	taskList: [],
	traders: [],
	playerLevel: 1,
	completedCount: 0,
	taskRequestId: 0,
	taskSearchTimer: null,
	barterOffset: 0,
	barterQuery: "",
	craftOffset: 0,
	craftQuery: "",
	currentMapImage: "",
	currentMapOriginal: "",
	currentMapTitle: "",
	drawerRequestId: 0,
};

function el(tag, className, text) {
	const node = document.createElement(tag);
	if (className) {
		node.className = className;
	}
	if (text !== undefined && text !== null) {
		node.textContent = text;
	}
	return node;
}

function formatNumber(value) {
	if (value === null || value === undefined || value === "") {
		return "--";
	}
	return numberFormat.format(value);
}

function formatTime(text) {
	if (!text) {
		return "--";
	}
	return text.replace("T", " ");
}

function formatDuration(seconds) {
	if (!seconds && seconds !== 0) {
		return "--";
	}
	const total = Math.round(seconds);
	const hours = Math.floor(total / 3600);
	const minutes = Math.round((total % 3600) / 60);
	if (hours > 0) {
		return minutes > 0 ? `${hours} 小时 ${minutes} 分` : `${hours} 小时`;
	}
	return `${minutes} 分钟`;
}

async function getJson(url) {
	const response = await fetch(url);
	if (!response.ok) {
		throw new Error(`请求失败 ${response.status}`);
	}
	return response.json();
}

function iconUrl(itemId, size) {
	return `/api/icon/${encodeURIComponent(itemId)}${size && size !== "icon" ? `?size=${size}` : ""}`;
}

function showView(name) {
	state.view = name;
	document.getElementById("view_home").hidden = name !== "home";
	document.getElementById("view_items").hidden = name !== "items";
	document.getElementById("view_tasks").hidden = name !== "tasks";
	document.getElementById("view_traders").hidden = name !== "traders";
	document.getElementById("view_barters").hidden = name !== "barters";
	document.getElementById("view_crafts").hidden = name !== "crafts";
	document.getElementById("view_hideout").hidden = name !== "hideout";
	document.getElementById("view_maps").hidden = name !== "maps";
	document.getElementById("view_settings").hidden = name !== "settings";
	document.getElementById("search_wrap").hidden = name !== "items";
	document.getElementById("btn_back").hidden = name === "home";
}

/* ---------- 任务模块 ---------- */

function traderImageUrl(traderId) {
	return `/api/asset/trader/${encodeURIComponent(traderId)}`;
}

function taskImageUrl(taskId) {
	return `/api/asset/task/${encodeURIComponent(taskId)}`;
}

async function loadTaskFilters() {
	const [traders, progress] = await Promise.all([
		getJson("/api/traders"),
		getJson("/api/progress"),
	]);
	state.traders = traders.traders || [];
	state.playerLevel = progress.playerLevel || 1;
	state.completedCount = progress.completedCount || 0;
	document.getElementById("player_level").value = state.playerLevel;
	renderTraders();
	renderTaskProgress();
}

function renderTaskProgress() {
	const total = state.traders.reduce((sum, trader) => sum + (trader.total || 0), 0);
	document.getElementById("task_progress").textContent =
		`已完成 ${formatNumber(state.completedCount)} / ${formatNumber(total)}`;
}

function renderTraders() {
	const strip = document.getElementById("trader_strip");
	strip.innerHTML = "";

	const all = el("button", "trader_btn is_all", "所有");
	if (!state.trader) {
		all.classList.add("is_active");
	}
	all.addEventListener("click", () => {
		state.trader = "";
		state.taskOffset = 0;
		renderTraders();
		loadTasks();
	});
	strip.appendChild(all);

	state.traders.forEach((trader) => {
		const button = el("button", "trader_btn");
		button.title = `${trader.name}（共 ${trader.total} 个任务，已完成 ${trader.done}）`;
		if (trader.id === state.trader) {
			button.classList.add("is_active");
		}
		if (trader.imageLink) {
			const image = document.createElement("img");
			image.src = traderImageUrl(trader.id);
			image.alt = trader.name;
			image.loading = "lazy";
			button.appendChild(image);
		} else {
			button.textContent = (trader.name || "?").slice(0, 2);
		}
		if (trader.done > 0) {
			button.appendChild(el("span", "trader_done", String(trader.done)));
		}
		button.addEventListener("click", () => {
			state.trader = trader.id === state.trader ? "" : trader.id;
			state.taskOffset = 0;
			renderTraders();
			loadTasks();
		});
		strip.appendChild(button);
	});
}

function taskQuery() {
	const params = new URLSearchParams({
		limit: String(state.taskLimit),
		offset: String(state.taskOffset),
	});
	if (state.taskQuery) {
		params.set("q", state.taskQuery);
	}
	if (state.trader) {
		params.set("trader", state.trader);
	}
	Object.entries(state.taskFilters).forEach(([key, value]) => {
		if (value) {
			params.set(key, "true");
		}
	});
	return params.toString();
}

function renderTaskCard(task) {
	const card = el("div", "task_card");
	if (task.completed) {
		card.classList.add("is_done");
	}
	if (!task.unlocked && !task.completed) {
		card.classList.add("is_locked");
	}

	if (task.imageLink) {
		const image = document.createElement("img");
		image.className = "task_thumb";
		image.src = taskImageUrl(task.id);
		image.alt = "";
		image.loading = "lazy";
		card.appendChild(image);
	} else {
		const placeholder = el("div", "task_thumb");
		card.appendChild(placeholder);
	}

	const main = el("div", "task_main");
	main.appendChild(el("div", "task_title", task.name || ""));
	const meta = el("div", "task_meta");
	meta.appendChild(el("span", "", task.trader.name || ""));
	if (task.minPlayerLevel) {
		meta.appendChild(el("span", "", `LV${task.minPlayerLevel}`));
	}
	if (task.map) {
		meta.appendChild(el("span", "", task.map));
	}
	if (task.objectiveCount) {
		meta.appendChild(el("span", "", `${task.objectiveCount} 个目标`));
	}
	if (task.kappaRequired) {
		meta.appendChild(el("span", "task_tag is_kappa", "Kappa"));
	}
	if (task.lightkeeperRequired) {
		meta.appendChild(el("span", "task_tag is_lk", "Lightkeeper"));
	}
	if (task.completed) {
		meta.appendChild(el("span", "task_tag is_done", "已完成"));
	} else if (task.lockReason) {
		meta.appendChild(el("span", "task_tag is_locked", task.lockReason));
	}
	main.appendChild(meta);
	card.appendChild(main);

	const actions = el("div", "task_actions");
	const doneButton = el("button", task.completed ? "btn_done is_done" : "btn_done", task.completed ? "已完成 ✓" : "标记完成");
	doneButton.addEventListener("click", async (event) => {
		event.stopPropagation();
		await toggleTaskDone(task.id, !task.completed);
	});
	actions.appendChild(doneButton);
	card.appendChild(actions);

	card.addEventListener("click", () => openTask(task.id));
	return card;
}

function renderTasks(payload) {
	state.taskList = payload.tasks || [];
	state.taskTotal = payload.total || 0;
	const list = document.getElementById("task_list");
	const empty = document.getElementById("task_empty");
	list.innerHTML = "";
	if (!state.taskList.length) {
		empty.hidden = false;
	} else {
		empty.hidden = true;
		state.taskList.forEach((task) => list.appendChild(renderTaskCard(task)));
	}
	renderTaskInfo();
	renderTaskPager();
}

function renderTaskInfo() {
	const parts = [];
	if (state.taskQuery) {
		parts.push(`搜索「${state.taskQuery}」`);
	}
	const trader = state.traders.find((entry) => entry.id === state.trader);
	if (trader) {
		parts.push(trader.name);
	}
	if (!parts.length) {
		parts.push("全部任务");
	}
	document.getElementById("task_info").textContent = `${parts.join(" · ")} — 共 ${formatNumber(state.taskTotal)} 个`;
}

function renderTaskPager() {
	const pager = document.getElementById("task_pager");
	pager.innerHTML = "";
	const page = Math.floor(state.taskOffset / state.taskLimit) + 1;
	const pages = Math.max(1, Math.ceil(state.taskTotal / state.taskLimit));

	const prev = el("button", "", "上一页");
	prev.disabled = state.taskOffset <= 0;
	prev.addEventListener("click", () => {
		state.taskOffset = Math.max(0, state.taskOffset - state.taskLimit);
		loadTasks();
	});

	const next = el("button", "", "下一页");
	next.disabled = state.taskOffset + state.taskLimit >= state.taskTotal;
	next.addEventListener("click", () => {
		state.taskOffset += state.taskLimit;
		loadTasks();
	});

	pager.appendChild(prev);
	pager.appendChild(el("span", "", `${page} / ${pages}`));
	pager.appendChild(next);
}

async function loadTasks() {
	const requestId = ++state.taskRequestId;
	const payload = await getJson(`/api/tasks?${taskQuery()}`);
	if (requestId !== state.taskRequestId) {
		return;
	}
	renderTasks(payload);
}

async function toggleTaskDone(taskId, completed) {
	await fetch("/api/progress/task", {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify({ taskId, completed }),
	});
	state.completedCount = completed ? state.completedCount + 1 : Math.max(0, state.completedCount - 1);
	renderTaskProgress();
	await loadTaskFilters();
	await loadTasks();
	if (!document.getElementById("drawer").hidden) {
		await openTask(taskId);
	}
}

function objectiveRow(objective, index) {
	const row = el("div", "objective_row");
	row.appendChild(el("span", "objective_mark", objective.optional ? "?" : String(index + 1)));
	const body = el("div", "objective_body");
	body.appendChild(el("div", "", objective.description || objective.type || ""));
	const extra = el("div", "objective_extra");
	if (objective.optional) {
		extra.appendChild(el("span", "task_tag", "可选"));
	}
	if (objective.count && objective.count > 1) {
		extra.appendChild(el("span", "", `数量 ${formatNumber(objective.count)}`));
	}
	(objective.maps || []).forEach((name) => {
		if (name) {
			extra.appendChild(el("span", "", name));
		}
	});
	(objective.items || []).forEach((item) => {
		const chip = el("span", "reward_item");
		const image = document.createElement("img");
		image.src = iconUrl(item.id);
		image.loading = "lazy";
		image.alt = "";
		chip.appendChild(image);
		chip.appendChild(el("span", "", item.shortName || item.name || ""));
		chip.title = item.name || "";
		extra.appendChild(chip);
	});
	if (extra.children.length) {
		body.appendChild(extra);
	}
	row.appendChild(body);
	return row;
}

function renderRewards(container, rewards) {
	if (!rewards) {
		return false;
	}
	let hasContent = false;

	if ((rewards.items || []).length) {
		const grid = el("div", "reward_grid");
		rewards.items.forEach((entry) => {
			const chip = el("div", "reward_item");
			const image = document.createElement("img");
			image.src = iconUrl(entry.id);
			image.loading = "lazy";
			image.alt = "";
			chip.appendChild(image);
			chip.appendChild(el("span", "", `${entry.shortName || entry.name || ""} ×${formatNumber(entry.count)}`));
			chip.title = entry.name || "";
			grid.appendChild(chip);
		});
		container.appendChild(grid);
		hasContent = true;
	}

	(rewards.traderStanding || []).forEach((entry) => {
		const sign = (entry.standing || 0) >= 0 ? "+" : "";
		container.appendChild(el("div", "reward_line", `${entry.trader} 声望 ${sign}${entry.standing}`));
		hasContent = true;
	});
	(rewards.skillLevelReward || []).forEach((entry) => {
		container.appendChild(el("div", "reward_line", `${entry.skill} 等级 +${entry.level}`));
		hasContent = true;
	});
	(rewards.offerUnlock || []).forEach((entry) => {
		container.appendChild(
			el("div", "reward_line", `解锁 ${entry.trader} LL${entry.level} 的「${entry.name}」`),
		);
		hasContent = true;
	});
	(rewards.traderUnlock || []).forEach((name) => {
		container.appendChild(el("div", "reward_line", `解锁商人 ${name}`));
		hasContent = true;
	});
	(rewards.traderDialogueUnlock || []).forEach((name) => {
		container.appendChild(el("div", "reward_line", `解锁 ${name} 的对话`));
		hasContent = true;
	});
	(rewards.achievement || []).forEach((name) => {
		if (name) {
			container.appendChild(el("div", "reward_line", `成就：${name}`));
			hasContent = true;
		}
	});
	(rewards.craftUnlock || []).forEach((entry) => {
		container.appendChild(
			el("div", "reward_line", `解锁 ${entry.station} 等级 ${entry.level} 的「${entry.name}」配方`),
		);
		hasContent = true;
	});
	(rewards.locationUnlock || []).forEach((name) => {
		if (name) {
			container.appendChild(el("div", "reward_line", `解锁地图 ${name}`));
			hasContent = true;
		}
	});

	return hasContent;
}

function renderMapBlock(group) {
	const block = el("div", "task_map_block");

	const head = el("div", "task_map_head");
	head.appendChild(el("span", "", `${group.mapName} · ${group.points.length} 个点位`));
	const controls = el("div", "map_controls");
	head.appendChild(controls);

	const viewport = el("div", "map_viewport");
	const canvas = el("div", "map_canvas");
	viewport.appendChild(canvas);

	const state = { scale: 1, x: 0, y: 0, ready: false };

	const apply = () => {
		canvas.style.transform = `translate(${state.x}px, ${state.y}px) scale(${state.scale})`;
	};

	const fit = () => {
		const box = viewport.getBoundingClientRect();
		if (!box.width || !group.width) {
			return;
		}
		const scale = Math.min(box.width / group.width, box.height / group.height) * 0.96;
		state.scale = scale;
		state.x = (box.width - group.width * scale) / 2;
		state.y = (box.height - group.height * scale) / 2;
		apply();
	};

	const zoom = (factor) => {
		const box = viewport.getBoundingClientRect();
		const next = Math.min(8, Math.max(0.2, state.scale * factor));
		const cx = box.width / 2;
		const cy = box.height / 2;
		state.x = cx - ((cx - state.x) / state.scale) * next;
		state.y = cy - ((cy - state.y) / state.scale) * next;
		state.scale = next;
		apply();
	};

	["+", "−", "⤢"].forEach((symbol) => {
		const button = el("button", "", symbol);
		button.title = symbol === "⤢" ? "重置视图" : symbol === "+" ? "放大" : "缩小";
		button.addEventListener("click", () => (symbol === "⤢" ? fit() : zoom(symbol === "+" ? 1.25 : 0.8)));
		controls.appendChild(button);
	});

	const image = el("img", "task_map_image");
	image.alt = group.mapName;
	image.decoding = "async";
	image.loading = "lazy";
	image.addEventListener("load", () => {
			group.width = image.naturalWidth;
			group.height = image.naturalHeight;
			// 只有 viewBox 的底图需要显式尺寸，点位层也会跟随这张图布局。
			image.width = group.width;
			image.height = group.height;
			const overlay = document.createElementNS("http://www.w3.org/2000/svg", "svg");
			overlay.setAttribute("class", "task_map_overlay");
			overlay.setAttribute("viewBox", `0 0 ${group.width} ${group.height}`);
			group.points.forEach((point) => {
				const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
				circle.setAttribute("cx", String(point.x * group.width));
				circle.setAttribute("cy", String(point.y * group.height));
				circle.setAttribute("r", String(Math.max(group.width, group.height) * 0.006));
				circle.setAttribute("class", point.optional ? "map_dot is_optional" : "map_dot");
				const title = document.createElementNS("http://www.w3.org/2000/svg", "title");
				title.textContent = point.label;
				circle.appendChild(title);
				overlay.appendChild(circle);
			});
			canvas.appendChild(overlay);

			state.ready = true;
			fit();

			let dragging = false;
			let lastX = 0;
			let lastY = 0;
			viewport.addEventListener("pointerdown", (event) => {
				dragging = true;
				lastX = event.clientX;
				lastY = event.clientY;
				viewport.classList.add("is_dragging");
				viewport.setPointerCapture(event.pointerId);
			});
			viewport.addEventListener("pointermove", (event) => {
				if (!dragging) {
					return;
				}
				state.x += event.clientX - lastX;
				state.y += event.clientY - lastY;
				lastX = event.clientX;
				lastY = event.clientY;
				apply();
			});
			const stopDrag = () => {
				dragging = false;
				viewport.classList.remove("is_dragging");
			};
			viewport.addEventListener("pointerup", stopDrag);
			viewport.addEventListener("pointercancel", stopDrag);
			viewport.addEventListener("wheel", (event) => {
				event.preventDefault();
				const box = viewport.getBoundingClientRect();
				const mx = event.clientX - box.left;
				const my = event.clientY - box.top;
				const factor = event.deltaY < 0 ? 1.12 : 0.89;
				const next = Math.min(8, Math.max(0.2, state.scale * factor));
				state.x = mx - ((mx - state.x) / state.scale) * next;
				state.y = my - ((my - state.y) / state.scale) * next;
				state.scale = next;
				apply();
			}, { passive: false });
	}, { once: true });
	image.addEventListener("error", () => {
		canvas.replaceChildren(el("div", "map_hint", "地图图片加载失败"));
	}, { once: true });
	image.src = `/api/map/svg/${encodeURIComponent(group.mapKey)}`;
	canvas.appendChild(image);

	block.appendChild(head);
	block.appendChild(viewport);
	block.appendChild(el("div", "map_hint", "拖动平移，滚轮缩放。红点为任务点位，橙色为可选目标。"));
	return block;
}

async function openTask(taskId) {
	const requestId = ++state.drawerRequestId;
	const body = document.getElementById("drawer_body");
	body.innerHTML = '<div class="loading_block">读取中…</div>';
	document.getElementById("drawer").hidden = false;
	document.getElementById("drawer_mask").hidden = false;
	document.getElementById("drawer").scrollTop = 0;
	try {
		const url = `/api/tasks/${encodeURIComponent(taskId)}`;
		const payload = await getJson(url);
		if (requestId !== state.drawerRequestId) {
			return;
		}
		renderTaskDetail(payload.task);
		getJson(`${url}/map`).then((result) => {
			if (requestId !== state.drawerRequestId || !result.maps.length) {
				return;
			}
			const section = el("div", "section");
			section.appendChild(sectionTitle("地图点位"));
			result.maps.forEach((group) => section.appendChild(renderMapBlock(group)));
			body.appendChild(section);
		}).catch(() => {});
	} catch (error) {
		if (requestId === state.drawerRequestId) {
			body.replaceChildren(el("div", "loading_block", `读取失败：${error.message}`));
		}
	}
}

function renderTaskDetail(task) {
	const body = document.getElementById("drawer_body");
	body.innerHTML = "";

	const head = el("div", "detail_head");
	if (task.imageLink) {
		const image = document.createElement("img");
		image.className = "detail_image";
		image.src = taskImageUrl(task.id);
		image.alt = "";
		head.appendChild(image);
	}
	const title = el("div", "detail_title");
	title.appendChild(el("h2", "", task.name || ""));
	const sub = [task.trader.name, task.map, task.minPlayerLevel ? `LV${task.minPlayerLevel}` : ""].filter(Boolean);
	title.appendChild(el("div", "short_name", sub.join(" · ")));
	const badges = el("div", "badge_list");
	if (task.completed) {
		badges.appendChild(el("span", "badge", "已完成"));
	} else if (task.lockReason) {
		badges.appendChild(el("span", "badge", task.lockReason));
	}
	if (task.kappaRequired) {
		badges.appendChild(el("span", "badge", "Kappa"));
	}
	if (task.lightkeeperRequired) {
		badges.appendChild(el("span", "badge", "Lightkeeper"));
	}
	if (task.experience) {
		badges.appendChild(el("span", "badge", `+${formatNumber(task.experience)} 经验`));
	}
	title.appendChild(badges);
	head.appendChild(title);
	body.appendChild(head);

	const bar = el("div", "detail_action_bar");
	const doneButton = el("button", task.completed ? "btn_primary is_done" : "btn_primary", task.completed ? "已完成 ✓ 点击撤销" : "标记完成");
	doneButton.addEventListener("click", () => toggleTaskDone(task.id, !task.completed));
	bar.appendChild(doneButton);
	if (task.wikiLink) {
		const link = el("a", "btn_link", "查看 Wiki");
		link.href = task.wikiLink;
		link.target = "_blank";
		link.rel = "noreferrer";
		bar.appendChild(link);
	}
	body.appendChild(bar);

	if ((task.objectives || []).length) {
		const section = el("div", "section");
		section.appendChild(sectionTitle(`任务目标（${task.objectives.length}）`));
		task.objectives.forEach((objective, index) => section.appendChild(objectiveRow(objective, index)));
		body.appendChild(section);
	}

	const finishSection = el("div", "section");
	finishSection.appendChild(sectionTitle("完成奖励"));
	if (task.experience) {
		finishSection.appendChild(el("div", "reward_line", `经验 +${formatNumber(task.experience)}`));
	}
	if (!renderRewards(finishSection, task.finishRewards) && !task.experience) {
		finishSection.appendChild(el("div", "hint_text", "无奖励数据"));
	}
	body.appendChild(finishSection);

	const prereqs = task.prerequisites || [];
	const traderReqs = task.traderRequirements || [];
	if (prereqs.length || traderReqs.length) {
		const section = el("div", "section");
		section.appendChild(sectionTitle("前置条件"));
		prereqs.forEach((entry) => {
			const row = el("div", "prereq_row");
			const link = el("a", "btn_link", entry.name);
			link.href = "#";
			link.addEventListener("click", (event) => {
				event.preventDefault();
				openTask(entry.id);
			});
			row.appendChild(link);
			row.appendChild(el("span", entry.completed ? "prereq_ok" : "prereq_no", entry.completed ? "已完成" : "未完成"));
			section.appendChild(row);
		});
		traderReqs.forEach((entry) => {
			const label = entry.type === "level" ? `${entry.trader} 等级` : `${entry.trader} 声望`;
			section.appendChild(el("div", "reward_line", `${label} ${entry.compare || ""} ${entry.value}`));
		});
		body.appendChild(section);
	}

	if ((task.neededKeys || []).length) {
		const section = el("div", "section");
		section.appendChild(sectionTitle("需要钥匙"));
		const grid = el("div", "reward_grid");
		task.neededKeys.forEach((entry) => {
			const chip = el("div", "reward_item");
			const image = document.createElement("img");
			image.src = iconUrl(entry.id);
			image.loading = "lazy";
			image.alt = "";
			chip.appendChild(image);
			chip.appendChild(el("span", "", entry.shortName || entry.name || ""));
			chip.title = entry.map ? `${entry.name || ""}（${entry.map}）` : entry.name || "";
			grid.appendChild(chip);
		});
		section.appendChild(grid);
		body.appendChild(section);
	}

	if ((task.followUps || []).length) {
		const section = el("div", "section");
		section.appendChild(sectionTitle(`后续任务（${task.followUps.length}）`));
		task.followUps.forEach((entry) => {
			const row = el("div", "prereq_row");
			const link = el("a", "btn_link", entry.name || "");
			link.href = "#";
			link.addEventListener("click", (event) => {
				event.preventDefault();
				openTask(entry.id);
			});
			row.appendChild(link);
			row.appendChild(el("span", "dim", entry.completed ? "已完成" : ""));
			section.appendChild(row);
		});
		body.appendChild(section);
	}
}

function renderModeSwitch() {
	const container = document.getElementById("mode_switch");
	container.innerHTML = "";
	state.modes.forEach((mode) => {
		const button = el("button", "mode_btn", mode.label);
		if (mode.key === state.mode) {
			button.classList.add("is_active");
		}
		button.addEventListener("click", () => switchMode(mode.key));
		container.appendChild(button);
	});
}

async function switchMode(modeKey) {
	if (modeKey === state.mode) {
		return;
	}
	const buttons = document.querySelectorAll(".mode_btn");
	buttons.forEach((button) => {
		button.disabled = true;
	});
	const badge = document.getElementById("sync_state");
	badge.className = "sync_state is_running";
	badge.textContent = "切换模式中…";
	try {
		const response = await fetch("/api/mode", {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({ mode: modeKey }),
		});
		const payload = await response.json();
		if (!payload.ok) {
			throw new Error(payload.error || "切换失败");
		}
		state.mode = modeKey;
		closeDrawer();
		state.category = "";
		state.query = "";
		state.offset = 0;
		state.categoryNames.clear();
		document.getElementById("search_input").value = "";
		renderModeSwitch();
		await refreshSync();
		renderHome(payload);
		if (state.view === "maps") {
			await loadMaps();
		}
		if (state.view === "items") {
			const categories = await getJson("/api/categories");
			renderCategories(categories.tree);
			await loadItems();
		}
		if (state.view === "tasks") {
			state.trader = "";
			state.taskQuery = "";
			state.taskOffset = 0;
			document.getElementById("task_search").value = "";
			await loadTaskFilters();
			await loadTasks();
		}
	} catch (error) {
		badge.className = "sync_state is_error";
		badge.textContent = error.message;
	} finally {
		document.querySelectorAll(".mode_btn").forEach((button) => {
			button.disabled = false;
		});
	}
}

function checkFirstRun(stats) {
	const existing = document.getElementById("first_run");
	if (!stats.empty) {
		existing?.remove();
		return;
	}
	if (existing) {
		return;
	}
	const banner = el("div", "first_run");
	banner.id = "first_run";
	banner.appendChild(el("div", "first_run_title", "首次使用，需要先下载数据"));
	banner.appendChild(
		el(
			"div",
			"first_run_text",
			"从 Tarkov.dev 下载三种游戏模式的物品、任务和地图。完成后可以离线查询文字资料。",
		),
	);
	const button = el("button", "btn_primary", "开始下载数据");
	button.addEventListener("click", () => document.getElementById("btn_sync_all").click());
	banner.appendChild(button);
	document.getElementById("view_home").prepend(banner);
}

async function refreshAll() {
	const stats = await getJson("/api/stats");
	renderHome(stats);
	checkFirstRun(stats);
}

function renderHome(stats) {
	const counts = stats.counts || {};
	const grid = document.getElementById("module_grid");
	grid.innerHTML = "";
	MODULES.forEach((module) => {
		const card = el("button", "module_card");
		if (!module.ready) {
			card.classList.add("is_disabled");
		}
		card.appendChild(el("div", "module_icon", module.icon));
		const name = el("div", "module_name", module.name);
		if (!module.ready) {
			name.appendChild(el("span", "module_badge", "即将上线"));
		}
		card.appendChild(name);
		card.appendChild(el("div", "module_desc", module.desc));
		card.appendChild(el("div", "module_count", `${formatNumber(counts[module.key] || 0)} 条`));
		if (module.ready) {
			card.addEventListener("click", () => openModule(module.key));
		}
		grid.appendChild(card);
	});

	const status = document.getElementById("home_status");
	const modeLabel = (state.modes.find((mode) => mode.key === state.mode) || {}).label || "";
	status.innerHTML = "";
	[
		`模式 ${modeLabel}`,
		`物品 ${formatNumber(counts.items || 0)}`,
		`任务 ${formatNumber(counts.tasks || 0)}`,
		`地图 ${formatNumber(counts.maps || 0)}`,
		`商人 ${formatNumber(counts.traders || 0)}`,
		`兑换 ${formatNumber(counts.barters || 0)}`,
		`制作 ${formatNumber(counts.crafts || 0)}`,
	].forEach((text) => status.appendChild(el("span", "", text)));
}

async function openModule(key) {
	showView(key);
	if (key === "items") {
		if (!document.getElementById("category_tree").children.length) {
			const categories = await getJson("/api/categories");
			renderCategories(categories.tree);
		}
		await loadItems();
	}
	if (key === "tasks") {
		await loadTaskFilters();
		await loadTasks();
	}
	if (key === "traders") {
		await loadTraders();
	}
	if (key === "barters") {
		state.barterOffset = 0;
		await loadBarters();
	}
	if (key === "crafts") {
		state.craftOffset = 0;
		await loadCrafts();
	}
	if (key === "hideout") {
		await loadHideout();
	}
	if (key === "maps") {
		await loadMaps();
	}
}

/* ---------- 地图 ---------- */

function mapImageUrl(url) {
	return `/api/game-map/image?url=${encodeURIComponent(url)}`;
}

/* ---------- 快速打开地图 ---------- */

const quickMap = {
	focusIndex: -1,
};

function toast(text, isError) {
	const node = el("div", isError ? "toast is_error" : "toast", text);
	document.body.appendChild(node);
	requestAnimationFrame(() => node.classList.add("is_show"));
	setTimeout(() => {
		node.classList.remove("is_show");
		setTimeout(() => node.remove(), 250);
	}, 2600);
}

function quickMapThumb(entry) {
	if (!entry) {
		return "";
	}
	if (entry.images && entry.images.length) {
		return entry.images[0].previewUrl || entry.images[0].url || "";
	}
	return entry.previewUrl || "";
}

async function ensureQuickMapData() {
	const payload = await getJson("/api/game-maps");
	return payload.maps || [];
}

function renderQuickMapList(maps) {
	const list = document.getElementById("quick_map_list");
	list.innerHTML = "";
	quickMap.focusIndex = -1;

	if (!maps.length) {
		list.appendChild(el("div", "quick_map_empty", "地图数据还没下载，请先重建全部资料"));
		return;
	}

	maps.forEach((entry, index) => {
		const item = el("div", "quick_map_item");
		const thumb = quickMapThumb(entry);
		if (thumb) {
			const image = document.createElement("img");
			image.src = mapImageUrl(thumb);
			image.loading = "lazy";
			image.alt = "";
			item.appendChild(image);
		}
		const info = el("div", "quick_map_info");
		info.appendChild(el("div", "quick_map_name", entry.name || entry.slug || ""));
		const meta = [];
		if (entry.players) {
			meta.push(`${entry.players} 人`);
		}
		if (entry.raidDuration) {
			meta.push(`${entry.raidDuration} 分钟`);
		}
		if (entry.exitCount) {
			meta.push(`撤离 ${entry.exitCount}`);
		}
		info.appendChild(el("div", "quick_map_meta", meta.join(" · ")));
		item.appendChild(info);
		item.appendChild(el("span", "quick_map_open", "打开 ↗"));

		item.addEventListener("click", () => {
			hideQuickMap();
			if (entry.previewUrl) {
				openMapViewer(entry.previewUrl, entry.name || "地图");
			} else {
				showView("maps");
				loadMaps(entry.slug);
			}
		});
		list.appendChild(item);
	});
}

function showQuickMap() {
	const button = document.getElementById("quick_map_btn");
	const panel = document.getElementById("quick_map_panel");
	button.classList.add("is_open");
	panel.hidden = false;
	ensureQuickMapData()
		.then((maps) => {
			if (!panel.hidden) {
				renderQuickMapList(maps);
			}
		})
		.catch(() => renderQuickMapList([]));
}

function hideQuickMap() {
	document.getElementById("quick_map_btn").classList.remove("is_open");
	document.getElementById("quick_map_panel").hidden = true;
}

function setupQuickMap() {
	const button = document.getElementById("quick_map_btn");
	const panel = document.getElementById("quick_map_panel");

	button.addEventListener("click", (event) => {
		event.stopPropagation();
		if (panel.hidden) {
			showQuickMap();
		} else {
			hideQuickMap();
		}
	});

	panel.addEventListener("click", (event) => event.stopPropagation());
	document.addEventListener("click", () => {
		if (!panel.hidden) {
			hideQuickMap();
		}
	});

	document.addEventListener("keydown", (event) => {
		if (panel.hidden) {
			return;
		}
		const items = [...panel.querySelectorAll(".quick_map_item")];
		if (!items.length) {
			return;
		}
		if (event.key === "Escape") {
			hideQuickMap();
			return;
		}
		if (event.key === "ArrowDown" || event.key === "ArrowUp") {
			event.preventDefault();
			const step = event.key === "ArrowDown" ? 1 : -1;
			quickMap.focusIndex = (quickMap.focusIndex + step + items.length) % items.length;
			items.forEach((node) => node.classList.remove("is_focus"));
			items[quickMap.focusIndex].classList.add("is_focus");
			items[quickMap.focusIndex].scrollIntoView({ block: "nearest" });
			return;
		}
		if (event.key === "Enter" && quickMap.focusIndex >= 0) {
			event.preventDefault();
			items[quickMap.focusIndex].click();
		}
	});
}

async function loadMaps(selectedSlug) {
	const payload = await getJson("/api/game-maps");
	const list = document.getElementById("map_list");
	list.innerHTML = "";
	const maps = payload.maps || [];
	document.getElementById("maps_info").textContent = maps.length
		? `共 ${maps.length} 张地图`
		: "地图数据尚未同步";

	if (!maps.length) {
		document.getElementById("map_placeholder").textContent = "请先从首页重建全部资料";
		document.getElementById("map_placeholder").hidden = false;
		document.getElementById("map_detail").hidden = true;
		return;
	}

	maps.forEach((entry) => {
		const item = el("div", "map_item");
		item.dataset.slug = entry.slug;
		if (entry.previewUrl) {
			const image = document.createElement("img");
			image.src = mapImageUrl(entry.previewUrl);
			image.loading = "lazy";
			image.alt = entry.name;
			item.appendChild(image);
		}
		item.appendChild(el("span", "map_item_name", entry.name || entry.slug));
		item.addEventListener("click", () => selectMap(entry.slug, item));
		list.appendChild(item);
	});

	const selectedIndex = Math.max(0, maps.findIndex((entry) => entry.slug === selectedSlug));
	selectMap(maps[selectedIndex].slug, list.children[selectedIndex]);
}

async function selectMap(slug, node) {
	document.querySelectorAll(".map_item.is_active").forEach((item) => item.classList.remove("is_active"));
	if (node) {
		node.classList.add("is_active");
	}
	document.getElementById("map_placeholder").hidden = true;
	const detail = document.getElementById("map_detail");
	detail.hidden = false;
	detail.querySelector("#map_title").textContent = "读取中…";

	try {
		const payload = await getJson(`/api/game-maps/${encodeURIComponent(slug)}`);
		if (node?.classList.contains("is_active") && node.isConnected) {
			renderMapDetail(payload.map);
		}
	} catch (error) {
		detail.querySelector("#map_title").textContent = `读取失败：${error.message}`;
	}
}

function renderMapDetail(map) {
	document.getElementById("map_title").textContent = `${map.name || ""}${map.nameEn ? `  ${map.nameEn}` : ""}`;

	const meta = document.getElementById("map_meta");
	meta.innerHTML = "";
	const info = [];
	if (map.players) {
		info.push(`人数 ${map.players}`);
	}
	if (map.raidDuration) {
		info.push(`时长 ${map.raidDuration} 分钟`);
	}
	if ((map.exits || []).length) {
		info.push(`撤离点 ${map.exits.length}`);
	}
	if ((map.bosses || []).length) {
		info.push(`BOSS ${map.bosses.length}`);
	}
	info.forEach((text) => meta.appendChild(el("span", "", text)));

	const tabs = document.getElementById("map_image_tabs");
	tabs.innerHTML = "";
	const images = map.images || [];
	const imageNode = document.getElementById("map_image");
	const wrap = imageNode.parentElement;
	wrap.classList.remove("is_zoomed");

	if (images.length) {
		images.forEach((image, index) => {
			const tab = el("button", "map_image_tab", image.title || `图 ${index + 1}`);
			if (index === 0) {
				tab.classList.add("is_active");
			}
			tab.addEventListener("click", () => {
				tabs.querySelectorAll(".map_image_tab").forEach((node) => node.classList.remove("is_active"));
				tab.classList.add("is_active");
				state.currentMapImage = image.url;
				state.currentMapOriginal = image.originalUrl || image.url;
				state.currentMapTitle = `${map.name || ""} · ${image.title || ""}`;
				imageNode.src = mapImageUrl(image.url);
				wrap.classList.remove("is_zoomed");
			});
			tabs.appendChild(tab);
		});
		state.currentMapImage = images[0].url;
		state.currentMapOriginal = images[0].originalUrl || images[0].url;
		state.currentMapTitle = `${map.name || ""} · ${images[0].title || ""}`;
		imageNode.src = mapImageUrl(images[0].url);
		imageNode.alt = images[0].title || map.name;
	} else {
		state.currentMapImage = "";
		state.currentMapOriginal = "";
		imageNode.removeAttribute("src");
		tabs.appendChild(el("span", "hint_text", "没有地图图片"));
	}

	const sections = document.getElementById("map_sections");
	sections.innerHTML = "";

	if (map.description) {
		sections.appendChild(el("div", "map_desc", map.description));
	}

	if ((map.exits || []).length) {
		sections.appendChild(renderMapChips("撤离点", map.exits.map((entry) => ({
			text: entry.name,
			tag: [entry.faction === "pmc" ? "PMC" : entry.faction === "scav" ? "SCAV" : "共享",
				entry.chance !== null && entry.chance !== undefined ? `${entry.chance}%` : "",
				entry.requirementTip && entry.requirementTip !== "EXFIL_Item" ? entry.requirementTip : "",
			].filter(Boolean).join(" · "),
			kind: entry.faction === "pmc" ? "is_pmc" : entry.faction === "scav" ? "is_scav" : "is_shared",
		}))));
	}

	if ((map.bosses || []).length) {
		sections.appendChild(renderMapChips("BOSS 刷新", map.bosses.map((entry) => ({
			text: entry.name,
			tag: [entry.chance !== null && entry.chance !== undefined ? `${entry.chance}%` : "", entry.zones || ""]
				.filter(Boolean).join(" · "),
			kind: "",
		}))));
	}

	if ((map.transits || []).length) {
		sections.appendChild(renderMapChips("转移点", map.transits.map((entry) => ({
			text: entry.name,
			tag: entry.target ? `通往 ${entry.target}` : "",
			kind: "",
		}))));
	}

	if ((map.hazards || []).length) {
		sections.appendChild(renderMapChips("危险区", map.hazards.map((entry) => ({
			text: entry.name || entry.type,
			tag: entry.type || "",
			kind: "",
		}))));
	}

	if ((map.keys || []).length) {
		sections.appendChild(renderMapChips("本图钥匙", map.keys.map((entry) => ({
			text: entry.name,
			tag: entry.lockCount ? `${entry.lockCount} 处可用` : "",
			icon: entry.id ? iconUrl(entry.id) : "",
			kind: "",
		}))));
	}
}

function renderMapChips(title, items) {
	const section = el("div", "map_section");
	const head = el("div", "map_section_head");
	head.appendChild(el("span", "", title));
	head.appendChild(el("span", "map_section_count", `${items.length} 项`));
	section.appendChild(head);

	const chips = el("div", "map_chips");
	items.forEach((item) => {
		const chip = el("div", `map_chip${item.kind ? ` ${item.kind}` : ""}`);
		if (item.icon) {
			const image = document.createElement("img");
			image.src = item.icon;
			image.loading = "lazy";
			image.alt = "";
			chip.appendChild(image);
		}
		chip.appendChild(el("span", "", item.text || ""));
		if (item.tag) {
			chip.appendChild(el("span", "map_chip_tag", item.tag));
		}
		chips.appendChild(chip);
	});
	section.appendChild(chips);
	return section;
}

/* ---------- 商人 ---------- */

async function loadTraders() {
	const payload = await getJson("/api/traders");
	const grid = document.getElementById("trader_grid");
	grid.innerHTML = "";
	const traders = payload.traders || [];
	document.getElementById("traders_info").textContent = `共 ${traders.length} 个商人`;

	traders.forEach((trader) => {
		const card = el("button", "trader_card");
		if (trader.imageLink) {
			const image = document.createElement("img");
			image.src = traderImageUrl(trader.id);
			image.alt = trader.name;
			image.loading = "lazy";
			card.appendChild(image);
		}
		const info = el("div", "trader_card_info");
		info.appendChild(el("div", "trader_card_name", trader.name || ""));
		const stat = el("div", "trader_card_stat");
		stat.appendChild(el("span", "", `任务 ${trader.total}`));
		stat.appendChild(el("span", "", `可接 ${trader.available}`));
		stat.appendChild(el("span", "", `已完成 ${trader.done}`));
		info.appendChild(stat);
		card.appendChild(info);
		card.addEventListener("click", () => openTrader(trader.id));
		grid.appendChild(card);
	});
}

async function openTrader(traderId) {
	const body = document.getElementById("drawer_body");
	body.innerHTML = '<div class="loading_block">读取中…</div>';
	document.getElementById("drawer").hidden = false;
	document.getElementById("drawer_mask").hidden = false;
	document.getElementById("drawer").scrollTop = 0;
	try {
		const payload = await getJson(`/api/traders/${encodeURIComponent(traderId)}`);
		renderTraderDetail(payload.trader);
	} catch (error) {
		body.innerHTML = `<div class="loading_block">读取失败：${error.message}</div>`;
	}
}

function renderTraderDetail(trader) {
	const body = document.getElementById("drawer_body");
	body.innerHTML = "";

	const head = el("div", "trader_detail_head");
	if (trader.imageLink) {
		const image = document.createElement("img");
		image.src = traderImageUrl(trader.id);
		image.alt = trader.name;
		head.appendChild(image);
	}
	const title = el("div", "detail_title");
	title.appendChild(el("h2", "", trader.name || ""));
	if (trader.description) {
		title.appendChild(el("div", "short_name", trader.description));
	}
	head.appendChild(title);
	body.appendChild(head);

	if ((trader.levels || []).length) {
		const section = el("div", "section");
		section.appendChild(sectionTitle("忠诚等级"));
		trader.levels.forEach((level) => {
			const row = el("div", "trader_level_row");
			row.appendChild(el("span", "", `LL${level.level}`));
			const parts = [`玩家等级 ${level.requiredPlayerLevel || 0}`];
			if (level.requiredReputation) {
				parts.push(`声望 ${level.requiredReputation}`);
			}
			if (level.payRate !== null && level.payRate !== undefined) {
				parts.push(`售价系数 ${level.payRate}`);
			}
			row.appendChild(el("span", "dim", parts.join(" · ")));
			section.appendChild(row);
		});
		body.appendChild(section);
	}

	if ((trader.offers || []).length) {
		const section = el("div", "section");
		section.appendChild(sectionTitle(`在售物品（${formatNumber(trader.offerCount)}，按价格排序）`));
		trader.offers.slice(0, 120).forEach((offer) => {
			const row = el("div", "offer_row");
			const image = document.createElement("img");
			image.src = urlIcon(offer.id);
			image.loading = "lazy";
			image.alt = "";
			row.appendChild(image);
			row.appendChild(el("span", "", offer.shortName || offer.name || ""));
			const level = offer.traderLevel ? `LL${offer.traderLevel}` : "";
			const limit = offer.buyLimit ? `限购 ${offer.buyLimit}` : "";
			row.appendChild(el("span", "dim", [level, limit].filter(Boolean).join(" · ")));
			row.appendChild(el("span", "offer_price", formatNumber(offer.price)));
			section.appendChild(row);
		});
		body.appendChild(section);
	}

	if ((trader.tasks || []).length) {
		const section = el("div", "section");
		section.appendChild(sectionTitle(`发布任务（${trader.taskCount}）`));
		trader.tasks.forEach((task) => {
			const row = el("div", "task_row");
			const link = el("a", "btn_link", task.name || "");
			link.href = "#";
			link.addEventListener("click", (event) => {
				event.preventDefault();
				openTask(task.id);
			});
			row.appendChild(link);
			row.appendChild(el("span", "task_trader", task.minPlayerLevel ? `LV${task.minPlayerLevel}` : ""));
			section.appendChild(row);
		});
		body.appendChild(section);
	}
}

function urlIcon(itemId) {
	return `/api/icon/${encodeURIComponent(itemId)}`;
}

/* ---------- 兑换配方 ---------- */

function recipeItemChip(entry) {
	const chip = el("span", "recipe_card_item");
	const image = document.createElement("img");
	image.src = urlIcon(entry.id);
	image.loading = "lazy";
	image.alt = "";
	chip.appendChild(image);
	if (entry.count && entry.count > 1) {
		chip.appendChild(el("span", "", `×${formatNumber(entry.count)}`));
	}
	chip.title = `${entry.name || ""}${entry.count ? ` ×${entry.count}` : ""}`;
	return chip;
}

function renderBarters(payload) {
	const list = document.getElementById("barter_list");
	list.innerHTML = "";
	document.getElementById("barters_info").textContent = `共 ${formatNumber(payload.total)} 条兑换配方`;

	(payload.barters || []).forEach((barter) => {
		const card = el("div", "recipe_card");
		const left = el("div", "recipe_card_side");
		barter.required.forEach((entry) => left.appendChild(recipeItemChip(entry)));
		const arrow = el("span", "recipe_arrow", "→");
		const right = el("div", "recipe_card_side");
		right.appendChild(recipeItemChip(barter.offered));

		const meta = el("div", "recipe_card_meta");
		meta.appendChild(el("div", "", barter.trader || ""));
		const tags = [];
		if (barter.traderLevel) {
			tags.push(`LL${barter.traderLevel}`);
		}
		if (barter.buyLimit) {
			tags.push(`限购 ${barter.buyLimit}`);
		}
		if (tags.length) {
			meta.appendChild(el("div", "", tags.join(" · ")));
		}

		card.appendChild(left);
		card.appendChild(arrow);
		card.appendChild(right);
		card.appendChild(meta);
		card.addEventListener("click", () => openItem(barter.offered.id));
		list.appendChild(card);
	});

	renderSimplePager("barters_pager", payload, (offset) => {
		state.barterOffset = offset;
		loadBarters();
	});
}

async function loadBarters() {
	const params = new URLSearchParams({
		limit: String(state.limit),
		offset: String(state.barterOffset || 0),
	});
	if (state.barterQuery) {
		params.set("q", state.barterQuery);
	}
	const payload = await getJson(`/api/barters?${params.toString()}`);
	renderBarters(payload);
}

/* ---------- 制作配方 ---------- */

function renderCrafts(payload) {
	const list = document.getElementById("craft_list");
	list.innerHTML = "";
	document.getElementById("crafts_info").textContent = `共 ${formatNumber(payload.total)} 条制作配方`;

	(payload.crafts || []).forEach((craft) => {
		const card = el("div", "recipe_card");
		const left = el("div", "recipe_card_side");
		craft.required.forEach((entry) => left.appendChild(recipeItemChip(entry)));
		const arrow = el("span", "recipe_arrow", "→");
		const right = el("div", "recipe_card_side");
		right.appendChild(recipeItemChip(craft.product));

		const meta = el("div", "recipe_card_meta");
		meta.appendChild(el("div", "", craft.station || ""));
		const tags = [`等级 ${craft.level || 1}`, formatDuration(craft.duration)];
		meta.appendChild(el("div", "", tags.join(" · ")));

		card.appendChild(left);
		card.appendChild(arrow);
		card.appendChild(right);
		card.appendChild(meta);
		card.addEventListener("click", () => openItem(craft.product.id));
		list.appendChild(card);
	});

	renderSimplePager("crafts_pager", payload, (offset) => {
		state.craftOffset = offset;
		loadCrafts();
	});
}

async function loadCrafts() {
	const params = new URLSearchParams({
		limit: String(state.limit),
		offset: String(state.craftOffset || 0),
	});
	if (state.craftQuery) {
		params.set("q", state.craftQuery);
	}
	const payload = await getJson(`/api/crafts?${params.toString()}`);
	renderCrafts(payload);
}

function renderSimplePager(containerId, payload, onChange) {
	const pager = document.getElementById(containerId);
	if (!pager) {
		return;
	}
	pager.innerHTML = "";
	const page = Math.floor(payload.offset / payload.limit) + 1;
	const pages = Math.max(1, Math.ceil(payload.total / payload.limit));

	const prev = el("button", "", "上一页");
	prev.disabled = payload.offset <= 0;
	prev.addEventListener("click", () => onChange(Math.max(0, payload.offset - payload.limit)));

	const next = el("button", "", "下一页");
	next.disabled = payload.offset + payload.limit >= payload.total;
	next.addEventListener("click", () => onChange(payload.offset + payload.limit));

	pager.appendChild(prev);
	pager.appendChild(el("span", "", `${page} / ${pages}`));
	pager.appendChild(next);
}

/* ---------- 藏身处 ---------- */

async function loadHideout() {
	const payload = await getJson("/api/hideout");
	const list = document.getElementById("hideout_list");
	list.innerHTML = "";
	const stations = payload.stations || [];
	document.getElementById("hideout_info").textContent = `共 ${stations.length} 个设施`;

	stations.forEach((station) => {
		const card = el("div", "hideout_card");

		const head = el("div", "hideout_head");
		if (station.imageLink) {
			const image = document.createElement("img");
			image.src = `/api/asset/hideout/${encodeURIComponent(station.id)}`;
			image.loading = "lazy";
			image.alt = station.name;
			image.addEventListener("error", () => image.remove(), { once: true });
			head.appendChild(image);
		}
		head.appendChild(el("div", "hideout_name", station.name || ""));
		head.appendChild(el("div", "hideout_levels", `${station.levels.length} 级`));
		card.appendChild(head);

		const body = el("div", "hideout_body");
		station.levels.forEach((level) => {
			const block = el("div", "hideout_level_block");
			const title = el("div", "hideout_level_title");
			title.appendChild(el("span", "", `等级 ${level.level}`));
			const meta = [formatDuration(level.constructionTime)];
			title.appendChild(el("span", "hideout_level_meta", `建造 ${meta.join("")}`));
			block.appendChild(title);

			if (level.items.length) {
				const items = el("div", "hideout_items");
				level.items.forEach((entry) => items.appendChild(recipeItemChip(entry)));
				block.appendChild(items);
			}
			level.stationRequirements.forEach((req) => {
				block.appendChild(el("div", "hideout_req", `需要「${req.station}」达到 ${req.level} 级`));
			});
			level.traderRequirements.forEach((req) => {
				block.appendChild(el("div", "hideout_req", `需要 ${req.trader} 达到 LL${req.level}`));
			});
			body.appendChild(block);
		});
		card.appendChild(body);

		head.addEventListener("click", () => body.classList.toggle("is_open"));
		list.appendChild(card);
	});
}

/* ---------- 地图全屏查看器 ---------- */

const viewer = {
	scale: 1,
	x: 0,
	y: 0,
	sourceUrl: "",
};

function viewerApply() {
	const image = document.getElementById("viewer_image");
	image.style.transform = `translate(${viewer.x}px, ${viewer.y}px) scale(${viewer.scale})`;
}

function viewerFit() {
	const image = document.getElementById("viewer_image");
	const stage = document.getElementById("viewer_stage");
	if (!image.naturalWidth || !image.naturalHeight) {
		return;
	}
	const box = stage.getBoundingClientRect();
	const scale = Math.min(box.width / image.naturalWidth, box.height / image.naturalHeight) * 0.95;
	viewer.scale = scale;
	viewer.x = (box.width - image.naturalWidth * scale) / 2;
	viewer.y = (box.height - image.naturalHeight * scale) / 2;
	viewerApply();
}

function viewerZoom(factor, centerX, centerY) {
	const stage = document.getElementById("viewer_stage");
	const box = stage.getBoundingClientRect();
	const cx = centerX === undefined ? box.width / 2 : centerX;
	const cy = centerY === undefined ? box.height / 2 : centerY;
	const next = Math.min(10, Math.max(0.08, viewer.scale * factor));
	viewer.x = cx - ((cx - viewer.x) / viewer.scale) * next;
	viewer.y = cy - ((cy - viewer.y) / viewer.scale) * next;
	viewer.scale = next;
	viewerApply();
}

function openMapViewer(url, title) {
	viewer.sourceUrl = url;
	document.getElementById("viewer_title").textContent = title || "地图";
	const image = document.getElementById("viewer_image");
	const container = document.getElementById("map_viewer");
	image.onload = () => viewerFit();
	container.hidden = false;
	image.src = mapImageUrl(url);
	if (image.complete) {
		viewerFit();
	}
}

function closeMapViewer() {
	document.getElementById("map_viewer").hidden = true;
	if (document.fullscreenElement) {
		document.exitFullscreen().catch(() => {});
	}
}

function setupMapViewer() {
	const stage = document.getElementById("viewer_stage");
	const image = document.getElementById("viewer_image");

	document.getElementById("viewer_close").addEventListener("click", closeMapViewer);
	document.getElementById("viewer_zoom_in").addEventListener("click", () => viewerZoom(1.3));
	document.getElementById("viewer_zoom_out").addEventListener("click", () => viewerZoom(0.77));
	document.getElementById("viewer_zoom_reset").addEventListener("click", viewerFit);

	document.getElementById("viewer_external").addEventListener("click", async (event) => {
		const button = event.target;
		button.disabled = true;
		const original = button.textContent;
		button.textContent = "正在打开…";
		try {
			const payload = await fetch("/api/open-file", {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({ url: state.currentMapOriginal || viewer.sourceUrl }),
			}).then((response) => response.json());
			button.textContent = payload.ok ? "已打开" : `失败：${payload.error || "未知"}`;
		} catch (error) {
			button.textContent = `失败：${error.message}`;
		}
		setTimeout(() => {
			button.disabled = false;
			button.textContent = original;
		}, 2000);
	});

	document.getElementById("map_viewer").addEventListener("dblclick", (event) => {
		if (event.target.closest(".viewer_bar")) {
			return;
		}
		const node = document.getElementById("map_viewer");
		if (document.fullscreenElement) {
			document.exitFullscreen().catch(() => {});
		} else {
			node.requestFullscreen().catch(() => {});
		}
	});

	stage.addEventListener("wheel", (event) => {
		event.preventDefault();
		const box = stage.getBoundingClientRect();
		viewerZoom(event.deltaY < 0 ? 1.15 : 0.87, event.clientX - box.left, event.clientY - box.top);
	}, { passive: false });

	let dragging = false;
	let lastX = 0;
	let lastY = 0;
	stage.addEventListener("pointerdown", (event) => {
		if (event.button !== 0) {
			return;
		}
		dragging = true;
		lastX = event.clientX;
		lastY = event.clientY;
		stage.classList.add("is_dragging");
		stage.setPointerCapture(event.pointerId);
	});
	stage.addEventListener("pointermove", (event) => {
		if (!dragging) {
			return;
		}
		viewer.x += event.clientX - lastX;
		viewer.y += event.clientY - lastY;
		lastX = event.clientX;
		lastY = event.clientY;
		viewerApply();
	});
	const stop = () => {
		dragging = false;
		stage.classList.remove("is_dragging");
	};
	stage.addEventListener("pointerup", stop);
	stage.addEventListener("pointercancel", stop);

	document.addEventListener("keydown", (event) => {
		if (document.getElementById("map_viewer").hidden) {
			return;
		}
		if (event.key === "Escape") {
			closeMapViewer();
		}
	});

	image.addEventListener("dragstart", (event) => event.preventDefault());
}

function goHome() {
	showView("home");
	closeDrawer();
}

function buildTree(nodes, container, depth) {
	nodes.forEach((node) => {
		state.categoryNames.set(node.id, node.name);
		const wrapper = el("div", "cat_node");
		const row = el("div", "cat_row");
		row.style.paddingLeft = `${12 + depth * 12}px`;
		row.dataset.id = node.id;

		const hasChildren = node.children.length > 0;
		const toggle = el("span", "cat_toggle", hasChildren ? "▸" : "");
		const name = el("span", "cat_name", node.name);
		const count = el("span", "cat_count", String(node.count));

		row.appendChild(toggle);
		row.appendChild(name);
		row.appendChild(count);

		const children = el("div", "cat_children");
		if (hasChildren) {
			buildTree(node.children, children, depth + 1);
			const expandByDefault = depth === 0;
			if (expandByDefault) {
				children.classList.add("is_open");
				toggle.textContent = "▾";
			}
			toggle.addEventListener("click", (event) => {
				event.stopPropagation();
				const open = children.classList.toggle("is_open");
				toggle.textContent = open ? "▾" : "▸";
			});
		}

		row.addEventListener("click", () => selectCategory(node.id, row));
		wrapper.appendChild(row);
		wrapper.appendChild(children);
		container.appendChild(wrapper);
	});
}

function selectCategory(categoryId, row) {
	state.category = categoryId;
	state.offset = 0;
	document.querySelectorAll(".cat_row.is_active").forEach((node) => node.classList.remove("is_active"));
	if (row) {
		row.classList.add("is_active");
		let parent = row.parentElement.parentElement;
		while (parent && parent.classList.contains("cat_children")) {
			parent.classList.add("is_open");
			const toggle = parent.previousElementSibling?.querySelector(".cat_toggle");
			if (toggle) {
				toggle.textContent = "▾";
			}
			parent = parent.parentElement.parentElement;
		}
	}
	loadItems();
}

function renderItems(payload) {
	const grid = document.getElementById("item_grid");
	const empty = document.getElementById("empty_state");
	grid.innerHTML = "";
	state.total = payload.total;

	if (!payload.items.length) {
		empty.hidden = false;
		renderPager();
		return;
	}
	empty.hidden = true;

	payload.items.forEach((item) => {
		const card = el("div", "item_card");
		card.addEventListener("click", () => openItem(item.id));

		const image = el("img", "item_icon");
		image.loading = "lazy";
		image.src = iconUrl(item.id);
		image.alt = item.name || "";

		const meta = el("div", "item_meta");
		meta.appendChild(el("div", "item_name", item.name || ""));

		const prices = el("div", "item_prices");
		const flea = el("span", "price_flea", formatNumber(item.avg24hPrice));
		flea.title = "跳蚤市场 24 小时均价";
		prices.appendChild(flea);
		if (item.sellToTrader) {
			const sell = el("span", "", `收 ${formatNumber(item.sellToTrader.price)}`);
			sell.title = `最高收购价 · ${item.sellToTrader.trader}`;
			prices.appendChild(sell);
		}
		meta.appendChild(prices);

		card.appendChild(image);
		card.appendChild(meta);
		grid.appendChild(card);
	});

	grid.scrollTop = 0;
	renderPager();
}

function renderPager() {
	const pager = document.getElementById("pager");
	pager.innerHTML = "";
	const page = Math.floor(state.offset / state.limit) + 1;
	const pages = Math.max(1, Math.ceil(state.total / state.limit));

	const prev = el("button", "", "上一页");
	prev.disabled = state.offset <= 0;
	prev.addEventListener("click", () => {
		state.offset = Math.max(0, state.offset - state.limit);
		loadItems();
	});

	const info = el("span", "", `${page} / ${pages}`);

	const next = el("button", "", "下一页");
	next.disabled = state.offset + state.limit >= state.total;
	next.addEventListener("click", () => {
		state.offset += state.limit;
		loadItems();
	});

	pager.appendChild(prev);
	pager.appendChild(info);
	pager.appendChild(next);
}

function renderResultInfo(payload) {
	const info = document.getElementById("result_info");
	const parts = [];
	if (state.category && state.categoryNames.has(state.category)) {
		parts.push(state.categoryNames.get(state.category));
	}
	if (state.query) {
		parts.push(`搜索「${state.query}」`);
	}
	if (!parts.length) {
		parts.push("全部物品");
	}
	info.textContent = `${parts.join(" · ")} — 共 ${formatNumber(payload.total)} 件`;
}

async function loadItems() {
	const requestId = ++state.requestId;
	const params = new URLSearchParams({
		limit: String(state.limit),
		offset: String(state.offset),
		sort: state.sort,
	});
	if (state.category) {
		params.set("category", state.category);
	}
	if (state.query) {
		params.set("q", state.query);
	}
	const payload = await getJson(`/api/items?${params.toString()}`);
	if (requestId !== state.requestId) {
		return;
	}
	renderResultInfo(payload);
	renderItems(payload);
}

function sectionTitle(text) {
	return el("h3", "", text);
}

function infoRow(label, value) {
	const row = el("div", "info_row");
	row.appendChild(el("span", "label", label));
	row.appendChild(el("span", "value", value));
	return row;
}

function priceTable(headers, rows) {
	const table = el("table", "price_table");
	const thead = el("thead");
	const headRow = el("tr");
	headers.forEach((header) => headRow.appendChild(el("th", "", header)));
	thead.appendChild(headRow);
	table.appendChild(thead);

	const tbody = el("tbody");
	rows.forEach((cells) => {
		const row = el("tr");
		cells.forEach((cell) => {
			const isNumber = typeof cell === "number" || /^[\d,]+$/.test(String(cell));
			row.appendChild(el("td", isNumber ? "num" : "", cell));
		});
		tbody.appendChild(row);
	});
	table.appendChild(tbody);
	return table;
}

function recipeItem(entry) {
	const wrapper = el("span", "recipe_item");
	const image = el("img", "recipe_thumb");
	image.loading = "lazy";
	image.src = iconUrl(entry.id);
	image.alt = entry.shortName || entry.name || "";
	image.title = entry.name || "";
	wrapper.appendChild(image);
	wrapper.appendChild(el("span", "", `×${formatNumber(entry.count)}`));
	wrapper.title = entry.name || "";
	return wrapper;
}

function recipeBlock(recipe, note) {
	const wrapper = el("div", "recipe");
	const left = el("div", "recipe_side");
	recipe.required.forEach((entry) => left.appendChild(recipeItem(entry)));

	const arrow = el("span", "recipe_arrow", "→");

	const right = el("div", "recipe_side");
	right.appendChild(recipeItem(recipe.product || recipe.offered));

	wrapper.appendChild(left);
	wrapper.appendChild(arrow);
	wrapper.appendChild(right);
	if (note) {
		wrapper.appendChild(el("div", "recipe_note", note));
	}
	return wrapper;
}

function renderDetail(item) {
	const body = document.getElementById("drawer_body");
	body.innerHTML = "";

	const head = el("div", "detail_head");
	const image = el("img", "detail_image");
	image.src = iconUrl(item.id, "image");
	image.alt = item.name || "";
	image.addEventListener("error", () => {
		image.src = iconUrl(item.id);
	}, { once: true });

	const title = el("div", "detail_title");
	title.appendChild(el("h2", "", item.name || ""));
	title.appendChild(el("div", "short_name", item.shortName || ""));
	const badges = el("div", "badge_list");
	(item.categoryNames || []).slice(0, 6).forEach((name) => {
		if (name) {
			badges.appendChild(el("span", "badge", name));
		}
	});
	title.appendChild(badges);

	head.appendChild(image);
	head.appendChild(title);
	body.appendChild(head);

	const basic = el("div", "section");
	basic.appendChild(sectionTitle("基本信息"));
	const grid = el("div", "info_grid");
	grid.appendChild(infoRow("重量", item.weight !== null && item.weight !== undefined ? `${item.weight} kg` : "--"));
	grid.appendChild(infoRow("尺寸", item.width && item.height ? `${item.width} × ${item.height}` : "--"));
	grid.appendChild(infoRow("基础价", formatNumber(item.basePrice)));
	grid.appendChild(infoRow("堆叠上限", formatNumber(item.stackMaxSize)));
	basic.appendChild(grid);
	body.appendChild(basic);

	const price = el("div", "section");
	price.appendChild(sectionTitle("价格"));
	const fleaRows = [
		["跳蚤均价（24 小时）", formatNumber(item.avg24hPrice)],
		["跳蚤最低（当前）", formatNumber(item.lastLowPrice)],
		["跳蚤最低（24 小时）", formatNumber(item.low24hPrice)],
		["跳蚤最高（24 小时）", formatNumber(item.high24hPrice)],
		["在售数量", formatNumber(item.lastOfferCount)],
	];
	price.appendChild(priceTable(["跳蚤市场", "价格"], fleaRows));

	if ((item.sellOffers || []).length) {
		const sub = el("div", "section");
		sub.appendChild(sectionTitle("商人收购价（卖给它）"));
		sub.appendChild(priceTable(
			["商人", "价格"],
			item.sellOffers.map((offer) => [offer.trader, formatNumber(offer.price)]),
		));
		price.appendChild(sub);
	}

	if ((item.buyOffers || []).length) {
		const sub = el("div", "section");
		sub.appendChild(sectionTitle("商人出售价（从它买）"));
		sub.appendChild(priceTable(
			["商人", "价格", "等级", "限购"],
			item.buyOffers.map((offer) => [
				offer.trader,
				formatNumber(offer.price),
				offer.traderLevel ? `LL${offer.traderLevel}` : "--",
				offer.buyLimit ? formatNumber(offer.buyLimit) : "--",
			]),
		));
		price.appendChild(sub);
	}
	body.appendChild(price);

	if ((item.barterFor || []).length) {
		const section = el("div", "section");
		section.appendChild(sectionTitle("如何兑换获得"));
		item.barterFor.forEach((barter) => {
			section.appendChild(recipeBlock(barter, `${barter.trader}${barter.traderLevel ? ` · LL${barter.traderLevel}` : ""}${barter.buyLimit ? ` · 限购 ${barter.buyLimit}` : ""}`));
		});
		body.appendChild(section);
	}

	if ((item.barterUsedIn || []).length) {
		const section = el("div", "section");
		section.appendChild(sectionTitle("可以拿去兑换"));
		item.barterUsedIn.forEach((barter) => {
			section.appendChild(recipeBlock(barter, `${barter.trader}${barter.traderLevel ? ` · LL${barter.traderLevel}` : ""}`));
		});
		body.appendChild(section);
	}

	if ((item.craftedBy || []).length) {
		const section = el("div", "section");
		section.appendChild(sectionTitle("藏身处制作"));
		item.craftedBy.forEach((craft) => {
			section.appendChild(recipeBlock(craft, `${craft.station} 等级 ${craft.level} · 耗时 ${formatDuration(craft.duration)}`));
		});
		body.appendChild(section);
	}

	if ((item.usedInCrafts || []).length) {
		const section = el("div", "section");
		section.appendChild(sectionTitle("用于制作"));
		item.usedInCrafts.forEach((craft) => {
			section.appendChild(recipeBlock(craft, `${craft.station} 等级 ${craft.level} · 耗时 ${formatDuration(craft.duration)}`));
		});
		body.appendChild(section);
	}

	if ((item.tasks || []).length) {
		const section = el("div", "section");
		section.appendChild(sectionTitle(`相关任务（${item.tasks.length}）`));
		item.tasks.forEach((task) => {
			const row = el("div", "task_row");
			const left = el("div");
			left.appendChild(el("div", "", task.name || ""));
			const meta = [task.trader, task.map].filter(Boolean).join(" · ");
			if (meta) {
				left.appendChild(el("div", "task_trader", meta));
			}
			row.appendChild(left);
			row.appendChild(el("span", "task_trader", task.minPlayerLevel ? `LV${task.minPlayerLevel}` : ""));
			section.appendChild(row);
		});
		body.appendChild(section);
	}

	if (item.description) {
		const section = el("div", "section");
		section.appendChild(sectionTitle("描述"));
		section.appendChild(el("div", "description_text", item.description));
		body.appendChild(section);
	}
}

async function openItem(itemId) {
	const requestId = ++state.drawerRequestId;
	const drawer = document.getElementById("drawer");
	const mask = document.getElementById("drawer_mask");
	const body = document.getElementById("drawer_body");
	body.innerHTML = '<div class="loading_block">读取中…</div>';
	drawer.hidden = false;
	mask.hidden = false;
	drawer.scrollTop = 0;
	try {
		const payload = await getJson(`/api/items/${encodeURIComponent(itemId)}`);
		if (requestId === state.drawerRequestId) {
			renderDetail(payload.item);
		}
	} catch (error) {
		if (requestId === state.drawerRequestId) {
			body.replaceChildren(el("div", "loading_block", `读取失败：${error.message}`));
		}
	}
}

function closeDrawer() {
	state.drawerRequestId++;
	document.getElementById("drawer").hidden = true;
	document.getElementById("drawer_mask").hidden = true;
}

function renderSyncState(sync) {
	const badge = document.getElementById("sync_state");
	const dataProgress = sync.progress || {};
	const bar = document.getElementById("sync_progress");
	const fill = document.getElementById("sync_progress_bar");
	badge.className = "sync_state";

	const setBar = (ratio, text) => {
		bar.hidden = false;
		fill.style.width = `${Math.round(Math.min(1, Math.max(0, ratio)) * 100)}%`;
		fill.title = text;
	};
	const hideBar = () => {
		bar.hidden = true;
		fill.style.width = "0%";
	};

	if (sync.running) {
		const total = dataProgress.total || 0;
		const done = dataProgress.done || 0;
		badge.classList.add("is_running");
		badge.textContent = total
			? `正在同步数据 ${formatNumber(done)} / ${formatNumber(total)}${dataProgress.label ? ` · ${dataProgress.label}` : ""}`
			: "正在同步数据…";
		setBar(total ? done / total : 0, badge.textContent);
		return;
	}
	hideBar();
	const result = sync.lastResult;
	if (result && result.errors && result.errors.length > 0) {
		badge.classList.add("is_error");
		badge.textContent = `同步出错 ${result.errors.length} 项`;
		return;
	}
	if (sync.lastFinishedAt) {
		badge.classList.add("is_ok");
		badge.textContent = `数据截至 ${formatTime(sync.lastFinishedAt)}`;
		return;
	}
	badge.textContent = "尚未同步";
}

async function refreshSync() {
	const sync = await getJson("/api/sync/status");
	renderSyncState(sync);
	return sync;
}

/* ---------- 设置：自动更新 ---------- */

const updateUi = { timer: null };

async function openSettings() {
	showView("settings");
	await refreshUpdateStatus();
	scheduleUpdatePoll();
}

function versionLabel(text) {
	const clean = String(text || "").replace(/^v/i, "");
	return clean ? `v${clean}` : "--";
}

function updateStatusText(status) {
	const progress = status.progress || {};
	if (progress.phase === "downloading") {
		return `正在下载安装包 ${progress.percent || 0}%`;
	}
	if (progress.phase === "downloaded") {
		return "安装包已下载完成，点击「安装并重启」完成更新";
	}
	if (progress.phase === "error" && progress.message) {
		return progress.message;
	}
	const result = status.result;
	if (!result) {
		return status.lastError || "点击右侧按钮检查是否有新版本";
	}
	if (!result.ok) {
		return result.message || "检查更新失败";
	}
	const suffix = result.warning ? `（${result.warning}）` : "";
	if (result.hasUpdate) {
		const how = result.manualOnly ? "，请前往发布页下载" : "";
		return `发现新版本 ${versionLabel(result.latest)}${how}${suffix}`;
	}
	return result.latest ? `已是最新版本（${versionLabel(status.current)}）${suffix}` : `已是最新版本${suffix}`;
}

function renderNotesBody(text) {
	/* 只处理更新日志用得到的写法：### 小标题、- 列表、**加粗**，其余按纯文本输出 */
	const wrap = el("div", "update_notes_body");
	String(text || "")
		.split("\n")
		.forEach((line) => {
			const trimmed = line.trim();
			if (!trimmed) {
				return;
			}
			if (/^#{1,6}\s/.test(trimmed)) {
				wrap.appendChild(el("div", "update_notes_group", trimmed.replace(/^#{1,6}\s*/, "")));
				return;
			}
			const item = el("div", trimmed.startsWith("- ") ? "update_notes_item" : "update_notes_line");
			const content = trimmed.replace(/^-\s+/, "").split("**");
			content.forEach((piece, index) => {
				if (!piece) {
					return;
				}
				if (index % 2 === 1) {
					item.appendChild(el("strong", "", piece));
				} else {
					item.appendChild(document.createTextNode(piece));
				}
			});
			wrap.appendChild(item);
		});
	return wrap;
}

function renderUpdateState(status) {
	document.getElementById("update_current").textContent = versionLabel(status.current);
	document.getElementById("update_last").textContent = status.lastCheckAt
		? formatTime(status.lastCheckAt)
		: "从未检查";

	const auto = document.getElementById("update_auto");
	auto.checked = Boolean(status.autoCheck);
	auto.parentElement.classList.toggle("is_on", Boolean(status.autoCheck));

	const proxyInput = document.getElementById("update_proxy");
	if (document.activeElement !== proxyInput) {
		proxyInput.value = status.proxy || "";
	}

	const checkButton = document.getElementById("btn_check_update");
	checkButton.disabled = Boolean(status.checking);
	checkButton.textContent = status.checking ? "检查中…" : "检查更新";

	const statusNode = document.getElementById("update_status");
	statusNode.textContent = updateStatusText(status);

	const progress = status.progress || {};
	const phase = progress.phase || "";
	const downloadButton = document.getElementById("btn_download_update");
	const result = status.result || {};
	const canDownload = Boolean(result.hasUpdate) && status.downloadable && !result.manualOnly;
	if (phase === "downloaded") {
		downloadButton.hidden = false;
		downloadButton.textContent = "安装并重启";
		downloadButton.disabled = false;
	} else if (canDownload) {
		downloadButton.hidden = false;
		downloadButton.textContent = "下载并安装";
		downloadButton.disabled = phase === "downloading";
	} else {
		downloadButton.hidden = true;
	}

	const bar = document.getElementById("update_progress");
	const fill = document.getElementById("update_progress_bar");
	if (progress.phase === "downloading" || progress.phase === "downloaded") {
		bar.hidden = false;
		fill.style.width = `${progress.phase === "downloaded" ? 100 : progress.percent || 0}%`;
	} else {
		bar.hidden = true;
		fill.style.width = "0%";
	}

	const notesNode = document.getElementById("update_notes");
	const releases = (result.releases || []).filter((entry) => entry.notes);
	const fallback = result.hasUpdate && result.notes ? [{ version: result.latest, notes: result.notes }] : [];
	const list = releases.length ? releases : fallback;
	if (list.length && progress.phase !== "downloading") {
		notesNode.hidden = false;
		notesNode.innerHTML = "";
		list.forEach((entry) => {
			notesNode.appendChild(el("div", "update_notes_title", versionLabel(entry.version)));
			notesNode.appendChild(renderNotesBody(entry.notes));
		});
	} else {
		notesNode.hidden = true;
		notesNode.innerHTML = "";
	}
}

async function refreshUpdateStatus() {
	const status = await getJson("/api/update/status");
	renderUpdateState(status);
	return status;
}

function scheduleUpdatePoll(delay = 3000) {
	clearTimeout(updateUi.timer);
	updateUi.timer = setTimeout(async () => {
		let status = null;
		try {
			status = await refreshUpdateStatus();
		} catch (error) {
			status = null;
		}
		const progress = (status && status.progress) || {};
		const busy = Boolean(status && (status.checking || progress.phase === "downloading"));
		if (state.view === "settings") {
			scheduleUpdatePoll(busy ? 1000 : 30000);
		}
	}, delay);
}

async function checkUpdate() {
	await fetch("/api/update/check", { method: "POST" });
	await refreshUpdateStatus();
	scheduleUpdatePoll(1000);
}

async function toggleAutoUpdate() {
	const next = !document.getElementById("update_auto").checked;
	await fetch("/api/update/auto", {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify({ enabled: next }),
	});
	await refreshUpdateStatus();
	if (next) {
		await checkUpdate();
	}
}

async function saveProxy() {
	const input = document.getElementById("update_proxy");
	const payload = await fetch("/api/update/proxy", {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify({ proxy: input.value.trim() }),
	}).then((response) => response.json());
	const statusNode = document.getElementById("update_status");
	if (!payload.ok) {
		statusNode.textContent = payload.message || "代理地址不正确";
		return;
	}
	statusNode.textContent = payload.proxy
		? `代理已保存：${payload.proxy}，正在重新检查…`
		: "已关闭代理，正在重新检查…";
	await fetch("/api/update/check", { method: "POST" });
	await refreshUpdateStatus();
	scheduleUpdatePoll(1000);
}

async function runUpdateAction() {
	const button = document.getElementById("btn_download_update");
	const progress = await getJson("/api/update/status").then((status) => status.progress || {});
	if (progress.phase === "downloaded") {
		const payload = await fetch("/api/update/install", { method: "POST" }).then((response) => response.json());
		if (!payload.ok) {
			document.getElementById("update_status").textContent = payload.message || "安装失败";
			return;
		}
		document.getElementById("update_status").textContent = "程序即将关闭并完成更新…";
		button.disabled = true;
		setTimeout(() => window.close(), 1200);
		return;
	}
	const payload = await fetch("/api/update/download", { method: "POST" }).then((response) => response.json());
	if (!payload.ok) {
		document.getElementById("update_status").textContent = payload.message || "下载失败";
		return;
	}
	scheduleUpdatePoll(800);
}

function renderCategories(treePayload) {
	let tree = treePayload || [];
	if (tree.length === 1 && tree[0].children.length) {
		state.categoryNames.set(tree[0].id, tree[0].name);
		tree = tree[0].children;
	}
	const container = document.getElementById("category_tree");
	container.innerHTML = "";
	buildTree(tree, container, 0);
}

async function init() {
	const [health, modes] = await Promise.all([
		getJson("/api/health"),
		getJson("/api/modes"),
	]);
	const versionNode = document.getElementById("version");
	if (versionNode) {
		versionNode.textContent = `v${health.version}`;
	}
	const titleVersion = document.getElementById("title_version");
	if (titleVersion) {
		titleVersion.textContent = `v${health.version}`;
	}
	state.modes = modes.modes;
	state.mode = modes.current;
	renderModeSwitch();

	await refreshAll();
	await refreshSync();

	showView("home");

	const search = document.getElementById("search_input");
	search.addEventListener("input", () => {
		clearTimeout(state.searchTimer);
		state.searchTimer = setTimeout(() => {
			state.query = search.value.trim();
			state.offset = 0;
			loadItems();
		}, 250);
	});

	document.getElementById("sort_select").addEventListener("change", (event) => {
		state.sort = event.target.value;
		state.offset = 0;
		loadItems();
	});

	document.getElementById("brand_home").addEventListener("click", goHome);
	document.getElementById("btn_settings").addEventListener("click", openSettings);
	document.getElementById("btn_check_update").addEventListener("click", checkUpdate);
	document.getElementById("btn_save_proxy").addEventListener("click", saveProxy);
	document.getElementById("update_proxy").addEventListener("keydown", (event) => {
		if (event.key === "Enter") {
			event.preventDefault();
			saveProxy();
		}
	});
	document.getElementById("btn_download_update").addEventListener("click", runUpdateAction);
	document.getElementById("update_auto").parentElement.addEventListener("click", (event) => {
		event.preventDefault();
		toggleAutoUpdate();
	});
	document.getElementById("btn_back").addEventListener("click", goHome);
	document.getElementById("btn_back_traders").addEventListener("click", goHome);
	document.getElementById("btn_back_barters").addEventListener("click", goHome);
	document.getElementById("btn_back_crafts").addEventListener("click", goHome);
	document.getElementById("btn_back_hideout").addEventListener("click", goHome);
	document.getElementById("btn_back_maps").addEventListener("click", goHome);
	document.getElementById("btn_back_settings").addEventListener("click", goHome);

	document.getElementById("map_image").addEventListener("click", () => {
		if (state.currentMapImage) {
			openMapViewer(state.currentMapImage, state.currentMapTitle || "地图");
		}
	});
	setupMapViewer();
	setupQuickMap();

	document.getElementById("barter_search").addEventListener("input", (event) => {
		clearTimeout(state.barterTimer);
		state.barterTimer = setTimeout(() => {
			state.barterQuery = event.target.value.trim();
			state.barterOffset = 0;
			loadBarters();
		}, 250);
	});

	document.getElementById("craft_search").addEventListener("input", (event) => {
		clearTimeout(state.craftTimer);
		state.craftTimer = setTimeout(() => {
			state.craftQuery = event.target.value.trim();
			state.craftOffset = 0;
			loadCrafts();
		}, 250);
	});

	document.querySelectorAll(".toggle").forEach((node) => {
		const key = node.dataset.key;
		node.addEventListener("click", () => {
			state.taskFilters[key] = !state.taskFilters[key];
			node.classList.toggle("is_on", state.taskFilters[key]);
			state.taskOffset = 0;
			loadTasks();
		});
	});

	document.getElementById("player_level").addEventListener("change", async (event) => {
		const level = Math.max(1, Math.min(79, Number(event.target.value) || 1));
		event.target.value = level;
		state.playerLevel = level;
		const payload = await fetch("/api/progress/level", {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({ level }),
		}).then((response) => response.json());
		state.playerLevel = payload.playerLevel;
		await loadTaskFilters();
		await loadTasks();
	});

	document.getElementById("task_search").addEventListener("input", (event) => {
		clearTimeout(state.taskSearchTimer);
		state.taskSearchTimer = setTimeout(() => {
			state.taskQuery = event.target.value.trim();
			state.taskOffset = 0;
			loadTasks();
		}, 250);
	});

	document.getElementById("drawer_close").addEventListener("click", closeDrawer);
	document.getElementById("drawer_mask").addEventListener("click", closeDrawer);
	document.addEventListener("keydown", (event) => {
		if (event.key === "Escape") {
			closeDrawer();
		}
	});

	/* 图片下载失败时藏起来，避免界面上出现一片破图标 */
	document.addEventListener(
		"error",
		(event) => {
			if (event.target instanceof HTMLImageElement) {
				event.target.classList.add("img_failed");
			}
		},
		true,
	);

	document.getElementById("btn_sync_all").addEventListener("click", rebuildGameData);
}

function setSyncMessage(text) {
	const node = document.getElementById("sync_message");
	if (node) {
		node.textContent = text;
	}
}

async function afterDataSync() {
	await refreshAll();
	document.getElementById("category_tree").replaceChildren();
	if (state.view === "items") {
		const categories = await getJson("/api/categories");
		renderCategories(categories.tree);
		await loadItems();
	}
	if (state.view === "tasks") {
		await loadTaskFilters();
		await loadTasks();
	}
	if (["maps", "traders", "barters", "crafts", "hideout"].includes(state.view)) {
		await openModule(state.view);
	}
}

async function rebuildGameData() {
	const button = document.getElementById("btn_sync_all");
	button.disabled = true;
	setSyncMessage("正在从 Tarkov.dev 重建三种模式的资料…");
	try {
		const response = await fetch("/api/sync/now", { method: "POST" });
		if (!response.ok) {
			throw new Error(`请求失败 ${response.status}`);
		}
		let sync = await refreshSync();
		while (sync.running) {
			await new Promise((resolve) => setTimeout(resolve, 750));
			sync = await refreshSync();
		}
		if (!sync.lastResult?.ok) {
			const issue = sync.lastResult?.errors?.[0];
			setSyncMessage(issue ? `重建失败 ${issue.mode} ${issue.key} · ${issue.error}` : "重建失败，请重试");
			return;
		}
		setSyncMessage("三种模式的资料已更新");
		await afterDataSync();
	} catch (error) {
		setSyncMessage(`无法读取重建状态 · ${error.message}`);
	} finally {
		button.disabled = false;
	}
}

init().catch((error) => {
	const badge = document.getElementById("sync_state");
	badge.className = "sync_state is_error";
	badge.textContent = error.message;
});
