"""Async encryption helpers for secrets stored by FOGG.

The local backend uses AES-256-GCM with a key supplied through the environment.
The Google backend uses Cloud KMS directly and never retrieves key material.
"""

from __future__ import annotations

import base64
import binascii
import json
import secrets
from threading import Lock
from typing import Any, Literal

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from utils.settings import get_settings

KMSBackend = Literal["local", "google"]
_ENVELOPE_PREFIX = "foggkms:v1:"
_MAX_PLAINTEXT_BYTES = 8 * 1024
_NONCE_BYTES = 12

_google_client: Any | None = None
_google_client_lock = Lock()


class KMSConfigurationError(RuntimeError):
    """KMS encryption is misconfigured for the selected environment."""


class KMSCiphertextError(ValueError):
    """Ciphertext is malformed or was created by another configured backend."""


class KMSDecryptionError(ValueError):
    """Ciphertext authentication failed, including a mismatched AAD context."""


class KMSOperationError(RuntimeError):
    """The configured KMS backend could not complete a cryptographic operation."""


def _get_backend() -> KMSBackend:
    settings = get_settings()
    backend = settings.kms_backend
    if settings.fogg_env == "prod" and backend == "local":
        raise KMSConfigurationError("Local KMS encryption cannot be used when FOGG_ENV=prod")
    return backend


