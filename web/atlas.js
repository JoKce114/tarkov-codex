/* 交互地图使用与任务地图相同的 SVG 坐标系。 */
(() => {
	"use strict";

	const GROUPS = {
		extracts: ["撤离点", "↗", "#8bc99a", true],
		spawns: ["出生点", "▲", "#e0a178", true],
		tasks: ["任务", "⚑", "#ebc46c", true],
		interactives: ["可使用物体", "◇", "#b2a6e5", false],
		containers: ["容器", "▣", "#7fb7d4", false],
		loot: ["散落物资", "◆", "#cfb886", false],
		transits: ["地图转移点", "⇄", "#71c2bd", false],
		hazards: ["危险区域", "!", "#e8867e", false],
		landmarks: ["地标", "●", "#c2c2b6", false],
		transport: ["交通工具", "⇢", "#a1bada", false]
	};
	const PAGE_SIZE = 35;
	const GROUP_ICONS = {
		extracts: "extract_shared", spawns: "spawn_pmc", tasks: "quest_objective", interactives: "switch",
		containers: "container_duffle-bag", loot: "loose_loot", transits: "extract_transit", hazards: "hazard", transport: "btr_stop"
	};
	const preferences = new Map();
	let ui;
	let data;
	let key;
	let request;
	let prefs;
	let groups = new Map();
	let floors = new Map();
	let activeFloor = null;
	let selected = null;
	let visiblePoints = [];
	let hasEnabledPoints = false;
	let backgroundKey = "";
	let retryToken = "";
	let hasLoadedTile = false;
	let clusterPoints = new Map();
	let frame = 0;
	let returnFocus;
	let inertElements = [];
	const view = { x: 0, y: 0, zoom: 1 };

	function node(tag, className, value) {
		const element = document.createElement(tag);
		if (className) {
			element.className = className;
		}
		if (value != null) {
			element.textContent = value;
		}
		return element;
	}

	function button(className, label, action) {
		const control = node("button", className, label);
		control.type = "button";
		control.addEventListener("click", action);
		return control;
	}

	function status(message) {
		ui.notice.textContent = message;
		ui.notice.hidden = !message;
	}

	function showHome(message) {
		status(message);
		ui.notice.append(button("atlas_sync", "返回首页", () => { closeAtlas(); goHome(); }));
	}

	function iconImage(icon, group) {
		if (!icon || !/^[a-z0-9_-]+$/.test(icon)) {
			return node("span", "atlas_symbol", GROUPS[group][1]);
		}
		const image = node("img", "atlas_symbol_image");
		image.alt = "";
		image.src = "/map_icons/" + icon + ".png";
		return image;
	}

	function initialize() {
		const root = document.getElementById("map_atlas");
		root.setAttribute("aria-label", "交互地图");
		root.innerHTML = `
			<header class="atlas_header">
				<button type="button" class="atlas_back">← 返回</button>
				<h2>交互地图<span class="atlas_title_map"></span></h2>
				<span class="atlas_meta"></span>
				<button type="button" class="atlas_mobile_filters" aria-expanded="false">图层筛选</button>
			</header>
			<aside class="atlas_sidebar" aria-label="地图与图层">
				<div class="atlas_map_fields">
					<label class="atlas_field_label" for="atlas_map_select">地图</label>
					<select id="atlas_map_select" class="atlas_map_select"></select>
					<input type="search" class="atlas_search" aria-label="搜索点位、任务或物品" placeholder="搜索点位、任务或物品" autocomplete="off">
					<div class="atlas_results" hidden></div>
				</div>
				<div class="atlas_layer_header"><h3>图层筛选</h3><button type="button" class="atlas_clear">隐藏全部</button></div>
				<div class="atlas_layers"></div>
			</aside>
			<div class="atlas_map">
				<div class="atlas_stage" role="region" tabindex="0" aria-label="地图，方向键平移，加减键缩放，Home 键查看全图">
					<img class="atlas_image" alt="" draggable="false" hidden>
					<div class="atlas_tiles" aria-hidden="true" hidden></div>
					<div class="atlas_markers"></div>
				</div>
				<div class="atlas_toolbar" aria-label="地图工具">
					<button type="button" class="atlas_plus" aria-label="放大" title="放大">+</button>
					<span class="atlas_zoom"></span>
					<button type="button" class="atlas_minus" aria-label="缩小" title="缩小">−</button>
					<button type="button" class="atlas_fit" aria-label="查看全图" title="查看全图">⛶</button>
				</div>
				<label class="atlas_floor" hidden>楼层<select class="atlas_floor_select" aria-label="楼层"></select></label>
				<div class="atlas_notices">
					<div class="atlas_notice" role="status" hidden></div>
					<div class="atlas_background_notice" role="status" hidden><span class="atlas_background_message"></span><button type="button" class="atlas_retry">重试</button></div>
				</div>
				<section class="atlas_card" aria-label="点位详情" hidden></section>
				<div class="atlas_map_footer"><span class="atlas_count"></span><span class="atlas_credit"></span></div>
			</div>`;
		ui = { root };
		for (const field of ["back", "meta", "title_map", "mobile_filters", "map_select", "search", "results", "clear", "layers", "stage", "image", "tiles", "markers", "zoom", "plus", "minus", "fit", "floor", "floor_select", "notice", "background_notice", "background_message", "retry", "card", "count", "credit"]) {
			ui[field] = root.querySelector(".atlas_" + field);
		}
		ui.back.addEventListener("click", closeAtlas);
		ui.mobile_filters.addEventListener("click", () => toggleSidebar(!root.classList.contains("atlas_filters_open")));
		ui.map_select.addEventListener("change", () => loadMap(ui.map_select.value));
		ui.floor_select.addEventListener("change", () => {
			setFloor(ui.floor_select.value);
			updateFilters();
		});
		ui.search.addEventListener("input", showResults);
		ui.clear.addEventListener("click", () => {
			if (!data) {
				return;
			}
			const enable = !hasEnabledPoints;
			for (const group of groups.values()) {
				setEnabled(group, group, enable);
			}
			if (enable) {
				prefs.hiddenStatuses.clear();
			}
			updateFilters();
		});
		ui.plus.addEventListener("click", () => zoomBy(1.45));
		ui.minus.addEventListener("click", () => zoomBy(1 / 1.45));
		ui.fit.addEventListener("click", fit);
		ui.retry.addEventListener("click", () => {
			setFloor(activeFloor?.key, true);
			ui.stage.focus();
			redraw();
		});
		ui.markers.addEventListener("click", (event) => {
			const marker = event.target.closest(".atlas_marker");
			const points = marker && clusterPoints.get(marker.dataset.cell);
			if (points) {
				showCluster(points);
				if (!event.detail) {
					ui.card.querySelector("h3").focus();
				}
			}
		});
		attachNavigation();
		new ResizeObserver(redraw).observe(ui.stage);
		document.addEventListener("keydown", (event) => {
			if (root.hidden || event.defaultPrevented || event.key !== "Escape" || !document.getElementById("drawer")?.hidden) {
				return;
			}
			event.preventDefault();
			if (!ui.card.hidden) {
				closeCard(true);
			} else if (root.classList.contains("atlas_filters_open")) {
				toggleSidebar(false);
				ui.mobile_filters.focus();
			} else {
				closeAtlas();
			}
		}, true);
	}

	function toggleSidebar(open) {
		ui.root.classList.toggle("atlas_filters_open", open);
		ui.mobile_filters.setAttribute("aria-expanded", String(open));
	}

	async function readJson(path, signal) {
		const response = await fetch(path, { signal });
		if (!response.ok) {
			throw new Error(String(response.status));
		}
		return response.json();
	}

	async function openAtlas(mapKey = "lighthouse", focus = null) {
		if (!ui) {
			initialize();
		}
		const drawer = document.getElementById("drawer");
		if (ui.root.hidden) {
			returnFocus = document.activeElement;
			for (const sibling of document.body.children) {
				if (sibling !== ui.root && !["drawer", "drawer_mask"].includes(sibling.id) && sibling.tagName !== "SCRIPT" && !sibling.inert) {
					sibling.inert = true;
					inertElements.push(sibling);
				}
			}
		}
		if (drawer && !drawer.hidden) {
			closeDrawer();
		}
		ui.root.hidden = false;
		ui.back.focus();
		await loadMap(mapKey, focus, key === mapKey && !!data);
	}

	function closeAtlas() {
		if (!ui || ui.root.hidden) {
			return;
		}
		ui.root.hidden = true;
		request?.abort();
		toggleSidebar(false);
		inertElements.forEach((element) => { element.inert = false; });
		inertElements = [];
		if (returnFocus?.getClientRects().length) {
			returnFocus.focus();
		}
	}

	function refreshAtlas() {
		if (ui && !ui.root.hidden) {
			return loadMap(key, null, true);
		}
	}

	async function loadMap(mapKey, focus = null, preserve = false) {
		request?.abort();
		preserve = preserve && !!data && key === mapKey;
		const controller = new AbortController();
		request = controller;
		const previous = preserve ? selected : null;
		const previousFloor = preserve ? activeFloor?.key : "";
		key = mapKey;
		if (!preserve) {
			data = null;
			selected = null;
			visiblePoints = [];
			activeFloor = null;
			floors.clear();
			backgroundKey = "";
			ui.background_notice.hidden = true;
			ui.floor.hidden = true;
			ui.image.hidden = true;
			ui.image.removeAttribute("src");
			delete ui.image.dataset.source;
			ui.tiles.hidden = true;
			ui.tiles.replaceChildren();
			ui.markers.replaceChildren();
			ui.layers.replaceChildren();
			ui.search.value = "";
			ui.results.hidden = true;
			ui.card.hidden = true;
			ui.meta.textContent = "";
			ui.title_map.textContent = "";
			ui.credit.textContent = "";
			ui.count.textContent = "";
		}
		status("正在读取地图…");
		try {
			const maps = await readJson("/api/atlas", controller.signal);
			if (controller.signal.aborted) {
				return;
			}
			ui.map_select.replaceChildren(...maps.maps.map((entry) => new Option(entry.name, entry.key)));
			const map = maps.maps.find((entry) => entry.key === mapKey);
			if (!map) {
				ui.map_select.selectedIndex = -1;
				status("本地暂无这张交互地图，请先在首页同步游戏数据。");
				return;
			}
			ui.map_select.value = mapKey;
			ui.title_map.textContent = " · " + map.name;
			const payload = await readJson("/api/atlas/" + encodeURIComponent(mapKey), controller.signal);
			if (controller.signal.aborted) {
				return;
			}
			if (!(payload.width > 0 && payload.height > 0)) {
				throw new Error("地图尺寸缺失");
			}
			data = payload;
			if (!preferences.has(key)) {
				preferences.set(key, { filters: new Map(), open: new Set(["extracts"]), hiddenStatuses: new Set(), lootQuery: "" });
			}
			prefs = preferences.get(key);
			floors = new Map((data.floors || []).map((floor) => [floor.key, floor]));
			ui.floor.hidden = !floors.size;
			ui.floor_select.replaceChildren(new Option("全部楼层", ""), ...Array.from(floors.values(), (floor) => new Option(floor.name, floor.key)));
			setFloor(previousFloor);
			indexPoints();
			ui.credit.textContent = data.author ? "制图 · " + data.author : "";
			ui.meta.textContent = [data.players ? data.players + " 人" : "", data.raidDuration ? data.raidDuration + " 分钟" : ""].filter(Boolean).join("　·　");
			if (data.hasLayers) {
				status("");
			} else {
				showHome("本地缺少点位，请在首页同步游戏数据。");
			}
			renderFilters();
			selected = previous && data.points.find((point) => samePoint(point, previous));
			updateFilters();
			showResults();
			if (!preserve) {
				fit();
			}
			if (selected) {
				showPoint(selected);
			}
			if (focus?.bossId) {
				const matching = data.points.filter((point) => point.bossIds?.includes(focus.bossId));
				for (const point of matching) {
					point.searchText += " " + (focus.bossName || focus.bossId).toLowerCase();
				}
				ui.search.value = focus.bossName || "";
				showResults();
				if (matching.length) {
					locate(matching[0]);
					if (matching.length > 1) {
						showCluster(matching);
					}
				} else {
					status("当前地图没有此首领的已知坐标。");
				}
			} else if (focus) {
				const target = data.points.find((point) => point.taskId === focus.taskId
					&& point.objectiveIndex === focus.objectiveIndex
					&& (focus.pointIndex == null || point.pointIndex === focus.pointIndex));
				if (target) {
					locate(target);
				} else {
					status("本地没有这个任务目标的地图坐标。");
				}
			}
		} catch (error) {
			if (!controller.signal.aborted) {
				status("地图读取失败。请检查网络，或在首页选择「同步游戏数据」后重试。");
			}
		}
	}

	function setFloor(floorKey, retry = false) {
		activeFloor = floors.get(floorKey) || null;
		ui.floor_select.value = activeFloor?.key || "";
		const nextKey = key + "/" + ui.floor_select.value;
		if (nextKey !== backgroundKey || retry) {
			backgroundKey = nextKey;
			retryToken = retry ? String(Date.now()) : "";
			hasLoadedTile = false;
			ui.tiles.replaceChildren();
			ui.background_notice.hidden = true;
		}
		const overviewSvg = data.hasSvg === false ? "" : "/api/map/svg/" + encodeURIComponent(key);
		const source = activeFloor ? activeFloor.svgUrl : overviewSvg;
		const tiles = activeFloor ? activeFloor.tiles : data.tiles;
		ui.tiles.hidden = !tiles?.length;
		if (source) {
			if (ui.image.dataset.source !== source || (retry && ui.image.dataset.failed === "true")) {
				const image = node("img", "atlas_image");
				image.draggable = false;
				image.dataset.source = source;
				image.addEventListener("error", () => {
					if (ui.image === image) {
						image.dataset.failed = "true";
						updateBackgroundNotice();
					}
				});
				image.addEventListener("load", updateBackgroundNotice);
				ui.image.replaceWith(image);
				ui.image = image;
				image.src = backgroundUrl(source);
			}
			ui.image.width = data.width;
			ui.image.height = data.height;
			ui.image.alt = [data.mapName, activeFloor?.name, "底图"].filter(Boolean).join(" ");
		} else {
			ui.image.removeAttribute("src");
			delete ui.image.dataset.source;
		}
		ui.image.hidden = !source;
		if (!ui.tiles.hidden) {
			ui.tiles.style.width = data.width + "px";
			ui.tiles.style.height = data.height + "px";
		}
	}

	function backgroundUrl(path) {
		return retryToken ? path + (path.includes("?") ? "&" : "?") + "retry=" + retryToken : path;
	}

	function updateBackgroundNotice() {
		if (ui.root.hidden || !data) {
			return;
		}
		const visible = ui.tiles.hidden ? [] : Array.from(ui.tiles.children);
		const emptyEdge = hasLoadedTile && visible.every((image) => image.dataset.edge === "true");
		const tilesFailed = visible.length > 0 && !emptyEdge && visible.every((image) => image.dataset.failed === "true");
		const svgFailed = !ui.image.hidden && ui.image.dataset.failed === "true";
		ui.background_notice.hidden = !tilesFailed && !svgFailed;
		if (!ui.background_notice.hidden) {
			const message = tilesFailed && !svgFailed && !ui.image.hidden ? "此区域的楼层图片加载失败。" : "当前区域的底图加载失败。";
			if (ui.background_message.textContent !== message) {
				ui.background_message.textContent = message;
			}
		}
	}

	function onFloor(point) {
		return !activeFloor || !point.floorKeys?.length || point.floorKeys.includes(activeFloor.key);
	}

	function floorLabel(point) {
		if (!floors.size) {
			return "";
		}
		const names = (point.floorKeys || []).map((floorKey) => floors.get(floorKey)?.name).filter(Boolean);
		return names.length ? names.join("、") : "楼层未标注";
	}

	function samePoint(point, previous) {
		return point.group === previous.group && point.label === previous.label
			&& point.taskId === previous.taskId && point.objectiveIndex === previous.objectiveIndex
			&& point.pointIndex === previous.pointIndex && point.x === previous.x && point.y === previous.y;
	}

	function branch(key, label) {
		return { key, label, children: new Map(), keys: new Set(), count: 0 };
	}

	function childOf(parent, key, label) {
		if (!parent.children.has(key)) {
			parent.children.set(key, branch(key, label));
		}
		return parent.children.get(key);
	}

	function indexPoints() {
		groups = new Map();
		data.points = (data.points || []).filter((point) => Object.hasOwn(GROUPS, point.group)
			&& Number.isFinite(point.x) && Number.isFinite(point.y));
		for (const point of data.points) {
			const group = childOf({ children: groups }, point.group, GROUPS[point.group][0]);
			group.icon = GROUP_ICONS[point.group];
			group.count++;
			point.filterKeys = [];
			const identifiers = point.itemIds || [];
			if (point.group === "loot" && identifiers.length) {
				const categories = new Set();
				for (const itemId of new Set(identifiers)) {
					const category = data.itemCategories?.[itemId] || "其他物资";
					const section = childOf(group, category, category);
					const leaf = childOf(section, itemId, data.itemNames?.[itemId] || itemId);
					leaf.count++;
					leaf.keys.add(itemId);
					section.keys.add(itemId);
					group.keys.add(itemId);
					point.filterKeys.push(itemId);
					categories.add(section);
				}
				categories.forEach((section) => { section.count++; });
			} else {
				const label = point.group === "tasks" ? point.taskKind || "目标" : point.type || group.label;
				const leaf = childOf(group, label, label);
				leaf.icon = point.icon || group.icon;
				leaf.count++;
				leaf.keys.add(label);
				group.keys.add(label);
				point.filterKeys.push(label);
			}
			point.searchText = [point.label, point.type, point.taskName, point.taskKind, point.keyName || data.itemNames?.[point.keyId] || point.keyId, group.label, floorLabel(point)].filter(Boolean).join(" ").toLowerCase();
		}
	}

	function filterState(group) {
		if (!prefs.filters.has(group.key)) {
			prefs.filters.set(group.key, { all: GROUPS[group.key][3], exceptions: new Set() });
		}
		return prefs.filters.get(group.key);
	}

	function enabled(state, key) {
		return state.all !== state.exceptions.has(key);
	}

	function setEnabled(group, section, value) {
		const state = filterState(group);
		if (section === group) {
			state.all = value;
			state.exceptions.clear();
			if (group.key === "tasks" && value) {
				prefs.hiddenStatuses.clear();
			}
		} else {
			for (const key of section.keys) {
				if (value === state.all) {
					state.exceptions.delete(key);
				} else {
					state.exceptions.add(key);
				}
			}
		}
	}

	function updateFilters() {
		const filtered = data.points.filter((point) => {
			const state = filterState(groups.get(point.group));
			return (point.group !== "tasks" || !prefs.hiddenStatuses.has(point.type))
				&& point.filterKeys.some((key) => enabled(state, key));
		});
		hasEnabledPoints = filtered.length > 0;
		visiblePoints = activeFloor ? filtered.filter(onFloor) : filtered;
		for (const checkbox of ui.layers.querySelectorAll("input[type=checkbox]")) {
			checkbox.update();
		}
		ui.clear.textContent = hasEnabledPoints ? "隐藏全部" : "显示全部";
		const total = activeFloor ? data.points.filter(onFloor).length : data.points.length;
		ui.count.textContent = (activeFloor ? "本层已显示 " : "已显示 ") + visiblePoints.length.toLocaleString() + " / " + total.toLocaleString() + " 个点位";
		if (!selected || !visiblePoints.includes(selected)) {
			closeCard();
		}
		redraw();
	}

	function renderFilters() {
		ui.layers.replaceChildren();
		for (const key of Object.keys(GROUPS)) {
			const group = groups.get(key);
			if (group) {
				ui.layers.append(makeFilter(group, group, key));
			}
		}
		if (!groups.size) {
			ui.layers.append(node("p", "atlas_empty", "尚无可筛选的点位"));
		}
	}

	function makeFilter(group, section, path) {
		const top = group === section;
		const wrap = node("div", top ? "atlas_group" : "atlas_subgroup");
		const row = node("div", "atlas_filter_row");
		const checkbox = node("input");
		checkbox.type = "checkbox";
		checkbox.setAttribute("aria-label", section.label);
		checkbox.update = () => {
			const state = filterState(group);
			let count = 0;
			for (const key of section.keys) {
				if (enabled(state, key)) {
					count++;
				}
			}
			checkbox.checked = count > 0 && count === section.keys.size;
			checkbox.indeterminate = count > 0 && count < section.keys.size;
			if (top && group.key === "tasks" && count && prefs.hiddenStatuses.size) {
				checkbox.checked = false;
				checkbox.indeterminate = true;
			}
		};
		checkbox.update();
		checkbox.addEventListener("change", () => {
			setEnabled(group, section, checkbox.checked);
			updateFilters();
		});
		const label = node("span", "atlas_option_name", section.label);
		const count = node("span", "atlas_quantity", section.count.toLocaleString());
		if (!section.children.size) {
			const line = node("label", "atlas_leaf");
			line.append(checkbox);
			if (section.icon) {
				line.append(iconImage(section.icon, group.key));
			}
			line.append(label, count);
			return line;
		}
		const expand = node("button", "atlas_expand");
		expand.type = "button";
		if (top) {
			const symbol = iconImage(group.icon, group.key);
			symbol.style.color = GROUPS[group.key][2];
			symbol.setAttribute("aria-hidden", "true");
			expand.append(symbol);
		}
		expand.append(label, count);
		const children = node("div", "atlas_children");
		const toggle = (open) => {
			expand.setAttribute("aria-expanded", String(open));
			children.hidden = !open;
			if (open && !children.childElementCount) {
				fillChildren(group, section, path, children);
			}
		};
		expand.addEventListener("click", () => {
			const open = children.hidden;
			if (open) {
				prefs.open.add(path);
			} else {
				prefs.open.delete(path);
			}
			toggle(open);
		});
		toggle(prefs.open.has(path));
		row.append(checkbox, expand);
		wrap.append(row, children);
		return wrap;
	}

	function pagedList(parent, entries, render, offset = 0) {
		const end = Math.min(entries.length, offset + PAGE_SIZE);
		const fragment = document.createDocumentFragment();
		for (const entry of entries.slice(offset, end)) {
			fragment.append(render(entry));
		}
		if (end < entries.length) {
			const more = button("atlas_more", "查看更多（剩余 " + (entries.length - end) + "）", () => {
				more.remove();
				pagedList(parent, entries, render, end);
			});
			fragment.append(more);
		}
		parent.append(fragment);
	}

	function fillChildren(group, section, path, parent) {
		const sorted = Array.from(section.children.values()).sort((left, right) => left.label.localeCompare(right.label, "zh-CN"));
		if (group.key === "tasks" && group === section) {
			parent.append(node("div", "atlas_field_label", "任务状态"));
			const statuses = new Map([["可接", 0], ["已完成", 0], ["未解锁", 0]]);
			for (const point of data.points) {
				if (point.group === "tasks") {
					statuses.set(point.type, (statuses.get(point.type) || 0) + 1);
				}
			}
			for (const [type, count] of statuses) {
				const label = node("label", "atlas_leaf");
				const checkbox = node("input");
				checkbox.type = "checkbox";
				checkbox.update = () => { checkbox.checked = !prefs.hiddenStatuses.has(type); };
				checkbox.update();
				checkbox.addEventListener("change", () => {
					if (checkbox.checked) {
						prefs.hiddenStatuses.delete(type);
					} else {
						prefs.hiddenStatuses.add(type);
					}
					updateFilters();
				});
				checkbox.setAttribute("aria-label", type);
				label.append(checkbox, node("span", "", type), node("span", "atlas_quantity", count));
				parent.append(label);
			}
			parent.append(node("div", "atlas_field_label", "任务点位"));
		}
		if (group.key === "loot" && group === section) {
			const search = node("input", "atlas_item_search");
			search.type = "search";
			search.placeholder = "按物品名称筛选";
			search.setAttribute("aria-label", search.placeholder);
			search.value = prefs.lootQuery;
			const list = node("div");
			const show = () => {
				prefs.lootQuery = search.value;
				const query = search.value.trim().toLowerCase();
				list.replaceChildren();
				const entries = query ? sorted.flatMap((category) => {
					const leaves = category.children.size ? [...category.children.values()] : [category];
					return leaves.filter((leaf) => leaf.label.toLowerCase().includes(query));
				}) : sorted;
				pagedList(list, entries, (entry) => makeFilter(group, entry, path + "/" + entry.key));
				if (!entries.length) {
					list.append(node("p", "atlas_empty", "本图没有匹配的物资"));
				}
			};
			search.addEventListener("input", show);
			parent.append(search, list);
			show();
		} else {
			pagedList(parent, sorted, (entry) => makeFilter(group, entry, path + "/" + entry.key));
		}
	}

	function pointName(point) {
		return point.label || point.taskName || point.type || GROUPS[point.group][0];
	}

	function pointRow(point, matchedId) {
		const extra = data.itemNames?.[matchedId];
		const line = button("atlas_point_row", "", () => locate(point, matchedId));
		const icon = iconImage(point.icon || GROUP_ICONS[point.group], point.group);
		icon.style.color = GROUPS[point.group][2];
		icon.setAttribute("aria-hidden", "true");
		const content = node("span");
		content.append(node("strong", "", pointName(point)));
		const secondary = [...new Set([point.taskName, extra, GROUPS[point.group][0], point.type, floorLabel(point)])].filter((text) => text && text !== pointName(point));
		content.append(node("small", "", secondary.join(" · ")));
		line.append(icon, content);
		return line;
	}

	function showResults() {
		const query = ui.search.value.trim().toLowerCase();
		ui.results.replaceChildren();
		ui.results.hidden = !query || !data;
		if (ui.results.hidden) {
			return;
		}
		const itemMatches = new Map();
		for (const [itemId, name] of Object.entries(data.itemNames || {})) {
			if (name.toLowerCase().includes(query) || data.itemCategories?.[itemId]?.toLowerCase().includes(query)) {
				itemMatches.set(itemId, name);
			}
		}
		const matches = [];
		for (const point of data.points) {
			const matchedItem = point.itemIds?.find((itemId) => itemMatches.has(itemId));
			if (matchedItem || point.searchText.includes(query)) {
				matches.push({ point, matchedItem });
			}
		}
		ui.results.append(node("div", "atlas_field_label", "找到 " + matches.length + " 个点位"));
		pagedList(ui.results, matches, (match) => pointRow(match.point, match.matchedItem));
	}

	function locate(point, matchedId) {
		const group = groups.get(point.group);
		const state = filterState(group);
		if (matchedId && point.filterKeys.includes(matchedId)) {
			setEnabled(group, { keys: [matchedId] }, true);
		} else if (!point.filterKeys.some((key) => enabled(state, key))) {
			setEnabled(group, { keys: [point.filterKeys[0]] }, true);
		}
		if (point.group === "tasks") {
			prefs.hiddenStatuses.delete(point.type);
		}
		if (!activeFloor || !onFloor(point)) {
			const matchingFloor = point.floorKeys?.find((floorKey) => floors.has(floorKey));
			if (matchingFloor) {
				setFloor(matchingFloor);
			}
		}
		updateFilters();
		view.zoom = Math.max(view.zoom, 5);
		view.x = point.x;
		view.y = point.y;
		toggleSidebar(false);
		showPoint(point, matchedId);
		ui.card.querySelector("h3").focus({ preventScroll: true });
	}

	function card(title, category) {
		ui.card.replaceChildren();
		const head = node("div", "atlas_card_head");
		head.append(node("span", "atlas_field_label", category));
		const dismiss = button("atlas_dismiss", "×", () => closeCard(true));
		dismiss.setAttribute("aria-label", "关闭点位详情");
		head.append(dismiss);
		const heading = node("h3", "", title);
		heading.tabIndex = -1;
		ui.card.append(head, heading);
		ui.card.hidden = false;
	}

	function closeCard(focusMap = false) {
		selected = null;
		ui.card.hidden = true;
		if (focusMap) {
			ui.stage.focus();
		}
		redraw();
	}

	function showPoint(point, matchedId) {
		selected = point;
		const category = [...new Set([GROUPS[point.group][0], point.taskKind, point.type, floorLabel(point), point.optional ? "可选" : ""])].filter(Boolean).join(" · ");
		card(pointName(point), category);
		if (point.description && point.description !== pointName(point)) {
			ui.card.append(node("p", "", point.description));
		}
		const keyName = point.keyName || data.itemNames?.[point.keyId] || point.keyId;
		if (keyName) {
			ui.card.append(node("p", "", "所需钥匙 · " + keyName));
		}
		if (point.group === "loot" && point.itemIds?.length) {
			const itemIds = [...new Set(point.itemIds)];
			if (matchedId && itemIds.includes(matchedId)) {
				itemIds.splice(itemIds.indexOf(matchedId), 1);
				itemIds.unshift(matchedId);
			}
			ui.card.append(node("div", "atlas_field_label", "可能出现的物品（" + itemIds.length + "）"));
			const items = node("div", "atlas_items");
			pagedList(items, itemIds, (itemId) => node("span", "atlas_item", data.itemNames?.[itemId] || itemId));
			ui.card.append(items);
		}
		if (point.taskId) {
			if (point.taskName !== pointName(point)) {
				ui.card.append(node("p", "", point.taskName));
			}
			ui.card.append(button("atlas_task_button", "查看任务详情 →", () => {
				openTask(point.taskId);
				document.getElementById("drawer_close")?.focus();
			}));
		}
		redraw();
	}

	function showCluster(points) {
		if (points.length === 1) {
			showPoint(points[0]);
			return;
		}
		selected = null;
		card(points.length + " 个点位", "点位列表");
		const spread = points.some((point) => point.x !== points[0].x || point.y !== points[0].y);
		if (spread && view.zoom < 32) {
			ui.card.append(button("atlas_cluster_zoom", "放大此处", () => {
				view.x = points.reduce((sum, point) => sum + point.x, 0) / points.length;
				view.y = points.reduce((sum, point) => sum + point.y, 0) / points.length;
				view.zoom = Math.min(32, view.zoom * 2.5);
				closeCard(true);
			}));
		}
		const list = node("div", "atlas_point_list");
		pagedList(list, points, (point) => pointRow(point));
		ui.card.append(list);
		redraw();
	}

	function fit() {
		if (data) {
			view.x = data.width / 2;
			view.y = data.height / 2;
			view.zoom = 1;
			redraw();
		}
	}

	function scale() {
		return Math.min(ui.stage.clientWidth / data.width, ui.stage.clientHeight / data.height) * view.zoom;
	}

	function zoomBy(factor, x = ui.stage.clientWidth / 2, y = ui.stage.clientHeight / 2) {
		if (!data) {
			return;
		}
		const before = scale();
		view.zoom = Math.min(32, Math.max(0.5, view.zoom * factor));
		const delta = 1 / before - 1 / scale();
		view.x += (x - ui.stage.clientWidth / 2) * delta;
		view.y += (y - ui.stage.clientHeight / 2) * delta;
		redraw();
	}

	function redraw() {
		if (!frame && data && !ui.root.hidden) {
			frame = requestAnimationFrame(draw);
		}
	}

	function draw() {
		frame = 0;
		if (!data || ui.root.hidden || !ui.stage.clientWidth || !ui.stage.clientHeight) {
			return;
		}
		const width = ui.stage.clientWidth;
		const height = ui.stage.clientHeight;
		const ratio = scale();
		view.x = Math.max(0, Math.min(data.width, view.x));
		view.y = Math.max(0, Math.min(data.height, view.y));
		const left = width / 2 - view.x * ratio;
		const top = height / 2 - view.y * ratio;
		const transform = "translate(" + left + "px," + top + "px) scale(" + ratio + ")";
		ui.image.style.transform = transform;
		if (!ui.tiles.hidden) {
			drawTiles(left, top, ratio, width, height, transform);
		}
		ui.zoom.textContent = Math.round(view.zoom * 100) + "%";
		ui.plus.disabled = view.zoom >= 32;
		ui.minus.disabled = view.zoom <= 0.5;
		const cells = new Map();
		const cellSize = view.zoom < 4 ? 43 : 32;
		for (const point of visiblePoints) {
			const x = point.x * ratio;
			const y = point.y * ratio;
			if (x + left < -18 || x + left > width + 18 || y + top < -18 || y + top > height + 18) {
				continue;
			}
			const cell = Math.floor(x / cellSize) + "," + Math.floor(y / cellSize);
			if (!cells.has(cell)) {
				cells.set(cell, { points: [], x: 0, y: 0 });
			}
			const cluster = cells.get(cell);
			cluster.points.push(point);
			cluster.x += x;
			cluster.y += y;
		}
		const previous = new Map([...ui.markers.children].map((marker) => [marker.dataset.cell, marker]));
		for (const cluster of cells.values()) {
			const highlighted = selected && cluster.points.includes(selected);
			cluster.x = (highlighted ? selected.x * ratio : cluster.x / cluster.points.length) + left;
			cluster.y = (highlighted ? selected.y * ratio : cluster.y / cluster.points.length) + top;
		}
		const captions = [];
		clusterPoints = new Map();
		for (const [cell, cluster] of cells) {
			const points = cluster.points;
			const highlighted = selected && points.includes(selected);
			const first = highlighted ? selected : points[0];
			const group = GROUPS[first.group];
			const marker = previous.get(cell) || node("button", "atlas_marker");
			previous.delete(cell);
			clusterPoints.set(cell, points);
			marker.type = "button";
			marker.dataset.cell = cell;
			marker.style.left = cluster.x + "px";
			marker.style.top = cluster.y + "px";
			marker.style.setProperty("--marker_color", group[2]);
			marker.classList.toggle("atlas_highlight", !!highlighted);
			marker.classList.toggle("atlas_cluster", points.length > 1);
			marker.dataset.symbol = group[1];
			const label = points.length === 1 ? pointName(first) : points.length + " 个点位 · " + [...new Set(points.map((point) => GROUPS[point.group][0]))].join("、");
			marker.title = label;
			marker.setAttribute("aria-label", label);
			const icon = first.icon || GROUP_ICONS[first.group];
			const mark = [icon || group[1], points.length].join("/");
			if (marker.dataset.mark !== mark) {
				marker.dataset.mark = mark;
				marker.replaceChildren(iconImage(icon, first.group));
				if (points.length > 1) {
					marker.append(node("span", "atlas_cluster_count", String(points.length)));
				}
			}
			delete marker.dataset.caption;
			if (points.length === 1 && view.zoom >= 1 && ["extracts", "transits", "landmarks"].includes(first.group)) {
				const half = Math.min(66, label.length * 6 + 4);
				const bounds = { left: cluster.x - half, right: cluster.x + half, top: cluster.y + 14, bottom: cluster.y + 31 };
				const overlaps = captions.some((area) => area.left < bounds.right && area.right > bounds.left
					&& area.top < bounds.bottom && area.bottom > bounds.top);
				const coversMarker = [...cells.values()].some((other) => other !== cluster && other.x > bounds.left - 13
					&& other.x < bounds.right + 13 && other.y > bounds.top - 13 && other.y < bounds.bottom + 13);
				if (!overlaps && !coversMarker && bounds.left >= 0 && bounds.right <= width && bounds.bottom <= height - 26) {
					marker.dataset.caption = label;
					captions.push(bounds);
				}
			}
			if (!marker.parentNode) {
				ui.markers.append(marker);
			}
		}
		previous.forEach((marker) => marker.remove());
	}

	function drawTiles(left, top, ratio, width, height, transform) {
		ui.tiles.style.transform = transform;
		const existing = new Map([...ui.tiles.children].map((image) => [image.dataset.url, image]));
		const nearX = Math.max(0, -left / ratio);
		const nearY = Math.max(0, -top / ratio);
		const farX = Math.min(data.width, (width - left) / ratio);
		const farY = Math.min(data.height, (height - top) / ratio);
		for (const tile of activeFloor?.tiles || data.tiles || []) {
			if (tile.x + tile.width <= nearX || tile.x >= farX
				|| tile.y + tile.height <= nearY || tile.y >= farY) {
				continue;
			}
			if (!existing.has(tile.url)) {
				const image = node("img", "atlas_tile");
				image.alt = "";
				image.draggable = false;
				image.dataset.url = tile.url;
				image.dataset.edge = String(tile.x <= 0 || tile.y <= 0 || tile.x + tile.width >= data.width || tile.y + tile.height >= data.height);
				image.style.left = tile.x + "px";
				image.style.top = tile.y + "px";
				image.style.width = tile.width + "px";
				image.style.height = tile.height + "px";
				image.addEventListener("error", () => {
					if (image.parentNode === ui.tiles) {
						image.hidden = true;
						image.dataset.failed = "true";
						updateBackgroundNotice();
					}
				}, { once: true });
				image.addEventListener("load", () => {
					if (image.parentNode === ui.tiles) {
						hasLoadedTile = true;
						updateBackgroundNotice();
					}
				}, { once: true });
				ui.tiles.append(image);
				image.src = backgroundUrl(tile.url);
			}
			existing.delete(tile.url);
		}
		existing.forEach((image) => image.remove());
		updateBackgroundNotice();
	}

	function attachNavigation() {
		const stage = ui.stage;
		let drag = null;
		stage.addEventListener("pointerdown", (event) => {
			if (!data || !event.isPrimary || event.button !== 0 || event.target.closest("button")) {
				return;
			}
			drag = { x: event.clientX, y: event.clientY, id: event.pointerId };
			stage.setPointerCapture(event.pointerId);
			stage.classList.add("atlas_dragging");
			stage.focus({ preventScroll: true });
		});
		stage.addEventListener("pointermove", (event) => {
			if (drag?.id !== event.pointerId || !data) {
				return;
			}
			view.x -= (event.clientX - drag.x) / scale();
			view.y -= (event.clientY - drag.y) / scale();
			drag.x = event.clientX;
			drag.y = event.clientY;
			redraw();
		});
		stage.addEventListener("lostpointercapture", () => {
			drag = null;
			stage.classList.remove("atlas_dragging");
		});
		stage.addEventListener("wheel", (event) => {
			event.preventDefault();
			const bounds = stage.getBoundingClientRect();
			const factor = event.deltaY < 0 ? 1.2 : 1 / 1.2;
			zoomBy(factor, event.clientX - bounds.left, event.clientY - bounds.top);
		}, { passive: false });
		stage.addEventListener("dblclick", (event) => {
			if (!event.target.closest("button")) {
				const bounds = stage.getBoundingClientRect();
				zoomBy(1.8, event.clientX - bounds.left, event.clientY - bounds.top);
			}
		});
		stage.addEventListener("keydown", (event) => {
			if (!data) {
				return;
			}
			const step = 70 / scale();
			switch (event.key) {
				case "ArrowLeft": view.x -= step; break;
				case "ArrowRight": view.x += step; break;
				case "ArrowUp": view.y -= step; break;
				case "ArrowDown": view.y += step; break;
				case "+":
				case "=": zoomBy(1.45); break;
				case "-": zoomBy(1 / 1.45); break;
				case "Home": fit(); break;
				default: return;
			}
			event.preventDefault();
			redraw();
		});
	}

	Object.assign(window, { openAtlas, closeAtlas, refreshAtlas });
})();
