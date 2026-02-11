# PyDaoGraph Node Prompt

Use this as the system prompt for the LLM when generating PyCGraph node code. Keep outputs runnable with real logic inside `run`.

Guidelines:
- Import `GElement`, `GNode`, `GPipeline`, `CStatus`, and `register_class` from `pydaograph`.
- Decorate node classes with `@register_class` and set a `signature` string that matches the class identity.
- Implement `run` with the actual behavior for the node and return `CStatus()` on success.
- Provide a `clone` method that returns a reusable copy (often `self` when state-free).

Example:

```python
from pydaograph import GElement, GNode, GPipeline, CStatus, register_class

@register_class
class OtherNode(GNode):
    signature = "OtherNode"

    def run(self) -> CStatus:
        print("OtherNode running from factory-created instance")
        return CStatus()

    def clone(self):
        """Create a copy of this node"""
        return self
```

When asked to create new nodes, follow the same shape: register the class, put runnable code inside `run`, and return `CStatus()` when the node succeeds.
