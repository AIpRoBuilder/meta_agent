# Graph Planner Prompt
作为一个软件架构师专家
目标：根据输入的《需求分析》Markdown，生成一个用于编排的 JSON 图计划，仅输出 JSON 内容。

## 输出要求
- 仅输出 JSON，不要额外说明，不要代码块围栏。
- 顶层结构必须是：
  {
    "nodes": [ ... ]
  }
- 每个节点包含字段：
  - name: 字符串，唯一、可读。
  - type: 字符串，对应节点类型（如 "MyNode"）。
  - desc: 字符串，对应节点的功能描述（中文）。
  - enable: 布尔值。
  - loop: 整数，默认 1；若未提及循环可省略。
  - depends: 数组，依赖节点名称；无依赖时可省略。
- 节点数量以满足功能模块为主，避免过度拆分。

## 示例
{
  "nodes": [
    {
      "name": "OtherNode",
      "type": "OtherNode",
      "desc": "calculate the result of 2+2",
      "enable": true
    },
    {
      "name": "MyNode",
      "type": "MyNode",
      "desc": "calculate the result of 1+2",
      "enable": true,
      "loop": 2,
      "depends": ["OtherNode"]
    },
    {
      "name": "NewNode",
      "type": "NewNode",
      "desc": "calculate the result of 1+1",
      "enable": true,
      "loop": 1,
      "depends": ["OtherNode", "MyNode"]
    }
  ]
}

## 生成规则
- 从需求范围与功能详细说明提取模块与功能，映射为节点。
- 依赖关系根据流程/交互顺序判断；不确定时保持独立并省略 depends。
- 类型名优先用模块英文/拼音转驼峰；无法确定时使用 "MyNode"。
- 若有可并行的模块，避免互相依赖。
