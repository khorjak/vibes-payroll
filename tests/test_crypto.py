import pytest
from cryptography.fernet import Fernet
from utils.crypto import encrypt, decrypt


@pytest.fixture()
def keyed_settings(monkeypatch):
    key = Fernet.generate_key().decode()
    fake = type("S", (), {"encryption_key": key})()
    monkeypatch.setattr("utils.crypto.settings", fake)
    return fake


def test_encrypt_returns_empty_for_empty_string():
    assert encrypt("") == ""


def test_encrypt_raises_when_no_key_configured(monkeypatch):
    monkeypatch.setattr("utils.crypto.settings", type("S", (), {"encryption_key": ""})())
    with pytest.raises(RuntimeError, match="ENCRYPTION_KEY is not configured"):
        encrypt("123456789")


def test_encrypt_produces_ciphertext_different_from_plaintext(keyed_settings):
    result = encrypt("123456789")
    assert result is not None
    assert result != "123456789"


def test_encrypt_decrypt_roundtrip(keyed_settings):
    plaintext = "987654321"
    assert decrypt(encrypt(plaintext)) == plaintext


def test_decrypt_returns_none_when_no_key_configured(monkeypatch):
    monkeypatch.setattr("utils.crypto.settings", type("S", (), {"encryption_key": ""})())
    assert decrypt("anything") is None


def test_decrypt_returns_none_for_invalid_ciphertext(keyed_settings):
    assert decrypt("this-is-not-valid-fernet-ciphertext") is None


def test_ssn_strips_dashes_roundtrip(keyed_settings):
    # Simulate how create_employee strips dashes before encrypting
    raw_ssn = "123-45-6789"
    stripped = raw_ssn.replace("-", "")
    encrypted = encrypt(stripped)
    decrypted = decrypt(encrypted)
    assert decrypted == "123456789"
    assert decrypted[-4:] == "6789"
