from pathlib import Path

from setuptools import find_packages, setup


BASE_DIR = Path(__file__).resolve().parent
README_PATH = BASE_DIR / "README.md"


setup(
	name="meta_agent",
	version="0.1.0",
	description="A meta agent to build agents of many kinds",
	long_description=README_PATH.read_text(encoding="utf-8"),
	long_description_content_type="text/markdown",
	author="",
	python_requires=">=3.10",
	packages=find_packages(
		exclude=(
			"example",
			"example.*",
			"__pycache__",
			"__pycache__.*",
			"tests",
			"tests.*",
		)
	),
	include_package_data=True,
)
