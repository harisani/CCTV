"""Download pinned OpenCV Zoo models and verify their SHA-256 digests."""

from __future__ import annotations

import argparse
import hashlib
import os
import urllib.request
from pathlib import Path


def download(url: str, checksum: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    digest = hashlib.sha256()
    try:
        with urllib.request.urlopen(url, timeout=120) as response:
            with temporary.open("wb") as output:
                for chunk in iter(lambda: response.read(1024 * 1024), b""):
                    output.write(chunk)
                    digest.update(chunk)
                output.flush()
                os.fsync(output.fileno())
        if digest.hexdigest() != checksum:
            raise RuntimeError(
                f"Checksum mismatch for {destination.name}: "
                f"{digest.hexdigest()}"
            )
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    parser.add_argument("--yunet-url", required=True)
    parser.add_argument("--yunet-sha256", required=True)
    parser.add_argument("--sface-url", required=True)
    parser.add_argument("--sface-sha256", required=True)
    args = parser.parse_args()
    download(
        args.yunet_url,
        args.yunet_sha256,
        args.destination / "face_detection_yunet_2023mar.onnx",
    )
    download(
        args.sface_url,
        args.sface_sha256,
        args.destination / "face_recognition_sface_2021dec.onnx",
    )


if __name__ == "__main__":
    main()
