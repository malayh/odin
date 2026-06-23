"""Token hashing and personal-access-token primitives."""

import hashlib
import hmac
import secrets

TOKEN_PREFIX = "odin_pat_"
_TOKEN_BYTES = 32


def generate_token() -> str:
    return f"{TOKEN_PREFIX}{secrets.token_urlsafe(_TOKEN_BYTES)}"


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_token(token: str, token_hash: str) -> bool:
    return hmac.compare_digest(hash_token(token), token_hash)
