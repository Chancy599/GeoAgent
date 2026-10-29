"""Runtime configuration for GeoAgent.

Secrets are read from ``.env`` and are never printed or logged by this module.
The default model id (``claude-haiku-5-5``) was verified against the configured
OpenAI-compatible provider's ``/models`` endpoint.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")


@dataclass
class PathSettings:
    project_root: Path = PROJECT_ROOT
    data_root: Path = PROJECT_ROOT / "data"
    image_dir: Path = PROJECT_ROOT / "data" / "test" / "image"
    latex_dir: Path = PROJECT_ROOT / "data" / "test" / "latex"
    tool_dir: Path = PROJECT_ROOT / "tool"
    tectonic: Path = PROJECT_ROOT / "tool" / "tectonic" / "tectonic.exe"
    outputs_dir: Path = PROJECT_ROOT / "outputs"
    runs_dir: Path = PROJECT_ROOT / "outputs" / "runs"
    configs_dir: Path = PROJECT_ROOT / "configs"
    env_file: Path = PROJECT_ROOT / ".env"


@dataclass
class ModelSettings:
    model: str = "claude-haiku-5-5"
    base_url: str = ""
    api_key: str = ""
    max_tokens: int = 4096
    temperature: float | None = None
    request_timeout: float = 120.0
    max_retries: int = 3
    image_max_dim: int = 1280
    jpeg_quality: int = 85

    def public_dict(self) -> dict[str, Any]:
        """Safe for logs: never includes the API key."""
        return {
            "model": self.model,
            "base_url": self.base_url,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "request_timeout": self.request_timeout,
            "max_retries": self.max_retries,
            "image_max_dim": self.image_max_dim,
            "jpeg_quality": self.jpeg_quality,
            "api_key_present": bool(self.api_key),
        }


@dataclass
class BudgetSettings:
    max_steps: int = 24
    max_tool_calls: int = 48
    max_visual_calls: int = 24
    max_total_tokens: int = 400_000
    timeout_seconds: int = 1200
    compile_timeout_seconds: int = 120

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Settings:
    paths: PathSettings = field(default_factory=PathSettings)
    model: ModelSettings = field(default_factory=ModelSettings)
    budget: BudgetSettings = field(default_factory=BudgetSettings)

    def public_dict(self) -> dict[str, Any]:
        return {
            "model": self.model.public_dict(),
            "budget": self.budget.to_dict(),
            "paths": {
                "project_root": str(self.paths.project_root),
                "image_dir": str(self.paths.image_dir),
                "latex_dir": str(self.paths.latex_dir),
                "tectonic": str(self.paths.tectonic),
                "runs_dir": str(self.paths.runs_dir),
            },
        }


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _build_paths() -> PathSettings:
    paths = PathSettings()
    overrides = _read_json(paths.configs_dir / "paths.json")
    for key, value in overrides.items():
        if hasattr(paths, key) and isinstance(value, str):
            candidate = Path(value)
            if not candidate.is_absolute():
                candidate = paths.project_root / candidate
            setattr(paths, key, candidate)
    tectonic_env = os.environ.get("GEOAGENT_TECTONIC")
    if tectonic_env:
        paths.tectonic = Path(tectonic_env)
    return paths


def _build_model() -> ModelSettings:
    defaults = ModelSettings()
    cfg = _read_json(PROJECT_ROOT / "configs" / "default.json")
    model_cfg = cfg.get("model", {}) if isinstance(cfg, dict) else {}

    model = ModelSettings(
        model=os.environ.get("GEOAGENT_MODEL") or model_cfg.get("model", defaults.model),
        base_url=os.environ.get("OPENAI_BASE_URL") or model_cfg.get("base_url", defaults.base_url),
        api_key=os.environ.get("OPENAI_API_KEY") or os.environ.get("GEOAGENT_API_KEY", ""),
        max_tokens=int(os.environ.get("GEOAGENT_MAX_TOKENS", model_cfg.get("max_tokens", defaults.max_tokens))),
        temperature=model_cfg.get("temperature", defaults.temperature),
        request_timeout=float(
            os.environ.get("GEOAGENT_REQUEST_TIMEOUT", model_cfg.get("request_timeout", defaults.request_timeout))
        ),
        max_retries=_env_int("GEOAGENT_MAX_RETRIES", int(model_cfg.get("max_retries", defaults.max_retries))),
        image_max_dim=_env_int("GEOAGENT_IMAGE_MAX_DIM", int(model_cfg.get("image_max_dim", defaults.image_max_dim))),
        jpeg_quality=_env_int("GEOAGENT_JPEG_QUALITY", int(model_cfg.get("jpeg_quality", defaults.jpeg_quality))),
    )
    return model


def _build_budget(run_overrides: dict[str, Any] | None = None) -> BudgetSettings:
    cfg = _read_json(PROJECT_ROOT / "configs" / "default.json")
    budget_cfg = cfg.get("budget", {}) if isinstance(cfg, dict) else {}
    defaults = BudgetSettings()
    values: dict[str, Any] = {}
    for key in defaults.to_dict():
        values[key] = budget_cfg.get(key, getattr(defaults, key))

    env_map = {
        "max_steps": "GEOAGENT_MAX_STEPS",
        "max_tool_calls": "GEOAGENT_MAX_TOOL_CALLS",
        "max_visual_calls": "GEOAGENT_MAX_VISUAL_CALLS",
        "max_total_tokens": "GEOAGENT_MAX_TOTAL_TOKENS",
        "timeout_seconds": "GEOAGENT_TIMEOUT_SECONDS",
        "compile_timeout_seconds": "GEOAGENT_COMPILE_TIMEOUT_SECONDS",
    }
    for key, env_name in env_map.items():
        if env_name in os.environ:
            try:
                values[key] = int(os.environ[env_name])
            except ValueError:
                pass
    if run_overrides:
        for key, value in run_overrides.items():
            if key in values and value is not None:
                values[key] = int(value) if key != "temperature" else value
    return BudgetSettings(**values)


def load_settings(run_overrides: dict[str, Any] | None = None) -> Settings:
    """Load settings from .env + configs/default.json + explicit run overrides."""
    return Settings(
        paths=_build_paths(),
        model=_build_model(),
        budget=_build_budget(run_overrides),
    )
