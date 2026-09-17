import uuid

from qdrant_client import models

from app.vectorstore.qdrant_repo import _filter


def test_filter_always_includes_user():
    user_id = uuid.uuid4()
    f = _filter(user_id)
    assert isinstance(f, models.Filter)
    keys = [c.key for c in f.must]
    assert "user_id" in keys
    assert "document_id" not in keys


def test_filter_with_documents():
    user_id = uuid.uuid4()
    docs = [uuid.uuid4(), uuid.uuid4()]
    f = _filter(user_id, docs)
    by_key = {c.key: c for c in f.must}
    assert by_key["user_id"].match.value == str(user_id)
    assert set(by_key["document_id"].match.any) == {str(d) for d in docs}
