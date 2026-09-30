from functools import lru_cache
import os


class Settings:
    database_url: str = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg://seismo:seismo@localhost:5432/seismo_teaching",
    )
    sample_dir: str = os.getenv("SAMPLE_DIR", "/workspace/backend/sample_data")
    model_name: str = "homogeneous-halfspace"
    model_version: str = "homogeneous-halfspace-v1"
    p_velocity_km_s: float = 6.0
    s_velocity_km_s: float = 3.5
    default_depth_km: float = 8.0
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
