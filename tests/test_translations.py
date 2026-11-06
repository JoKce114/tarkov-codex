from __future__ import annotations

from app.translations import apply_translations, tokenize


def test_tokenize_simple_path() -> None:
	tokens = tokenize("$.data.items.*.name")
	assert [type(token).__name__ for token in tokens] == ["Key", "Key", "Wildcard", "Key"]
	assert tokens[0].name == "data"


def test_tokenize_multikey_and_liststar() -> None:
	tokens = tokenize("$.data.tasks.*['startRewards','finishRewards'][*].customization[*].name")
	names = [type(token).__name__ for token in tokens]
	assert names == ["Key", "Key", "Wildcard", "MultiKey", "ListStar", "Key", "ListStar", "Key"]
	assert tokens[3].names == ("startRewards", "finishRewards")


def test_tokenize_double_dot_is_separator() -> None:
	tokens = tokenize("$.data.tasks.*.objectives[*]..bodyParts[*]")
	names = [type(token).__name__ for token in tokens]
	assert names == ["Key", "Key", "Wildcard", "Key", "ListStar", "Key", "ListStar"]


def test_apply_replaces_strings() -> None:
	payload = {
		"data": {"items": {"a": {"name": "a Name", "shortName": "a Short"}}},
		"translations": ["$.data.items.*.name", "$.data.items.*.shortName"],
	}
	apply_translations(payload, {"a Name": "步枪", "a Short": "步枪"})
	assert payload["data"]["items"]["a"]["name"] == "步枪"
	assert payload["data"]["items"]["a"]["shortName"] == "步枪"


def test_apply_handles_list_star() -> None:
	payload = {
		"data": {"maps": {"m": {"enemies": ["Scav", "Boss"]}}},
		"translations": ["$.data.maps.*.enemies[*]"],
	}
	apply_translations(payload, {"Scav": "拾荒者"})
	assert payload["data"]["maps"]["m"]["enemies"] == ["拾荒者", "Boss"]


def test_apply_handles_multikey() -> None:
	payload = {
		"data": {
			"tasks": {
				"t": {
					"finishRewards": {"customization": [{"name": "skin Name"}]},
					"startRewards": {"customization": [{"name": "skin Name"}]},
				}
			}
		},
		"translations": ["$.data.tasks.*['startRewards','finishRewards'][*].customization[*].name"],
	}
	apply_translations(payload, {"skin Name": "皮肤"})
	assert payload["data"]["tasks"]["t"]["finishRewards"]["customization"][0]["name"] == "皮肤"
	assert payload["data"]["tasks"]["t"]["startRewards"]["customization"][0]["name"] == "皮肤"


def test_apply_skips_missing_paths() -> None:
	payload = {"data": {"items": {}}, "translations": ["$.data.items.*.properties.name"]}
	apply_translations(payload, {"x": "y"})
	assert payload["data"]["items"] == {}
