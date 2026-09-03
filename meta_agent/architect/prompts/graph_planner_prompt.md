# Graph Planner Prompt
作为一个agent流程架构专家
目标：根据输入的《需求分析》Markdown，生成一个用于编排的 JSON 图计划，仅输出 JSON 内容。

## 输出要求
- 仅输出 JSON，不要额外说明，不要代码块围栏。
- 节点设计必须遵循工作流节点参考中的能力边界，仅可使用以下节点语义：
  - WorkflowStepNode（nodeKind=input）：需要文本类用户输入，通常对应 ext_data.type="user_input"。
  - WorkflowOperationNode（nodeKind=operation）：纯处理/计算节点，不直接向用户索取输入，通常对应 ext_data.type="none"。
  - WorkflowFileNode（nodeKind=file）：通用文件上传/存储节点，对应 ext_data.type="user_file_input"。
  - WorkflowSkillNode（nodeKind=skill）：技能封装类节点，对应 ext_data.type="skill"，且应填写 ext_data.skill_name（技能目录名）。
  - SpatialTemporalContractNode（nodeKind=spatial_temporal_contract）：将上游输出或 session_state 中的描述整理为时空关系 contract JSON，对应 ext_data.type="spatial_temporal_contract"。
  - 不得虚构上述实现基类之外的节点能力模型。
- 顶层结构必须是：
  {
    "nodes": [ ... ]
  }
- 每个节点包含字段：
  - name: 字符串，唯一、可读，且必须为英文标识符（仅英文字母和数字，建议 PascalCase）；必须体现业务语义（如 FileUpload、ImageAnalysis、ReportGeneration）。
  - type: 字符串，必须与 name 完全一致。
  - desc: 字符串，对应节点的功能描述（中文）。
  - ext_data: 必填，JSON 对象，格式为 {"type": "...", "desc": "..."}。
    - 若节点需要用户输入，type 必须为 "user_input"。
    - 若节点是通用文件上传/存储，type 使用 "user_file_input"。
    - 若节点是技能封装节点，type 使用 "skill"，并填写 skill_name（值为默认技能目录中的子目录名）。
    - 若节点要基于上游描述生成时空 contract JSON，type 使用 "spatial_temporal_contract"。
    - 映射关系："user_input" -> WorkflowStepNode；"user_file_input" -> WorkflowFileNode；"skill" -> WorkflowSkillNode；"spatial_temporal_contract" -> SpatialTemporalContractNode。
    - 其他示例 type："url"、"file"、"db"、"none"。
    - 若 type 为 "none"，desc 必须为 "no need for ext data"。
    - 示例：{"type":"user_input","desc":"user input income"}、{"type":"user_file_input","desc":"upload files for storage and downstream processing"}、{"type":"skill","skill_name":"baidu_search","desc":"search baidu for query results"}、{"type":"spatial_temporal_contract","desc":"generate spatial-temporal contract JSON from upstream description"}、{"type":"url","desc":"image generator api"}。
  - enable: 布尔值。
  - loop: 整数，默认 1；若未提及循环可省略。
    - 若某节点需要执行多次以更新节点状态，必须显式设置 loop > 1。
    - 示例：
      {
        "name": "UserInput",
        "type": "UserInput",
        "desc": "接收用户输入的目标用户画像与教学大纲文本",
        "loop": 2,
        "ext_data": {
          "type": "user_input",
          "desc": "输入目标用户画像和教学大纲文本"
        },
        "enable": true
      }
  - depends: 数组，依赖节点名称；无依赖时可省略。
  - inputs_format: 当 ext_data.type 为 "user_input" 或 "skill" 时可填写，值为对象，描述输入字段及其原始类型（string/number/boolean/object/array）。
- 节点数量以满足功能模块为主，避免过度拆分。

## 示例
{
  "nodes": [
    {
      "name": "OtherNode",
      "type": "OtherNode",
      "desc": "calculate the result of 2+2",
      "ext_data": {"type": "none", "desc": "no need for ext data"},
      "enable": true
    },
    {
      "name": "MyNode",
      "type": "MyNode",
      "desc": "calculate the result of 1+2 plus or minus the result from the previous node",
      "ext_data": {"type": "user_input", "desc": "need to get user's choice to either plus or minus the result from previous node"},
      "enable": true,
      "loop": 2,
      "depends": ["OtherNode"]
    },
    {
      "name": "NewNode",
      "type": "NewNode",
      "desc": "calculate the result of 1+1",
      "ext_data": {"type": "none", "desc": "no need for ext data"},
      "enable": true,
      "loop": 1,
      "depends": ["OtherNode", "MyNode"]
    }
  ]
}

## 生成规则
- 从需求范围与功能详细说明提取模块与功能，映射为节点。
- 依赖关系根据流程/交互顺序判断；不确定时保持独立并省略 depends。
- 节点 name/type 一律使用英文，且二者保持相同；禁止使用 MyNode、NewNode、Node1、N1、A 这类无语义占位名。
- 即使信息不完整，也要基于节点功能写出语义化名称（如 UserInputCollection、ContentSearchExecution、FinalSummaryOutput）。
- 当需求明确要求产出场景/关系/对象的时空 contract JSON 时，优先规划为 ext_data.type="spatial_temporal_contract"，而不是降级为普通 WorkflowOperationNode。
- 若有可并行的模块，避免互相依赖。