def _additional_authenticated_data(
    uid: str,
    group: str,
    additional_context: dict[str, str] | None,
) -> bytes:
    if not uid or not uid.strip():
        raise ValueError("uid must be a non-empty string")
    if not group or not group.strip():
        raise ValueError("group must be a non-empty string")

    context = additional_context or {}
    if any(
        not isinstance(key, str) or not isinstance(value, str) for key, value in context.items()
    ):
        raise TypeError("additional_context must contain only string keys and values")
    if {"uid", "group"}.intersection(context):
        raise ValueError("additional_context cannot override reserved 'uid' or 'group' fields")

    return json.dumps(
        {
            "domain": "fogg.secret.v1",
            "uid": uid,
            "group": group,
            "additional_context": context,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _local_key() -> bytes:
    encoded_key = get_settings().kms_local_encryption_key.strip()
    if not encoded_key:
        raise KMSConfigurationError(
            "KMS_LOCAL_ENCRYPTION_KEY is required when KMS_BACKEND=local; "
            "generate it with 'openssl rand -base64 32'"
        )
    try:
        key = base64.b64decode(encoded_key, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise KMSConfigurationError("KMS_LOCAL_ENCRYPTION_KEY must be valid base64") from exc
    if len(key) != 32:
        raise KMSConfigurationError("KMS_LOCAL_ENCRYPTION_KEY must decode to exactly 32 bytes")
    return key


def _get_google_client() -> Any:
    global _google_client
    with _google_client_lock:
        if _google_client is None:
            try:
                from google.cloud import kms_v1
            except Exception as exc:
                raise KMSConfigurationError("Google Cloud KMS SDK is unavailable") from exc
            _google_client = kms_v1.KeyManagementServiceAsyncClient()
        return _google_client


def _google_key_name() -> str:
    key_name = get_settings().kms_key_name.strip()
    if not key_name:
        raise KMSConfigurationError("KMS_KEY_NAME is required when KMS_BACKEND=google")
    return key_name


def _pack_envelope(backend: KMSBackend, ciphertext: bytes, **metadata: str) -> str:
    envelope: dict[str, str | int] = {
        "version": 1,
        "backend": backend,
        "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
    }
    envelope.update(metadata)
    serialized = json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return _ENVELOPE_PREFIX + base64.urlsafe_b64encode(serialized).decode("ascii")


def _unpack_envelope(value: str) -> dict[str, Any]:
    if not value.startswith(_ENVELOPE_PREFIX):
        raise KMSCiphertextError("Unsupported encrypted secret format")
    try:
        serialized = base64.urlsafe_b64decode(value[len(_ENVELOPE_PREFIX) :])
        envelope = json.loads(serialized)
        if (
            not isinstance(envelope, dict)
            or envelope.get("version") != 1
            or envelope.get("backend") not in {"local", "google"}
            or not isinstance(envelope.get("ciphertext"), str)
        ):
            raise ValueError("invalid envelope fields")
        envelope["ciphertext_bytes"] = base64.b64decode(envelope["ciphertext"], validate=True)
        return envelope
    except (ValueError, TypeError, KeyError, binascii.Error, json.JSONDecodeError) as exc:
        raise KMSCiphertextError("Encrypted secret envelope is malformed") from exc


async def encrypt_secret(
    plaintext: str,
    uid: str,
    group: str,
    additional_context: dict[str, str] | None = None,
) -> str:
    """Encrypt a secret and bind it to its owner/group/context using AAD.

    ``uid`` should identify the secret's actual owner (for example, a workspace
    ID for a workspace-shared credential), and ``group`` should be a stable
    purpose/provider label. Neither value nor ``additional_context`` is secret.
    """
    plaintext_bytes = plaintext.encode("utf-8")
    aad = _additional_authenticated_data(uid, group, additional_context)
    if len(plaintext_bytes) + len(aad) > _MAX_PLAINTEXT_BYTES:
        raise ValueError("plaintext plus authenticated context must not exceed 8 KiB")

    backend = _get_backend()
    if backend == "local":
        nonce = secrets.token_bytes(_NONCE_BYTES)
        ciphertext = AESGCM(_local_key()).encrypt(nonce, plaintext_bytes, aad)
        return _pack_envelope(
            backend,
            ciphertext,
            nonce=base64.b64encode(nonce).decode("ascii"),
        )

    key_name = _google_key_name()
    try:
        response = await _get_google_client().encrypt(
            request={
                "name": key_name,
                "plaintext": plaintext_bytes,
                "additional_authenticated_data": aad,
            }
        )
    except Exception as exc:
        raise KMSOperationError("Google Cloud KMS encryption failed") from exc
    return _pack_envelope(backend, response.ciphertext, key_name=key_name)


async def decrypt_secret(
    ciphertext: str,
    uid: str,
    group: str,
    additional_context: dict[str, str] | None = None,
) -> str:
    """Decrypt a secret only when the supplied owner/group/context match."""
    aad = _additional_authenticated_data(uid, group, additional_context)
    envelope = _unpack_envelope(ciphertext)
    backend = _get_backend()
    if envelope["backend"] != backend:
        raise KMSCiphertextError(
            "Encrypted secret backend differs from KMS_BACKEND; migrate ciphertext before switching"
        )

    if backend == "local":
        try:
            nonce = base64.b64decode(envelope["nonce"], validate=True)
            plaintext = AESGCM(_local_key()).decrypt(
                nonce,
                envelope["ciphertext_bytes"],
                aad,
            )
        except InvalidTag as exc:
            raise KMSDecryptionError(
                "Encrypted secret or authenticated context is invalid"
            ) from exc
        except (ValueError, TypeError, KeyError, binascii.Error) as exc:
            raise KMSCiphertextError("Local encrypted secret envelope is malformed") from exc
    else:
        key_name = envelope.get("key_name")
        if not isinstance(key_name, str) or not key_name:
            raise KMSCiphertextError("Google encrypted secret is missing its KMS key name")
        try:
            response = await _get_google_client().decrypt(
                request={
                    "name": key_name,
                    "ciphertext": envelope["ciphertext_bytes"],
                    "additional_authenticated_data": aad,
                }
            )
            plaintext = response.plaintext
        except Exception as exc:
            raise KMSOperationError("Google Cloud KMS decryption failed") from exc

    try:
        return plaintext.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise KMSDecryptionError("Decrypted secret is not valid UTF-8") from exc


async def close_kms_client() -> None:
    """Close the shared Google KMS client during application shutdown."""
    global _google_client
    with _google_client_lock:
        client, _google_client = _google_client, None
    if client is not None:
        await client.close()
