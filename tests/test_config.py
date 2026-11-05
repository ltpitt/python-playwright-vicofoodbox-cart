from __future__ import annotations

import pytest

from vicocart.config import ConfigError, load_credentials, load_llm_settings


def test_no_credentials_returns_none() -> None:
    assert load_credentials({}) is None


def test_both_set() -> None:
    creds = load_credentials({"VICO_EMAIL": " me@example.com ", "VICO_PASSWORD": "pw"})
    assert creds is not None
    assert creds.email == "me@example.com"
    assert creds.password == "pw"


@pytest.mark.parametrize("env", [{"VICO_EMAIL": "me@example.com"}, {"VICO_PASSWORD": "pw"}])
def test_half_set_is_an_error(env: dict[str, str]) -> None:
    with pytest.raises(ConfigError):
        load_credentials(env)


def test_password_not_in_repr() -> None:
    creds = load_credentials({"VICO_EMAIL": "me@example.com", "VICO_PASSWORD": "s3cret"})
    assert "s3cret" not in repr(creds)


def test_llm_needs_a_model() -> None:
    with pytest.raises(ConfigError, match="LLM_MODEL"):
        load_llm_settings({"LLM_API_KEY": "k"})


def test_llm_hosted_endpoint_needs_a_key() -> None:
    with pytest.raises(ConfigError, match="LLM_API_KEY"):
        load_llm_settings({"LLM_MODEL": "m"})


def test_llm_local_endpoint_needs_no_key() -> None:
    settings = load_llm_settings({"LLM_MODEL": "m", "LLM_BASE_URL": "http://localhost:11434/v1"})
    assert settings.base_url == "http://localhost:11434/v1"
    assert settings.api_key == "unused"


def test_llm_key_not_in_repr() -> None:
    settings = load_llm_settings({"LLM_MODEL": "m", "LLM_API_KEY": "sk-secret"})
    assert "sk-secret" not in repr(settings)
    assert settings.base_url is None
