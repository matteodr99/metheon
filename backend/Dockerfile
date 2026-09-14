# One image for the backend. It starts the API by default; the worker runs
# from the same image with a different command, since the two share every
# line of code and every dependency. Two Dockerfiles would be one more thing
# to keep in step.
FROM python:3.9-slim

# Unbuffered output so logs reach `docker compose logs` immediately.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Nothing here needs root. A process that is compromised through the API
# should not find itself root inside the container.
RUN useradd --create-home --uid 1000 --shell /usr/sbin/nologin app

WORKDIR /app

# Dependencies are copied on their own so the layer is cached across code
# changes. psycopg-binary ships wheels, so no build toolchain is needed.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=app:app app ./app

USER app

# Documentation only; publishing the port is the orchestrator's call.
EXPOSE 8000

# No HEALTHCHECK on purpose: the worker shares this image and serves no
# HTTP, and probes belong to whatever runs the container. The endpoints are
# /api/health/live and /api/health.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
