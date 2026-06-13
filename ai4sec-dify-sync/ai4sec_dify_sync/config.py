from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _path_env(name: str, default: Path) -> Path:
    value = _env(name)
    return Path(value).expanduser() if value else default


@dataclass(frozen=True)
class Settings:
    ai4sec_root: Path
    ai4sec_data_dir: Path
    ai4sec_app_db: Path
    state_db: Path
    dataset_id: str
    dify_base_url: str
    dify_dataset_api_key: str
    dify_proxy_base_url: str
    timeout_seconds: float
    indexing_technique: str
    process_rule_mode: str
    poll_interval_seconds: float
    max_attempts: int
    max_text_chars: int

    @property
    def use_proxy(self) -> bool:
        return bool(self.dify_proxy_base_url)


def load_settings(base_dir: Path) -> Settings:
    default_ai4sec_root = base_dir.parent
    ai4sec_root = _path_env("AI4SEC_ROOT", default_ai4sec_root).resolve()
    ai4sec_data_dir = _path_env("AI4SEC_DATA_DIR", ai4sec_root / "docker-data").resolve()
    ai4sec_app_db = _path_env("AI4SEC_APP_DB", ai4sec_data_dir / "app.db").resolve()
    state_db = _path_env("DIFY_SYNC_STATE_DB", base_dir / "state" / "dify_syncs.db").resolve()

    return Settings(
        ai4sec_root=ai4sec_root,
        ai4sec_data_dir=ai4sec_data_dir,
        ai4sec_app_db=ai4sec_app_db,
        state_db=state_db,
        dataset_id=_env("DIFY_DATASET_ID") or _env("DIFY_DEFAULT_DATASET_ID"),
        dify_base_url=_env("DIFY_BASE_URL").rstrip("/"),
        dify_dataset_api_key=_env("DIFY_DATASET_API_KEY"),
        dify_proxy_base_url=_env("DIFY_PROXY_BASE_URL").rstrip("/"),
        timeout_seconds=float(_env("DIFY_SYNC_TIMEOUT_SECONDS", "120")),
        indexing_technique=_env("DIFY_INDEXING_TECHNIQUE", "economy"),
        process_rule_mode=_env("DIFY_PROCESS_RULE_MODE", "automatic"),
        poll_interval_seconds=float(_env("DIFY_SYNC_INTERVAL_SECONDS", "30")),
        max_attempts=int(_env("DIFY_SYNC_MAX_ATTEMPTS", "5")),
        max_text_chars=int(_env("DIFY_SYNC_MAX_TEXT_CHARS", "0")),
    )
