# -*- coding: utf-8 -*-
import uuid

import pytest


@pytest.mark.asyncio
async def test_get_user_cookie_string_cleans_undecryptable_record(monkeypatch):
    from unittest.mock import patch

    from cryptography.exceptions import InvalidTag

    from app.services.agent import web_cookie_store as wcs

    owner = uuid.uuid4()
    calls = []

    class FakeRow:
        cookie_string = "encrypted-bytes"

    class FakeSession:
        def __init__(self):
            self.deleted = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def scalar(self, stmt):
            return FakeRow()

        async def delete(self, row):
            self.deleted.append(row)

        async def commit(self):
            calls.append("commit")

    fake_session = FakeSession()

    def fake_decrypt(ct, key):
        raise InvalidTag

    monkeypatch.setattr(wcs, "async_session_factory", lambda: fake_session)
    monkeypatch.setattr(wcs, "decrypt_token", fake_decrypt)

    result = await wcs.get_user_cookie_string(owner, "www.douyin.com")

    assert result is None
    assert len(fake_session.deleted) == 1
    assert "commit" in calls
