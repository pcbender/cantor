from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    root_dir: Path
    redis_url: str
    host: str
    port: int
    provider_timeout_seconds: int
    max_provider_output_bytes: int
    max_provider_cpu_seconds: int = 60
    max_provider_memory_bytes: int = 2_147_483_648
    max_job_artifact_bytes: int = 104_857_600

    @property
    def skills_dir(self) -> Path:
        return self.root_dir / "skills"

    @property
    def tools_dir(self) -> Path:
        return self.root_dir / "tools"

    @property
    def jobs_dir(self) -> Path:
        return self.root_dir / "work" / "jobs"

    @property
    def scaffolds_dir(self) -> Path:
        return self.root_dir / "work" / "scaffolds"


def get_settings(root_dir: Path | None = None) -> Settings:
    root = (root_dir or Path(__file__).resolve().parent.parent).resolve()
    load_dotenv(root / ".env")
    return Settings(
        root_dir=root,
        redis_url=os.getenv("CANTO_REDIS_URL", "redis://localhost:6379/0"),
        host=os.getenv("CANTO_HOST", "127.0.0.1"),
        port=int(os.getenv("CANTO_PORT", "8765")),
        provider_timeout_seconds=int(os.getenv("CANTO_PROVIDER_TIMEOUT_SECONDS", "120")),
        max_provider_output_bytes=int(os.getenv("CANTO_MAX_PROVIDER_OUTPUT_BYTES", "1048576")),
        max_provider_cpu_seconds=int(
            os.getenv("CANTO_MAX_PROVIDER_CPU_SECONDS", "60")
        ),
        max_provider_memory_bytes=int(
            os.getenv("CANTO_MAX_PROVIDER_MEMORY_BYTES", "2147483648")
        ),
        max_job_artifact_bytes=int(
            os.getenv("CANTO_MAX_JOB_ARTIFACT_BYTES", "104857600")
        ),
    )
