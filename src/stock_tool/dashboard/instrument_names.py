"""Render-scoped access to the shared name directory; no implicit disk/network I/O."""

from contextvars import ContextVar
from collections.abc import Callable
from typing import Any

from stock_tool.application.instrument_names import NameDirectory, directory_for
from stock_tool.runtime_paths import RuntimePaths

current_names: ContextVar[NameDirectory | None] = ContextVar("instrument_names", default=None)


def bind_names(st: Any, paths: RuntimePaths) -> Callable[[], None]:
    directory = directory_for(paths.cache_dir / "instrument-names-v1.json")
    current_names.set(directory)
    directory.start_refresh()
    if directory.running:
        st.session_state["names_refresh_pending"] = True

    @st.fragment(run_every="2s")
    def poll() -> None:
        if directory.running:
            st.caption("官方名稱背景確認中；行情與研究可先使用。")
        elif st.session_state.pop("names_refresh_pending", False):
            st.rerun(scope="app")

    return poll


def name_notice(market: str, symbol: str) -> str:
    directory = current_names.get()
    if market.upper() not in {"TWSE", "TPEX"}:
        return ""
    if directory is None:
        return "中文名稱未確認"
    _, notice = directory.resolve(market, symbol)
    return notice
