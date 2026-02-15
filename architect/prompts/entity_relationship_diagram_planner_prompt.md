# Entity Relationship Diagram Planner Prompt
作为一个软件架构师专家
目标：根据输入的《需求分析》Markdown，生成实体关系图（ERD）的 JSON，仅输出 JSON 内容。

## 输出要求
- 仅输出 JSON 对象，不要额外说明，不要使用代码块围栏。
- 顶层结构必须包含字段：details、entities、relationships。
- details: 数组，元素包含 detail 与 description，描述常用标记与数据类型。
- entities: 数组，元素包含 name 与 fields；fields 为字段数组，字段属性：name、keyType（PK/FK/空字符串）、dataType（如 text/integer/timestamp/serial 等）、required（布尔）。
- relationships: 数组，元素为 relationship 字符串，格式 "(FK) <from_entity>.<from_field> << (PK) <to_entity>.<to_field>"。

## 生成规则
- 基于需求分析识别核心实体（用户、文档、比对结果、任务、日志等），为每个实体列出关键字段。
- keyType 仅在主键/外键时填写 PK/FK，其他留空字符串。
- dataType 选用 text、integer、timestamp、serial、boolean、json 等常见类型，保持简洁。
- required 依据业务必填性判断，无法确定时设为 false。
- relationships 仅在存在外键或明确关联时填写，格式必须符合要求。
- 保持字段命名简洁、使用下划线；实体命名用驼峰或首字母大写单词。

## 示例
{
  "details": [
    { "detail": "PK", "description": "Primary Key" },
    { "detail": "FK", "description": "Foreign Key" },
    { "detail": "NN", "description": "Not Null" },
    { "detail": "serial", "description": "Automatic integer starting from 1" },
    { "detail": "text", "description": "String of characters" }
  ],
  "entities": [
    {
      "name": "Person",
      "fields": [
        { "name": "person_id", "keyType": "PK", "dataType": "serial", "required": true },
        { "name": "first_name", "keyType": "", "dataType": "text", "required": true },
        { "name": "last_name", "keyType": "", "dataType": "text", "required": true },
        { "name": "age", "keyType": "", "dataType": "integer", "required": true }
      ]
    },
    {
      "name": "Book",
      "fields": [
        { "name": "isbn", "keyType": "PK", "dataType": "text", "required": true },
        { "name": "book_name", "keyType": "", "dataType": "text", "required": true },
        { "name": "page_count", "keyType": "", "dataType": "integer", "required": true },
        { "name": "owner", "keyType": "FK", "dataType": "integer", "required": false }
      ]
    }
  ],
  "relationships": [
    { "relationship": "(FK) Book.owner << (PK) Person.person_id" }
  ]
}
