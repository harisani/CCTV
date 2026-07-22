#!/usr/bin/env bash
set -u

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "FFmpeg belum terpasang. Jalankan: brew install ffmpeg" >&2
  exit 1
fi

echo "Daftar perangkat video macOS:"
ffmpeg -hide_banner -f avfoundation -list_devices true -i "" 2>&1 || true
