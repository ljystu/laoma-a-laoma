# 老马封禁追踪（laoma-ban-tracker）

记录 B站 UP主「马督工」（mid **316568752**，节目《睡前消息》）的停更、禁言、视频下架历史，并生成一个静态网页。

> 注意：搜索“睡前消息”排第一的 mid 4466168 是转发号（签名自称“我是个假的睡前消息”），不是主号。

## 数据来源

| 来源 | 脚本 | 说明 |
|---|---|---|
| B站投稿列表 + 账号信息 | `scripts/fetch_bilibili.py` | WBI 签名接口；经常被风控（-352 / HTTP 412），见下文 |
| YouTube「睡前消息」频道 `UCR4U_q_MojVVqYnawAVlryw`、「马前卒」@maqianzu | `scripts/fetch_youtube.py` | 用 yt-dlp，不需要 API key；精确日期逐条抓取并缓存 |
| 社区文稿库 [bedtimenews-archive-contents](https://github.com/bedtimenews/bedtimenews-archive-contents) | `scripts/fetch_archive.py` | 每期文稿（含 bvid）、`banned.md` 下架合集、目录页的禁言/停更提示 |
| Wayback Machine CDX | `scripts/fetch_archive.py` | 已下架视频页、空间页的存档链接 |

## 运行

```bash
cd laoma-ban-tracker
python3 -m venv .venv && .venv/bin/pip install yt-dlp   # 只有 YouTube 需要
python3 scripts/check.py          # 抓取 + 对比 + 重算 + 打印中文摘要
python3 scripts/serve.py          # 不缓存的本地服务，打开 http://localhost:8780/site/
```

`check.py` 做的事：

0. **先更新粉丝文稿库**（主数据源）：`git pull --ff-only`，失败就重新浅克隆；重新解析期号、标题、bvid、YouTube/西瓜链接、`banned.md` 和目录页停更提示。和上次相比改了哪些文件记进 `data/archive_changes.json`；下架合集或停更提示有增删时，生成一条 `pending` 事件（14 天内显示）。

1. 抓 B站全部投稿和账号 `silence` 字段，存原始快照到 `data/snapshots/<UTC时间>.json`
2. 和上一个**完整**快照对比：消失的 bvid 记进 `data/removals.json`（首次发现时间），silence 变化记进 `data/state.json`
3. 更新 YouTube 列表（每次最多补 100 条精确日期）和文稿库（`git pull`）
4. `scripts/analyze.py` 重算 `data/status.json`、`data/episodes.json`、`data/events.json`，网页直接读这三个文件

参数：`--skip-youtube`、`--skip-archive`。

## 判定规则

没有官方声明可依据，**只能靠前后对比**：

- `confirmed`：两份快照（本工具自己的 `data/snapshots/`，或 Wayback 存档）直接显示**视频从在线变成消失**，或 **`silence` 从 0 变 1 / 1 变 0**。证据里一定有 `before`（之前那份）和 `url`（之后那份）。
  - 下架：逐个读 Wayback 存档的视频页，`<title>` 是“【睡前消息N】…_哔哩哔哩_bilibili” 算在线，“视频去哪了呢？” 算消失。
  - 禁言：读 Wayback 存档的 `x/space/wbi/acc/info` 接口响应里的 `silence` 字段。
- `inferred`：
  - **疑似停更**：B站相邻两次投稿间隔 > 前 20 个间隔中位数的 3 倍，且 > 10 天。同期 YouTube 仍在发睡前消息 → `ban`，否则 `hiatus`。
  - **社区标注**：文稿库目录页写了“禁言 / 冷静期 / 被封 / 放假 / 暑假”的期号区间。起止日期取区间前后两期的实际发布日期。
  - **下架**：只出现在社区“下架合集”、找不到存档前后对比的。时间未知时 `start` 用原发布日期（summary 会写明）。
- `pending`：距最后一次投稿超过 3 倍中位间隔且 > 10 天，原因未知，`end=null`。
- **手工事件**：写进 `data/manual_events.json`（数组，格式同 events.json），同 id 覆盖自动事件。只有证据里带 `before` 的才算 `confirmed`。
- 社区内容只作补充证据（`kind: community`）。YouTube 的上传日期如果比后面某一期还晚（补传），就丢掉不用。

## B站风控

匿名请求 `x/space/wbi/*` 很容易被 -352 / HTTP 412 拦截。脚本只做**退避重试**和放慢翻页（每页间隔 20–40 秒），不伪造浏览器指纹。列表抓不全时不会覆盖 `data/videos.json`，也不做下架判定，避免误报。

## 云端自动运行（GitHub Actions + Vercel）

- `.github/workflows/check.yml`：每 6 小时（UTC 0/6/12/18 点 17 分）跑一次 `python scripts/check.py`，有变化就把 `data/` 提交回仓库。也可以在 GitHub 的 Actions 页面手动点 “Run workflow”。
- Vercel 连这个仓库，每次提交自动重新发布；`vercel.json` 把 `/` 跳到 `/site/`，`.vercelignore` 只发布网页需要的文件。
- 停掉：在 GitHub 仓库 Settings → Actions 里禁用，或删掉 workflow 文件。
- 注意：GitHub 的服务器在海外，B站风控更严，B站部分大概率抓不到（脚本会退避后放弃，不影响其他来源）；YouTube 也可能要求验证，补日期会慢。

本地想手动跑：`python3 scripts/check.py`。

## 文件

```
data/status.json        当前状态（站点头部）
data/episodes.json      每期状态与来源
data/events.json        封禁/停更/下架事件
data/manual_events.json 手工补充（confirmed）
data/videos.json        B站投稿（规范化）
data/youtube.json       YouTube 视频
data/archive.json       文稿库解析结果 + Wayback 链接
data/snapshots/         每次抓取的 B站原始响应
data/raw/               文稿库 clone、yt-dlp 日期缓存
site/                   index.html + app.js（无构建、无外部 CDN）
```
