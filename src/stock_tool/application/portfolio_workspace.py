"""Application boundary for the native Holdings and Risk workspace.

The workspace composes the existing portfolio, valuation, health, risk, FX,
stress, and ledger services.  It intentionally owns no Streamlit state and it
never creates a ledger or fetches data while loading or analysing a portfolio.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
import json
from pathlib import Path
from typing import Callable, Mapping, Sequence, cast

import pandas as pd

from stock_tool import __version__
from stock_tool.application.portfolio import PortfolioLedgerService
from stock_tool.application.portfolio_risk import PortfolioRiskResult, PortfolioRiskService
from stock_tool.domain.models import MissingData
from stock_tool.portfolio.ledger import LedgerSnapshot
from stock_tool.portfolio.ledger_repository import LedgerRepository
from stock_tool.portfolio_health import (
    PortfolioHealthConfig,
    PortfolioHealthResult,
    PortfolioHealthService,
)
from stock_tool.portfolio_management import (
    add_portfolio_position,
    load_portfolio_result,
    normalize_portfolio,
    remove_portfolio_position,
    save_portfolio,
)
from stock_tool.portfolio_stress import (
    PortfolioStressResult,
    PortfolioStressService,
    StressScenario,
)
from stock_tool.portfolio_valuation import (
    Currency,
    FxQuote,
    PortfolioValuationConfig,
    PortfolioValuationResult,
    PortfolioValuationService,
    StaticFxRateProvider,
)
from stock_tool.portfolio_analytics import build_portfolio_risk_inputs
from stock_tool.runtime_paths import RuntimePaths


class PortfolioDataStatus(StrEnum):
    """User-visible state of the holdings analysis inputs."""

    MISSING = "missing"
    PARTIAL = "partial"
    STALE = "stale"
    READY = "ready"


@dataclass(frozen=True, slots=True)
class PortfolioWorkspaceSnapshot:
    """Immutable loaded holdings state without exposing a private path."""

    positions: pd.DataFrame
    status: PortfolioDataStatus
    warnings: tuple[str, ...] = ()
    missing_data: tuple[MissingData, ...] = ()

    @property
    def portfolio(self) -> pd.DataFrame:
        """Compatibility alias for callers that use the domain term portfolio."""

        return self.positions


@dataclass(frozen=True, slots=True)
class PortfolioWorkspaceManifest:
    """Deterministic, privacy-safe input manifest for one analysis."""

    core: Mapping[str, object]
    digest: str

    def to_dict(self) -> dict[str, object]:
        return {"schema_version": 1, "core": dict(self.core), "digest": self.digest}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n"


@dataclass(frozen=True, slots=True)
class PortfolioWorkspaceStressResult:
    """Stress evidence bound to the exact analysis and scenario that produced it."""

    result: PortfolioStressResult
    manifest_digest: str
    scenario: StressScenario

    @property
    def base_value_after(self) -> float | None:
        return self.result.base_value_after

    @property
    def base_impact(self) -> float | None:
        return self.result.base_impact

    @property
    def assumptions(self) -> tuple[str, ...]:
        return self.result.assumptions

    @property
    def disclaimer(self) -> str:
        return self.result.disclaimer

    @property
    def missing_data(self) -> tuple[MissingData, ...]:
        return self.result.missing_data


@dataclass(frozen=True, slots=True)
class PortfolioWorkspaceAnalysis:
    """All read-only analysis outputs used by the native page."""

    snapshot: PortfolioWorkspaceSnapshot
    valuation: PortfolioValuationResult
    health: PortfolioHealthResult
    risk: PortfolioRiskResult
    ledger_snapshot: LedgerSnapshot | None
    stress_results: tuple[PortfolioWorkspaceStressResult, ...]
    manifest: PortfolioWorkspaceManifest
    status: PortfolioDataStatus
    warnings: tuple[str, ...]

    @property
    def result(self) -> PortfolioWorkspaceAnalysis:
        """Expose a stable result alias for generic workspace consumers."""

        return self

    @property
    def is_current(self) -> bool:
        """Return the last computed state; callers should compare manifests for refreshes."""

        return True


# Short alias used by a few application consumers.
PortfolioWorkspaceResult = PortfolioWorkspaceAnalysis


class PortfolioWorkspaceApplicationService:
    """Coordinate portfolio persistence and analysis through injected paths."""

    def __init__(
        self,
        *,
        portfolio_path: str | Path | None = None,
        ledger_path: str | Path | None = None,
        valuation_service: PortfolioValuationService | None = None,
        health_service: PortfolioHealthService | None = None,
        risk_service: PortfolioRiskService | None = None,
        stress_service: PortfolioStressService | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        runtime = RuntimePaths.from_environment()
        self.portfolio_path = (
            Path(portfolio_path) if portfolio_path is not None else runtime.portfolio_file
        )
        self.ledger_path = (
            Path(ledger_path) if ledger_path is not None else runtime.ledger_database_file
        )
        self._valuation_service = valuation_service
        self._health_service = health_service or PortfolioHealthService()
        self._risk_service = risk_service or PortfolioRiskService(now=now)
        self._stress_service = stress_service or PortfolioStressService()

    def load_snapshot(self) -> PortfolioWorkspaceSnapshot:
        """Read holdings without creating or migrating any file."""

        loaded = load_portfolio_result(self.portfolio_path)
        positions = normalize_portfolio(loaded.frame)
        warnings = tuple("持股檔案讀取或格式需要檢查。" for _ in loaded.warnings[:1])
        status = (
            PortfolioDataStatus.MISSING
            if positions.empty and not loaded.warnings and not loaded.missing_data
            else (
                PortfolioDataStatus.PARTIAL
                if loaded.warnings or loaded.missing_data
                else PortfolioDataStatus.READY
            )
        )
        return PortfolioWorkspaceSnapshot(
            positions=positions,
            status=status,
            warnings=warnings,
            missing_data=tuple(loaded.missing_data),
        )

    def load_positions(self) -> pd.DataFrame:
        """Return a normalized copy of the current holdings."""

        return self.load_snapshot().positions.copy(deep=True)

    reload = load_snapshot

    def save_positions(self, positions: pd.DataFrame) -> pd.DataFrame:
        """Persist a normalized portfolio only after the caller explicitly saves."""

        normalized = normalize_portfolio(positions)
        save_portfolio(normalized, self.portfolio_path)
        return normalized.copy(deep=True)

    def add_or_update_position(
        self,
        positions: pd.DataFrame,
        *,
        symbol: str,
        market: str,
        quantity: float,
        average_cost: float,
        currency: str | None = None,
        note: str = "",
    ) -> pd.DataFrame:
        """Return and persist one market-qualified position update."""

        updated = add_portfolio_position(
            positions,
            symbol=symbol,
            market=market,
            quantity=float(quantity),
            average_cost=float(average_cost),
            currency=currency,
            note=note,
        )
        return self.save_positions(updated)

    add_position = add_or_update_position
    update_position = add_or_update_position

    def remove_position(self, positions: pd.DataFrame, *, symbol: str, market: str) -> pd.DataFrame:
        """Remove exactly one market-qualified identity and persist the result."""

        updated = remove_portfolio_position(positions, symbol=symbol, market=market)
        return self.save_positions(updated)

    def analyze(
        self,
        *,
        positions: pd.DataFrame | None = None,
        prices: pd.DataFrame | None = None,
        base_currency: Currency | str = Currency.TWD,
        fx_quote: FxQuote | None = None,
        fundamentals: pd.DataFrame | None = None,
        indicators: pd.DataFrame | None = None,
        stock_scores: pd.DataFrame | None = None,
        classifications: pd.DataFrame | None = None,
        fx_applied_at: str | None = None,
        health_config: PortfolioHealthConfig | None = None,
        stress_scenarios: Sequence[StressScenario] = (),
        scenario_inputs: pd.DataFrame | None = None,
    ) -> PortfolioWorkspaceAnalysis:
        """Calculate valuation, health, exposure, and stress evidence without I/O."""

        snapshot = self._snapshot_from_positions(positions)
        frame = snapshot.positions.copy(deep=True)
        currency = Currency.parse(base_currency)
        provider = StaticFxRateProvider([fx_quote]) if fx_quote is not None else None
        valuation_service = self._valuation_service or PortfolioValuationService(
            fx_provider=provider,
            config=PortfolioValuationConfig(base_currency=currency),
        )
        valuation = valuation_service.value(positions=frame, prices=prices)
        risk_inputs = build_portfolio_risk_inputs(prices, valuation.positions)
        health_service = self._health_service
        if health_config is not None:
            health_service = PortfolioHealthService(health_config)
        health = health_service.assess(
            portfolio=frame,
            valuation=valuation,
            prices=prices,
            fundamentals=fundamentals,
            indicators=indicators,
            stock_scores=stock_scores,
            risk_inputs=risk_inputs,
        )
        ledger_snapshot = self._read_existing_ledger()
        risk = self._risk_service.assess(
            portfolio=frame,
            prices=prices,
            valuation=valuation,
            health=health,
            classifications=classifications,
            ledger_snapshot=ledger_snapshot,
            warnings=risk_inputs.warnings,
            scenario_inputs=scenario_inputs,
        )
        warnings = _unique_text(
            (*snapshot.warnings, *valuation.warnings, *health.warnings, *risk.warnings)
        )
        missing = (
            *snapshot.missing_data,
            *valuation.missing_data,
            *health.missing_data,
            *risk.missing_data,
        )
        status = _analysis_status(snapshot, valuation, risk, fx_quote, missing)
        manifest = self.build_manifest(
            positions=frame,
            prices=prices,
            base_currency=currency,
            fx_quote=fx_quote,
            fx_applied_at=fx_applied_at,
            status=status,
            warnings=warnings,
            health_config=health_config or PortfolioHealthConfig(),
            stress_scenarios=stress_scenarios,
        )
        stress_results = tuple(
            PortfolioWorkspaceStressResult(
                result=self._stress_service.run(valuation=valuation, scenario=scenario),
                manifest_digest=manifest.digest,
                scenario=scenario,
            )
            for scenario in stress_scenarios
        )
        analysis_snapshot = PortfolioWorkspaceSnapshot(
            positions=frame,
            status=status,
            warnings=warnings,
            missing_data=tuple(dict.fromkeys(missing)),
        )
        return PortfolioWorkspaceAnalysis(
            snapshot=analysis_snapshot,
            valuation=valuation,
            health=health,
            risk=risk,
            ledger_snapshot=ledger_snapshot,
            stress_results=stress_results,
            manifest=manifest,
            status=status,
            warnings=warnings,
        )

    def build_manifest(
        self,
        *,
        positions: pd.DataFrame,
        prices: pd.DataFrame | None,
        base_currency: Currency | str,
        fx_quote: FxQuote | None,
        fx_applied_at: str | None = None,
        status: PortfolioDataStatus | str,
        warnings: Sequence[str] = (),
        health_config: PortfolioHealthConfig | None = None,
        stress_scenarios: Sequence[StressScenario] = (),
    ) -> PortfolioWorkspaceManifest:
        """Build a canonical manifest excluding notes, paths, and runtime timestamps."""

        health = health_config or PortfolioHealthConfig()
        scenario_payload = [
            {
                "name": scenario.name,
                "type": scenario.scenario_type.value,
                "shock_pct": float(scenario.shock_pct),
                "market": scenario.market,
            }
            for scenario in stress_scenarios
        ]
        fx_payload = None
        if fx_quote is not None:
            fx_payload = {
                "from_currency": fx_quote.from_currency.value,
                "to_currency": fx_quote.to_currency.value,
                "rate": float(fx_quote.rate) if fx_quote.rate is not None else None,
                "source": str(fx_quote.source),
                "effective_at": str(fx_quote.effective_at),
                "applied_at": fx_applied_at,
                "stale": bool(fx_quote.stale),
            }
        core: dict[str, object] = {
            "schema_version": 1,
            "holdings": {
                "fingerprint": _holdings_fingerprint(positions),
                "count": int(len(normalize_portfolio(positions))),
            },
            "prices": {
                "fingerprint": _prices_fingerprint(prices),
                "rows": int(len(prices)) if prices is not None else 0,
                "data_as_of": _price_as_of(prices),
            },
            "fx": fx_payload,
            "base_currency": Currency.parse(base_currency).value,
            "health": asdict(health),
            "risk": {"price_stale_after_days": 7},
            "stress": scenario_payload,
            "application_version": __version__,
            "status": PortfolioDataStatus(status).value,
            "warnings": list(_unique_text(warnings)),
        }
        encoded = _canonical_json(core)
        return PortfolioWorkspaceManifest(
            core=core,
            digest=sha256(encoded.encode("utf-8")).hexdigest(),
        )

    def result_is_current(
        self,
        analysis: PortfolioWorkspaceAnalysis | PortfolioWorkspaceManifest,
        *,
        positions: pd.DataFrame,
        prices: pd.DataFrame | None,
        base_currency: Currency | str,
        fx_quote: FxQuote | None,
        fx_applied_at: str | None = None,
        health_config: PortfolioHealthConfig | None = None,
        stress_scenarios: Sequence[StressScenario] = (),
    ) -> bool:
        """Compare a saved analysis with the current input manifest."""

        saved = analysis.manifest if isinstance(analysis, PortfolioWorkspaceAnalysis) else analysis
        current = self.build_manifest(
            positions=positions,
            prices=prices,
            base_currency=base_currency,
            fx_quote=fx_quote,
            fx_applied_at=fx_applied_at,
            status=cast(
                PortfolioDataStatus | str,
                saved.core.get("status", PortfolioDataStatus.READY.value),
            ),
            warnings=cast(Sequence[str], saved.core.get("warnings", ())),
            health_config=health_config,
            stress_scenarios=stress_scenarios,
        )
        return current.digest == saved.digest

    def run_stress(
        self, analysis: PortfolioWorkspaceAnalysis, scenario: StressScenario
    ) -> PortfolioWorkspaceStressResult:
        """Run one explicit assumption without changing analysis inputs."""

        return PortfolioWorkspaceStressResult(
            result=self._stress_service.run(valuation=analysis.valuation, scenario=scenario),
            manifest_digest=analysis.manifest.digest,
            scenario=scenario,
        )

    def stress_result_is_current(
        self,
        stress_result: PortfolioWorkspaceStressResult,
        analysis: PortfolioWorkspaceAnalysis,
        scenario: StressScenario,
    ) -> bool:
        """Reject stress evidence after either its analysis or assumptions changed."""

        return (
            isinstance(stress_result, PortfolioWorkspaceStressResult)
            and stress_result.manifest_digest == analysis.manifest.digest
            and stress_result.scenario == scenario
        )

    def _snapshot_from_positions(
        self, positions: pd.DataFrame | None
    ) -> PortfolioWorkspaceSnapshot:
        if positions is None:
            return self.load_snapshot()
        frame = normalize_portfolio(positions)
        status = PortfolioDataStatus.MISSING if frame.empty else PortfolioDataStatus.READY
        return PortfolioWorkspaceSnapshot(frame, status)

    def _read_existing_ledger(self) -> LedgerSnapshot | None:
        """Replay a ledger only when its SQLite file already exists."""

        if not self.ledger_path.is_file():
            return None
        try:
            repository = LedgerRepository(self.ledger_path)
            return PortfolioLedgerService(repository=repository).replay_persisted()
        except (OSError, RuntimeError, ValueError):
            return None


def _analysis_status(
    snapshot: PortfolioWorkspaceSnapshot,
    valuation: PortfolioValuationResult,
    risk: PortfolioRiskResult,
    fx_quote: FxQuote | None,
    missing: Sequence[MissingData],
) -> PortfolioDataStatus:
    if snapshot.positions.empty:
        return PortfolioDataStatus.MISSING
    if fx_quote is not None and fx_quote.stale:
        return PortfolioDataStatus.STALE
    if (
        valuation.base_market_value is None
        or missing
        or risk.price_data_status.status in {"partial", "unknown"}
    ):
        return PortfolioDataStatus.PARTIAL
    if risk.price_data_status.status == "stale":
        return PortfolioDataStatus.STALE
    return PortfolioDataStatus.READY


def _holdings_fingerprint(frame: pd.DataFrame) -> str:
    normalized = normalize_portfolio(frame)
    rows = [
        {
            "symbol": str(row.symbol),
            "market": str(row.market),
            "currency": str(row.currency),
            "quantity": float(row.quantity),
            "average_cost": float(row.average_cost),
        }
        for row in normalized.sort_values(["symbol", "market"]).itertuples(index=False)
    ]
    return _digest(rows)


def _prices_fingerprint(prices: pd.DataFrame | None) -> str | None:
    if prices is None or prices.empty:
        return None
    columns = [
        column for column in ("date", "symbol", "market", "close") if column in prices.columns
    ]
    if len(columns) < 4:
        return None
    work = prices.loc[:, columns].copy(deep=True)
    work["date"] = pd.to_datetime(work["date"], errors="coerce", utc=True).map(
        lambda value: value.isoformat() if pd.notna(value) else None
    )
    work["symbol"] = work["symbol"].fillna("").astype(str).str.strip().str.upper()
    work["market"] = work["market"].fillna("").astype(str).str.strip().str.upper()
    work["close"] = pd.to_numeric(work["close"], errors="coerce")
    rows = sorted(
        [row for row in work.to_dict(orient="records") if row["date"] is not None],
        key=lambda row: (row["symbol"], row["market"], row["date"], str(row["close"])),
    )
    return _digest(rows)


def _price_as_of(prices: pd.DataFrame | None) -> str | None:
    if prices is None or prices.empty or "date" not in prices.columns:
        return None
    dates = pd.to_datetime(prices["date"], errors="coerce").dropna()
    return dates.max().date().isoformat() if not dates.empty else None


def _digest(value: object) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _canonical_json(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=_json_default
    )


def _json_default(value: object) -> object:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Path):
        return value.name
    if isinstance(value, MissingData):
        return value.to_dict()
    if isinstance(value, tuple):
        return list(value)
    raise TypeError(f"Unsupported manifest value: {type(value).__name__}")


def _unique_text(values: Sequence[object]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))
