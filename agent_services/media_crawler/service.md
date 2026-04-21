# MediaCrawler 本地运行指南（基础 Python 环境）
## description
一个功能强大的多平台自媒体数据采集工具，支持小红书、抖音、快手、B站、微博、贴吧、知乎等主流平台的公开信息抓取。
🔧 技术原理
核心技术：基于 Playwright 浏览器自动化框架登录保存登录态
无需JS逆向：利用保留登录态的浏览器上下文环境，通过 JS 表达式获取签名参数
优势特点：无需逆向复杂的加密算法，大幅降低技术门槛
## 1. 前置条件
请先安装以下工具：
- Python `3.10+`（建议 `3.11`）
- Node.js `>=16`
- `uv`（Python 包管理工具）
- playwright
## 2. git clone
```bash
git clone git@github.com:NanmiCoder/MediaCrawler.git
```
## 3. 安装 Python 依赖（使用 uv）
```bash
uv sync
```
## 4. 启动服务
### 1. platform
- "xhs": 小红书, "dy": 抖音, "ks": 快手, "bili": 哔哩哔哩, "wb": 微博, "tieba": 百度贴吧, "zhihu": 知乎
### 2. type
- search: 搜索模式,根据关键词搜索内容,批量获取特定主题内容
- detail: 详情模式,获取指定ID的详情,精确获取已知内容
- creator: 创作者模式,获取创作者所有内容,追踪特定博主/UP主
### 3. save_data_option
- json: 使用 JSON 存储数据
- csv: 使用 CSV 存储数据
- jsonl: 使用 JSONL 存储数据（默认格式，无需指定）
- excel: 使用 EXCEL 存储数据

```bash
uv run main.py --platform xhs --lt qrcode --type search --save_data_option json
```
## 5. 使用服务
```bash
echo ./MediaCrawler/data/*
```
## 6. 解析结果
### 1. 位置（dir-default）
- dir: ./MediaCrawler/data/*.json, 使用 JSON 存储数据
- dir: ./MediaCrawler/data/*.csv, 使用 CSV 存储数据
- dir: ./MediaCrawler/data/*.jsonl, 使用 JSONL 存储数据（默认格式，无需指定）
- dir: ./MediaCrawler/data/*.xlsx, 使用 EXCEL 存储数据
### 2. 样式（格式）
- xhs
``` jsonl
{"comment_id": "63e2b84800000000240203cf", "create_time": 1675802696000, "ip_location": null, "note_id": "63da50c00000000002003b09", "content": "视频剪辑有兴趣但不会，一加就是公开课每天都一样，然后就卖课[doge]", "user_id": "5e67cf600000000001002983", "nickname": "欧阳", "avatar": "https://sns-avatar-qc.xhscdn.com/avatar/626d6a7a1a7230b26d48c9c6.jpg?imageView2/2/w/120/format/jpg", "sub_comment_count": "1", "pictures": "", "parent_comment_id": 0, "last_modify_ts": 1776336346130, "like_count": "0"}
{"comment_id": "63de5be5000000001903f14f", "create_time": 1675516901000, "ip_location": null, "note_id": "63da50c00000000002003b09", "content": "你是好人    祝你好运", "user_id": "600c0c3f000000000101ceba", "nickname": "阿贵", "avatar": "https://sns-avatar-qc.xhscdn.com/avatar/1040g2jo30qmjb6lhgq4g5o0c1gvgbjlqovdkeog?imageView2/2/w/120/format/jpg", "sub_comment_count": "5", "pictures": "", "parent_comment_id": 0, "last_modify_ts": 1776336346130, "like_count": "13"}
```