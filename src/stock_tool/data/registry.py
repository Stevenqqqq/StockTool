"""Declarative registry for supported price-data providers.

The registry describes capability and deterministic fallback order only.  It
never stores credentials or provider-specific request parameters.
"""

from __future__ import annotations

from dataclasses import dataclass


class ProviderRegistryError(ValueError):
    """Raised when a requested provider is unknown or incompatible."""


@dataclass(frozen=True, slots=True)
class ProviderCapability:
    """Non-sensitive provider capability advertised to orchestration code."""

    markets: frozenset[str]
    data_types: frozenset[str] = frozenset({"prices"})
    requires_credentials: bool = False

    def supports(self, *, market: str, data_type: str = "prices") -> bool:
        """Return whether the provider supports an explicit request."""

        return market.upper() in self.markets and data_type in self.data_types


@dataclass(frozen=True, slots=True)
class ProviderDefinition:
    """One provider entry with deterministic priority."""

    provider_id: str
    display_name: str
    capability: ProviderCapability
    priority: int
    enabled: bool = True

    def __post_init__(self) -> None:
        """Normalize the public provider identifier."""

        provider_id = str(self.provider_id).strip().lower()
        if not provider_id:
            raise ValueError("provider_id 不可為空白。")
        object.__setattr__(self, "provider_id", provider_id)


@dataclass(frozen=True, slots=True)
class ProviderRegistry:
    """Immutable source of provider capability and fallback ordering."""

    definitions: tuple[ProviderDefinition, ...]

    def __post_init__(self) -> None:
        """Reject duplicate provider identifiers before runtime use."""

        identifiers = [definition.provider_id for definition in self.definitions]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("Provider registry 不可包含重複 provider_id。")

    def definition(self, provider_id: str) -> ProviderDefinition:
        """Return one registered provider or raise a safe configuration error."""

        normalized = str(provider_id).strip().lower()
        for definition in self.definitions:
            if definition.provider_id == normalized:
                return definition
        raise ProviderRegistryError(f"不支援的資料來源：{normalized or '空白'}")

    def ordered(
        self,
        *,
        provider_id: str,
        market: str,
        data_type: str = "prices",
    ) -> tuple[ProviderDefinition, ...]:
        """Return enabled compatible providers in stable priority order.

        ``cache`` is intentionally not registered here: it is a local fallback
        policy rather than a remote provider capability.
        """

        selected = str(provider_id).strip().lower()
        market_key = str(market).strip().upper()
        if selected == "auto":
            return tuple(
                sorted(
                    (
                        definition
                        for definition in self.definitions
                        if definition.enabled
                        and definition.capability.supports(market=market_key, data_type=data_type)
                    ),
                    key=lambda definition: (definition.priority, definition.provider_id),
                )
            )

        definition = self.definition(selected)
        if not definition.enabled:
            raise ProviderRegistryError(f"資料來源 {definition.provider_id} 目前未啟用。")
        if not definition.capability.supports(market=market_key, data_type=data_type):
            raise ProviderRegistryError(
                f"資料來源 {definition.provider_id} 不支援市場 {market_key}。"
            )
        return (definition,)


DEFAULT_PROVIDER_REGISTRY = ProviderRegistry(
    definitions=(
        ProviderDefinition(
            provider_id="yfinance",
            display_name="yfinance",
            capability=ProviderCapability(markets=frozenset({"TWSE", "TPEX", "US", "AUTO"})),
            priority=10,
        ),
        ProviderDefinition(
            provider_id="finmind",
            display_name="FinMind",
            capability=ProviderCapability(
                markets=frozenset({"TWSE", "TPEX"}), requires_credentials=True
            ),
            priority=20,
        ),
    )
)
