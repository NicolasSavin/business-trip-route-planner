import os
from pydantic import BaseModel
class Settings(BaseModel):
    enabled: bool = os.getenv("TUTU_PLAYWRIGHT_ENABLED", "false").lower() == "true"
    headless: bool = os.getenv("TUTU_PLAYWRIGHT_HEADLESS", "true").lower() == "true"
    timeout_seconds: int = int(os.getenv("TUTU_PLAYWRIGHT_TIMEOUT_SECONDS", "30"))
    operation_timeout_seconds: int = int(os.getenv("TUTU_PLAYWRIGHT_OPERATION_TIMEOUT_SECONDS", "25"))
    concurrency: int = int(os.getenv("TUTU_PLAYWRIGHT_CONCURRENCY", "1"))
    cache_ttl_seconds: int = int(os.getenv("TUTU_PLAYWRIGHT_CACHE_TTL_SECONDS", "300"))
    artifact_dir: str = os.getenv("TUTU_PLAYWRIGHT_ARTIFACT_DIR", "/tmp/tutu-playwright-artifacts")
    service_api_token: str = os.getenv("SERVICE_API_TOKEN", "")
    mock_mode: bool = os.getenv("TUTU_PLAYWRIGHT_MOCK", "true").lower() == "true"
    tutu_base_url: str = os.getenv("TUTU_BASE_URL", "https://www.tutu.ru")
settings = Settings()
