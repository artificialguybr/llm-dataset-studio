"""Configurações do LLM Dataset Studio — sem conceitos de imagem.

Substitui thumbnail_size/thumbnails_dir/quarantine_dir por text-specific paths.
"""
import json
import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="IDS_", env_file=".env", extra="ignore")

    data_dir: Path = Path("./data")
    db_url: str = ""  # empty = sqlite inside data_dir
    # Text quality thresholds (per-dataset overrides in Dataset.thresholds_json)
    min_length: int = 10
    max_length: int = 100000
    repetition_threshold: float = 0.3
    spam_threshold: float = 0.7
    code_threshold: float = 0.5
    toxicity_threshold: float = 0.8
    pii_threshold: float = 0.5
    # Near-duplicate (MinHash Jaccard)
    minhash_threshold: float = 0.7

    # Providers (plugins): ativo por escopo + credenciais. Pago só ativa com key.
    embeddings_provider: str = ""      # vazio = 1º registrado (sentence-transformers)
    preannotation_provider: str = ""
    captioning_provider: str = ""
    label_issues_provider: str = ""
    pii_provider: str = ""
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_text_model: str = "gpt-4o-mini"
    embeddings_device: str = ""           # vazio = auto (cuda > mps > cpu)
    # segundos de idle antes de despejar processos-plugin carregados (0 = nunca)
    plugin_idle_timeout: int = 900
    # Optional model/plugin assets; each plugin owns its runtime, not the core.
    models_path: str = ""
    plugins_path: str = ""

    @property
    def models_dir(self) -> Path:
        return Path(self.models_path) if self.models_path else self.data_dir / "models"

    @property
    def plugins_dir(self) -> Path:
        return Path(self.plugins_path) if self.plugins_path else self.data_dir / "plugins"

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def derived_dir(self) -> Path:
        return self.data_dir / "derived"

    @property
    def quarantine_dir(self) -> Path:
        return self.data_dir / "quarantine"

    @property
    def manifests_dir(self) -> Path:
        return self.data_dir / "manifests"

    @property
    def exports_dir(self) -> Path:
        return self.data_dir / "exports"

    @property
    def embeddings_dir(self) -> Path:
        return self.data_dir / "embeddings"

    def ensure_dirs(self) -> None:
        for d in (self.raw_dir, self.derived_dir, self.quarantine_dir,
                  self.manifests_dir, self.exports_dir, self.embeddings_dir,
                  self.models_dir, self.plugins_dir):
            d.mkdir(parents=True, exist_ok=True)

    @property
    def database_url(self) -> str:
        return self.db_url or f"sqlite:///{self.data_dir / 'studio.db'}"


_settings_cache: Settings | None = None


def _provider_file() -> Path:
    return get_settings_base().data_dir / "provider-settings.json"


def _read_provider_file() -> dict:
    path = _provider_file()
    try:
        value = json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def get_settings_base() -> Settings:
    return Settings()


def provider_model(provider: str, capability: str) -> str:
    stored = _read_provider_file().get("providers", {}).get(provider, {})
    models = stored.get("models", {}) if isinstance(stored, dict) else {}
    if isinstance(models, dict) and models.get(capability):
        return str(models[capability])
    s = get_settings()
    return {
        "openai": s.openai_text_model,
    }.get(provider, "")


def public_provider_settings() -> dict:
    s = get_settings()
    return {
        "selection": {
            scope: getattr(s, f"{scope}_provider", "")
            for scope in ("embeddings", "preannotation", "captioning", "label_issues", "pii")
        },
        "providers": {
            name: {
                "configured": bool(getattr(s, key)),
                "model": provider_model(name, "preannotation"),
                "models": {cap: provider_model(name, cap) for cap in ("preannotation", "captioning", "pii")},
            }
            for name, key in (
                ("openai", "openai_api_key"),
            )
        },
    }


def update_provider_settings(body: dict) -> dict:
    raw = _read_provider_file()
    providers = raw.setdefault("providers", {})
    for name, values in (body.get("providers") or {}).items():
        if name not in {"openai"} or not isinstance(values, dict):
            continue
        current = providers.setdefault(name, {})
        if values.get("api_key"):
            current["api_key"] = str(values["api_key"])
        models = values.get("models")
        if isinstance(models, dict):
            current.setdefault("models", {}).update({
                key: str(value).strip()
                for key, value in models.items()
                if key in {"preannotation", "captioning", "pii"} and str(value).strip()
            })
    selection = body.get("selection")
    if isinstance(selection, dict):
        raw["selection"] = {
            key: str(value)
            for key, value in selection.items()
            if key in {"embeddings", "preannotation", "captioning", "label_issues", "pii"}
        }
    path = _provider_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(raw, indent=2) + "\n")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    clear_settings_cache()
    return public_provider_settings()


def _provider_overrides() -> dict:
    raw = _read_provider_file()
    overrides = {}
    for scope, value in (raw.get("selection") or {}).items():
        if scope in {"embeddings", "preannotation", "captioning", "label_issues", "pii"} and value:
            overrides[f"{scope}_provider"] = value
    for provider, values in (raw.get("providers") or {}).items():
        if not isinstance(values, dict):
            continue
        key = {"openai": "openai_api_key"}.get(provider)
        if key and values.get("api_key"):
            overrides[key] = values["api_key"]
    return overrides


def get_settings() -> Settings:
    global _settings_cache
    if _settings_cache is None:
        base = Settings()
        _settings_cache = base.model_copy(update=_provider_overrides())
    return _settings_cache


def clear_settings_cache() -> None:
    global _settings_cache
    _settings_cache = None