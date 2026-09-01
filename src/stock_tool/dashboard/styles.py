"""Static design tokens and responsive styles for the Streamlit dashboard."""

from __future__ import annotations

from typing import Any

# This mapping is deliberately identical to .streamlit/config.toml. StockTool
# currently offers one product theme; it does not claim a light-mode contract
# while forcing dark presentation with CSS.
STREAMLIT_THEME_CONTRACT = {
    "base": "dark",
    "primaryColor": "#4F9CFF",
    "backgroundColor": "#0B1220",
    "secondaryBackgroundColor": "#111B2B",
    "textColor": "#EDF2F8",
    "font": "sans serif",
}

# Keep visual decisions in one small, inspectable contract. Values are static
# and never include user, provider, or market data.
DESIGN_TOKENS = {
    "app_background": "#0b1220",
    "surface": "#111b2b",
    "surface_muted": "#0f1826",
    "surface_alt": "#162235",
    "surface_elevated": "#1b2a40",
    "primary": "#4f9cff",
    "primary_hover": "#75b5ff",
    "accent": "#75d7c6",
    "success": "#42c997",
    "warning": "#e0ad58",
    "error": "#e47783",
    "info": "#6da9ee",
    "border": "#2b3a50",
    "border_strong": "#3b506d",
    "text": "#edf2f8",
    "muted": "#aeb9c8",
    "subtle": "#7f8da3",
    "font_family": '"Microsoft JhengHei", "PingFang TC", "Segoe UI", sans-serif',
    "font_size_body": "0.95rem",
    "font_size_small": "0.8rem",
    "font_size_title": "clamp(1.75rem, 3.1vw, 2.65rem)",
    "line_height_body": "1.55",
    "line_height_heading": "1.18",
    "spacing_xs": "0.35rem",
    "spacing_sm": "0.6rem",
    "spacing_md": "1rem",
    "spacing_lg": "1.5rem",
    "spacing_xl": "2.25rem",
    "radius_sm": "6px",
    "radius_md": "10px",
    "radius_lg": "16px",
    "shadow_surface": "0 16px 38px rgba(2, 8, 19, 0.24)",
    "focus_ring": "0 0 0 3px rgba(79, 156, 255, 0.34)",
}


