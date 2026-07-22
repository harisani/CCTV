#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "Skrip ini hanya untuk macOS." >&2
  exit 1
fi
if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "FFmpeg belum terpasang. Jalankan: brew install ffmpeg" >&2
  exit 1
fi

WEBCAM_DEVICE_INDEX="${WEBCAM_DEVICE_INDEX:-0}"
WEBCAM_FPS="${WEBCAM_FPS:-30}"
WEBCAM_WIDTH="${WEBCAM_WIDTH:-1280}"
WEBCAM_HEIGHT="${WEBCAM_HEIGHT:-720}"
WEBCAM_BITRATE="${WEBCAM_BITRATE:-2M}"
WEBCAM_RTSP_PUBLISH_URL="${WEBCAM_RTSP_PUBLISH_URL:-rtsp://127.0.0.1:8554/macbook-webcam}"

echo "Menyiarkan webcam MacBook ke ${WEBCAM_RTSP_PUBLISH_URL}"
echo "Tekan Ctrl+C untuk menghentikan kamera virtual."

exec ffmpeg \
  -hide_banner \
  -f avfoundation \
  -framerate "${WEBCAM_FPS}" \
  -video_size "${WEBCAM_WIDTH}x${WEBCAM_HEIGHT}" \
  -i "${WEBCAM_DEVICE_INDEX}:none" \
  -an \
  -c:v h264_videotoolbox \
  -b:v "${WEBCAM_BITRATE}" \
  -g "$((WEBCAM_FPS * 2))" \
  -bf 0 \
  -pix_fmt yuv420p \
  -f rtsp \
  -rtsp_transport tcp \
  "${WEBCAM_RTSP_PUBLISH_URL}"
