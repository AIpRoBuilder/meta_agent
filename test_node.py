from auditor.node_auditor import CodeAuditor


coder = PromptNodeFileCoder(api_key="sk-8b72ab4e941b46eb9631b9d5c8af5b0a", 
                        model="deepseek-chat",provider="deepseek")
for name, info in nodes.items():
    coder.write_node_from_requirement(name, info, "requirement_analysis.md", f"generated_{name}", language="python",temperature=0.0)
    while True:
        ok, violations = CodeAuditor().audit_node_file("./generated_CreateTask.py")
        print("pass" if ok else violations)