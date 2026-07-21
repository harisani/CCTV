"""Password hashing based on Python's memory-hard scrypt implementation."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os


class PasswordService:
    """Hash and verify passwords without storing reversible credentials."""

    algorithm = "scrypt"
    n = 2**14
    r = 8
    p = 1
    key_length = 64

    def hash(self, password: str, *, enforce_policy: bool = True) -> str:
        if enforce_policy:
            self.validate(password)
        salt = os.urandom(16)
        digest = hashlib.scrypt(
            password.encode("utf-8"), salt=salt, n=self.n, r=self.r, p=self.p, dklen=self.key_length
        )
        return "$".join(
            (
                self.algorithm,
                str(self.n),
                str(self.r),
                str(self.p),
                base64.urlsafe_b64encode(salt).decode("ascii"),
                base64.urlsafe_b64encode(digest).decode("ascii"),
            )
        )

    def verify(self, password: str, encoded: str) -> bool:
        try:
            algorithm, n, r, p, salt, expected = encoded.split("$", 5)
            if algorithm != self.algorithm:
                return False
            actual = hashlib.scrypt(
                password.encode("utf-8"),
                salt=base64.urlsafe_b64decode(salt),
                n=int(n),
                r=int(r),
                p=int(p),
                dklen=len(base64.urlsafe_b64decode(expected)),
            )
            return hmac.compare_digest(actual, base64.urlsafe_b64decode(expected))
        except (ValueError, TypeError):
            return False

    @staticmethod
    def validate(password: str) -> None:
        if len(password) < 12:
            raise ValueError("Password must contain at least 12 characters")
        if len(password) > 256:
            raise ValueError("Password is too long")
