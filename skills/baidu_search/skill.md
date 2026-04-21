# Python Baidu Search API
## Description
百度搜索接口的封装，pip安装，支持命令行执行。
## Installation
```sh
python3.10 -m pip install baidusearch
```
## Using
```python
from baidusearch.baidusearch import search
results = search('Full Stack Developer')  # returns 10 or less results
[ {"title:'Name', "abstract':Link', "url": URL},
	{"title:'Name2', "abstract':Link2', "url": URL2},
	... ]
results = search('China', num_results=20)  # returns 20 or less results
```
## Examples
```python
from baidusearch.baidusearch import search
search('Python')
[{'title': 'Welcome to Python.org官网', 'abstract': "The official home of the Python Programming Language...  # Python 3: List comprehensions >>> fruits = ['Banana', 'Apple', 'Lime'] >>> loud_fruits ...", 'url': 'http://www.baidu.com/link?url=cwYxPdTt2BvutAY8dyUXTmkaWD0dkOHxqdXx4Yf12cEz4QtxP20DS2V76sM02UiV', 'rank': 1}, {'title': 'Python_百度百科', 'abstract': 'Python是一种计算机程序设计语言。是一种面向对象的动态类型语言，最初被设计用于编写自动化脚本(shell)，随着版本的不断更新和语言新功能的添加，越来越多被用于独立的、大型...   \n                \n\nPython简介及应用领域\n下载Python\n发展历程\n风格\n更多>>\n\nbaike.baidu.com/', 'url': 'http://www.baidu.com/link?url=VTtKogGlo04HC6OXufls8bARa00Sa6qqqFMiDVH8ElzbawCkliIA5GnslVHDTQldiZ6GLw6b0qWZn9CvPutoBK', 'rank': 2}, {'title': '2019年4 个关于 Python 编程语言的故事_WatchStor.com - 领先的...', 'abstract': '1天前\xa0-\xa0今天要讲 4 个关于 Python 编程语言的故事,来看看人工智能时代爆发的 Python。在这里先不告诉你 Python 是“最好的编程语言”(无论什么意思)。言归...', 'url': 'http://www.baidu.com/link?url=N6pJDdnll5vz4wePXeAFbuCCVeG80fx1-7TYR4AIc65RhvUs2xLSNz7tR3jWlDQGGN9jN9NXK3Oi6vFJjlSlWa', 'rank': 3}, {'title': 'Python教程 - 廖雪峰的官方网站', 'abstract': '2019年4月10日\xa0-\xa0研究互联网产品和技术,提供原创中文精品教程... 这是小白的Python新手教程,具有如下特点:中文,免费,零起点,完整示例,基于最新的Python 3版本。Python是一种计算机程序...', 'url': 'http://www.baidu.com/link?url=zALhNq5-wC0_-0n7D9wCOY7DbkgiDp34Vax4nDIqOdQUTDRCcjxtNyDt28PEWAVBiYq13wEh2YPXzYdHZBzCKdxjEYxZruTifOsDSxGXAnAgcDjSTrQLZa64tOVROQSh', 'rank': 4}, {'title': 'Github标星2w+,热榜第一,如何用Python实现所有算法-新闻频道-和讯网', 'abstract': '1天前\xa0-\xa0 学会了Python基础知识,想进阶一下,那就来点算法吧!毕竟编程语言只是工具,结构算法才是灵魂。  新手如何入门Python算法?  几位印度小哥在GitHub上建了...', 'url': 'http://www.baidu.com/link?url=DFhvfJkV-Mkf5kos9ZU0HXTd8TIePKRBVYFvsTuIQ4C8e8FpsvjWLf8xcZ0Y5DQFhupRKgjkir9TqqqV3EMFiq', 'rank': 5}, {'title': 'Python 简介 | 菜鸟教程', 'abstract': 'Python 简介 Python 是一个高层次的结合了解释性、编译性、互动性和面向对象的脚本语言。 Python 的设计具有很强的可读性,相比其他语言经常使用英文关键字,其他语言...', 'url': 'http://www.baidu.com/link?url=2kup-3yNhTL4TZtIGh4dij0T_by-RrpZhtQyTdLxdPBhkU1QyCftZ_u40B57kjw1pbqCVr855cIlP4COGEdPWq', 'rank': 6}, {'title': '这里有8个流行的Python可视化工具包,你喜欢哪个?_凤凰网科技', 'abstract': '1天前\xa0-\xa0喜欢用 Python 做项目的小伙伴不免会遇到这种情况:做图表时,用哪种好看又实用的可视化工具包呢?之前文章里出现过漂亮的图表时,也总有读者在后台留言...', 'url': 'http://www.baidu.com/link?url=AvonuOcAHDHMPhw-kotE-mKtfVmWpX3OfzWfkwwbM60Qw4Le5m82aP1gZ3iKhSS9', 'rank': 7}, {'title': 'Download Python | Python.org', 'abstract': 'The official home of the Python Programming Language... Looking for Python with a different OS? Python for Windows, Linux/UNIX, Mac OS X, Other ...', 'url': 'http://www.baidu.com/link?url=jvryi70Hj3_XYdUYI7n1Q1x35kUP2-ZicozQ2MIKyEBG2kLgYHRGxfFYW-bAK3-o', 'rank': 8}, {'title': 'Python_官方电脑版_华军纯净下载', 'abstract': '版本 : 3.7.3 for Windows\n 大小 : 24.25MB\n 更新 : 2019-04-17\n 环境 : WinAll\n\n立即下载', 'url': 'http://soft.onlinedown.net/soft/14542.htm', 'rank': 9}, {'title': 'Python - 开源软件 - OSCHINA', 'abstract': 'Pytype 是 Google 开源的 Python 静态类型分析器。 Pytype 可以: Lint plain Python code, flagging common mistakes s... 收藏0 评论0  Pyright - Python ...', 'url': 'http://www.baidu.com/link?url=25WmCBMCAtbxafgNDexDO2U-O4BSOaYeA8UnBKMqUos5ovD8WeM5P96Huw88tztwrsS_xA98qLkKhHRC9Ea1j_', 'rank': 10}]
```

