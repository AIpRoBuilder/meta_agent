@register_class
class MyNode(GNode):
    signature = "MyNode"

    def run(self) -> CStatus:
        print("MyNode running from factory-created instance")
        return CStatus()
    def clone(self):
        """Create a copy of this node"""
        return self

@register_class
class OtherNode(GNode):
    signature = "OtherNode"

    def run(self) -> CStatus:
        print("OtherNode running from factory-created instance")
        return CStatus()
    def clone(self):
        """Create a copy of this node"""
        return self