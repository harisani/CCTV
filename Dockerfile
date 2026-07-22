FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    YOLO_CONFIG_DIR=/tmp

WORKDIR /service

# Default CPU wheels keep local/Apple-Silicon images compact. GPU deployments can
# override TORCH_INDEX_URL with the matching official CUDA wheel index.
ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 postgresql-client \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir \
        torch==2.5.1 torchvision==0.20.1 --index-url "${TORCH_INDEX_URL}" \
    && pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY alembic.ini ./
COPY alembic ./alembic
COPY docker/entrypoint.sh /entrypoint.sh

RUN mkdir -p /service/storage \
    && chmod +x /entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "app.app:app", "--host", "0.0.0.0", "--port", "8000"]
