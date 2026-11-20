"""普通地图的中文预览图和高清原图目录。"""

ASSET_BASE = "https://assets.tarkovbox.com/images/"


def _image(title: str, preview: str, original: str) -> dict[str, str]:
	return {"title": title, "url": ASSET_BASE + preview, "previewUrl": ASSET_BASE + preview,
		"originalUrl": ASSET_BASE + original, "author": "TarkovBox"}


ATLAS = {
	"factory": (
		_image("工厂汉化地图", "maps/localized/factory-preview.jpg",
			"public-assets/4f/4ffa07d028850cc98f5e12f0ded49ccbeaa31e2bd8d94c31a5d438119e8de85c.webp"),
	),
	"customs": (
		_image("海关汉化地图", "maps/localized/customs-preview.jpg",
			"public-assets/01/01bf001c0deb99976079a96bc509bb68f87e9e296d530cfa78f001edd16a8495.webp"),
		_image("海关宿舍楼", "maps/localized/customs-dorms-preview.jpg",
			"public-assets/5d/5d8f543e65879d71637c5c17d58325574bee9222968a98a5a6c13dcf3583f829.webp"),
	),
	"woods": (
		_image("森林汉化地图", "maps/localized/woods-preview.jpg",
			"public-assets/2b/2ba5dbab31c6960ab14f79001e62c9d769343bec5fdf7d44d50feafdf499df54.webp"),
		_image("森林列车停放处", "maps/localized/woods-rail-yard-preview.jpg",
			"public-assets/64/64c1ac80e3d2e6cedcfbdef880628eb59617d3851d3d634a1a149dbc700065e5.webp"),
	),
	"lighthouse": (
		_image("灯塔汉化地图", "maps/localized/lighthouse-preview.jpg",
			"public-assets/d9/d919692ca4e31ee55832cc80cfbccdc355e2617d709369eaa75fe614d10968c0.webp"),
	),
	"shoreline": (
		_image("海岸线汉化地图", "maps/localized/shoreline-preview.jpg",
			"public-assets/2e/2e6f6c089e99a43ade6b285d64edd9382793961eb29f2023ae42b73c26c3593a.webp"),
		_image("海岸线疗养院", "maps/localized/shoreline-resort-preview.jpg",
			"public-assets/e8/e86890a636c9154781b7af9af5865a66c5a2f3c9d89814a1d53404b1bea2ae94.webp"),
	),
	"reserve": (
		_image("储备站汉化地图", "maps/localized/reserve-preview.jpg",
			"public-assets/4e/4e3f620030f6411dbba7fbd9676c3fc559988c28ce424c2ade9768a886e2552e.webp"),
	),
	"interchange": (
		_image("立交桥汉化地图", "maps/localized/interchange-preview.jpg",
			"public-assets/bc/bc66171a21278237aeee6eb4d78fe26a9ef6c856744cfa1d88f8e8962c7c748c.webp"),
	),
	"streets-of-tarkov": (
		_image("塔科夫街区汉化地图", "maps/localized/streets-preview.jpg",
			"public-assets/51/519b38d7cd27633a59793e0cbdf0b2e075f4e7994494df9d8c172f4b1e459172.webp"),
	),
	"the-lab": (
		_image("实验室 2D 地图", "maps/localized/the-lab-2d-source.webp",
			"maps/localized/the-lab-2d-source.webp"),
		_image("实验室 2.5D 地图", "maps/localized/the-lab-2-5d-source.webp",
			"maps/localized/the-lab-2-5d-source.webp"),
	),
	"ground-zero": (
		_image("中心区汉化地图", "maps/localized/ground-zero-preview.jpg",
			"public-assets/b4/b4891c474bf20335e35b3eed83cf981f26ade3c8db4ceb657cb917a57b4ea675.webp"),
	),
	"terminal": (
		_image("终点站汉化地图", "maps/localized/terminal-preview.jpg",
			"public-assets/7b/7ba50731ab5f67a4050b453577e39afdc1586a00f32e201ed3594632af34e3e4.webp"),
	),
	"the-labyrinth": (
		_image("迷宫汉化地图", "maps/localized/the-labyrinth-preview.jpg",
			"public-assets/87/87d8c78c7c41fad0ed5d175accc5e77b50b8a88c794f90f3cf879af21b39de18.webp"),
	),
	"icebreaker": (
		_image("破冰船汉化地图", "maps/localized/icebreaker-preview.jpg",
			"public-assets/a8/a8ea1049e0d477578054d3ded1a8fd6ba17f9eafe35a4c269e91523d9089ad36.webp"),
	),
}
