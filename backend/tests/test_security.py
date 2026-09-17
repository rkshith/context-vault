import uuid

from app.core.security import create_access_token, decode_access_token, hash_password, verify_password


def test_password_roundtrip():
    hashed = hash_password("correct-horse-1")
    assert hashed != "correct-horse-1"
    assert verify_password("correct-horse-1", hashed) is True
    assert verify_password("wrong", hashed) is False
    assert verify_password("anything", "not-a-hash") is False


def test_token_roundtrip():
    user_id = uuid.uuid4()
    token = create_access_token(user_id)
    assert decode_access_token(token) == user_id


def test_token_invalid():
    assert decode_access_token("garbage") is None
    assert decode_access_token("") is None
