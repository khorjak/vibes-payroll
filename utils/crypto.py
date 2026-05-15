from cryptography.fernet import Fernet
from config import settings


def _fernet() -> Fernet | None:
    if not settings.encryption_key:
        return None
    return Fernet(settings.encryption_key.encode())


def encrypt(value: str) -> str | None:
    f = _fernet()
    if not f or not value:
        return None
    return f.encrypt(value.encode()).decode()


def decrypt(value: str) -> str | None:
    f = _fernet()
    if not f or not value:
        return None
    try:
        return f.decrypt(value.encode()).decode()
    except Exception:
        return None
