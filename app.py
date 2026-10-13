"""
FC Central — FCSC ERP (Revised Edition)
Crafted by Dibyo Chattopadhyay.

Master application entrypoint: bootstrap, authentication, sidebar, module router,
and all shared UI helpers (theme, weather, festival calendar, login scene,
notification bell, global search).
"""
from __future__ import annotations

__author__ = "Dibyo Chattopadhyay"

import base64
import datetime
import html
import logging
import os

import streamlit as st

from config import (
    FACTORIES, ALL_FACTORIES, UserRole,
    today_ist, now_ist, DATA_DIR, LOG_FILE,
)
from core.database import db
from core.security import verify_password, hash_password
from database.seeds.seed_master import run_seed
from repositories.user_repository import UserRepository

# UI Page Modules
from ui.pages import dashboard, sales, formulation, stores, production, quality, procurement, reports, admin

# ── Optional: outbound HTTP (weather + WhatsApp alerts) ─────────────────────
try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

# ── Optional: authorship signature ───────────────────────────────────────────
try:
    from fcsc_signature import (
        CREDIT_NAME as _CREDIT_NAME,
        credit_line as _credit_line,
        signature_html as _signature_html,
    )
except ImportError:
    _CREDIT_NAME = "Dibyo Chattopadhyay"

    def _credit_line() -> str:
        return f"FC Central | Crafted by {_CREDIT_NAME}"

    def _signature_html(**_kw) -> str:
        return (
            "<div style='text-align:center;margin-top:0.9rem;font-size:11px;"
            f"font-style:italic;opacity:.8;'>crafted by {_CREDIT_NAME}</div>"
        )


# ── Logging ───────────────────────────────────────────────────────────────────
DATA_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    filename=str(LOG_FILE),
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("fcsc_erp")


# =====================================================================
# 1. PAGE CONFIG
# =====================================================================
st.set_page_config(page_title="FC Central — FCSC ERP", layout="wide", page_icon="🏺")


# =====================================================================
# 2. DESIGN SYSTEM CSS (Base Layer)
# =====================================================================
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Cinzel:wght@500;600;700&family=Cormorant+Garamond:wght@500;600;700&family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@500;600&display=swap');

:root {
    --fc-canvas:      #F6F7F8;
    --fc-surface:     #FFFFFF;
    --fc-surface-alt: #FAFBFC;
    --fc-ink:         #14181F;
    --fc-ink-soft:    #4B5563;
    --fc-muted:       #8A93A1;
    --fc-border:      #E4E7EC;
    --fc-border-soft: #EEF0F3;

    --fc-accent:      #2B4C7E;
    --fc-accent-dark: #1F3B63;
    --fc-accent-soft: #EAF0F9;

    --fc-red:         #B3261E;
    --fc-red-soft:    #FBEAE9;
    --fc-amber:       #92600C;
    --fc-amber-soft:  #FBF1DE;
    --fc-green:       #1E6B45;
    --fc-green-soft:  #E7F4EE;
    --fc-blue:        #2B4C7E;
    --fc-blue-soft:   #EAF0F9;

    --fc-radius:    8px;
    --fc-radius-sm: 6px;
    --fc-shadow:    0 1px 2px rgba(20,24,31,0.05);
    --fc-shadow-md: 0 2px 8px rgba(20,24,31,0.08);

    --fc-font-ui:   'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    --fc-font-mono: 'JetBrains Mono', 'SFMono-Regular', Consolas, monospace;
}

html, body, [class*="css"] { font-family: var(--fc-font-ui); }
.main { background-color: var(--fc-canvas); }
.block-container { padding-top: 1.75rem !important; padding-bottom: 3rem !important; max-width: 1380px; }

[data-testid="stMetricValue"], .fc-num, td, .stDataFrame { font-variant-numeric: tabular-nums; }

*:focus-visible { outline: 2px solid var(--fc-accent) !important; outline-offset: 2px; }
@media (prefers-reduced-motion: reduce) { * { transition: none !important; animation: none !important; } }

