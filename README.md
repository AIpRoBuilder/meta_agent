# meta_agent

meta_agent is a Python library for generating AG-UI workflow projects, including backend workflow nodes, FastAPI entrypoints, and workflow planning artifacts.

## Requirements

- Python 3.10 or newer
- Git available on your machine
- A supported LLM provider API key

Core installation includes the default OpenAI-compatible client path. If you want to use the Zhipu provider, install the optional `zhipu` extra.

`ag-ui-workflow` and `pydaograph` are installed from GitHub during setup, so `git` must be available for `pip`, `uv`, `poetry`, and Docker builds.

## Install With pip

Install the library from the repository root:

```bash
python3 -m pip install .
```

For editable local development:

```bash
python3 -m pip install -e .
```

Install with the optional Zhipu provider extra:

```bash
python3 -m pip install '.[zhipu]'
```

If your tooling expects a `requirements.txt` file, this repository also supports:

```bash
python3 -m pip install -r requirements.txt
```

## Install With uv

Install the library from the repository root:

```bash
uv pip install .
```

For editable local development:

```bash
uv pip install -e .
```

Install with the optional Zhipu provider extra:

```bash
uv pip install '.[zhipu]'
```

The compatibility `requirements.txt` also works with uv:

```bash
uv pip install -r requirements.txt
```

## Install With Poetry

Install dependencies and the package in the current environment:

```bash
poetry install
```

Install with the optional Zhipu provider extra:

```bash
poetry install -E zhipu
```

## Docker Install

Build the image:

```bash
docker build -t meta-agent .
```

Verify the package is installed in the container:

```bash
docker run --rm meta-agent
```

Run your own Python command against the installed library:

```bash
docker run --rm meta-agent -c "import meta_agent; print(meta_agent.__version__)"
```

Run a local script from your current workspace:

```bash
docker run --rm -v "$(pwd)":/workspace -w /workspace meta-agent your_script.py
```

## Quick Start

```python
from meta_agent.agent_builder import AgentBuilder

builder = AgentBuilder(
	api_key="your-api-key",
	provider="deepseek",
	model="deepseek-chat",
	root_dir="./example",
)
```

## License

This project is licensed under the Apache License 2.0. See `LICENSE` for details.