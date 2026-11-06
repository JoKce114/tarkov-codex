from __future__ import annotations

from typing import NamedTuple


class Key(NamedTuple):
	name: str


class MultiKey(NamedTuple):
	names: tuple[str, ...]


class Wildcard(NamedTuple):
	pass


class ListStar(NamedTuple):
	pass


def tokenize(path: str) -> list:
	"""解析 $.data.tasks.*.objectives[*]['a','b'].effects[*] 这类路径。

	支持四种片段：普通键、* 通配、[*] 列表遍历、['a','b'] 多键。
	连续的点（..）按普通分隔处理。
	"""
	text = path.strip()
	if text.startswith("$"):
		text = text[1:]
	if text.startswith("."):
		text = text[1:]

	tokens: list = []
	buffer: list[str] = []

	def flush() -> None:
		if buffer:
			key = "".join(buffer).strip()
			if key:
				tokens.append(Wildcard() if key == "*" else Key(key))
			buffer.clear()

	index = 0
	length = len(text)
	while index < length:
		char = text[index]
		if char == ".":
			flush()
			index += 1
			continue
		if char == "[":
			flush()
			end = text.find("]", index)
			if end == -1:
				break
			inner = text[index + 1 : end].strip()
			if inner == "*":
				tokens.append(ListStar())
			else:
				names = tuple(
					part.strip().strip("'").strip('"')
					for part in inner.split(",")
					if part.strip()
				)
				if names:
					tokens.append(MultiKey(names))
			index = end + 1
			continue
		buffer.append(char)
		index += 1
	flush()
	return tokens


def apply_tokens(node, tokens: list, table: dict) -> None:
	"""宽容匹配：键遇到列表就逐项下钻，[*] 遇到字典视为不改变节点。

	tarkov.dev 的路径写法不完全符合标准 JSONPath，过于严格会漏翻大量文案。
	"""
	if node is None or not tokens:
		return
	token = tokens[0]
	rest = tokens[1:]

	if isinstance(token, Wildcard):
		values = node.values() if isinstance(node, dict) else node if isinstance(node, list) else ()
		for value in values:
			apply_tokens(value, rest, table)
		return

	if isinstance(token, ListStar):
		if isinstance(node, list):
			for position, value in enumerate(node):
				if rest:
					apply_tokens(value, rest, table)
				elif isinstance(value, str) and table.get(value):
					node[position] = table[value]
		elif isinstance(node, dict):
			apply_tokens(node, rest, table)
		return

	if isinstance(token, MultiKey):
		if isinstance(node, dict):
			for name in token.names:
				if name in node:
					apply_tokens(node[name], rest, table)
		elif isinstance(node, list):
			for value in node:
				apply_tokens(value, tokens, table)
		return

	if isinstance(node, list):
		for value in node:
			apply_tokens(value, tokens, table)
		return

	if not isinstance(node, dict) or token.name not in node:
		return

	if rest:
		apply_tokens(node[token.name], rest, table)
		return

	value = node[token.name]
	if isinstance(value, str):
		translated = table.get(value)
		if translated:
			node[token.name] = translated
	elif isinstance(value, list):
		for position, entry in enumerate(value):
			if isinstance(entry, str) and table.get(entry):
				node[position] = table[entry]


def apply_translations(payload: dict, table: dict) -> None:
	if not table:
		return
	for path in payload.get("translations") or []:
		tokens = tokenize(path)
		if tokens:
			apply_tokens(payload, tokens, table)
