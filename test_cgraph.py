from pydaograph import GPipeline, GElement
from meta_agent.architect.graph import Graph
import example.main_entrypoint
import json
import importlib
import sys
from pathlib import Path
from typing import Optional

def import_nodes_from_root(nodes_root: Path, explicit_modules: Optional[list] = None) -> None:
    """Walk the provided directory and import every Python module inside it.
    
    :param nodes_root: root directory containing node modules (packages or .py files)
    :param explicit_modules: optional list of specific module names to import
    """
    # Ensure the directory is on sys.path so plain imports work
    root_str = str(nodes_root.resolve())
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
    
    if explicit_modules:
        # Import only specified modules
        for mod_name in explicit_modules:
            try:
                importlib.import_module(mod_name)
                print(f"Imported explicit module: {mod_name}")
            except Exception as e:
                print(f"Warning: failed to import explicit module {mod_name}: {e}")
        return
    
    # Auto-scan for all Python modules
    for pyfile in nodes_root.rglob("*.py"):
        # Skip dunder modules
        if pyfile.name.startswith("__"):
            continue
        
        rel = pyfile.relative_to(nodes_root)
        mod_name = ".".join(rel.with_suffix("").parts)
        try:
            importlib.import_module(mod_name)
            print(f"Imported node module: {mod_name}")
        except Exception as e:
            # Don't crash the loader; just warn
            print(f"Warning: failed to import node module {mod_name}: {e}")

def main():
    import_nodes_from_root(Path("/Users/xiechuxi/Desktop/codes/meta_agent/example"))
    graph = Graph(str("./example/graph_plan.json"))
    print(GElement.registeredClasses())
    node = GElement.create("HomePageInput")
    node.run()
    for node_name, subgraph in graph.get_all_subgraph().items():
        print(node_name)
        pipeline = GPipeline()
        pipeline.buildFromJsonStr(json.dumps(subgraph))
        pipeline.process()
        pipeline.destroy()
    
    
    # a = pipeline.buildFromJson("/Users/xiechuxi/Desktop/codes/meta_agent/example.json")
    # print("Pipeline built from JSON:", a.getInfo())


if __name__ == "__main__":
    main()