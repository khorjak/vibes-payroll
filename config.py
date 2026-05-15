from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "sqlite:///./payroll.db"
    encryption_key: str = ""
    app_name: str = "Payroll"
    debug: bool = False

    model_config = {"env_file": ".env"}


settings = Settings()
