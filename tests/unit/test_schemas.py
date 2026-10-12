"""Unit tests for request-schema validation."""

import pytest
from app.modules.auth.schemas import UserRegisterRequest
from pydantic import ValidationError


def test_password_too_short_rejected() -> None:
    with pytest.raises(ValidationError):
        UserRegisterRequest(email="a@b.com", password="short", company_name="Acme")


def test_password_too_long_rejected() -> None:
    with pytest.raises(ValidationError):
        UserRegisterRequest(email="a@b.com", password="x" * 129, company_name="Acme")


def test_invalid_email_rejected() -> None:
    with pytest.raises(ValidationError):
        UserRegisterRequest(email="not-an-email", password="supersecret", company_name="Acme")


def test_company_name_required() -> None:
    with pytest.raises(ValidationError):
        UserRegisterRequest(**{"email": "a@b.com", "password": "supersecret"})


def test_names_default_to_none() -> None:
    model = UserRegisterRequest(email="a@b.com", password="supersecret", company_name="Acme")
    assert model.first_name is None
    assert model.last_name is None
