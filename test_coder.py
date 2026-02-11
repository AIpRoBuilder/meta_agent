from auditor.node_auditor import CodeAuditor
from worker.node_writer import PromptNodeFileCoder
from demand_analyzer.requirement_disector import RequirementDisector
from architect.graph_planner import GraphPlanner
from tools.graph_tools import graph_to_nodes

# coder.code_to_file("Write a node that find prime numbers", "generated_node.py")


# analyzer = RequirementDisector(api_key="sk-8b72ab4e941b46eb9631b9d5c8af5b0a", 
#                         model="deepseek-chat",provider="deepseek")
# analyzer.code_to_file("Analyze the requirements to create an app for law contract audit and compare two different contracts.", "requirement_analysis.md")

# graph_planner = GraphPlanner(api_key="sk-8b72ab4e941b46eb9631b9d5c8af5b0a", 
#                         model="deepseek-chat",provider="deepseek")
# graph_planner.plan_from_file("requirement_analysis.md", "graph_plan.json")

nodes = graph_to_nodes("graph_plan.json")
coder = PromptNodeFileCoder(api_key="sk-8b72ab4e941b46eb9631b9d5c8af5b0a", 
                        model="deepseek-chat",provider="deepseek")
for name, info in nodes.items():
    file_path = coder.write_node_from_requirement(name, info, "requirement_analysis.md", f"generated_{name}", language="python",temperature=0.0)
    while True:
        ok, violations = CodeAuditor().audit_node_file(file_path)
        if ok:
            print(f"{name} passed the audit!")
            break
        amendment = "\n".join([f"Line {v.lineno}: {v.rule} - {v.detail}" for v in violations])
        print(f"{name} failed the audit with violations:\n{amendment}")
        coder.amend_code_with_feedback(f"generated_{name}", amendment, language="python",temperature=0.0)