"""Sending one Web Push message (REQ-019, TASK-034): VAPID (RFC 8292) and aes128gcm content encryption
(RFC 8291, RFC 8188), on `cryptography` and the standard library only.

The push service (Google, Mozilla, Apple) only relays an encrypted blob to the browser: it never sees the
alert's text. `send` answers with the push service's status so the caller can drop a subscription the
service says is gone (404, 410).
"""

import base64
import json
import os
import struct
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

RECORD_SIZE = 4096
TIMEOUT_SECONDS = 10


def b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def _hkdf(salt: bytes, ikm: bytes, info: bytes, length: int) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=salt, info=info).derive(ikm)


def _public_bytes(key: ec.EllipticCurvePublicKey) -> bytes:
    return key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


def encrypt(
    plaintext: bytes,
    p256dh: str,
    auth: str,
    *,
    sender_key: ec.EllipticCurvePrivateKey | None = None,
    salt: bytes | None = None,
) -> bytes:
    """The request body for one message to the browser keys `p256dh` and `auth` (RFC 8291 section 3).
    `sender_key` and `salt` are fresh for every message; tests pass them to check the RFC's example."""
    receiver = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), b64url_decode(p256dh))
    sender_key = sender_key or ec.generate_private_key(ec.SECP256R1())
    salt = salt or os.urandom(16)
    sender_public = _public_bytes(sender_key.public_key())
    shared = sender_key.exchange(ec.ECDH(), receiver)
    ikm = _hkdf(
        b64url_decode(auth), shared, b"WebPush: info\x00" + _public_bytes(receiver) + sender_public, 32
    )
    key = _hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = _hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
    if len(plaintext) + 17 > RECORD_SIZE:
        raise ValueError("A push message must fit in one record")
    record = AESGCM(key).encrypt(nonce, plaintext + b"\x02", None)  # 0x02: the last (and only) record
    header = salt + struct.pack("!IB", RECORD_SIZE, len(sender_public)) + sender_public
    return header + record


def vapid_authorization(
    endpoint: str, private_key_b64: str, subject: str, *, now: float | None = None
) -> str:
    """The Authorization header proving the message comes from this server (RFC 8292): a JWT signed with
    the VAPID private key, for the push service's origin, valid for 12 hours."""
    parts = urlsplit(endpoint)
    claims = {"aud": f"{parts.scheme}://{parts.netloc}", "exp": int((now or time.time()) + 12 * 3600)}
    claims["sub"] = subject
    signing_input = (
        b64url_encode(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode())
        + "."
        + b64url_encode(json.dumps(claims, separators=(",", ":")).encode())
    )
    key = private_key(private_key_b64)
    r, s = decode_dss_signature(key.sign(signing_input.encode(), ec.ECDSA(hashes.SHA256())))
    token = signing_input + "." + b64url_encode(r.to_bytes(32, "big") + s.to_bytes(32, "big"))
    public = b64url_encode(_public_bytes(key.public_key()))
    return f"vapid t={token}, k={public}"


def private_key(value: str) -> ec.EllipticCurvePrivateKey:
    """The VAPID private key from its base64url raw form (32 bytes) or a PEM block."""
    if "BEGIN" in value:
        key = serialization.load_pem_private_key(value.encode(), password=None)
        if not isinstance(key, ec.EllipticCurvePrivateKey):
            raise ValueError("The VAPID key must be an EC P-256 key")
        return key
    return ec.derive_private_key(int.from_bytes(b64url_decode(value), "big"), ec.SECP256R1())


def public_key_for(private_key_b64: str) -> str:
    """The applicationServerKey browsers subscribe with, derived from the private key."""
    return b64url_encode(_public_bytes(private_key(private_key_b64).public_key()))


def new_keys() -> tuple[str, str]:
    """A fresh VAPID key pair as (private, public), both base64url."""
    key = ec.generate_private_key(ec.SECP256R1())
    raw = key.private_numbers().private_value.to_bytes(32, "big")
    return b64url_encode(raw), b64url_encode(_public_bytes(key.public_key()))


@dataclass
class Result:
    status: int  # 0 when the push service could not be reached

    @property
    def gone(self) -> bool:
        """The push service no longer knows this subscription: the browser unsubscribed or it expired."""
        return self.status in (404, 410)

    @property
    def delivered(self) -> bool:
        return 200 <= self.status < 300


def send(
    endpoint: str,
    p256dh: str,
    auth: str,
    payload: dict,
    *,
    private_key_b64: str,
    subject: str,
    ttl: int = 3600,
    topic: str = "",
) -> Result:
    """Send one message. `topic` lets the push service replace an undelivered message with a newer one on
    the same subject (RFC 8030 section 5.4)."""
    body = encrypt(json.dumps(payload, separators=(",", ":")).encode(), p256dh, auth)
    headers = {
        "Authorization": vapid_authorization(endpoint, private_key_b64, subject),
        "Content-Encoding": "aes128gcm",
        "Content-Type": "application/octet-stream",
        "TTL": str(ttl),
        "Urgency": "high",
    }
    if topic:
        headers["Topic"] = topic
    request = urllib.request.Request(endpoint, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310
            return Result(response.status)
    except urllib.error.HTTPError as error:
        return Result(error.code)
    except (urllib.error.URLError, TimeoutError, OSError):
        return Result(0)
