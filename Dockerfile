FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    YOLO_CONFIG_DIR=/tmp

WORKDIR /service

ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 postgresql-client \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --system --gid 10001 cctv \
    && useradd --system --uid 10001 --gid cctv \
        --home-dir /service --shell /usr/sbin/nologin cctv

COPY requirements.txt ./
RUN pip install --no-cache-dir \
        torch==2.5.1 torchvision==0.20.1 --index-url "${TORCH_INDEX_URL}" \
    && pip install --no-cache-dir -r requirements.txt \
    && python -c "import torchreid; torchreid.models.build_model(name='osnet_x1_0', num_classes=1000, loss='softmax', pretrained=True)"

COPY pyproject.toml ./
COPY app ./app
COPY alembic.ini ./
COPY alembic ./alembic
COPY docker/entrypoint.sh /entrypoint.sh

RUN mkdir -p /service/storage \
    && chown -R cctv:cctv /service/storage \
    && chmod +x /entrypoint.sh

FROM base AS test

ENV POSTGRES_PASSWORD=test-only-postgres-password \
    JWT_SECRET=test-only-jwt-secret \
    API_ADMIN_PASSWORD=test-only-admin-password

RUN pip install --no-cache-dir ".[dev]"
COPY tests ./tests
COPY examples ./examples
ENTRYPOINT []
CMD ["pytest", "-q"]

FROM base AS production

USER 10001:10001

EXPOSE 8000
ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "app.app:app", "--host", "0.0.0.0", "--port", "8000"]
