FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /srv

# Install dependencies first for layer caching, at the versions uv.lock pins, as CI does.
COPY pyproject.toml uv.lock ./
RUN uv export --locked --no-dev --no-emit-project --no-hashes -o /tmp/requirements.txt \
    && uv pip install --system --no-cache -r /tmp/requirements.txt

COPY app/ app/

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
