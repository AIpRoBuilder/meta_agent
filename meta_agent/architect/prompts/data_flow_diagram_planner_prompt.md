# Data Flow Diagram Planner Prompt
作为一个软件架构师专家
目标：根据输入的《需求分析》Markdown，生成数据流图（DFD）的 JSON，仅输出 JSON 内容。

## 输出要求
- 仅输出 JSON 对象，不要额外说明，不要使用代码块围栏。
- 顶层结构必须包含字段：class、description、nodeDataArray、linkDataArray。
- class：以系统/产品名称的短横线或下划线形式命名。
- description：字符串，一句话描述系统作用（中文）。
- nodeDataArray：数组，元素字段包括
  - id：整数，保持唯一。建议分段：1-99 实体，100-199 处理过程，200-299 数据上下文/数据流。
  - type：字符串，限定为 entity/process/context 三类。
  - name：字符串，简洁可读。
  - desc：可选，补充说明（中文）。
- linkDataArray：数组，元素字段包括
  - from：整数，指向节点 id（通常为 entity 或 process）。
  - edge：整数，指向节点 id（通常为 context，表示数据流）。
  - to：整数，指向节点 id（通常为 process 或 entity）。

## 生成规则
- 基于需求分析提取核心实体（用户、文件、比对任务、结果、报告等）、处理过程（上传、解析、比对、条款分析、报告生成等）和数据上下文（原始文件、解析文本、差异结果、报告摘要等）。
- 确保每个处理过程节点至少有输入与输出的数据流（context）。
- 数据流 edge id 应对应 nodeDataArray 中的 context 节点，以便可追溯输入输出。
- 优先使用简洁命名；当角色存在上下游关系时，通过 linkDataArray 体现流向。
- 保持结构紧凑，避免过度拆分，覆盖需求范围的关键步骤即可。

## 示例
{
  "class": "product_procurement_system",
  "description": "product procurement system.",
  "nodeDataArray": [
    {
      "id": 1,
      "type": "entity",
      "name": "ProductStorageManager"
    },
    {
      "id": 2,
      "type": "entity",
      "name": "Procurers"
    },
    {
      "id": 3,
      "type": "entity",
      "name": "TotalStorageList"
    },
    {
      "id": 4,
      "type": "entity",
      "name": "TotalOrderInfos"
    },
    {
      "id": 101,
      "type": "process",
      "name": "Receive Product Needs"
    },
    {
      "id": 102,
      "type": "process",
      "name": "Update StorageList"
    },
    {
      "id": 103,
      "type": "process",
      "name": "Process Orders"
    },
    {
      "id": 104,
      "type": "process",
      "name": "Produce Order Summary"
    },
    {
      "id": 201,
      "type": "context",
      "name": "ProductNeeds"
    },
    {
      "id": 202,
      "type": "context",
      "name": "StorageList"
    },
    {
      "id": 203,
      "type": "context",
      "name": "StorageInfos"
    },
    {
      "id": 204,
      "type": "context",
      "name": "OrderInfos"
    },
    {
      "id": 205,
      "type": "context",
      "name": "OrderSummary"
    }
  ],
  "linkDataArray": [
    {
      "from": 1,
      "edge": 201,
      "to": 101
    },
    {
      "from": 101,
      "edge": 201,
      "to": 102
    },
    {
      "from": 102,
      "edge": 202,
      "to": 3
    },
    {
      "from": 3,
      "edge": 202,
      "to": 102
    },
    {
      "from": 102,
      "edge": 203,
      "to": 103
    },
    {
      "from": 103,
      "edge": 204,
      "to": 4
    },
    {
      "from": 4,
      "edge": 204,
      "to": 104
    },
    {
      "from": 104,
      "edge": 205,
      "to": 2
    }
  ]
}
