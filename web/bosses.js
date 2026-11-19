(() => {
	"use strict";

	let request;

	function element(tag, style, text) {
		const result = document.createElement(tag);
		result.className = style;
		if (text != null) {
			result.textContent = text;
		}
		return result;
	}

	function action(label, style, callback) {
		const control = element("button", style, label);
		control.type = "button";
		control.addEventListener("click", callback);
		return control;
	}

	function portrait(boss) {
		const frame = element("div", "boss_portrait");
		frame.append(element("span", "boss_initial", boss.name.slice(0, 1)));
		if (boss.portrait) {
			const image = element("img", "");
			image.alt = "";
			image.loading = "lazy";
			image.src = "/api/bosses/" + encodeURIComponent(boss.id) + "/portrait";
			image.addEventListener("error", () => image.remove(), { once: true });
			frame.append(image);
		}
		return frame;
	}

	async function read(path, render) {
		request?.abort();
		const control = new AbortController();
		request = control;
		const mount = document.getElementById("boss_catalog");
		mount.replaceChildren(element("p", "boss_empty", "正在读取首领资料…"));
		try {
			const response = await fetch(path, { signal: control.signal });
			if (!response.ok) {
				throw new Error();
			}
			const result = await response.json();
			if (!control.signal.aborted) {
				mount.replaceChildren();
				render(mount, result);
			}
		} catch (error) {
			if (!control.signal.aborted) {
				mount.replaceChildren(element("p", "boss_empty", "首领资料读取失败。"), action("重新读取", "btn_ghost", () => read(path, render)));
			}
		}
	}

	function loadBosses() {
		return read("/api/bosses", (mount, result) => {
			if (!result.available || !result.bosses.length) {
				mount.append(element("p", "boss_empty", "当前模式暂无首领资料，请在首页同步游戏数据。"), action("返回首页", "btn_ghost", goHome));
				return;
			}
			const search = element("input", "boss_search");
			search.type = "search";
			search.placeholder = "搜索首领或地图";
			search.setAttribute("aria-label", search.placeholder);
			const grid = element("div", "boss_grid");
			const show = () => {
				grid.replaceChildren();
				const query = search.value.trim().toLowerCase();
				for (const boss of result.bosses) {
					const mapNames = boss.maps.map((map) => map.name);
					if (![boss.name, boss.slug, ...mapNames].some((name) => name.toLowerCase().includes(query))) {
						continue;
					}
					const card = action("", "boss_card", () => openBoss(boss.id));
					const copy = element("div", "boss_card_text");
					copy.append(element("strong", "", boss.name), element("small", "", boss.slug));
					if (mapNames.length) {
						copy.append(element("span", "", mapNames.join(" · ")));
					}
					card.append(portrait(boss), copy);
					grid.append(card);
				}
				if (!grid.childElementCount) {
					grid.append(element("p", "boss_empty", "没有匹配的首领。"));
				}
			};
			search.addEventListener("input", show);
			mount.append(search, grid);
			show();
		});
	}

	function itemsSection(title, items) {
		const section = element("section", "boss_section");
		section.append(element("h3", "", title + "（" + items.length + "）"));
		if (!items.length) {
			section.append(element("p", "boss_empty", "当前数据未收录。"));
			return section;
		}
		const search = element("input", "boss_search");
		search.type = "search";
		search.placeholder = "查找" + title;
		search.setAttribute("aria-label", search.placeholder);
		const list = element("div", "boss_items");
		const show = () => {
			list.replaceChildren();
			const query = search.value.trim().toLowerCase();
			const matches = items.filter((item) => item.name.toLowerCase().includes(query));
			let offset = 0;
			const next = () => {
				for (const item of matches.slice(offset, offset + 24)) {
					const control = action(item.name, "boss_item", () => openItem(item.id));
					control.disabled = !item.available;
					if (item.available) {
						const icon = element("img", "");
						icon.alt = "";
						icon.loading = "lazy";
						icon.src = "/api/icon/" + encodeURIComponent(item.id);
						control.prepend(icon);
					}
					list.append(control);
				}
				offset += 24;
				if (offset < matches.length) {
					const more = action("查看更多（剩余 " + (matches.length - offset) + "）", "btn_ghost", () => { more.remove(); next(); });
					list.append(more);
				}
			};
			next();
			if (!matches.length) {
				list.append(element("p", "boss_empty", "没有匹配的物品。"));
			}
		};
		search.addEventListener("input", show);
		section.append(search, list);
		show();
		return section;
	}

	function openBoss(id) {
		return read("/api/bosses/" + encodeURIComponent(id), (mount, boss) => {
			mount.append(action("← 首领列表", "btn_ghost", loadBosses));
			const header = element("div", "boss_header");
			const bio = element("div", "boss_intro");
			bio.append(element("h2", "", boss.name));
			for (const paragraph of [boss.bio, boss.description].filter(Boolean)) {
				bio.append(element("p", "", paragraph));
			}
			if (!boss.bio && !boss.description) {
				const areas = boss.maps.map((map) => map.name).join("、");
				bio.append(element("p", "", areas ? boss.name + " 在当前模式的出没地图包括" + areas + "。" : "当前模式尚未收录该角色的出没地图。"));
			}
			header.append(portrait(boss), bio);
			mount.append(header);
			if (Object.keys(boss.health).length) {
				const health = element("div", "boss_health");
				for (const [part, amount] of Object.entries(boss.health)) {
					health.append(element("span", "", part + " " + amount));
				}
				mount.append(health);
			}
			if (boss.maps.length) {
				const areas = element("section", "boss_section");
				areas.append(element("h3", "", "出没地图"));
				const grid = element("div", "boss_map_list");
				for (const map of boss.maps) {
					const chance = map.chances.map((value) => Number((value * 100).toFixed(1)) + "%").join(" / ");
					const label = [map.name, chance, map.pointCount ? map.pointCount + " 处点位 ↗" : "暂无定位"].filter(Boolean).join(" · ");
					const control = action(label, "boss_map", () => openAtlas(map.key, { bossId: boss.id, bossName: boss.name }));
					control.disabled = !map.pointCount;
					const location = element("div", "boss_location");
					location.append(control);
					if (map.zones?.length) {
						location.append(element("p", "", "出现区域 · " + map.zones.join("、")));
					}
					if (map.escorts?.length) {
						location.append(element("p", "", "随从 · " + map.escorts.join("、")));
					}
					grid.append(location);
				}
				areas.append(grid);
				mount.append(areas);
			}
			mount.append(itemsSection("可能携带或掉落的物品", boss.loot), itemsSection("装备及配件", boss.equipment));
		});
	}

	Object.assign(window, { loadBosses, openBoss });
})();