::-webkit-scrollbar { width: 8px; height: 8px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: #D3D8DF; border-radius: 99px; }
::-webkit-scrollbar-thumb:hover { background: #B4BBC6; }

section[data-testid="stSidebar"] { background: #14181F; border-right: 1px solid #232833; }
section[data-testid="stSidebar"] * { color: #C7CCD6 !important; }
section[data-testid="stSidebar"] h1 {
    color: #FFFFFF !important; font-family: var(--fc-font-ui) !important;
    font-size: 0.95rem !important; font-weight: 700 !important; letter-spacing: -0.01em;
    padding-bottom: 0.6rem; border-bottom: 1px solid #232833; margin-bottom: 0.6rem !important;
}
section[data-testid="stSidebar"] .stSelectbox label,
section[data-testid="stSidebar"] p { color: #7B8494 !important; font-size: 12px; }
section[data-testid="stSidebar"] div[data-testid="stRadio"] > div[role="radiogroup"] { gap: 1px; }
section[data-testid="stSidebar"] div[data-testid="stRadio"] label {
    border-radius: 4px !important; padding: 7px 10px !important; margin: 0 !important;
    border-left: 2px solid transparent; transition: background 0.12s;
}
section[data-testid="stSidebar"] div[data-testid="stRadio"] label:hover { background: rgba(255,255,255,0.05); }
section[data-testid="stSidebar"] div[data-testid="stRadio"] label:has(input:checked) {
    background: rgba(255,255,255,0.07); border-left-color: #6E9BE8;
}
section[data-testid="stSidebar"] div[data-testid="stRadio"] label:has(input:checked) p {
    color: #FFFFFF !important; font-weight: 600 !important;
}
section[data-testid="stSidebar"] hr { border-top: 1px solid #232833 !important; }

h1 { color: var(--fc-ink) !important; font-family: var(--fc-font-ui) !important;
     font-size: 1.5rem !important; font-weight: 700 !important; letter-spacing: -0.015em; }
h2 { color: var(--fc-ink) !important; font-family: var(--fc-font-ui) !important; font-size: 1.15rem !important; font-weight: 600 !important; }
h3 { color: var(--fc-ink) !important; font-family: var(--fc-font-ui) !important; font-size: 0.95rem !important; font-weight: 600 !important; }
[data-testid="stCaptionContainer"] { color: var(--fc-muted) !important; font-size: 12.5px !important; }

div[data-testid="metric-container"] {
    background: var(--fc-surface); border: 1px solid var(--fc-border);
    border-radius: var(--fc-radius); padding: 0.9rem 1.05rem;
}
div[data-testid="metric-container"] label {
    font-size: 11px !important; color: var(--fc-muted) !important;
    text-transform: uppercase; letter-spacing: 0.06em; font-weight: 600 !important;
}
div[data-testid="metric-container"] div[data-testid="stMetricValue"] {
    font-family: var(--fc-font-mono) !important; font-size: 1.4rem !important;
    font-weight: 600 !important; color: var(--fc-ink) !important;
}

.stButton > button {
    background: var(--fc-accent) !important; color: #FFFFFF !important;
    border: 1px solid var(--fc-accent) !important; border-radius: 6px !important;
    font-weight: 600 !important; font-size: 13.5px !important;
    box-shadow: none !important; transition: background 0.12s !important;
}
.stButton > button:hover { background: var(--fc-accent-dark) !important; border-color: var(--fc-accent-dark) !important; }
.stDownloadButton > button {
    border-radius: 6px !important; font-weight: 600 !important;
    border: 1px solid var(--fc-border) !important; background: var(--fc-surface) !important;
    color: var(--fc-ink-soft) !important; box-shadow: none !important;
}
.stDownloadButton > button:hover { border-color: var(--fc-accent) !important; color: var(--fc-accent) !important; }
button[kind="secondary"] {
    background: transparent !important; color: var(--fc-red) !important;
    border: 1px solid var(--fc-border) !important; font-size: 12.5px !important; box-shadow: none !important;
}
button[kind="secondary"]:hover { background: var(--fc-red-soft) !important; border-color: var(--fc-red) !important; }

.stTabs [data-baseweb="tab-list"] { gap: 4px; background: transparent; border-bottom: 1px solid var(--fc-border); padding: 0; }
.stTabs [data-baseweb="tab"] { border-radius: 0; padding: 0.5rem 0.85rem; font-size: 13px; font-weight: 500; color: var(--fc-muted); }
.stTabs [aria-selected="true"] { background: transparent !important; color: var(--fc-ink) !important; font-weight: 600 !important; box-shadow: inset 0 -2px 0 var(--fc-accent); }

.stTextInput input, .stNumberInput input, .stDateInput input, .stTextArea textarea {
    border-radius: 6px !important; border: 1px solid var(--fc-border) !important;
    font-size: 13.5px !important; transition: border-color 0.12s, box-shadow 0.12s;
}
.stTextInput input:focus, .stNumberInput input:focus, .stTextArea textarea:focus {
    border-color: var(--fc-accent) !important; box-shadow: 0 0 0 3px var(--fc-accent-soft) !important;
}
div[data-baseweb="select"] > div { border-radius: 6px !important; border-color: var(--fc-border) !important; }

.stAlert, .stSuccess, .stWarning, .stError, .stInfo {
    border-radius: var(--fc-radius-sm) !important; border: 1px solid var(--fc-border) !important; box-shadow: none !important;
}
.stSuccess { border-left: 3px solid var(--fc-green) !important; background: var(--fc-green-soft) !important; }
.stWarning { border-left: 3px solid var(--fc-amber) !important; background: var(--fc-amber-soft) !important; }
.stError   { border-left: 3px solid var(--fc-red)   !important; background: var(--fc-red-soft)   !important; }
.stInfo    { border-left: 3px solid var(--fc-blue)  !important; background: var(--fc-blue-soft)  !important; }

div[data-testid="stExpander"] { border: 1px solid var(--fc-border) !important; border-radius: var(--fc-radius) !important; box-shadow: none !important; overflow: hidden; }
div[data-testid="stExpander"] summary { font-weight: 600; font-size: 13px; color: var(--fc-ink); transition: background 0.12s; }
div[data-testid="stExpander"] summary:hover { background: var(--fc-surface-alt); }
div[data-testid="stDataFrame"] { border: 1px solid var(--fc-border) !important; border-radius: var(--fc-radius) !important; overflow: hidden; }
hr { border-top: 1px solid var(--fc-border); margin: 1.1rem 0; }

.fc-page-eyebrow { font-size: 11px; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase; color: var(--fc-muted); margin-bottom: 2px; }
.fc-page-sub { font-size: 13px; color: var(--fc-muted); margin-top: 2px; margin-bottom: 0; }
.fc-section-label { font-size: 11px; font-weight: 600; letter-spacing: 0.07em; text-transform: uppercase; color: var(--fc-muted); margin: 0 0 8px 0; }
.fc-pill { display:inline-flex; align-items:center; gap:5px; font-size:11.5px; font-weight:600; padding:2px 9px; border-radius:99px; line-height:1.7; }
.fc-pill.success { background: var(--fc-green-soft); color: var(--fc-green); }
.fc-pill.warning  { background: var(--fc-amber-soft); color: var(--fc-amber); }
.fc-pill.error    { background: var(--fc-red-soft);   color: var(--fc-red);   }
.fc-pill.info     { background: var(--fc-blue-soft);  color: var(--fc-blue);  }
.fc-divider-tight { border-top: 1px solid var(--fc-border); margin: 0.75rem 0; }
</style>
""", unsafe_allow_html=True)


# =====================================================================
# 3. ZOHO-STYLE SKIN (Visual overlay — no logic changed)
# =====================================================================
st.markdown("""
<style>
:root {
    --zk-navy:#151B30; --zk-navy-2:#1E2640; --zk-navy-hover:#262F50;
    --zk-blue:#2F6FED; --zk-blue-dark:#2559C4; --zk-blue-soft:#EAF1FE;
    --zk-canvas:#F3F5F9; --zk-card:#FFFFFF; --zk-head:#F8F9FC;
    --zk-line:#E6E9F0; --zk-ink:#1B2233; --zk-muted:#7A8499;
    --fc-accent:#2F6FED; --fc-accent-dark:#2559C4; --fc-accent-soft:#EAF1FE;
    --fc-blue:#2F6FED; --fc-blue-soft:#EAF1FE;
    --fc-canvas:#F3F5F9; --fc-radius:12px;
}
.stApp { background: var(--zk-canvas) !important; }
.block-container { max-width: 1480px; padding-top: 1.4rem !important; }
header[data-testid="stHeader"] { background: var(--zk-navy) !important; height: 3rem; border-bottom: 1px solid #232B47; }
header[data-testid="stHeader"] * { color: #C9D1E6 !important; }
.stDeployButton, [data-testid="stDeployButton"] { display: none !important; }

section[data-testid="stSidebar"] { background: var(--zk-navy) !important; border-right: 1px solid #232B47; }
section[data-testid="stSidebar"] div[data-testid="stRadio"] > div[role="radiogroup"] { gap: 2px; }
section[data-testid="stSidebar"] div[data-testid="stRadio"] label > div:first-child:not([data-testid="stMarkdownContainer"]) { display: none !important; }
section[data-testid="stSidebar"] div[data-testid="stRadio"] label {
    border-radius: 10px !important; padding: 9px 12px !important; border-left: 0 !important; width: 100%; transition: background .12s;
}
section[data-testid="stSidebar"] div[data-testid="stRadio"] label p { font-size: 13.5px !important; font-weight: 500; }
section[data-testid="stSidebar"] div[data-testid="stRadio"] label:hover { background: var(--zk-navy-hover) !important; }
section[data-testid="stSidebar"] div[data-testid="stRadio"] label:has(input:checked) {
    background: var(--zk-navy-2) !important; box-shadow: inset 3px 0 0 var(--zk-blue);
}
section[data-testid="stSidebar"] div[data-testid="stRadio"] label:has(input:checked) p { color: #FFFFFF !important; font-weight: 600 !important; }

h1 { font-size: 1.65rem !important; color: var(--zk-ink) !important; letter-spacing: -0.02em; margin-bottom: .4rem !important; }
.stTabs [data-baseweb="tab-list"] { gap: 6px; border-bottom: 1px solid var(--zk-line); }
.stTabs [data-baseweb="tab"] { padding: .65rem 1rem; font-size: 14px; font-weight: 500; color: #4A5470; }
.stTabs [data-baseweb="tab"]:hover { color: var(--zk-blue); background: transparent; }
.stTabs [aria-selected="true"] { color: var(--zk-blue) !important; box-shadow: inset 0 -3px 0 var(--zk-blue) !important; font-weight: 600 !important; }

div[data-testid="metric-container"] {
    background: var(--zk-card); border: 1px solid var(--zk-line); border-radius: 12px;
    padding: 1rem 1.15rem; box-shadow: 0 1px 3px rgba(21,27,48,.05);
}
div[data-testid="metric-container"] div[data-testid="stMetricValue"] {
    font-family: var(--fc-font-ui) !important; font-weight: 600 !important; font-size: 1.55rem !important; color: var(--zk-ink) !important;
}
div[data-testid="stExpander"] { background: var(--zk-card); border: 1px solid var(--zk-line) !important; border-radius: 12px !important; }
div[data-testid="stExpander"] summary { background: var(--zk-head); padding: .7rem 1rem; }
div[data-testid="stDataFrame"] { border: 1px solid var(--zk-line) !important; border-radius: 12px !important; background: var(--zk-card); }

.stButton > button { background: var(--zk-blue) !important; border-color: var(--zk-blue) !important; border-radius: 8px !important; }
.stButton > button:hover { background: var(--zk-blue-dark) !important; border-color: var(--zk-blue-dark) !important; }
.stTextInput input, .stNumberInput input, .stDateInput input, .stTextArea textarea, div[data-baseweb="select"] > div {
    border-radius: 8px !important; border-color: #D9DEE9 !important; background: #FFFFFF;
}
.stAlert, .stSuccess, .stWarning, .stError, .stInfo { border-radius: 10px !important; }
.stInfo { background: #EEF4FF !important; border-left-color: var(--zk-blue) !important; }
/* Sidebar select: the global select rule paints it white while sidebar text is forced light. */
section[data-testid="stSidebar"] div[data-baseweb="select"] > div { background: var(--zk-navy-2) !important; border-color: #2E3860 !important; }
</style>
""", unsafe_allow_html=True)


# =====================================================================
# 4. MODULE ICONS
# =====================================================================
_MODULE_ICONS = {
    "Dashboard":              "🏠",
    "Commercial & Sales":     "🛍️",
    "Formulation & R&D":      "🧪",
    "Stores & Raw Materials": "📦",
    "Production Execution":   "⚙️",
    "Quality Control":        "✅",
    "Procurement":            "🛒",
    "Reports & Traceability": "📑",
    "System Administration":  "🔧",
}

MODULES = [
    "Dashboard",
    "Commercial & Sales",
    "Formulation & R&D",
    "Stores & Raw Materials",
    "Production Execution",
    "Quality Control",
    "Procurement",
    "Reports & Traceability",
    "System Administration",
]


# =====================================================================
# 5. SKELETON LOADERS
# =====================================================================
_SKELETON_CSS = """
<style>
@keyframes fcsc-shimmer { 0%{background-position:-400px 0} 100%{background-position:400px 0} }
.fcsc-skel { background:linear-gradient(90deg,#EFE4CC 25%,#E2D4B8 37%,#EFE4CC 63%);
    background-size:400px 100%; animation:fcsc-shimmer 1.3s ease-in-out infinite; border-radius:8px; }
.fcsc-skel-row { display:flex; gap:10px; margin:4px 0 10px; }
.fcsc-skel-card { flex:1; min-width:120px; height:76px; border:1px solid #E2D4B8; }
.fcsc-skel-line { height:13px; margin-bottom:9px; }
</style>
"""

def show_skeleton_cards(count: int = 5):
    placeholder = st.empty()
    cards = "".join("<div class='fcsc-skel fcsc-skel-card'></div>" for _ in range(count))
    placeholder.markdown(f"{_SKELETON_CSS}<div class='fcsc-skel-row'>{cards}</div>", unsafe_allow_html=True)
    return placeholder


# =====================================================================
# 6. WEATHER (optional — Open-Meteo, no API key)
# =====================================================================
FACTORY_COORDS = {
    "Belda":    (22.0600, 87.3200),
    "Mogra":    (22.8500, 88.1300),
    "Singur":   (22.7800, 88.0300),
    "Siliguri": (26.7271, 88.3953),
}
_WMO_ICON = {
    0: ("☀️","Clear sky"), 1: ("🌤️","Mainly clear"), 2: ("⛅","Partly cloudy"),
    3: ("☁️","Overcast"), 45: ("🌫️","Fog"), 51: ("🌦️","Drizzle"),
    61: ("🌧️","Rain"), 63: ("🌧️","Rain"), 65: ("🌧️","Heavy rain"),
    80: ("🌦️","Rain showers"), 95: ("⛈️","Thunderstorm"),
    48: ("🌫️","Rime fog"), 53: ("🌦️","Drizzle"), 55: ("🌧️","Heavy drizzle"),
    56: ("🌧️","Freezing drizzle"), 57: ("🌧️","Freezing drizzle"),
    66: ("🌧️","Freezing rain"), 67: ("🌧️","Freezing rain"),
    81: ("🌧️","Heavy showers"), 82: ("⛈️","Violent showers"),
    96: ("⛈️","Thunderstorm, hail"), 99: ("⛈️","Severe thunderstorm"),
}

def _weather_icon(code) -> tuple[str, str]:
    try:
        return _WMO_ICON.get(int(code), ("🌡️", "—"))
    except (TypeError, ValueError):
        return ("🌡️", "—")

@st.cache_data(ttl=1800, show_spinner=False)
def fetch_factory_weather(lat: float, lon: float) -> dict | None:
    if not HAS_REQUESTS:
        return None
    try:
        resp = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat, "longitude": lon,
                "current": "temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m",
                "hourly": "visibility,precipitation_probability",
                "timezone": "Asia/Kolkata", "forecast_days": 1,
            },
            timeout=(5, 10),
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        cur_d, hourly = data.get("current", {}), data.get("hourly", {})
        idx = 0
        _times = hourly.get("time", [])
        # current.time is 15-minute resolution ("...T14:45"); hourly slots are on the
        # hour, so truncate or the lookup never matches and hour 0 is used all day.
        _cur_hour = (cur_d.get("time") or "")[:13] + ":00"
        if _cur_hour in _times:
            idx = _times.index(_cur_hour)
        _vis  = hourly.get("visibility", [])
        _rain = hourly.get("precipitation_probability", [])
        icon, label = _weather_icon(cur_d.get("weather_code", 0))
        return {
            "temp": cur_d.get("temperature_2m"),
            "feels_like": cur_d.get("apparent_temperature"),
            "humidity": cur_d.get("relative_humidity_2m"),
            "wind_speed": cur_d.get("wind_speed_10m"),
            "rain_chance": _rain[idx] if idx < len(_rain) else None,
            "visibility_km": round(_vis[idx] / 1000, 1) if idx < len(_vis) and _vis[idx] is not None else None,
            "icon": icon, "label": label,
        }
    except Exception as e:
        logger.warning("Weather fetch failed (%s,%s): %s: %s", lat, lon, type(e).__name__, e)
        return None

def generate_weather_tip(w: dict | None) -> tuple[str, str] | None:
    if not w or w.get("temp") is None:
        return None
    rain, vis, wind, temp, hum = w.get("rain_chance"), w.get("visibility_km"), w.get("wind_speed"), w.get("temp"), w.get("humidity")
    if rain is not None and rain >= 60:
        return ("warning", f"🌧️ {rain:.0f}% rain — cover outdoor sand/cement stock & check drainage")
    if vis is not None and vis < 2:
        return ("warning", f"🌫️ Low visibility ({vis:.1f} km) — caution for dispatch vehicles")
    if wind is not None and wind >= 30:
        return ("warning", f"🌬️ Strong winds ({wind:.0f} km/h) — secure loose packaging")
    if temp is not None and temp >= 38:
        return ("warning", f"🌡️ Very hot ({temp:.0f}°C) — schedule hydration breaks")
    if hum is not None and hum >= 85:
        return ("info", f"💧 High humidity ({hum:.0f}%) — extra care for moisture-sensitive powders")
    if rain is not None and rain >= 30:
        return ("info", f"🌦️ Rain possible ({rain:.0f}%) — keep tarpaulins ready")
    return None

def render_weather_advisory(scope_factory: str | None) -> None:
    if not HAS_REQUESTS:
        return
    targets = [scope_factory] if scope_factory else list(FACTORY_COORDS.keys())
    lines = []
    for fac in targets:
        coords = FACTORY_COORDS.get(fac)
        if not coords:
            continue
        tip = generate_weather_tip(fetch_factory_weather(*coords))
        if tip:
            severity, msg = tip
            lines.append((severity, f"**{fac}** — {msg}" if not scope_factory else msg))
    if not lines:
        return
    st.markdown("**🌦️ Weather Advisory**")
    for severity, msg in lines:
        (st.warning if severity == "warning" else st.info)(msg)

def render_weather_strip() -> None:
    if not HAS_REQUESTS:
        return
    st.markdown("""
    <style>
    .fcsc-weather-row { display:flex; gap:10px; flex-wrap:wrap; justify-content:center; max-width:920px; margin:0 auto 0.4rem; position:relative; z-index:1; }
    .fcsc-weather-card { flex:1; min-width:175px; max-width:215px;
        background:linear-gradient(180deg,#FFFBF2 0%,#FBF3E4 100%);
        border:1px solid #EFE4CC; border-top:3px solid #6E1423;
        border-radius:10px; padding:12px 14px; box-shadow:0 4px 14px -8px rgba(28,18,13,0.15); }
    .fcsc-weather-fac { font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:0.06em; color:#8C7B62; margin-bottom:4px; }
    .fcsc-weather-main { display:flex; align-items:center; gap:8px; margin-bottom:8px; }
    .fcsc-weather-temp { font-family:'JetBrains Mono',monospace; font-size:22px; font-weight:700; color:#241812; }
    .fcsc-weather-label { font-size:11px; color:#5C4632; }
    .fcsc-weather-grid { display:grid; grid-template-columns:1fr 1fr; gap:3px 8px; font-size:11px; color:#5C4632; }
    .fcsc-weather-grid b { color:#241812; font-family:'JetBrains Mono',monospace; }
    .fcsc-weather-unavailable { font-size:11px; color:#C4B393; text-align:center; padding:14px 0; }
    .fcsc-weather-tip { margin-top:8px; padding:6px 8px; border-radius:6px; font-size:10.5px; line-height:1.35; font-weight:600; }
    .fcsc-weather-tip.warning { background:#F6E6E4; color:#4A0D18; }
    .fcsc-weather-tip.info    { background:#F5E9D0; color:#6B4413; }
    </style>
    """, unsafe_allow_html=True)

    skel = show_skeleton_cards(count=4)
    cards = []
    for fac_name, (lat, lon) in FACTORY_COORDS.items():
        w = fetch_factory_weather(lat, lon)
        if not w or w.get("temp") is None:
            cards.append(
                f"<div class='fcsc-weather-card'><div class='fcsc-weather-fac'>🏭 {fac_name}</div>"
                f"<div class='fcsc-weather-unavailable'>Weather unavailable</div></div>"
            )
            continue
        rain  = f"{w['rain_chance']:.0f}%" if w['rain_chance'] is not None else "—"
        vis   = f"{w['visibility_km']:.1f} km" if w['visibility_km'] is not None else "—"
        wind  = f"{w['wind_speed']:.0f} km/h" if w['wind_speed'] is not None else "—"
        hum   = f"{w['humidity']:.0f}%" if w['humidity'] is not None else "—"
        feels = f"{w['feels_like']:.0f}°" if w['feels_like'] is not None else "—"
        tip = generate_weather_tip(w)
        tip_html = f"<div class='fcsc-weather-tip {tip[0]}'>{tip[1]}</div>" if tip else ""
        cards.append(
            f"<div class='fcsc-weather-card'>"
            f"<div class='fcsc-weather-fac'>🏭 {fac_name}</div>"
            f"<div class='fcsc-weather-main'><span style='font-size:22px;'>{w['icon']}</span>"
            f"<div><div class='fcsc-weather-temp'>{w['temp']:.0f}°C</div>"
            f"<div class='fcsc-weather-label'>{w['label']} · feels {feels}</div></div></div>"
            f"<div class='fcsc-weather-grid'>"
            f"<span>💧 Humidity</span><b>{hum}</b><span>🌬️ Wind</span><b>{wind}</b>"
            f"<span>👁️ Visibility</span><b>{vis}</b><span>🌧️ Rain</span><b>{rain}</b>"
            f"</div>{tip_html}</div>"
        )
    skel.empty()
    st.markdown(f"<div class='fcsc-weather-row'>{''.join(cards)}</div>", unsafe_allow_html=True)


# =====================================================================
# 7. FESTIVAL / HOLIDAY CALENDAR (West Bengal 2026)
# =====================================================================
WB_FESTIVALS_2026 = [
    {"start": "2026-01-01", "end": "2026-01-01", "name": "New Year's Day",                  "emoji": "🎉", "closes_factory": True},
    {"start": "2026-01-12", "end": "2026-01-12", "name": "Swami Vivekananda Jayanti",        "emoji": "🪔", "closes_factory": True},
    {"start": "2026-01-23", "end": "2026-01-23", "name": "Netaji Jayanti & Saraswati Puja", "emoji": "📚", "closes_factory": True},
    {"start": "2026-01-26", "end": "2026-01-26", "name": "Republic Day",                     "emoji": "🇮🇳", "closes_factory": True},
    {"start": "2026-08-15", "end": "2026-08-15", "name": "Independence Day",                 "emoji": "🇮🇳", "closes_factory": True},
    {"start": "2026-09-17", "end": "2026-09-17", "name": "Vishwakarma Puja",                 "emoji": "🛠️", "closes_factory": True,
     "note": "Machinery is worshipped; the production line is typically idle."},
    {"start": "2026-10-02", "end": "2026-10-02", "name": "Gandhi Jayanti",                   "emoji": "🕊️", "closes_factory": True},
    {"start": "2026-10-10", "end": "2026-10-10", "name": "Mahalaya",                         "emoji": "🪔", "closes_factory": False},
    {"start": "2026-10-15", "end": "2026-10-24", "name": "Durga Puja",                       "emoji": "🎊", "closes_factory": True,
     "note": "The year's longest break — Maha Chaturthi through the post-Dashami holidays."},
    {"start": "2026-10-26", "end": "2026-10-26", "name": "Lakshmi Puja",                     "emoji": "🪔", "closes_factory": True},
    {"start": "2026-11-08", "end": "2026-11-10", "name": "Kali Puja / Diwali",               "emoji": "🪔", "closes_factory": True},
    {"start": "2026-11-11", "end": "2026-11-11", "name": "Bhai Phonta",                      "emoji": "🎀", "closes_factory": True},
    {"start": "2026-12-25", "end": "2026-12-25", "name": "Christmas",                        "emoji": "🎄", "closes_factory": True},
]

def _parse_iso_date(d: str) -> datetime.date:
    return datetime.datetime.strptime(d, "%Y-%m-%d").date()

def get_festival_banner_info(within_days: int = 10) -> dict | None:
    today = today_ist()
    ongoing, upcoming = [], []
    for f in WB_FESTIVALS_2026:
        start, end = _parse_iso_date(f["start"]), _parse_iso_date(f["end"])
        if start <= today <= end:
            ongoing.append((start, f))
        elif start > today and (start - today).days <= within_days:
            upcoming.append((start, f))
    if ongoing:
        _, f = min(ongoing, key=lambda x: x[0])
        return {**f, "status": "today"}
    if upcoming:
        start, f = min(upcoming, key=lambda x: x[0])
        return {**f, "status": "upcoming", "days_away": (start - today).days}
    return None

def render_festival_banner(compact: bool = False) -> None:
    info = get_festival_banner_info()
    if info is None:
        return
    start_d, end_d = _parse_iso_date(info["start"]), _parse_iso_date(info["end"])
    span = start_d.strftime("%d %b") + (f"–{end_d.strftime('%d %b')}" if start_d != end_d else "")
    if info["status"] == "today":
        headline = f"{info['emoji']} {info['name']} — Today ({span})"
    else:
        days = info["days_away"]
        headline = f"{info['emoji']} {info['name']} — in {days} day{'s' if days != 1 else ''} ({span})"
    closure_note = "Factories closed" if info.get("closes_factory") else "Widely observed — plan for lower attendance"
    detail = info.get("note", "")
    if compact:
        st.info(f"{headline} · {closure_note}" + (f" — {detail}" if detail else ""))
        return
    st.markdown(f"""
    <div style='max-width:920px;margin:0.6rem auto 0;padding:12px 18px;
        background:linear-gradient(90deg,#F7EEDD,#FFFBF2);
        border:1px solid #F0DEB8;border-left:4px solid #8C5A1B;
        border-radius:10px;box-shadow:0 4px 14px -8px rgba(28,18,13,0.12);'>
        <div style='font-weight:700;font-size:14px;color:#241812;'>{headline}</div>
        <div style='font-size:12px;color:#8C7B62;margin-top:2px;'>{closure_note}{f' — {detail}' if detail else ''}</div>
    </div>
    """, unsafe_allow_html=True)


# =====================================================================
# 8. DURGA PUJA LOGIN SCENE (in season only: Oct 10-26, Mahalaya to Lakshmi Puja)
# =====================================================================
def _is_puja_season() -> bool:
    today = today_ist()
    return (today.month == 10 and 10 <= today.day <= 26)

def _puja_rangoli_svg(uid: str, size: int = 300) -> str:
    petals = []
    for i in range(8):
        angle = i * 45
        petals.append(
            f"<g transform='rotate({angle} 150 150)'>"
            f"<path d='M150,150 Q172,88 150,34 Q128,88 150,150 Z' fill='none' stroke='#FFD666' stroke-width='1.4' opacity='0.75'/>"
            f"<circle cx='150' cy='48' r='4.5' fill='#FFD666' opacity='0.7'/>"
            f"</g>"
        )
    rings = (
        "<circle cx='150' cy='150' r='142' fill='none' stroke='#FFD666' stroke-width='1' stroke-dasharray='3 7' opacity='0.5'/>"
        "<circle cx='150' cy='150' r='98' fill='none' stroke='#D4AF37' stroke-width='1' opacity='0.45'/>"
        "<circle cx='150' cy='150' r='30' fill='none' stroke='#FFD666' stroke-width='1.6' opacity='0.75'/>"
        "<circle cx='150' cy='150' r='8' fill='#FFD666' opacity='0.65'/>"
    )
    return (
        f"<svg class='fcsc-puja-rangoli' id='{uid}' width='{size}' height='{size}' "
        f"viewBox='0 0 300 300' xmlns='http://www.w3.org/2000/svg'>{rings}{''.join(petals)}</svg>"
    )

def render_puja_scene() -> None:
    _css = """
<style>
.stApp { background: radial-gradient(ellipse 130% 90% at 50% 0%,
    #F0532E 0%,#D9301F 24%,#A81B2C 50%,#7A1220 72%,#4A0D18 100%) !important; }
.fcsc-puja-scene { position:fixed; inset:0; overflow:hidden; pointer-events:none; z-index:0; }
@keyframes fcsc-puja-skyline-drift { 0%{transform:translateX(-3%)} 100%{transform:translateX(3%)} }
.fcsc-puja-skyline { position:absolute; left:-5%; right:-5%; bottom:0; height:30%; display:flex;
    align-items:flex-end; gap:1.4%; filter:blur(1.5px); opacity:0.35;
    animation:fcsc-puja-skyline-drift 95s ease-in-out infinite alternate; }
.fcsc-puja-bldg { background:#4A0D18; border-radius:1px 1px 0 0; }
@keyframes fcsc-puja-glow-breathe { 0%,100%{opacity:.55} 50%{opacity:.9} }
.fcsc-puja-glow { position:absolute; left:50%; bottom:6%; width:52%; height:42%; transform:translateX(-50%);
    background:radial-gradient(ellipse at 50% 100%,rgba(255,214,130,.4) 0%,rgba(212,175,55,.18) 45%,rgba(212,175,55,0) 75%);
    filter:blur(8px); animation:fcsc-puja-glow-breathe 10s ease-in-out infinite; }
@keyframes fcsc-puja-rangoli-spin { from{transform:rotate(0deg)} to{transform:rotate(360deg)} }
.fcsc-puja-rangoli-wrap { position:absolute; pointer-events:none; }
.fcsc-puja-rangoli { animation-name:fcsc-puja-rangoli-spin; animation-timing-function:linear; animation-iteration-count:infinite; }
@keyframes fcsc-puja-light-pulse { 0%,100%{opacity:.55;transform:scale(.9)} 50%{opacity:1;transform:scale(1.15)} }
.fcsc-puja-lightline { position:absolute; top:3%; left:0; width:100%; height:60px; }
.fcsc-puja-bulb { position:absolute; width:9px; height:9px; border-radius:50%;
    background:radial-gradient(circle,#FFFBEA 0%,#FFD666 45%,rgba(255,214,102,0) 100%);
    box-shadow:0 0 12px 3px rgba(255,214,102,.75);
    animation-name:fcsc-puja-light-pulse; animation-timing-function:ease-in-out; animation-iteration-count:infinite; }
@keyframes fcsc-puja-diya-flicker { 0%,100%{opacity:.65} 45%{opacity:.95} 80%{opacity:1} }
.fcsc-puja-diya { position:absolute; bottom:2%; width:20px; height:20px; border-radius:50%;
    background:radial-gradient(circle,rgba(255,235,180,.95) 0%,rgba(255,153,51,.7) 50%,rgba(255,153,51,0) 100%);
    filter:blur(2px); animation-name:fcsc-puja-diya-flicker; animation-timing-function:ease-in-out; animation-iteration-count:infinite; }
@keyframes fcsc-puja-particle-float { 0%{transform:translate(0,0);opacity:0} 12%{opacity:.6} 88%{opacity:.35} 100%{transform:translate(18px,-92vh);opacity:0} }
.fcsc-puja-particle { position:absolute; bottom:0; border-radius:50%;
    background:radial-gradient(circle,rgba(255,244,214,.9) 0%,rgba(255,244,214,0) 70%);
    animation-name:fcsc-puja-particle-float; animation-timing-function:linear; animation-iteration-count:infinite; }
.fcsc-puja-vignette { position:absolute; inset:0;
    background:radial-gradient(ellipse 46% 62% at 50% 40%,rgba(15,8,5,.5) 0%,rgba(15,8,5,.2) 55%,rgba(15,8,5,0) 80%); }
.fcsc-puja-alpana { position:absolute; left:0; right:0; bottom:0; height:4px; opacity:.75;
    background:repeating-linear-gradient(90deg,#FFD666 0,#FFD666 6px,transparent 6px,transparent 12px,
        #FFFBF2 12px,#FFFBF2 15px,transparent 15px,transparent 21px,#D4AF37 21px,#D4AF37 27px,transparent 27px,transparent 33px); }
</style>
"""
    buildings = "".join(
        f"<div class='fcsc-puja-bldg' style='width:{22+(i%4)*9}px;height:{40+(i*13)%60}%;'></div>"
        for i in range(16)
    )
    _rgl1 = _puja_rangoli_svg("rgl1", 320).replace("id='rgl1'", "id='rgl1' style='animation-duration:150s;'")
    _rgl2 = _puja_rangoli_svg("rgl2", 360).replace("id='rgl2'", "id='rgl2' style='animation-duration:210s;'")
    rangoli = (
        f"<div class='fcsc-puja-rangoli-wrap' style='top:-70px;left:-70px;opacity:.28;'>{_rgl1}</div>"
        f"<div class='fcsc-puja-rangoli-wrap' style='bottom:-90px;right:-90px;opacity:.24;'>{_rgl2}</div>"
    )
    bulbs = "".join(
        f"<span class='fcsc-puja-bulb' style='left:{i*(100/21):.1f}%;top:{4+10*abs(i/21-0.5)*2:.1f}px;"
        f"animation-duration:{3.2+(i%5)*0.5:.2f}s;animation-delay:{(i%7)*0.4:.2f}s;'></span>"
        for i in range(22)
    )
    diyas = "".join(
        f"<span class='fcsc-puja-diya' style='left:{2+(i*7)%96}%;animation-duration:{3.0+(i%4)*0.7:.2f}s;animation-delay:{(i%6)*0.5:.2f}s;'></span>"
        for i in range(14)
    )
    particles = "".join(
        f"<span class='fcsc-puja-particle' style='left:{(i*13)%100}%;width:{2+(i%3)}px;height:{2+(i%3)}px;"
        f"animation-duration:{13+(i%6)*2.2:.1f}s;animation-delay:{(i%9)*1.6:.1f}s;'></span>"
        for i in range(18)
    )
    st.markdown(
        f"{_css}<div class='fcsc-puja-scene'>"
        f"<div class='fcsc-puja-skyline'>{buildings}</div>"
        f"<div class='fcsc-puja-glow'></div>{rangoli}"
        f"<div class='fcsc-puja-lightline'>{bulbs}</div>{diyas}{particles}"
        f"<div class='fcsc-puja-vignette'></div><div class='fcsc-puja-alpana'></div>"
        f"</div>",
        unsafe_allow_html=True,
    )


# =====================================================================
# 9. LOGO LOADER
# =====================================================================
@st.cache_data
def _get_logo_data_uri() -> str | None:
    _script_dir = os.path.dirname(os.path.abspath(__file__))
    for _logo_path in [
        os.path.join(_script_dir, "assets", "fcsc_logo.png"),
        os.path.join(_script_dir, "fcsc_logo.png"),
    ]:
        try:
            with open(_logo_path, "rb") as f:
                return f"data:image/png;base64,{base64.b64encode(f.read()).decode()}"
        except Exception:
            continue
    return None


# =====================================================================
# 10. DATABASE BOOTSTRAP (runs once via st.cache_resource)
# =====================================================================
@st.cache_resource
def _bootstrap() -> bool:
    migrations_dir = os.path.join(os.path.dirname(__file__), "database", "migrations")
    db.apply_migrations(migrations_dir)
    run_seed(db)
    return True

_bootstrap()

user_repo = UserRepository(db)


# =====================================================================
# 11. SESSION STATE INIT + INACTIVITY TIMEOUT
# =====================================================================
if "logged_in" not in st.session_state:
    st.session_state.logged_in        = False
    st.session_state.username         = ""
    st.session_state.display_name     = ""
    st.session_state.role             = ""
    st.session_state.factory          = None
    st.session_state.department       = ""
    st.session_state.must_change_pwd  = False
    st.session_state.last_activity    = now_ist()

if st.session_state.logged_in:
    _now = now_ist()
    if (_now - st.session_state.last_activity).total_seconds() > 7200:
        for _k in list(st.session_state.keys()):
            del st.session_state[_k]
        st.rerun()
    else:
        st.session_state.last_activity = _now
        # Re-read the account every run so deactivation / role / plant changes made by an
        # admin apply immediately, not only after the user logs out or times out.
        _fresh = user_repo.get_user_by_username(st.session_state.username)
        if _fresh is None or not getattr(_fresh, "is_active", True):
            for _k in list(st.session_state.keys()):
                del st.session_state[_k]
            st.rerun()
        st.session_state.role         = _fresh.role
        st.session_state.department   = _fresh.department
        st.session_state.factory      = _fresh.factory
        st.session_state.display_name = _fresh.display_name


# =====================================================================
# 12. LOGIN PAGE
# =====================================================================
def show_login_page() -> None:
    if _is_puja_season():
        render_puja_scene()
    st.markdown("""
    <style>
    section[data-testid="stSidebar"] { display:none; }
    div[data-testid="stToolbar"]     { display:none; }
    .fcsc-login-wrap { display:flex; justify-content:center; padding:2rem 0 1rem; position:relative; z-index:1; }
    .fcsc-login-card {
        width:100%; max-width:490px; position:relative;
        background:linear-gradient(180deg,#1C120D 0%,#241811 100%);
        border:1.5px solid rgba(184,134,11,.6); border-radius:6px;
        padding:2.2rem 2.2rem 1.6rem;
        box-shadow:0 24px 60px -20px rgba(0,0,0,.7),0 2px 10px rgba(0,0,0,.4);
    }
    .fcsc-login-card::before { content:""; position:absolute; inset:8px;
        border:1px solid rgba(212,175,55,.35); border-radius:3px; pointer-events:none; }
    .fcsc-logo-img { display:block; width:100%; max-width:100%; height:auto; margin:0 auto 0.6rem;
        border-radius:4px; filter:drop-shadow(0 4px 14px rgba(0,0,0,.55)); }
    .fcsc-brand-title { text-align:center; margin:0; font-family:'Cormorant Garamond',Georgia,serif; font-weight:700;
        font-size:2.2rem; letter-spacing:.02em; line-height:1.1; text-transform:uppercase; }
    .fcsc-brand-title .fc-strong { color:#D4AF37; }
    .fcsc-brand-title .fc-light  { color:#F1E4BE; font-weight:500; }
    .fcsc-brand-rule { width:56px; height:1px; margin:.9rem auto .85rem;
        background:linear-gradient(90deg,transparent,#D4AF37,transparent); }
    .fcsc-brand-tagline { text-align:center; font-family:'Cinzel',Georgia,serif; font-size:11px; font-weight:500; letter-spacing:.22em;
        text-transform:uppercase; color:#9C8A6E; margin:0 0 1.8rem; }
    .fcsc-form-label { text-align:center; font-family:'Cinzel',Georgia,serif; font-size:15px; font-weight:700; letter-spacing:.18em;
        text-transform:uppercase; color:#D4AF37; margin:1.2rem 0 1.1rem 0; }
    .fcsc-login-footer { text-align:center; font-size:11px; color:#8C7B62; margin-top:1.6rem;
        padding-top:1.1rem; border-top:1px solid rgba(184,134,11,.25); }
    .fcsc-login-company { text-align:center; font-size:11px; color:#9C8A6E; letter-spacing:.06em; margin-top:.35rem; }
    
    div[data-testid="stForm"] { border:none !important; padding:0 !important; background:transparent !important; }
    div[data-testid="stForm"] label p { color:#385A90 !important; font-size:13.5px !important; font-weight:600 !important; margin-bottom:2px !important; }
    div[data-testid="stForm"] .stTextInput input {
        background:#EAF0FA !important; border:1.5px solid #CBD5E1 !important;
        color:#0F172A !important; border-radius:8px !important;
        font-size:14.5px !important; font-weight:500 !important;
        padding:9px 14px !important; box-shadow:inset 0 1px 2px rgba(0,0,0,.04) !important;
    }
    div[data-testid="stForm"] .stTextInput input:focus {
        border-color:#2F6FED !important; background:#FFFFFF !important;
        box-shadow:0 0 0 3px rgba(47,111,237,.22) !important;
    }
    div[data-testid="stForm"] .stTextInput input::placeholder { color:#94A3B8 !important; }
    div[data-testid="stForm"] .stFormSubmitButton button {
        background:linear-gradient(180deg,#B8860B 0%,#8C5A1B 100%) !important;
        color:#1C120D !important; border:1px solid #D4AF37 !important;
        font-family:'Cinzel',Georgia,serif !important; font-weight:700 !important;
        letter-spacing:.12em !important; text-transform:uppercase !important; font-size:13.5px !important;
        border-radius:6px !important; padding:0.55rem 1rem !important; margin-top:0.5rem !important;
    }
    div[data-testid="stForm"] .stFormSubmitButton button:hover {
        background:linear-gradient(180deg,#D4AF37 0%,#B8860B 100%) !important;
        box-shadow:0 4px 16px rgba(184,134,11,.45) !important;
    }
    </style>
    """, unsafe_allow_html=True)

    _logo_uri = _get_logo_data_uri()
    if _logo_uri:
        _logo_html = f"<img src='{_logo_uri}' class='fcsc-logo-img' alt='FCSC logo'>"
    else:
        _logo_html = (
            "<div class='fcsc-brand-title'>"
            "<span class='fc-strong'>FC</span> <span class='fc-light'>CENTRAL</span></div>"
            "<div class='fcsc-brand-rule'></div>"
            "<p class='fcsc-brand-tagline'>Driving Operational Excellence</p>"
        )

    col_l, col_c, col_r = st.columns([1, 1.2, 1])
    with col_c:
        st.markdown(f"<div class='fcsc-login-wrap'><div class='fcsc-login-card'>{_logo_html}", unsafe_allow_html=True)
        st.markdown("<p class='fcsc-form-label'>SIGN IN TO YOUR ACCOUNT</p>", unsafe_allow_html=True)

        with st.form("login_form"):
            uname = st.text_input("Username", placeholder="Enter your username").strip().lower()
            pwd   = st.text_input("Password", type="password", placeholder="Enter your password")
            submitted = st.form_submit_button("🔐 Sign In", use_container_width=True)

        if submitted:
            locked, wait_sec = user_repo.is_account_locked(uname)
            if locked:
                st.error(f"🔒 Account locked. Retry in {wait_sec}s.")
            else:
                user = user_repo.get_user_by_username(uname)
                if user and verify_password(pwd, user.password_hash):
                    user_repo.reset_failed_attempts(uname)
                    st.session_state.logged_in       = True
                    st.session_state.username        = user.username
                    st.session_state.display_name    = user.display_name
                    st.session_state.role            = user.role
                    st.session_state.factory         = user.factory
                    st.session_state.department      = user.department
                    st.session_state.must_change_pwd = user.must_change_password
                    st.session_state.last_activity   = now_ist()
                    st.rerun()
                else:
                    attempts, lockout = user_repo.register_failed_attempt(uname)
                    remaining = max(0, 5 - attempts)
                    if lockout:
                        st.error("🔒 Account locked for 15 minutes after repeated failures.")
                    else:
                        st.error(f"Invalid username or password. {remaining} attempt(s) remaining.")

        st.markdown(f"""
            <div class='fcsc-login-footer'>
                Contact your administrator if you have trouble logging in.
                <div class='fcsc-login-company'>FIRSTCHOICE SPECIALITY CHEMICALS PVT. LTD.</div>
                {_signature_html(height_px=44, label_color="#B8860B")}
            </div></div></div>
        """, unsafe_allow_html=True)

    # Below the card: festival banner + weather strip
    render_festival_banner()
    st.markdown("<div style='height:0.6rem'></div>", unsafe_allow_html=True)
    render_weather_strip()


if not st.session_state.logged_in:
    show_login_page()
    st.stop()


# =====================================================================
# 13. FORCED PASSWORD CHANGE
# =====================================================================
if st.session_state.must_change_pwd:
    st.warning("🔒 **Temporary password detected.** Set a new password before continuing.")
    with st.form("pw_change_form"):
        p1 = st.text_input("New Password", type="password")
        p2 = st.text_input("Confirm New Password", type="password")
        if st.form_submit_button("Update Password & Continue", use_container_width=True):
            _cur = user_repo.get_user_by_username(st.session_state.username)
            if len(p1) < 8:
                st.error("Password must be at least 8 characters.")
            elif p1 != p2:
                st.error("Passwords do not match.")
            elif _cur and verify_password(p1, _cur.password_hash):
                st.error("Choose a password different from the temporary one.")
            else:
                user_repo.update_password(st.session_state.username, hash_password(p1))
                st.session_state.must_change_pwd = False
                st.success("Password updated. Loading ERP…")
                st.rerun()
    if st.button("Log out instead 🚪"):
        for _k in list(st.session_state.keys()):
            del st.session_state[_k]
        st.rerun()
    st.stop()


# =====================================================================
# 14. NOTIFICATION BELL
# =====================================================================
def render_notification_bell(is_admin: bool, user_factory: str | None) -> None:
    notes: list[dict] = []
    check_failed = False
    try:
        from services.inventory_service import InventoryService
        inv = InventoryService(db)
        alerts = inv.get_low_stock_alerts(factory=user_factory)
        if alerts:
            notes.append({"icon": "📉", "severity": "warning",
                          "text": f"{len(alerts)} material(s) below reorder threshold"})
    except Exception:
        check_failed = True
        logger.warning("Notification bell: low-stock check failed", exc_info=True)

    count = len(notes)
    label = f"🔔 ({count})" if count else ("🔔⚠️" if check_failed else "🔔")

    def _render_notes() -> None:
        if check_failed:
            st.warning("⚠️ Alerts could not be loaded — check the application log.")
        elif not notes:
            st.caption("✅ All clear — nothing needs attention right now.")
        for n in notes:
            (st.warning if n["severity"] == "warning" else st.info)(f"{n['icon']} {n['text']}")

    if hasattr(st, "popover"):
        with st.popover(label):
            _render_notes()
    else:
        with st.expander(label, expanded=False):
            _render_notes()


# =====================================================================
# 15. SIDEBAR NAVIGATION
# =====================================================================
is_admin = (st.session_state.role == UserRole.ADMIN.value)

with st.sidebar:
    # Brand mark
    st.markdown("### 🏺 FC Central")
    st.caption("Firstchoice Speciality Chemicals")

    # User identity card
    st.markdown(f"""
    <div style='background:rgba(255,255,255,0.08);padding:8px 12px;border-radius:8px;margin-bottom:12px;'>
        <div style='font-weight:600;font-size:14px;color:#fff;'>{html.escape(st.session_state.display_name)}</div>
        <div style='font-size:11px;color:#94A3B8;'>
            {html.escape(st.session_state.role.upper())} &middot; {html.escape(str(st.session_state.department))}
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Factory scope selector
    if is_admin:
        active_factory = st.selectbox("🏭 Plant Context", [ALL_FACTORIES] + FACTORIES, index=0, key="factory_selector")
    else:
        active_factory = st.session_state.factory or FACTORIES[0]
        st.markdown(f"**Plant:** `{active_factory}`")

    st.markdown("---")

    # Module navigation — labelled with icons from the reference
    visible_modules = [m for m in MODULES if is_admin or m != "System Administration"]
    module_labels = [f"{_MODULE_ICONS.get(m, '▸')} {m}" for m in visible_modules]
    selected_label = st.radio("Navigation", module_labels, index=0, key="module_radio", label_visibility="collapsed")
    selected_module = visible_modules[module_labels.index(selected_label)]

    st.markdown("---")

    # Notification bell
    render_notification_bell(is_admin, None if active_factory == ALL_FACTORIES else active_factory)

    st.markdown("---")

    # Festival/monsoon compact reminder
    render_festival_banner(compact=True)

    st.markdown("---")

    # Weather advisory for logged-in user's factory
    if not is_admin and st.session_state.factory:
        render_weather_advisory(st.session_state.factory)

    if st.button("Log out 🚪", use_container_width=True):
        for _k in list(st.session_state.keys()):
            del st.session_state[_k]
        st.rerun()

    # Authorship credit
    st.markdown(
        f"<div style='margin-top:1.5rem;font-size:10px;color:#4B5563;text-align:center;'>{_credit_line()}</div>",
        unsafe_allow_html=True,
    )


# =====================================================================
# 16. PAGE ROUTER
# =====================================================================
role = st.session_state.role
dept = st.session_state.department

if selected_module == "System Administration" and not is_admin:
    st.error("🚫 System Administration is restricted to administrators.")
    st.stop()

if selected_module == "Dashboard":
    dashboard.render(active_factory, role, dept)
elif selected_module == "Commercial & Sales":
    sales.render(active_factory, role, dept)
elif selected_module == "Formulation & R&D":
    formulation.render(active_factory, role, dept)
elif selected_module == "Stores & Raw Materials":
    stores.render(active_factory, role, dept)
elif selected_module == "Production Execution":
    production.render(active_factory, role, dept)
elif selected_module == "Quality Control":
    quality.render(active_factory, role, dept)
elif selected_module == "Procurement":
    procurement.render(active_factory, role, dept)
elif selected_module == "Reports & Traceability":
    reports.render(active_factory, role, dept)
elif selected_module == "System Administration":
    admin.render(active_factory, role, dept)