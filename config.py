from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "sqlite:///./payroll.db"
    encryption_key: str = ""
    secret_key: str = "dev-secret-key-change-in-production"
    admin_username: str = "admin"
    admin_password: str = "changeme"
    app_name: str = "Payroll"
    debug: bool = False
    session_https_only: bool = False

    model_config = {"env_file": ".env"}


settings = Settings()

_INSECURE_SECRET = "dev-secret-key-change-in-production"
if not settings.debug and settings.secret_key == _INSECURE_SECRET:
    raise RuntimeError(
        "SECRET_KEY must be changed from the default before running in production. "
        "Set SECRET_KEY in your .env file or set DEBUG=true for local development."
    )
