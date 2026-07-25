import pytest
from sqlalchemy import select

from api.auth import hash_password
from enums import UserRole
from models import User


@pytest.mark.asyncio
async def test_admin_delete_user_commits(client, db_session):
    admin = User(
        username="admin-delete-user",
        password_hash=hash_password("admin-password"),
        role=UserRole.ADMIN,
    )
    target = User(
        username="delete-target-user",
        password_hash=hash_password("target-password"),
        role=UserRole.USER,
    )
    db_session.add_all([admin, target])
    await db_session.commit()

    login = await client.post(
        "/api/auth/login",
        json={"username": "admin-delete-user", "password": "admin-password"},
    )
    assert login.status_code == 200

    response = await client.delete(
        f"/api/admin/users/{target.id}",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    deleted = await db_session.execute(select(User).where(User.id == target.id))
    assert deleted.scalar_one_or_none() is None
