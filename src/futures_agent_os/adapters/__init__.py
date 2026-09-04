"""Concrete external adapters behind domain-owned ports."""

from .codex_app_server import (
    CodexAppServerProvider as CodexGenericModelProvider,
    CodexTurnTransport,
    OfficialCodexAppServerTransport,
)
from .iwencai_openapi import (
    IwencaiEvidence,
    IwencaiHttpResult,
    IwencaiOpenApiClient,
    IwencaiRequest,
    IwencaiSkill,
    IwencaiTransport,
    UrlLibIwencaiTransport,
)
from .official_exchange_daily import (
    HttpReadResult,
    OfficialDailyRawFile,
    OfficialDailySource,
    OfficialExchangeDailyClient,
    ReadOnlyHttpTransport,
    UrlLibReadOnlyTransport,
    official_daily_url,
)
from .official_research_series import (
    OFFICIAL_RESEARCH_ROLL_POLICY,
    OFFICIAL_RESEARCH_SERIES_NORMALIZER,
    OfficialResearchSeriesBundle,
    materialize_official_research_series,
)
from .official_daily_bars import OfficialDailyBar, normalize_official_daily
from .official_daily_dataset import (
    OFFICIAL_DAILY_DATASET_SCHEMA,
    OFFICIAL_DAILY_NORMALIZER,
    OfficialDailyDatasetBundle,
    materialize_official_daily_datasets,
)
from .openai_responses import OpenAIResponsesProvider, ResponseTransport
from .research_model_payload import (
    R002_EXPERIMENT_DESIGN_SCHEMA,
    R002_INDEPENDENT_CRITIC_SCHEMA,
    R002_RESEARCH_SYNTHESIS_SCHEMA,
)

__all__ = [
    "CodexGenericModelProvider",
    "CodexTurnTransport",
    "OfficialCodexAppServerTransport",
    "HttpReadResult",
    "OfficialDailyRawFile",
    "OfficialDailySource",
    "OfficialExchangeDailyClient",
    "OFFICIAL_RESEARCH_ROLL_POLICY",
    "OFFICIAL_RESEARCH_SERIES_NORMALIZER",
    "OfficialResearchSeriesBundle",
    "materialize_official_research_series",
    "ReadOnlyHttpTransport",
    "UrlLibReadOnlyTransport",
    "official_daily_url",
    "OfficialDailyBar",
    "normalize_official_daily",
    "OFFICIAL_DAILY_DATASET_SCHEMA",
    "OFFICIAL_DAILY_NORMALIZER",
    "OfficialDailyDatasetBundle",
    "materialize_official_daily_datasets",
    "IwencaiEvidence",
    "IwencaiHttpResult",
    "IwencaiOpenApiClient",
    "IwencaiRequest",
    "IwencaiSkill",
    "IwencaiTransport",
    "UrlLibIwencaiTransport",
    "OpenAIResponsesProvider",
    "ResponseTransport",
    "R002_EXPERIMENT_DESIGN_SCHEMA",
    "R002_INDEPENDENT_CRITIC_SCHEMA",
    "R002_RESEARCH_SYNTHESIS_SCHEMA",
]
