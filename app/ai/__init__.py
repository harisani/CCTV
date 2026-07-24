"""Computer-vision components used by asynchronous AI jobs."""

from app.ai.biometric_service import (
    BiometricModelUnavailable,
    FaceCandidateObservation,
    OpenCVBiometricService,
)

__all__ = [
    "BiometricModelUnavailable",
    "FaceCandidateObservation",
    "OpenCVBiometricService",
]
