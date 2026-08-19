# Build context is the repo root — the image needs both workspace packages
# (dnd5e-engine, dnd5e-srd-data) plus this app. Build with:
#   docker build -f apps/demo/Dockerfile -t nat20-demo .
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY packages/ packages/
COPY apps/ apps/
RUN uv sync --frozen --no-dev --all-packages
EXPOSE 8080
CMD ["uv", "run", "--no-sync", "uvicorn", "nat20_demo.app:app", "--host", "0.0.0.0", "--port", "8080"]
