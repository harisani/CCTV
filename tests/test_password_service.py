import unittest

from app.services.password_service import PasswordService


class PasswordServiceTest(unittest.TestCase):
    def test_hashes_and_verifies_password_without_storing_plaintext(self) -> None:
        service = PasswordService()
        encoded = service.hash("a-strong-password-123")

        self.assertNotIn("a-strong-password-123", encoded)
        self.assertTrue(service.verify("a-strong-password-123", encoded))
        self.assertFalse(service.verify("wrong-password", encoded))

    def test_rejects_short_password(self) -> None:
        with self.assertRaises(ValueError):
            PasswordService().hash("short")


if __name__ == "__main__":
    unittest.main()