STATIC_STYLES = f"""
<style>
:root {{
  color-scheme: dark;
  --stocktool-app: {DESIGN_TOKENS['app_background']};
  --stocktool-surface: {DESIGN_TOKENS['surface']};
  --stocktool-surface-muted: {DESIGN_TOKENS['surface_muted']};
  --stocktool-surface-alt: {DESIGN_TOKENS['surface_alt']};
  --stocktool-elevated: {DESIGN_TOKENS['surface_elevated']};
  --stocktool-primary: {DESIGN_TOKENS['primary']};
  --stocktool-primary-hover: {DESIGN_TOKENS['primary_hover']};
  --stocktool-accent: {DESIGN_TOKENS['accent']};
  --stocktool-success: {DESIGN_TOKENS['success']};
  --stocktool-warning: {DESIGN_TOKENS['warning']};
  --stocktool-error: {DESIGN_TOKENS['error']};
  --stocktool-info: {DESIGN_TOKENS['info']};
  --stocktool-border: {DESIGN_TOKENS['border']};
  --stocktool-border-strong: {DESIGN_TOKENS['border_strong']};
  --stocktool-text: {DESIGN_TOKENS['text']};
  --stocktool-muted: {DESIGN_TOKENS['muted']};
  --stocktool-subtle: {DESIGN_TOKENS['subtle']};
  --stocktool-font: {DESIGN_TOKENS['font_family']};
  --stocktool-radius-sm: {DESIGN_TOKENS['radius_sm']};
  --stocktool-radius-md: {DESIGN_TOKENS['radius_md']};
  --stocktool-radius-lg: {DESIGN_TOKENS['radius_lg']};
  --stocktool-shadow: {DESIGN_TOKENS['shadow_surface']};
  --stocktool-focus: {DESIGN_TOKENS['focus_ring']};
}}

html,
body,
.stApp,
div[data-testid="stAppViewContainer"] {{
  max-width: 100%;
  overflow-x: clip;
}}

.stApp,
div[data-testid="stAppViewContainer"] {{
  background: var(--stocktool-app);
  color: var(--stocktool-text);
  font-family: var(--stocktool-font);
}}

section[data-testid="stSidebar"] {{
  background: var(--stocktool-surface);
  border-right: 1px solid var(--stocktool-border);
}}
section[data-testid="stSidebar"] > div:first-child {{ padding: 1.25rem 1rem; }}
section[data-testid="stSidebar"] hr {{ border-color: var(--stocktool-border); }}
.stocktool-brand-link {{
  display: inline-flex;
  align-items: center;
  min-height: 2.4rem;
  color: var(--stocktool-text) !important;
  font-size: 1.5rem;
  font-weight: 700;
  line-height: 1.2;
  text-decoration: none !important;
}}
.stocktool-brand-link:focus-visible {{
  border-radius: 0.4rem;
  outline: 3px solid var(--stocktool-focus);
  outline-offset: 3px;
}}
.stocktool-main-anchor {{
  display: block;
  width: 0;
  height: 0;
  overflow: hidden;
}}
a[aria-label="Link to heading"] {{
  display: none !important;
}}

.main .block-container {{
  box-sizing: border-box;
  width: 100%;
  max-width: 1440px;
  margin-inline: auto;
  padding: 1.6rem clamp(1rem, 3vw, 3rem) 3rem;
}}

h1, h2, h3, h4 {{
  color: var(--stocktool-text);
  line-height: {DESIGN_TOKENS['line_height_heading']};
  letter-spacing: -0.015em;
  overflow-wrap: anywhere;
}}
h1 {{ font-size: {DESIGN_TOKENS['font_size_title']}; }}
p, label, small, [data-testid="stCaptionContainer"] {{
  line-height: {DESIGN_TOKENS['line_height_body']};
  overflow-wrap: anywhere;
}}
[data-testid="stCaptionContainer"] {{ color: var(--stocktool-muted); }}

/* StockTool workspace header: hierarchy comes from alignment and whitespace,
   not another heavy card. */
.st-ui-workspace-header {{
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: flex-end;
  gap: 1rem;
  min-width: 0;
  padding: 0.4rem 0 1.25rem;
  margin-bottom: 1rem;
  border-bottom: 1px solid var(--stocktool-border);
}}
.st-ui-workspace-header__copy,
.st-ui-workspace-header__meta,
.st-ui-section-header,
.st-ui-stat,
.st-ui-state-panel__copy {{ min-width: 0; }}
.st-ui-workspace-header h1 {{
  margin: 0.1rem 0 0.45rem;
  font-size: {DESIGN_TOKENS['font_size_title']};
}}
.st-ui-workspace-header p {{ margin: 0; color: var(--stocktool-muted); }}
.st-ui-workspace-header__meta {{
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: 0.35rem 0.65rem;
  text-align: right;
}}
.st-ui-as-of-label {{ color: var(--stocktool-subtle); font-size: 0.76rem; }}
.st-ui-as-of-value {{ color: var(--stocktool-text); font-size: 0.9rem; white-space: nowrap; }}
.st-ui-eyebrow {{
  color: var(--stocktool-accent) !important;
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.11em;
}}
.st-ui-badge {{
  display: inline-flex;
  align-items: center;
  width: fit-content;
  min-height: 1.8rem;
  padding: 0.24rem 0.65rem;
  border: 1px solid currentColor;
  border-radius: 999px;
  font-size: 0.78rem;
  font-weight: 700;
  white-space: nowrap;
}}

/* Native Streamlit form stays interactive; only its layout and surface change. */
.st-key-home_command_panel {{
  box-sizing: border-box;
  min-width: 0;
  max-width: 100%;
  padding: 1.2rem 1.25rem 1.1rem;
  margin-bottom: 1.5rem;
  background: var(--stocktool-surface);
  border: 1px solid var(--stocktool-border);
  border-radius: var(--stocktool-radius-lg);
  box-shadow: var(--stocktool-shadow);
}}
.st-ui-command-panel {{ min-width: 0; }}
.st-ui-section-header {{ margin-bottom: 0.8rem; }}
.st-ui-section-header h2 {{ margin: 0.1rem 0 0.35rem; font-size: 1.22rem; }}
.st-ui-section-header p {{ margin: 0; color: var(--stocktool-muted); }}
.st-key-home_command_panel div[data-testid="stForm"] [data-testid="stVerticalBlock"] {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 11rem), 1fr));
  gap: 0.85rem;
  align-items: end;
}}
.st-key-home_command_panel div[data-testid="stFormSubmitButton"] {{ align-self: end; }}
.st-key-home_command_panel div[data-testid="stButton"] {{ width: fit-content; }}

.st-ui-stat-group {{ margin-top: 1rem; min-width: 0; }}
.st-ui-stat-group h3,
.st-ui-outcome-matrix h3 {{
  margin: 0 0 0.65rem;
  color: var(--stocktool-muted);
  font-size: 0.82rem;
  font-weight: 700;
  letter-spacing: 0.03em;
}}
.st-ui-stat-grid {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 9rem), 1fr));
  gap: 0.75rem;
  min-width: 0;
}}
.st-ui-stat {{
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
  min-width: 0;
  box-sizing: border-box;
  padding: 0.75rem 0.85rem;
  background: var(--stocktool-surface-muted);
  border-top: 2px solid var(--stocktool-border-strong);
  border-radius: var(--stocktool-radius-md);
}}
.st-ui-stat-grid--primary .st-ui-stat {{
  min-height: 6rem;
  justify-content: center;
  background: var(--stocktool-surface-alt);
}}
.st-ui-stat__label {{ color: var(--stocktool-muted); font-size: 0.78rem; }}
.st-ui-stat__value {{
  color: var(--stocktool-text);
  font-size: clamp(1.05rem, 2vw, 1.55rem);
  font-variant-numeric: tabular-nums;
  overflow-wrap: anywhere;
}}
.st-ui-stat__detail {{ color: var(--stocktool-subtle); font-size: 0.74rem; }}

.st-ui-tone--neutral {{ color: var(--stocktool-muted); }}
.st-ui-tone--info {{ color: var(--stocktool-info); }}
.st-ui-tone--success {{ color: var(--stocktool-success); }}
.st-ui-tone--warning {{ color: var(--stocktool-warning); }}
.st-ui-tone--error {{ color: var(--stocktool-error); }}
.st-ui-stat.st-ui-tone--neutral {{ border-top-color: var(--stocktool-border-strong); }}
.st-ui-stat.st-ui-tone--info {{ border-top-color: var(--stocktool-info); }}
.st-ui-stat.st-ui-tone--success {{ border-top-color: var(--stocktool-success); }}
.st-ui-stat.st-ui-tone--warning {{ border-top-color: var(--stocktool-warning); }}
.st-ui-stat.st-ui-tone--error {{ border-top-color: var(--stocktool-error); }}

.st-ui-state-panel {{
  display: grid;
  grid-template-columns: 3px minmax(0, 1fr);
  gap: 0.85rem;
  min-width: 0;
  margin: 0.75rem 0 1rem;
  padding: 0.8rem 0.95rem;
  background: var(--stocktool-surface-muted);
  border: 1px solid var(--stocktool-border);
  border-radius: var(--stocktool-radius-md);
}}
.st-ui-state-panel__marker {{ border-radius: 99px; background: currentColor; }}
.st-ui-state-panel strong {{ color: currentColor; }}
.st-ui-state-panel p {{ margin: 0.18rem 0 0; color: var(--stocktool-muted); }}
.st-ui-state-panel__next span {{
  margin-right: 0.45rem;
  color: var(--stocktool-subtle);
  font-size: 0.74rem;
  font-weight: 700;
}}

.st-ui-danger-panel {{
  display: grid;
  grid-template-columns: 4px minmax(0, 1fr);
  gap: 0.85rem;
  min-width: 0;
  margin: 1rem 0;
  padding: 0.9rem 1rem;
  background: rgba(228, 119, 131, 0.08);
  border: 1px solid rgba(228, 119, 131, 0.35);
  border-radius: var(--stocktool-radius-md);
  color: var(--stocktool-error);
}}
.st-ui-danger-panel__marker {{ border-radius: 99px; background: var(--stocktool-error); }}
.st-ui-danger-panel strong {{ color: var(--stocktool-error); font-size: 0.95rem; }}
.st-ui-danger-panel p {{ margin: 0.2rem 0 0; color: var(--stocktool-muted); font-size: 0.88rem; }}
.st-ui-danger-panel__note {{ color: var(--stocktool-error) !important; font-size: 0.8rem; font-weight: 600; }}

.st-ui-action-banner {{
  min-width: 0;
  margin: 0.8rem 0 1.2rem;
  padding: 1rem 1.2rem;
  background: var(--stocktool-surface);
  border: 1px solid var(--stocktool-border);
  border-radius: var(--stocktool-radius-md);
}}
.st-ui-action-banner h3 {{ margin: 0 0 0.3rem; font-size: 1.05rem; }}
.st-ui-action-banner p {{ margin: 0; color: var(--stocktool-muted); font-size: 0.9rem; }}

.st-key-home_prediction_lab {{
  min-width: 0;
  margin: 1.8rem 0 0.5rem;
  padding: 1.2rem 1.25rem;
  background: var(--stocktool-surface);
  border: 1px solid var(--stocktool-border);
  border-left: 3px solid rgba(117, 215, 198, 0.62);
  border-radius: var(--stocktool-radius-lg);
}}
.st-ui-prediction-lab {{ min-width: 0; }}
.st-ui-prediction-buckets {{ min-width: 0; }}
.st-ui-outcome-matrix {{ margin-top: 1rem; min-width: 0; }}
.st-ui-outcome-grid {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 14rem), 1fr));
  gap: 0.75rem;
}}
.st-ui-outcome-row {{
  min-width: 0;
  padding: 0.8rem;
  background: var(--stocktool-surface-muted);
  border-radius: var(--stocktool-radius-md);
}}
.st-ui-outcome-row h4 {{ margin: 0 0 0.55rem; font-size: 0.86rem; }}
.st-ui-outcome-values {{
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.45rem;
}}
.st-ui-outcome-cell {{
  display: flex;
  justify-content: space-between;
  gap: 0.4rem;
  min-width: 0;
  padding: 0.42rem 0.5rem;
  background: var(--stocktool-surface-alt);
  border-radius: var(--stocktool-radius-sm);
}}
.st-ui-outcome-cell span {{ color: var(--stocktool-muted); font-size: 0.76rem; }}
.st-ui-outcome-cell strong {{ color: var(--stocktool-text); font-variant-numeric: tabular-nums; }}

/* Existing lower-page Streamlit columns wrap cleanly across all zoom levels */
div[data-testid="stHorizontalBlock"] {{
  flex-wrap: wrap !important;
  gap: 0.8rem;
  min-width: 0;
}}
div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"] {{
  flex: 1 1 min(100%, 12rem) !important;
  width: auto !important;
  min-width: 0 !important;
  box-sizing: border-box;
}}
div[data-testid="stMetric"] {{
  min-width: 0;
  box-sizing: border-box;
  padding: 0.7rem 0.8rem;
  background: var(--stocktool-surface-muted);
  border-bottom: 1px solid var(--stocktool-border);
  border-radius: var(--stocktool-radius-sm);
}}
div[data-testid="stMetricLabel"] p {{ color: var(--stocktool-muted); font-size: 0.78rem; }}
div[data-testid="stMetricValue"] {{ color: var(--stocktool-text); font-variant-numeric: tabular-nums; }}

div[data-testid="stVerticalBlockBorderWrapper"] {{
  min-width: 0;
  box-sizing: border-box;
  background: var(--stocktool-surface-muted);
  border: 1px solid var(--stocktool-border);
  border-radius: var(--stocktool-radius-md);
  box-shadow: none;
}}
div[data-testid="stButton"] > button,
div[data-testid="stDownloadButton"] > button {{
  min-height: 2.5rem;
  max-width: 100%;
  border: 1px solid var(--stocktool-border-strong);
  border-radius: var(--stocktool-radius-md);
  background: var(--stocktool-surface-alt);
  color: var(--stocktool-text);
  font-weight: 650;
  transition: background 120ms ease, border-color 120ms ease, transform 120ms ease;
}}
div[data-testid="stButton"] > button p,
div[data-testid="stDownloadButton"] > button p,
div[data-testid="stFormSubmitButton"] > button p {{
  white-space: nowrap;
  overflow: visible;
  text-overflow: clip;
}}
div[data-testid="stButton"] > button:hover,
div[data-testid="stDownloadButton"] > button:hover {{
  background: var(--stocktool-elevated);
  border-color: var(--stocktool-primary);
}}
div[data-testid="stButton"] > button:active,
div[data-testid="stDownloadButton"] > button:active {{ transform: translateY(1px); }}
div[data-testid="stButton"] > button[kind="primary"],
div[data-testid="stFormSubmitButton"] > button,
button[data-testid="stBaseButton-primaryFormSubmit"] {{
  background: var(--stocktool-primary) !important;
  border-color: var(--stocktool-primary) !important;
  color: #07101f !important;
}}
div[data-testid="stFormSubmitButton"] > button:hover,
button[data-testid="stBaseButton-primaryFormSubmit"]:hover {{
  background: var(--stocktool-primary-hover) !important;
  border-color: var(--stocktool-primary-hover) !important;
}}

div[data-testid="stAlert"] {{ border-radius: var(--stocktool-radius-md); border-left-width: 3px; }}
div[data-testid="stAlert"] > div {{
  background: var(--stocktool-surface-alt) !important;
  color: var(--stocktool-text) !important;
  border: 1px solid var(--stocktool-border);
}}
div[data-testid="stExpander"] {{
  border: 1px solid var(--stocktool-border);
  border-radius: var(--stocktool-radius-md);
  background: rgba(22, 34, 53, 0.52);
}}

input,
textarea,
div[data-baseweb="select"] > div {{
  max-width: 100%;
  border-radius: var(--stocktool-radius-md) !important;
  border-color: var(--stocktool-border-strong) !important;
  background: var(--stocktool-surface-alt) !important;
  color: var(--stocktool-text) !important;
}}
div[data-baseweb="select"] [role="option"] {{
  background: var(--stocktool-surface);
  color: var(--stocktool-text);
}}

button:focus-visible,
a:focus-visible,
input:focus-visible,
textarea:focus-visible,
[role="button"]:focus-visible,
[role="radio"]:focus-visible,
[role="option"]:focus-visible {{
  outline: 2px solid var(--stocktool-primary);
  outline-offset: 3px;
  box-shadow: var(--stocktool-focus);
}}

@media (max-width: 900px) {{
  .main .block-container {{ padding-inline: 1rem; }}
  .st-ui-workspace-header {{ flex-direction: column; align-items: flex-start; }}
  .st-ui-workspace-header__meta {{ justify-content: flex-start; text-align: left; }}
  .st-ui-badge {{ justify-self: flex-start; }}
  .st-ui-stat-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
}}

@media (max-width: 600px) {{
  .main .block-container {{ padding-top: 1rem; padding-bottom: 2rem; }}
  .st-key-home_command_panel {{ padding: 1rem; }}
  .st-ui-stat-grid,
  .st-ui-outcome-grid {{ grid-template-columns: minmax(0, 1fr); }}
  .st-ui-outcome-values {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
  div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"] {{ flex-basis: 100% !important; }}
}}
</style>
"""


def apply_dashboard_styles(st: Any) -> None:
    """Inject static, non-user-controlled style tokens for the Dashboard shell."""

    st.markdown(STATIC_STYLES, unsafe_allow_html=True)
