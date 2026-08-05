from __future__ import annotations

import base64
import secrets
from dataclasses import dataclass
from typing import ClassVar

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class WeChatSecretBoxError(Exception):
    """Encryption/decryption failed or key material is invalid."""


@dataclass(frozen=True, slots=True)
class WeChatSecretBox:
    """AES-GCM secret box for WeChat session material at rest.

    - The encryption key is never persisted by this module.
    - Key version metadata is returned alongside ciphertext so callers can
      store it next to the encrypted value.
    - Keys are decoded from URL-safe Base64 and must be 32 bytes (AES-256).
    - Rotation is supported by creating a new box with a new key version; the
      previous box remains available for decryption.
    """

    key_version: str
    _aesgcm: AESGCM
    KEY_SIZE: ClassVar[int] = 32
    NONCE_SIZE: ClassVar[int] = 12

    def __post_init__(self) -> None:
        if not self.key_version or len(self.key_version) > 64:
            raise WeChatSecretBoxError("key_version must be 1..64 characters")

    @classmethod
    def from_urlsafe_base64(cls, key_material: str, key_version: str) -> "WeChatSecretBox":
        """Build a secret box from URL-safe Base64-encoded 32-byte key material."""
        if not key_material:
            raise WeChatSecretBoxError("encryption key is required")
        try:
            key = base64.urlsafe_b64decode(key_material)
        except Exception as exc:
            raise WeChatSecretBoxError("encryption key is not valid base64") from exc
        if len(key) != cls.KEY_SIZE:
            raise WeChatSecretBoxError(
                f"encryption key must be {cls.KEY_SIZE} bytes, got {len(key)}"
            )
        return cls(key_version=key_version, _aesgcm=AESGCM(key))

    @classmethod
    def generate_key_material(cls) -> str:
        """Generate a fresh URL-safe Base64-encoded 32-byte key.

        Intended for bootstrapping deployment secrets and tests only; do not
        call at runtime from production request handlers.
        """
        return base64.urlsafe_b64encode(secrets.token_bytes(cls.KEY_SIZE)).decode("ascii")

    @classmethod
    def generate_for_test(cls, key_version: str = "v1") -> "WeChatSecretBox":
        """Build a fresh secret box for unit tests."""
        return cls.from_urlsafe_base64(cls.generate_key_material(), key_version)

    def encrypt(self, plaintext: str) -> tuple[str, str]:
        """Return (ciphertext_urlsafe_b64, nonce_urlsafe_b64) for *plaintext*."""
        try:
            nonce = secrets.token_bytes(self.NONCE_SIZE)
            ciphertext = self._aesgcm.encrypt(
                nonce,
                plaintext.encode("utf-8"),
                None,
            )
            return (
                base64.urlsafe_b64encode(ciphertext).decode("ascii"),
                base64.urlsafe_b64encode(nonce).decode("ascii"),
            )
        except Exception as exc:
            raise WeChatSecretBoxError("failed to encrypt secret") from exc

    def decrypt(self, ciphertext_b64: str, nonce_b64: str) -> str:
        """Decrypt *ciphertext_b64* authenticated with *nonce_b64*."""
        try:
            ciphertext = base64.urlsafe_b64decode(ciphertext_b64)
            nonce = base64.urlsafe_b64decode(nonce_b64)
            plaintext = self._aesgcm.decrypt(nonce, ciphertext, None)
            return plaintext.decode("utf-8")
        except InvalidTag as exc:
            raise WeChatSecretBoxError("decryption authentication failed") from exc
        except Exception as exc:
            raise WeChatSecretBoxError("failed to decrypt secret") from exc

    def seal(self, plaintext: str) -> dict[str, str]:
        """Return a serializable sealed-value envelope."""
        ciphertext, nonce = self.encrypt(plaintext)
        return {
            "v": self.key_version,
            "ct": ciphertext,
            "nonce": nonce,
        }

    def unseal(self, envelope: dict[str, str]) -> str:
        """Decrypt an envelope produced by :meth:`seal`."""
        if envelope.get("v") != self.key_version:
            raise WeChatSecretBoxError("envelope key version does not match")
        return self.decrypt(envelope["ct"], envelope["nonce"])
