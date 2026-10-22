"""Integration tests for invitations (join a company) and user management."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from app.models import Company, Invitation, User, UserRole
from app.modules.auth import security
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

INVITEE = "installer@example.com"
INVITEE_PASSWORD = "installerpass"


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _admin(registered: dict[str, Any]) -> dict[str, str]:
    return _headers(registered["access_token"])


async def _invite(
    client: AsyncClient, registered: dict[str, Any], email: str = INVITEE, role: str = "installer"
) -> dict[str, Any]:
    resp = await client.post(
        "/users/invitations", json={"email": email, "role": role}, headers=_admin(registered)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _accept(client: AsyncClient, token: str) -> dict[str, Any]:
    resp = await client.post(
        "/auth/invitations/accept",
        json={"token": token, "password": INVITEE_PASSWORD, "first_name": "Ina"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _user_in_other_company(db: AsyncSession) -> User:
    company = Company(name="Other Co")
    db.add(company)
    await db.flush()
    user = User(
        company_id=company.id, role=UserRole.INSTALLER, email="other@example.com", password_hash="x"
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


# --- Invitations -----------------------------------------------------------


async def test_full_invite_flow(client: AsyncClient, registered: dict[str, Any]) -> None:
    invite = await _invite(client, registered)
    assert invite["email"] == INVITEE
    assert invite["role"] == "installer"
    assert invite["token"]

    preview = await client.post("/auth/invitations/lookup", json={"token": invite["token"]})
    assert preview.status_code == 200
    assert preview.json()["company_name"] == "Test Co"
    assert preview.json()["email"] == INVITEE

    accepted = await _accept(client, invite["token"])
    user = accepted["user"]
    assert user["email"] == INVITEE
    assert user["role"] == "installer"
    assert user["company_id"] == registered["user"]["company_id"]
    assert accepted["access_token"]

    login = await client.post("/auth/login", json={"email": INVITEE, "password": INVITEE_PASSWORD})
    assert login.status_code == 200


async def test_invite_token_is_single_use(client: AsyncClient, registered: dict[str, Any]) -> None:
    invite = await _invite(client, registered)
    await _accept(client, invite["token"])

    again = await client.post(
        "/auth/invitations/accept", json={"token": invite["token"], "password": "anotherpass"}
    )
    assert again.status_code == 400


async def test_token_is_stored_hashed(
    client: AsyncClient, db: AsyncSession, registered: dict[str, Any]
) -> None:
    invite = await _invite(client, registered)
    row = await db.get(Invitation, uuid.UUID(invite["id"]))

    assert row is not None
    assert row.token_hash != invite["token"]
    assert row.token_hash == security.hash_invite_token(invite["token"])


async def test_expired_invite_rejected(
    client: AsyncClient, db: AsyncSession, registered: dict[str, Any]
) -> None:
    invite = await _invite(client, registered)
    row = await db.get(Invitation, uuid.UUID(invite["id"]))
    assert row is not None
    row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    await db.commit()

    resp = await client.post("/auth/invitations/lookup", json={"token": invite["token"]})
    assert resp.status_code == 400


async def test_unknown_token_rejected(client: AsyncClient) -> None:
    resp = await client.post(
        "/auth/invitations/accept", json={"token": "nope", "password": "whatever1"}
    )
    assert resp.status_code == 400


async def test_reinvite_replaces_old_link(client: AsyncClient, registered: dict[str, Any]) -> None:
    first = await _invite(client, registered)
    second = await _invite(client, registered, role="company_admin")

    old = await client.post("/auth/invitations/lookup", json={"token": first["token"]})
    assert old.status_code == 400
    accepted = await _accept(client, second["token"])
    assert accepted["user"]["role"] == "company_admin"


async def test_revoked_invite_rejected_and_hidden(
    client: AsyncClient, registered: dict[str, Any]
) -> None:
    invite = await _invite(client, registered)

    listed = await client.get("/users/invitations", headers=_admin(registered))
    assert [i["id"] for i in listed.json()] == [invite["id"]]
    assert "token" not in listed.json()[0]

    resp = await client.delete(f"/users/invitations/{invite['id']}", headers=_admin(registered))
    assert resp.status_code == 204
    again = await client.delete(f"/users/invitations/{invite['id']}", headers=_admin(registered))
    assert again.status_code == 404

    assert (await client.get("/users/invitations", headers=_admin(registered))).json() == []
    lookup = await client.post("/auth/invitations/lookup", json={"token": invite["token"]})
    assert lookup.status_code == 400


async def test_cannot_invite_existing_email(
    client: AsyncClient, registered: dict[str, Any]
) -> None:
    resp = await client.post(
        "/users/invitations",
        json={"email": registered["user"]["email"]},
        headers=_admin(registered),
    )
    assert resp.status_code == 409


async def test_cannot_invite_super_admin(client: AsyncClient, registered: dict[str, Any]) -> None:
    resp = await client.post(
        "/users/invitations",
        json={"email": "boss@example.com", "role": "super_admin"},
        headers=_admin(registered),
    )
    assert resp.status_code == 422


async def test_installer_cannot_invite(client: AsyncClient, registered: dict[str, Any]) -> None:
    installer = await _accept(client, (await _invite(client, registered))["token"])

    resp = await client.post(
        "/users/invitations",
        json={"email": "friend@example.com"},
        headers=_headers(installer["access_token"]),
    )
    assert resp.status_code == 403


async def test_cannot_revoke_other_company_invite(
    client: AsyncClient, db: AsyncSession, registered: dict[str, Any]
) -> None:
    other = await _user_in_other_company(db)
    invitation = Invitation(
        company_id=other.company_id,
        email="x@example.com",
        role=UserRole.INSTALLER,
        token_hash="0" * 64,
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )
    db.add(invitation)
    await db.commit()

    resp = await client.delete(f"/users/invitations/{invitation.id}", headers=_admin(registered))
    assert resp.status_code == 404


# --- User management -------------------------------------------------------


async def test_list_users_is_company_scoped(
    client: AsyncClient, db: AsyncSession, registered: dict[str, Any]
) -> None:
    await _user_in_other_company(db)
    installer = await _accept(client, (await _invite(client, registered))["token"])

    # Installers can see their teammates too
    resp = await client.get("/users", headers=_headers(installer["access_token"]))
    assert resp.status_code == 200
    emails = {u["email"] for u in resp.json()}
    assert emails == {registered["user"]["email"], INVITEE}


async def test_admin_can_promote_user(client: AsyncClient, registered: dict[str, Any]) -> None:
    installer = await _accept(client, (await _invite(client, registered))["token"])

    resp = await client.patch(
        f"/users/{installer['user']['id']}",
        json={"role": "company_admin"},
        headers=_admin(registered),
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == "company_admin"


async def test_installer_cannot_update_users(
    client: AsyncClient, registered: dict[str, Any]
) -> None:
    installer = await _accept(client, (await _invite(client, registered))["token"])

    resp = await client.patch(
        f"/users/{registered['user']['id']}",
        json={"is_active": False},
        headers=_headers(installer["access_token"]),
    )
    assert resp.status_code == 403


async def test_admin_cannot_modify_self(client: AsyncClient, registered: dict[str, Any]) -> None:
    resp = await client.patch(
        f"/users/{registered['user']['id']}",
        json={"role": "installer"},
        headers=_admin(registered),
    )
    assert resp.status_code == 409


async def test_cannot_modify_other_company_user(
    client: AsyncClient, db: AsyncSession, registered: dict[str, Any]
) -> None:
    other = await _user_in_other_company(db)
    resp = await client.patch(
        f"/users/{other.id}", json={"is_active": False}, headers=_admin(registered)
    )
    assert resp.status_code == 404


async def test_company_admin_cannot_modify_super_admin(
    client: AsyncClient, db: AsyncSession, registered: dict[str, Any]
) -> None:
    boss = User(
        company_id=uuid.UUID(registered["user"]["company_id"]),
        role=UserRole.SUPER_ADMIN,
        email="boss@example.com",
        password_hash="x",
    )
    db.add(boss)
    await db.commit()

    resp = await client.patch(
        f"/users/{boss.id}", json={"is_active": False}, headers=_admin(registered)
    )
    assert resp.status_code == 403


async def test_deactivated_user_is_locked_out(
    client: AsyncClient, registered: dict[str, Any]
) -> None:
    # Accepting leaves the installer's refresh cookie in the client jar.
    installer = await _accept(client, (await _invite(client, registered))["token"])

    resp = await client.patch(
        f"/users/{installer['user']['id']}",
        json={"is_active": False},
        headers=_admin(registered),
    )
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False

    me = await client.get("/auth/me", headers=_headers(installer["access_token"]))
    assert me.status_code == 401
    refreshed = await client.post("/auth/refresh")
    assert refreshed.status_code == 401
    login = await client.post("/auth/login", json={"email": INVITEE, "password": INVITEE_PASSWORD})
    assert login.status_code == 403

    # Reactivating restores login
    await client.patch(
        f"/users/{installer['user']['id']}", json={"is_active": True}, headers=_admin(registered)
    )
    login = await client.post("/auth/login", json={"email": INVITEE, "password": INVITEE_PASSWORD})
    assert login.status_code == 200
