import os

from meta_agent.agent_builder import AgentBuilder
from pathlib import Path


requirement_text = Path("./requirement.txt").read_text(encoding="utf-8")
builder = AgentBuilder(api_key="sk-7b750ecf940b45be82019e430be390b0",
		provider="deepseek",
		model="deepseek-v4-pro",
		root_dir="./example_agent", frontend_style_prompt="style: suitable for social media like renote, tiktok, facebook operation platform, clean and easy to use. Use markdown format for outputs when applicable."
	)

builder.run_full_pipeline(requirement_text=requirement_text,
                          test_after_generation=True
	)

