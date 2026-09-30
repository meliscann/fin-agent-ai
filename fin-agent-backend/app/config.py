from pydantic_settings import BaseSettings
from typing import Literal


class Settings(BaseSettings):
    # LLM
    llm_provider: Literal["gemini", "groq"] = "groq"

    gemini_api_key: str = ""
    gemini_model: str = "gemini-1.5-flash"

    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"

    # Veri kaynakları
    tcmb_api_key: str = ""

    # Analiz varsayımları — tek doğru kaynak (portfolio.py ve agents/__init__.py
    # burayı okur, kendi kopyalarını tutmaz)
    inflation_rate: float = 0.30

    # Uygulama
    app_env: Literal["development", "production"] = "development"
    app_port: int = 8000
    cors_origins: str = "http://localhost:3000"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",")]

    @property
    def is_dev(self) -> bool:
        return self.app_env == "development"

    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()
