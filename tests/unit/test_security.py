import uuid

import pytest

from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)


def test_password_hash_roundtrip():
    hashed = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", hashed)
    assert not verify_password("wrong password", hashed)


def test_access_token_roundtrip():
    user_id = uuid.uuid4()
    token = create_access_token(user_id)
    payload = decode_token(token)
    assert payload["sub"] == str(user_id)
    assert payload["type"] == "access"


def test_refresh_token_has_distinct_type():
    user_id = uuid.uuid4()
    token = create_refresh_token(user_id)
    payload = decode_token(token)
    assert payload["type"] == "refresh"


def test_decode_rejects_tampered_token():
    token = create_access_token(uuid.uuid4())
    # Tamper a middle character rather than the last one: the last base64url
    # character of an HMAC-SHA256 signature encodes some unused padding
    # bits, so flipping it can occasionally decode to the same signature
    # bytes and pass verification anyway -- a middle character is always a
    # genuine content change.
    mid = len(token) // 2
    tampered = token[:mid] + ("A" if token[mid] != "A" else "B") + token[mid + 1 :]
    with pytest.raises(Exception):
        decode_token(tampered)
