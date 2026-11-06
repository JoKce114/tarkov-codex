# 塔科夫百科

逃离塔科夫的本地资料查询工具。桌面程序，离线可用，数据自动同步。

## 功能

- **物品图鉴**：5498 件物品的价格、属性、兑换配方、制作配方
- **商人任务**：全部任务的目标、前置条件、奖励、地图点位、图文攻略
- **地图**：13 张地图的高清汉化图，含撤离点、BOSS、钥匙
- **商人**：11 个商人的忠诚等级、在售物品、发布任务
- **兑换配方 / 藏身处制作 / 藏身处升级**：全部配方与建造材料
- **激活码**：当前有效的兑换码

支持 PVE / PVP / SEASON 三种游戏模式的数据切换，任务进度本地保存。

## 运行

需要 Python 3.10+（仅开发时需要，打包版不需要）。

```bash
pip install -r requirements.txt
python -m app.main
```

首次启动会自动从 [tarkov.dev](https://tarkov.dev) 下载数据，约 1-2 分钟。
之后可完全离线使用，需要更新时点界面上的同步按钮。

## 打包

```bash
python scripts/build_seed.py        # 生成出厂数据
python scripts/build_extra_seed.py  # 加入地图、攻略、激活码
python build/build.py               # 打包到 dist/
```

## 数据来源

| 内容 | 来源 |
|---|---|
| 物品、任务、商人、配方 | [tarkov.dev](https://tarkov.dev) 公开接口 |
| 地图与标记点 | [TarkovBox](https://www.tarkovbox.com) |
| 任务攻略 | [TarkovBox](https://www.tarkovbox.com) / [OPtarkov](https://www.optarkov.com) |
| 地图绘制 | [RE3MR](https://re3mr.com) |

数据版权归各来源所有。本仓库**只包含程序代码**，不包含任何游戏素材或第三方内容；
数据由使用者在本地自行下载。

## 目录结构

```
app/            后端：数据加载、同步、接口
web/            前端：界面与交互
scripts/        数据抓取与打包辅助脚本
tests/          单元测试
build/          打包脚本
```

运行时会生成 `data/`（数据缓存）和 `logs/`（日志），均不纳入版本控制。
