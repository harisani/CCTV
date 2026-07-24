FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/service \
    TORCH_HOME=/service/.cache/torch \
    XDG_CACHE_HOME=/service/.cache \
    MPLCONFIGDIR=/tmp/matplotlib \
    YOLO_CONFIG_DIR=/tmp

WORKDIR /service

ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu
ARG YUNET_MODEL_URL=https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx
ARG YUNET_MODEL_SHA256=8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4
ARG SFACE_MODEL_URL=https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx
ARG SFACE_MODEL_SHA256=0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 postgresql-client \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --system --gid 10001 cctv \
    && useradd --system --uid 10001 --gid cctv \
        --home-dir /service --shell /usr/sbin/nologin cctv

COPY requirements.txt ./
COPY docker/download_biometric_models.py /tmp/download_biometric_models.py
RUN mkdir -p /service/.cache/torch /service/storage \
    && pip install --no-cache-dir \
        torch==2.5.1 torchvision==0.20.1 --index-url "${TORCH_INDEX_URL}" \
    && pip install --no-cache-dir -r requirements.txt \
    && python -c "import torchreid; torchreid.models.build_model(name='osnet_x1_0', num_classes=1000, loss='softmax', pretrained=True)" \
    && python -c "from ultralytics import YOLO; YOLO('yolo11n.pt')" \
    && python /tmp/download_biometric_models.py /service/models \
        --yunet-url "${YUNET_MODEL_URL}" \
        --yunet-sha256 "${YUNET_MODEL_SHA256}" \
        --sface-url "${SFACE_MODEL_URL}" \
        --sface-sha256 "${SFACE_MODEL_SHA256}" \
    && rm /tmp/download_biometric_models.py

COPY pyproject.toml ./
COPY app ./app
COPY alembic.ini ./
COPY alembic ./alembic
COPY docker/entrypoint.sh /entrypoint.sh

RUN mkdir -p /tmp/matplotlib \
    && chown -R cctv:cctv /service/.cache /service/storage /service/models /tmp/matplotlib \
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
