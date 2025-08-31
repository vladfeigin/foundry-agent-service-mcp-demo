# syntax=docker/dockerfile:1
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

# Copy project metadata first for better layer caching
COPY pyproject.toml uv.lock ./

# Install exactly what's in the lockfile (no dev deps)
RUN uv sync --frozen --no-dev

# Put the venv on PATH for subsequent layers (uv run also handles this)
ENV VIRTUAL_ENV="/app/.venv"
ENV PATH="${VIRTUAL_ENV}/bin:${PATH}"

# Copy app code (adjust path if your file lives elsewhere)
COPY server/server.py ./server.py

# (Optional) drop privileges
RUN useradd --create-home --shell /bin/bash app && chown -R app:app /app
USER app

EXPOSE 4200

# Run with uv -> uvicorn (Streamable HTTP endpoint at /mcp)
#CMD ["uv", "run", "uvicorn", "server:starlette_app", "--host", "0.0.0.0", "--port", "4200"]
CMD ["sh","-c","uv run uvicorn server:starlette_app --host 0.0.0.0 --port ${PORT:-4200}"]