from pathlib import Path

from setuptools import find_packages, setup


BASE_DIR = Path(__file__).resolve().parent
README_PATH = BASE_DIR / "README.md"


setup(
	name="meta_agent",
	version="0.2.0",
	description="A meta agent to build agents of many kinds",
	long_description=README_PATH.read_text(encoding="utf-8"),
	long_description_content_type="text/markdown",
	author="",
	python_requires=">=3.10",
	packages=find_packages(
		exclude=(
			"example",
			"example.*",
			"example_agent",
			"example_agent.*",
			"__pycache__",
			"__pycache__.*",
			"tests",
			"tests.*",
		)
	),
	include_package_data=True,
	package_data={
		"meta_agent": [
			"architect/prompts/*.md",
			"auditor/prompts/*.md",
			"demand_analyzer/prompts/*.md",
			"worker/prompts/*.md",
			"worker/templates/*.tmpl",
			"library/*.md",
			"library/*.html",
		],
	},
	install_requires=[
		"croniter>=2.0.0",
	],
)
