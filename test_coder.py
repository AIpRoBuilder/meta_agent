from architect.data_flow_planner import DataFlowPlanner
from auditor.graph_json_auditor import GraphJsonAuditor
from auditor.node_auditor import NodeAuditor
from auditor.main_entrypoint_auditor import MainEntryPointAuditor
from worker.main_writer import PromptMainFileCoder
from worker.node_writer import PromptNodeFileCoder
from worker.context_writer import PromptContextParamCoder
from demand_analyzer.requirement_disector import RequirementDisector
from architect.graph_planner import GraphPlanner
from tools.graph_tools import graph_to_nodes

# coder.code_to_file("Write a node that find prime numbers", "generated_node.py")
api_key="sk-8b72ab4e941b46eb9631b9d5c8af5b0a"
model = "deepseek-chat"
provider="deepseek"
root_dir = "./example"



analyzer = RequirementDisector(api_key=api_key, 
                        model=model,provider=provider)
analyzer.code_to_file("Analyze the requirements to create an app for law contract audit and compare two different contracts.", 
                      "requirement_analysis.md")
print("Requirement analysis completed.")

graph_json_auditor = GraphJsonAuditor()
graph_planner = GraphPlanner(api_key=api_key, 
                        model=model,provider=provider)
graph_planner.plan_from_file("requirement_analysis.md", f"{root_dir}/graph_plan.json")
while True:
    ok, violations = graph_json_auditor.audit_graph_json(f"{root_dir}/graph_plan.json")
    if ok:
        print("Graph JSON passed the audit!")
        break
    amendment = "\n".join([f"Line {v.lineno}: {v.rule} - {v.detail}" for v in violations])
    print(f"Graph JSON failed the audit with violations:\n{amendment}")
    graph_planner.amend_file_with_feedback(f"{root_dir}/graph_plan.json", amendment, temperature=0.2)
print("Graph planning completed.")

dataflow_planner = DataFlowPlanner(api_key=api_key, model=model,provider=provider)
dataflow_planner.diagram_from_file("requirement_analysis.md", f"{root_dir}/data_flow.json", f"{root_dir}/graph_plan.json", temperature=0.0)

print("DataFlow Diagram completed.")
param_coder = PromptContextParamCoder(api_key=api_key, model=model,provider=provider)
param_coder.write_context_param_from_data_flow(f"{root_dir}/data_flow.json", 
                                               "LawParam", 
                                               f"{root_dir}/LawParam.py",
                                               graph_plan_path=f"{root_dir}/graph_plan.json", 
                                               temperature=0.0)

coder = PromptNodeFileCoder(api_key=api_key,
                        model=model,provider=provider)
print("Starting node generation and audit...")
nodes = graph_to_nodes(f"{root_dir}/graph_plan.json")
for name, info in nodes.items():
    file_path = coder.write_node_from_requirement(name,
                                                  "LawParam", 
                                                  f"{root_dir}/graph_plan.json",
                                                  "requirement_analysis.md", 
                                                  f"{root_dir}/{name}", 
                                                  language="python",temperature=0.0)
    while True:
        ok, violations = NodeAuditor().audit_node_file(file_path)
        if ok:
            print(f"{name} passed the audit!")
            break
        amendment = "\n".join([f"Line {v.lineno}: {v.rule} - {v.detail}" for v in violations])
        print(f"{name} failed the audit with violations:\n{amendment}")
        coder.amend_code_with_feedback(f"{root_dir}/{name}", amendment, language="python",temperature=0.2)
print("All nodes generated and audited successfully.")
print("Generating main entrypoint...")
main_writer = PromptMainFileCoder(api_key=api_key, 
                        model=model,provider=provider)
main_writer.write_main_entrypoint(
    pipeline_json=f"{root_dir}/graph_plan.json",
    output_path=f"{root_dir}/main_entrypoint.py",
    fastapi_host="0.0.0.0",
    temperature=0.0
)
while True:
    ok, violations = MainEntryPointAuditor().audit_main_entrypoint_file(f"{root_dir}/main_entrypoint.py")
    if ok:
        print("main_writer passed the audit!")
        break
    amendment = "\n".join([f"Line {v.lineno}: {v.rule} - {v.detail}" for v in violations])
    print(f"main_writer failed the audit with violations:\n{amendment}")
    main_writer.amend_code_with_feedback(f"{root_dir}/main_entrypoint.py", amendment, language="python",temperature=0.2)
    
    