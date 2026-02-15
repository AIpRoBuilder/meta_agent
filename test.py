from architect.entity_relationship_diagram_planner import ERDiagramPlanner
from architect.data_flow_planner import DataFlowPlanner
from worker.context_writer import PromptContextParamCoder


# erd_planner = ERDiagramPlanner(
#     api_key="sk-8b72ab4e941b46eb9631b9d5c8af5b0a", 
#                         model="deepseek-chat",provider="deepseek"
# )
# erd_planner.diagram_from_file("requirement_analysis.md", "er_diagram.json")

dataflow_planner = DataFlowPlanner(
    api_key="sk-8b72ab4e941b46eb9631b9d5c8af5b0a", 
                        model="deepseek-chat",provider="deepseek"
)

dataflow_planner.diagram_from_file("requirement_analysis.md", "data_flow.json",temperature=0.0)

param_coder = PromptContextParamCoder(api_key="sk-8b72ab4e941b46eb9631b9d5c8af5b0a", 
                        model="deepseek-chat",provider="deepseek")
param_coder.write_context_param_from_data_flow("data_flow.json", "LawParam", "law_param.py",graph_plan_path="graph_plan.json", temperature=0.0)