import json
import unittest

from pydaograph import CStatus, GNode, GPipeline, register_class

from meta_agent.tools import get_pipeline_id, set_pipeline_id


@register_class
class CapturePipelineIdNode(GNode):
    captured_pipeline_id = None

    def clone(self):
        return self

    def run(self) -> CStatus:
        type(self).captured_pipeline_id = get_pipeline_id(self)
        print(f"Captured pipeline ID: {type(self).captured_pipeline_id}")
        return CStatus()


class TestGraphToolsPipelineId(unittest.TestCase):
    def test_pipeline_id_is_visible_inside_node(self) -> None:
        CapturePipelineIdNode.captured_pipeline_id = None
        pipeline = GPipeline()

        status = set_pipeline_id(pipeline, "run-123")
        self.assertFalse(status.isErr(), status.getInfo())
        self.assertEqual(get_pipeline_id(pipeline), "run-123")

        build_status = pipeline.buildFromJsonStr(
            json.dumps(
                {
                    "nodes": [
                        {
                            "name": "CapturePipelineIdNode",
                            "type": "CapturePipelineIdNode",
                            "depends": [],
                        }
                    ]
                }
            )
        )
        self.assertFalse(build_status.isErr(), build_status.getInfo())

        try:
            process_status = pipeline.process()
            self.assertFalse(process_status.isErr(), process_status.getInfo())
            self.assertEqual(CapturePipelineIdNode.captured_pipeline_id, "run-123")
        finally:
            pipeline.destroy()


if __name__ == "__main__":
    unittest.main()