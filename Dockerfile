FROM python:3.13-slim

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:0.12.4 /uv /uvx /bin/

# Copy project files
COPY pyproject.toml .
COPY medicall/ medicall/

# Install dependencies
RUN uv pip install --system -e .

EXPOSE 8000
CMD ["uvicorn", "medicall.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
