"""Application configuration."""
from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Settings loaded from environment."""

    # Paths (shared storage: same base_dir for API and workers; can override with volume/MinIO path)
    base_dir: Path = Path(__file__).resolve().parent.parent
    # Stateless: solo directorios temporales por sesión (session_root / session_id); se borra tras descarga o TTL
    session_root: Path = Path(".sessions")
    # Librería de samples para overlays IA (percussion, instruments, vocals)
    assets_samples_dir: Path = Path("assets") / "samples"

    # Redis: broker/backend for Celery, job state, admin config (if set → use Celery + Redis store)
    redis_url: str = ""

    # LLM (only for JSON decision; no audio processing)
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    mix_decision_model: str = "gpt-4o-mini"

    # Audio
    default_sr: int = 44100
    max_upload_mb: int = 100

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.session_root = self.base_dir / str(self.session_root)
        self.assets_samples_dir = self.base_dir / str(self.assets_samples_dir)

    @property
    def use_celery(self) -> bool:
        return bool(self.redis_url and self.redis_url.strip())

    model_config = {"env_prefix": "AUTOMIX_", "env_file": ".env"}


settings = Settings()
