from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from backend.app.services.auth import adapters


class AuthAdapterTests(unittest.TestCase):
    def test_build_account_lifecycle_uses_existing_credential_boundaries(self) -> None:
        repository = MagicMock()
        otp = MagicMock()
        lifecycle = MagicMock()

        with patch.object(
            adapters,
            "AccountLifecycle",
            return_value=lifecycle,
        ) as lifecycle_type:
            result = adapters.build_account_lifecycle(
                repository=repository,
                otp=otp,
            )

        self.assertIs(result, lifecycle)
        lifecycle_type.assert_called_once_with(
            repository=repository,
            otp=otp,
            hash_password=adapters.hash_password,
            verify_password=adapters.verify_password,
            issue_token=adapters.create_access_token,
        )


if __name__ == "__main__":
    unittest.main()
