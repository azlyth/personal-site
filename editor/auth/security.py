"""Security primitives: token hashing + random ids. Pure, no I/O.

Mirrors spruce's app/core/security.py exactly -- same shape, same reasoning
(32-byte urlsafe tokens; only the sha256 hash is ever stored)."""
import hashlib
import secrets


def hash_token(raw: str) -> str:
    """Stable sha256 hex of a token -- magic-link tokens are stored hashed."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def new_token() -> str:
    """High-entropy, URL-safe token for magic links."""
    return secrets.token_urlsafe(32)


def new_session_id() -> str:
    """High-entropy, URL-safe session id (bearer, stored server-side)."""
    return secrets.token_urlsafe(32)
