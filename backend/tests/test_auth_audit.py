import logging

import pytest

from api.auth import hash_password
from enums import UserRole
from models import User


@pytest.mark.asyncio
async def test_failed_login_audit_includes_submitted_credentials_and_forwarded_ip(
    client,
    db_session,
    caplog,
):
    user = User(
        username="audit-admin",
        password_hash=hash_password("expected-password"),
        role=UserRole.ADMIN,
    )
    db_session.add(user)
    await db_session.flush()
    with caplog.at_level(logging.WARNING, logger="api.auth"):
        response = await client.post(
            "/api/auth/login",
            json={"username": "audit-admin", "password": "submitted-typo"},
            headers={"X-Forwarded-For": "10.38.67.17"},
        )

    assert response.status_code == 401
    assert (
        "auth_login_failed reason=password_mismatch username=audit-admin "
        "password=submitted-typo client_ip=10.38.67.17"
    ) in caplog.text


@pytest.mark.asyncio
async def test_failed_login_audit_marks_unknown_username(client, caplog):
    with caplog.at_level(logging.WARNING, logger="api.auth"):
        response = await client.post(
            "/api/auth/login",
            json={"username": "missing-user", "password": "submitted-typo"},
            headers={"X-Forwarded-For": "10.38.67.17"},
        )

    assert response.status_code == 401
    assert (
        "auth_login_failed reason=user_not_found username=missing-user "
        "password=submitted-typo client_ip=10.38.67.17"
    ) in caplog.text
