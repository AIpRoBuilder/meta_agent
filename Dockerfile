FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

COPY LICENSE MANIFEST.in README.md pyproject.toml setup.py ./
COPY meta_agent ./meta_agent

RUN python -m pip install --upgrade pip \
    && python -m pip install .

ENTRYPOINT ["python"]
CMD ["-c", "import meta_agent; print(meta_agent.__version__)"]