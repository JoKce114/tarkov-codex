# 塔科夫百科

逃离塔科夫的本地资料查询工具。游戏资料来自 Tarkov.dev，下载后可离线查询。

## 功能

- **物品图鉴**：物品的价格、属性、兑换配方和制作配方
- **商人任务**：任务目标、前置条件、奖励、地图点位和 Wiki 链接
- **地图**：按游戏模式显示撤离点、BOSS、转移点和钥匙
- **商人**：商人的忠诚等级、在售物品、发布任务
- **兑换配方 / 藏身处制作 / 藏身处升级**：全部配方与建造材料

支持 PVE / PVP / SEASON 三种游戏模式的数据切换，任务进度本地保存。

## 运行

需要 Python 3.10+（仅开发时需要，打包版不需要）。

```bash
pip install -r requirements.txt
python -m app.main
```

打包版自带出厂资料。开发环境没有资料时，点击首页「重建全部资料」下载三种模式的数据。
重建在后台进行，已有资料仍可查询。新资料校验通过后一次启用。
普通地图默认显示 TarkovBox 中文标注图，点击预览可查看高清原图。首次查看需要联网，已缓存的图片可离线打开。

## 打包

```bash
python scripts/build_seed.py        # 从 Tarkov.dev 全量生成出厂资料
python build/build.py               # 打包到 dist/
python scripts/release.py           # 生成 release/ 下的更新包和 latest.json
```

## 发布更新

1. 改 `app/paths.py` 里的 `APP_VERSION`
2. 依次执行上面的打包命令
3. 在发布仓库 `tarkov-codex-releases` 新建 Release，tag 用 `v<版本>`
4. 上传 `release/` 下的 zip 和 `latest.json`

程序启动后每 24 小时查一次版本：先读 Release 的 `latest.json` 静态附件（不占用
GitHub API 配额），确认有新版本才调一次接口取更新说明。被限流时会把恢复时间记在
本地，期间不再发请求。

国内网络直连不上 `github.com`，在「设置 → 自动更新 → 代理地址」里填写本机代理端口
（如 `http://127.0.0.1:7897`）即可检查和下载更新。代理只接受 http/https 地址。

## 数据来源

| 内容 | 来源 |
|---|---|
| 物品、任务、地图、商人、配方 | [json.tarkov.dev](https://json.tarkov.dev) |
| 普通地图中文标注图 | [TarkovBox](https://www.tarkovbox.com/maps/download) |
| 图标与任务地图底图 | [assets.tarkov.dev](https://assets.tarkov.dev) |

生成的缓存和出厂资料不纳入版本控制。

## 目录结构

```
app/            后端：数据加载、同步、接口
web/            前端：界面与交互
scripts/        数据抓取与打包辅助脚本
tests/          单元测试
build/          打包脚本
```

运行时会生成 `data/`（数据缓存）和 `logs/`（日志），均不纳入版本控制。
