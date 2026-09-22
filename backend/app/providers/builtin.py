"""Built-in text providers.

Local sentence-transformers embeddings, optional Cleanlab, and a configurable
OpenAI-compatible text LLM adapter are registered here. New company runtimes
can register the same Provider contract without changing the core services.
"""
from ..analyzers import embeddings as st_embeddings
from .base import Provider, register


class SentenceTransformersProvider(Provider):
    scope = "embeddings"
    name = "sentence-transformers"
    version = "st-1"
    install = "uv sync --extra ml"

    def available(self) -> tuple[bool, str]:
        return st_embeddings.is_available(), self.install


class OpenAITextProvider(Provider):
    """OpenAI-compatible text LLM; key and model are configured per capability."""
    version = "1"
    install = "set IDS_OPENAI_API_KEY and a model in Settings"

    def available(self) -> tuple[bool, str]:
        from ..config import get_settings, provider_model
        s = get_settings()
        if not s.openai_api_key:
            return False, self.install
        if not provider_model(self.name, self.scope):
            return False, "choose a model in Settings"
        return True, ""


class PreannotationOpenAI(OpenAITextProvider):
    scope = "preannotation"
    name = "openai"


class CaptionOpenAI(OpenAITextProvider):
    scope = "captioning"
    name = "openai"


class PiiOpenAI(OpenAITextProvider):
    scope = "pii"
    name = "openai"


class CleanlabProvider(Provider):
    scope = "label_issues"
    name = "cleanlab"
    version = "1"
    install = "uv add cleanlab"

    def available(self) -> tuple[bool, str]:
        try:
            import cleanlab  # noqa: F401
            return True, ""
        except ImportError:
            return False, self.install


register(SentenceTransformersProvider())
for provider in (PreannotationOpenAI(), CaptionOpenAI(), PiiOpenAI()):
    register(provider)
register(CleanlabProvider())
