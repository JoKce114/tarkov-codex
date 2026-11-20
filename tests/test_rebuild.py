import json
from threading import Event

from requests import Response

from app.api import create_app
from app.progress import ProgressStore
from app.sync import SyncManager


def payload(mode, dataset):
	if dataset.endswith('_zh'):
		return {'data': {'unused': '译文'}}
	if dataset == 'items':
		return {'data': {'items': {'item': {'id': 'item', 'name': mode}}}}
	if dataset == 'tasks':
		return {'data': {
			'tasks': {'task': {'id': 'task', 'name': mode, 'finishRewards': {'achievement': ['award']}}},
			'achievements': {'award': {'id': 'award', 'name': '成就奖励'}},
		}}
	if dataset == 'maps':
		return {'data': {'maps': {'map': {'id': 'map', 'name': mode, 'normalizedName': 'customs'}}}}
	if dataset in ('barters', 'crafts'):
		return {'data': [{'id': 'recipe'}]}
	return {'data': {'row': {'id': 'row', 'name': mode}}}


def upstream(url):
	mode, dataset = url.split('/')[-2:]
	response = Response()
	response.status_code = 200
	response._content = json.dumps(payload(mode, dataset)).encode()
	return response


def test_app_can_be_created_before_server_event_loop(tmp_path):
	app = create_app(SyncManager(tmp_path), ProgressStore(tmp_path / 'progress.json'), auto_update=False)
	assert app.title == '塔科夫百科'


def test_invalid_response_cannot_publish_partial_generation(tmp_path, monkeypatch):
	manager = SyncManager(tmp_path)

	def bad_response(url, *_):
		response = upstream(url)
		if url.endswith('/regular/tasks'):
			response._content = b'<html>upstream failure</html>'
		return response

	monkeypatch.setattr(manager, '_request', bad_response)
	result = manager.sync_all()
	assert not result['ok']
	assert (result['errors'][0]['mode'], result['errors'][0]['key']) == ('regular', 'tasks')
	assert not manager.current.items
	assert not (tmp_path / 'current.json').exists()


def test_rebuilt_task_detail_retains_achievement_reward(tmp_path, monkeypatch):
	manager = SyncManager(tmp_path)
	monkeypatch.setattr(manager, '_request', upstream)
	assert manager.sync_all()['ok']
	detail = manager.current.task_detail('task', set(), 1)
	assert detail['finishRewards']['achievement'] == ['成就奖励']


def test_queries_and_mode_switch_work_while_rebuilding(tmp_path, monkeypatch):
	manager = SyncManager(tmp_path)
	monkeypatch.setattr(manager, '_request', lambda url, *_: upstream(url))
	assert manager.sync_all()['ok']
	old = manager.current
	started = Event()
	resume = Event()

	def slow_response(url, *_):
		started.set()
		assert resume.wait(10)
		return upstream(url)

	monkeypatch.setattr(manager, '_request', slow_response)
	assert manager.start_background()
	try:
		assert started.wait(5)
		assert not manager.start_background()
		assert manager.current.item_detail('item')['name'] == 'pve'
		assert manager.current.task_detail('task', set(), 1)['name'] == 'pve'
		assert manager.set_mode('regular').item_detail('item')['name'] == 'regular'
	finally:
		resume.set()
		manager._worker.join(10)
	assert manager.status()['lastResult']['ok']
	assert manager.current is not old
	assert manager.current.mode == 'regular'
	assert SyncManager(tmp_path, mode='pvp-season').current.items['item']['name'] == 'pvp-season'
