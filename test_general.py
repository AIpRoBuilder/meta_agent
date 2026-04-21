from __future__ import annotations

from typing import Any

from meta_agent.ag_ui_workflow.nodes import WorkflowActionNode
from meta_agent.ag_ui_workflow.types import StepRunOutput


class MediaCrawlerSearchServiceNode(WorkflowActionNode):
    STEP_ID = "MediaCrawlerSearchServiceNode"
    TITLE = "Start MediaCrawler XHS Search Service"
    PROMPT = "Start MediaCrawler using the local-run guide command flow."
    DEPENDENCIES: list[str] = []

    DEFAULT_WORKDIR = "/Users/xiechuxi/Desktop/codes/meta_agent/MediaCrawler"
    DEFAULT_REPO_URL = "git@github.com:NanmiCoder/MediaCrawler.git"
    DEFAULT_PLATFORM = "xhs"
    DEFAULT_LOGIN_TYPE = "qrcode"
    DEFAULT_CRAWLER_TYPE = "search"
    DEFAULT_IMAGE = "opensandbox/playwright:latest"

    def build_instance_spec(
        self,
        dependency_results: dict[str, StepRunOutput],
        session_state: dict[str, Any],
    ) -> dict[str, Any]:
        workdir = str(session_state.get("mediaCrawlerDir") or self.DEFAULT_WORKDIR)
        repo_url = str(session_state.get("mediaCrawlerRepo") or self.DEFAULT_REPO_URL)
        platform = str(session_state.get("mediaCrawlerPlatform") or self.DEFAULT_PLATFORM)
        login_type = str(session_state.get("mediaCrawlerLoginType") or self.DEFAULT_LOGIN_TYPE)
        crawler_type = str(session_state.get("mediaCrawlerType") or self.DEFAULT_CRAWLER_TYPE)

        default_command = (
              # Clone repo if not present, install deps, and run main
              f"sh -lc \""
              f"if [ ! -d '{workdir}' ]; then git clone {repo_url} {workdir}; fi && "
              f"cd {workdir} && "
              f"uv sync && "
              f"uv run playwright install && "
              f"uv run main.py --platform {platform} --lt {login_type} --type {crawler_type}"
              "\""
        )

        probe_command = (
            "sh -lc \""
            f"pgrep -f 'main.py --platform {platform} --lt {login_type} --type {crawler_type}' >/dev/null "
            "&& echo service_started"
            "\""
        )

        return {
            "mode": "local",
            "localMode": "service",
            "stdout": "/Users/xiechuxi/Desktop/codes/meta_agent/service_stdout.log",
            "image": session_state.get("sandboxImage") or self.DEFAULT_IMAGE,
            "domain": session_state.get("sandboxDomain"),
            "command": session_state.get("instanceCommand") or default_command,
            "probeCommand": session_state.get("instanceProbeCommand") or probe_command,
            "probeDelaySeconds": session_state.get("instanceProbeDelaySeconds") or 20,
            "sandboxTimeoutSeconds": session_state.get("sandboxTimeoutSeconds") or 1800,
            "requestTimeoutSeconds": session_state.get("sandboxRequestTimeoutSeconds") or 180,
            "killOnExit": session_state.get("sandboxKillOnExit", True),
        }



def run_example() -> None:
	node = MediaCrawlerSearchServiceNode()
	session_state: dict[str, Any] = {
		# Optional overrides:
		# "sandboxDomain": "localhost:8100",
		# "mediaCrawlerDir": "/workspace/MediaCrawler",
		# "servicePort": 8080,
		# "sandboxImage": "ghcr.io/astral-sh/uv:python3.11-bookworm",
	}

	spec = node.build_instance_spec({}, session_state)
	result = node.run_in_sandbox(spec=spec, session_state=session_state)

	print("ok:", result.get("ok"))
	print("exitCode:", result.get("exitCode"))
	print("stdout (service probe):\n", result.get("stdout", ""))
	print("stderr:\n", result.get("stderr", ""))


if __name__ == "__main__":
	run_example()

