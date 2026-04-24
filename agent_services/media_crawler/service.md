# MediaCrawler 本地运行指南（基础 Python 环境）
## description
一个功能强大的多平台自媒体数据采集工具，支持小红书、抖音、快手、B站、微博、贴吧、知乎等主流平台的公开信息抓取。
🔧 技术原理
核心技术：基于 Playwright 浏览器自动化框架登录保存登录态
无需JS逆向：利用保留登录态的浏览器上下文环境，通过 JS 表达式获取签名参数
优势特点：无需逆向复杂的加密算法，大幅降低技术门槛
## 1. Installation
请先安装以下工具：
- Python `3.10+`（建议 `3.11`）
- Node.js `>=16`
- `uv`（Python 包管理工具）
- playwright
```bash
cd {root_dir}
git clone git@github.com:NanmiCoder/MediaCrawler.git
cd {root_dir}/MediaCrawler && uv sync
```
## 2. Start Service
### 2.1 platform
- "xhs": 小红书, "dy": 抖音, "ks": 快手, "bili": 哔哩哔哩, "wb": 微博, "tieba": 百度贴吧, "zhihu": 知乎
### 2.2 type
- search: 搜索模式,根据关键词搜索内容,批量获取特定主题内容
- detail: 详情模式,获取指定ID的详情,精确获取已知内容
- creator: 创作者模式,获取创作者所有内容,追踪特定博主/UP主
### 2.3 save_data_option
- json: 使用 JSON 存储数据
- csv: 使用 CSV 存储数据
- jsonl: 使用 JSONL 存储数据（默认格式，无需指定）
- excel: 使用 EXCEL 存储数据
### 2.4 command
```bash
cd {root_dir}/MediaCrawler
uv run main.py --platform xhs --lt qrcode --type search --keywords "学习" --save_data_option json
```
## 3. Using
### 3.1 Code
```python
import json
from pathlib import Path

# Load JSONL file (one JSON object per line)
def load_jsonl(filepath: str) -> list[dict]:
    records = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records

# Load JSON file (array of objects)
def load_json(filepath: str) -> list[dict]:
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)

# Example: parse xhs comment records
def parse_xhs_comments(records: list[dict]):
    result = []
    for item in records:
        comment_id = item["comment_id"]
        note_id = item["note_id"]
        nickname = item["nickname"]
        content = item["content"]
        ip_location = item.get("ip_location", "")
        like_count = item.get("like_count", "0")
        sub_comment_count = item.get("sub_comment_count", "0")
        create_time = item["create_time"]  # unix ms timestamp
        result.append({'nickname':nickname,'content':content,'like_count':like_count,'sub_comment_count':sub_comment_count,'create_time':create_time})
    return result
        

# Usage
records = load_json("{root_dir}/MediaCrawler/data/xhs/json/comments.json")
parse_xhs_comments(records)
```
### 3.2 Parse Result & Examples
#### 3.2.1 位置（dir-default）
- dir: {root_dir}/MediaCrawler/data/json/*.json, 使用 JSON 存储数据
- dir: {root_dir}/MediaCrawler/data/csv/*.csv, 使用 CSV 存储数据
- dir: {root_dir}/MediaCrawler/data/*.jsonl, 使用 JSONL 存储数据（默认格式，无需指定）
- dir: {root_dir}/MediaCrawler/data/excel/*.xlsx, 使用 EXCEL 存储数据
#### 3.2.2 样式（格式）
- xhs
``` jsonl
{"comment_id": "63e2b84800000000240203cf", "create_time": 1675802696000, "ip_location": null, "note_id": "63da50c00000000002003b09", "content": "视频剪辑有兴趣但不会，一加就是公开课每天都一样，然后就卖课[doge]", "user_id": "5e67cf600000000001002983", "nickname": "欧阳", "avatar": "https://sns-avatar-qc.xhscdn.com/avatar/626d6a7a1a7230b26d48c9c6.jpg?imageView2/2/w/120/format/jpg", "sub_comment_count": "1", "pictures": "", "parent_comment_id": 0, "last_modify_ts": 1776336346130, "like_count": "0"}
{"comment_id": "63de5be5000000001903f14f", "create_time": 1675516901000, "ip_location": null, "note_id": "63da50c00000000002003b09", "content": "你是好人    祝你好运", "user_id": "600c0c3f000000000101ceba", "nickname": "阿贵", "avatar": "https://sns-avatar-qc.xhscdn.com/avatar/1040g2jo30qmjb6lhgq4g5o0c1gvgbjlqovdkeog?imageView2/2/w/120/format/jpg", "sub_comment_count": "5", "pictures": "", "parent_comment_id": 0, "last_modify_ts": 1776336346130, "like_count": "13"}
```