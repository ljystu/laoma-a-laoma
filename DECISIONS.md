# DECISIONS

- **主号 = mid 316568752「马督工」**（219 万粉、1031 投稿）。否决 4466168「睡前消息」：签名自称转发号。
- **只用标准库 + yt-dlp**。`requests` 没装，urllib 足够；yt-dlp 只在 `.venv` 里。
- **B站风控只退避、放慢，不伪造指纹**（dm_img_* 等参数）。抓不全就不覆盖 videos.json、不判下架。
- **YouTube 主数据源用 UCR4U「睡前消息」频道**，不是 @maqianzu：后者 310 条视频里只有 1 条睡前消息（其余是产经破壁机/讲点黑话/高见）。UCR4U 是否官方没能核实，所以 sources 里不标 `official`。
- **日期只取 B站 pubdate，其次 YouTube upload_date**。否决文稿库的 `dateCreated`：它是 wiki 建页时间，老期数是迁移日期。
- **confirmed 只认前后快照对比**（用户定：没有官方声明可依据）。Wayback 存的 acc/info 接口响应、视频页存档都能用来对比。社区文稿库只做补充证据。
- **下架事件起止 = 最后一次存档在线 → 第一次存档消失**；找不到存档对时 `start` 用原发布日期、`end=null`，标 inferred。今后由 check.py 记录前后快照。
- **B站列表没抓全时，期号状态一律 `unknown`**，不拿 YouTube 有就当“B站没了”。
- **YouTube 补传日期**：比后面某一期还晚的日期丢掉，否则事件起止会被拉到错误的年份。
- **小宇宙播客不做抓取器**：是粉丝补档版，页面显示 0 集。蜻蜓FM/头条/抖音/X 没做（时间有限，且多数需登录或强反爬）。
- **站点自己做了一版**，读协调方给的 schema（status/episodes/events）；周统计在前端算，不生成派生文件。
