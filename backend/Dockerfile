FROM python:3.9-slim

# Unbuffered output so worker logs reach `docker compose logs` immediately.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Dependencies are copied on their own so the layer is cached across code
# changes. psycopg-binary ships wheels, so no build toolchain is needed.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

CMD ["python", "-m", "app.worker"]
