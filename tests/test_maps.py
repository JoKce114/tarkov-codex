from app.api import build_task_map
from app.mapconfig import MapConfig
from app.maps import build_map_detail
from app.store import DataStore


def test_map_relationships_use_current_mode_data(tmp_path):
	store = DataStore(tmp_path)
	store.maps = {'map': {'normalizedName': 'customs', 'name': '海关',
		'extracts': [{'name': '旧加油站', 'faction': 'scav'}],
		'bosses': [{'mob': 'boss', 'spawnChance': 0.75}],
		'transits': [{'map': 'reserve', 'description': '前往储备站'}],
		'locks': [{'key': 'key'}, {'key': 'key'}] }, 'reserve': {'name': '储备站'}}
	store.mobs = {'boss': {'name': 'Reshala'}}
	store.items = {'key': {'name': '工厂钥匙'}}
	result = build_map_detail(store, 'map', MapConfig())
	assert result['exits'][0]['name'] == '旧加油站'
	assert result['bosses'][0]['chance'] == 75
	assert result['transits'][0]['target'] == '储备站'
	assert result['keys'] == [{'id': 'key', 'name': '工厂钥匙', 'lockCount': 2}]


def test_task_positions_can_be_read_without_a_bottom_image(tmp_path):
	store = DataStore(tmp_path)
	store.maps = {'map': {'normalizedName': 'customs', 'name': '海关'}}
	config = MapConfig()
	task = {'objectives': [{'description': '目标', 'zones': [{'map': 'map', 'position': {'x': 10, 'z': 10}}]}]}
	group, = build_task_map(task, store, config)['maps']
	assert group['mapKey'] == 'customs'
	assert group['points'][0]['label'] == '目标'
	assert 0 <= group['points'][0]['x'] <= 1
	assert 0 <= group['points'][0]['y'] <= 1
