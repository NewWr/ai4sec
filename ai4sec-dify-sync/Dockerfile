FROM python:3.13-slim

WORKDIR /app

COPY pyproject.toml ./
COPY ai4sec_dify_sync ./ai4sec_dify_sync

RUN pip install --no-cache-dir .

CMD ["ai4sec-dify-sync", "watch"]
