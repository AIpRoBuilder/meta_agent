from __future__ import annotations
from unittest import result

from example_agent import TableOutput
from ag_ui_workflow.types import StepRunOutput


node = TableOutput()
recommendations = [
    {
        "title": "示例标题",
        "author": "示例作者",
        "core_summary": "摘要",
        "recommendation_reason": "理由",
    }
]
session_state: dict[str, object] = {}
dependency_results = {
    "RecommendationGeneration": StepRunOutput(
        summary="ok",
        card={},
        derived={"recommendations": recommendations},
    )
}

result = node.process_chat(user_input="   ", dependency_results=dependency_results, session_state=session_state)
resp = node._request_llm(result)
print(resp) 
