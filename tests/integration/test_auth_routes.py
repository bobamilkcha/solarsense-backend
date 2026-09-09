"""Integration tests for the auth routes (HTTP layer).

Note: /auth/refresh and /auth/logout read the refresh token from the cookie, not
the request body. The httpx AsyncClient persists Set-Cookie across requests, so
once a test registers/logs in, the cookie is sent automatically.
"""

from httpx import AsyncClient


async def test_register_returns_access_and_sets_httponly_cookie(
    client: AsyncClient, credentials: dict[str, str]
) -> None:
    resp = await client.post("/auth/register", json=credentials)

    assert resp.status_code == 201

    body = resp.json()
    assert body["access_token"]
    assert body["token_type"] == "bearer"
    assert body["user"]["email"] == credentials["email"]
    # Refresh token lives only in the cookie, never in the JSON body.
    assert "refresh_token" not in body

    set_cookie = resp.headers["set-cookie"]
    assert "refresh_token=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "Path=/auth" in set_cookie


async def test_register_rejects_short_password(
    client: AsyncClient, credentials: dict[str, str]
) -> None:
    resp = await client.post("/auth/register", json={**credentials, "password": "short"})
    assert resp.status_code == 422


async def test_register_rejects_duplicate_email(
    client: AsyncClient, credentials: dict[str, str], registered: dict[str, object]
) -> None:
    resp = await client.post("/auth/register", json=credentials)
    assert resp.status_code == 409
    assert resp.json()["detail"] == "Email already exists"


async def test_login_returns_access_and_sets_cookie(
    client: AsyncClient, credentials: dict[str, str], registered: dict[str, object]
) -> None:
    resp = await client.post("/auth/login", json=credentials)

    assert resp.status_code == 200
    assert resp.json()["token_type"] == "bearer"
    assert "HttpOnly" in resp.headers["set-cookie"]


async def test_login_rejects_wrong_password(
    client: AsyncClient, credentials: dict[str, str], registered: dict[str, object]
) -> None:
    resp = await client.post("/auth/login", json={**credentials, "password": "wrong"})
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid credentials"


async def test_login_rejects_unknown_email(
    client: AsyncClient, credentials: dict[str, str]
) -> None:
    resp = await client.post("/auth/login", json=credentials)
    assert resp.status_code == 401


async def test_login_rejects_missing_field(client: AsyncClient) -> None:
    resp = await client.post("/auth/login", json={"email": "a@b.com"})
    assert resp.status_code == 422


async def test_refresh_rotates_and_invalidates_old_token(
    client: AsyncClient, registered: dict[str, object]
) -> None:
    old_cookie = client.cookies.get("refresh_token")

    resp = await client.post("/auth/refresh")
    assert resp.status_code == 200
    assert resp.json()["token_type"] == "bearer"

    new_cookie = client.cookies.get("refresh_token")
    assert new_cookie != old_cookie

    # Reusing the rotated-out token must fail. Clear the jar first so the new
    # cookie doesn't shadow the one we're putting back.
    client.cookies.clear()
    client.cookies.set("refresh_token", old_cookie, domain="test", path="/auth")  # type: ignore
    reuse = await client.post("/auth/refresh")
    assert reuse.status_code == 401


async def test_refresh_without_cookie_returns_401(client: AsyncClient) -> None:
    resp = await client.post("/auth/refresh")
    assert resp.status_code == 401


async def test_refresh_rejects_garbage_cookie(client: AsyncClient) -> None:
    client.cookies.set("refresh_token", "not-a-jwt", domain="test", path="/auth")
    resp = await client.post("/auth/refresh")
    assert resp.status_code == 401


async def test_logout_revokes_refresh_token(
    client: AsyncClient, registered: dict[str, object]
) -> None:
    logout = await client.post("/auth/logout")
    assert logout.status_code == 204

    # The revoked token can no longer be refreshed.
    resp = await client.post("/auth/refresh")
    assert resp.status_code == 401


async def test_logout_without_cookie_is_idempotent(client: AsyncClient) -> None:
    resp = await client.post("/auth/logout")
    assert resp.status_code == 204


async def test_me_returns_user_when_authenticated(
    client: AsyncClient, credentials: dict[str, str], registered: dict[str, object]
) -> None:
    access = registered["access_token"]
    resp = await client.get("/auth/me", headers={"Authorization": f"Bearer {access}"})
    assert resp.status_code == 200
    assert resp.json()["email"] == credentials["email"]


async def test_me_without_token_returns_401(client: AsyncClient) -> None:
    resp = await client.get("/auth/me")
    assert resp.status_code == 401


async def test_me_rejects_garbage_token(client: AsyncClient) -> None:
    resp = await client.get("/auth/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert resp.status_code == 401
    assert resp.headers["www-authenticate"] == "Bearer"
