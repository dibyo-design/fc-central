import streamlit as st
import pandas as pd
import sqlite3
import datetime
import hashlib
import hmac
import os
import base64
import secrets
import logging
import threading
import shutil
import smtplib
import contextlib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from io import BytesIO

# ── optional: plotly preferred, bar_chart fallback ────────────────────────────
try:
    import plotly.express as px
    import plotly.graph_objects as go
    HAS_PLOTLY = True
except ImportError:
    HAS_PLOTLY = False

# ── optional: PDF generation (batch traceability certificates, invoices) ──────
try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                     TableStyle, Image as RLImage)
    HAS_REPORTLAB = True
except ImportError:
    HAS_REPORTLAB = False

# ── optional: QR codes on traceability certificates ──────────────────────────
try:
    import qrcode
    HAS_QRCODE = True
except ImportError:
    HAS_QRCODE = False

# ── optional: outbound HTTP for WhatsApp/SMS alerts via Twilio's REST API ─────
# Deliberately uses plain `requests` calls rather than the `twilio` SDK — one
# fewer hard dependency, and degrades the same way reportlab/qrcode do: the
# app still runs fully, this feature just quietly stays unavailable.
try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

# ================= LOGGING =================
# FIX: Errors that used to be silently swallowed (bare `except: pass`) are now
# recorded here so real bugs don't vanish. Doesn't stop the app from continuing.
logging.basicConfig(
    filename="fcsc_app.log",
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("fcsc_erp")

# ================= CONFIG =================
st.set_page_config(page_title="FCSC ERP", layout="wide", page_icon="🏺")

# ================= THEME =================
# Design system: one consistent "accent bar" language (top border on cards,
# left border on alerts, underline on active tabs, left border on the
# selected sidebar item) instead of scattered one-off decoration — the
# unifying signature is executing that single idea everywhere, not adding
# more motifs. Data-heavy numbers (metrics, batch/PR numbers) get a
# monospace face so figures line up and read like instrument readouts;
# everything else stays on Inter for legibility at factory-floor viewing
# distances. Both fonts fall back cleanly to system sans/monospace if the
# CDN import is blocked on a given network.
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@500;600&display=swap');

:root {
    /* Neutral surface scale — cool gray, not warm/decorative */
    --fc-canvas:      #F6F7F8;
    --fc-surface:     #FFFFFF;
    --fc-surface-alt: #FAFBFC;
    --fc-ink:         #14181F;
    --fc-ink-soft:    #4B5563;
    --fc-muted:       #8A93A1;
    --fc-border:      #E4E7EC;
    --fc-border-soft: #EEF0F3;

    /* One restrained brand accent used ONLY for primary actions + focus */
    --fc-accent:      #2B4C7E;
    --fc-accent-dark: #1F3B63;
    --fc-accent-soft: #EAF0F9;

    /* Status colours — desaturated, functional, not decorative */
    --fc-red:         #B3261E;
    --fc-red-soft:    #FBEAE9;
    --fc-amber:       #92600C;
    --fc-amber-soft:  #FBF1DE;
    --fc-green:       #1E6B45;
    --fc-green-soft:  #E7F4EE;
    --fc-blue:        #2B4C7E;
    --fc-blue-soft:   #EAF0F9;

    --fc-radius:      8px;
    --fc-radius-sm:   6px;
    --fc-shadow:      0 1px 2px rgba(20,24,31,0.05);
    --fc-shadow-md:   0 2px 8px rgba(20,24,31,0.08);

    --fc-font-ui:      'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    --fc-font-mono:    'JetBrains Mono', 'SFMono-Regular', Consolas, monospace;
}

/* ── base ─────────────────────────────────────────────────────────────── */
html, body, [class*="css"] { font-family: var(--fc-font-ui); }
.main { background-color: var(--fc-canvas); }
.block-container { padding-top: 1.75rem !important; padding-bottom: 3rem !important; max-width: 1360px; }

/* Numeric data reads as instrument output: tabular figures, no jitter */
[data-testid="stMetricValue"], .fc-num, td, .stDataFrame { font-variant-numeric: tabular-nums; }

/* ── accessibility: visible keyboard focus everywhere, respect reduced motion ── */
*:focus-visible { outline: 2px solid var(--fc-accent) !important; outline-offset: 2px; }
@media (prefers-reduced-motion: reduce) {
    * { transition: none !important; animation: none !important; }
}

/* ── scrollbars: quiet, not a design feature ── */
::-webkit-scrollbar { width: 8px; height: 8px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: #D3D8DF; border-radius: 99px; }
::-webkit-scrollbar-thumb:hover { background: #B4BBC6; }

/* ── sidebar: dense operational nav, not a lobby ─────────────────────────
   Dark neutral (near-black slate), not a decorative material. One accent
   rail marks the active module — the same signal used for active tabs and
   selected rows elsewhere, so the eye learns it once. */
section[data-testid="stSidebar"] {
    background: #14181F;
    border-right: 1px solid #232833;
}
section[data-testid="stSidebar"] * { color: #C7CCD6 !important; }
section[data-testid="stSidebar"] h1 {
    color: #FFFFFF !important; font-family: var(--fc-font-ui) !important;
    font-size: 0.95rem !important; font-weight: 700 !important; letter-spacing: -0.01em;
    padding-bottom: 0.6rem; border-bottom: 1px solid #232833; margin-bottom: 0.6rem !important;
}
section[data-testid="stSidebar"] .stSelectbox label,
section[data-testid="stSidebar"] p { color: #7B8494 !important; font-size: 12px; }

/* module list: flat rows, left rail on active, no gradients */
section[data-testid="stSidebar"] div[data-testid="stRadio"] > div[role="radiogroup"] { gap: 1px; }
section[data-testid="stSidebar"] div[data-testid="stRadio"] label {
    border-radius: 4px !important; padding: 7px 10px !important; margin: 0 !important;
    border-left: 2px solid transparent; transition: background 0.12s;
}
section[data-testid="stSidebar"] div[data-testid="stRadio"] label:hover {
    background: rgba(255,255,255,0.05);
}
section[data-testid="stSidebar"] div[data-testid="stRadio"] label:has(input:checked) {
    background: rgba(255,255,255,0.07);
    border-left-color: #6E9BE8;
}
section[data-testid="stSidebar"] div[data-testid="stRadio"] label:has(input:checked) p {
    color: #FFFFFF !important; font-weight: 600 !important;
}
section[data-testid="stSidebar"] hr { border-top: 1px solid #232833 !important; }

/* ── headings: system sans, one clear hierarchy, no ornament ── */
h1 {
    color: var(--fc-ink) !important; font-family: var(--fc-font-ui) !important;
    font-size: 1.5rem !important; font-weight: 700 !important; letter-spacing: -0.015em;
    padding-bottom: 0; margin-bottom: 0.15rem !important;
}
h2 { color: var(--fc-ink) !important; font-family: var(--fc-font-ui) !important; font-size: 1.15rem !important; font-weight: 600 !important; letter-spacing: -0.01em; }
h3 { color: var(--fc-ink) !important; font-family: var(--fc-font-ui) !important; font-size: 0.95rem !important; font-weight: 600 !important; }
[data-testid="stCaptionContainer"] { color: var(--fc-muted) !important; font-size: 12.5px !important; }

/* ── metric cards: flat, bordered, data-first — no hover lift theatrics ── */
div[data-testid="metric-container"] {
    background: var(--fc-surface); border: 1px solid var(--fc-border);
    border-radius: var(--fc-radius);
    padding: 0.9rem 1.05rem;
}
div[data-testid="metric-container"] label {
    font-size: 11px !important; color: var(--fc-muted) !important;
    font-family: var(--fc-font-ui) !important;
    text-transform: uppercase; letter-spacing: 0.06em; font-weight: 600 !important;
}
div[data-testid="metric-container"] div[data-testid="stMetricValue"] {
    font-family: var(--fc-font-mono) !important; font-size: 1.4rem !important;
    font-weight: 600 !important; color: var(--fc-ink) !important; letter-spacing: -0.01em;
}

/* ── buttons: one solid primary style, flat, no gradient/glow ── */
.stButton > button {
    background: var(--fc-accent) !important; color: #FFFFFF !important;
    border: 1px solid var(--fc-accent) !important; border-radius: 6px !important;
    font-weight: 600 !important; font-size: 13.5px !important; letter-spacing: 0;
    box-shadow: none !important;
    transition: background 0.12s !important;
}
.stButton > button:hover { background: var(--fc-accent-dark) !important; border-color: var(--fc-accent-dark) !important; }
.stButton > button:active { background: var(--fc-accent-dark) !important; }
.stDownloadButton > button {
    border-radius: 6px !important; font-weight: 600 !important;
    border: 1px solid var(--fc-border) !important; background: var(--fc-surface) !important;
    color: var(--fc-ink-soft) !important; box-shadow: none !important;
}
.stDownloadButton > button:hover { border-color: var(--fc-accent) !important; color: var(--fc-accent) !important; }

/* secondary / destructive-adjacent actions: outlined, quiet until needed */
button[kind="secondary"] {
    background: transparent !important; color: var(--fc-red) !important;
    border: 1px solid var(--fc-border) !important; font-size: 12.5px !important;
    padding: 4px 10px !important; box-shadow: none !important;
}
button[kind="secondary"]:hover { background: var(--fc-red-soft) !important; border-color: var(--fc-red) !important; }

/* ── tabs: flat underline, no pill/shadow ── */
.stTabs [data-baseweb="tab-list"] {
    gap: 4px; background: transparent; border-bottom: 1px solid var(--fc-border); padding: 0;
}
.stTabs [data-baseweb="tab"] {
    border-radius: 0; padding: 0.5rem 0.85rem;
    font-size: 13px; font-weight: 500; color: var(--fc-muted);
}
.stTabs [aria-selected="true"] {
    background: transparent !important; color: var(--fc-ink) !important;
    font-weight: 600 !important; box-shadow: inset 0 -2px 0 var(--fc-accent);
}

/* ── inputs: crisp 1px borders, one focus signal ── */
.stTextInput input, .stNumberInput input, .stDateInput input, .stTextArea textarea {
    border-radius: 6px !important; border: 1px solid var(--fc-border) !important; font-size: 13.5px !important;
    transition: border-color 0.12s, box-shadow 0.12s;
}
.stTextInput input:focus, .stNumberInput input:focus, .stTextArea textarea:focus {
    border-color: var(--fc-accent) !important; box-shadow: 0 0 0 3px var(--fc-accent-soft) !important;
}
div[data-baseweb="select"] > div { border-radius: 6px !important; border-color: var(--fc-border) !important; }
div[data-baseweb="tag"] { background: var(--fc-accent-soft) !important; color: var(--fc-accent) !important; border-radius: 4px !important; }
div[data-baseweb="slider"] div[role="slider"] { background-color: var(--fc-accent) !important; }

/* ── alerts: left-bar accent, flat fill, no drop shadow ── */
.stAlert, .stSuccess, .stWarning, .stError, .stInfo {
    border-radius: var(--fc-radius-sm) !important; border: 1px solid var(--fc-border) !important;
    box-shadow: none !important;
}
.stSuccess { border-left: 3px solid var(--fc-green) !important; background: var(--fc-green-soft) !important; }
.stWarning { border-left: 3px solid var(--fc-amber) !important; background: var(--fc-amber-soft) !important; }
.stError   { border-left: 3px solid var(--fc-red)   !important; background: var(--fc-red-soft) !important; }
.stInfo    { border-left: 3px solid var(--fc-blue)  !important; background: var(--fc-blue-soft) !important; }

/* ── expanders ── */
div[data-testid="stExpander"] {
    border: 1px solid var(--fc-border) !important; border-radius: var(--fc-radius) !important;
    box-shadow: none !important; overflow: hidden;
}
div[data-testid="stExpander"] summary { font-weight: 600; font-size: 13px; color: var(--fc-ink); transition: background 0.12s; }
div[data-testid="stExpander"] summary:hover { background: var(--fc-surface-alt); }

/* ── dataframes / tables ── */
div[data-testid="stDataFrame"] { border: 1px solid var(--fc-border) !important; border-radius: var(--fc-radius) !important; overflow: hidden; }

hr { border-top: 1px solid var(--fc-border); margin: 1.1rem 0; }

/* ── reusable page-header + status-pill classes used by redesigned pages ── */
.fc-page-eyebrow { font-size: 11px; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase; color: var(--fc-muted); margin-bottom: 2px; }
.fc-page-sub { font-size: 13px; color: var(--fc-muted); margin-top: 2px; margin-bottom: 0; }
.fc-section-label { font-size: 11px; font-weight: 600; letter-spacing: 0.07em; text-transform: uppercase; color: var(--fc-muted); margin: 0 0 8px 0; }
.fc-pill { display:inline-flex; align-items:center; gap:5px; font-size:11.5px; font-weight:600; padding:2px 9px; border-radius:99px; line-height:1.7; }
.fc-pill.success { background: var(--fc-green-soft); color: var(--fc-green); }
.fc-pill.warning  { background: var(--fc-amber-soft); color: var(--fc-amber); }
.fc-pill.error    { background: var(--fc-red-soft);   color: var(--fc-red); }
.fc-pill.info     { background: var(--fc-blue-soft);  color: var(--fc-blue); }
.fc-divider-tight { border-top: 1px solid var(--fc-border); margin: 0.75rem 0; }
</style>
""", unsafe_allow_html=True)

# ================= DB =================
# PERF FIX: load()/load_filtered() further down re-run "SELECT * FROM ..."
# against every table on every single widget interaction, even though
# Streamlit reruns the whole script top-to-bottom on every click/keystroke.
# With years of daily-log/production/stock rows this is the single biggest
# cause of the app feeling sluggish. @st.cache_data (added below) fixes
# that, but a plain cache would show stale data right after a supervisor
# saves something. So every cached read is keyed on this "data version"
# number, bumped by a Connection subclass every time anything, anywhere in
# the app, calls conn.commit() — so a save instantly invalidates every
# cached read without having to hunt down and edit ~50 commit() call sites.
# (A plain `conn.commit = ...` instance-attribute monkeypatch does NOT work
# here — sqlite3.Connection is a C type and raises AttributeError on that;
# subclassing is the correct fix.)
_data_version = {"v": 0}

class _TrackingConnection(sqlite3.Connection):
    def commit(self) -> None:
        super().commit()
        _data_version["v"] += 1

# FIX: Connection now created before auth (previously it was created *after*
# login), because credentials and brute-force lockouts are now persisted in
# the database instead of living only in memory / hardcoded in source.
@st.cache_resource
def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect("fcsc.db", check_same_thread=False, factory=_TrackingConnection)
    # FIX: WAL mode lets reads and writes proceed concurrently instead of
    # blocking each other — matters once several supervisors hit the same
    # SQLite file at once. Cheap to enable, meaningfully reduces
    # "database is locked" errors under concurrent use.
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    # FIX: default busy_timeout is 0 — a second writer hits "database is
    # locked" immediately instead of waiting. 5s lets a writer that's
    # blocked behind another session's BEGIN IMMEDIATE (see _write_lock
    # below) simply wait its turn, which is what we want now that closing
    # stock is computed under an explicit write lock.
    conn.execute("PRAGMA busy_timeout=5000;")
    return conn

conn = get_connection()

# FIX: `cur` used to be a single sqlite3.Cursor object shared by every
# Streamlit session. Streamlit runs each active user's script in its own
# thread, and a sqlite3.Cursor is NOT safe to share across threads — two
# supervisors clicking "Save" at the same moment could interleave their
# execute()/fetchone() calls on the *same* cursor object and each end up
# reading the other's query results (wrong stock numbers, wrong batch IDs,
# etc.), even though the underlying connection itself is fine to share.
# `_ThreadLocalCursor` transparently gives each thread its own real
# sqlite3.Cursor while every existing `cur.execute(...)` / `cur.fetchone()`
# / `cur.lastrowid` call site in this file keeps working unchanged.
class _ThreadLocalCursor:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._conn = connection
        self._local = threading.local()

    def _get(self) -> sqlite3.Cursor:
        c = getattr(self._local, "cursor", None)
        if c is None:
            c = self._conn.cursor()
            self._local.cursor = c
        return c

    def __getattr__(self, name):
        return getattr(self._get(), name)

cur = _ThreadLocalCursor(conn)

# FIX: closes the "read previous closing balance, then insert the new one"
# race (reconciliation review, Section 3). WAL mode lets reads and writes
# proceed concurrently, but it does NOT make a read-then-write *sequence*
# atomic — two sessions can both read the same previous closing stock
# before either has written, so one session's addition silently overwrites
# the other's instead of stacking on top of it. BEGIN IMMEDIATE acquires
# SQLite's write lock up front, before the read inside the block runs, so
# a second session's BEGIN IMMEDIATE simply waits (via PRAGMA busy_timeout,
# set above) until the first one commits and its read no longer sees stale
# data. Use this around any "read latest ledger row, compute new balance,
# insert" sequence — currently: FG stock movements and RM stock entries.
@contextlib.contextmanager
def _write_lock():
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
        conn.commit()
    except Exception:
        conn.rollback()
        raise


# ================= AUTH =================
# FIX: Passwords are now salted and hashed with hashlib.scrypt (a slow,
# purpose-built password KDF) instead of one unsalted SHA-256 pass. Plain
# SHA-256 is fast by design (it's a checksum algorithm), which makes it
# practical to brute-force or rainbow-table offline; scrypt is deliberately
# slow and salted per-user so the same password never hashes the same way
# twice and can't be cracked with precomputed tables.
_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2 ** 14, 8, 1

def _hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt,
                             n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32)
    return f"{salt.hex()}${digest.hex()}"

def _verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, digest_hex = stored.split("$")
        salt = bytes.fromhex(salt_hex)
        candidate = hashlib.scrypt(password.encode(), salt=salt,
                                    n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32)
        # FIX: constant-time comparison — avoids leaking timing information
        # about how many bytes of the hash matched.
        return hmac.compare_digest(candidate.hex(), digest_hex)
    except Exception:
        return False

cur.executescript("""
CREATE TABLE IF NOT EXISTS users (
    username TEXT PRIMARY KEY,
    password TEXT NOT NULL,
    role     TEXT NOT NULL,
    factory  TEXT,
    display  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS login_attempts (
    username     TEXT PRIMARY KEY,
    attempts     INTEGER DEFAULT 0,
    locked_until TEXT
);
CREATE TABLE IF NOT EXISTS login_log (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    username  TEXT NOT NULL,
    factory   TEXT,
    role      TEXT,
    timestamp TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS module_usage (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    username  TEXT NOT NULL,
    module    TEXT NOT NULL,
    timestamp TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS feedback (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    username  TEXT NOT NULL,
    factory   TEXT,
    message   TEXT NOT NULL,
    status    TEXT NOT NULL DEFAULT 'pending',
    timestamp TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS app_errors (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    level     TEXT NOT NULL,
    username  TEXT,
    message   TEXT NOT NULL
);
""")
conn.commit()

# ================= PILOT DASHBOARD: instrumentation =================
# NEW: lightweight usage tracking that feeds the admin-only "Pilot Dashboard"
# module further down. Every insert here is wrapped so a tracking failure
# can never take down the actual feature the user is trying to use.

class _SQLiteLogHandler(logging.Handler):
    """Mirrors every WARNING+ log record into app_errors so the Pilot
    Dashboard can show 'errors reported' without anyone having to go dig
    through fcsc_app.log on disk."""
    def emit(self, record: logging.LogRecord) -> None:
        try:
            _uname = "system"
            try:
                _uname = st.session_state.get("username", "system") or "system"
            except Exception:
                pass
            cur.execute(
                "INSERT INTO app_errors (timestamp, level, username, message) VALUES (?,?,?,?)",
                (datetime.datetime.now().isoformat(timespec="seconds"),
                 record.levelname, _uname, self.format(record))
            )
            conn.commit()
        except Exception:
            pass  # logging must never raise

logger.addHandler(_SQLiteLogHandler())

def log_login(username: str, factory: str | None, role: str) -> None:
    try:
        cur.execute(
            "INSERT INTO login_log (username, factory, role, timestamp) VALUES (?,?,?,?)",
            (username, factory, role, datetime.datetime.now().isoformat(timespec="seconds"))
        )
        conn.commit()
    except Exception as e:
        logger.warning("login_log write failed: %s", e)

def log_module_view(username: str, module: str) -> None:
    try:
        cur.execute(
            "INSERT INTO module_usage (username, module, timestamp) VALUES (?,?,?)",
            (username, module, datetime.datetime.now().isoformat(timespec="seconds"))
        )
        conn.commit()
    except Exception as e:
        logger.warning("module_usage write failed: %s", e)

def submit_feedback(username: str, factory: str | None, message: str) -> None:
    cur.execute(
        "INSERT INTO feedback (username, factory, message, status, timestamp) VALUES (?,?,?,'pending',?)",
        (username, factory, message.strip(), datetime.datetime.now().isoformat(timespec="seconds"))
    )
    conn.commit()

# ── Seed default accounts on first run only ───────────────────────────────────
# FIX: Plaintext defaults no longer live permanently in source. They're used
# once, here, to seed the table — after that only the salted hash exists
# anywhere. ⚠️ CHANGE THESE PASSWORDS immediately via the sidebar "Change My
# Password" form, which now actually persists (see the sidebar section).
_DEFAULT_USERS = [
    ("admin",    "admin@fcsc",    "admin",      None,       "Administrator"),
    ("belda",    "belda@fcsc",    "supervisor", "Belda",    "Belda Supervisor"),
    ("mogra",    "mogra@fcsc",    "supervisor", "Mogra",    "Mogra Supervisor"),
    ("singur",   "singur@fcsc",   "supervisor", "Singur",   "Singur Supervisor"),
    ("siliguri", "siliguri@fcsc", "supervisor", "Siliguri", "Siliguri Supervisor"),
]
if cur.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
    for _uname, _pw, _role, _fac, _disp in _DEFAULT_USERS:
        cur.execute("INSERT INTO users VALUES (?,?,?,?,?)",
                     (_uname, _hash_password(_pw), _role, _fac, _disp))
    conn.commit()

def get_user(username: str) -> dict | None:
    row = cur.execute(
        "SELECT username, password, role, factory, display FROM users WHERE username = ?",
        (username,)
    ).fetchone()
    if row is None:
        return None
    return {"username": row[0], "password": row[1], "role": row[2],
            "factory": row[3], "display": row[4]}

# ── Server-side brute-force protection ─────────────────────────────────────────
# FIX: Previously tracked in st.session_state, which is scoped to a single
# browser session — an attacker could bypass the lockout just by opening a
# new tab or incognito window. Now tracked per-username in the database, so
# it survives across sessions, tabs, and app restarts.
_MAX_ATTEMPTS = 5
_LOCKOUT_MINS = 15

def _get_lockout(username: str) -> tuple[int, datetime.datetime | None]:
    row = cur.execute(
        "SELECT attempts, locked_until FROM login_attempts WHERE username = ?",
        (username,)
    ).fetchone()
    if row is None:
        return 0, None
    locked_until = datetime.datetime.fromisoformat(row[1]) if row[1] else None
    return row[0], locked_until

def _register_failed_attempt(username: str) -> tuple[int, datetime.datetime | None]:
    attempts, _ = _get_lockout(username)
    attempts += 1
    locked_until = (datetime.datetime.now() + datetime.timedelta(minutes=_LOCKOUT_MINS)
                     if attempts >= _MAX_ATTEMPTS else None)
    cur.execute(
        "INSERT INTO login_attempts VALUES (?,?,?) "
        "ON CONFLICT(username) DO UPDATE SET attempts=excluded.attempts, "
        "locked_until=excluded.locked_until",
        (username, attempts, locked_until.isoformat() if locked_until else None)
    )
    conn.commit()
    return attempts, locked_until

def _reset_attempts(username: str) -> None:
    cur.execute("DELETE FROM login_attempts WHERE username = ?", (username,))
    conn.commit()

# Modules blocked for factory supervisors
SUPERVISOR_BLOCKED = {"Dashboard", "P&L", "Analysis", "Audit Trail", "Pilot Dashboard"}
ADMIN_MODULES      = ["Dashboard", "Daily Log", "Production", "Formulation", "Sand", "Stock",
                       "Procurement", "Quality", "Sales", "Dispatch", "Reconciliation", "Cost", "P&L", "Analysis",
                       "Reports", "Customers", "Audit Trail", "Pilot Dashboard"]
SUPERVISOR_MODULES = ["My Factory", "Daily Log", "Production", "Formulation", "Sand", "Stock",
                       "Procurement", "Quality", "Sales", "Dispatch", "Reconciliation", "Cost", "Reports"]

# NEW: Company logo for the login page — loaded from disk and cached as a
# base64 data URI so it can be embedded straight into the styled HTML card
# below (Streamlit's raw st.markdown blocks can't reference local file paths
# directly). Looked up relative to this script so it works regardless of the
# working directory the app is launched from. Falls back to None if the file
# isn't present, so a missing asset never crashes the login page — the CSS
# still renders, just without the image.
@st.cache_data
def _get_logo_data_uri() -> str | None:
    _script_dir = os.path.dirname(os.path.abspath(__file__))
    _candidates = [
        os.path.join(_script_dir, "assets", "fcsc_logo.png"),
        os.path.join(_script_dir, "fcsc_logo.png"),
        os.path.join(os.getcwd(), "assets", "fcsc_logo.png"),
        os.path.join(os.getcwd(), "fcsc_logo.png"),
    ]
    for _logo_path in _candidates:
        try:
            with open(_logo_path, "rb") as f:
                _b64 = base64.b64encode(f.read()).decode()
            return f"data:image/png;base64,{_b64}"
        except Exception:
            continue
    logger.warning("Logo asset not found. Checked: %s", _candidates)
    return None

# ================= WEATHER (login page) =================
# NEW: current conditions per factory, shown on the login page. Uses
# Open-Meteo (free, no API key) — reuses the same `requests` import/flag
# already used for WhatsApp/SMS above. Degrades the same way as every other
# optional feature in this app: if `requests` isn't installed or the API
# call fails for any reason, the login page just skips this section —
# it must never block someone from logging in.

FACTORY_COORDS = {
    "Belda":    (22.0600, 87.3200),
    "Mogra":    (22.8500, 88.1300),
    "Singur":   (22.7800, 88.0300),
    "Siliguri": (26.7271, 88.3953),
}

_WMO_ICON = {
    0: ("☀️", "Clear sky"), 1: ("🌤️", "Mainly clear"), 2: ("⛅", "Partly cloudy"),
    3: ("☁️", "Overcast"), 45: ("🌫️", "Fog"), 48: ("🌫️", "Rime fog"),
    51: ("🌦️", "Light drizzle"), 53: ("🌦️", "Drizzle"), 55: ("🌦️", "Dense drizzle"),
    61: ("🌧️", "Slight rain"), 63: ("🌧️", "Rain"), 65: ("🌧️", "Heavy rain"),
    71: ("🌨️", "Slight snow"), 73: ("🌨️", "Snow"), 75: ("🌨️", "Heavy snow"),
    80: ("🌦️", "Rain showers"), 81: ("🌦️", "Rain showers"), 82: ("⛈️", "Violent showers"),
    95: ("⛈️", "Thunderstorm"), 96: ("⛈️", "Thunderstorm + hail"), 99: ("⛈️", "Thunderstorm + hail"),
}

def _weather_icon(code) -> tuple[str, str]:
    try:
        return _WMO_ICON.get(int(code), ("🌡️", "—"))
    except (TypeError, ValueError):
        return ("🌡️", "—")

@st.cache_data(ttl=1800, show_spinner=False)
def fetch_factory_weather(lat: float, lon: float) -> dict | None:
    """Current temp/humidity/wind/visibility/rain-chance for one location.
    Returns None on any failure — never raises, never blocks login."""
    if not HAS_REQUESTS:
        return None
    try:
        resp = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat, "longitude": lon,
                "current": "temperature_2m,relative_humidity_2m,apparent_temperature,"
                           "precipitation,weather_code,wind_speed_10m",
                "hourly": "visibility,precipitation_probability",
                "timezone": "Asia/Kolkata",
                "forecast_days": 1,
            },
            timeout=6,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        cur, hourly = data.get("current", {}), data.get("hourly", {})

        # Match the current hour's index into the hourly arrays (visibility
        # and rain-probability are only available hourly, not in `current`).
        idx = 0
        _times = hourly.get("time", [])
        if cur.get("time") in _times:
            idx = _times.index(cur["time"])

        _vis_list  = hourly.get("visibility", [])
        _rain_list = hourly.get("precipitation_probability", [])
        visibility_m = _vis_list[idx] if idx < len(_vis_list) else None
        rain_chance  = _rain_list[idx] if idx < len(_rain_list) else None
        icon, label = _weather_icon(cur.get("weather_code", 0))

        return {
            "temp": cur.get("temperature_2m"),
            "feels_like": cur.get("apparent_temperature"),
            "humidity": cur.get("relative_humidity_2m"),
            "wind_speed": cur.get("wind_speed_10m"),
            "rain_chance": rain_chance,
            "visibility_km": round(visibility_m / 1000, 1) if visibility_m is not None else None,
            "icon": icon, "label": label,
        }
    except Exception as e:
        logger.warning("Weather fetch failed for (%s,%s): %s", lat, lon, e)
        return None

# ================= WEATHER-BASED OPERATIONAL TIPS =================
# NEW: turns raw weather numbers into a short, specific action line — tied
# to conditions that actually matter for a cement/chemical-additive plant:
# outdoor sand/aggregate storage, moisture-sensitive powders (cement, RDP,
# MHEC — all already in the MATERIALS list), dispatch-truck visibility, and
# labour heat safety. Only the single most urgent tip is returned, in
# priority order, so it reads as one clear nudge rather than a wall of
# caveats. Returns None when there's nothing worth flagging — a quiet day
# should look quiet, not padded out with a manufactured "all clear" line.
def generate_weather_tip(w: dict | None) -> tuple[str, str] | None:
    """Returns (severity, message) where severity is 'warning' or 'info'."""
    if not w or w.get("temp") is None:
        return None
    rain = w.get("rain_chance")
    vis  = w.get("visibility_km")
    wind = w.get("wind_speed")
    temp = w.get("temp")
    hum  = w.get("humidity")

    if rain is not None and rain >= 60:
        return ("warning", f"🌧️ {rain:.0f}% rain chance — cover outdoor sand/cement stock & check drainage")
    if vis is not None and vis < 2:
        return ("warning", f"🌫️ Low visibility ({vis:.1f} km) — caution advised for dispatch vehicle movement")
    if wind is not None and wind >= 30:
        return ("warning", f"🌬️ Strong winds ({wind:.0f} km/h) — secure loose packaging & tarpaulins")
    if temp is not None and temp >= 38:
        return ("warning", f"🌡️ Very hot ({temp:.0f}°C) — schedule worker hydration breaks")
    if hum is not None and hum >= 85:
        return ("info", f"💧 High humidity ({hum:.0f}%) — extra care for moisture-sensitive powders (cement, RDP, MHEC)")
    if rain is not None and rain >= 30:
        return ("info", f"🌦️ Rain possible ({rain:.0f}%) — keep tarpaulins ready")
    return None

def render_weather_advisory(scope_factory: str | None) -> None:
    """Compact weather-driven advisory for the logged-in app (Dashboard /
    My Factory). `scope_factory=None` checks every factory and surfaces any
    that have an active tip; passing one factory name checks only that one.
    Renders nothing at all if there's nothing worth flagging."""
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


# ================= SKELETON LOADERS =================
# NEW: shimmering placeholder blocks shown while data is being fetched,
# instead of a bare spinner + text — one of the fastest ways to make a
# Streamlit app stop feeling like a form and start feeling like a
# considered product, with no changes to the underlying data flow.
_SKELETON_CSS = """
<style>
@keyframes fcsc-shimmer { 0% {background-position:-400px 0;} 100% {background-position:400px 0;} }
.fcsc-skel { background:linear-gradient(90deg,#EFE4CC 25%,#E2D4B8 37%,#EFE4CC 63%);
    background-size:400px 100%; animation:fcsc-shimmer 1.3s ease-in-out infinite;
    border-radius:8px; }
.fcsc-skel-row { display:flex; gap:10px; margin:4px 0 10px; }
.fcsc-skel-card { flex:1; min-width:120px; height:76px; border:1px solid #E2D4B8;
    border-top:3px solid #E2D4B8; }
.fcsc-skel-line { height:13px; margin-bottom:9px; }
</style>
"""

def show_skeleton_cards(count: int = 5):
    """Renders `count` shimmering card placeholders into a fresh st.empty()
    and returns it — call `.empty()` on the return value once real content
    is ready to replace it seamlessly."""
    placeholder = st.empty()
    cards = "".join("<div class='fcsc-skel fcsc-skel-card'></div>" for _ in range(count))
    placeholder.markdown(f"{_SKELETON_CSS}<div class='fcsc-skel-row'>{cards}</div>",
                          unsafe_allow_html=True)
    return placeholder

def show_skeleton_lines(count: int = 4):
    """Renders `count` shimmering line placeholders (for table-like content)
    into a fresh st.empty() and returns it."""
    placeholder = st.empty()
    widths = [96, 88, 92, 80, 90, 85, 94, 78]
    lines = "".join(
        f"<div class='fcsc-skel fcsc-skel-line' style='width:{widths[i % len(widths)]}%;'></div>"
        for i in range(count)
    )
    placeholder.markdown(f"{_SKELETON_CSS}{lines}", unsafe_allow_html=True)
    return placeholder


def render_weather_strip() -> None:
    """Row of compact per-factory weather cards for the login page. Each
    card also shows its single highest-priority operational tip inline —
    tying the tip directly to that location's actual conditions rather
    than a generic aggregate blurb."""
    if not HAS_REQUESTS:
        return  # silently skip — same degrade pattern as PDF/QR/WhatsApp features

    st.markdown("""
    <style>
    .fcsc-weather-row { display:flex; gap:10px; flex-wrap:wrap; justify-content:center;
        max-width:920px; margin:0 auto 0.4rem; }
    .fcsc-weather-card { flex:1; min-width:175px; max-width:215px;
        background:linear-gradient(180deg,#FFFBF2 0%,#FBF3E4 100%);
        border:1px solid #EFE4CC; border-top:3px solid #6E1423;
        border-radius:10px; padding:12px 14px;
        box-shadow:0 4px 14px -8px rgba(28,18,13,0.15); }
    .fcsc-weather-fac { font-size:11px; font-weight:700; text-transform:uppercase;
        letter-spacing:0.06em; color:#8C7B62; margin-bottom:4px; }
    .fcsc-weather-main { display:flex; align-items:center; gap:8px; margin-bottom:8px; }
    .fcsc-weather-temp { font-family:'JetBrains Mono',monospace; font-size:22px;
        font-weight:700; color:#241812; }
    .fcsc-weather-label { font-size:11px; color:#5C4632; }
    .fcsc-weather-grid { display:grid; grid-template-columns:1fr 1fr; gap:3px 8px;
        font-size:11px; color:#5C4632; }
    .fcsc-weather-grid b { color:#241812; font-family:'JetBrains Mono',monospace; }
    .fcsc-weather-unavailable { font-size:11px; color:#C4B393; text-align:center; padding:14px 0; }
    .fcsc-weather-tip { margin-top:8px; padding:6px 8px; border-radius:6px;
        font-size:10.5px; line-height:1.35; font-weight:600; }
    .fcsc-weather-tip.warning { background:#F6E6E4; color:#4A0D18; }
    .fcsc-weather-tip.info    { background:#F5E9D0; color:#6B4413; }
    </style>
    """, unsafe_allow_html=True)

    # Skeleton flash while the Open-Meteo calls are in flight (visible
    # mainly on a cold cache — subsequent loads within the 30-min TTL are
    # instant and this placeholder is replaced almost immediately).
    _weather_skel = show_skeleton_cards(count=4)

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
        tip_html = (f"<div class='fcsc-weather-tip {tip[0]}'>{tip[1]}</div>" if tip else "")

        cards.append(
            f"<div class='fcsc-weather-card'>"
            f"<div class='fcsc-weather-fac'>🏭 {fac_name}</div>"
            f"<div class='fcsc-weather-main'>"
            f"<span style='font-size:22px;'>{w['icon']}</span>"
            f"<div><div class='fcsc-weather-temp'>{w['temp']:.0f}°C</div>"
            f"<div class='fcsc-weather-label'>{w['label']} · feels {feels}</div></div></div>"
            f"<div class='fcsc-weather-grid'>"
            f"<span>💧 Humidity</span><b>{hum}</b>"
            f"<span>🌬️ Wind</span><b>{wind}</b>"
            f"<span>👁️ Visibility</span><b>{vis}</b>"
            f"<span>🌧️ Rain chance</span><b>{rain}</b>"
            f"</div>{tip_html}</div>"
        )
    _weather_skel.empty()
    st.markdown(f"<div class='fcsc-weather-row'>{''.join(cards)}</div>", unsafe_allow_html=True)


# ================= FESTIVAL / HOLIDAY CALENDAR (West Bengal) =================
# NEW: surfaces the state's festival/holiday calendar contextually — as a
# banner on the login page, and as a quieter reminder inside Dashboard / My
# Factory. Dates below are West Bengal's officially notified 2026 holiday
# calendar (Finance Dept. Notification 4188-F(P2), 27 Nov 2025), plus
# Vishwakarma Puja — not a state holiday, but a near-universal shop-floor
# observance where machinery is worshipped and the line goes idle for the
# day, so it's genuinely operationally relevant even though it isn't a
# gazetted closure. Lunar-calendar festivals move every year — this list is
# specific to 2026 and should be refreshed (or migrated to a DB table, the
# same way vendors/material codes are, for in-app editing) ahead of 2027.
#
# Each entry is a closed date RANGE (single-day festivals repeat the same
# date for start/end) so multi-day breaks like Durga Puja read as one
# continuous banner instead of five separate ones.
WB_FESTIVALS_2026 = [
    {"start": "2026-01-01", "end": "2026-01-01", "name": "New Year's Day",                    "emoji": "🎉", "closes_factory": True},
    {"start": "2026-01-12", "end": "2026-01-12", "name": "Swami Vivekananda Jayanti",          "emoji": "🪔", "closes_factory": True},
    {"start": "2026-01-23", "end": "2026-01-23", "name": "Netaji Jayanti & Saraswati Puja",    "emoji": "📚", "closes_factory": True},
    {"start": "2026-01-26", "end": "2026-01-26", "name": "Republic Day",                       "emoji": "🇮🇳", "closes_factory": True},
    {"start": "2026-07-13", "end": "2026-07-13", "name": "Bhanu Jayanti",                      "emoji": "🪔", "closes_factory": False},
    {"start": "2026-07-16", "end": "2026-07-16", "name": "Rath Yatra",                         "emoji": "🛞", "closes_factory": False},
    {"start": "2026-08-15", "end": "2026-08-15", "name": "Independence Day",                   "emoji": "🇮🇳", "closes_factory": True},
    {"start": "2026-09-04", "end": "2026-09-04", "name": "Krishna Janmashtami",                "emoji": "🪈", "closes_factory": False},
    {"start": "2026-09-14", "end": "2026-09-14", "name": "Ganesh Chaturthi",                   "emoji": "🐘", "closes_factory": False},
    {"start": "2026-09-17", "end": "2026-09-17", "name": "Vishwakarma Puja",                   "emoji": "🛠️", "closes_factory": True,
     "note": "Widely observed on the shop floor — machinery is worshipped and the line is typically idle for the day."},
    {"start": "2026-10-02", "end": "2026-10-02", "name": "Gandhi Jayanti",                     "emoji": "🕊️", "closes_factory": True},
    {"start": "2026-10-10", "end": "2026-10-10", "name": "Mahalaya",                           "emoji": "🪔", "closes_factory": False},
    {"start": "2026-10-15", "end": "2026-10-24", "name": "Durga Puja",                         "emoji": "🎊", "closes_factory": True,
     "note": "The year's longest break — Maha Chaturthi through the additional post-Dashami holidays."},
    {"start": "2026-10-26", "end": "2026-10-26", "name": "Lakshmi Puja (additional holiday)",  "emoji": "🪔", "closes_factory": True},
    {"start": "2026-11-08", "end": "2026-11-10", "name": "Kali Puja / Diwali",                 "emoji": "🪔", "closes_factory": True,
     "note": "Kali Puja falls on the 8th; the 9th–10th are additional notified holidays."},
    {"start": "2026-11-11", "end": "2026-11-11", "name": "Bhai Phonta",                        "emoji": "🎀", "closes_factory": True},
    {"start": "2026-11-15", "end": "2026-11-16", "name": "Chhat Puja",                         "emoji": "🌅", "closes_factory": False},
    {"start": "2026-12-25", "end": "2026-12-25", "name": "Christmas",                          "emoji": "🎄", "closes_factory": True},
]

def _parse_iso_date(d: str) -> datetime.date:
    return datetime.datetime.strptime(d, "%Y-%m-%d").date()

def get_festival_banner_info(within_days: int = 10) -> dict | None:
    """Returns info for the most relevant festival: one happening today (if
    any), otherwise the nearest upcoming one within `within_days`. Returns
    None if nothing qualifies — the banner is then simply not shown, rather
    than displaying a stale or irrelevant note."""
    today = datetime.date.today()
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
    """Renders a festival/holiday banner if one is relevant right now.
    `compact=True` renders a slim single-line version for the logged-in app
    (Dashboard, My Factory); the full version is for the login page. Renders
    nothing at all when no festival is within range."""
    info = get_festival_banner_info(within_days=10)
    if info is None:
        return

    start_d, end_d = _parse_iso_date(info["start"]), _parse_iso_date(info["end"])
    span = start_d.strftime("%d %b") + (f"–{end_d.strftime('%d %b')}" if start_d != end_d else "")

    if info["status"] == "today":
        headline = f"{info['emoji']} {info['name']} — Today ({span})"
    else:
        days = info["days_away"]
        headline = f"{info['emoji']} {info['name']} — in {days} day{'s' if days != 1 else ''} ({span})"

    closure_note = ("Factories closed" if info.get("closes_factory")
                     else "Widely observed — plan for lower attendance")
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
        <div style='font-size:12px;color:#8C7B62;margin-top:2px;'>
            {closure_note}{f' — {detail}' if detail else ''}
        </div>
    </div>
    """, unsafe_allow_html=True)


# ================= MONSOON SEASON THEME =================
# NEW: a light seasonal treatment for West Bengal's monsoon window (roughly
# June through September per IMD's normal onset/withdrawal dates for the
# state). Purely additive — a subtle animated rain overlay behind the login
# card and a compact advisory banner reusing the same pattern as the
# festival banner above. Automatically switches itself off outside the
# monsoon months, so there's nothing to remember to toggle each year.
MONSOON_MONTHS = {6, 7, 8, 9}

def is_monsoon_season(_today: datetime.date | None = None) -> bool:
    today = _today or datetime.date.today()
    return today.month in MONSOON_MONTHS

_STORM_SCENE_CSS = """
<style>
/* Dark stormy sky replaces the usual light canvas behind the login page,
   only while this scene is mounted (i.e. only on the login page, only in
   monsoon months) — normal app pages are never touched by this. */
.stApp { background: linear-gradient(180deg,#211510 0%,#2B1D14 45%,#3A2A1C 100%) !important; }

.fcsc-storm-scene { position: fixed; inset: 0; overflow: hidden; pointer-events: none; z-index: 0; }

/* ── Clouds — soft blurred masses drifting at different depths/speeds ── */
@keyframes fcsc-cloud-drift {
    0%   { transform: translateX(-12%); }
    100% { transform: translateX(12%); }
}
.fcsc-cloud {
    position: absolute; border-radius: 50%; filter: blur(18px);
    background: radial-gradient(ellipse at 50% 50%, rgba(60,70,95,0.85) 0%, rgba(45,53,74,0.55) 70%, rgba(45,53,74,0) 100%);
    animation-name: fcsc-cloud-drift;
    animation-timing-function: ease-in-out;
    animation-iteration-count: infinite;
    animation-direction: alternate;
}

/* ── Lightning — irregular double-flash lighting the whole scene, plus a
   jagged bolt that flickers near one cloud in rough sync ── */
@keyframes fcsc-lightning-flash {
    0%, 100% { opacity: 0; }
    91%      { opacity: 0; }
    92%      { opacity: 0.85; }
    93%      { opacity: 0.1; }
    94%      { opacity: 0.6; }
    95.5%    { opacity: 0; }
}
.fcsc-lightning-flash {
    position: absolute; inset: 0;
    background: radial-gradient(ellipse at 30% 15%, rgba(226,236,255,0.9) 0%, rgba(226,236,255,0.15) 45%, rgba(226,236,255,0) 75%);
    animation: fcsc-lightning-flash linear infinite;
}
@keyframes fcsc-bolt-flicker {
    0%, 100% { opacity: 0; }
    91.5%    { opacity: 0; }
    92%      { opacity: 1; }
    93%      { opacity: 0.2; }
    94%      { opacity: 0.9; }
    95.5%    { opacity: 0; }
}
.fcsc-bolt {
    position: absolute; top: 6%; left: 26%; width: 90px; height: 220px;
    filter: drop-shadow(0 0 8px rgba(210,228,255,0.9));
    animation: fcsc-bolt-flicker linear infinite;
}

/* ── Rain — angled, wind-driven streaks ── */
@keyframes fcsc-rain-fall {
    0%   { transform: translate(-60px,-120%); opacity: 0; }
    12%  { opacity: 0.55; }
    88%  { opacity: 0.4; }
    100% { transform: translate(60px,1000%); opacity: 0; }
}
.fcsc-raindrop {
    position: absolute; top: -10%; width: 1.5px; height: 90px;
    background: linear-gradient(180deg,
        rgba(190,210,235,0) 0%, rgba(190,210,235,0.55) 50%, rgba(190,210,235,0) 100%);
    animation-name: fcsc-rain-fall;
    animation-timing-function: linear;
    animation-iteration-count: infinite;
}

/* ── Trees — silhouettes along the bottom edge, swaying in the wind ── */
@keyframes fcsc-tree-sway {
    0%, 100% { transform: rotate(-3.5deg); }
    50%      { transform: rotate(4deg); }
}
.fcsc-tree-row { position: absolute; bottom: 0; left: 0; width: 100%; height: 190px; }
.fcsc-tree {
    position: absolute; bottom: 0; transform-origin: bottom center;
    animation-name: fcsc-tree-sway;
    animation-timing-function: ease-in-out;
    animation-iteration-count: infinite;
    opacity: 0.9;
}
</style>
"""

def render_monsoon_storm_scene(drop_count: int = 70, cloud_count: int = 5, tree_count: int = 7) -> None:
    """Renders a full animated thunderstorm scene behind the login card —
    dark sky, drifting clouds, flickering lightning, wind-angled rain, and
    swaying tree silhouettes along the bottom edge. Deterministic
    pseudo-scatter (no `random` import needed) so layout is stable across
    reruns. No-ops entirely outside monsoon months."""
    if not is_monsoon_season():
        return

    # Clouds: varying width/blur/height/speed for a rough sense of depth.
    clouds = []
    for i in range(cloud_count):
        left     = (i * 23) % 90
        top      = 2 + (i * 7) % 14
        width    = 260 + (i % 3) * 90
        height   = 70 + (i % 2) * 30
        duration = 34 + (i % 4) * 9
        clouds.append(
            f"<div class='fcsc-cloud' style='left:{left}%; top:{top}%; "
            f"width:{width}px; height:{height}px; "
            f"animation-duration:{duration}s;'></div>"
        )

    # Lightning: whole-scene flash + one jagged bolt, both on a long loop so
    # strikes feel irregular rather than metronomic.
    lightning = (
        "<div class='fcsc-lightning-flash' style='animation-duration:9s;'></div>"
        "<svg class='fcsc-bolt' style='animation-duration:9s;' viewBox='0 0 40 100' "
        "xmlns='http://www.w3.org/2000/svg'>"
        "<polygon points='22,0 6,52 18,52 10,100 34,40 20,40' fill='#E5EAEF'/>"
        "</svg>"
    )

    # Rain: angled streaks driven by wind, denser/faster than a light shower.
    drops = []
    for i in range(drop_count):
        left     = (i * 17) % 110 - 5
        duration = 0.9 + (i % 6) * 0.18
        delay    = (i % 9) * 0.3
        drops.append(
            f"<span class='fcsc-raindrop' style='left:{left}%; "
            f"animation-duration:{duration:.2f}s; animation-delay:{delay:.2f}s;'></span>"
        )

    # Trees: simple silhouettes, staggered size/sway timing along the
    # bottom edge so the row reads as a natural tree-line, not a repeat tile.
    trees = []
    for i in range(tree_count):
        left     = 2 + i * (96 / max(tree_count - 1, 1))
        h        = 130 + (i % 3) * 22
        duration = 2.6 + (i % 4) * 0.5
        delay    = (i % 5) * 0.35
        trees.append(
            f"<svg class='fcsc-tree' style='left:{left:.1f}%; height:{h}px; "
            f"animation-duration:{duration:.2f}s; animation-delay:{delay:.2f}s;' "
            f"viewBox='0 0 60 130' xmlns='http://www.w3.org/2000/svg'>"
            f"<rect x='27' y='78' width='6' height='52' fill='#1C120D'/>"
            f"<ellipse cx='30' cy='45' rx='27' ry='34' fill='#1C120D'/>"
            f"<ellipse cx='16' cy='62' rx='16' ry='20' fill='#1C120D'/>"
            f"<ellipse cx='44' cy='62' rx='16' ry='20' fill='#1C120D'/>"
            f"</svg>"
        )

    st.markdown(
        f"{_STORM_SCENE_CSS}"
        f"<div class='fcsc-storm-scene'>"
        f"{''.join(clouds)}{lightning}{''.join(drops)}"
        f"<div class='fcsc-tree-row'>{''.join(trees)}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )

def render_monsoon_banner(compact: bool = False) -> None:
    """Seasonal advisory banner shown only during the monsoon window.
    `compact=True` renders a slim single-line version for the logged-in app
    (Dashboard / My Factory), matching `render_festival_banner`'s pattern.
    Renders nothing outside monsoon months."""
    if not is_monsoon_season():
        return

    headline = "🌧️ Monsoon Season Active — Jun to Sep"
    detail   = ("Increased humidity and rainfall may affect outdoor material "
                "storage, moisture-sensitive powders, and dispatch schedules.")

    if compact:
        st.info(f"{headline} · {detail}")
        return

    st.markdown(f"""
    <div style='max-width:920px;margin:0.6rem auto 0;padding:12px 18px;
        background:linear-gradient(90deg,#E5EAEF,#FFFBF2);
        border:1px solid #D6DEE6;border-left:4px solid #2F5975;
        border-radius:10px;box-shadow:0 4px 14px -8px rgba(28,18,13,0.12);
        position:relative; z-index:1;'>
        <div style='font-weight:700;font-size:14px;color:#241812;'>{headline}</div>
        <div style='font-size:12px;color:#8C7B62;margin-top:2px;'>{detail}</div>
    </div>
    """, unsafe_allow_html=True)


# ================= NOTIFICATION BELL =================
# NEW: a single bell icon that rolls up everything already scattered across
# the app that someone should probably act on today — open procurement,
# overdue procurement stages, open NCRs, and low/critical stock — computed
# live from existing tables rather than a separate notifications table, so
# there's nothing new to seed or keep in sync. Role-scoped: supervisors only
# see their own factory's items, admins see everything.
def get_notifications(is_admin: bool, user_factory: str | None) -> list[dict]:
    notes: list[dict] = []
    fac_clause = "" if is_admin else " AND factory = ?"
    fac_params = () if is_admin else (user_factory,)

    try:
        n_open_proc = cur.execute(
            f"SELECT COUNT(*) FROM procurement_requests WHERE status='Open'{fac_clause}",
            fac_params
        ).fetchone()[0]
        if n_open_proc:
            notes.append({"icon": "🛒", "severity": "warning", "module": "Procurement",
                          "text": f"{n_open_proc} open procurement request(s) awaiting action"})
    except sqlite3.Error:
        pass

    try:
        _open_ids = cur.execute(
            f"SELECT id FROM procurement_requests WHERE status='Open'{fac_clause}", fac_params
        ).fetchall()
        if _open_ids:
            _ids = tuple(r[0] for r in _open_ids)
            _ph = ",".join("?" * len(_ids))
            n_overdue = cur.execute(
                f"SELECT COUNT(*) FROM procurement_stages WHERE request_id IN ({_ph}) "
                f"AND status NOT IN ('Completed','Skipped') AND due_date < ?",
                (*_ids, str(datetime.date.today()))
            ).fetchone()[0]
            if n_overdue:
                notes.append({"icon": "⏰", "severity": "warning", "module": "Procurement",
                              "text": f"{n_overdue} procurement stage(s) overdue"})
    except sqlite3.Error:
        pass

    try:
        if is_admin:
            n_ncr = cur.execute("SELECT COUNT(*) FROM ncr_capa WHERE status='Open'").fetchone()[0]
        else:
            n_ncr = cur.execute(
                "SELECT COUNT(*) FROM ncr_capa n JOIN production_batches pb "
                "ON pb.batch_no = n.batch_no WHERE n.status='Open' AND pb.factory = ?",
                (user_factory,)
            ).fetchone()[0]
        if n_ncr:
            notes.append({"icon": "⚠️", "severity": "warning", "module": "Quality",
                          "text": f"{n_ncr} open NCR(s) need corrective action"})
    except sqlite3.Error:
        pass

    try:
        _stock_q = (
            "SELECT s.material, s.factory, s.closing_stock, "
            "COALESCE(r.threshold, ?) AS threshold FROM stock s "
            "INNER JOIN (SELECT factory, material, MAX(id) AS max_id FROM stock GROUP BY factory, material) latest "
            "ON s.factory = latest.factory AND s.material = latest.material AND s.id = latest.max_id "
            "LEFT JOIN reorder_levels r ON r.material = s.material AND r.factory = s.factory"
            + fac_clause
        )
        low_rows = cur.execute(_stock_q, (DEFAULT_REORDER_THRESHOLD, *fac_params)).fetchall()
        n_low = sum(1 for _, _, qty, thr in low_rows if qty < thr)
        if n_low:
            notes.append({"icon": "📉", "severity": "warning", "module": "Stock",
                          "text": f"{n_low} material(s) below reorder threshold"})
    except sqlite3.Error:
        pass

    return notes

def render_notification_bell(is_admin: bool, user_factory: str | None) -> None:
    """Renders the bell in the sidebar. Uses st.popover for a real dropdown
    feel where available; falls back to an expander on older Streamlit
    versions that don't have st.popover yet."""
    notes = get_notifications(is_admin, user_factory)
    count = len(notes)
    label = f"🔔 Notifications ({count})" if count else "🔔 Notifications"

    def _render_body():
        if not notes:
            st.caption("✅ You're all caught up — nothing needs attention right now.")
        else:
            for n in notes:
                (st.warning if n["severity"] == "warning" else st.info)(f"{n['icon']} {n['text']}")

    if hasattr(st, "popover"):
        with st.popover(label, use_container_width=True):
            _render_body()
    else:
        with st.expander(label, expanded=False):
            _render_body()


# ================= GLOBAL SEARCH =================
# NEW: one search box across customers, vendors, materials, products, sales
# orders, dispatches, procurement requests, and QC batches — instead of
# having to already know which of the ~15 modules something lives in.
# Role-scoped the same way as the rest of the app: supervisors' factory-
# scoped tables (stock, production, sales, procurement, batches) are
# filtered to their own factory; global masters (customers, vendors) search
# everywhere regardless of role.
def run_global_search(q: str, is_admin: bool, user_factory: str | None,
                       limit_per_cat: int = 5) -> list[dict]:
    like = f"%{q}%"
    results: list[dict] = []

    def _fac(has_factory: bool = True):
        if is_admin or not has_factory:
            return "", ()
        return " AND factory = ?", (user_factory,)

    try:
        for name, gstin in cur.execute(
            "SELECT name, gstin FROM customers WHERE name LIKE ? OR gstin LIKE ? LIMIT ?",
            (like, like, limit_per_cat)
        ).fetchall():
            results.append({"category": "Customer", "icon": "🏢", "label": name,
                            "detail": f"GSTIN: {gstin or '—'}", "module": "Customers"})
    except sqlite3.Error:
        pass

    try:
        for name, email, phone in cur.execute(
            "SELECT name, email, phone FROM vendors WHERE name LIKE ? LIMIT ?", (like, limit_per_cat)
        ).fetchall():
            results.append({"category": "Vendor", "icon": "🏭", "label": name,
                            "detail": email or phone or "No contact on file", "module": "Procurement"})
    except sqlite3.Error:
        pass

    clause, params = _fac()
    try:
        for material, fac in cur.execute(
            f"SELECT DISTINCT material, factory FROM stock WHERE material LIKE ?{clause} LIMIT ?",
            (like, *params, limit_per_cat)
        ).fetchall():
            results.append({"category": "Material", "icon": "🧱", "label": material,
                            "detail": f"Stock @ {fac}", "module": "Stock"})
    except sqlite3.Error:
        pass

    clause, params = _fac()
    try:
        for product, fac in cur.execute(
            f"SELECT DISTINCT product, factory FROM production WHERE product LIKE ?{clause} LIMIT ?",
            (like, *params, limit_per_cat)
        ).fetchall():
            results.append({"category": "Product", "icon": "⚙️", "label": fg_label(product),
                            "detail": f"Produced @ {fac}", "module": "Production"})
    except sqlite3.Error:
        pass

    clause, params = _fac()
    try:
        for customer, product, total, date in cur.execute(
            f"SELECT customer, product, total, date FROM sales_orders "
            f"WHERE (customer LIKE ? OR product LIKE ?){clause} ORDER BY id DESC LIMIT ?",
            (like, like, *params, limit_per_cat)
        ).fetchall():
            results.append({"category": "Sales Order", "icon": "📈", "label": f"{customer} — {product}",
                            "detail": f"{fmt_inr(total)} on {date}", "module": "Sales"})
    except sqlite3.Error:
        pass

    clause, params = _fac()
    try:
        for customer, product, total, date in cur.execute(
            f"SELECT customer, product, total, date FROM sales "
            f"WHERE (customer LIKE ? OR product LIKE ?){clause} ORDER BY id DESC LIMIT ?",
            (like, like, *params, limit_per_cat)
        ).fetchall():
            results.append({"category": "Dispatch", "icon": "🚚", "label": f"{customer} — {product}",
                            "detail": f"{fmt_inr(total)} on {date}", "module": "Dispatch"})
    except sqlite3.Error:
        pass

    clause, params = _fac()
    try:
        for material, fac, status in cur.execute(
            f"SELECT material, factory, status FROM procurement_requests "
            f"WHERE material LIKE ?{clause} ORDER BY id DESC LIMIT ?",
            (like, *params, limit_per_cat)
        ).fetchall():
            results.append({"category": "Procurement", "icon": "🛒", "label": material,
                            "detail": f"{status} @ {fac}", "module": "Procurement"})
    except sqlite3.Error:
        pass

    clause, params = _fac()
    try:
        for batch_no, product, status in cur.execute(
            f"SELECT batch_no, product, status FROM production_batches "
            f"WHERE batch_no LIKE ?{clause} ORDER BY id DESC LIMIT ?",
            (like, *params, limit_per_cat)
        ).fetchall():
            results.append({"category": "Batch", "icon": "🧪", "label": batch_no,
                            "detail": f"{product} — {status}", "module": "Quality"})
    except sqlite3.Error:
        pass

    clause, params = _fac()
    try:
        for batch_no, material, supplier, status in cur.execute(
            f"SELECT batch_no, material, supplier, status FROM rm_batches "
            f"WHERE (batch_no LIKE ? OR material LIKE ? OR supplier LIKE ?){clause} "
            f"ORDER BY id DESC LIMIT ?",
            (like, like, like, *params, limit_per_cat)
        ).fetchall():
            results.append({"category": "RM Batch", "icon": "📥", "label": f"{batch_no} — {material}",
                            "detail": f"{supplier} — {status}", "module": "Quality"})
    except sqlite3.Error:
        pass

    return results

def render_global_search(is_admin: bool, user_factory: str | None,
                          available_modules: list[str]) -> None:
    """Search bar shown at the top of every module. Jumping to a result's
    module works by writing the target into session_state under the same
    key the sidebar's module radio uses, then rerunning — the radio picks
    that value up as its new selection on the next run."""
    st.markdown("""
    <style>
    .fcsc-search-hint { font-size:11px; color:#8C7B62; margin:2px 0 6px 2px; }
    </style>
    """, unsafe_allow_html=True)
    sc1, sc2 = st.columns([6, 1])
    with sc1:
        query = st.text_input(
            "Global search", key="global_search_q", label_visibility="collapsed",
            placeholder="🔍 Search customers, materials, batches, sales orders, vendors…"
        )
    with sc2:
        st.button("Search", key="global_search_btn", use_container_width=True)

    q = (query or "").strip()
    if len(q) < 2:
        return

    results = run_global_search(q, is_admin, user_factory)
    with st.container():
        if not results:
            st.caption(f"No matches for “{q}”.")
        else:
            st.caption(f"{len(results)} result(s) for “{q}”")
            for i, r in enumerate(results):
                rc1, rc2 = st.columns([6, 1])
                with rc1:
                    st.markdown(
                        f"{r['icon']} **{r['label']}** &nbsp;·&nbsp; "
                        f"<span style='color:#8C7B62;font-size:12px'>{r['category']} — {r['detail']}</span>",
                        unsafe_allow_html=True,
                    )
                with rc2:
                    # NEW: Customer / Material / Batch results open the consolidated
                    # 360° page directly instead of just dropping the person into the
                    # parent module to go hunting for the record themselves.
                    _detail_map = {"Customer": "customer", "Material": "material", "Batch": "batch"}
                    if r["category"] in _detail_map:
                        if st.button("Open 360° →", key=f"gs_open_{i}_{r['module']}", use_container_width=True):
                            open_detail_view(_detail_map[r["category"]], r["label"])
                    elif r["module"] in available_modules:
                        if st.button("Open →", key=f"gs_open_{i}_{r['module']}", use_container_width=True):
                            st.session_state["module_radio"] = r["module"]
                            st.rerun()
            st.markdown("<hr style='margin:6px 0 2px;border-color:#EFE4CC;'>", unsafe_allow_html=True)


def show_login_page() -> None:
    """Renders the full-screen login form and halts execution until authenticated."""
    render_monsoon_storm_scene()
    st.markdown("""
    <style>
    section[data-testid="stSidebar"] { display: none; }
    div[data-testid="stToolbar"]     { display: none; }

    /* ── FCSC ERP — Premium Industrial Login Page ───────────────────── */
    .fcsc-login-wrap {
        display: flex;
        justify-content: center;
        padding: 2.4rem 0 1rem;
        position: relative;
        z-index: 1;
    }
    .fcsc-login-card {
        width: 100%;
        max-width: 460px;
        position: relative;
        background: linear-gradient(180deg, #1C120D 0%, #241811 100%);
        border: 1px solid rgba(184,134,11,0.55);
        border-radius: 4px;
        padding: 3rem 2.8rem 1.8rem;
        box-shadow: 0 24px 60px -20px rgba(0,0,0,0.55), 0 2px 10px rgba(0,0,0,0.3);
    }
    /* filigree corner frame — a fine gold hairline set inward from the card edge,
       the one ornamental flourish this page spends its budget on */
    .fcsc-login-card::before {
        content: "";
        position: absolute; inset: 10px;
        border: 1px solid rgba(212,175,55,0.35);
        pointer-events: none;
    }
    .fcsc-logo-img {
        display: block;
        max-width: 220px;
        width: 100%;
        height: auto;
        margin: 0 auto 1.6rem;
        filter: drop-shadow(0 2px 6px rgba(0,0,0,0.4));
    }
    .fcsc-brand-title {
        text-align: center;
        margin: 0;
        font-family: 'Cormorant Garamond', Georgia, serif;
        font-weight: 700;
        font-size: 2.5rem;
        letter-spacing: 0.02em;
        line-height: 1.1;
        text-transform: uppercase;
    }
    .fcsc-brand-title .fc-strong {
        color: #D4AF37;
        font-weight: 700;
    }
    .fcsc-brand-title .fc-light {
        color: #F1E4BE;
        font-weight: 500;
    }
    .fcsc-brand-rule {
        width: 56px; height: 1px; margin: 0.9rem auto 0.85rem;
        background: linear-gradient(90deg, transparent, #D4AF37, transparent);
    }
    .fcsc-brand-tagline {
        text-align: center;
        font-family: 'Cinzel', Georgia, serif;
        font-size: 11px;
        font-weight: 500;
        letter-spacing: 0.22em;
        text-transform: uppercase;
        color: #9C8A6E;
        margin: 0 0 2.1rem;
    }
    .fcsc-form-label {
        text-align: center;
        font-family: 'Cinzel', Georgia, serif;
        font-size: 10.5px;
        font-weight: 500;
        letter-spacing: 0.16em;
        text-transform: uppercase;
        color: #B8860B;
        margin-bottom: 1rem;
    }
    .fcsc-login-footer {
        text-align: center;
        font-size: 11px;
        color: #8C7B62;
        margin-top: 1.7rem;
        padding-top: 1.1rem;
        border-top: 1px solid rgba(184,134,11,0.25);
        position: relative; z-index: 1;
    }
    .fcsc-login-company {
        text-align: center;
        font-size: 11px;
        color: #9C8A6E;
        letter-spacing: 0.06em;
        margin-top: 0.35rem;
    }
    /* the login form's own inputs and button sit on the dark card, so they
       need their own light treatment rather than the app-wide light-card styling */
    .fcsc-login-card [data-testid="stForm"] label p { color: #D9CBA9 !important; }
    .fcsc-login-card [data-testid="stForm"] .stTextInput input {
        background: rgba(255,251,242,0.06) !important;
        border: 1.5px solid rgba(184,134,11,0.4) !important;
        color: #F1E4BE !important;
        border-radius: 3px !important;
    }
    .fcsc-login-card [data-testid="stForm"] .stTextInput input::placeholder { color: #6B5540 !important; }
    .fcsc-login-card [data-testid="stForm"] .stTextInput input:focus {
        border-color: #D4AF37 !important; box-shadow: 0 0 0 2px rgba(212,175,55,0.18) !important;
    }
    .fcsc-login-card [data-testid="stForm"] .stFormSubmitButton button {
        background: linear-gradient(180deg, #B8860B 0%, #8C5A1B 100%) !important;
        color: #1C120D !important; border: 1px solid #D4AF37 !important;
        font-family: 'Cinzel', Georgia, serif !important; font-weight: 600 !important;
        letter-spacing: 0.08em !important; text-transform: uppercase !important; font-size: 12px !important;
    }
    .fcsc-login-card [data-testid="stForm"] .stFormSubmitButton button:hover {
        background: linear-gradient(180deg, #D4AF37 0%, #B8860B 100%) !important;
        box-shadow: 0 4px 14px rgba(184,134,11,0.4) !important;
    }
    </style>
    """, unsafe_allow_html=True)

    _logo_uri = _get_logo_data_uri()
    if _logo_uri:
        _logo_html = f"<img src='{_logo_uri}' class='fcsc-logo-img' alt='FCSC logo'>"
    else:
        # Fallback if assets/fcsc_logo.png wasn't found alongside app.py —
        # show the text wordmark instead of leaving the card blank.
        _logo_html = (
            "<h1 class='fcsc-brand-title'>"
            "<span class='fc-strong'>FIRSTCHOICE</span> <span class='fc-light'>CENTRAL</span>"
            "</h1>"
            "<div class='fcsc-brand-rule'></div>"
            "<p class='fcsc-brand-tagline'>Driving Operational Excellence</p>"
        )

    col_l, col_c, col_r = st.columns([1, 1.2, 1])
    with col_c:
        st.markdown(f"""
        <div class='fcsc-login-wrap'>
          <div class='fcsc-login-card'>
            {_logo_html}
        """, unsafe_allow_html=True)

        st.markdown("<p class='fcsc-form-label'>Sign in to your account</p>", unsafe_allow_html=True)

        with st.form("login_form"):
            username = st.text_input("Username", placeholder="Enter your username")
            password = st.text_input("Password", type="password",
                                     placeholder="Enter your password")
            submitted = st.form_submit_button("🔐 Sign In", width='stretch')

        if submitted:
            uname = username.strip().lower()
            attempts, locked_until = _get_lockout(uname)
            _locked = locked_until is not None and datetime.datetime.now() < locked_until

            if _locked:
                _wait = int((locked_until - datetime.datetime.now()).total_seconds())
                st.error(f"Too many failed attempts. Try again in {_wait}s.")
            else:
                user = get_user(uname)
                if user and _verify_password(password, user["password"]):
                    _reset_attempts(uname)
                    st.session_state.logged_in    = True
                    st.session_state.username     = uname
                    st.session_state.role         = user["role"]
                    st.session_state.user_factory = user["factory"]
                    st.session_state.display_name = user["display"]
                    log_login(uname, user["factory"], user["role"])
                    st.rerun()
                else:
                    attempts, locked_until = _register_failed_attempt(uname)
                    remaining = max(0, _MAX_ATTEMPTS - attempts)
                    if locked_until is not None:
                        st.error(f"🔒 Account locked for {_LOCKOUT_MINS} minutes after too many failed attempts.")
                    else:
                        st.error(f"Invalid username or password. {remaining} attempt(s) remaining.")

        st.markdown("""
            <div class='fcsc-login-footer'>
                Contact your administrator if you have trouble logging in.
                <div class='fcsc-login-company'>FIRSTCHOICE SPECIALITY CHEMICALS PVT. LTD.</div>
            </div>
          </div>
        </div>
        """, unsafe_allow_html=True)

    # ── Festival/holiday + monsoon banners, then weather strip — below the login card ──
    render_festival_banner()
    render_monsoon_banner()
    st.markdown("<div style='height:0.6rem'></div>", unsafe_allow_html=True)
    render_weather_strip()

# ── Session state init ────────────────────────────────────────────────────────
if "logged_in" not in st.session_state:
    st.session_state.logged_in    = False
    st.session_state.username     = ""
    st.session_state.role         = ""
    st.session_state.user_factory = None
    st.session_state.display_name = ""

if not st.session_state.logged_in:
    show_login_page()
    st.stop()

# ── Session inactivity timeout (2 hours) ─────────────────────────────────────
_TIMEOUT_SECONDS = 7200  # 2 hours
_now = datetime.datetime.now()
if "last_activity" not in st.session_state:
    st.session_state.last_activity = _now
elif (_now - st.session_state.last_activity).total_seconds() > _TIMEOUT_SECONDS:
    for _k in list(st.session_state.keys()):
        del st.session_state[_k]
    st.rerun()
else:
    st.session_state.last_activity = _now

# ── Convenience shortcuts ─────────────────────────────────────────────────────
_role         = st.session_state.role           # "admin" | "supervisor"
_user_factory = st.session_state.user_factory   # e.g. "Belda" | None
_is_admin     = _role == "admin"
_is_supervisor = _role == "supervisor"

# ================= TABLES =================
cur.executescript("""
CREATE TABLE IF NOT EXISTS production (
    id INTEGER PRIMARY KEY,
    date TEXT, factory TEXT, product TEXT,
    labour INTEGER, hours REAL, production REAL, efficiency REAL
);
CREATE TABLE IF NOT EXISTS sand (
    id INTEGER PRIMARY KEY,
    date TEXT, factory TEXT, qty INTEGER, sand_type TEXT
);
CREATE TABLE IF NOT EXISTS stock (
    id INTEGER PRIMARY KEY,
    date TEXT, factory TEXT, material TEXT,
    received INTEGER, used INTEGER, closing_stock INTEGER
);
CREATE TABLE IF NOT EXISTS sales (
    id INTEGER PRIMARY KEY,
    date TEXT, factory TEXT, customer TEXT,
    product TEXT, qty INTEGER, price REAL, total REAL,
    status TEXT DEFAULT 'Paid', challan_no TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS costs (
    id INTEGER PRIMARY KEY,
    date TEXT, factory TEXT, category TEXT, amount REAL,
    description TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS daily_log (
    id INTEGER PRIMARY KEY,
    date TEXT, factory TEXT, category TEXT,
    activity TEXT, personnel TEXT, status TEXT, notes TEXT
);
CREATE TABLE IF NOT EXISTS sales_orders (
    id          INTEGER PRIMARY KEY,
    date        TEXT,
    factory     TEXT,
    customer    TEXT,
    sales_rep   TEXT,
    product     TEXT,
    unit_price  REAL,
    qty         INTEGER,
    total       REAL
);
CREATE TABLE IF NOT EXISTS sales_targets (
    id          INTEGER PRIMARY KEY,
    month       TEXT,
    factory     TEXT,
    sales_rep   TEXT,
    target_qty  INTEGER  DEFAULT 0,
    target_amt  REAL     DEFAULT 0
);
CREATE TABLE IF NOT EXISTS audit_log (
    id        INTEGER PRIMARY KEY,
    timestamp TEXT,
    username  TEXT,
    action    TEXT,
    tbl       TEXT,
    record_id TEXT,
    detail    TEXT
);
""")
conn.commit()

# ── Create new tables added after initial deployment ─────────────────────────
cur.executescript("""
CREATE TABLE IF NOT EXISTS production_targets (
    id         INTEGER PRIMARY KEY,
    month      TEXT,
    factory    TEXT,
    target_qty REAL    DEFAULT 0,
    notes      TEXT    DEFAULT ''
);
CREATE TABLE IF NOT EXISTS customers (
    id      INTEGER PRIMARY KEY,
    name    TEXT UNIQUE,
    gstin   TEXT DEFAULT '',
    address TEXT DEFAULT '',
    phone   TEXT DEFAULT ''
);
""")
conn.commit()

# ── NEW: Procurement workflow tables ──────────────────────────────────────────
cur.executescript("""
CREATE TABLE IF NOT EXISTS procurement_requests (
    id            INTEGER PRIMARY KEY,
    created_at    TEXT,
    factory       TEXT,
    material      TEXT,
    trigger_type  TEXT DEFAULT 'manual',   -- 'auto_low_stock' | 'manual'
    qty_suggested REAL DEFAULT 0,
    unit          TEXT DEFAULT '',
    status        TEXT DEFAULT 'Open',     -- 'Open' | 'Closed'
    notes         TEXT DEFAULT '',
    closed_at     TEXT
);
CREATE TABLE IF NOT EXISTS procurement_stages (
    id           INTEGER PRIMARY KEY,
    request_id   INTEGER NOT NULL,
    seq          INTEGER NOT NULL,
    stage_name   TEXT NOT NULL,
    status       TEXT DEFAULT 'Pending',   -- 'Pending' | 'In Progress' | 'Completed' | 'Skipped'
    owner        TEXT DEFAULT '',
    due_date     TEXT,
    completed_at TEXT,
    updated_by   TEXT
);
CREATE TABLE IF NOT EXISTS reorder_levels (
    material  TEXT NOT NULL,
    factory   TEXT NOT NULL,
    threshold REAL DEFAULT 50,
    PRIMARY KEY (material, factory)
);
CREATE TABLE IF NOT EXISTS procurement_recipients (
    email      TEXT PRIMARY KEY,
    added_by   TEXT,
    added_at   TEXT
);
CREATE TABLE IF NOT EXISTS digest_recipients (
    email      TEXT PRIMARY KEY,
    added_by   TEXT,
    added_at   TEXT
);
CREATE TABLE IF NOT EXISTS vendors (
    name           TEXT PRIMARY KEY,
    email          TEXT DEFAULT '',
    phone          TEXT DEFAULT '',
    lead_time_days INTEGER DEFAULT 0,
    notes          TEXT DEFAULT '',
    created_at     TEXT
);
CREATE TABLE IF NOT EXISTS vendor_materials (
    material       TEXT PRIMARY KEY,
    vendor_name    TEXT NOT NULL,
    lead_time_days INTEGER DEFAULT 0,
    pack_size      TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS material_codes (
    material TEXT PRIMARY KEY,
    code     TEXT DEFAULT ''
);
""")
conn.commit()

# -- NEW: Official Material Master (single source of truth) ---------------
# Replaces the old free-text MATERIALS list as the authoritative record for
# every raw material, packaging item, label/sticker, and process/intermediate
# item. Sourced from the plant team's Codification_for_System.xlsx and never
# auto-generated or renamed -- see SEED_MATERIALS_MASTER below. A handful of
# items are seeded with procurement_code=NULL and status='Pending Code
# Confirmation' because the source sheet had an unresolved code collision;
# these still work everywhere in the ERP, just flagged, until the plant QC
# head confirms the correct code (do not guess it here).
cur.executescript("""
CREATE TABLE IF NOT EXISTS materials_master (
    id                INTEGER PRIMARY KEY,
    lab_code          TEXT,
    name              TEXT NOT NULL,
    procurement_code  TEXT,
    category          TEXT DEFAULT 'Raw Material',
    status            TEXT DEFAULT 'Confirmed',
    created_at        TEXT
);
CREATE TABLE IF NOT EXISTS material_aliases (
    legacy_name    TEXT PRIMARY KEY,
    canonical_name TEXT NOT NULL
);
""")
conn.commit()

# ── NEW: Quality Control / Batch Traceability workflow ────────────────────────
# Mirrors the RM Receipt → Incoming QC → Production → Process QC → FG QC →
# Packing QC → Dispatch QC pipeline. Each stage is its own table (not one huge
# QC table), and a production batch can only enter a stage once the previous
# one has passed — enforced in the helper functions below, not just the UI.
cur.executescript("""
CREATE TABLE IF NOT EXISTS rm_batches (
    id            INTEGER PRIMARY KEY,
    supplier      TEXT,
    po_reference  TEXT DEFAULT '',
    material      TEXT,
    batch_no      TEXT,
    quantity      REAL DEFAULT 0,
    unit          TEXT DEFAULT '',
    factory       TEXT,
    received_date TEXT,
    status        TEXT DEFAULT 'Awaiting QC',   -- Awaiting QC | Approved | Rejected
    created_by    TEXT,
    created_at    TEXT
);
CREATE TABLE IF NOT EXISTS incoming_inspection (
    id            INTEGER PRIMARY KEY,
    rm_batch_id   INTEGER NOT NULL,
    appearance    TEXT DEFAULT '',
    colour        TEXT DEFAULT '',
    moisture      TEXT DEFAULT '',
    particle_size TEXT DEFAULT '',
    remarks       TEXT DEFAULT '',
    decision      TEXT,     -- Pass | Fail
    inspector     TEXT,
    date          TEXT
);
CREATE TABLE IF NOT EXISTS supplier_return_notes (
    id          INTEGER PRIMARY KEY,
    rm_batch_id INTEGER NOT NULL,
    reason      TEXT DEFAULT '',
    created_at  TEXT
);
CREATE TABLE IF NOT EXISTS production_batches (
    id         INTEGER PRIMARY KEY,
    batch_no   TEXT UNIQUE,
    product    TEXT,
    formula    TEXT DEFAULT '',
    factory    TEXT,
    operator   TEXT,
    machine    TEXT,
    shift      TEXT,
    status     TEXT DEFAULT 'Production Started',
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS production_batch_materials (
    id                   INTEGER PRIMARY KEY,
    production_batch_id  INTEGER NOT NULL,
    rm_batch_id          INTEGER NOT NULL,
    qty_used             REAL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS process_inspection (
    id                   INTEGER PRIMARY KEY,
    production_batch_id  INTEGER NOT NULL,
    viscosity            TEXT DEFAULT '',
    density               TEXT DEFAULT '',
    temperature           TEXT DEFAULT '',
    appearance            TEXT DEFAULT '',
    remarks               TEXT DEFAULT '',
    decision              TEXT,
    inspector             TEXT,
    date                  TEXT
);
CREATE TABLE IF NOT EXISTS fg_inspection (
    id                   INTEGER PRIMARY KEY,
    production_batch_id  INTEGER NOT NULL,
    adhesion             TEXT DEFAULT '',
    strength              TEXT DEFAULT '',
    consistency           TEXT DEFAULT '',
    colour                TEXT DEFAULT '',
    weight                TEXT DEFAULT '',
    decision              TEXT,
    inspector             TEXT,
    date                  TEXT
);
CREATE TABLE IF NOT EXISTS packing_inspection (
    id                   INTEGER PRIMARY KEY,
    production_batch_id  INTEGER NOT NULL,
    correct_bag           INTEGER DEFAULT 0,
    correct_label          INTEGER DEFAULT 0,
    correct_batch          INTEGER DEFAULT 0,
    net_weight_ok          INTEGER DEFAULT 0,
    seal_quality_ok        INTEGER DEFAULT 0,
    decision               TEXT,
    inspector              TEXT,
    date                   TEXT
);
CREATE TABLE IF NOT EXISTS dispatch_approval (
    id                   INTEGER PRIMARY KEY,
    production_batch_id  INTEGER NOT NULL,
    pdi_completed         INTEGER DEFAULT 0,
    approved_by           TEXT,
    date                  TEXT,
    status                TEXT     -- Released | Blocked
);
CREATE TABLE IF NOT EXISTS ncr_capa (
    id                 INTEGER PRIMARY KEY,
    source_stage       TEXT,      -- Incoming | Process | FG | Packing
    reference_id       INTEGER,
    batch_no           TEXT,
    description        TEXT,
    corrective_action  TEXT DEFAULT '',
    status             TEXT DEFAULT 'Open',   -- Open | Closed
    raised_by          TEXT,
    raised_at          TEXT,
    closed_at          TEXT
);
""")
conn.commit()

# ── NEW: Bill of Materials / Formulation ───────────────────────────────────────
# One product can have several BOM versions over time (formula revisions);
# only one is ever "active" at once — enforced in _activate_bom() below, not
# just in the UI — so a lookup never has to guess which version is current.
cur.executescript("""
CREATE TABLE IF NOT EXISTS bom_headers (
    id           INTEGER PRIMARY KEY,
    product      TEXT NOT NULL,
    version      TEXT DEFAULT 'v1',
    formula_code TEXT DEFAULT '',
    batch_size   REAL DEFAULT 100,
    batch_unit   TEXT DEFAULT 'KG',
    is_active    INTEGER DEFAULT 0,
    notes        TEXT DEFAULT '',
    created_by   TEXT,
    created_at   TEXT
);
CREATE TABLE IF NOT EXISTS bom_lines (
    id            INTEGER PRIMARY KEY,
    bom_id        INTEGER NOT NULL,
    material      TEXT NOT NULL,
    qty_per_batch REAL DEFAULT 0,
    unit          TEXT DEFAULT 'KG',
    sequence      INTEGER DEFAULT 0,
    notes         TEXT DEFAULT ''
);
""")
conn.commit()

# ── NEW: WhatsApp / SMS alert recipients (via Twilio) ─────────────────────────
cur.executescript("""
CREATE TABLE IF NOT EXISTS whatsapp_recipients (
    phone      TEXT PRIMARY KEY,
    channel    TEXT DEFAULT 'whatsapp',
    events     TEXT DEFAULT 'low_stock,ncr',
    added_by   TEXT,
    added_at   TEXT
);
""")
conn.commit()

# ── NEW: per-user saved default filters (factory / date range / module) ──────
cur.executescript("""
CREATE TABLE IF NOT EXISTS user_prefs (
    username           TEXT PRIMARY KEY,
    default_factory    TEXT,
    default_days_back  INTEGER,
    default_module     TEXT,
    updated_at         TEXT
);
""")
conn.commit()

# -- NEW: Finished Goods stock ledger + central reconciliation log ------------
# fg_stock is a ledger, not an overwritten balance: every Production save and
# every Dispatch save inserts its own row (production_in or dispatch_out), and
# closing_stock is computed at insert time from the previous row for that
# factory+product, same pattern as the existing `stock` (RM) table. Never
# written to directly from the UI outside record_fg_stock_movement().
#
# inventory_reconciliation is an append-only log of every QC<->Stock and
# Dispatch<->Quality check that's been run — nothing here ever corrects a
# source record, it only ever records what was found. See reconcile_* helpers
# below (after to_mt/from_mt are defined).
cur.executescript("""
CREATE TABLE IF NOT EXISTS fg_stock (
    id             INTEGER PRIMARY KEY,
    date           TEXT, factory TEXT, product TEXT,
    fg_code        TEXT DEFAULT '',
    production_in  REAL DEFAULT 0,
    dispatch_out   REAL DEFAULT 0,
    adjustment     REAL DEFAULT 0,
    closing_stock  REAL DEFAULT 0,
    source_module  TEXT DEFAULT '',
    source_ref_id  INTEGER,
    created_at     TEXT
);
CREATE TABLE IF NOT EXISTS inventory_reconciliation (
    id              INTEGER PRIMARY KEY,
    check_type      TEXT,
    factory         TEXT,
    item_code       TEXT,
    period_start    TEXT, period_end TEXT,
    qty_source_a    REAL, qty_source_b REAL,
    difference      REAL,
    severity        TEXT,
    detail          TEXT,
    checked_at      TEXT
);
""")
conn.commit()

# -- ADDITIVE MIGRATION (2nd-pass integrity review) ---------------------------
# Never touches existing columns/rows — only adds what's missing, so every
# existing table, record and downstream query keeps working unchanged.
#
#  1) fg_stock.movement_type — distinguishes a normal Production/Dispatch
#     entry from a Reversal/Correction row written when an edit or delete
#     needs to keep the ledger truthful (see reverse_fg_stock_for_source()).
#  2) production_batches.quantity / quantity_unit — the QC/batch-traceability
#     side never captured an actual output quantity, which is why the old
#     Dispatch<->Quality check could only compare a batch COUNT (a proxy, not
#     a real quantity check — Section 11 fix). New batches can record it;
#     historical batches stay NULL and are handled as an explicitly labelled
#     fallback, never silently treated as zero or "matched".
#  3) fg_product_unit — canonical FG stock-keeping unit per product (Section
#     6). Production is logged in weight (MT/KG); Dispatch is logged as a
#     packed-unit count ("Qty" = bags/pieces, already the de-facto FG stock
#     unit used historically). Without a per-product pack weight, those two
#     can't be combined in one ledger — this table is the single place that
#     conversion factor lives, editable by an admin.
def _safe_add_column(table: str, coldef: str) -> None:
    try:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {coldef}")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # column already exists — additive migration is idempotent

_safe_add_column("fg_stock", "movement_type TEXT DEFAULT 'Entry'")
_safe_add_column("production_batches", "quantity REAL")
_safe_add_column("production_batches", "quantity_unit TEXT DEFAULT ''")

cur.executescript("""
CREATE TABLE IF NOT EXISTS fg_product_unit (
    product         TEXT PRIMARY KEY,
    stock_unit      TEXT DEFAULT 'Bags',
    pack_weight_kg  REAL,
    updated_by      TEXT,
    updated_at      TEXT
);
""")
conn.commit()

# -- NEW: Official Finished Goods Master (single source of truth) ---------
# Mirrors materials_master/material_aliases below but for finished products.
# Sourced from the plant team's finished_good_codification.xlsx
# (2026-08-13) and never auto-generated or renamed here -- see
# SEED_FINISHED_GOODS_MASTER. A handful of items are seeded with code=NULL
# and status='Pending Code Confirmation' because the source sheet had no
# code yet; these still work everywhere in the ERP, just flagged, until the
# plant team confirms the code.
cur.executescript("""
CREATE TABLE IF NOT EXISTS finished_goods_master (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    code        TEXT,
    status      TEXT DEFAULT 'Confirmed',
    created_at  TEXT
);
CREATE TABLE IF NOT EXISTS fg_aliases (
    legacy_name    TEXT PRIMARY KEY,
    canonical_name TEXT NOT NULL
);
""")
conn.commit()

def get_user_prefs(username: str) -> dict | None:
    row = cur.execute(
        "SELECT default_factory, default_days_back, default_module FROM user_prefs WHERE username = ?",
        (username,)
    ).fetchone()
    if row is None:
        return None
    return {"default_factory": row[0], "default_days_back": row[1], "default_module": row[2]}

def save_user_prefs(username: str, factory_val: str | None, days_back: int, module_val: str) -> None:
    cur.execute(
        "INSERT INTO user_prefs VALUES (?,?,?,?,?) "
        "ON CONFLICT(username) DO UPDATE SET default_factory=excluded.default_factory, "
        "default_days_back=excluded.default_days_back, default_module=excluded.default_module, "
        "updated_at=excluded.updated_at",
        (username, factory_val, days_back, module_val,
         datetime.datetime.now().isoformat(timespec="seconds"))
    )
    conn.commit()


# NEW: Imported once, on first run, from the factory's actual RM Daily Stock
# tracker (Jan–Jun 2026) — 39 real suppliers mapped to 154 materials, with the
# lead times and pack sizes that were already being tracked in that sheet.
# Email/phone are blank (weren't in the source data) — fill those in via
# Procurement → 🏭 Vendors before relying on "Notify Vendor" to actually send.
_SEED_VENDORS = [
    ("AMBUJA CEMENTS LIMITED", 0),
    ("ANAND ENTERPRISES", 7),
    ("ASSOCIATED DYE CHEM CORPORATION", 0),
    ("Algol Chemicals India Pvt Ltd", 8),
    ("BDC DISTRIBUTION PRIVATE LIMITED", 10),
    ("BISWAS INTERNATIONAL", 10),
    ("BROADWAYS CHEMTECH LLP", 25),
    ("C J S SPECIALTY CHEMICALS PRIVATE LIMITED/SAFFRON ENTERPRISE", 15),
    ("CHEMLINE INDIA LTD", 15),
    ("Excel Orgo-Chem Private Limited", 15),
    ("GORACHAND & CO", 7),
    ("GREEN", 0),
    ("Gujarat Polysol Chemicals Pvt. Ltd.", 12),
    ("HARYANA PIGMENT & CHEMICAL INDUSTRIES", 0),
    ("HINDCON CHEMICALS LIMITED", 6),
    ("HITECH/INTERDOMINO", 10),
    ("Himadri Speciality Chemical Ltd", 0),
    ("IMCD INDIA PRIVATE LIMITED", 10),
    ("JBL INTERNATIONAL", 10),
    ("KALEIDO CHEMIE PRIVATE LIMITED", 0),
    ("KHANDELWAL MINERALS", 15),
    ("Kinjal International", 5),
    ("M/S. CADKAMS MARKETING", 4),
    ("MK PETRO", 10),
    ("NIRMAL AND COMPANY", 7),
    ("NOBLE ALCHEM PVT.LTD. UNIT II", 15),
    ("OML CHEMICALS", 7),
    ("OXFORD ENTERPRISES", 15),
    ("Omega Minerals", 7),
    ("PURANDAR INVESTMENT PVT. LTD.", 12),
    ("RXSOL CHEMO PHARMA INTERNATIONAL", 0),
    ("S M ENTERPRISES", 7),
    ("S M ENTERPRISES/Kinjal International", 10),
    ("SAFFRON", 4),
    ("SAFFRON ENTERPRISE", 6),
    ("SAKSHI CHEM SCIENCES PRIVATE LIMITED", 12),
    ("SINGHANIA AND SONS PRIVATE LIMITED", 10),
    ("SREEMAA CHEMICALS", 15),
    ("Shah Enterprise", 10),
]
_SEED_VENDOR_MATERIALS = [
    ("nan", "SAKSHI CHEM SCIENCES PRIVATE LIMITED", 12, "25 KG"),
    ("ADDAGE PCE 128 (POLY CARBOXYLATE ETHER) POWDER", "SAKSHI CHEM SCIENCES PRIVATE LIMITED", 12, "25 KG"),
    ("ADDAGE PCE POWDER", "SAKSHI CHEM SCIENCES PRIVATE LIMITED", 12, "25 KG"),
    ("ALPHOX-200 H", "Kinjal International", 0, "50 KG"),
    ("ALPOX 200", "Kinjal International", 7, "50 KG BARREL"),
    ("ALUMINIUM SULPHATE", "Kinjal International", 10, "50 KG BAG"),
    ("ANTI FOAM POWDER", "Kinjal International", 10, "50 KG BAG"),
    ("APCOTEX TSN 651", "ASSOCIATED DYE CHEM CORPORATION", 0, "200 KG BARREL"),
    ("AQUAPHOBE WR2", "SAFFRON ENTERPRISE", 12, "50 KG CARBOY"),
    ("BARYTES POWDER 2511", "S M ENTERPRISES", 7, "25 KG"),
    ("BONDEX 5800", "PURANDAR INVESTMENT PVT. LTD.", 12, "220 KG BARREL"),
    ("BONDEX J-400", "PURANDAR INVESTMENT PVT. LTD.", 10, "220 KG BARREL"),
    ("BONDEX T 60", "PURANDAR INVESTMENT PVT. LTD.", 12, "50 KG"),
    ("BUTYL CELLSOLOV", "Excel Orgo-Chem Private Limited", 15, "200 KG BARREL"),
    ("BYK-9076", "C J S SPECIALTY CHEMICALS PRIVATE LIMITED/SAFFRON ENTERPRISE", 15, "25 KG"),
    ("Bondex 5295", "PURANDAR INVESTMENT PVT. LTD.", 12, "220 kg Barrel"),
    ("C 400", "CHEMLINE INDIA LTD", 20, "220 KG BARREL"),
    ("C 76", "CHEMLINE INDIA LTD", 10, "200 KG BARREL"),
    ("C-2835/03  PCT135", "Gujarat Polysol Chemicals Pvt. Ltd.", 12, "KG"),
    ("CALCIUM CARBONATE 1000", "S M ENTERPRISES/Kinjal International", 10, "50 KG BAG"),
    ("CALCIUM CHLORIDE", "Kinjal International", 10, "25 KG"),
    ("CALCIUM FORMATE", "Kinjal International", 7, "25 KG"),
    ("CALCIUM STARATE", "Kinjal International", 7, "25 KG"),
    ("CALENDUM", "HITECH/INTERDOMINO", 10, "25 KG BAG"),
    ("CAMCURE 2979", "SAFFRON ENTERPRISE", 0, "30 KG CARBOY"),
    ("CAMCURE W287", "SAFFRON", 0, "200 KG BARREL"),
    ("CAMSPEED 3054", "SAFFRON ENTERPRISE", 0, "30 KG CARBOY"),
    ("CEEFAST ALPHA BLUE 15.0 (U)", "M/S. CADKAMS MARKETING", 0, "25KG"),
    ("CEEFAST BETA BLUE (U)", "M/S. CADKAMS MARKETING", 0, "25 KG"),
    ("CEEFAST CHROMOCYANINE", "M/S. CADKAMS MARKETING", 7, ""),
    ("CEEFAST CHROMOCYANINE GREEN", "M/S. CADKAMS MARKETING", 7, "25 KG"),
    ("CEEFAST GREEN 7(U)", "M/S. CADKAMS MARKETING", 0, "25 KG"),
    ("CEEFAST RED 48.2", "M/S. CADKAMS MARKETING", 0, "20 KG"),
    ("CEEFAST VIOLET TONER 777", "M/S. CADKAMS MARKETING", 0, "10 KG BAG"),
    ("CEEFST GREEN B 807", "M/S. CADKAMS MARKETING", 7, "20 KG"),
    ("CEEROX BLACK OXIDE", "M/S. CADKAMS MARKETING", 7, "25 KG"),
    ("CEEROX BLACK OXIDE 330", "M/S. CADKAMS MARKETING", 0, "25 KG"),
    ("CEEROX BROWN OXIDE", "M/S. CADKAMS MARKETING", 7, "25 KG"),
    ("CEEROX RED OXIDE 130", "M/S. CADKAMS MARKETING", 0, "25 KG"),
    ("CEEROX RED OXIDE 445", "M/S. CADKAMS MARKETING", 7, "25 KG"),
    ("CEEROX RED OXIDE 473", "M/S. CADKAMS MARKETING", 7, "25 KG"),
    ("CEEROX YELLOW OXIDE E", "M/S. CADKAMS MARKETING", 0, "25 KG"),
    ("CHINA CLAY CP POWDER(KAOLIN CLAY)", "S M ENTERPRISES", 10, "35 KG BAG"),
    ("CHINA CLAY CP POWDER(KAOLIN)", "S M ENTERPRISES", 10, "35 KG BAG"),
    ("CITRIC ACID MONOHYDRATE", "GORACHAND & CO", 7, "25 KG BAG"),
    ("CMC POWDER", "Kinjal International", 10, "50 KG BAG"),
    ("DIETHANOLAMINE", "Kinjal International", 7, "225 KG BARREL"),
    ("DISPLAYER CF707", "M/S. CADKAMS MARKETING", 7, "200 KG BARREL"),
    ("DOLOMITE", "KHANDELWAL MINERALS", 15, "50 KG BAG"),
    ("DRIED ALUMINIUM HYDROXIDE GEL", "Kinjal International", 7, "20 KG"),
    ("DYN A70", "Algol Chemicals India Pvt Ltd", 15, "200 kg Barrel"),
    ("EASTMAN TEXANOL", "SAFFRON ENTERPRISE", 10, "200 KG BARREL"),
    ("EMERI SAND", "SREEMAA CHEMICALS", 15, "50 KG"),
    ("EPOXY CURING AGENT LITE 2401", "SINGHANIA AND SONS PRIVATE LIMITED", 0, "25 KG"),
    ("EPOXY CURING AGENT NC 541", "SINGHANIA AND SONS PRIVATE LIMITED", 0, "30 KG CARBOY"),
    ("FINESET 35", "SREEMAA CHEMICALS", 15, "50 KG CARBOY"),
    ("FORMALDIHYDE", "Kinjal International", 0, "50 KG & DRUM"),
    ("FORMIC ACID", "Kinjal International", 0, "35 KG CARBOY"),
    ("GALAXY SLES", "Kinjal International", 7, "50 KG CARBOY"),
    ("GINOPOL (SLS POWDER)", "Kinjal International", 0, "20 KG"),
    ("GLOBAMINE GREEN", "SAFFRON", 7, "20 KG"),
    ("GLYCERINE", "Kinjal International", 0, "50 KG"),
    ("GYPSUM POWDER", "Kinjal International", 7, "50 KG"),
    ("HIMFLOW CRETE HRWR 3J02 55%", "Himadri Speciality Chemical Ltd", 0, ""),
    ("HIND HFR - WD 500", "HINDCON CHEMICALS LIMITED", 7, "KG"),
    ("HIND HFR - WD 500 C2835/07", "HINDCON CHEMICALS LIMITED", 7, "KG"),
    ("HIND MOULD RELEASE OB", "HINDCON CHEMICALS LIMITED", 0, "TANKER"),
    ("HYDRATED LIME", "OXFORD ENTERPRISES", 15, "50 KG BAG"),
    ("HYDROSOFT SRF 50", "HINDCON CHEMICALS LIMITED", 0, ""),
    ("INDOLIGA PSR50(K)", "Kinjal International", 7, "KG"),
    ("IPA", "Kinjal International", 7, "160 KG"),
    ("KELCOCRETE DG-F", "BROADWAYS CHEMTECH LLP", 0, "25 KG"),
    ("LAPOX AH 428", "HINDCON CHEMICALS LIMITED", 7, "30 KG CARBOY"),
    ("LAPOX AH 713", "HINDCON CHEMICALS LIMITED", 7, "190 KG BARREL"),
    ("LAPOX B-47", "HINDCON CHEMICALS LIMITED", 7, "30 KG CARBOY"),
    ("LAPOX B11", "HINDCON CHEMICALS LIMITED", 7, "240 KG BARREL"),
    ("LIME STONE", "Kinjal International", 0, "50 KG BAG"),
    ("LUBOLICE", "Kinjal International", 7, "90 KG BARREL"),
    ("MAK KOTE", "MK PETRO", 10, "20 LTR CARBOY"),
    ("MDEA", "Kinjal International", 7, "230 kg Barrel"),
    ("MEK", "Kinjal International", 0, "200 KG BARREL"),
    ("MERGAL K14", "SREEMAA CHEMICALS", 15, "30 KG CARBOY"),
    ("METHYL ISOBUTYL KETONE", "Kinjal International", 0, "165 KG BARREL"),
    ("MHEC", "Shah Enterprise", 10, "25 KG BAG"),
    ("MICRO SILICA 85%", "GREEN", 0, ""),
    ("MICRO SILICA 92%", "GREEN", 0, ""),
    ("MUSCLUER OX ULTRA MARINE BLUE CI 2900", "KALEIDO CHEMIE PRIVATE LIMITED", 0, "25 KG"),
    ("MUSCULAR OXIDE ULFRAMARINE BLUE PIGMENTS CI-2900", "KALEIDO CHEMIE PRIVATE LIMITED", 0, "25 kg"),
    ("NC 513", "SINGHANIA AND SONS PRIVATE LIMITED", 15, "200 KG BARREL"),
    ("NC 541", "SINGHANIA AND SONS PRIVATE LIMITED", 15, "200 KG BARREL"),
    ("NC 558", "SINGHANIA AND SONS PRIVATE LIMITED", 15, "222 KG MS BARREL"),
    ("NX 5454", "SINGHANIA AND SONS PRIVATE LIMITED", 15, "204 KG BARREL"),
    ("OPC CEMENT", "ANAND ENTERPRISES", 7, "50 KG BAG"),
    ("ORTHO PHOSPHORIC ACID", "Kinjal International", 0, "35 KG"),
    ("PCE 128 (POLY CARBOXYLATE ETHER)", "SAKSHI CHEM SCIENCES PRIVATE LIMITED", 12, "25 KG"),
    ("PECEVIS 100 PS", "BROADWAYS CHEMTECH LLP", 15, "25 KG"),
    ("PEG  400", "Kinjal International", 0, "55 KG CARBOY"),
    ("PHOSPHORIC ACID", "Kinjal International", 7, "35 KG CARBOY"),
    ("PIGMENTS GREEN B  807/811", "M/S. CADKAMS MARKETING", 0, "25 KG"),
    ("POLY ACRALAMIDE", "Kinjal International", 7, "25 KG BAG"),
    ("POLY ACRYLAMIDE", "Kinjal International", 7, "25 KG BAG"),
    ("POLY PROPYLENE GLYCOL", "RXSOL CHEMO PHARMA INTERNATIONAL", 0, "215 KG BARREL"),
    ("POTASSIUM LITHIUM SILICATE KL25", "NOBLE ALCHEM PVT.LTD. UNIT II", 15, "43.480 KG CARBOY"),
    ("PPC CEMENT", "AMBUJA CEMENTS LIMITED", 0, "BULKER"),
    ("PRECIPATED CALCIUM CARBONATE", "Kinjal International", 7, "50 KG BAG"),
    ("PROPLYLENE GLYCOL", "SAFFRON ENTERPRISE", 10, "215 KG BARREL"),
    ("PUTEC 3255", "BROADWAYS CHEMTECH LLP", 60, "200 KG BARREL"),
    ("PVA 2488", "JBL INTERNATIONAL", 10, "25 KG"),
    ("QUARTZ POWDER(300 Mesh or 45 Micron)", "Kinjal International", 7, "50 KG BAG"),
    ("QUARTZ SAND(-300 to 75)", "Omega Minerals", 7, "50 KG BAG"),
    ("R 85", "Algol Chemicals India Pvt Ltd", 0, ""),
    ("RDP 1    5010", "Shah Enterprise", 10, "25 KG BAG"),
    ("RDP 2 5044", "BDC DISTRIBUTION PRIVATE LIMITED", 10, "25 KG BAG"),
    ("RESILANE GTMS", "SAFFRON ENTERPRISE", 7, "50 KG CARBOY"),
    ("RHEO PLUS", "Kinjal International", 10, "12.5  KG BAG"),
    ("RTC-12(2,2,4 TRIMETHYL1,3PENTANEDIOL MONOISOBUTYRATE)", "SAFFRON ENTERPRISE", 10, "200 KG BARREL"),
    ("SAND 2.36", "NIRMAL AND COMPANY", 7, ""),
    ("SAND 600 MICRON", "NIRMAL AND COMPANY", 7, ""),
    ("SAPCO NDW", "Kinjal International", 7, "90 KG BARREL"),
    ("SBR LATEX", "ASSOCIATED DYE CHEM CORPORATION", 0, "200 KG BARREL"),
    ("SHUTTEROL RA", "HINDCON CHEMICALS LIMITED", 7, "IBC TANK"),
    ("SILICA FLOUR(400 Mesh or 37 Micron)", "S M ENTERPRISES", 7, "50 KG BAG"),
    ("SILICA POWDER", "S M ENTERPRISES", 0, "50 KG BAG"),
    ("SINGLE POLYMER", "BISWAS INTERNATIONAL", 10, "25 KG"),
    ("SLES 230 KG", "Kinjal International", 7, "230 kg Barrel"),
    ("SNF LIQUID", "Kinjal International", 0, "200 kg Barrel"),
    ("SNF POWDER", "HINDCON CHEMICALS LIMITED", 7, "25 KG BAG"),
    ("SNF POWDER (sodium nepthalene sulphonate)", "HINDCON CHEMICALS LIMITED", 7, "25 KG BAG"),
    ("SODA ASH(Light)", "Kinjal International", 7, "50 KG BAG"),
    ("SODIUM CARBONATE(Light)", "Kinjal International", 0, "50 KG BAG"),
    ("SODIUM GLUCONATE", "Kinjal International", 7, "25 KG BAG"),
    ("SODIUM HYDROXIDE solution", "Kinjal International", 7, "330 KG BARREL"),
    ("SODIUM LIGNO 01", "Kinjal International", 7, "25 KG BAG"),
    ("SODIUM NITRATE", "Kinjal International", 7, "25 KG"),
    ("SODIUM SHULPHATE", "Kinjal International", 0, "50 KG BAG"),
    ("SODIUM SILICATE", "HARYANA PIGMENT & CHEMICAL INDUSTRIES", 0, "250 KG BARREL"),
    ("SODIUM SILICOFLUORIDE", "Kinjal International", 0, "25 KG BAG"),
    ("SODIUM SULPHATE", "Kinjal International", 0, "50 KG"),
    ("SODIUM THIOCYANATE", "Kinjal International", 7, "25 KG"),
    ("SOLVENT C9", "Kinjal International", 15, "170 KG"),
    ("SUGAR", "Kinjal International", 7, "50 KG BAG"),
    ("SULPHAMIC ACID", "Kinjal International", 0, "50 KG BAG"),
    ("SYNTHETIC IRON OXIDE PIGMENTS", "KALEIDO CHEMIE PRIVATE LIMITED", 0, "25 KG"),
    ("SYNTHETIC IRON OXIDE RED (MUSCLEROX)", "KALEIDO CHEMIE PRIVATE LIMITED", 0, "25 KG"),
    ("TALCUM POWDER KOHINOOR", "S M ENTERPRISES", 7, "50 KG BAG"),
    ("TEA 99%", "Kinjal International", 7, "220 kg Barrel"),
    ("TECHNOCEL-500-I", "IMCD INDIA PRIVATE LIMITED", 10, "10 KG BAG"),
    ("TIO2 ®", "M/S. CADKAMS MARKETING", 12, "25 KG BAG"),
    ("UNIWET 3048", "SAFFRON ENTERPRISE", 0, "25 KG"),
    ("WHITE CEMENT", "OML CHEMICALS", 7, "50 KG BAG"),
    ("XYLINE", "Kinjal International", 7, "200 KG BARREL"),
    ("YELLOW OXIDE", "M/S. CADKAMS MARKETING", 0, "25 KG"),
    ("ZINC DUST", "SREEMAA CHEMICALS", 15, "50 KG"),
    ("ZINC PHOSPHATE", "Kinjal International", 7, "25 KG"),
]
if cur.execute("SELECT COUNT(*) FROM vendors").fetchone()[0] == 0:
    for _vname, _vlead in _SEED_VENDORS:
        cur.execute(
            "INSERT OR IGNORE INTO vendors VALUES (?,?,?,?,?,?)",
            (_vname, "", "", _vlead, "", datetime.datetime.now().isoformat(timespec="seconds"))
        )
    for _mat, _ven, _lead, _pack in _SEED_VENDOR_MATERIALS:
        cur.execute(
            "INSERT OR IGNORE INTO vendor_materials VALUES (?,?,?,?)",
            (_mat, _ven, _lead, _pack)
        )
    conn.commit()

# ── Seed material codes from the same RM Daily Stock tracker ──────────────────
# NEW: Lets raw materials be tracked by their internal code (e.g. "C0665/01"),
# same as the source spreadsheet did, not just by name.
_SEED_MATERIAL_CODES = [
    ("ADDAGE PCE 128 (POLY CARBOXYLATE ETHER) POWDER", "C2835/08"),
    ("ADDAGE PCE POWDER", "C2835/08"),
    ("ALPHOX-200 H", "C2490/01"),
    ("ALPOX 200", "C2490/01"),
    ("ALUMINIUM SULPHATE", "C0345/01"),
    ("ANTI FOAM POWDER", "C0480/01"),
    ("APCOTEX TSN 651", "C3795/01"),
    ("AQUAPHOBE WR2", "C2775/01"),
    ("BARYTES POWDER 2511", "C0525/02"),
    ("BONDEX 5800", "C0090/01"),
    ("BONDEX J-400", "C3780/01"),
    ("BONDEX T 60", "C0145/02"),
    ("BUTYL CELLSOLOV", "C0665/01"),
    ("BYK-9076", "C0676/01"),
    ("Bondex 5295", "C3782/01"),
    ("C 400", "C3780/01"),
    ("C 76", "C3781/02"),
    ("C-2835/03  PCT135", "C2835/03"),
    ("CALCIUM CARBONATE 1000", "C0750/08"),
    ("CALCIUM CHLORIDE", "C0765/02"),
    ("CALCIUM FORMATE", "C0780/01"),
    ("CALCIUM STARATE", "C0855/01"),
    ("CALENDUM", "C0990/08"),
    ("CAMCURE 2979", "C1881/06"),
    ("CAMCURE W287", "C1881/08"),
    ("CAMSPEED 3054", "C1881/05"),
    ("CEEFAST ALPHA BLUE 15.0 (U)", "C2700/29"),
    ("CEEFAST BETA BLUE (U)", "C2700/30"),
    ("CEEFAST CHROMOCYANINE", "C2700/12"),
    ("CEEFAST CHROMOCYANINE GREEN", "C2700/12"),
    ("CEEFAST GREEN 7(U)", "C2700/31"),
    ("CEEFAST RED 48.2", "C2700/36"),
    ("CEEFAST VIOLET TONER 777", "C2700/37"),
    ("CEEFST GREEN B 807", "C2700/32"),
    ("CEEROX BLACK OXIDE", "C2700/04"),
    ("CEEROX BLACK OXIDE 330", "C2700/04"),
    ("CEEROX BROWN OXIDE", "C2700/33"),
    ("CEEROX RED OXIDE 130", "C2700/07"),
    ("CEEROX RED OXIDE 445", "C2700/34"),
    ("CEEROX RED OXIDE 473", "C2700/35"),
    ("CHINA CLAY CP POWDER(KAOLIN CLAY)", "C1005/01"),
    ("CHINA CLAY CP POWDER(KAOLIN)", "C1005/01"),
    ("CITRIC ACID MONOHYDRATE", "C1065/01"),
    ("CMC POWDER", "C0930/01"),
    ("DIETHANOLAMINE", "C1315/01"),
    ("DISPLAYER CF707", "C1185/01"),
    ("DOLOMITE", "C0900/02"),
    ("DRIED ALUMINIUM HYDROXIDE GEL", "C0330/02"),
    ("DYN A70", "C0145/01"),
    ("EASTMAN TEXANOL", "C0030/01"),
    ("EMERI SAND", "C1470/01"),
    ("EPOXY CURING AGENT LITE 2401", "C1881/07"),
    ("EPOXY CURING AGENT NC 541", "C1881/02"),
    ("FINESET 35", "C1610/01"),
    ("FORMALDIHYDE", "C1650/01"),
    ("FORMIC ACID", "C1665/01"),
    ("GALAXY SLES", "C3510/01"),
    ("GINOPOL (SLS POWDER)", "C3510/02"),
    ("GLOBAMINE GREEN", "C1745/01"),
    ("GLYCERINE", "C1755/01"),
    ("GYPSUM POWDER", "C0870/01"),
    ("HIMFLOW CRETE HRWR 3J02 55%", "C2835/01"),
    ("HIND HFR - WD 500", "C2835/02"),
    ("HIND HFR - WD 500 C2835/07", "C2835/02"),
    ("HIND MOULD RELEASE OB", "C1200/01"),
    ("HYDRATED LIME", "C0795/01"),
    ("HYDROSOFT SRF 50", "C2835/06"),
    ("INDOLIGA PSR50(K)", "C2835/06"),
    ("IPA", "C2010/01"),
    ("KELCOCRETE DG-F", "C0145/04"),
    ("LAPOX AH 428", "C1882/01"),
    ("LAPOX AH 713", "C1880/01"),
    ("LAPOX B-47", "C0615/02"),
    ("LAPOX B11", "C0615/01"),
    ("LIME STONE", "C0750/08"),
    ("LUBOLICE", "C2520/01"),
    ("MAK KOTE", "C0632/01"),
    ("MDEA", "C2280/01"),
    ("MEK", "C2190/01"),
    ("MERGAL K14", "C3215/01"),
    ("METHYL ISOBUTYL KETONE", "C2265/01"),
    ("MHEC", "C2235/01"),
    ("MICRO SILICA 85%", "C2310/03"),
    ("MICRO SILICA 92%", "C2310/02"),
    ("MUSCLUER OX ULTRA MARINE BLUE CI 2900", "C2700/28"),
    ("MUSCULAR OXIDE ULFRAMARINE BLUE PIGMENTS CI-2900", "C2700/28"),
    ("NC 513", "C1500/02"),
    ("NC 541", "C1881/02"),
    ("NC 558", "C1881/01"),
    ("NX 5454", "C1881/04"),
    ("OPC CEMENT", "C0990/05"),
    ("ORTHO PHOSPHORIC ACID", "C2595/01"),
    ("PCE 128 (POLY CARBOXYLATE ETHER)", "C2835/08"),
    ("PECEVIS 100 PS", "C0145/03"),
    ("PEG  400", "C2885/01"),
    ("PHOSPHORIC ACID", "C2595/01"),
    ("PIGMENTS GREEN B  807/811", "C2700/32"),
    ("POLY ACRALAMIDE", "C2745/01"),
    ("POLY ACRYLAMIDE", "C2745/01"),
    ("POTASSIUM LITHIUM SILICATE KL25", "C3601/01"),
    ("PPC CEMENT", "C0990/07"),
    ("PRECIPATED CALCIUM CARBONATE", "C0750/09"),
    ("PROPLYLENE GLYCOL", "C2370/01"),
    ("PUTEC 3255", "C2795/01"),
    ("PVA 2488", "C3245/01"),
    ("QUARTZ POWDER(300 Mesh or 45 Micron)", "C3255/07"),
    ("QUARTZ SAND(-300 to 75)", "C3255/04"),
    ("R 85", "C2835/06"),
    ("RDP 1    5010", "C4139/01"),
    ("RDP 2 5044", "C4140/01"),
    ("RESILANE GTMS", "C2585/02"),
    ("RHEO PLUS", "C0485/01"),
    ("RTC-12(2,2,4 TRIMETHYL1,3PENTANEDIOL MONOISOBUTYRATE)", "C0030/02"),
    ("SAND 2.36", "C3345/07"),
    ("SAND 600 MICRON", "C3345/16"),
    ("SAPCO NDW", "C1190/01"),
    ("SBR LATEX", "C3795/02"),
    ("SHUTTEROL RA", "C1200/01"),
    ("SILICA FLOUR(400 Mesh or 37 Micron)", "C3345/01"),
    ("SILICA POWDER", "C3345/01"),
    ("SINGLE POLYMER", "C3305/01"),
    ("SLES 230 KG", "C3510/01"),
    ("SNF LIQUID", "C3570/01"),
    ("SNF POWDER", "C3585/01"),
    ("SNF POWDER (sodium nepthalene sulphonate)", "C3585/01"),
    ("SODA ASH(Light)", "C3435/02"),
    ("SODIUM CARBONATE(Light)", "C3435/02"),
    ("SODIUM GLUCONATE", "C3465/01"),
    ("SODIUM HYDROXIDE solution", "C3480/01"),
    ("SODIUM LIGNO 01", "C3525/02"),
    ("SODIUM NITRATE", "C3540/01"),
    ("SODIUM SHULPHATE", "C3615/01"),
    ("SODIUM SILICATE", "C3600/01"),
    ("SODIUM SILICOFLUORIDE", "C3460/01"),
    ("SODIUM SULPHATE", "C3615/01"),
    ("SODIUM THIOCYANATE", "C3630/01"),
    ("SOLVENT C9", "C3680/01"),
    ("SUGAR", "C3810/01"),
    ("SULPHAMIC ACID", "C3825/01"),
    ("TALCUM POWDER KOHINOOR", "C3885/01"),
    ("TEA 99%", "C4005/01"),
    ("TECHNOCEL-500-I", "C2445/01"),
    ("TIO2 ®", "C3960/01"),
    ("UNIWET 3048", "C0676/02"),
    ("WHITE CEMENT", "C0990/03"),
    ("XYLINE", "C4230/01"),
    ("YELLOW OXIDE", "C2700/08"),
    ("ZINC DUST", "C2700/14"),
    ("ZINC PHOSPHATE", "C2700/27"),
]
# ── Official Material Master — imported from Codification_for_System.xlsx
# (provided by the plant team, 2026-08-07). Format: (lab_code, name, procurement_code, category, status)
# procurement_code is None and status is 'Pending Code Confirmation' for the handful of items
# where the source sheet had a code collision the plant QC head still needs to resolve —
# see Codification_for_System_REVIEWED.xlsx for the flagged rows. Do not guess these codes.
SEED_MATERIALS_MASTER = [
    ("C0330/02", "ALUMINIUM HYDROXIDE GEL DRIED", "R1001", "Raw Material", "Confirmed"),
    ("C0345/01", "ALUMINIUM SULPHATE IRON FREE GRADE", "R1002", "Raw Material", "Confirmed"),
    ("C0765/02", "CALCIUM CHLORIDE SOLID(FUSED)", "R1003", "Raw Material", "Confirmed"),
    ("C0780/01", "CALCIUM FORMATE POWDER", "R1004", "Raw Material", "Confirmed"),
    ("C0795/01", "CALCIUM HYDROXIDE (HYDRATED LIME)", "R1005", "Raw Material", "Confirmed"),
    ("C3435/01", "SODIUM CARBONATE", "R1006", "Raw Material", "Confirmed"),
    ("C3540/01", "SODIUM NITRATE", "R1007", "Raw Material", "Confirmed"),
    ("C3630/01", "SODIUM THIOCYANATE", "R1008", "Raw Material", "Confirmed"),
    ("C1065/01", "CITRIC ACID MONOHYDRATE POWDER", "R1201", "Raw Material", "Confirmed"),
    ("C1665/01", "FORMIC ACID (85%)", "R1202", "Raw Material", "Confirmed"),
    ("C2490/01", "NONYL PHENOL ETHOXYLATE", "R1203", "Raw Material", "Confirmed"),
    ("C3825/01", "SULPHAMIC ACID", "R1204", "Raw Material", "Confirmed"),
    ("C0676/01", "BYK 9076", "R1401", "Raw Material", "Confirmed"),
    ("C0676/02", "Uniwet 3048", "R1405", "Raw Material", "Confirmed"),
    ("C3135/01", "POTASSIUM DICHROMATE", "R1402", "Raw Material", "Confirmed"),
    ("C2585/01", "SILANE BASED ADHESION PROMOTER(BYK 4511)", "R1403", "Raw Material", "Confirmed"),
    ("C2585/02", "SILANE BASED ADHESION PROMOTER(RESIL GTMS)", "R1404", "Raw Material", "Confirmed"),
    ("C3510/01", "SODIUM LAURYL ETHER SULPHATE", "R1601", "Raw Material", "Confirmed"),
    ("C1755/01", "GLYCERINE", "R1801", "Raw Material", "Confirmed"),
    ("C2010/01", "ISOPROPYL ALCOHOL", "R1802", "Raw Material", "Confirmed"),
    ("C3480/01", "SODIUM HYDROXIDE SOLUTION", "R2201", "Raw Material", "Confirmed"),
    ("C2280/01", "METHYLDIETHANOLAMINE (MDEA)", "R2401", "Raw Material", "Confirmed"),
    ("C4005/01", "TRIETHANOLAMINE (TEA) - 99%", "R2402", "Raw Material", "Confirmed"),
    ("C1315/01", "DIETHANOLAMINE(DEA)", "R2403", "Raw Material", "Confirmed"),
    ("C1260/01", "DIBUTYLTIN DILAURATE", "R2601", "Raw Material", "Confirmed"),
    ("C0930/01", "CARBOXYMETHYL CELLULOSE LV", "R2801", "Raw Material", "Confirmed"),
    ("C1935/01", "HYDROXYETHYL CELLULOSE", "R2802", "Raw Material", "Confirmed"),
    ("C2205/01", "METHYL HYDROXY ETHYL CELLULOSE (40000PF)", "R2803", "Raw Material", "Confirmed"),
    ("C2205/02", "METHYL HYDROXY ETHYL CELLULOSE (60000)", "R2804", "Raw Material", "Confirmed"),
    ("C2445/01", "NATURAL CELLULOSE FIBRES(TECHNOCEL C500)", "R2805", "Raw Material", "Confirmed"),
    ("C2445/02", "NATURAL CELLULOSE FIBRES(ARBOCEL PWC 500 )", "R2806", "Raw Material", "Confirmed"),
    ("C0990/03", "CEMENT - WHITE", "R3001", "Raw Material", "Confirmed"),
    ("C0990/05", "CEMENT (OPC) 53 GRADE", "R3002", "Raw Material", "Confirmed"),
    ("C0990/07", "CEMENT PPC(AMBUJA/NUVOCO)", "R3003", "Raw Material", "Confirmed"),
    ("C0990/10", "CEMENT PPC(DALMIA)", "R3004", "Raw Material", "Confirmed"),
    ("C0990/11", "CEMENT PPC(AMBUJA/NUVOCO) Siliguri", "R3005", "Raw Material", "Confirmed"),
    ("C0485/01", "ANTISETTLING AGENT (RHEOPLUS)", "R3201", "Raw Material", "Confirmed"),
    ("C1610/01", "FINESET 35", "R3202", "Raw Material", "Confirmed"),
    ("C0665/01", "BUTYL CELLOSOLVE", "R3401", "Raw Material", "Confirmed"),
    ("C0030/01", "2,2,4-TRIMETHYL-1,3-PENTANEDIOL MONO (2-METHYL PROPANATE)(TEXANOL)", "R3402", "Raw Material", "Confirmed"),
    ("C0480/01", "ANTIFOAM", "R3602", "Raw Material", "Confirmed"),
    ("C0677/01", "BYK 054", "R3603", "Raw Material", "Confirmed"),
    ("C1185/01", "DEFOAMER FOR PC (DYN 575/DISPLAIRE 707)", "R3604", "Raw Material", "Confirmed"),
    ("C1190/01", "DEFOAMER FOR EMULSION (SAPCO NDW)", "R3605", "Raw Material", "Confirmed"),
    ("C2780/01", "POLYESTER FIBER 6MM(RECRON)", "R4401", "Raw Material", "Confirmed"),
    ("C2780/02", "POLYESTER FIBER 12MM(RECRON)", "R4402", "Raw Material", "Confirmed"),
    ("C0525/02", "BARIUM SULPHATE (OFF COLOURED)", "R4601", "Raw Material", "Confirmed"),
    ("C0750/08", "CALCIUM CARBONATE- 300 MESH", "R4602", "Raw Material", "Confirmed"),
    ("C0750/06", "CALCIUM CARBONATE (STEARATE COATED) (-45 MICRONS)", "R4603", "Raw Material", "Confirmed"),
    ("C0900/02", "CALCIUM/MAGNESIUM CARBONATE- DOLOMITE 45 MICRONE", "R4604", "Raw Material", "Confirmed"),
    ("C3210/01", "PRECIPITATED SILICA", "R4605", "Raw Material", "Confirmed"),
    ("C3345/01", "SILICA FLOUR (<300 Mesh)", "R4606", "Raw Material", "Confirmed"),
    ("C3345/03", "SILICA FLOUR 45micron (325 MESH)", "R4607", "Raw Material", "Confirmed"),
    ("C3345/17", "SILICA FLOUR 37micron (400 MESH)", "R4608", "Raw Material", "Confirmed"),
    ("C3885/01", "TALC- MAGNESIUM SILICATE", "R4609", "Raw Material", "Confirmed"),
    ("C1666/01", "FRAGNANCE – LEMON DT", "R4801", "Raw Material", "Confirmed"),
    ("C1880/01", "HARDENER FOR EPOXY(AMIDE BASED- LAPOX AH713)", "R5001", "Raw Material", "Confirmed"),
    ("C1881/01", "HARDENER FOR EPOXY(PHENOLALKAMINE BASED- CARDOLITE NC558)", "R5002", "Raw Material", "Confirmed"),
    ("C1881/02", "HARDENER FOR EPOXY(PHENOLALKAMINE BASED- CARDOLITE NC541)", "R5003", "Raw Material", "Confirmed"),
    ("C1881/04", "HARDENER FOR EPOXY(PHENOLALKAMINE BASED- CARDOLITE NX 5454)", "R5004", "Raw Material", "Confirmed"),
    ("C1882/01", "HARDENER FOR EPOXY(AMINE BASED- LAPOX AH 428)", "R5005", "Raw Material", "Confirmed"),
    ("C1200/01", "DEMOULDING OIL (SERVO CONMOULD 12/HIND MOULD RELEASE OB)", "R5601", "Raw Material", "Confirmed"),
    ("C2520/01", "OLEIC ACID (LUBOLIC GRADE)", "R1205", "Raw Material", "Confirmed"),
    ("C2835/01", "POLYCARBOXYLIC ETHER (LIQUID) - DYN E 35 (55%)", "R6001", "Raw Material", "Confirmed"),
    ("C2835/02", "POLYCARBOXYLIC ETHER (LIQUID) (DYN E 95 (50%)/HYDROSOFT WD 500)", "R6002", "Raw Material", "Confirmed"),
    ("C2835/03", "POLYCARBOXYLIC ETHER (LIQUID) (PCT 135)", "R6003", "Raw Material", "Confirmed"),
    ("C2835/06", "POLYCARBOXYLIC ETHER (LIQUID) - DYN R 85", "R6004", "Raw Material", "Confirmed"),
    ("C2835/08", "POLYCARBOXYLIC ETHER POWDER", "R6005", "Raw Material", "Confirmed"),
    ("C2595/01", "ORTHO PHOSPHORIC ACID (85%)", "R1206", "Raw Material", "Confirmed"),
    ("C2700/04", "PIGMENT - INORGANIC - IRON OXIDE BLACK", "R6402", "Raw Material", "Confirmed"),
    ("C2700/05", "PIGMENT - INORGANIC - IRON OXIDE BLACK PIGMENT", "R6403", "Raw Material", "Confirmed"),
    ("C2700/07", "PIGMENT - INORGANIC - IRON OXIDE RED PIGMENT", "R6404", "Raw Material", "Confirmed"),
    ("C2700/08", "PIGMENT - INORGANIC - IRON OXIDE YELLOW PIGMENT", "R6405", "Raw Material", "Confirmed"),
    ("C2700/12", "PIGMENT - INORGANIC CHROMOCYANINE GREEN-1753", "R6406", "Raw Material", "Confirmed"),
    ("C2700/26", "PIGMENT - RED OXIDE COLORANT PR101", "R6407", "Raw Material", "Confirmed"),
    ("C2700/27", "PIGMENT - ZINC PHOSPHATE PIGMENT", "R6408", "Raw Material", "Confirmed"),
    ("C2700/28", "PIGMENT-ULTRAMARINE BLUE", "R6409", "Raw Material", "Confirmed"),
    ("C3960/01", "TITANIUM DIOXIDE (RUTILE) SULPHATE PROCESSED", "R6410", "Raw Material", "Confirmed"),
    ("C2700/29", "PIGMENT-CEEFAST ALPHA BLUE 15:0 (U)", "R6411", "Raw Material", "Confirmed"),
    ("C2700/30", "PIGMENT-CEEFAST BETA BLUE (U)", "R6412", "Raw Material", "Confirmed"),
    ("C2700/31", "PIGMENT-CEEFAST GREEN 7 (U)", "R6413", "Raw Material", "Confirmed"),
    ("C2700/32", "PIGMENT-CEEFAST GREEN  B 807", "R6414", "Raw Material", "Confirmed"),
    ("C2700/33", "PIGMENT-CEEROX BROWN OXIDE", "R6415", "Raw Material", "Confirmed"),
    ("C2700/34", "PIGMENT-CEEROX RED OXIDE 445", "R6416", "Raw Material", "Confirmed"),
    ("C2700/35", "PIGMENT-CEEROX RED OXIDE 473", "R6417", "Raw Material", "Confirmed"),
    ("C2700/36", "PIGMENT-CEEFAST RED 48:2", "R6401", "Raw Material", "Confirmed"),
    ("C2700/37", "PIGMENT-CEEFAST VIOLET TONER 777", "R6418", "Raw Material", "Confirmed"),
    ("C2700/38", "PIGMENT-CEEFAST MIDDLE CHROME( E)", "R6419", "Raw Material", "Confirmed"),
    ("C0090/01", "ACRYLIC COPOLYMER EMULSION(BONDEX 5800)", "R6601", "Raw Material", "Confirmed"),
    ("C0090/02", "ACRYLIC COPOLYMER EMULSION(KEMICRYL 2505)", "R6602", "Raw Material", "Confirmed"),
    ("C3780/01", "STYRENE ACRYLIC COPOLYMER EMULSION(BONDEX J400)", "R6603", "Raw Material", "Confirmed"),
    ("C3781/02", "STYRENE ACRYLIC COPOLYMER EMULSION(BONDEX J76C)", "R6604", "Raw Material", "Confirmed"),
    ("C3782/01", "WATER-BASED DISPERSION OR EMULSION OF ACRYLIC AND STYRENE COPOLYMER WITH FINE PARTICLES(BONDEX 5295)", "R6605", "Raw Material", "Confirmed"),
    ("C3795/01", "STYRENE BUTADIENE RUBBER LATEX (STYROFAN D623)", "R6606", "Raw Material", "Confirmed"),
    ("C3795/02", "STYRENE BUTADIENE RUBBER LATEX (COLOURCHEM)", "R6609", "Raw Material", "Confirmed"),
    ("C4139/01", "REDISPERSIBLE POWDER(VINNAPAS 5010N)", "R6607", "Raw Material", "Confirmed"),
    ("C4140/01", "REDISPERSIBLE POWDER(VINNAPAS 5044)", "R6608", "Raw Material", "Confirmed"),
    ("C0140/01", "ACRYLIC-POLYURATAHNE HYBRID POLYMER(CARBOSET CA1009I)", "R6801", "Raw Material", "Confirmed"),
    ("C2885/01", "POLYETHYLENE GLYCOL 400", "R7001", "Raw Material", "Confirmed"),
    ("C3525/02", "SODIUM LIGNOSULPHONATE POWDER (SAPPI – SOUTH AFRICA)", "R7002", "Raw Material", "Confirmed"),
    ("C3570/01", "SNF(40%)-HIMADRI", "R7003", "Raw Material", "Confirmed"),
    ("C3585/01", "SNF(POWDER)-HIMADRI", "R7004", "Raw Material", "Confirmed"),
    ("C1985/01", "IPDI(BASONAT I)", "R7201", "Raw Material", "Confirmed"),
    ("C2795/01", "POLYESTER BASED PU DISPERSION(PUTEC 3255)", "R7202", "Raw Material", "Confirmed"),
    ("C3067/01", "POLYURATHANE COATING SOLVENT BASED(HIND HYDRO FLEX PU)", "R7203", "Raw Material", "Confirmed"),
    ("C1650/01", "FORMALDEHYDE SOLUTION (METHANOL STABILISED)", "R7601", "Raw Material", "Confirmed"),
    ("C3215/01", "PRESERVATIVE(MERGAL K-14)", "R7602", "Raw Material", "Confirmed"),
    ("C0615/01", "BISPHENOL A EPOXY RESIN(LAPOX B11)", "R7801", "Raw Material", "Confirmed"),
    ("C1500/02", "EPOXY REACTIVE DILUENTS (CARDOLITE NC 513)", "R7802", "Raw Material", "Confirmed"),
    ("C2810/01", "POLYESTER RESIN CASULE(300 X 32)", "R7803", "Raw Material", "Confirmed"),
    ("C2810/02", "POLYESTER RESIN CASULE(300 X 40)", "R7804", "Raw Material", "Confirmed"),
    ("C0870/01", "CALCIUM SULPHATE - GYPSUM", "R8001", "Raw Material", "Confirmed"),
    ("C2370/01", "MONO PROPYLENE GLYCOL", "R8002", "Raw Material", "Confirmed"),
    ("C3465/01", "SODIUM GLUCONATE POWDER", "R8003", "Raw Material", "Confirmed"),
    ("C3810/01", "SUGAR – SUCROSE", "R8004", "Raw Material", "Confirmed"),
    ("C3460/01", "SODIUM SILICOFLUORIDE", "R8201", "Raw Material", "Confirmed"),
    ("C3615/01", "SODIUM SULPHATE", "R8202", "Raw Material", "Confirmed"),
    ("C3255/04", "QUARTZ SAND (75-300)", "R8402", "Raw Material", "Confirmed"),
    ("C3345/07", "SILICA SAND (0.15-2mm)", "R8403", "Raw Material", "Confirmed"),
    ("C3345/16", "SILICA SAND DRY(<600 Mic)", "R8404", "Raw Material", "Confirmed"),
    ("C3065/01", "POLYSULPHIDE SEALANT POUR GRADE(HIND SEALANT PS)", "T3000", "Raw Material", "Confirmed"),
    ("C3070/01", "POLYURATHANE SEALANT 1K(HIND SEALANT PU)", "T3002", "Raw Material", "Confirmed"),
    ("C2775/01", "POLYDIMETHYL POLYSILOXANE(Aquaphobe WR2)", "R8801", "Raw Material", "Confirmed"),
    ("C3170/01", "POTASSIUM METHYL SILICONATE(SILRES BS 16)", "R8802", "Raw Material", "Confirmed"),
    ("C3600/01", "SODIUM SILICATE SOLUTION (wt. ratio 3.30)", "R9001", "Raw Material", "Confirmed"),
    ("C3601/01", "POTASSIUM LITHIUM SILICATE", "R9002", "Raw Material", "Confirmed"),
    ("C2075/01", "LIQUID HINDERED AMINE STABILIZER(POLYSORB 292)", "R9201", "Raw Material", "Confirmed"),
    ("C2190/01", "METHYL ETHYL KETONE", "R9202", "Raw Material", "Confirmed"),
    ("C2265/01", "METHYL ISOBUTYL KETONE", "R9203", "Raw Material", "Confirmed"),
    ("C2745/01", "POLYACRYLAMIDE", "R6610", "Raw Material", "Confirmed"),
    ("C4230/01", "XYLENE", "R9204", "Raw Material", "Confirmed"),
    ("C0145/01", "ACRYLIC TYPE VMA - DYN A70", "R9801", "Raw Material", "Confirmed"),
    ("C0145/02", "ACRYLIC VMA(BONDEX T60/INDOFIL ASE 60)", "R9802", "Raw Material", "Confirmed"),
    ("C0145/03", "PECEVIS 100", "R9805", "Raw Material", "Confirmed"),
    ("C1680/01", "FUMED SILICA/MICRO SILICA", "R9803", "Raw Material", "Confirmed"),
    ("C1685/01", "HYDROPHILIC FUMES SILICA(AEROSIL 200)", "R9804", "Raw Material", "Confirmed"),
    ("C3455/01", "SODIUM FLUORIDE", "R1009", "Raw Material", "Confirmed"),
    ("C0361/02", "BITUMINUS COATING(ELASTOCRYL EMB)", "R7204", "Raw Material", "Confirmed"),
    ("C3068/01", "POLYURATHANE GROUT SINGLE COMPONENT(HYDROGUARDIAN- DHP 2000)", "R7205", "Raw Material", "Confirmed"),
    ("C3069/01", "POLYURATHANE GROUT DOUBLE COMPONENT(HYDROGUARDIAN-DHP 9000)", "R7206", "Raw Material", "Confirmed"),
    ("C2310/01", "MICROSILICA (DENSIFIED) 92%", "R3006", "Raw Material", "Confirmed"),
    ("C2310/02", "MICROSILICA (UNDENSIFIED) 92%", "R3007", "Raw Material", "Confirmed"),
    ("C2310/03", "MICROSILICA (UNDENSIFIED) 85%", "R3008", "Raw Material", "Confirmed"),
    ("C3195/01", "POWDER DEFOAMER(ADDITIVE 5154)", "R3601", "Raw Material", "Confirmed"),
    ("C0855/01", "CALCIUM STEARATE POWDER", "R4610", "Raw Material", "Confirmed"),
    ("C0615/02", "BISPHENOL A EPOXY RESIN(LAPOX B47)", "R7805", "Raw Material", "Confirmed"),
    ("C3255/07", "QURTZ SAND (45 Micron/300 Mesh)", "R8405", "Raw Material", "Confirmed"),
    ("C0990/09", "Calamdum", "R3009", "Raw Material", "Confirmed"),
    ("C0315/01", "Aluminium Powder", "R5201", "Raw Material", "Confirmed"),
    ("C1881/05", "CAMSPEED 3054", "R5006", "Raw Material", "Confirmed"),
    ("C1881/06", "HARDENER FOR EPOXY(CAMCURE 2979)", "R5007", "Raw Material", "Confirmed"),
    ("C1881/07", "HARDENER FOR EPOXY(PHENOLALKAMINE BASED- CARDOLITE LITE 2401)", "R5008", "Raw Material", "Confirmed"),
    ("C2700/14", "ZINC METAL PIGMENT", "R5202", "Raw Material", "Confirmed"),
    ("X40001", "50% SOLUTION OF BONDEX T-60", None, "Process/Intermediate", "Confirmed"),
    ("X50001", "2% SOLUTION OF HEC", None, "Process/Intermediate", "Confirmed"),
    ("X50002", "10% SOLUTION OF SHMP", None, "Process/Intermediate", "Confirmed"),
    ("X60001", "1% SOLUTION OF AMMONIA", None, "Process/Intermediate", "Confirmed"),
    ("X70001", "80% SOLUTION OF DEA", None, "Process/Intermediate", "Confirmed"),
    ("X80001", "FLOOR WASTAGE POWDER MATERIAL", None, "Process/Intermediate", "Confirmed"),
    ("X90001", "TIO2 PASTE", None, "Process/Intermediate", "Confirmed"),
    ("X90002", "CRETE 1", None, "Process/Intermediate", "Confirmed"),
    ("X90003", "CRETE 2", None, "Process/Intermediate", "Confirmed"),
    ("C1005/01", "CHINA CLAY (KAOLIN)", "R4611", "Raw Material", "Confirmed"),
    ("C3245/01", "PVA 2488", "R1406", "Raw Material", "Confirmed"),
    ("C1881/08", "HARDENER FOR EPOXY(CAMCURE W287)", "R5009", "Raw Material", "Confirmed"),
    ("C3345/01", "Silica Powder(300 mesh)", "R4612", "Raw Material", "Confirmed"),
    ("C0250/01", "Baraytes Powder(400 mesh)", "R4613", "Raw Material", "Confirmed"),
    ("C1745/01", "Globamine Green", "R1407", "Raw Material", "Confirmed"),
    ("C3680/01", "Solvesso 100", "R9205", "Raw Material", "Confirmed"),
    ("C0600/01", "Benzoyl Alcohol", "R9206", "Raw Material", "Confirmed"),
    ("C1881/03", "Cardolite NX 5198", "R5010", "Raw Material", "Confirmed"),
    ("C1505/01", "Resicare AIC", "R1408", "Raw Material", "Confirmed"),
    ("C1190/02", "AFA 2KI", "R3606", "Raw Material", "Confirmed"),
    ("C3345/09", "1 mm down sand", "R8406", "Raw Material", "Confirmed"),
    ("C0885/01", "CSA Binder", "R3010", "Raw Material", "Confirmed"),
    ("C1620/01", "FLY ASH", "R3011", "Raw Material", "Confirmed"),
    ("C1620/02", "FLY ASH(Siliguri)", "R3012", "Raw Material", "Confirmed"),
    ("C1470/01", "EMERY GRIT(0.15 MM -2.36 MM)", "R8407", "Raw Material", "Confirmed"),
    ("C2385/01", "MTO", "R9207", "Raw Material", "Confirmed"),
    ("C4170/01", "WATER", "R9208", "Raw Material", "Confirmed"),
    ("C4200/01", "SAVCAT 40", "R4001", "Raw Material", "Confirmed"),
    ("C0185/01", "ALKYD RESIN", "R7806", "Raw Material", "Confirmed"),
    ("C3345/18", "<600 micron Siliguri", "R8408", "Raw Material", "Confirmed"),
    ("C3345/20", "-2.36 Sand Siliguri", "R8409", "Raw Material", "Confirmed"),
    ("C0750/09", "CALCIUM CARBONATE- PRECIPITATED (~1Mic)", "R4618", "Raw Material", "Confirmed"),
    ("C2415/01", "N,N-DIMETHYLANILINE", "R2602", "Raw Material", "Confirmed"),
    ("C1100/01", "COBALT OCTATE(6%)", "R2603", "Raw Material", "Confirmed"),
    ("C1100/02", "COBALT OCTATE(3%)", "R2604", "Raw Material", "Confirmed"),
    ("C0585/02", "BENZOYL PEROXIDE (75%)", "R2605", "Raw Material", "Confirmed"),
    ("C2815/01", "POLYESTER RESIN GP GRADE", "R7807", "Raw Material", "Confirmed"),
    ("C3510/02", "SODIUM LAURYL SULPHATE", "R1602", "Raw Material", "Confirmed"),
    ("C3305/01", "SINGLE POLYMER FOR PUTTY", "R6611", "Raw Material", "Confirmed"),
    ("C4035/01", "TRIETHYLENE TETRAMINE (T.E.T.)", "R5011", "Raw Material", "Confirmed"),
    ("C1995/01", "ISOPHORONE DIAMINE HARDENER(45)", "R5012", "Raw Material", "Confirmed"),
    ("C1995/02", "ISOPHORONE DIAMINE HARDENER(60)", "R5013", "Raw Material", "Confirmed"),
    ("C3255/02", "QUARTZ SAND 300 MESH (0.75mm - 0.425mm)", "R8410", "Raw Material", "Confirmed"),
    ("C2700/11", "PIGMENT - INORGANIC (MIDDLE CHROME -1322)", "R8420", "Raw Material", "Confirmed"),
    ("C3275/01", "RESICARE AIC", "R1410", "Raw Material", "Confirmed"),
    ("C3255/09", "QUARTZ SAND (-150 MICRON)(WHITE)", "R8411", "Raw Material", "Confirmed"),
    ("C1965/01", "ISOCYANATE RESIN ALIPHATIC-HDI-DESMODUR N75", "R7810", "Raw Material", "Confirmed"),
    ("C1980/01", "ISOCYANATE RESIN AROMATIC-MDI", "R7809", "Raw Material", "Confirmed"),
    ("C2945/01", "POLYOL RESIN(CARDOLITE NX9005)", "R7808", "Raw Material", "Confirmed"),
    ("C2360/01", "MOISTURE SCAVENGER AND STABILISER(ADDITIVE OF)", "R1409", "Raw Material", "Confirmed"),
    ("C1120/01", "COCO DI ETHANOL AMIDE", "R1207", "Raw Material", "Confirmed"),
    ("C0345/02", "ALUMINIUM SULPHATE IRON FREE GRADE(40%) SOLUTION", "R1012", "Raw Material", "Confirmed"),
    ("C0146/01", "AGGREGATE 20MM SINGUR", "R4614", "Raw Material", "Confirmed"),
    ("C0146/02", "AGGREGATE 20MM SILIGURI", "R4615", "Raw Material", "Confirmed"),
    ("C0147/01", "AGGREGATE 10MM SINGUR", "R4616", "Raw Material", "Confirmed"),
    ("C0147/01", "AGGREGATE 10MM SILIGURI", "R4617", "Raw Material", "Confirmed"),
    ("C0840/02", "CALCIUM NITRATE POWDER", "R8203", "Raw Material", "Confirmed"),
    ("C0485/02", "ANTISETTLING AGENT (ADDITIVE 5292)", "R3203", "Raw Material", "Confirmed"),
    ("C1995/03", "CARDOLITE NT 5901", "R5014", "Raw Material", "Confirmed"),
    ("C2700/39", "PIGMENT-CEEROX RED OXIDE 130", "R6420", "Raw Material", "Confirmed"),
    ("C2701/01", "PEARL GOLD- EMS 351", "R6421", "Raw Material", "Confirmed"),
    ("C2045/01", "JOINT FILLER BOARD", "R7400", "Raw Material", "Confirmed"),
    ("C3890/01", "TAPE- JOINT TPE(T-1MM: W-150 MM: L-50MM)", "R7401", "Raw Material", "Confirmed"),
    ("C1606/01", "FIBERMESH 45 GSM", "R4403", "Raw Material", "Confirmed"),
    ("C3065/03", "PU BASED PRIMER(HIND PRIME PU-250 GM)", "R7207", "Raw Material", "Confirmed"),
    ("C3068/02", "POLYURATHANE GROUT SINGLE COMPONENT(HIND HYDROFOAM PU SC)", "R7208", "Raw Material", "Confirmed"),
    ("C0145/04", "KELCOCRETE DG(DIUTAN GUM)", "R9806", "Raw Material", "Confirmed"),
    ("C2105/01", "LITHIUM NITRATE ANHYDROUS POWDER", "R8204", "Raw Material", "Confirmed"),
    ("C2195/01", "METHYL ETHYL KETONE PEROXIDE", "R2607", "Raw Material", "Confirmed"),
    ("C3066/01", "POLYSULPHIDE SEALANT GUN GRADE", "T3003", "Raw Material", "Confirmed"),
    ("C3435/02", "SODIUM CARBONATE(LIGHT)", "R1010", "Raw Material", "Confirmed"),
    ("C3645/02", "SODIUM THIOSULPHATE PENTAHYDRATE", "R1011", "Raw Material", "Confirmed"),
    ("C3755/01", "STONE DUST", "R4619", "Raw Material", "Confirmed"),
    ("C3855/01", "SULPHONATED MELAMINE FORMALDEHYDE CONDENSATE", "R7005", "Raw Material", "Confirmed"),
    ("P1000", "NM PLASTIC BOTTLE 500 ML WITH INNER, WH", None, "Packaging", "Confirmed"),
    ("P1100", "NM PLASTIC BOTTLE 1000 ML WITH INNER,WH", None, "Packaging", "Confirmed"),
    ("P1200", "NM PLASTIC BOTTLE 5000 ML WITH INNER,WH", None, "Packaging", "Confirmed"),
    ("P2000", "WM PLASTIC WHITE BOTTLE 100 ML WITH INNER, WOH", None, "Packaging", "Confirmed"),
    ("P2100", "WM PLASTIC WHITE BOTTLE 200 ML WITH INNER, WOH", None, "Packaging", "Confirmed"),
    ("P2200", "WM PLASTIC WHITE  BOTTLE 500 ML WITH INNER, WOH", None, "Packaging", "Confirmed"),
    ("P2300", "WM PLASTIC WHITE BOTTLE 1000 ML WITH INNER, WOH", None, "Packaging", "Confirmed"),
    ("P2400", "WM PLASTIC CLEAR BOTTLE 500 ML WITHOUT INNER", None, "Packaging", "Confirmed"),
    ("P3000", "WM PLASTIC WHITE 250 ML CONTAINER WITH INNER", None, "Packaging", "Confirmed"),
    ("P3100", "WM PLASTIC WHITE 500 ML CONTAINER WITH INNER", None, "Packaging", "Confirmed"),
    ("P3200", "WM PLASTIC CLEAR 500 ML CONTAINER WITHOUT INNER", None, "Packaging", "Confirmed"),
    ("P4000", "1LTR WHITE BUCKET WITHOUT HANDLE RED LID", None, "Packaging", "Confirmed"),
    ("P4100", "2LTR WHITE BUCKET WITH HANDLE RED LID", None, "Packaging", "Confirmed"),
    ("P4200", "5LTR WHITE BUCKET WITH HANDLE RED LID", None, "Packaging", "Confirmed"),
    ("P4300", "10LTR WHITE BUCKET WITH HANDLE RED LID", None, "Packaging", "Confirmed"),
    ("P4400", "20LTR WHITE BUCKET WITH HANDLE RED LID", None, "Packaging", "Confirmed"),
    ("P4500", "25LTR WHITE BUCKET WITH HANDLE RED LID", None, "Packaging", "Confirmed"),
    ("P5000", "210 LTR BLUE BARREL", None, "Packaging", "Confirmed"),
    ("P5100", "210 LTR WHITE BARREL", None, "Packaging", "Confirmed"),
    ("P5200", "235 LTR BLUE BARREL", None, "Packaging", "Confirmed"),
    ("P5300", "235 LTR WHITE BARREL", None, "Packaging", "Confirmed"),
    ("P5400", "50 LTR BLUE BARREL", None, "Packaging", "Confirmed"),
    ("P5500", "100 LTR BLUE BARREL", None, "Packaging", "Confirmed"),
    ("P5600", "1000 LTR IBC NEW", None, "Packaging", "Confirmed"),
    ("P5610", "1000 LTR IBC OLD", None, "Packaging", "Confirmed"),
    ("P6000", "HDPE COMMON BAG 30 KG WITH LINER", None, "Packaging", "Confirmed"),
    ("P6050", "HDPE BAG FOR PLASTWELL 40 KG WITH LINER", None, "Packaging", "Confirmed"),
    ("P6100", "HDPE BAG FOR BLOCKFIX 40 KG WITH LINER", None, "Packaging", "Confirmed"),
    ("P6110", "HDPE BAG FOR WALLSAFE 40 KG WITH LINER", None, "Packaging", "Confirmed"),
    ("P6150", "HDPE BAG FOR TILLEGLUE 1.0 20 KG WITH LINER", None, "Packaging", "Confirmed"),
    ("P6200", "HDPE BAG FOR TILLEGLUE 2.0 20 KG WITH LINER", None, "Packaging", "Confirmed"),
    ("P6250", "HDPE BAG FOR TILLEGLUE 3.0 20 KG WITH LINER", None, "Packaging", "Confirmed"),
    ("P6300", "HDPE BAG FOR TILLEGLUE 4.0 20 KG WITH LINER", None, "Packaging", "Confirmed"),
    ("P6350", "HDPE BAG FOR TILEGLUE 4.0 + 20 KG WITH LINER", None, "Packaging", "Confirmed"),
    ("P6400", "LOCKTIE 8 INCH", None, "Packaging", "Confirmed"),
    ("P6450", "LOCKTIE 10 INCH", None, "Packaging", "Confirmed"),
    ("P6500", "LOCKTIE 12 INCH", None, "Packaging", "Confirmed"),
    ("P6550", "POLYPACK CLEAR 2KG", None, "Packaging", "Confirmed"),
    ("P6600", "POLYPACK CLEAR 5KG", None, "Packaging", "Confirmed"),
    ("P6650", "POLYPACK WHITE 2KG", None, "Packaging", "Confirmed"),
    ("P6700", "POLYPACK WHITE 5KG", None, "Packaging", "Confirmed"),
    ("P6750", "POLYPACK CLEAR 30KG", None, "Packaging", "Confirmed"),
    ("P6800", "POLYPACK CLEAR 15KG", None, "Packaging", "Confirmed"),
    ("P7000", "20KG 5PLY COOMON CARTOON", None, "Packaging", "Confirmed"),
    ("P7050", "7PLY CARTOON- CONCAP R PRINTED", None, "Packaging", "Confirmed"),
    ("P7100", "EP BOND BA CARTOON-PRINTED(0.4+0.2KG WM X 12 UNIT)", None, "Packaging", "Confirmed"),
    ("P7150", "EP BOND BA CARTOON-PRINTED(2+1KG X 2 UNIT)", None, "Packaging", "Confirmed"),
    ("P7200", "CARTOON BOX(0.2KG X 24)-COMMON", None, "Packaging", "Confirmed"),
    ("P7250", "CARTOON BOX(0.5KGX 18 NOS.)-COMMON", None, "Packaging", "Confirmed"),
    ("P7300", "CARTOON BOX(1KGX 12 NOS.)-COMMON", None, "Packaging", "Confirmed"),
    ("P7350", "CARTOON BOX(600ML X 20 UNIT)-PRINTED PUSEAL", None, "Packaging", "Confirmed"),
    ("P7400", "CARTOON(0.5+0.5KG WM X 4) -EP COAT FGW PRINTED", None, "Packaging", "Confirmed"),
    ("P7410", "CARTOON(0.5+0.5KG WM)", None, "Packaging", "Confirmed"),
    ("P7450", "CARTOON(5KG X 4) -COMMON", None, "Packaging", "Confirmed"),
    ("P7500", "CARTOON(1KG X 15) -SUPERGROUT CG PRINTED", None, "Packaging", "Confirmed"),
    ("P7550", "CARTOON( 2+2 KG BUCKET x 2) -EP COAT FGW PRINTED", None, "Packaging", "Confirmed"),
    ("P7600", "CARTOON( 1KG BUCKET X 10 ) -REPCON CRACK X PRINTED", None, "Packaging", "Confirmed"),
    ("P7650", "CARTOON( 3KG BUCKET X 4 ) -REPCON CRACK X PRINTED", None, "Packaging", "Confirmed"),
    ("P7700", "CARTOON( 2+2 KG BUCKET x 2) -EP GROUT LV PRINTED", None, "Packaging", "Confirmed"),
    ("P7750", "CARTOON (0.25KG X 20)-PU SEAL PRIMER PRINTED", None, "Packaging", "Confirmed"),
    ("P7800", "CARTOON (600 ML X 20)-PU SEAL PRINTED", None, "Packaging", "Confirmed"),
    ("P7850", "ANCHOR PR CARTOON(1 KG)", None, "Packaging", "Confirmed"),
    ("ST1000", "0.2 KG STICKER-AQUAPROOF IW", None, "Label/Sticker", "Confirmed"),
    ("ST1050", "0.2 KG STICKER-ADMIX CG", None, "Label/Sticker", "Confirmed"),
    ("ST1100", "0.2 KG STICKER-ANCHOR PR PART 1", None, "Label/Sticker", "Confirmed"),
    ("ST2000", "0.5 KG STICKER-AQUAPROOF CRYSTALLINE", None, "Label/Sticker", "Confirmed"),
    ("ST2050", "0.5 KG STICKER- CEMBOND SBR", None, "Label/Sticker", "Confirmed"),
    ("ST2100", "0.5 KG STICKER-CEMCOAT AR", None, "Label/Sticker", "Confirmed"),
    ("ST2150", "0.5 KG STICKER-RUSTCURE", None, "Label/Sticker", "Confirmed"),
    ("ST2200", "0.5 KG STICKER-TILESMART AC", None, "Label/Sticker", "Confirmed"),
    ("ST2250", "0.5 KG STICKER-EP COAT FGW COMP A", None, "Label/Sticker", "Confirmed"),
    ("ST2260", "0.5 KG STICKER-EP COAT FGW COMP B", None, "Label/Sticker", "Confirmed"),
    ("ST3000", "1.0 kg STICKER-AQUAPROOF IW", None, "Label/Sticker", "Confirmed"),
    ("ST3050", "1.0 kg STICKER-CEMBOND SBR", None, "Label/Sticker", "Confirmed"),
    ("ST3100", "1.0 kg STICKER-CEMCOAT AR", None, "Label/Sticker", "Confirmed"),
    ("ST3110", "1kg COMMON STICKER FG", None, "Label/Sticker", "Confirmed"),
    ("ST3150", "1.0 kg STICKER-ELASTOCEM COMP B", None, "Label/Sticker", "Confirmed"),
    ("ST3200", "1.0 kg STICKER-ELASTOCEM FLEX COMP B", None, "Label/Sticker", "Confirmed"),
    ("ST3250", "1.0 kg STICKER-ELASTOCEM SUPER FLEX COMP B", None, "Label/Sticker", "Confirmed"),
    ("ST3300", "1.0 kg STICKER-ELASTOCAT", None, "Label/Sticker", "Confirmed"),
    ("ST3350", "1.0 kg STICKER-ELASTOCAT SR", None, "Label/Sticker", "Confirmed"),
    ("ST3400", "1.0 kg STICKER-RUSTCURE", None, "Label/Sticker", "Confirmed"),
    ("ST3410", "1.0 kg STICKER-TILESSMART AC", None, "Label/Sticker", "Confirmed"),
    ("ST3450", "1.0 kg STICKER-CEMCOAT PRIMER", None, "Label/Sticker", "Confirmed"),
    ("ST3500", "1.0 kg STICKER-AQUAPROOF PRIMER PU W COMP A", None, "Label/Sticker", "Confirmed"),
    ("ST3550", "1.0 kg STICKER-AQUAPROOF PRIMER PU W COMP B", None, "Label/Sticker", "Confirmed"),
    ("ST3600", "1.0 kg STICKER-SILICOCOAT", None, "Label/Sticker", "Confirmed"),
    ("ST3660", "1.0 kg STICKER-EP COAT ZINK", None, "Label/Sticker", "Confirmed"),
    ("ST3700", "1.0 kg STICKER-REPCON CRACK-X", None, "Label/Sticker", "Confirmed"),
    ("ST3750", "5.0 kg STICKER-AQUAPROOF IW", None, "Label/Sticker", "Confirmed"),
    ("ST3800", "5.0 kg STICKER-CEMBOND SBR", None, "Label/Sticker", "Confirmed"),
    ("ST3850", "5.0 kg STICKER-CEMCOAT AR", None, "Label/Sticker", "Confirmed"),
    ("ST3900", "5.0 kg STICKER-ELASTOCEM COMP B", None, "Label/Sticker", "Confirmed"),
    ("ST3950", "5.0 kg STICKER-ELASTOCEM FLEX COMP B", None, "Label/Sticker", "Confirmed"),
    ("ST4000", "5.0 kg STICKER-ELASTOCEM SUPER FLEX COMP B", None, "Label/Sticker", "Confirmed"),
    ("ST4050", "5.0 kg STICKER-ELASTOCAT", None, "Label/Sticker", "Confirmed"),
    ("ST4100", "5.0 kg STICKER-ELASTOCAT SR", None, "Label/Sticker", "Confirmed"),
    ("ST4150", "5.0 kg STICKER-RUSTCURE", None, "Label/Sticker", "Confirmed"),
    ("ST4200", "5.0 kg STICKER-TILESSMART AC", None, "Label/Sticker", "Confirmed"),
    ("ST4250", "5.0 kg STICKER-CEMCOAT PRIMER", None, "Label/Sticker", "Confirmed"),
    ("ST4300", "5.0 kg STICKER-AQUAPROOF PRIMER PU W COMP A", None, "Label/Sticker", "Confirmed"),
    ("ST4310", "5.0 kg STICKER-AQUAPROOF PRIMER PU W COMP B", None, "Label/Sticker", "Confirmed"),
    ("ST4350", "5.0 kg STICKER-SILICOCOAT", None, "Label/Sticker", "Confirmed"),
    ("ST4400", "5.0 kg STICKER-EP COAT ZINK", None, "Label/Sticker", "Confirmed"),
    ("ST4450", "10 kg STICKER-AQUAPROOF IW", None, "Label/Sticker", "Confirmed"),
    ("ST4500", "10 kg STICKER-CEMBOND SBR", None, "Label/Sticker", "Confirmed"),
    ("ST4550", "10 kg STICKER-CEMCOAT AR", None, "Label/Sticker", "Confirmed"),
    ("ST4600", "10 kg STICKER-AQUAPROOF PU W1", None, "Label/Sticker", "Confirmed"),
    ("ST4650", "10 kg STICKER-ELASTOCAT", None, "Label/Sticker", "Confirmed"),
    ("ST4700", "10 kg STICKER-ELASTOCAT SR", None, "Label/Sticker", "Confirmed"),
    ("ST4750", "15 kg STICKER-ELASTOCEM FLEX", None, "Label/Sticker", "Confirmed"),
    ("ST4800", "20 kg STICKER-AQUAPROOF IW", None, "Label/Sticker", "Confirmed"),
    ("ST4850", "20 kg STICKER-CEMBOND SBR", None, "Label/Sticker", "Confirmed"),
    ("ST4900", "20 kg STICKER-CEMCOAT AR", None, "Label/Sticker", "Confirmed"),
    ("ST4950", "20 kg STICKER-AQUAPROOF PU W1", None, "Label/Sticker", "Confirmed"),
    ("ST5000", "20 kg STICKER-ELASTOCAT", None, "Label/Sticker", "Confirmed"),
    ("ST5050", "20 kg STICKER-ELASTOCAT SR", None, "Label/Sticker", "Confirmed"),
    ("ST5100", "20 kg STICKER-CEMCOAT PRIMER", None, "Label/Sticker", "Confirmed"),
    ("ST5150", "20 kg STICKER-SILICOCOAT", None, "Label/Sticker", "Confirmed"),
    ("ST5200", "20 kg STICKER-ELASTOCEM", None, "Label/Sticker", "Confirmed"),
    ("ST5250", "20 kg STICKER-ELASTOCEM SUPERFLEX", None, "Label/Sticker", "Confirmed"),
    ("ST5300", "20 kg STICKER-AQUAPROOP PU S1", None, "Label/Sticker", "Confirmed"),
    ("ST5350", "20 kg STICKER-CONSET CA", None, "Label/Sticker", "Confirmed"),
    ("ST5400", "20 kg STICKER-HIPROCAST 20E", None, "Label/Sticker", "Confirmed"),
    ("ST5450", "20 kg STICKER-HIPROCAST 30E", None, "Label/Sticker", "Confirmed"),
    ("ST5500", "20 kg STICKER-HIPROCAST 50E", None, "Label/Sticker", "Confirmed"),
    ("ST5550", "250 kg STICKER-ESTEEMA 501", None, "Label/Sticker", "Confirmed"),
    ("ST5600", "250 kg STICKER-ESTEEMA 1001", None, "Label/Sticker", "Confirmed"),
    ("ST5650", "250 kg STICKER-ESTEEMA 1501", None, "Label/Sticker", "Confirmed"),
    ("ST5700", "250 kg STICKER-ESTEEMA 2001", None, "Label/Sticker", "Confirmed"),
    ("ST5750", "250 kg STICKER-ESTEEMA PLUS 2501", None, "Label/Sticker", "Confirmed"),
    ("ST5800", "250 kg STICKER-ESTEEMA PLUS 2751", None, "Label/Sticker", "Confirmed"),
    ("ST5850", "250 kg STICKER-ESTEEMA PLUS 3001", None, "Label/Sticker", "Confirmed"),
    ("ST5900", "250 kg STICKER-HIPROCAST 20E", None, "Label/Sticker", "Confirmed"),
    ("ST5950", "250 kg STICKER-HIPROCAST 30E", None, "Label/Sticker", "Confirmed"),
    ("ST6000", "250 kg STICKER-HIPROCAST 50E", None, "Label/Sticker", "Confirmed"),
    ("ST6050", "200 LTR STICKER-SHUTTEROL RA", None, "Label/Sticker", "Confirmed"),
    ("ST6100", "200 LTR STICKER-SHUTTEROL RAS", None, "Label/Sticker", "Confirmed"),
    ("ST6150", "200 LTR STICKER-SHUTTEROL RAE", None, "Label/Sticker", "Confirmed"),
    ("ST6200", "200 LTR STICKER-SHUTTEROL RA EXTRA", None, "Label/Sticker", "Confirmed"),
    ("ST6250", "275 kg STICKER-SPRAYCON A", None, "Label/Sticker", "Confirmed"),
    ("ST6300", "275 kg STICKER-SPRAYCON AF", None, "Label/Sticker", "Confirmed"),
    ("ST6350", "275 kg STICKER-SPRAYCON AF(LV)", None, "Label/Sticker", "Confirmed"),
    ("ST6400", "STICKER - ANCHOR PR PART 2", None, "Label/Sticker", "Confirmed"),
]

# ── Legacy free-text material names (used in historical ERP records) mapped
# to their canonical name above, matched via shared internal lab code. This lets
# old rm_batches/bom_lines/etc. rows keep displaying correctly without rewriting
# historical data. Format: (legacy_name, canonical_name)
SEED_MATERIAL_ALIASES = [
    ("ADDAGE PCE 128 (POLY CARBOXYLATE ETHER) POWDER", "POLYCARBOXYLIC ETHER POWDER"),
    ("ADDAGE PCE POWDER", "POLYCARBOXYLIC ETHER POWDER"),
    ("ALPHOX-200 H", "NONYL PHENOL ETHOXYLATE"),
    ("ALPOX 200", "NONYL PHENOL ETHOXYLATE"),
    ("ALUMINIUM SULPHATE", "ALUMINIUM SULPHATE IRON FREE GRADE"),
    ("ANTI FOAM POWDER", "ANTIFOAM"),
    ("APCOTEX TSN 651", "STYRENE BUTADIENE RUBBER LATEX (STYROFAN D623)"),
    ("AQUAPHOBE WR2", "POLYDIMETHYL POLYSILOXANE(Aquaphobe WR2)"),
    ("BARYTES POWDER 2511", "BARIUM SULPHATE (OFF COLOURED)"),
    ("BONDEX 5800", "ACRYLIC COPOLYMER EMULSION(BONDEX 5800)"),
    ("BONDEX J-400", "STYRENE ACRYLIC COPOLYMER EMULSION(BONDEX J400)"),
    ("BONDEX T 60", "ACRYLIC VMA(BONDEX T60/INDOFIL ASE 60)"),
    ("BUTYL CELLSOLOV", "BUTYL CELLOSOLVE"),
    ("BYK-9076", "BYK 9076"),
    ("Bondex 5295", "WATER-BASED DISPERSION OR EMULSION OF ACRYLIC AND STYRENE COPOLYMER WITH FINE PARTICLES(BONDEX 5295)"),
    ("C 400", "STYRENE ACRYLIC COPOLYMER EMULSION(BONDEX J400)"),
    ("C 76", "STYRENE ACRYLIC COPOLYMER EMULSION(BONDEX J76C)"),
    ("C-2835/03  PCT135", "POLYCARBOXYLIC ETHER (LIQUID) (PCT 135)"),
    ("CALCIUM CARBONATE 1000", "CALCIUM CARBONATE- 300 MESH"),
    ("CALCIUM CHLORIDE", "CALCIUM CHLORIDE SOLID(FUSED)"),
    ("CALCIUM FORMATE", "CALCIUM FORMATE POWDER"),
    ("CALCIUM STARATE", "CALCIUM STEARATE POWDER"),
    ("CAMCURE 2979", "HARDENER FOR EPOXY(CAMCURE 2979)"),
    ("CAMCURE W287", "HARDENER FOR EPOXY(CAMCURE W287)"),
    ("CAMSPEED 3054", "CAMSPEED 3054"),
    ("CEEFAST ALPHA BLUE 15.0 (U)", "PIGMENT-CEEFAST ALPHA BLUE 15:0 (U)"),
    ("CEEFAST BETA BLUE (U)", "PIGMENT-CEEFAST BETA BLUE (U)"),
    ("CEEFAST CHROMOCYANINE", "PIGMENT - INORGANIC CHROMOCYANINE GREEN-1753"),
    ("CEEFAST CHROMOCYANINE GREEN", "PIGMENT - INORGANIC CHROMOCYANINE GREEN-1753"),
    ("CEEFAST GREEN 7(U)", "PIGMENT-CEEFAST GREEN 7 (U)"),
    ("CEEFAST RED 48.2", "PIGMENT-CEEFAST RED 48:2"),
    ("CEEFAST VIOLET TONER 777", "PIGMENT-CEEFAST VIOLET TONER 777"),
    ("CEEFST GREEN B 807", "PIGMENT-CEEFAST GREEN  B 807"),
    ("CEEROX BLACK OXIDE", "PIGMENT - INORGANIC - IRON OXIDE BLACK"),
    ("CEEROX BLACK OXIDE 330", "PIGMENT - INORGANIC - IRON OXIDE BLACK"),
    ("CEEROX BROWN OXIDE", "PIGMENT-CEEROX BROWN OXIDE"),
    ("CEEROX RED OXIDE 130", "PIGMENT - INORGANIC - IRON OXIDE RED PIGMENT"),
    ("CEEROX RED OXIDE 445", "PIGMENT-CEEROX RED OXIDE 445"),
    ("CEEROX RED OXIDE 473", "PIGMENT-CEEROX RED OXIDE 473"),
    ("CHINA CLAY CP POWDER(KAOLIN CLAY)", "CHINA CLAY (KAOLIN)"),
    ("CHINA CLAY CP POWDER(KAOLIN)", "CHINA CLAY (KAOLIN)"),
    ("CITRIC ACID MONOHYDRATE", "CITRIC ACID MONOHYDRATE POWDER"),
    ("CMC POWDER", "CARBOXYMETHYL CELLULOSE LV"),
    ("DIETHANOLAMINE", "DIETHANOLAMINE(DEA)"),
    ("DISPLAYER CF707", "DEFOAMER FOR PC (DYN 575/DISPLAIRE 707)"),
    ("DOLOMITE", "CALCIUM/MAGNESIUM CARBONATE- DOLOMITE 45 MICRONE"),
    ("DRIED ALUMINIUM HYDROXIDE GEL", "ALUMINIUM HYDROXIDE GEL DRIED"),
    ("DYN A70", "ACRYLIC TYPE VMA - DYN A70"),
    ("EASTMAN TEXANOL", "2,2,4-TRIMETHYL-1,3-PENTANEDIOL MONO (2-METHYL PROPANATE)(TEXANOL)"),
    ("EMERI SAND", "EMERY GRIT(0.15 MM -2.36 MM)"),
    ("EPOXY CURING AGENT LITE 2401", "HARDENER FOR EPOXY(PHENOLALKAMINE BASED- CARDOLITE LITE 2401)"),
    ("EPOXY CURING AGENT NC 541", "HARDENER FOR EPOXY(PHENOLALKAMINE BASED- CARDOLITE NC541)"),
    ("FINESET 35", "FINESET 35"),
    ("FORMALDIHYDE", "FORMALDEHYDE SOLUTION (METHANOL STABILISED)"),
    ("FORMIC ACID", "FORMIC ACID (85%)"),
    ("GALAXY SLES", "SODIUM LAURYL ETHER SULPHATE"),
    ("GINOPOL (SLS POWDER)", "SODIUM LAURYL SULPHATE"),
    ("GLOBAMINE GREEN", "Globamine Green"),
    ("GLYCERINE", "GLYCERINE"),
    ("GYPSUM POWDER", "CALCIUM SULPHATE - GYPSUM"),
    ("HIMFLOW CRETE HRWR 3J02 55%", "POLYCARBOXYLIC ETHER (LIQUID) - DYN E 35 (55%)"),
    ("HIND HFR - WD 500", "POLYCARBOXYLIC ETHER (LIQUID) (DYN E 95 (50%)/HYDROSOFT WD 500)"),
    ("HIND HFR - WD 500 C2835/07", "POLYCARBOXYLIC ETHER (LIQUID) (DYN E 95 (50%)/HYDROSOFT WD 500)"),
    ("HIND MOULD RELEASE OB", "DEMOULDING OIL (SERVO CONMOULD 12/HIND MOULD RELEASE OB)"),
    ("HYDRATED LIME", "CALCIUM HYDROXIDE (HYDRATED LIME)"),
    ("HYDROSOFT SRF 50", "POLYCARBOXYLIC ETHER (LIQUID) - DYN R 85"),
    ("INDOLIGA PSR50(K)", "POLYCARBOXYLIC ETHER (LIQUID) - DYN R 85"),
    ("IPA", "ISOPROPYL ALCOHOL"),
    ("KELCOCRETE DG-F", "KELCOCRETE DG(DIUTAN GUM)"),
    ("LAPOX AH 428", "HARDENER FOR EPOXY(AMINE BASED- LAPOX AH 428)"),
    ("LAPOX AH 713", "HARDENER FOR EPOXY(AMIDE BASED- LAPOX AH713)"),
    ("LAPOX B-47", "BISPHENOL A EPOXY RESIN(LAPOX B47)"),
    ("LAPOX B11", "BISPHENOL A EPOXY RESIN(LAPOX B11)"),
    ("LIME STONE", "CALCIUM CARBONATE- 300 MESH"),
    ("LUBOLICE", "OLEIC ACID (LUBOLIC GRADE)"),
    ("MDEA", "METHYLDIETHANOLAMINE (MDEA)"),
    ("MEK", "METHYL ETHYL KETONE"),
    ("MERGAL K14", "PRESERVATIVE(MERGAL K-14)"),
    ("METHYL ISOBUTYL KETONE", "METHYL ISOBUTYL KETONE"),
    ("MICRO SILICA 85%", "MICROSILICA (UNDENSIFIED) 85%"),
    ("MICRO SILICA 92%", "MICROSILICA (UNDENSIFIED) 92%"),
    ("MUSCLUER OX ULTRA MARINE BLUE CI 2900", "PIGMENT-ULTRAMARINE BLUE"),
    ("MUSCULAR OXIDE ULFRAMARINE BLUE PIGMENTS CI-2900", "PIGMENT-ULTRAMARINE BLUE"),
    ("NC 513", "EPOXY REACTIVE DILUENTS (CARDOLITE NC 513)"),
    ("NC 541", "HARDENER FOR EPOXY(PHENOLALKAMINE BASED- CARDOLITE NC541)"),
    ("NC 558", "HARDENER FOR EPOXY(PHENOLALKAMINE BASED- CARDOLITE NC558)"),
    ("NX 5454", "HARDENER FOR EPOXY(PHENOLALKAMINE BASED- CARDOLITE NX 5454)"),
    ("OPC CEMENT", "CEMENT (OPC) 53 GRADE"),
    ("ORTHO PHOSPHORIC ACID", "ORTHO PHOSPHORIC ACID (85%)"),
    ("PCE 128 (POLY CARBOXYLATE ETHER)", "POLYCARBOXYLIC ETHER POWDER"),
    ("PECEVIS 100 PS", "PECEVIS 100"),
    ("PEG  400", "POLYETHYLENE GLYCOL 400"),
    ("PHOSPHORIC ACID", "ORTHO PHOSPHORIC ACID (85%)"),
    ("PIGMENTS GREEN B  807/811", "PIGMENT-CEEFAST GREEN  B 807"),
    ("POLY ACRALAMIDE", "POLYACRYLAMIDE"),
    ("POLY ACRYLAMIDE", "POLYACRYLAMIDE"),
    ("POTASSIUM LITHIUM SILICATE KL25", "POTASSIUM LITHIUM SILICATE"),
    ("PPC CEMENT", "CEMENT PPC(AMBUJA/NUVOCO)"),
    ("PRECIPATED CALCIUM CARBONATE", "CALCIUM CARBONATE- PRECIPITATED (~1Mic)"),
    ("PROPLYLENE GLYCOL", "MONO PROPYLENE GLYCOL"),
    ("PUTEC 3255", "POLYESTER BASED PU DISPERSION(PUTEC 3255)"),
    ("PVA 2488", "PVA 2488"),
    ("QUARTZ POWDER(300 Mesh or 45 Micron)", "QURTZ SAND (45 Micron/300 Mesh)"),
    ("QUARTZ SAND(-300 to 75)", "QUARTZ SAND (75-300)"),
    ("R 85", "POLYCARBOXYLIC ETHER (LIQUID) - DYN R 85"),
    ("RDP 1    5010", "REDISPERSIBLE POWDER(VINNAPAS 5010N)"),
    ("RDP 2 5044", "REDISPERSIBLE POWDER(VINNAPAS 5044)"),
    ("RESILANE GTMS", "SILANE BASED ADHESION PROMOTER(RESIL GTMS)"),
    ("RHEO PLUS", "ANTISETTLING AGENT (RHEOPLUS)"),
    ("SAND 2.36", "SILICA SAND (0.15-2mm)"),
    ("SAND 600 MICRON", "SILICA SAND DRY(<600 Mic)"),
    ("SAPCO NDW", "DEFOAMER FOR EMULSION (SAPCO NDW)"),
    ("SBR LATEX", "STYRENE BUTADIENE RUBBER LATEX (COLOURCHEM)"),
    ("SHUTTEROL RA", "DEMOULDING OIL (SERVO CONMOULD 12/HIND MOULD RELEASE OB)"),
    ("SINGLE POLYMER", "SINGLE POLYMER FOR PUTTY"),
    ("SLES 230 KG", "SODIUM LAURYL ETHER SULPHATE"),
    ("SNF LIQUID", "SNF(40%)-HIMADRI"),
    ("SNF POWDER", "SNF(POWDER)-HIMADRI"),
    ("SNF POWDER (sodium nepthalene sulphonate)", "SNF(POWDER)-HIMADRI"),
    ("SODA ASH(Light)", "SODIUM CARBONATE(LIGHT)"),
    ("SODIUM CARBONATE(Light)", "SODIUM CARBONATE(LIGHT)"),
    ("SODIUM GLUCONATE", "SODIUM GLUCONATE POWDER"),
    ("SODIUM HYDROXIDE solution", "SODIUM HYDROXIDE SOLUTION"),
    ("SODIUM LIGNO 01", "SODIUM LIGNOSULPHONATE POWDER (SAPPI – SOUTH AFRICA)"),
    ("SODIUM NITRATE", "SODIUM NITRATE"),
    ("SODIUM SHULPHATE", "SODIUM SULPHATE"),
    ("SODIUM SILICATE", "SODIUM SILICATE SOLUTION (wt. ratio 3.30)"),
    ("SODIUM SILICOFLUORIDE", "SODIUM SILICOFLUORIDE"),
    ("SODIUM SULPHATE", "SODIUM SULPHATE"),
    ("SODIUM THIOCYANATE", "SODIUM THIOCYANATE"),
    ("SOLVENT C9", "Solvesso 100"),
    ("SUGAR", "SUGAR – SUCROSE"),
    ("SULPHAMIC ACID", "SULPHAMIC ACID"),
    ("TALCUM POWDER KOHINOOR", "TALC- MAGNESIUM SILICATE"),
    ("TEA 99%", "TRIETHANOLAMINE (TEA) - 99%"),
    ("TECHNOCEL-500-I", "NATURAL CELLULOSE FIBRES(TECHNOCEL C500)"),
    ("TIO2 ®", "TITANIUM DIOXIDE (RUTILE) SULPHATE PROCESSED"),
    ("UNIWET 3048", "Uniwet 3048"),
    ("WHITE CEMENT", "CEMENT - WHITE"),
    ("XYLINE", "XYLENE"),
    ("YELLOW OXIDE", "PIGMENT - INORGANIC - IRON OXIDE YELLOW PIGMENT"),
    ("ZINC DUST", "ZINC METAL PIGMENT"),
    ("ZINC PHOSPHATE", "PIGMENT - ZINC PHOSPHATE PIGMENT"),
]

# ── Official Finished Goods Master — imported from finished_good_codification.xlsx
# (provided by the plant team, 2026-08-13). Format: (name, code, status).
# code is None and status is 'Pending Code Confirmation' for the handful of
# items the source sheet had not yet assigned a code to -- do not guess it here.
SEED_FINISHED_GOODS_MASTER = [
    ("AQUAPROOF CRYSTALLINE - 30KGS", "FPS_C050_30K", "Confirmed"),
    ("AQUAPROOF C.T.X 2K", "FPS_D700", "Confirmed"),
    ("AQUAPROOF IW 10 KGS", "FPS_C010_10K", "Confirmed"),
    ("AQUAPROOF IW 1 KGS", "FPS_C010_1K", "Confirmed"),
    ("AQUAPROOF IW - 200 GM", "FPS_C010_0.2K", "Confirmed"),
    ("AQUAPROOF IW 20 KGS", "FPS_C010_20K", "Confirmed"),
    ("AQUAPROOF IW 5 KGS", "FPS_C010_5K", "Confirmed"),
    ("AQUAPROOF PU PRIMER - W - 10 KGS", "FPS_C1300_10K", "Confirmed"),
    ("AQUAPROOF PU S1", "FPS_C1200-20K", "Confirmed"),
    ("AQUAPROOF PU W1", "FPS_C400_5K", "Confirmed"),
    ("AQUAPROOF PU W1 20 KGS", "FPS_C400_20K", "Confirmed"),
    ("Bitukot 1K - 20 Kgs", "FPS_C800_20K", "Confirmed"),
    ("Bitukot 1K - 5 Kgs", "FPS_C800_5K", "Confirmed"),
    ("CEMBOND SBR 0.5 KGS", "FPS_C100_0.5K", "Confirmed"),
    ("CEMBOND SBR 10 KGS", "FPS_C100_10K", "Confirmed"),
    ("CEMBOND SBR 1 KGS", "FPS_C100_1K", "Confirmed"),
    ("CEMBOND SBR 20 KGS", "FPS_C100_20", "Confirmed"),
    ("CEMBOND SBR 5 KG", "FPS_C100_5K", "Confirmed"),
    ("CEMCOAT AR -10 KGS", "FPS_C200_10K", "Confirmed"),
    ("CEMCOAT AR - 1 KG", "FPS_C200_1K", "Confirmed"),
    ("CEMCOAT AR -20 Kg", "FPS_C200_20K", "Confirmed"),
    ("CEMCOAT AR - 5 KGS", "FPS_C200_5K", "Confirmed"),
    ("CEMCOAT PRIMER - 5 KGS", "FPS_C150_5K", "Confirmed"),
    ("CEMGROUT AD - 250 GM", "FPS_E250_0.25K", "Confirmed"),
    ("CEMGROUT GP2 - 30 Kgs", "FPS_E150_30K", "Confirmed"),
    ("CEMGROUT GP - 30 Kgs", "FPS_E050_30K", "Confirmed"),
    ("CONSET R", "FPS_A090_250K", "Confirmed"),
    ("CRETE VMA", "FPS_A650_200K", "Confirmed"),
    ("CUREWELL ARB", "FPS_B300_230L", "Confirmed"),
    ("ELASTOCEM - 20 kg", "FPS_C250_20K", "Confirmed"),
    ("ELASTOCEM - 40 Kg", "FPS_C250_40K", "Confirmed"),
    ("ELASTOCEM - 4 KGS", "FPS_C250_4K", "Confirmed"),
    ("ELASTOCOAT - 10 Kgs", "FPS_C500_10K", "Confirmed"),
    ("ELASTOCOAT - 20 Kgs", "FPS_C500_20K", "Confirmed"),
    ("EP Bond BA", "FPS_D600_0.6K", "Confirmed"),
    ("EP COAT FGW - 1 Kgs", "FPS_C1500_1K", "Confirmed"),
    ("EP COAT FGW - 4 KGS", "FPS_C1500_4K", "Confirmed"),
    ("ESTEEMA 1001", "FPS_A300_250K", "Confirmed"),
    ("ESTEEMA 1501", "FPS_A350_250K", "Confirmed"),
    ("ESTEEMA 2001", "FPS_A400_250K", "Confirmed"),
    ("ESTEEMA PLUS 2501", "FPS_A500_250K", "Confirmed"),
    ("ESTEEMA PLUS 2751", "FPS_A550_250K", "Confirmed"),
    ("ESTEEMA PLUS 3001", "FPS_A600_250K", "Confirmed"),
    ("HARDTOP M", "FPS_F200_30K", "Confirmed"),
    ("HARDTOP NM", "FPS_F100", "Confirmed"),
    ("HARDTOP NM- 30 Kg", "FPS_F100_30K", "Confirmed"),
    ("HIPROCAST 20E", "FPS_A200_250K", "Confirmed"),
    ("HIPROCAST 30E", "FPS_A230_250K", "Confirmed"),
    ("HIPROCAST 50E", "FPS_A250_250K", "Confirmed"),
    ("HIPROCAST 50HE", None, "Pending Code Confirmation"),
    ("MICRETE- 30 KGS", "FPS_D100_30K", "Confirmed"),
    ("PLAST AEA", "FPS_A170_200K", "Confirmed"),
    ("POLYSEAL G 4 KGS", "FPS_G300_4K", "Confirmed"),
    ("PUMP PRIMO", "FPS_B400_0.2K", "Confirmed"),
    ("Pu Seal", "FPS_G100", "Confirmed"),
    ("Pu Seal 2K", "FPS_G800_4K", "Confirmed"),
    ("PU SEAL PRIMER", "FPS_G400_0.25K", "Confirmed"),
    ("REPCON CRACK- X - 3 Kgs", "FPS_D500_3K", "Confirmed"),
    ("REPCON EP UWP - 4 KGS", "FPS_D800_4K", "Confirmed"),
    ("REPCON FC - 30 KGS", "FPS_D200_30K", "Confirmed"),
    ("RUST CURE - 1 KG", "FPS_D1100_1K", "Confirmed"),
    ("RUST CURE - 500 GM", "FPS_D1100_0.5K", "Confirmed"),
    ("SHUTTEROL RA", "FPS_B550_230L", "Confirmed"),
    ("SHUTTEROL RAE", "FPS_B600_230L", "Confirmed"),
    ("SHUTTEROL RAE (EXTRA)", "FPS_B650_230L", "Confirmed"),
    ("SHUTTEROL RAS", "FPS_B500_230L", "Confirmed"),
    ("SILICOCOAT 1 KGS", "FPS_C950_1K", "Confirmed"),
    ("SILICOCOAT 5 KGS", "FPS_C950_5K", "Confirmed"),
    ("Spraycon AF", "FPS_A140_275K", "Confirmed"),
    ("SPRAYCON AF (LV)", "FPS_A145_275K", "Confirmed"),
    ("SPRAYCON AFP", "FPS_A800_20K", "Confirmed"),
    ("SUPERGROUT CG - Alpine Blue - 1Kgs", "FPS_H800_1K013", "Confirmed"),
    ("SUPERGROUT CG - Burgundy -1Kg", "FPS_H800_1K012", "Confirmed"),
    ("SUPERGROUT CG - Chocolate - 1 Kgs", "FPS_H800_1K044", "Confirmed"),
    ("SUPERGROUT CG - Native Grey - 1 Kgs", "FPS_H800_1K027", "Confirmed"),
    ("SUPERGROUT CG - Smoke Grey - 1 Kgs", "FPS_H800_1K031", "Confirmed"),
    ("SUPERGROUT CG - Terracotta - 1 Kgs", "FPS_H800_1K021", "Confirmed"),
    ("SUPERGROUT EG - FP- Quarry Red-3.8Kg & Resin Kit-1.2Kg", "FPS_H900_5K022", "Confirmed"),
    ("TOPHARD LS", "FPS_F400_250K", "Confirmed"),
    ("TOPHARD SS", "FPS_F300_250K", "Confirmed"),
    ("UW PLAST", "FPS_A180_230K", "Confirmed"),
    ("ADMIX CG 200ML", "FPS_H1000_0.2L", "Confirmed"),
    ("Anchor PR - 1kg", "FPS_E1150_1K", "Confirmed"),
    ("AQUAPROOF CRYSTALLINE - 5KGS", "FPS_C050_5K", "Confirmed"),
    ("AQUAPROOF PU PRIMER - W - 20 KGS", "FPS_C1300_20K", "Confirmed"),
    ("BECK BOND EP 17", "FPS_F700", "Confirmed"),
    ("BECK BOND SLF 36", "FPS_F500", "Confirmed"),
    ("BITUCOAT PRIMER W - 20 Kgs", "FPS_C1100_20K", "Confirmed"),
    ("BLOCKFIX - 40Kgs", "FPS_H1100_40K", "Confirmed"),
    ("CEMCOAT AR - 500 ML", "FPS_C200_0.5K", "Confirmed"),
    ("CEMCOAT PRIMER - 1 KGS", "FPS_C150_1K", "Confirmed"),
    ("CEMCOAT PRIMER - 20 KGS", "FPS_C150_20K", "Confirmed"),
    ("CEMGROUT GP1 - 30 Kgs", "FPS_E050_30K", "Confirmed"),
    ("CONSET CA PLUS", "FPS_A900_250K", "Confirmed"),
    ("CONSET SL", "FPS_A950_275K", "Confirmed"),
    ("DRYMIXCRETE - 50 KGS", "FPS_H1500", "Confirmed"),
    ("EFFLOCOAT 1K - 20 KGS", "FPS_C900_20K", "Confirmed"),
    ("EFFLOCOAT 1K - 5 KGS", "FPS_C900_1K", "Confirmed"),
    ("ELASTOCEM FLEX - 15 KGS", "FPS_C300_15K", "Confirmed"),
    ("ELASTOCEM FLEX - 3 KGS", "FPS_C300_3K", "Confirmed"),
    ("ELASTOCEM FLEX - 60 KGS", "FPS_C300_60K", "Confirmed"),
    ("ELASTOCOAT - 1 Kgs", "FPS_C500_1K", "Confirmed"),
    ("ELASTOCOAT - 5 Kgs", "FPS_C500_5K", "Confirmed"),
    ("ELASTOCOAT-GREEN- 20 Kgs", "FPS_C500_20KGR", "Confirmed"),
    ("ELASTOCOAT-RED- 20 Kgs", "FPS_C500_20KRD", "Confirmed"),
    ("ELASTOCOAT SR - 10 KGS", "FPS_C600_10K", "Confirmed"),
    ("ELASTOCOAT SR - 1 KGS", "FPS_C600_1K", "Confirmed"),
    ("ELASTOCOAT SR - 20 KGS", "FPS_C600_20K", "Confirmed"),
    ("ELASTOCOAT SR - 5 KGS", "FPS_C600_5K", "Confirmed"),
    ("ELASTOCOAT-WHITE- 20 Kgs", "FPS_C500_20KWH", "Confirmed"),
    ("ELASTOCOAT XL 20 KGS", "FPS_C550_20K", "Confirmed"),
    ("EP BOND BA - 3 KG", "FPS_D600_3K", "Confirmed"),
    ("EP BOND BA - 600 GRAM", "FPS_D600_0.6K", "Confirmed"),
    ("EP COAT FG - 4 KGS", "FPS_C1450_4K", "Confirmed"),
    ("EP COAT FGW - 20 KGS", "FPS_C1500_20K", "Confirmed"),
    ("EP COAT ZINC 1 KG", "FPS_D1200_1K", "Confirmed"),
    ("EP GROUT LV - 15 KGS", "FPS_E550_15K", "Confirmed"),
    ("EP GROUT LV - 3 KGS", "FPS_E550_3K", "Confirmed"),
    ("EP GROUT UW - 3 KGS", "FPS_E650_3K", "Confirmed"),
    ("EP GROUT UW - 4 KGS", "FPS_E650", "Confirmed"),
    ("FCSC MICROSILICA", "FPS_A750_20K", "Confirmed"),
    ("FIRSTSHINE - COPPER GLITTER - 100 GM", None, "Pending Code Confirmation"),
    ("FIRSTSHINE - SILVER GLITTER - 100 GM", None, "Pending Code Confirmation"),
    ("FLOOR HARDTOP NM- 25 Kg", "FPS_F100_30K", "Confirmed"),
    ("HARDTOP M - 30 KGS", "FPS_F200_30K", "Confirmed"),
    ("MEASURE CAP", None, "Pending Code Confirmation"),
    ("MICRETE- 5 KGS", "FPS_D100_5K", "Confirmed"),
    ("PLAST WELL -40 KGS", "FPS_H1400_40K", "Confirmed"),
    ("Plugcon - 1 Kgs", None, "Pending Code Confirmation"),
    ("Plugcon - 5 Kgs", None, "Pending Code Confirmation"),
    ("Polymer Bondex 400", None, "Pending Code Confirmation"),
    ("POLYSEAL G 6.5 KGS", "FPS_G300_6.5K", "Confirmed"),
    ("POLYSEAL P - 6.5 KGS", "FPS_G200_6.5K", "Confirmed"),
    ("Premix", None, "Pending Code Confirmation"),
    ("PU GROUT 1K", "FPS_E750_10K", "Confirmed"),
    ("PU GROUT 2 K", "FPS_E850_10K", "Confirmed"),
    ("Pu Seal 2K - 4kg", "FPS_G800_4K", "Confirmed"),
    ("Recron Fiber", None, "Pending Code Confirmation"),
    ("REPCON CRACK- X -1kg", "FPS_D500_1K", "Confirmed"),
    ("REPCON EP COAL TAR - 20 KGS", "FPS_D700_20K", "Confirmed"),
    ("REPCON EP TM - 6KG", "FPS_D900_6K", "Confirmed"),
    ("REPCON EP UWP - 1 KG", "FPS_D800_1K", "Confirmed"),
    ("REPCON FC - 5 KGS", "FPS_D200_5K", "Confirmed"),
    ("REPCON MICRETE- 30 KGS", "FPS_D100_30K", "Confirmed"),
    ("REPCON RUSTCURE", "FPS_D1100", "Confirmed"),
    ("REPCON TI - 25 KGS", "FPS_D300_25K", "Confirmed"),
    ("RUST CURE - 20 KG", "FPS_D1100_20K", "Confirmed"),
    ("RUST CURE - 5 KG", "FPS_D1100_5K", "Confirmed"),
    ("RXSOL", None, "Pending Code Confirmation"),
    ("SEAL TAPE ADHESIVE - 3 KGS", "FPS_G700_3K", "Confirmed"),
    ("SEAL TAPE TPE", "FPS_G500", "Confirmed"),
    ("SILICOCOAT 10 KGS", "FPS_C950_10K", "Confirmed"),
    ("SILICOCOAT 20 KGS", "FPS_C950_20K", "Confirmed"),
    ("SPECTRA FLOGUARD EH", "FPS_F800", "Confirmed"),
    ("SUPERGROUT CG -  Almond-1Kg", "FPS_H800_1K003", "Confirmed"),
    ("SUPERGROUT CG - Antique White - 1 Kgs", "FPS_H800_1K005", "Confirmed"),
    ("SUPERGROUT CG - AQUA BLUE -1Kg", "FPS_H800_1K017", "Confirmed"),
    ("SUPERGROUT CG - AUBURN-1KG", "FPS_H800_1K030", "Confirmed"),
    ("SUPERGROUT CG - Bloom-1Kg", "FPS_H800_1K029", "Confirmed"),
    ("SUPERGROUT CG - Blue -1Kg", "FPS_H800_1K054", "Confirmed"),
    ("SUPERGROUT CG - Bright White-1Kg", "FPS_H800_1K001", "Confirmed"),
    ("SUPERGROUT CG - BUFF -1Kg", "FPS_H800_1K007", "Confirmed"),
    ("SUPERGROUT CG - Canyon Red-1Kg", "FPS_H800_1K016", "Confirmed"),
    ("SUPERGROUT CG - Chocolate Brown - 1 Kgs", "FPS_H800_1K055", "Confirmed"),
    ("SUPERGROUT CG - CITRUS LIME - 1KG", "FPS_H800_1K040", "Confirmed"),
    ("SUPERGROUT CG -Cofee Brown-1kg", "FPS_H800_1K050", "Confirmed"),
    ("SUPERGROUT CG - Dusty Rose - 1 Kgs", "FPS_H800_1K006", "Confirmed"),
    ("SUPERGROUT CG - Gleaming Gold-1Kg", "FPS_H800_1K034", "Confirmed"),
    ("SUPERGROUT CG - Gold-1Kg", "FPS_H800_1K049", "Confirmed"),
    ("SUPERGROUT CG - Green-1Kg", "FPS_H800_1K056", "Confirmed"),
    ("SUPERGROUT CG - Grey -1Kg", "FPS_H800_1K053", "Confirmed"),
    ("SUPERGROUT CG - Ivory-1Kg", "FPS_H800_1K004", "Confirmed"),
    ("SUPERGROUT CG LINCOLN GREEN - 1 KG", "FPS_H800_1K035", "Confirmed"),
    ("SUPERGROUT CG - Lite Brown- 1kg", "FPS_H800_1K051", "Confirmed"),
    ("SUPERGROUT CG - Manyan Red-1Kg", "FPS_H800_1K018", "Confirmed"),
    ("SUPERGROUT CG - Marble Beigh-1Kg", "FPS_H800_1K011", "Confirmed"),
    ("SUPERGROUT CG - Mayan Red -1Kg", "FPS_H800_1K018", "Confirmed"),
    ("SUPERGROUT CG - Midnight Black-1Kg", "FPS_H800_1K010", "Confirmed"),
    ("SUPERGROUT CG - Off White-1Kg", "FPS_H800_1K002", "Confirmed"),
    ("SUPERGROUT CG - PEACH - 1Kg", "FPS_H800_1K043", "Confirmed"),
    ("SUPERGROUT CG - Raven-1Kg", "FPS_H800_1K015", "Confirmed"),
    ("SUPERGROUT CG - SANDY GOLD -1KG", "FPS_H800_1K057", "Confirmed"),
    ("SUPERGROUT CG - SAPHIRE-1KG", "FPS_H800_1K019", "Confirmed"),
    ("SUPERGROUT CG - Scamper-1Kg", "FPS_H800_1K036", "Confirmed"),
    ("SUPERGROUT CG - SEMILLON -1Kg", "FPS_H800_1K023", "Confirmed"),
    ("SUPERGROUT CG - Silk-1Kg", "FPS_H800_1K004", "Confirmed"),
    ("SUPERGROUT CG - Silver Shadow-1Kg", "FPS_H800_1K058", "Confirmed"),
    ("SUPERGROUT CG - SKY BLUE-1 KG", "FPS_H800_1K009", "Confirmed"),
    ("SUPERGROUT CG - SLATE GREY -1Kg", "FPS_H800_1K014", "Confirmed"),
    ("SUPERGROUT CG - Terracota-1Kg", "FPS_H800_1K021", "Confirmed"),
    ("SUPERGROUT CG - Terracota-1Kgs", "FPS_H800", "Confirmed"),
    ("SUPERGROUT CG - Trakotta - 1 Kg", "FPS_H800", "Confirmed"),
    ("SUPERGROUT CG - Umbra Slate-1Kg", "FPS_H800_1K026", "Confirmed"),
    ("SUPERGROUT CG - Vine-1Kg", "FPS_H800_1K032", "Confirmed"),
    ("SUPERGROUT EG - Antique White", "FPS_H900_1K005", "Confirmed"),
    ("SUPERGROUT EG - AQUA BLUE WITH GLITTER -1Kg", "FPS_H900_1K017", "Confirmed"),
    ("SUPERGROUT EG - Bright White - 1 Kg", "FPS_H900_1K001", "Confirmed"),
    ("SUPERGROUT EG - FP- 760g & Resin Kit - 240g", "FPS_H900", "Confirmed"),
    ("SUPERGROUT EG - FP- Alpine Blue-760g & Resin Kit - 240g", "FPS_H900_1K013", "Confirmed"),
    ("SUPERGROUT EG-FP- Black-3.8 Kg & Resin Kit-1.2 Kg", "FPS_H900_5K050", "Confirmed"),
    ("SUPERGROUT EG - FP- Bloom-760g & Resin Kit - 240g", "FPS_H900_1K029", "Confirmed"),
    ("SUPERGROUT EG - FP- Bright White-3.8Kg & Resin Kit-1.2Kg", "FPS_H900_5K001", "Confirmed"),
    ("SUPERGROUT EG - FP- Bright White-760g & Resin Kit - 240g", "FPS_H900_1K001", "Confirmed"),
    ("SUPERGROUT EG-FP-Brown-3.8KG & Resin Kit-1.2KG", "FPS_H900_5K051", "Confirmed"),
    ("SUPERGROUT EG-FP-Brown-760g & Resin Kit-240g", "FPS_H900_1K051", "Confirmed"),
    ("SUPERGROUT EG - FP- Burgundy-3.8Kg & Resin Kit-1.2Kg", "FPS_H900_5K012", "Confirmed"),
    ("SUPERGROUT EG - FP- Burgundy-760g & Resin Kit - 240g", "FPS_H900_1K012", "Confirmed"),
    ("SUPERGROUT EG - FP- Canyon Red-3.8Kg & Resin Kit - 1.2Kg", "FPS_H900_5K016", "Confirmed"),
    ("SUPERGROUT EG - FP- Canyon Red-760g & Resin Kit - 240g", "FPS_H900_1K016", "Confirmed"),
    ("SUPERGROUT EG - FP- Chocolate-760g & Resin Kit - 240g", "FPS_H900_1K044", "Confirmed"),
    ("SUPERGROUT EG - FP- Citrus Lime-3.8Kg & Resin Kit - 1.2Kg", "FPS_H900_5K040", "Confirmed"),
    ("SUPERGROUT EG - FP- Citrus Lime-760g & Resin Kit - 240g", "FPS_H900_1K040", "Confirmed"),
    ("SUPERGROUT EG-FP-COFFEE BROWN-3.8 KG & Resin Kit-1.2KG", "FPS_H900_5K052", "Confirmed"),
    ("SUPERGROUT EG-FP-COFFEE BROWN-760g & Resin Kit-240g", "FPS_H900_1K052", "Confirmed"),
    ("SUPERGROUT EG-FP-Dark Brown-3.8 KG & Resin Kit-1.2KG", "FPS_H900_5K053", "Confirmed"),
    ("SUPERGROUT EG-FP-Dark Brown-760g & Resin Kit-240g", "FPS_H900_1K053", "Confirmed"),
    ("SUPERGROUT EG-FP- Dark Grey-3.8KG & Resin Kit-1.2KG", "FPS_H900_5K054", "Confirmed"),
    ("SUPERGROUT EG-FP- Dark Grey-760g & Resin Kit-240g", "FPS_H900_1K054", "Confirmed"),
    ("SUPERGROUT EG - FP-Gleaming Gold-3.8Kg & Resin Kit-1.2Kg", "FPS_H900_5K034", "Confirmed"),
    ("SUPERGROUT EG-FP-GleamingGold760G+Resign kit 240G", "FPS_H900_1K034", "Confirmed"),
    ("SUPERGROUT EG-FP-Gold760G+Resign kit 240G", "FPS_H900_1K049", "Confirmed"),
    ("SUPERGROUT EG - FP- Gold Glitter (BR White)-760g & Resin Kit - 240g", "FPS_H900_1K001", "Confirmed"),
    ("SUPERGROUT EG - FP- Gold Glitter (Citrus Lime)-3.8Kg & Resin Kit-1.2Kg", "FPS_H900_5K040", "Confirmed"),
    ("SUPERGROUT EG - FP- Gold Glitter (Citrus Lime)-760g & Resin Kit - 240g", "FPS_H900_1K040", "Confirmed"),
    ("SUPERGROUT EG-FP-Grey-3.8KG & Resin Kit-1.2KG", "FPS_H900_5K055", "Confirmed"),
    ("SUPERGROUT EG-FP-Grey760G+Resign kit 240G", "FPS_H900_1K055", "Confirmed"),
    ("SUPERGROUT EG-FP-Ivory 3.8KG+Resign kit 1.2KG", "FPS_H900_5K004", "Confirmed"),
    ("SUPERGROUT EG-FP-Ivory 760G+Resign kit 240G", "FPS_H900_1K004", "Confirmed"),
    ("SUPERGROUT EG-FP-Jet Black-3.8 Kg & Resin Kit-1.2 Kg", "FPS_H900_5K056", "Confirmed"),
    ("SUPERGROUT EG-FP- Light Grey-3.8KG & Resin Kit-1.2KG", "FPS_H900_5K057", "Confirmed"),
    ("SUPERGROUT EG-FP-Light Grey-760g & Resin Kit-240g", "FPS_H900_1K057", "Confirmed"),
    ("SUPERGROUT EG - FP - Mayan Red-3.8 Kgs + 1.2 Kgs Resign Kit", "FPS_H900_5K018", "Confirmed"),
    ("SUPERGROUT EG - FP - Mayan Red-760G + 260G Resign Kit", "FPS_H900_1K018", "Confirmed"),
    ("SUPERGROUT EG-FP- Midnight Black-3.8kg & Resin Kit-1.2kg", "FPS_H900_5K010", "Confirmed"),
    ("SUPERGROUT EG-FP- Midnight Black-760g & Resin Kit-240g", "FPS_H900_1K010", "Confirmed"),
    ("SUPERGROUT EG -FP-MOCCA-3.8 KGS & Resin kit 1.2kgs", "FPS_H900_5K008", "Confirmed"),
    ("SUPERGROUT EG-FP-MOCCA 760G+Resign kit 240G", "FPS_H900_1K008", "Confirmed"),
    ("SUPERGROUT EG-FP-OFFWHITE 3.8kg + Resign kit 1.2kg", "FPS_H900_5K002", "Confirmed"),
    ("SUPERGROUT EG-FP-OFF WHITE 760g + Resign kit 240g", "FPS_H900_1K002", "Confirmed"),
    ("SUPERGROUT EG - FP- Peach-760g & Resin Kit - 240g", "FPS_H900_1K043", "Confirmed"),
    ("SUPERGROUT EG-FP-Platinum Grey760G+Resign kit 240G", "FPS_H900_1K020", "Confirmed"),
    ("SUPERGROUT EG-FP-RED 760G+Resign kit 240G", "FPS_H900_1K058", "Confirmed"),
    ("SUPERGROUT EG - FP- Sandy Gold-760g & Resin Kit - 240g", "FPS_H900_1K059", "Confirmed"),
    ("SUPERGROUT EG - FP- Silk-3.8Kg & Resin Kit-1.2Kg", "FPS_H900_5K004", "Confirmed"),
    ("SUPERGROUT EG - FP- Silk-760g & Resin Kit - 240g", "FPS_H900_1K004", "Confirmed"),
    ("SUPERGROUT EG - FP- Sky Blue-760g & Resin Kit - 240g", "FPS_H900_1K009", "Confirmed"),
    ("SUPERGROUT EG -FP -Slate Grey-3.8Kgs+ Resign kit 1.2kg", "FPS_H900_5K014", "Confirmed"),
    ("SUPERGROUT EG - FP- Slate Grey-760g & Resin Kit - 240g", "FPS_H900_1K014", "Confirmed"),
    ("SUPERGROUT EG -FP-SMOKE-3.8 KGS & Resin kit 1.2kgs", "FPS_H900_5K031", "Confirmed"),
    ("SUPERGROUT EG-FP- STEEL SMOG-760g & Resin Kit-240g", "FPS_H900_5K037", "Confirmed"),
    ("SUPERGROUT EG - FP- Terracota-3.8kg & Resin Kit - 1.2kg", "FPS_H900_5K021", "Confirmed"),
    ("SUPERGROUT EG - FP- Terracota-760g & Resin Kit - 240g", "FPS_H900_1K021", "Confirmed"),
    ("SUPERGROUT EG - FP-Umbra Slate-3.8Kg & Resin Kit-1.2Kg", "FPS_H900_5K026", "Confirmed"),
    ("SUPERGROUT EG-FP- Umbra Slate-760g & Resin Kit-240g", "FPS_H900_1K026", "Confirmed"),
    ("SUPERGROUT EG - GOLDEN SPARKLE – 760G & Resign Kit 240kg", "FPS_H900_1K049", "Confirmed"),
    ("SUPERGROUT EG -GOLDEN – 3.8 KG & Resign Kit 1.2kg", "FPS_H900_5K049", "Confirmed"),
    ("SUPERGROUT EG -GOLDEN – 760g & Resign Kit 240g", "FPS_H900_1K049", "Confirmed"),
    ("TILEGLUE-1.0-Grey-20Kgs", "FPS_H100_20K", "Confirmed"),
    ("TILEGLUE-2.0-Grey-20Kgs", "FPS_H200_20K", "Confirmed"),
    ("TILEGLUE-2.0-White-20Kgs", "FPS_H250_20K", "Confirmed"),
    ("TILEGLUE-3.0-Grey-20Kgs", "FPS_H300_20K", "Confirmed"),
    ("TILEGLUE-3.0-White-20kgs", "FPS_H350_20K", "Confirmed"),
    ("TILEGLUE-4.0-Grey-20Kgs", "FPS_H400_20K", "Confirmed"),
    ("TILEGLUE-4.0-White-20Kgs", "FPS_H450_20K", "Confirmed"),
    ("TILEGLUE-4.O+ Grey-20Kgs", "FPS_H500_20K", "Confirmed"),
    ("TILEGLUE-4.O+ -White-20Kgs", "FPS_H550_20K", "Confirmed"),
    ("TILEGLUE-5.0-Grey-20Kgs", None, "Pending Code Confirmation"),
    ("TILEGLUE-5.0-White-20Kgs", None, "Pending Code Confirmation"),
    ("Tileglue super 300 GM", "FPS_H700_0.3K", "Confirmed"),
    ("TILESMART AC 1 Ltr", "FPS_H1200_1K", "Confirmed"),
    ("TILESMART AC 500Ml", "FPS_H1200_0.5K", "Confirmed"),
    ("WALLSAFE - 40Kgs", "FPS_H1300_40K", "Confirmed"),
    ("WALLSAFE - 5Kgs", "FPS_H1300_5K", "Confirmed"),
    ("3MM APP Membrane", None, "Pending Code Confirmation"),
    ("AQUAPROOF CRYSTALLINE - 500 GRAM", "FPS_C050_0.5K", "Confirmed"),
    ("AQUAPROOF PU W1 10 KGS", "FPS_C400_10K", "Confirmed"),
    ("CONCAP R", "FPS_E950_32MM", "Confirmed"),
    ("FCSC FIBERMESH 45", "FPS_C2400", "Confirmed"),
    ("FCSC Shield 3P", "FPS_C2050", "Confirmed"),
    ("Plugcon - 25 Kgs", "FPS_D350_25K", "Confirmed"),
    ("SPECTRA FLOGUARD CP", "FPS_F1200_4.1K", "Confirmed"),
    ("SPECTRA FLOGUARD EPSL 4K", "FPS_F500_18.6K", "Confirmed"),
    ("SPECTRA FLOGUARD ERP 2K", "FPS_F700_6K", "Confirmed"),
    ("SUPERGROUT CG - Red-1Kg", "FPS_H800_1K052", "Confirmed"),
]


SEED_FG_ALIASES = [
    ("SUPERGROUT CG BRIGHT WHITE 1 KG", "SUPERGROUT CG - Bright White-1Kg"),
    ("SUPERGROUT CG IVORY 1 KG", "SUPERGROUT CG - Ivory-1Kg"),
    ("SUPERGROUT CG MIDNIGHT BLACK 1 KG", "SUPERGROUT CG - Midnight Black-1Kg"),
    ("SUPERGROUT CG SLATE GREY 1 KG", "SUPERGROUT CG - SLATE GREY -1Kg"),
    ("SUPERGROUT CG CHOCOLATE 1 KG", "SUPERGROUT CG - Chocolate - 1 Kgs"),
    ("SUPERGROUT CG CHOCOLATE BROWN 1 KG", "SUPERGROUT CG - Chocolate Brown - 1 Kgs"),
    ("SUPERGROUT CG TERRACOTTA 1 KG", "SUPERGROUT CG - Terracotta - 1 Kgs"),
    ("SUPERGROUT CG CANYON RED 1 KG", "SUPERGROUT CG - Canyon Red-1Kg"),
    ("SUPERGROUT CG GLEAMING GOLD 1 KG", "SUPERGROUT CG - Gleaming Gold-1Kg"),
    ("SUPERGROUT CG BLUE 1 KG", "SUPERGROUT CG - Blue -1Kg"),
    ("SUPERGROUT CG LINCOLN GREEN 1 KG", "SUPERGROUT CG LINCOLN GREEN - 1 KG"),
    ("SUPERGROUT EG BRIGHT WHITE 1 KG", "SUPERGROUT EG - Bright White - 1 Kg"),
    ("TILESMART AC 1 LTR", "TILESMART AC 1 Ltr"),
    ("TILESMART AC 500 ML", "TILESMART AC 500Ml"),
    ("ADMIX CG 200 ML", "ADMIX CG 200ML"),
    ("AQUAPROOF IW 1 KG", "AQUAPROOF IW 1 KGS"),
    ("AQUAPROOF IW 5 KG", "AQUAPROOF IW 5 KGS"),
    ("AQUAPROOF IW 10 KG", "AQUAPROOF IW 10 KGS"),
    ("AQUAPROOF IW 20 KG", "AQUAPROOF IW 20 KGS"),
    ("ELASTOCEM 4KG", "ELASTOCEM - 4 KGS"),
    ("CEMBOND SBR 1 KG", "CEMBOND SBR 1 KGS"),
    ("CEMBOND SBR 5 KG", "CEMBOND SBR 5 KG"),
    ("CEMBOND SBR 10 KG", "CEMBOND SBR 10 KGS"),
    ("CEMBOND SBR 20 KG", "CEMBOND SBR 20 KGS"),
]


if cur.execute("SELECT COUNT(*) FROM finished_goods_master").fetchone()[0] == 0:
    for _fgnm, _fgcode, _fgst in SEED_FINISHED_GOODS_MASTER:
        cur.execute(
            "INSERT INTO finished_goods_master(name,code,status,created_at) VALUES (?,?,?,?)",
            (_fgnm, _fgcode, _fgst, datetime.datetime.now().isoformat(timespec="seconds"))
        )
    conn.commit()
if cur.execute("SELECT COUNT(*) FROM fg_aliases").fetchone()[0] == 0:
    for _fglegacy, _fgcanon in SEED_FG_ALIASES:
        cur.execute("INSERT OR IGNORE INTO fg_aliases VALUES (?,?)", (_fglegacy, _fgcanon))
    conn.commit()

if cur.execute("SELECT COUNT(*) FROM material_codes").fetchone()[0] == 0:
    for _mat, _code in _SEED_MATERIAL_CODES:
        cur.execute("INSERT OR IGNORE INTO material_codes VALUES (?,?)", (_mat, _code))
    conn.commit()
if cur.execute("SELECT COUNT(*) FROM materials_master").fetchone()[0] == 0:
    for _lc, _nm, _pc, _cat, _st in SEED_MATERIALS_MASTER:
        cur.execute(
            "INSERT INTO materials_master(lab_code,name,procurement_code,category,status,created_at) "
            "VALUES (?,?,?,?,?,?)",
            (_lc, _nm, _pc, _cat, _st, datetime.datetime.now().isoformat(timespec="seconds"))
        )
    conn.commit()
if cur.execute("SELECT COUNT(*) FROM material_aliases").fetchone()[0] == 0:
    for _legacy, _canon in SEED_MATERIAL_ALIASES:
        cur.execute("INSERT OR IGNORE INTO material_aliases VALUES (?,?)", (_legacy, _canon))
    conn.commit()

# ── Migrations — add new columns to existing databases without data loss ──────
for _mig in [
    "ALTER TABLE costs ADD COLUMN description TEXT DEFAULT ''",
    "ALTER TABLE sales ADD COLUMN challan_no  TEXT DEFAULT ''",
    "ALTER TABLE sales ADD COLUMN status      TEXT DEFAULT 'Paid'",
    "ALTER TABLE sand  ADD COLUMN unit        TEXT DEFAULT 'Bags'",
    "ALTER TABLE sales ADD COLUMN gstin       TEXT DEFAULT ''",
    "ALTER TABLE sales ADD COLUMN hsn_code    TEXT DEFAULT ''",
    "ALTER TABLE sales ADD COLUMN gst_rate    REAL DEFAULT 18.0",
    "ALTER TABLE sales_orders ADD COLUMN gstin    TEXT DEFAULT ''",
    "ALTER TABLE sales_orders ADD COLUMN hsn_code TEXT DEFAULT ''",
    "ALTER TABLE sales_orders ADD COLUMN gst_rate REAL DEFAULT 18.0",
    "ALTER TABLE procurement_requests ADD COLUMN vendor TEXT DEFAULT ''",
    "ALTER TABLE stock ADD COLUMN code TEXT DEFAULT ''",
    # FIX: stock never had a `unit` column, but scan_low_stock_and_trigger_procurement()
    # queries s.unit — every scan was silently failing (caught by its broad except)
    # and NO auto low-stock alerts were ever actually firing. This closes that gap.
    "ALTER TABLE stock ADD COLUMN unit TEXT DEFAULT ''",
    # NEW: optional ₹/unit cost per material, used to compute a standard cost
    # per batch on the Formulation (BOM) module. Left at 0 until set — BOM
    # costing simply shows ₹0 / not-yet-costed for anything not filled in.
    "ALTER TABLE material_codes ADD COLUMN unit_cost REAL DEFAULT 0",
    # NEW: Stock <-> Production <-> QC <-> Dispatch reconciliation — optional,
    # nullable link columns only. Existing entry flows are unaffected; these
    # are populated only when a user explicitly ties a new entry to a QC batch.
    "ALTER TABLE production ADD COLUMN production_batch_id INTEGER",
    "ALTER TABLE sales      ADD COLUMN production_batch_id INTEGER",
    "ALTER TABLE stock      ADD COLUMN rm_batch_id INTEGER",
]:
    try:
        cur.execute(_mig)
        conn.commit()
    except sqlite3.OperationalError as e:
        # FIX: Narrowed from bare `except Exception: pass`. "duplicate
        # column" is the expected/safe case (migration already applied);
        # anything else is logged so a real schema problem doesn't vanish
        # silently.
        if "duplicate column" not in str(e).lower():
            logger.warning("Migration failed: %s | %s", _mig, e)

# ================= INDEXES =================
# FIX: These columns are filtered on in almost every query in the app
# (load_filtered() below). Without indexes, every date-range/factory filter
# does a full table scan — fine on a few hundred rows, noticeably slower
# once the tables grow into the tens of thousands.
for _idx in [
    "CREATE INDEX IF NOT EXISTS idx_production_date_factory ON production(date, factory)",
    "CREATE INDEX IF NOT EXISTS idx_sand_date_factory        ON sand(date, factory)",
    "CREATE INDEX IF NOT EXISTS idx_stock_date_factory       ON stock(date, factory)",
    "CREATE INDEX IF NOT EXISTS idx_sales_date_factory       ON sales(date, factory)",
    "CREATE INDEX IF NOT EXISTS idx_costs_date_factory       ON costs(date, factory)",
    "CREATE INDEX IF NOT EXISTS idx_daily_log_date_factory   ON daily_log(date, factory)",
    "CREATE INDEX IF NOT EXISTS idx_sales_orders_date_factory ON sales_orders(date, factory)",
    "CREATE INDEX IF NOT EXISTS idx_audit_log_username        ON audit_log(username)",
    "CREATE INDEX IF NOT EXISTS idx_procurement_req_status     ON procurement_requests(status, factory, material)",
    "CREATE INDEX IF NOT EXISTS idx_procurement_stage_request  ON procurement_stages(request_id)",
    "CREATE INDEX IF NOT EXISTS idx_vendor_materials_vendor     ON vendor_materials(vendor_name)",
    "CREATE INDEX IF NOT EXISTS idx_rm_batches_status            ON rm_batches(status, factory)",
    "CREATE INDEX IF NOT EXISTS idx_prod_batches_status           ON production_batches(status, factory)",
    "CREATE INDEX IF NOT EXISTS idx_pbm_batch                     ON production_batch_materials(production_batch_id)",
    "CREATE INDEX IF NOT EXISTS idx_process_insp_batch             ON process_inspection(production_batch_id)",
    "CREATE INDEX IF NOT EXISTS idx_fg_insp_batch                  ON fg_inspection(production_batch_id)",
    "CREATE INDEX IF NOT EXISTS idx_packing_insp_batch             ON packing_inspection(production_batch_id)",
    "CREATE INDEX IF NOT EXISTS idx_dispatch_appr_batch            ON dispatch_approval(production_batch_id)",
    "CREATE INDEX IF NOT EXISTS idx_ncr_status                     ON ncr_capa(status)",
]:
    try:
        cur.execute(_idx)
    except sqlite3.Error as e:
        logger.warning("Index creation failed: %s | %s", _idx, e)
conn.commit()

# ================= CONSTANTS =================
# FIX: Magic strings replaced with named constants — no more silent typo bugs.
ALL_FACTORIES  = "All"
SCOPE_ACTIVE   = "Active Factory"
SCOPE_ALL      = "All Factories"

FACTORIES      = ["Belda", "Mogra", "Singur", "Siliguri"]
COST_CATS      = ["Raw Materials", "Labour", "Utilities", "Rent / Lease",
                   "Maintenance", "Marketing", "Logistics", "Salaries", "Other"]
SAND_TYPES     = ["M-Sand", "River Sand", "Fine Sand", "Coarse Sand", "Other"]
SAND_UNITS     = ["Bags (50 KG)", "Metric Tonnes", "Cubic Feet", "Cubic Metres", "Kilograms", "Loads"]
GST_RATES      = [5.0, 12.0, 18.0, 28.0]
# ── NEW: Material Master (official codification, single source of truth) ─────
# Every module that lets a user pick a raw material should build its dropdown
# from get_material_master_names(), not from a hardcoded list. canonical_material()
# resolves old free-text names (still sitting in historical rm_batches/bom_lines/
# etc. rows) to the current official name via material_aliases, so nothing has
# to be rewritten in place — new records just use the canonical name directly.

def get_material_master_df() -> pd.DataFrame:
    """Full official material master, one row per item, newest first by category."""
    df = pd.read_sql_query(
        "SELECT id, lab_code, name, procurement_code, category, status "
        "FROM materials_master ORDER BY category, name", conn
    )
    # NULL procurement_code (the Pending Code Confirmation items) reads back as
    # NaN, which breaks search_filter's row-join — display it as blank instead.
    df["procurement_code"] = df["procurement_code"].fillna("")
    return df

def get_material_master_names(category: str | None = None) -> list[str]:
    """Canonical material names for dropdowns. Includes 'Pending Code Confirmation'
    items (they're usable, just flagged) — see material_label() for the badge.
    Excludes 'Inactive' materials — see Material Master → Deactivate; historical
    records referencing them still resolve fine, they just drop out of new pickers."""
    if category:
        rows = cur.execute(
            "SELECT name FROM materials_master WHERE status != 'Inactive' AND category = ? ORDER BY name",
            (category,)
        ).fetchall()
    else:
        rows = cur.execute(
            "SELECT name FROM materials_master WHERE status != 'Inactive' ORDER BY name"
        ).fetchall()
    return [r[0] for r in rows]

def add_material_master(lab_code: str, name: str, procurement_code: str,
                         category: str, status: str = "Confirmed") -> tuple[bool, str]:
    """Adds a new material to the official master. Never touches historical
    records — this only affects what's available going forward."""
    name = name.strip()
    if not name:
        return False, "Material name is required."
    if cur.execute("SELECT id FROM materials_master WHERE name = ?", (name,)).fetchone():
        return False, f"A material named '{name}' already exists."
    try:
        cur.execute(
            "INSERT INTO materials_master(lab_code,name,procurement_code,category,status,created_at) "
            "VALUES (?,?,?,?,?,?)",
            (lab_code.strip() or None, name, procurement_code.strip() or None, category, status,
             datetime.datetime.now().isoformat(timespec="seconds"))
        )
        conn.commit()
        log_audit("INSERT", "materials_master", name, f"Added via Material Master admin ({category})")
        return True, f"Added {name} to the Material Master."
    except sqlite3.Error as e:
        return False, f"Database error: {e}"

def update_material_master(material_id: int, lab_code: str, procurement_code: str,
                            category: str, status: str) -> tuple[bool, str]:
    """Edits an existing material's codes/category/status. Deactivating a material
    (status='Inactive') removes it from get_material_master_names() dropdowns
    without deleting the row or touching any historical record that references it."""
    try:
        cur.execute(
            "UPDATE materials_master SET lab_code=?, procurement_code=?, category=?, status=? WHERE id=?",
            (lab_code.strip() or None, procurement_code.strip() or None, category, status, material_id)
        )
        conn.commit()
        log_audit("UPDATE", "materials_master", material_id, "Updated via Material Master admin")
        return True, "Material updated."
    except sqlite3.Error as e:
        return False, f"Database error: {e}"

def material_label(name: str) -> str:
    """User-friendly display label: 'R1001 – ALUMINIUM HYDROXIDE GEL DRIED' when
    a Procurement Code exists, or just the bare material name when it doesn't —
    no placeholder text, per the Procurement module's display rule."""
    row = cur.execute(
        "SELECT procurement_code FROM materials_master WHERE name = ?", (name,)
    ).fetchone()
    if not row or not row[0]:
        return name
    return f"{row[0]} – {name}"

def canonical_material(name: str) -> str:
    """Resolve a legacy free-text material name (from historical records) to its
    current official name. Returns the input unchanged if it's already canonical
    or has no known alias — never invents or renames anything."""
    if not name:
        return name
    row = cur.execute(
        "SELECT canonical_name FROM material_aliases WHERE legacy_name = ?", (name,)
    ).fetchone()
    return row[0] if row else name

def material_procurement_code(name: str) -> str:
    """Official Procurement Code for a material, resolving aliases first. Empty
    string if the material is unrecognised or still Pending Code Confirmation."""
    canon = canonical_material(name)
    row = cur.execute(
        "SELECT procurement_code FROM materials_master WHERE name = ?", (canon,)
    ).fetchone()
    return (row[0] or "") if row else ""

def get_lab_code(material_name: str) -> str:
    """Official Lab Code (e.g. 'C0330/02') for a material, resolving legacy
    aliases first. Empty string if the material is unrecognised."""
    canon = canonical_material(material_name)
    row = cur.execute(
        "SELECT lab_code FROM materials_master WHERE name = ?", (canon,)
    ).fetchone()
    return (row[0] or "") if row else ""

def lab_code_label(material_name: str) -> str:
    """Display label using the Lab Code in place of the material name — used by
    the Stock module, where the Lab Code is the primary identifier shown. Falls
    back to the bare name if no Lab Code is on file (e.g. an 'Other / Custom'
    item not yet added to the official master)."""
    code = get_lab_code(material_name)
    return code if code else material_name
MATERIALS      = get_material_master_names()
# "Other / Custom" kept as a catch-all for anything genuinely not yet in the
# official master (see Codification_for_System.xlsx) — new/unlisted materials
# should be added to materials_master via Material Master admin, not typed
# freehand here.
MATERIALS.append("Other / Custom")

# ── Official Finished Goods Master (official codification, single source of
# truth) ─────────────────────────────────────────────────────────────────────
# Every module that lets a user pick a finished product should build its
# dropdown from get_finished_goods_master_names(), not from a hardcoded list.
# canonical_product() resolves old free-text names (still sitting in
# historical production/sales/stock/dispatch rows) to the current official
# name via fg_aliases, so nothing has to be rewritten in place — new records
# just use the canonical name directly.

def get_finished_goods_master_df() -> pd.DataFrame:
    """Full official finished goods master, one row per SKU."""
    df = pd.read_sql_query(
        "SELECT id, name, code, status FROM finished_goods_master ORDER BY name", conn
    )
    # NULL code (the Pending Code Confirmation items) reads back as NaN,
    # which breaks search_filter's row-join — display it as blank instead.
    df["code"] = df["code"].fillna("")
    return df

def get_finished_goods_master_names() -> list[str]:
    """Canonical finished-product names for dropdowns. Includes 'Pending Code
    Confirmation' items (they're usable, just flagged) — see fg_label() for
    the badge. Excludes 'Inactive' products — see Finished Goods Master →
    Deactivate; historical records referencing them still resolve fine, they
    just drop out of new pickers."""
    rows = cur.execute(
        "SELECT name FROM finished_goods_master WHERE status != 'Inactive' ORDER BY name"
    ).fetchall()
    return [r[0] for r in rows]

def add_finished_good(name: str, code: str, status: str = "Confirmed") -> tuple[bool, str]:
    """Adds a new finished product to the official master. Never touches
    historical records — this only affects what's available going forward."""
    name = name.strip()
    if not name:
        return False, "Product name is required."
    if cur.execute("SELECT id FROM finished_goods_master WHERE name = ?", (name,)).fetchone():
        return False, f"A finished product named '{name}' already exists."
    try:
        cur.execute(
            "INSERT INTO finished_goods_master(name,code,status,created_at) VALUES (?,?,?,?)",
            (name, code.strip() or None, status, datetime.datetime.now().isoformat(timespec="seconds"))
        )
        conn.commit()
        log_audit("INSERT", "finished_goods_master", name, "Added via Finished Goods Master admin")
        return True, f"Added {name} to the Finished Goods Master."
    except sqlite3.Error as e:
        return False, f"Database error: {e}"

def update_finished_good(fg_id: int, code: str, status: str) -> tuple[bool, str]:
    """Edits an existing product's code/status. Deactivating a product
    (status='Inactive') removes it from get_finished_goods_master_names()
    dropdowns without deleting the row or touching any historical record
    that references it."""
    try:
        cur.execute(
            "UPDATE finished_goods_master SET code=?, status=? WHERE id=?",
            (code.strip() or None, status, fg_id)
        )
        conn.commit()
        log_audit("UPDATE", "finished_goods_master", fg_id, "Updated via Finished Goods Master admin")
        return True, "Finished product updated."
    except sqlite3.Error as e:
        return False, f"Database error: {e}"

def canonical_product(name: str) -> str:
    """Resolve a legacy free-text product name (from historical records) to
    its current official name. Returns the input unchanged if it's already
    canonical or has no known alias — never invents or renames anything."""
    if not name:
        return name
    row = cur.execute(
        "SELECT canonical_name FROM fg_aliases WHERE legacy_name = ?", (name,)
    ).fetchone()
    return row[0] if row else name

def get_fg_code(product_name: str) -> str:
    """Official RM/FG Code (e.g. 'FPS_C010_1K') for a finished product,
    resolving legacy aliases first. Empty string if the product is
    unrecognised or still Pending Code Confirmation."""
    canon = canonical_product(product_name)
    row = cur.execute(
        "SELECT code FROM finished_goods_master WHERE name = ?", (canon,)
    ).fetchone()
    return (row[0] or "") if row else ""

def fg_label(product_name: str) -> str:
    """User-friendly display label: 'FPS_C010_1K – AQUAPROOF IW 1 KGS' when a
    code exists, or just the bare product name when it doesn't — no
    placeholder text, mirroring material_label()."""
    code = get_fg_code(product_name)
    return f"{code} – {product_name}" if code else product_name

FCSC_PRODUCTS  = get_finished_goods_master_names()
# "Other / Custom" kept as a catch-all for anything genuinely not yet in the
# official master (see finished_good_codification.xlsx) — new/unlisted
# products should be added to finished_goods_master via Finished Goods
# Master admin, not typed freehand here.
FCSC_PRODUCTS.append("Other / Custom")
LOG_CATEGORIES = ["Production", "Quality Control", "Procurement", "Dispatch",
                   "Maintenance", "HR", "R&D", "Safety", "Finance", "Other"]
LOG_STATUSES   = ["Completed", "In Progress", "Pending", "Cancelled"]

# ── NEW: Procurement workflow ─────────────────────────────────────────────────
# Fixed 8-stage pipeline every procurement request moves through, whether it
# was opened automatically by a low-stock alert or raised manually.
PROCUREMENT_STAGES = [
    ("Purchase Requisition",   "Store In-charge"),
    ("Approval",               "Plant Manager"),
    ("Purchase Order",         "Purchase Officer"),
    ("Vendor Acknowledgement", "Purchase Officer"),
    ("Material Dispatched",    "Supplier"),
    ("Material Received",      "Stores"),
    ("Quality Inspection",     "QC Team"),
    ("Stock Updated",          "Stores"),
]
STAGE_STATUSES = ["Pending", "In Progress", "Completed", "Skipped"]
DEFAULT_REORDER_THRESHOLD = 50  # used when a material/factory has no custom threshold set

# ── NEW: Quality / Batch workflow ─────────────────────────────────────────────
# A production batch's `status` is the single source of truth for which stage
# it's at. Each QC stage tab only shows batches whose status makes them
# eligible — so a batch literally cannot be inspected out of order.
BATCH_STATUS_FLOW = [
    "Production Started",   # created; awaiting Process QC
    "Process QC Passed",    # awaiting FG QC
    "FG QC Passed",         # awaiting Packing QC
    "Packing QC Passed",    # awaiting Dispatch QC (PDI)
    "Dispatch Approved",    # PDI done — cleared to dispatch
    "Dispatched",           # left the factory
]
BATCH_STATUS_HOLD = {
    "Process QC Passed":  "On Hold",     # Process QC fail
    "FG QC Passed":       "Rejected",    # FG QC fail
    "Packing QC Passed":  "Rework",      # Packing QC fail
    "Dispatch Approved":  "Dispatch Blocked",  # PDI not done / fail
}
SHIFTS = ["Morning", "Afternoon", "Night"]

# ================= UNIT SYSTEM =================
# FIX: "Short Tons" corrected to 0.907185 (1 short ton ≠ 1 metric tonne).
UNIT_MAP = {
    "Metric Tonnes": 1.0,
    "Kilograms":     0.001,
    "Short Tons":    0.907185,
}

# ================= HELPERS =================
# FIX: Allowed-table whitelist prevents accidental or injected table names.
_ALLOWED_TABLES = {"production", "sand", "stock", "sales", "costs", "daily_log",
                    "sales_orders", "sales_targets", "audit_log", "production_targets",
                    "customers"}

def fmt_inr(x: float | int) -> str:
    try:
        return f"₹{float(x):,.0f}"
    except Exception:
        return "₹0"

_STATUS_PILL_COLORS = {
    "success": ("#145C3C", "#E3EEE3"),
    "warning": ("#8C5A1B", "#F5E9D0"),
    "error":   ("#6E1423", "#F6E6E4"),
    "info":    ("#1E3A5F", "#E5EAEF"),
    "neutral": ("#5C4632", "#EFE4CC"),
}

def status_pill(label: str, kind: str = "neutral") -> str:
    """Returns an HTML span styled as a small colored status badge. Only
    usable inside st.markdown(..., unsafe_allow_html=True) — st.dataframe
    renders as a canvas grid and can't display HTML, so status text inside
    a dataframe column stays plain emoji+text (see stock_status_label etc.)."""
    fg, bg = _STATUS_PILL_COLORS.get(kind, _STATUS_PILL_COLORS["neutral"])
    return (f"<span style='display:inline-flex;align-items:center;gap:4px;"
            f"background:{bg};color:{fg};font-size:11px;font-weight:700;"
            f"padding:3px 10px;border-radius:99px;letter-spacing:0.02em;"
            f"white-space:nowrap;'>{label}</span>")

def safe_pct_change(new_val: float, old_val: float) -> float | None:
    """Returns % change from old_val to new_val, or None if old_val is zero.
    Use this for period-over-period comparisons (e.g. today's production vs
    yesterday's). Do NOT use this for a share-of-total like profit margin —
    that's a different formula (see safe_ratio_pct below); the two look
    similar but ((profit/revenue) - 1) * 100 is off by exactly 100
    percentage points from the real margin."""
    return ((new_val / old_val) - 1) * 100 if old_val else None

def safe_ratio_pct(part: float, whole: float) -> float | None:
    """Returns `part` as a percentage of `whole` (e.g. profit margin =
    safe_ratio_pct(profit, revenue)), or None if whole is zero."""
    return (part / whole) * 100 if whole else None

@st.cache_data(show_spinner=False)
def _load_cached(table: str, _version: int) -> pd.DataFrame:
    return pd.read_sql_query(f"SELECT * FROM {table} ORDER BY date DESC", conn)

def load(table: str) -> pd.DataFrame:
    # FIX: Whitelist guard — raises immediately on unrecognised table names.
    assert table in _ALLOWED_TABLES, f"Invalid table: {table}"
    # PERF: cached per data-version — see _data_version / conn.commit above.
    return _load_cached(table, _data_version["v"]).copy()

@st.cache_data(show_spinner=False)
def _load_filtered_cached(table: str, factory_val: str,
                           d_start_s: str, d_end_s: str, _version: int) -> pd.DataFrame:
    if factory_val != ALL_FACTORIES:
        return pd.read_sql_query(
            f"SELECT * FROM {table} WHERE date >= ? AND date <= ? AND factory = ? ORDER BY date DESC",
            conn, params=[d_start_s, d_end_s, factory_val]
        )
    return pd.read_sql_query(
        f"SELECT * FROM {table} WHERE date >= ? AND date <= ? ORDER BY date DESC",
        conn, params=[d_start_s, d_end_s]
    )

def load_filtered(table: str, factory_val: str,
                  d_start: datetime.date, d_end: datetime.date) -> pd.DataFrame:
    assert table in _ALLOWED_TABLES, f"Invalid table: {table}"
    # FIX: Parameters stay parameterised — no f-string injection risk.
    # PERF: cached per data-version — see _data_version / conn.commit above.
    return _load_filtered_cached(
        table, factory_val, str(d_start), str(d_end), _data_version["v"]
    ).copy()

def empty_chart_msg(msg: str = "No data available") -> None:
    st.info(msg)

def search_filter(df: pd.DataFrame, label: str = "Search records",
                  key: str = "search") -> pd.DataFrame:
    """Return a filtered dataframe based on a text search across all columns."""
    q = st.text_input(f"🔍 {label}", placeholder="Type to filter…", key=key)
    if q:
        # FIX: Concatenate all columns into one string per row — single
        # str.contains pass is faster than apply across every column.
        combined = df.apply(lambda col: col.astype(str)).agg(" ".join, axis=1)
        df = df[combined.str.contains(q, case=False, na=False)]
        st.caption(f"{len(df)} matching record(s)")
    return df

def paginate_df(df: pd.DataFrame, page_size: int = 50,
                key: str = "page") -> pd.DataFrame:
    """Return one page of a dataframe with a number-input page control."""
    n = len(df)
    if n <= page_size:
        return df
    pages = (n - 1) // page_size + 1
    page = st.number_input("Page", min_value=1, max_value=pages,
                            value=1, step=1, key=key)
    st.caption(f"Showing {page_size} of {n} records (page {page}/{pages})")
    return df.iloc[(page - 1) * page_size: page * page_size]

def delete_row_ui(df: pd.DataFrame, table: str,
                  label_col: str, key_prefix: str, on_delete=None) -> None:
    """Renders an expander with two-step confirmation before deleting a row.
    `on_delete`, if given, is called with the full row (as it was *before*
    deletion) right after the DELETE commits — used by Production/Dispatch to
    reverse the linked FG stock movement so nothing is orphaned (Sections 7/8)."""
    assert table in _ALLOWED_TABLES, f"Invalid table: {table}"
    if df.empty:
        return
    with st.expander("🗑️ Delete a Record", expanded=False):
        # FIX: not every table has a `date` column (e.g. "customers"), so the
        # date portion of the label is now optional instead of a hard
        # KeyError when it's missing.
        has_date = "date" in df.columns
        options = {
            (f"ID {row['id']} — {row[label_col]} ({row['date']})" if has_date
             else f"ID {row['id']} — {row[label_col]}"): row["id"]
            for _, row in df.iterrows()
        }
        chosen = st.selectbox("Select record to delete", list(options.keys()),
                               key=f"{key_prefix}_del_select")

        # ── Step 1: arm the confirmation ──────────────────────────────────
        armed_key = f"{key_prefix}_del_armed"
        if armed_key not in st.session_state:
            st.session_state[armed_key] = False

        if not st.session_state[armed_key]:
            if st.button("🗑️ Delete this record", key=f"{key_prefix}_del_btn"):
                st.session_state[armed_key] = True
                st.rerun()
        else:
            # ── Step 2: show the red confirmation prompt ──────────────────
            st.error(
                f"⚠️ **Are you sure?** This will permanently delete:\n\n"
                f"> {chosen}\n\n"
                f"This action **cannot be undone**."
            )
            col_yes, col_no = st.columns(2)
            with col_yes:
                if st.button("✅ Yes, delete it", key=f"{key_prefix}_del_confirm"):
                    rid = options[chosen]
                    _row_before = df[df["id"] == rid].iloc[0] if "id" in df.columns else None
                    try:
                        cur.execute(f"DELETE FROM {table} WHERE id = ?", (rid,))
                        conn.commit()
                        log_audit("DELETE", table, rid, f"label={chosen}")
                        if on_delete is not None and _row_before is not None:
                            on_delete(_row_before)
                        st.session_state[armed_key] = False
                        st.success("Record deleted.")
                        st.rerun()
                    except sqlite3.Error as e:
                        st.error(f"Database error while deleting: {e}")
            with col_no:
                if st.button("❌ Cancel", key=f"{key_prefix}_del_cancel"):
                    st.session_state[armed_key] = False
                    st.rerun()

def progress_bar(label: str, value: float, max_value: float,
                 color: str = "#6E1423") -> None:
    pct = min(int(value / max_value * 100), 100) if max_value else 0
    st.markdown(
        f"<div style='margin-bottom:10px'>"
        f"<div style='display:flex;justify-content:space-between;font-size:12px;"
        f"color:#5C4632;margin-bottom:4px'><span>{label}</span>"
        f"<span style=\"font-family:'JetBrains Mono',monospace;font-weight:600;\">{pct}%</span></div>"
        f"<div style='background:#E2D4B8;border-radius:99px;height:8px;overflow:hidden;"
        f"box-shadow:inset 0 1px 2px rgba(28,18,13,0.08)'>"
        f"<div style='background:linear-gradient(90deg,{color},{color}CC);width:{pct}%;"
        f"height:100%;border-radius:99px;transition:width 0.6s'></div></div></div>",
        unsafe_allow_html=True,
    )

# FIX: RM stock closing-balance integrity (reconciliation review, Section 2).
# `stock.closing_stock` is a per-row snapshot chained off the *previous row
# for that (factory, material)* — not recomputed from the ledger on read.
# Editing or deleting an old row used to leave every later row's
# closing_stock stale (e.g. correcting Jan 2's Received from +50 to +70
# left Jan 3 and Jan 4 still showing their original, now-wrong, closing
# figures) until someone happened to add a brand-new row for that same
# material/factory. This recomputes the whole chain in one pass, in the
# same (id ASC) order the app already uses to determine "previous row", so
# it always matches what the entry/edit screens show as "closing stock" —
# call it after any INSERT, UPDATE, or DELETE that touches a stock row.
def recompute_stock_chain(factory: str, material: str) -> None:
    """Recomputes closing_stock for every row of this (factory, material)
    pair, walking id ASC and chaining received/used forward. Idempotent —
    safe to call after an insert even though that row's closing was already
    correct, and safe to call twice for the same pair."""
    if not factory or not material:
        return
    rows = cur.execute(
        "SELECT id, received, used FROM stock WHERE factory=? AND material=? ORDER BY id ASC",
        (factory, material)
    ).fetchall()
    running = 0
    for rid, received, used in rows:
        running += (received or 0) - (used or 0)
        cur.execute("UPDATE stock SET closing_stock=? WHERE id=?", (running, rid))
    conn.commit()

# ── 360° detail pages: Batch / Customer / Material ────────────────────────
# NEW: a single shared "drill-down" mechanism so clicking a batch, a
# customer, or a material anywhere in the app (table row, global search
# result) opens one consolidated page instead of sending the user hunting
# across five different modules. Implemented as a session_state override
# that's checked once, right before the normal module routing — see the
# "if st.session_state.get('_detail_view')" block further down — rather
# than threading a page parameter through every module branch.
def open_detail_view(view_type: str, key: str) -> None:
    st.session_state["_detail_view"] = {"type": view_type, "key": key}
    st.rerun()

def close_detail_view() -> None:
    st.session_state.pop("_detail_view", None)

def detail_back_button(label: str = "← Back") -> None:
    if st.button(label, key="_detail_view_back_btn"):
        close_detail_view()
        st.rerun()

def log_audit(action: str, table: str, record_id: int | str, detail: str = "") -> None:
    """Write one row to audit_log. Never raises — audit failure must not block the main op."""
    try:
        cur.execute(
            "INSERT INTO audit_log VALUES (NULL,?,?,?,?,?,?)",
            (
                datetime.datetime.now().isoformat(timespec="seconds"),
                st.session_state.get("username", "system"),
                action,
                table,
                str(record_id),
                detail,
            ),
        )
        conn.commit()
    except Exception as e:
        # FIX: still never raises (audit failure must not block the main
        # operation) but the failure is now logged instead of vanishing.
        logger.warning("Audit log write failed: %s", e)

# ================= PROCUREMENT ENGINE =================
# NEW: Low-stock detection → email alert → tracked purchase workflow.
#
# Reorder thresholds are configurable per material/factory (Procurement →
# Settings). SMTP credentials are read from st.secrets["smtp"] (preferred —
# add a `[smtp]` block to `.streamlit/secrets.toml`) or from environment
# variables (SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_SENDER).
# Recipients — who the alerts actually go to — are managed inside the app
# itself (Procurement → ⚙️ Settings → Alert Recipients), stored in the
# `procurement_recipients` table, so purchase-team emails can be added or
# removed without touching secrets.toml. Any recipients set via secrets/env
# are still honoured too (merged in), for anyone who prefers that route.
# If SMTP transport or recipients aren't configured, procurement requests
# still get created and are fully usable — only the email step is skipped
# (and clearly flagged as such in the UI).

def _get_smtp_transport() -> dict | None:
    """Returns SMTP host/port/credentials from st.secrets or environment
    variables, or None if nothing is configured. Never raises."""
    try:
        if "smtp" in st.secrets:
            cfg = st.secrets["smtp"]
            if cfg.get("host"):
                return {
                    "host": cfg.get("host"), "port": int(cfg.get("port", 587)),
                    "user": cfg.get("user"), "password": cfg.get("password"),
                    "sender": cfg.get("sender") or cfg.get("user"),
                    "use_tls": bool(cfg.get("use_tls", True)),
                    "static_recipients": [r.strip() for r in
                        str(cfg.get("recipients", "")).split(",") if r.strip()],
                }
    except Exception:
        pass  # st.secrets may not exist at all — that's fine, fall through

    host = os.environ.get("SMTP_HOST")
    if not host:
        return None
    return {
        "host": host, "port": int(os.environ.get("SMTP_PORT", 587)),
        "user": os.environ.get("SMTP_USER"), "password": os.environ.get("SMTP_PASSWORD"),
        "sender": os.environ.get("SMTP_SENDER", os.environ.get("SMTP_USER", "")),
        "use_tls": os.environ.get("SMTP_USE_TLS", "true").lower() != "false",
        "static_recipients": [r.strip() for r in
            os.environ.get("PROCUREMENT_ALERT_EMAILS", "").split(",") if r.strip()],
    }

def get_alert_recipients() -> list[str]:
    """Recipient list = whatever's saved in-app (procurement_recipients table)
    plus any static ones from secrets/env, deduplicated."""
    db_recipients = [r[0] for r in cur.execute(
        "SELECT email FROM procurement_recipients ORDER BY email").fetchall()]
    transport = _get_smtp_transport()
    static_recipients = transport["static_recipients"] if transport else []
    seen, merged = set(), []
    for e in db_recipients + static_recipients:
        if e.lower() not in seen:
            seen.add(e.lower())
            merged.append(e)
    return merged

def add_alert_recipient(email: str, added_by: str) -> tuple[bool, str]:
    email = email.strip().lower()
    if not email or "@" not in email or "." not in email.split("@")[-1]:
        return False, "That doesn't look like a valid email address."
    try:
        cur.execute(
            "INSERT INTO procurement_recipients VALUES (?,?,?) "
            "ON CONFLICT(email) DO NOTHING",
            (email, added_by, datetime.datetime.now().isoformat(timespec="seconds"))
        )
        conn.commit()
        return True, f"Added {email}."
    except sqlite3.Error as e:
        return False, f"Database error: {e}"

def remove_alert_recipient(email: str) -> None:
    cur.execute("DELETE FROM procurement_recipients WHERE email = ?", (email,))
    conn.commit()

def _get_smtp_config() -> dict | None:
    """Combined config used when actually sending: transport + recipients.
    Returns None if either half is missing."""
    transport = _get_smtp_transport()
    recipients = get_alert_recipients()
    if not transport or not recipients:
        return None
    return {**transport, "recipients": recipients}

def send_procurement_alert_email(material: str, factory: str, closing_stock: float,
                                  threshold: float, unit: str, request_id: int) -> tuple[bool, str]:
    """Emails the purchase department about a low-stock / procurement event.
    Never raises — returns (success, message) so the caller can show it
    in-app either way (email failure must not block the request itself)."""
    cfg = _get_smtp_config()
    if not cfg:
        # FIX: pinpoint which half is actually missing instead of a vague
        # combined message — much faster to debug.
        _transport = _get_smtp_transport()
        _recipients = get_alert_recipients()
        if not _transport and not _recipients:
            return False, ("Email not sent — no SMTP server is configured AND no "
                            "recipients are saved. Set both up under Procurement → ⚙️ Settings.")
        elif not _transport:
            return False, ("Email not sent — SMTP server isn't configured "
                            "(recipients are saved fine). Check the banner under "
                            "Procurement → ⚙️ Settings → Email Alerts, and make sure "
                            "the app was restarted after adding secrets.toml / env vars.")
        else:
            return False, ("Email not sent — no recipients are saved yet. "
                            "Add at least one under Procurement → ⚙️ Settings → Alert Recipients.")
    try:
        msg = MIMEMultipart()
        msg["Subject"] = f"⚠️ Low Stock Alert: {material} at {factory} — PR-{request_id:05d}"
        msg["From"] = cfg["sender"]
        msg["To"] = ", ".join(cfg["recipients"])
        body = (
            f"A procurement request has been opened and needs action.\n\n"
            f"Request ID       : PR-{request_id:05d}\n"
            f"Material         : {material}\n"
            f"Factory          : {factory}\n"
            f"Current Stock    : {closing_stock:.2f} {unit}\n"
            f"Reorder Threshold: {threshold:.2f} {unit}\n\n"
            f"Please action the Purchase Requisition stage in the FCSC ERP "
            f"→ Procurement module.\n"
        )
        msg.attach(MIMEText(body, "plain"))
        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=10) as server:
            if cfg["use_tls"]:
                server.starttls()
            if cfg["user"]:
                server.login(cfg["user"], cfg["password"])
            server.sendmail(cfg["sender"], cfg["recipients"], msg.as_string())
        return True, f"Alert emailed to {', '.join(cfg['recipients'])}"
    except Exception as e:
        logger.warning("Procurement alert email failed: %s", e)
        return False, f"Email send failed: {e}"

# ================= SCHEDULED REPORT DIGEST =================
# NEW: reuses the same SMTP config as procurement alerts. IMPORTANT — this
# button sends the digest immediately, on demand. Streamlit only runs code
# while the app is open/being visited, so it cannot fire a "daily 8am" email
# on its own; true scheduling needs an OS-level scheduler (cron on
# Linux/Mac, Task Scheduler on Windows) calling the standalone
# `digest_job.py` script (shipped alongside this file) at whatever time you
# want. This button is for testing that script's output looks right, and
# for one-off "send it now" digests.
def get_digest_recipients() -> list[str]:
    return [r[0] for r in cur.execute(
        "SELECT email FROM digest_recipients ORDER BY email").fetchall()]

def add_digest_recipient(email: str, added_by: str) -> tuple[bool, str]:
    email = email.strip().lower()
    if not email or "@" not in email or "." not in email.split("@")[-1]:
        return False, "That doesn't look like a valid email address."
    try:
        cur.execute(
            "INSERT INTO digest_recipients VALUES (?,?,?) ON CONFLICT(email) DO NOTHING",
            (email, added_by, datetime.datetime.now().isoformat(timespec="seconds"))
        )
        conn.commit()
        return True, f"Added {email}."
    except sqlite3.Error as e:
        return False, f"Database error: {e}"

def remove_digest_recipient(email: str) -> None:
    cur.execute("DELETE FROM digest_recipients WHERE email = ?", (email,))
    conn.commit()

def build_digest_html(period_label: str) -> str:
    """Plain-language summary of the last `period_label` across all
    factories — production, revenue, costs, open procurement, open NCRs."""
    today = datetime.date.today()
    since = {"Today": today, "Last 7 Days": today - datetime.timedelta(days=7),
             "This Month": today.replace(day=1)}.get(period_label, today - datetime.timedelta(days=7))

    prod = pd.read_sql_query("SELECT * FROM production WHERE date >= ?", conn, params=(str(since),))
    sales = pd.read_sql_query("SELECT * FROM sales WHERE date >= ?", conn, params=(str(since),))
    so    = pd.read_sql_query("SELECT * FROM sales_orders WHERE date >= ?", conn, params=(str(since),))
    costs = pd.read_sql_query("SELECT * FROM costs WHERE date >= ?", conn, params=(str(since),))
    open_proc = cur.execute("SELECT COUNT(*) FROM procurement_requests WHERE status='Open'").fetchone()[0]
    open_ncr  = cur.execute("SELECT COUNT(*) FROM ncr_capa WHERE status='Open'").fetchone()[0]

    # FIX: Revenue = Dispatch only (goods actually shipped/invoiced). Sales
    # Orders are booked commitments, not revenue — shown as a separate
    # "Order Book" line so a booked order isn't double-counted once it
    # later dispatches.
    total_prod = prod["production"].sum() if not prod.empty else 0
    revenue = sales["total"].sum() if not sales.empty else 0
    order_book = so["total"].sum() if not so.empty else 0
    cost = costs["amount"].sum() if not costs.empty else 0

    rows = [
        ("Period", f"{since} to {today}"),
        ("Total Production", f"{total_prod:,.2f} MT"),
        ("Revenue (Dispatch)", fmt_inr(revenue)),
        ("Order Book (Sales Orders booked, not yet dispatched)", fmt_inr(order_book)),
        ("Costs", fmt_inr(cost)),
        ("Net Profit", fmt_inr(revenue - cost)),
        ("Open Procurement Requests", str(open_proc)),
        ("Open NCRs", str(open_ncr)),
    ]
    row_html = "".join(
        f"<tr><td style='padding:6px 12px;border:1px solid #E0D2AE;'><b>{k}</b></td>"
        f"<td style='padding:6px 12px;border:1px solid #E0D2AE;'>{v}</td></tr>"
        for k, v in rows
    )
    return (
        f"<h2 style='color:#6E1423;'>FCSC ERP — {period_label} Digest</h2>"
        f"<table style='border-collapse:collapse;font-family:sans-serif;font-size:13px;'>"
        f"{row_html}</table>"
        f"<p style='color:#8C7B62;font-size:12px;'>Generated {datetime.datetime.now():%Y-%m-%d %H:%M}. "
        f"See the ERP for full detail.</p>"
    )

def send_digest_email(period_label: str) -> tuple[bool, str]:
    transport = _get_smtp_transport()
    recipients = get_digest_recipients()
    if not transport:
        return False, "Email not sent — no SMTP server configured (see Procurement → Settings)."
    if not recipients:
        return False, "Email not sent — no digest recipients saved yet. Add one below."
    try:
        html = build_digest_html(period_label)
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"FCSC ERP — {period_label} Digest — {datetime.date.today()}"
        msg["From"] = transport["sender"]
        msg["To"] = ", ".join(recipients)
        msg.attach(MIMEText(html, "html"))
        with smtplib.SMTP(transport["host"], transport["port"], timeout=10) as server:
            if transport["use_tls"]:
                server.starttls()
            if transport["user"]:
                server.login(transport["user"], transport["password"])
            server.sendmail(transport["sender"], recipients, msg.as_string())
        return True, f"Digest emailed to {', '.join(recipients)}"
    except Exception as e:
        logger.warning("Digest email failed: %s", e)
        return False, f"Email send failed: {e}"

# ── NEW: Material codes ─────────────────────────────────────────────────────
def get_material_code(material: str) -> str:
    row = cur.execute(
        "SELECT code FROM material_codes WHERE material = ?", (material,)
    ).fetchone()
    return row[0] if row else ""

def set_material_code(material: str, code: str) -> None:
    cur.execute(
        "INSERT INTO material_codes VALUES (?,?) "
        "ON CONFLICT(material) DO UPDATE SET code=excluded.code",
        (material, code.strip())
    )
    conn.commit()

# ── NEW: Vendor master ──────────────────────────────────────────────────────
# Pre-loaded from the factory's own historical raw-material stock records
# (154 materials → 39 real suppliers, with lead times). Emails/phones are
# blank until filled in via Procurement → 🏭 Vendors — that's the one manual
# step needed before "Notify Vendor" can actually send anything.

def get_default_vendor_for_material(material: str) -> str | None:
    row = cur.execute(
        "SELECT vendor_name FROM vendor_materials WHERE material = ?", (material,)
    ).fetchone()
    return row[0] if row else None

def get_vendor(name: str) -> dict | None:
    row = cur.execute(
        "SELECT name, email, phone, lead_time_days, notes FROM vendors WHERE name = ?",
        (name,)
    ).fetchone()
    if row is None:
        return None
    return {"name": row[0], "email": row[1], "phone": row[2],
            "lead_time_days": row[3], "notes": row[4]}

def upsert_vendor(name: str, email: str, phone: str, lead_time_days: int, notes: str) -> tuple[bool, str]:
    name = name.strip()
    if not name:
        return False, "Vendor name is required."
    try:
        cur.execute(
            "INSERT INTO vendors VALUES (?,?,?,?,?,?) "
            "ON CONFLICT(name) DO UPDATE SET email=excluded.email, phone=excluded.phone, "
            "lead_time_days=excluded.lead_time_days, notes=excluded.notes",
            (name, email.strip(), phone.strip(), lead_time_days, notes.strip(),
             datetime.datetime.now().isoformat(timespec="seconds"))
        )
        conn.commit()
        return True, f"Saved vendor {name}."
    except sqlite3.Error as e:
        return False, f"Database error: {e}"

def set_material_vendor(material: str, vendor_name: str, lead_time_days: int, pack_size: str) -> None:
    cur.execute(
        "INSERT INTO vendor_materials VALUES (?,?,?,?) "
        "ON CONFLICT(material) DO UPDATE SET vendor_name=excluded.vendor_name, "
        "lead_time_days=excluded.lead_time_days, pack_size=excluded.pack_size",
        (material, vendor_name, lead_time_days, pack_size)
    )
    conn.commit()

def send_vendor_email(vendor_name: str, material: str, factory: str, qty: float,
                       unit: str, request_id: int) -> tuple[bool, str]:
    """Emails the specific vendor linked to this request — separate from the
    internal purchase-team alert. Never raises."""
    vendor = get_vendor(vendor_name) if vendor_name else None
    if not vendor:
        return False, "No vendor is linked to this request yet. Set one under 🏭 Vendors."
    if not vendor["email"]:
        return False, (f"{vendor_name} has no email on file yet. Add one under "
                        f"Procurement → 🏭 Vendors before notifying them.")
    transport = _get_smtp_transport()
    if not transport:
        return False, "Email not sent — SMTP server isn't configured yet (see ⚙️ Settings)."
    try:
        msg = MIMEMultipart()
        msg["Subject"] = f"Purchase Order Request — PR-{request_id:05d} — {material}"
        msg["From"] = transport["sender"]
        msg["To"] = vendor["email"]
        body = (
            f"Dear {vendor_name},\n\n"
            f"We would like to place an order for the following:\n\n"
            f"Material   : {material}\n"
            f"Quantity   : {qty:.2f} {unit}\n"
            f"Deliver to : FCSC — {factory}\n"
            f"Reference  : PR-{request_id:05d}\n\n"
            f"Please confirm acknowledgement and expected dispatch date at your "
            f"earliest convenience.\n\nRegards,\nFirstchoice Speciality Chemicals Pvt. Ltd.\n"
        )
        msg.attach(MIMEText(body, "plain"))
        with smtplib.SMTP(transport["host"], transport["port"], timeout=10) as server:
            if transport["use_tls"]:
                server.starttls()
            if transport["user"]:
                server.login(transport["user"], transport["password"])
            server.sendmail(transport["sender"], [vendor["email"]], msg.as_string())
        log_audit("UPDATE", "procurement_requests", request_id, f"Vendor notified: {vendor_name}")
        return True, f"Emailed {vendor_name} at {vendor['email']}"
    except Exception as e:
        logger.warning("Vendor email failed: %s", e)
        return False, f"Email send failed: {e}"

def _open_procurement_request(material: str, factory: str, trigger_type: str,
                               qty: float, unit: str, notes: str,
                               vendor: str | None = None) -> int:
    """Creates a procurement_requests row plus its 8-stage workflow. Returns
    the new request id. If vendor isn't given, auto-fills from the material's
    default vendor (vendor_materials) when one is on file."""
    now_iso = datetime.datetime.now().isoformat(timespec="seconds")
    vendor = vendor or get_default_vendor_for_material(material) or ""
    cur.execute(
        "INSERT INTO procurement_requests VALUES (NULL,?,?,?,?,?,?,?,?,NULL,?)",
        (now_iso, factory, material, trigger_type, qty, unit, "Open", notes, vendor)
    )
    req_id = cur.lastrowid
    today = datetime.date.today()
    # FIX: "Material Received" due date now reflects the vendor's actual
    # lead_time_days when a vendor is on file, instead of a flat +6 days —
    # this is what makes the promised-vs-actual vendor performance
    # comparison (see vendor_performance_summary()) meaningful rather than
    # comparing against an arbitrary placeholder date.
    _vendor_row = get_vendor(vendor) if vendor else None
    _lead_days = _vendor_row["lead_time_days"] if _vendor_row and _vendor_row.get("lead_time_days") else None
    for i, (stage_name, default_owner) in enumerate(PROCUREMENT_STAGES):
        if stage_name == "Material Received" and _lead_days:
            due = today + datetime.timedelta(days=_lead_days)
        else:
            due = today + datetime.timedelta(days=i + 1)
        cur.execute(
            "INSERT INTO procurement_stages VALUES (NULL,?,?,?,?,?,?,?,?)",
            (req_id, i, stage_name, "Pending", default_owner,
             str(due), None, "system")
        )
    conn.commit()
    log_audit("INSERT", "procurement_requests", req_id, f"{trigger_type}: {material} @ {factory}")
    return req_id

def scan_low_stock_and_trigger_procurement() -> list[dict]:
    """Checks the latest closing stock per (factory, material) against its
    reorder threshold. For anything below threshold that doesn't already
    have an open procurement request, opens one and emails the purchase
    department. Returns the list of newly created alerts."""
    created: list[dict] = []
    try:
        latest = pd.read_sql_query("""
            SELECT s.factory, s.material, s.closing_stock,
                   COALESCE(s.unit, '') AS unit
            FROM stock s
            INNER JOIN (
                SELECT factory, material, MAX(date) AS max_date
                FROM stock GROUP BY factory, material
            ) latest
            ON s.factory = latest.factory AND s.material = latest.material
               AND s.date = latest.max_date
        """, conn)
    except Exception as e:
        logger.warning("Low-stock scan query failed: %s", e)
        return created

    for _, row in latest.iterrows():
        factory_, material_ = row["factory"], row["material"]
        threshold_row = cur.execute(
            "SELECT threshold FROM reorder_levels WHERE material=? AND factory=?",
            (material_, factory_)
        ).fetchone()
        threshold = threshold_row[0] if threshold_row else DEFAULT_REORDER_THRESHOLD
        if row["closing_stock"] >= threshold:
            continue

        already_open = cur.execute(
            "SELECT id FROM procurement_requests WHERE material=? AND factory=? AND status='Open'",
            (material_, factory_)
        ).fetchone()
        if already_open:
            continue  # already actioned — don't spam a fresh alert every rerun

        req_id = _open_procurement_request(
            material_, factory_, "auto_low_stock", row["closing_stock"], row["unit"],
            f"Auto-triggered: stock {row['closing_stock']:.2f} {row['unit']} "
            f"below reorder threshold {threshold:.2f}"
        )
        sent, msg = send_procurement_alert_email(
            material_, factory_, row["closing_stock"], threshold, row["unit"], req_id
        )
        # NEW: WhatsApp/SMS goes out alongside the email — same trigger,
        # different channel, for people who don't watch email closely.
        broadcast_phone_alert(
            "low_stock",
            f"⚠️ FCSC Low Stock — {material_} @ {factory_}: {row['closing_stock']:.2f} "
            f"{row['unit']} (below {threshold:.2f}). PR-{req_id:05d} opened."
        )
        created.append({"material": material_, "factory": factory_, "request_id": req_id,
                         "email_sent": sent, "email_msg": msg})
    return created

# ================= VENDOR PERFORMANCE =================
# NEW: compares each vendor's promised delivery (the "Material Received"
# stage's due_date, which is now set from vendor.lead_time_days when the
# request is opened) against when that stage was actually marked Completed.
def vendor_performance_summary() -> pd.DataFrame:
    """One row per vendor: PO count, on-time %, avg delay (days). Only
    considers requests where the 'Material Received' stage has actually
    been completed — open/in-flight requests have nothing to compare yet."""
    df = pd.read_sql_query("""
        SELECT r.vendor, r.material, r.factory, r.id AS request_id,
               s.due_date AS promised, s.completed_at AS actual
        FROM procurement_requests r
        JOIN procurement_stages s
          ON s.request_id = r.id AND s.stage_name = 'Material Received'
        WHERE r.vendor IS NOT NULL AND r.vendor != ''
          AND s.status = 'Completed' AND s.completed_at IS NOT NULL
    """, conn)
    if df.empty:
        return df
    df["promised_date"] = pd.to_datetime(df["promised"], errors="coerce")
    df["actual_date"]   = pd.to_datetime(df["actual"], errors="coerce").dt.normalize()
    df = df.dropna(subset=["promised_date", "actual_date"])
    if df.empty:
        return df
    df["delay_days"] = (df["actual_date"] - df["promised_date"]).dt.days
    df["on_time"] = df["delay_days"] <= 0

    summary = (df.groupby("vendor")
                 .agg(POs=("request_id", "count"),
                      on_time_pct=("on_time", "mean"),
                      avg_delay_days=("delay_days", "mean"))
                 .reset_index())
    summary["on_time_pct"] = (summary["on_time_pct"] * 100).round(1)
    summary["avg_delay_days"] = summary["avg_delay_days"].round(1)
    return summary.sort_values("on_time_pct", ascending=False).reset_index(drop=True)

# ================= WHATSAPP / SMS ALERT ENGINE =================
# NEW: same event-driven idea as the email alert engine above — low stock and
# NCRs push a message out immediately — but to phones via Twilio (WhatsApp
# or SMS), for people who don't watch email closely on the factory floor.
# Uses plain HTTP calls to Twilio's REST API rather than the `twilio` SDK,
# so it degrades the same way SMTP/reportlab/qrcode do: unset it, and the
# app keeps working, this step is just skipped (never blocks the calling
# action — a stock scan or NCR still completes even if every send fails).

def _get_twilio_config() -> dict | None:
    """Reads Twilio credentials from st.secrets["twilio"] or environment
    variables. Returns None if nothing is configured."""
    try:
        if "twilio" in st.secrets:
            cfg = st.secrets["twilio"]
            if cfg.get("account_sid"):
                return {
                    "account_sid": cfg.get("account_sid"), "auth_token": cfg.get("auth_token"),
                    "whatsapp_from": cfg.get("whatsapp_from", ""), "sms_from": cfg.get("sms_from", ""),
                }
    except Exception:
        pass  # st.secrets may not exist at all — fine, fall through to env vars
    sid = os.environ.get("TWILIO_ACCOUNT_SID")
    if not sid:
        return None
    return {
        "account_sid": sid, "auth_token": os.environ.get("TWILIO_AUTH_TOKEN"),
        "whatsapp_from": os.environ.get("TWILIO_WHATSAPP_FROM", ""),
        "sms_from": os.environ.get("TWILIO_SMS_FROM", ""),
    }

def get_phone_recipients(event: str) -> list[dict]:
    """Everyone subscribed to a given event type ('low_stock' or 'ncr')."""
    rows = cur.execute("SELECT phone, channel, events FROM whatsapp_recipients").fetchall()
    return [{"phone": r[0], "channel": r[1]} for r in rows if event in (r[2] or "").split(",")]

def add_phone_recipient(phone: str, channel: str, events: list[str], added_by: str) -> tuple[bool, str]:
    phone = phone.strip()
    if not phone.startswith("+") or not phone[1:].replace(" ", "").isdigit():
        return False, "Enter the number in international format, e.g. +919812345678."
    if not events:
        return False, "Pick at least one alert type for this recipient."
    try:
        cur.execute(
            "INSERT INTO whatsapp_recipients VALUES (?,?,?,?,?) "
            "ON CONFLICT(phone) DO UPDATE SET channel=excluded.channel, events=excluded.events",
            (phone, channel, ",".join(events), added_by, datetime.datetime.now().isoformat(timespec="seconds"))
        )
        conn.commit()
        return True, f"Saved {phone} ({channel})."
    except sqlite3.Error as e:
        return False, f"Database error: {e}"

def remove_phone_recipient(phone: str) -> None:
    cur.execute("DELETE FROM whatsapp_recipients WHERE phone = ?", (phone,))
    conn.commit()

def send_whatsapp_sms(phone: str, channel: str, body: str) -> tuple[bool, str]:
    """Sends one message via Twilio. Never raises — always returns
    (success, message) so the caller can decide whether/how to surface it."""
    if not HAS_REQUESTS:
        return False, "The `requests` package isn't installed (pip install requests)."
    cfg = _get_twilio_config()
    if not cfg:
        return False, ("Twilio isn't configured. Add a `[twilio]` block to secrets.toml "
                        "(account_sid, auth_token, whatsapp_from, sms_from) or set the "
                        "TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN / TWILIO_WHATSAPP_FROM / "
                        "TWILIO_SMS_FROM environment variables, then restart the app.")
    from_num = cfg["whatsapp_from"] if channel == "whatsapp" else cfg["sms_from"]
    if not from_num:
        return False, f"No Twilio '{channel}' sender number configured yet."
    to_num = f"whatsapp:{phone}" if channel == "whatsapp" else phone
    if channel == "whatsapp" and not from_num.startswith("whatsapp:"):
        from_num = f"whatsapp:{from_num}"
    try:
        resp = requests.post(
            f"https://api.twilio.com/2010-04-01/Accounts/{cfg['account_sid']}/Messages.json",
            auth=(cfg["account_sid"], cfg["auth_token"]),
            data={"From": from_num, "To": to_num, "Body": body},
            timeout=10,
        )
        if resp.status_code in (200, 201):
            return True, f"Sent to {phone} via {channel}."
        return False, f"Twilio error {resp.status_code}: {resp.text[:200]}"
    except Exception as e:
        logger.warning("WhatsApp/SMS send failed: %s", e)
        return False, f"Send failed: {e}"

def broadcast_phone_alert(event: str, body: str) -> list[tuple[str, bool, str]]:
    """Sends `body` to everyone subscribed to `event`. One recipient's
    failure never blocks the others. Returns a per-recipient result list."""
    results = []
    for r in get_phone_recipients(event):
        ok, msg = send_whatsapp_sms(r["phone"], r["channel"], body)
        results.append((r["phone"], ok, msg))
    return results

# ================= REORDER-POINT FORECASTING =================
# NEW: uses the daily `used` figures already logged in the stock table to
# estimate a consumption rate per (factory, material), then projects how
# many days remain before closing stock crosses the reorder threshold —
# rather than only alerting once it's already below it.
def reorder_forecast(days_history: int = 30) -> pd.DataFrame:
    """Returns one row per (factory, material) currently tracked in stock,
    with average daily usage, days remaining until the reorder threshold,
    and a projected reorder date. NaN/None days_remaining means usage has
    been zero/flat over the lookback window, so no forecast can be made."""
    cutoff = str(datetime.date.today() - datetime.timedelta(days=days_history))
    hist = pd.read_sql_query(
        "SELECT factory, material, date, used, closing_stock FROM stock "
        "WHERE date >= ? ORDER BY factory, material, date",
        conn, params=(cutoff,)
    )
    if hist.empty:
        return pd.DataFrame()

    latest_idx = hist.groupby(["factory", "material"])["date"].idxmax()
    latest = hist.loc[latest_idx, ["factory", "material", "closing_stock"]].reset_index(drop=True)

    usage = (hist.groupby(["factory", "material"])["used"]
                  .mean().reset_index().rename(columns={"used": "avg_daily_used"}))

    out = latest.merge(usage, on=["factory", "material"], how="left")

    thresholds = pd.read_sql_query("SELECT material, factory, threshold FROM reorder_levels", conn)
    out = out.merge(thresholds, on=["material", "factory"], how="left")
    out["threshold"] = out["threshold"].fillna(DEFAULT_REORDER_THRESHOLD)

    def _days_remaining(row):
        if not row["avg_daily_used"] or row["avg_daily_used"] <= 0:
            return None
        headroom = row["closing_stock"] - row["threshold"]
        return max(0, headroom) / row["avg_daily_used"]

    out["days_to_threshold"] = out.apply(_days_remaining, axis=1)
    out["projected_reorder_date"] = out["days_to_threshold"].apply(
        lambda d: str(datetime.date.today() + datetime.timedelta(days=int(d))) if d is not None else "—"
    )
    return out.sort_values("days_to_threshold", na_position="last").reset_index(drop=True)

# ================= BOM / FORMULATION ENGINE =================
# NEW: standard formula per product — a reference batch size plus the raw
# materials/quantities that go into it. Two things this powers: (1) scaling
# to a planned production quantity to see what needs to be pulled from stock
# / procured, and (2) a rough standard cost per batch once unit costs are on
# file. This does NOT replace the actual materials recorded on a production
# batch (production_batch_materials) — that stays the source of truth for
# what was really used; a BOM is the *plan*, not the record of what happened.

def get_active_bom(product: str) -> dict | None:
    row = cur.execute(
        "SELECT * FROM bom_headers WHERE product=? AND is_active=1 ORDER BY id DESC LIMIT 1",
        (product,)
    ).fetchone()
    if row is None:
        return None
    cols = [d[0] for d in cur.description]
    return dict(zip(cols, row, strict=True))

def get_bom_lines(bom_id: int) -> pd.DataFrame:
    return pd.read_sql_query(
        "SELECT * FROM bom_lines WHERE bom_id = ? ORDER BY sequence, id", conn, params=(bom_id,)
    )

def _activate_bom(bom_id: int, product: str) -> None:
    """Marks one BOM version active and deactivates every other version of
    the same product — so exactly one version is ever "the" formula, while
    older versions stay in the table for history/traceability."""
    cur.execute("UPDATE bom_headers SET is_active=0 WHERE product = ?", (product,))
    cur.execute("UPDATE bom_headers SET is_active=1 WHERE id = ?", (bom_id,))
    conn.commit()

def create_bom(product: str, version: str, formula_code: str, batch_size: float,
               batch_unit: str, notes: str, lines: list[dict]) -> tuple[bool, str, int | None]:
    """`lines`: list of {'material','qty_per_batch','unit','notes'} dicts."""
    if not product:
        return False, "Select a product.", None
    if not lines:
        return False, "Add at least one material line (quantity must be > 0).", None
    try:
        cur.execute(
            "INSERT INTO bom_headers VALUES (NULL,?,?,?,?,?,0,?,?,?)",
            (product, version.strip() or "v1", formula_code.strip(), batch_size, batch_unit,
             notes.strip(), st.session_state.get("username", "system"), _now_iso())
        )
        bom_id = cur.lastrowid
        for i, ln in enumerate(lines):
            cur.execute(
                "INSERT INTO bom_lines VALUES (NULL,?,?,?,?,?,?)",
                (bom_id, ln["material"], ln["qty_per_batch"], ln["unit"], i, ln.get("notes", ""))
            )
        conn.commit()
        log_audit("INSERT", "bom_headers", bom_id, f"{product} | {version} | {len(lines)} materials")
        return True, f"Saved formula {version} for {product} ({len(lines)} materials).", bom_id
    except sqlite3.Error as e:
        return False, f"Database error: {e}", None

def calculate_material_requirement(product: str, qty_to_produce: float,
                                    factory: str | None = None) -> pd.DataFrame:
    """Scales the active BOM's per-batch quantities to a planned production
    quantity, and compares against current closing stock — factory-specific
    if `factory` is given, otherwise summed across all factories. Returns an
    empty DataFrame if there's no active BOM or no lines on it."""
    bom = get_active_bom(product)
    if bom is None:
        return pd.DataFrame()
    lines = get_bom_lines(bom["id"])
    if lines.empty:
        return pd.DataFrame()
    scale = qty_to_produce / bom["batch_size"] if bom["batch_size"] else 0

    rows = []
    for _, ln in lines.iterrows():
        required = ln["qty_per_batch"] * scale
        if factory:
            row = cur.execute(
                "SELECT closing_stock FROM stock WHERE material=? AND factory=? "
                "ORDER BY id DESC LIMIT 1", (ln["material"], factory)
            ).fetchone()
            available = row[0] if row else 0
        else:
            row = cur.execute(
                "SELECT COALESCE(SUM(closing_stock),0) FROM stock s1 WHERE material = ? "
                "AND id = (SELECT MAX(id) FROM stock s2 "
                "WHERE s2.material = s1.material AND s2.factory = s1.factory)",
                (ln["material"],)
            ).fetchone()
            available = row[0] if row else 0
        rows.append({
            "material": ln["material"], "unit": ln["unit"],
            "required_qty": round(required, 3), "available_qty": round(available, 3),
            "shortage": round(max(0.0, required - available), 3),
        })
    return pd.DataFrame(rows)

def bom_standard_cost(product: str) -> float | None:
    """Sums qty_per_batch × unit_cost across the active BOM's lines, using
    unit costs saved on material_codes.unit_cost. None = no active BOM at
    all; 0 = a BOM exists but no line has a cost on file yet."""
    bom = get_active_bom(product)
    if bom is None:
        return None
    lines = get_bom_lines(bom["id"])
    if lines.empty:
        return 0.0
    total = 0.0
    for _, ln in lines.iterrows():
        row = cur.execute("SELECT unit_cost FROM material_codes WHERE material = ?",
                           (ln["material"],)).fetchone()
        total += ln["qty_per_batch"] * (row[0] if row and row[0] else 0)
    return round(total, 2)

# ================= QUALITY / BATCH TRACEABILITY ENGINE =================
# NEW: RM Receipt → Incoming QC → Production Batch → Process QC → FG QC →
# Packing QC → Dispatch QC (PDI). Every "record_*_inspection" function is the
# ONLY way a batch's status advances — the UI never sets status directly, so
# a batch can't be pushed to a later stage than its inspections justify, even
# by mistake.

def _now_iso() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")

def raise_ncr(source_stage: str, reference_id: int, batch_no: str, description: str) -> int:
    """Auto-opens a Non-Conformance Record whenever any QC stage fails."""
    cur.execute(
        "INSERT INTO ncr_capa VALUES (NULL,?,?,?,?,?,?,?,?,NULL)",
        (source_stage, reference_id, batch_no, description, "",
         "Open", st.session_state.get("username", "system"), _now_iso())
    )
    conn.commit()
    ncr_id = cur.lastrowid
    broadcast_phone_alert(
        "ncr",
        f"⚠️ FCSC NCR-{ncr_id:04d} raised — {source_stage} QC, batch {batch_no}: {description[:100]}"
    )
    return ncr_id

# ── Stage 1: Incoming Material (Stores) ─────────────────────────────────────
def create_rm_batch(supplier: str, po_reference: str, material: str, batch_no: str,
                     quantity: float, unit: str, factory: str, received_date) -> int:
    cur.execute(
        "INSERT INTO rm_batches VALUES (NULL,?,?,?,?,?,?,?,?,?,?,?)",
        (supplier, po_reference, material, batch_no, quantity, unit, factory,
         str(received_date), "Awaiting QC", st.session_state.get("username", "system"), _now_iso())
    )
    conn.commit()
    rm_id = cur.lastrowid
    log_audit("INSERT", "rm_batches", rm_id, f"{material} | batch {batch_no} | {supplier}")
    return rm_id

# ── Stage 2: Incoming QC ─────────────────────────────────────────────────────
def record_incoming_inspection(rm_batch_id: int, appearance: str, colour: str, moisture: str,
                                particle_size: str, remarks: str, decision: str, inspector: str) -> int:
    assert decision in ("Pass", "Fail")
    cur.execute(
        "INSERT INTO incoming_inspection VALUES (NULL,?,?,?,?,?,?,?,?,?)",
        (rm_batch_id, appearance, colour, moisture, particle_size, remarks,
         decision, inspector, _now_iso())
    )
    insp_id = cur.lastrowid
    new_status = "Approved" if decision == "Pass" else "Rejected"
    cur.execute("UPDATE rm_batches SET status=? WHERE id=?", (new_status, rm_batch_id))
    conn.commit()
    _rm = cur.execute("SELECT material, batch_no FROM rm_batches WHERE id=?", (rm_batch_id,)).fetchone()
    log_audit("UPDATE", "rm_batches", rm_batch_id, f"Incoming QC: {decision}")
    if decision == "Fail":
        cur.execute("INSERT INTO supplier_return_notes VALUES (NULL,?,?,?)",
                     (rm_batch_id, remarks or "Failed incoming inspection", _now_iso()))
        conn.commit()
        raise_ncr("Incoming", insp_id, _rm[1] if _rm else "",
                   f"Incoming QC failed for {_rm[0] if _rm else 'material'} (batch {_rm[1] if _rm else ''}): {remarks}")
    return insp_id

# ── Stage 3: Production Batch ────────────────────────────────────────────────
def generate_batch_no(factory: str) -> str:
    _prefix = f"FCSC-{factory[:3].upper()}-{datetime.date.today().strftime('%Y%m%d')}"
    _count = cur.execute(
        "SELECT COUNT(*) FROM production_batches WHERE batch_no LIKE ?", (f"{_prefix}%",)
    ).fetchone()[0]
    return f"{_prefix}-{_count + 1:03d}"

def create_production_batch(product: str, formula: str, factory: str, operator: str,
                             machine: str, shift: str, rm_batch_ids: list[int],
                             qty_used_map: dict[int, float], quantity: float | None = None,
                             quantity_unit: str = "") -> tuple[int | None, str]:
    """Creates a production batch. Refuses if any selected RM batch isn't
    Approved — this is the actual enforcement, not just a UI filter.
    `quantity`/`quantity_unit` capture the batch's actual output (Section 11)
    so Dispatch<->Quality reconciliation can compare real quantities instead
    of a batch count — optional, since historical batches never had it."""
    for rid in rm_batch_ids:
        _status = cur.execute("SELECT status FROM rm_batches WHERE id=?", (rid,)).fetchone()
        if not _status or _status[0] != "Approved":
            return None, f"RM batch id {rid} is not QC-Approved — cannot be used in production."
    batch_no = generate_batch_no(factory)
    cur.execute(
        "INSERT INTO production_batches "
        "(batch_no,product,formula,factory,operator,machine,shift,status,created_at,"
        "quantity,quantity_unit) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (batch_no, product, formula, factory, operator, machine, shift,
         "Production Started", _now_iso(), quantity, quantity_unit)
    )
    pb_id = cur.lastrowid
    for rid in rm_batch_ids:
        cur.execute("INSERT INTO production_batch_materials VALUES (NULL,?,?,?)",
                     (pb_id, rid, qty_used_map.get(rid, 0)))
    conn.commit()
    log_audit("INSERT", "production_batches", pb_id, f"{batch_no} | {product} @ {factory}")
    return pb_id, batch_no

# ── Stage 4: Process QC ──────────────────────────────────────────────────────
def record_process_inspection(pb_id: int, viscosity: str, density: str, temperature: str,
                               appearance: str, remarks: str, decision: str, inspector: str) -> int:
    assert decision in ("Pass", "Fail")
    cur.execute(
        "INSERT INTO process_inspection VALUES (NULL,?,?,?,?,?,?,?,?,?)",
        (pb_id, viscosity, density, temperature, appearance, remarks, decision, inspector, _now_iso())
    )
    insp_id = cur.lastrowid
    new_status = "Process QC Passed" if decision == "Pass" else BATCH_STATUS_HOLD["Process QC Passed"]
    cur.execute("UPDATE production_batches SET status=? WHERE id=?", (new_status, pb_id))
    conn.commit()
    log_audit("UPDATE", "production_batches", pb_id, f"Process QC: {decision}")
    if decision == "Fail":
        _bno = cur.execute("SELECT batch_no FROM production_batches WHERE id=?", (pb_id,)).fetchone()
        raise_ncr("Process", insp_id, _bno[0] if _bno else "", f"Process QC failed: {remarks}")
    return insp_id

# ── Stage 5: Finished Goods QC ───────────────────────────────────────────────
def record_fg_inspection(pb_id: int, adhesion: str, strength: str, consistency: str,
                          colour: str, weight: str, decision: str, inspector: str) -> int:
    assert decision in ("Pass", "Fail")
    cur.execute(
        "INSERT INTO fg_inspection VALUES (NULL,?,?,?,?,?,?,?,?,?)",
        (pb_id, adhesion, strength, consistency, colour, weight, decision, inspector, _now_iso())
    )
    insp_id = cur.lastrowid
    new_status = "FG QC Passed" if decision == "Pass" else BATCH_STATUS_HOLD["FG QC Passed"]
    cur.execute("UPDATE production_batches SET status=? WHERE id=?", (new_status, pb_id))
    conn.commit()
    log_audit("UPDATE", "production_batches", pb_id, f"FG QC: {decision}")
    if decision == "Fail":
        _bno = cur.execute("SELECT batch_no FROM production_batches WHERE id=?", (pb_id,)).fetchone()
        raise_ncr("FG", insp_id, _bno[0] if _bno else "", "Finished Goods QC failed")
    return insp_id

# ── Stage 6: Packing QC ──────────────────────────────────────────────────────
def record_packing_inspection(pb_id: int, correct_bag: bool, correct_label: bool,
                               correct_batch: bool, net_weight_ok: bool, seal_quality_ok: bool,
                               inspector: str) -> int:
    decision = "Pass" if all([correct_bag, correct_label, correct_batch,
                               net_weight_ok, seal_quality_ok]) else "Fail"
    cur.execute(
        "INSERT INTO packing_inspection VALUES (NULL,?,?,?,?,?,?,?,?,?)",
        (pb_id, int(correct_bag), int(correct_label), int(correct_batch),
         int(net_weight_ok), int(seal_quality_ok), decision, inspector, _now_iso())
    )
    insp_id = cur.lastrowid
    new_status = "Packing QC Passed" if decision == "Pass" else BATCH_STATUS_HOLD["Packing QC Passed"]
    cur.execute("UPDATE production_batches SET status=? WHERE id=?", (new_status, pb_id))
    conn.commit()
    log_audit("UPDATE", "production_batches", pb_id, f"Packing QC: {decision}")
    if decision == "Fail":
        _bno = cur.execute("SELECT batch_no FROM production_batches WHERE id=?", (pb_id,)).fetchone()
        raise_ncr("Packing", insp_id, _bno[0] if _bno else "", "Packing QC failed one or more checks")
    return insp_id

# ── Stage 7: Dispatch QC (PDI) ───────────────────────────────────────────────
def record_dispatch_approval(pb_id: int, pdi_completed: bool, approved_by: str) -> int:
    status = "Released" if pdi_completed else "Blocked"
    cur.execute(
        "INSERT INTO dispatch_approval VALUES (NULL,?,?,?,?,?)",
        (pb_id, int(pdi_completed), approved_by, _now_iso(), status)
    )
    conn.commit()
    new_status = "Dispatch Approved" if pdi_completed else BATCH_STATUS_HOLD["Dispatch Approved"]
    cur.execute("UPDATE production_batches SET status=? WHERE id=?", (new_status, pb_id))
    conn.commit()
    log_audit("UPDATE", "production_batches", pb_id, f"Dispatch QC: {status}")
    return cur.lastrowid

def mark_batch_dispatched(pb_id: int) -> None:
    cur.execute("UPDATE production_batches SET status='Dispatched' WHERE id=?", (pb_id,))
    conn.commit()
    log_audit("UPDATE", "production_batches", pb_id, "Marked Dispatched")

# ================= BATCH TRACEABILITY REPORT =================
# NEW: pulls every stage already captured by the QC engine above (RM receipt →
# incoming QC → production batch → process QC → FG QC → packing QC → dispatch
# approval) into a single structure, for a one-page certificate per batch —
# the payoff for having captured all of this data stage-by-stage in the
# first place.
def get_batch_traceability(batch_no: str) -> dict | None:
    """Returns a dict with every stage's data for one production batch, or
    None if the batch number doesn't exist. Never raises — missing stages
    (e.g. batch hasn't reached Packing QC yet) show up as empty/None."""
    pb = cur.execute(
        "SELECT * FROM production_batches WHERE batch_no = ?", (batch_no,)
    ).fetchone()
    if pb is None:
        return None
    pb_cols = [d[0] for d in cur.description]
    pb_row = dict(zip(pb_cols, pb, strict=True))
    pb_id = pb_row["id"]

    materials = pd.read_sql_query("""
        SELECT r.material, r.batch_no AS rm_batch_no, r.supplier, r.received_date,
               pbm.qty_used, ii.decision AS incoming_decision
        FROM production_batch_materials pbm
        JOIN rm_batches r ON r.id = pbm.rm_batch_id
        LEFT JOIN incoming_inspection ii ON ii.rm_batch_id = r.id
        WHERE pbm.production_batch_id = ?
    """, conn, params=(pb_id,))

    def _one(table: str) -> dict | None:
        row = cur.execute(
            f"SELECT * FROM {table} WHERE production_batch_id = ? ORDER BY id DESC LIMIT 1",
            (pb_id,)
        ).fetchone()
        if row is None:
            return None
        cols = [d[0] for d in cur.description]
        return dict(zip(cols, row, strict=True))

    return {
        "batch": pb_row,
        "materials": materials,
        "process_qc": _one("process_inspection"),
        "fg_qc": _one("fg_inspection"),
        "packing_qc": _one("packing_inspection"),
        "dispatch_qc": _one("dispatch_approval"),
        "ncrs": pd.read_sql_query(
            "SELECT * FROM ncr_capa WHERE batch_no = ? ORDER BY id", conn, params=(batch_no,)
        ),
    }

# ── Batch progress stepper — GLOBAL (was previously defined only inside the
# Quality module's `elif module == "Quality":` block, which made it
# unreachable from the new Batch Detail 360° page since that page can be
# opened without ever visiting the Quality module in the same run) ─────────
BATCH_STEPS = [
    ("Production Started", "Production"),
    ("Process QC Passed",  "Process QC"),
    ("FG QC Passed",       "FG QC"),
    ("Packing QC Passed",  "Packing QC"),
    ("Dispatch Approved",  "Dispatch QC"),
    ("Dispatched",         "Dispatched"),
]
BATCH_HOLD_STAGE = {
    "On Hold":           "Process QC",
    "Rejected":          "FG QC",
    "Rework":            "Packing QC",
    "Dispatch Blocked":  "Dispatch QC",
}

def render_batch_progress(status: str) -> None:
    if status in BATCH_HOLD_STAGE:
        st.markdown(status_pill(f"🛑 Held at {BATCH_HOLD_STAGE[status]} — {status}", "error"),
                    unsafe_allow_html=True)
        return
    idx = next((i for i, (s, _) in enumerate(BATCH_STEPS) if s == status), 0)
    segs = []
    for i, (_s, label) in enumerate(BATCH_STEPS):
        if i < idx:
            circle = ("background:#145C3C;border-color:#145C3C;color:#F7F1E3;", "✓")
        elif i == idx:
            circle = ("background:#F7F1E3;border-color:#6E1423;color:#6E1423;"
                       "box-shadow:0 0 0 4px rgba(110,20,35,0.12);", str(i + 1))
        else:
            circle = ("background:#F7F1E3;border-color:#E0D2AE;color:#C4B393;", str(i + 1))
        style, glyph = circle
        line_color = "#145C3C" if i < idx else "#E2D4B8"
        label_weight = "700" if i == idx else "500"
        label_color = "#241812" if i <= idx else "#8C7B62"
        connector = "" if i == 0 else (
            f"<div style='position:absolute;top:13px;right:50%;width:100%;height:2px;"
            f"background:{line_color};z-index:0;'></div>"
        )
        segs.append(
            f"<div style='flex:1;display:flex;flex-direction:column;align-items:center;position:relative;'>"
            f"{connector}"
            f"<div style='width:26px;height:26px;border-radius:50%;border:2px solid;{style}"
            f"display:flex;align-items:center;justify-content:center;font-size:11px;"
            f"font-weight:700;z-index:1;position:relative;'>{glyph}</div>"
            f"<div style='font-size:11px;margin-top:6px;text-align:center;"
            f"font-weight:{label_weight};color:{label_color};'>{label}</div>"
            f"</div>"
        )
    st.markdown(f"<div style='display:flex;align-items:flex-start;margin:8px 0 4px;'>"
                 f"{''.join(segs)}</div>", unsafe_allow_html=True)

def generate_batch_qr_png(batch_no: str) -> bytes | None:
    """Returns PNG bytes of a QR code encoding the batch number, for printing
    on the bag label. Scanning it doesn't open a live report on its own —
    that requires the app to be hosted at a stable URL the QR can point to;
    until then, whoever scans it can type the batch number into the
    Traceability tab. Returns None if the qrcode package isn't installed."""
    if not HAS_QRCODE:
        return None
    img = qrcode.make(f"FCSC BATCH:{batch_no}")
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

def generate_traceability_pdf(trace: dict) -> bytes | None:
    """Builds a one-page traceability certificate PDF from the dict returned
    by get_batch_traceability(). Returns None if reportlab isn't installed."""
    if not HAS_REPORTLAB:
        return None
    b = trace["batch"]
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                             topMargin=16*mm, bottomMargin=16*mm,
                             leftMargin=16*mm, rightMargin=16*mm)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("TraceTitle", parent=styles["Title"],
                                  textColor=colors.HexColor("#6E1423"), fontSize=16)
    h_style = ParagraphStyle("TraceH", parent=styles["Heading2"], fontSize=11,
                              textColor=colors.HexColor("#1C120D"), spaceBefore=10, spaceAfter=4)
    body = styles["Normal"]

    story = [
        Paragraph("FCSC — Batch Traceability Certificate", title_style),
        Paragraph(f"Firstchoice Speciality Chemicals Pvt. Ltd. &nbsp;|&nbsp; "
                  f"Generated {datetime.date.today().strftime('%d %B %Y')}", body),
        Spacer(1, 8),
    ]

    def _kv_table(rows: list[tuple[str, str]]) -> Table:
        t = Table([[Paragraph(f"<b>{k}</b>", body), Paragraph(str(v), body)] for k, v in rows],
                   colWidths=[45*mm, 130*mm])
        t.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#E0D2AE")),
            ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F3E7D0")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        return t

    story.append(Paragraph("Production Batch", h_style))
    story.append(_kv_table([
        ("Batch No.", b["batch_no"]), ("Product", fg_label(b["product"])),
        ("Formula", b.get("formula") or "—"), ("Factory", b["factory"]),
        ("Operator", b["operator"]), ("Machine", b.get("machine") or "—"),
        ("Shift", b.get("shift") or "—"), ("Status", b["status"]),
        ("Created", (b["created_at"] or "")[:16]),
    ]))

    mdf = trace["materials"]
    story.append(Paragraph("Raw Materials Used", h_style))
    if mdf.empty:
        story.append(Paragraph("No raw materials linked to this batch.", body))
    else:
        rows = [["Material", "RM Batch No.", "Supplier", "Qty Used", "Incoming QC"]]
        for _, r in mdf.iterrows():
            rows.append([r["material"], r["rm_batch_no"], r["supplier"],
                         f"{r['qty_used']:g}", r["incoming_decision"] or "—"])
        mt = Table(rows, colWidths=[38*mm, 30*mm, 38*mm, 22*mm, 25*mm])
        mt.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#E0D2AE")),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1C120D")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 8.5),
            ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.append(mt)

    stage_specs = [
        ("Process QC",  "process_qc",  ["viscosity", "density", "temperature", "appearance", "decision", "inspector", "date"]),
        ("FG QC",       "fg_qc",       ["adhesion", "strength", "consistency", "colour", "weight", "decision", "inspector", "date"]),
        ("Packing QC",  "packing_qc",  ["correct_bag", "correct_label", "correct_batch", "net_weight_ok", "seal_quality_ok", "decision", "inspector", "date"]),
        ("Dispatch QC (PDI)", "dispatch_qc", ["pdi_completed", "approved_by", "date", "status"]),
    ]
    for label, key, fields in stage_specs:
        story.append(Paragraph(label, h_style))
        rec = trace.get(key)
        if not rec:
            story.append(Paragraph("Not yet recorded.", body))
        else:
            story.append(_kv_table([(f.replace('_', ' ').title(), rec.get(f, "—")) for f in fields]))

    if not trace["ncrs"].empty:
        story.append(Paragraph("Non-Conformance Reports (NCR/CAPA)", h_style))
        rows = [["Stage", "Description", "Status", "Raised"]]
        for _, n in trace["ncrs"].iterrows():
            rows.append([n["source_stage"], n["description"][:60], n["status"], (n["raised_at"] or "")[:10]])
        nt = Table(rows, colWidths=[25*mm, 90*mm, 20*mm, 25*mm])
        nt.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#E0D2AE")),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#6E1423")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ]))
        story.append(nt)

    qr_bytes = generate_batch_qr_png(b["batch_no"])
    if qr_bytes:
        qr_buf = BytesIO(qr_bytes)
        story.append(Spacer(1, 10))
        story.append(Paragraph("Scan to look up this batch:", body))
        story.append(RLImage(qr_buf, width=28*mm, height=28*mm))

    doc.build(story)
    return buf.getvalue()

# ── Company details used on generated invoices — edit these for your entity ──
COMPANY_INFO = {
    "name": "Firstchoice Speciality Chemicals Pvt. Ltd.",
    "address": "Belda, Mogra, Singur & Siliguri, West Bengal, India",
    "gstin": "— set your company GSTIN in COMPANY_INFO —",
    "email": "support@fcsc.co.in",
    "phone": "+91 33 3500 0230",
}

def generate_invoice_pdf(order_row: dict, customer_row: dict | None) -> bytes | None:
    """Builds a GST-style invoice PDF for one sales order. `order_row` is a
    dict of one row from sales_orders (must include gstin/hsn_code/gst_rate —
    added via migration). Returns None if reportlab isn't installed. NOTE:
    formatted to look like a GST invoice, but isn't a substitute for your
    accountant/GST software confirming it meets full statutory requirements
    (e.g. invoice numbering sequence, e-invoice IRN if applicable)."""
    if not HAS_REPORTLAB:
        return None
    o = order_row
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                             topMargin=16*mm, bottomMargin=16*mm,
                             leftMargin=16*mm, rightMargin=16*mm)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("InvTitle", parent=styles["Title"],
                                  textColor=colors.HexColor("#6E1423"), fontSize=18)
    body = styles["Normal"]

    story = [
        Paragraph(COMPANY_INFO["name"], title_style),
        Paragraph(f"{COMPANY_INFO['address']}<br/>GSTIN: {COMPANY_INFO['gstin']}<br/>"
                  f"{COMPANY_INFO['email']} | {COMPANY_INFO['phone']}", body),
        Spacer(1, 10),
        Paragraph(f"<b>TAX INVOICE</b> &nbsp;&nbsp; Order #{o['id']:05d} &nbsp;&nbsp; "
                  f"Date: {o['date']}", styles["Heading3"]),
        Spacer(1, 6),
    ]

    bill_to = [
        f"<b>Bill To:</b> {o['customer']}",
        f"GSTIN: {o.get('gstin') or '—'}",
    ]
    if customer_row:
        if customer_row.get("address"):
            bill_to.append(customer_row["address"])
        if customer_row.get("phone"):
            bill_to.append(f"Phone: {customer_row['phone']}")
    story.append(Paragraph("<br/>".join(bill_to), body))
    story.append(Spacer(1, 10))

    gst_rate = o.get("gst_rate") or 18.0
    taxable = o["qty"] * o["unit_price"]
    tax_amt = round(taxable * gst_rate / 100, 2)
    grand = round(taxable + tax_amt, 2)

    rows = [["Product", "HSN", "Qty", "Unit Price", "Taxable Value"],
            [fg_label(o["product"]), o.get("hsn_code") or "—", f"{o['qty']:g}",
             fmt_inr(o["unit_price"]), fmt_inr(taxable)]]
    t = Table(rows, colWidths=[55*mm, 25*mm, 20*mm, 30*mm, 35*mm])
    t.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#E0D2AE")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1C120D")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(t)
    story.append(Spacer(1, 8))

    totals = Table([
        ["Taxable Amount", fmt_inr(taxable)],
        [f"GST @ {gst_rate:g}%", fmt_inr(tax_amt)],
        ["Grand Total", fmt_inr(grand)],
    ], colWidths=[135*mm, 30*mm])
    totals.setStyle(TableStyle([
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("FONTNAME", (0, 2), (-1, 2), "Helvetica-Bold"),
        ("LINEABOVE", (0, 2), (-1, 2), 0.8, colors.HexColor("#1C120D")),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(totals)
    story.append(Spacer(1, 16))
    story.append(Paragraph(f"Sales Representative: {o.get('sales_rep') or '—'}", body))
    story.append(Paragraph("This is a computer-generated invoice.", styles["Italic"]))

    doc.build(story)
    return buf.getvalue()

def get_order_status(order_id: int) -> dict | None:
    """Customer-facing order status lookup: which batch (if known) fulfilled
    this order and its dispatch stage, for a simple 'has my order shipped'
    answer without a phone call. Best-effort — links an order to a batch via
    matching product + factory + date, since sales_orders doesn't currently
    store a direct batch reference."""
    order = cur.execute(
        "SELECT * FROM sales_orders WHERE id = ?", (order_id,)
    ).fetchone()
    if order is None:
        return None
    cols = [d[0] for d in cur.description]
    order_row = dict(zip(cols, order, strict=True))

    candidate = cur.execute("""
        SELECT pb.batch_no, pb.status, da.date AS dispatch_date
        FROM production_batches pb
        LEFT JOIN dispatch_approval da ON da.production_batch_id = pb.id
        WHERE pb.product = ? AND pb.factory = ?
        ORDER BY pb.id DESC LIMIT 1
    """, (order_row["product"], order_row["factory"])).fetchone()

    return {
        "order": order_row,
        "batch_no": candidate[0] if candidate else None,
        "batch_status": candidate[1] if candidate else None,
        "dispatch_date": candidate[2] if candidate else None,
    }

# ================= SIDEBAR =================
with st.sidebar:
    st.markdown("""
    <div style='padding:0.2rem 2px 1.1rem; display:flex; align-items:center; gap:9px;
                border-bottom:1px solid #232833; margin-bottom:0.9rem;'>
        <div style='width:26px;height:26px;border-radius:6px;background:#2B4C7E;
                    display:flex;align-items:center;justify-content:center;
                    color:#fff;font-size:12px;font-weight:700;flex-shrink:0;'>FC</div>
        <div style='line-height:1.25;'>
            <div style='font-size:13px;font-weight:700;color:#FFFFFF;letter-spacing:-0.01em;'>FCSC ERP</div>
            <div style='font-size:10.5px;color:#7B8494;'>Firstchoice Speciality Chemicals</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ── User badge ────────────────────────────────────────────────────────
    badge_label = "Administrator" if _is_admin else _user_factory
    st.markdown(
        f"<div style='background:rgba(255,255,255,0.05);border:1px solid #232833;"
        f"border-radius:6px;padding:8px 10px;margin-bottom:14px;'>"
        f"<div style='color:#FFFFFF;font-size:12.5px;font-weight:600;'>"
        f"{st.session_state.display_name}</div>"
        f"<div style='color:#7B8494;font-size:11px;margin-top:1px;'>"
        f"{badge_label}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )

    # NEW: notification bell — rolls up open procurement, overdue stages,
    # open NCRs, and low stock into one place instead of only surfacing on
    # each module separately.
    render_notification_bell(_is_admin, _user_factory)

    # NEW: saved per-user default filters — loaded once per session so a
    # supervisor/admin doesn't have to re-pick their usual factory/module
    # every visit. Explicit picks below still win within the session.
    if "_prefs_loaded" not in st.session_state:
        _saved_prefs = get_user_prefs(st.session_state.username)
        st.session_state._saved_prefs = _saved_prefs
        st.session_state._prefs_loaded = True
    _saved_prefs = st.session_state.get("_saved_prefs")

    # ── Factory selector — locked for supervisors ─────────────────────────
    if _is_admin:
        _fac_options = [ALL_FACTORIES] + FACTORIES
        _fac_default_idx = 0
        if _saved_prefs and _saved_prefs.get("default_factory") in _fac_options:
            _fac_default_idx = _fac_options.index(_saved_prefs["default_factory"])
        factory = st.selectbox("ACTIVE FACTORY", _fac_options, index=_fac_default_idx)
    else:
        # Supervisor: hard-locked to their factory, no selectbox
        factory = _user_factory
        st.markdown(
            f"<div style='font-size:11px;color:#7B8494;letter-spacing:0.06em;"
            f"text-transform:uppercase;margin-bottom:4px;'>Factory</div>"
            f"<div style='font-size:13px;font-weight:600;color:#FFFFFF;"
            f"padding:7px 10px;background:rgba(255,255,255,0.05);border:1px solid #232833;"
            f"border-radius:6px;margin-bottom:12px;'>{factory}</div>",
            unsafe_allow_html=True,
        )

    # ── Module selector — filtered by role ────────────────────────────────
    available_modules = ADMIN_MODULES if _is_admin else SUPERVISOR_MODULES
    _module_default_idx = 0
    if _saved_prefs and _saved_prefs.get("default_module") in available_modules:
        _module_default_idx = available_modules.index(_saved_prefs["default_module"])

    # NOTE: `key="module_radio"` lets Global Search "jump" to a module — it
    # sets st.session_state["module_radio"] then calls st.rerun(); on the
    # fresh run that follows, this widget reads that value from session
    # state instead of `index` (Streamlit only honors `index` the first
    # time a keyed widget is created, before session_state has a value for it).
    module = st.radio("MODULE", available_modules, index=_module_default_idx, key="module_radio")

    # NEW: record a "module view" once per switch (not on every rerun caused
    # by unrelated widget clicks within the same module) — feeds the Pilot
    # Dashboard's "Most-used modules" chart.
    if st.session_state.get("_last_logged_module") != module:
        log_module_view(st.session_state.username, module)
        st.session_state["_last_logged_module"] = module

    unit = st.selectbox("UNIT SYSTEM", list(UNIT_MAP.keys()))

    st.markdown("---")
    st.caption("DATE RANGE")

    # ── Date range: cached across all tables so it doesn't run on every click ──
    @st.cache_data(ttl=60)
    def _get_date_bounds() -> tuple:
        _q = """
            SELECT MIN(mn) AS mn, MAX(mx) AS mx FROM (
                SELECT MIN(date) AS mn, MAX(date) AS mx FROM production
                UNION ALL SELECT MIN(date), MAX(date) FROM sand
                UNION ALL SELECT MIN(date), MAX(date) FROM stock
                UNION ALL SELECT MIN(date), MAX(date) FROM sales
                UNION ALL SELECT MIN(date), MAX(date) FROM sales_orders
                UNION ALL SELECT MIN(date), MAX(date) FROM costs
                UNION ALL SELECT MIN(date), MAX(date) FROM daily_log
            )
        """
        _r = pd.read_sql_query(_q, conn)
        return _r.iloc[0, 0], _r.iloc[0, 1]
    _mn, _mx = _get_date_bounds()
    bounds      = pd.DataFrame({"mn": [_mn], "mx": [_mx]})
    _mn         = bounds.iloc[0, 0]
    _mx         = bounds.iloc[0, 1]
    _today      = datetime.date.today()
    default_start = pd.to_datetime(_mn).date() if _mn else _today.replace(day=1)
    # Always extend end to today so freshly saved entries are immediately visible
    default_end   = max(pd.to_datetime(_mx).date(), _today) if _mx else _today
    # NEW: a saved "days back" preference overrides the full-history default
    # start date, so returning to a familiar recent window doesn't require
    # re-picking it every visit.
    if _saved_prefs and _saved_prefs.get("default_days_back"):
        default_start = max(default_start, _today - datetime.timedelta(days=_saved_prefs["default_days_back"]))

    date_range = st.date_input(
        "Range", value=[default_start, default_end],
        label_visibility="collapsed", key="date_range"
    )
    d_start = date_range[0] if len(date_range) >= 1 else default_start
    d_end   = date_range[1] if len(date_range) >= 2 else d_start

    if st.button("Save as my default view", key="save_prefs_btn",
                  width='stretch'):
        save_user_prefs(
            st.session_state.username,
            factory if _is_admin else None,
            (_today - d_start).days,
            module,
        )
        st.session_state._saved_prefs = get_user_prefs(st.session_state.username)
        st.success("Saved — this factory/range/module will load automatically next time.")

    st.markdown("---")

    # ── System control — admin only ───────────────────────────────────────
    if _is_admin:
        st.caption("SYSTEM CONTROL")
        with st.expander("Reset transactional data", expanded=False):
            st.error(
                "This permanently clears **production, sand, stock, sales, "
                "costs, daily log, sales orders, and sales targets** for "
                "**all factories** — not just the one currently selected. "
                "Master data (users, vendors, BOMs, quality records) and the "
                "**audit log are never touched**, so who did this and when "
                "stays on record. A safety backup of the whole database is "
                "taken automatically first."
            )
            reset_word = st.text_input("Type RESET to confirm", key="reset_word",
                                        placeholder="RESET")
            reset_armed_key = "reset_erp_armed"
            if reset_armed_key not in st.session_state:
                st.session_state[reset_armed_key] = False

            if not st.session_state[reset_armed_key]:
                if st.button("Reset ERP", key="reset_erp_step1"):
                    if reset_word.strip() == "RESET":
                        st.session_state[reset_armed_key] = True
                        st.rerun()
                    else:
                        st.warning("Type the word RESET exactly to confirm.")
            else:
                st.error(
                    "⚠️ **Last chance.** This cannot be undone from within the "
                    "app (only by restoring the automatic backup). Proceed?"
                )
                rc1, rc2 = st.columns(2)
                with rc1:
                    if st.button("✅ Yes, wipe transactional data", key="reset_erp_confirm"):
                        try:
                            # Safety net: timestamped full backup before touching anything.
                            _rbk_dir = "fcsc_backups"
                            os.makedirs(_rbk_dir, exist_ok=True)
                            _rbk_name = (f"{_rbk_dir}/fcsc_pre_reset_"
                                         f"{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.db")
                            conn.commit()
                            shutil.copy2("fcsc.db", _rbk_name)

                            # FIX: audit_log is intentionally excluded — wiping the log
                            # in the same action it's supposed to record would erase the
                            # evidence of who ran the reset.
                            cur.executescript("""
                                DELETE FROM production; DELETE FROM sand;
                                DELETE FROM stock; DELETE FROM sales; DELETE FROM costs;
                                DELETE FROM daily_log; DELETE FROM sales_orders;
                                DELETE FROM sales_targets;
                                DELETE FROM fg_stock; DELETE FROM inventory_reconciliation;
                            """)
                            conn.commit()
                            log_audit("RESET", "*", "all",
                                      f"Transactional data reset by {st.session_state.get('username')}; "
                                      f"backup saved to {_rbk_name}")
                            st.session_state[reset_armed_key] = False
                            st.success(f"Reset complete. Backup saved to `{_rbk_name}`.")
                            st.rerun()
                        except (sqlite3.Error, OSError) as e:
                            st.error(f"Reset failed — no data was touched if this is a backup error: {e}")
                with rc2:
                    if st.button("❌ Cancel", key="reset_erp_cancel"):
                        st.session_state[reset_armed_key] = False
                        st.rerun()
        st.markdown("---")

    st.caption(f"Today: {datetime.date.today()}")

    # ── Change Password ───────────────────────────────────────────────────
    st.markdown("---")
    with st.expander("Change my password", expanded=False):
        cp_cur  = st.text_input("Current password",  type="password", key="cp_cur")
        cp_new  = st.text_input("New password",       type="password", key="cp_new")
        cp_new2 = st.text_input("Confirm new password", type="password", key="cp_new2")
        if st.button("Update Password", key="cp_btn"):
            _uname = st.session_state.username
            _udata = get_user(_uname)
            # FIX: Password change now writes to the `users` table, so it
            # survives restarts (previously it only mutated an in-memory
            # dict and the UI admitted the change was temporary).
            if not _udata or not _verify_password(cp_cur, _udata["password"]):
                st.error("Current password is incorrect.")
            elif len(cp_new) < 6:
                st.error("New password must be at least 6 characters.")
            elif cp_new != cp_new2:
                st.error("New passwords do not match.")
            else:
                cur.execute("UPDATE users SET password = ? WHERE username = ?",
                            (_hash_password(cp_new), _uname))
                conn.commit()
                st.success("Password updated and saved.")

    # ── Send Feedback — every user, feeds the admin-only Pilot Dashboard ────
    st.markdown("---")
    with st.expander("💬 Send feedback", expanded=False):
        st.caption("Found a bug, or something confusing? Tell us — this goes "
                   "straight to the admin team's pilot dashboard.")
        fb_msg = st.text_area("Your feedback", key="fb_msg_input",
                               placeholder="What happened, and what were you trying to do?",
                               height=90, label_visibility="collapsed")
        if st.button("Submit feedback", key="fb_submit_btn"):
            if not fb_msg.strip():
                st.warning("Write a line or two first.")
            else:
                submit_feedback(st.session_state.username, _user_factory, fb_msg)
                st.success("Thanks — sent to the admin team.")

    # ── Logout ────────────────────────────────────────────────────────────
    if st.button("Log out", width='stretch'):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()

# ── DB backup ─────────────────────────────────────────────────────────────
if _is_admin and "db_backed_up" not in st.session_state:
    try:
        _backup_dir = "fcsc_backups"
        os.makedirs(_backup_dir, exist_ok=True)
        _backup_name = f"{_backup_dir}/fcsc_{datetime.date.today()}.db"
        if not os.path.exists(_backup_name):
            shutil.copy2("fcsc.db", _backup_name)
            # keep only last 30 daily backups
            _bk_files = sorted([f for f in os.listdir(_backup_dir) if f.endswith(".db")])
            for _old in _bk_files[:-30]:
                os.remove(os.path.join(_backup_dir, _old))
    except Exception as e:
        # FIX: backup failure still never blocks the app, but is now logged.
        logger.warning("DB backup failed: %s", e)
    st.session_state["db_backed_up"] = True

# ── unit converters ────────────────────────────────────────────────────────
def to_mt(value: float) -> float:
    return float(value) * UNIT_MAP[unit]

def from_mt(value: float) -> float:
    return float(value) / UNIT_MAP[unit]

# ═════════════════════════════════════════════════════════════════════════
#  FINISHED GOODS STOCK LEDGER + RECONCILIATION ENGINE
# ═════════════════════════════════════════════════════════════════════════
# Core principle (per the Stock/Production/QC/Dispatch reconciliation spec):
# transactions are entered once, in their own module (Production, Dispatch,
# QC, Stock). This engine derives FG stock from those transactions and
# cross-checks the RM side against QC — it never becomes a second place to
# type the same number, and it never silently corrects a mismatch.
#
# FG identity: keyed on (factory, product) using the same free-text product
# names Production/Dispatch already use. `fg_code` is carried on every row
# for forward compatibility and back-filled once the FGB-/FGP- scheme from
# the plant team is finalised — nothing else here needs to change when that
# happens.

def get_fg_closing_stock(fac: str, product: str) -> float:
    """Latest closing FG stock for a factory+product. 0 if never logged."""
    row = cur.execute(
        "SELECT closing_stock FROM fg_stock WHERE factory=? AND product=? "
        "ORDER BY id DESC LIMIT 1", (fac, product)
    ).fetchone()
    return float(row[0]) if row else 0.0

def record_fg_stock_movement(date_val, fac: str, product: str, *, production_in: float = 0,
                              dispatch_out: float = 0, adjustment: float = 0,
                              source_module: str = "", source_ref_id: int | None = None,
                              fg_code: str = "", movement_type: str = "Entry") -> float:
    """Appends one FG stock ledger row and returns the new closing balance.
    Never overwrites a prior row — this is a ledger, not a balance field.
    FIX: read-previous-then-insert now runs inside _write_lock() so two
    concurrent movements for the same factory/product can't both read the
    same previous closing and silently clobber one another (reconciliation
    review, Section 3)."""
    with _write_lock():
        prev = get_fg_closing_stock(fac, product)
        closing = prev + production_in - dispatch_out + adjustment
        cur.execute(
            "INSERT INTO fg_stock (date,factory,product,fg_code,production_in,dispatch_out,"
            "adjustment,closing_stock,source_module,source_ref_id,created_at,movement_type) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (str(date_val), fac, product, fg_code, production_in, dispatch_out, adjustment,
             closing, source_module, source_ref_id, _now_iso(), movement_type)
        )
    return closing

# ── FG stock edit/delete integrity (Sections 7 & 8) ─────────────────────────
# Production and Dispatch each write exactly one fg_stock row per save, tagged
# with (source_module, source_ref_id). To keep the ledger truthful across
# edits/deletes without ever mutating a historical row, every correction is
# itself a *new* ledger row that exactly cancels the source's current net
# contribution. Summing all rows for a given (source_module, source_ref_id)
# therefore always equals that source's current, post-edit effect on FG stock
# — this is what makes repeated edits (edit → edit → edit) still net out
# correctly instead of drifting.
def get_fg_source_net(source_module: str, source_ref_id: int) -> dict:
    """Current net FG-stock contribution of one source record, summed across
    every ledger row ever written for it (original entry + any reversals/
    corrections already applied)."""
    row = cur.execute(
        "SELECT COALESCE(SUM(production_in),0), COALESCE(SUM(dispatch_out),0), "
        "COALESCE(SUM(adjustment),0) FROM fg_stock WHERE source_module=? AND source_ref_id=?",
        (source_module, source_ref_id)
    ).fetchone()
    return {"production_in": row[0] or 0.0, "dispatch_out": row[1] or 0.0,
            "adjustment": row[2] or 0.0}

def reverse_fg_stock_for_source(fac: str, product: str, source_module: str,
                                 source_ref_id: int) -> float | None:
    """Fully reverses one source record's current net FG-stock contribution
    by appending an exactly-offsetting ledger row under the *same*
    (factory, product) it was originally posted against. Returns the new
    closing balance for that factory+product, or None if the source never
    had any FG-stock effect to reverse (e.g. it predates this ledger, or a
    prior reversal already zeroed it out — never double-reverses)."""
    net = get_fg_source_net(source_module, source_ref_id)
    if not (net["production_in"] or net["dispatch_out"] or net["adjustment"]):
        return None
    return record_fg_stock_movement(
        datetime.date.today(), fac, product,
        production_in=-net["production_in"], dispatch_out=-net["dispatch_out"],
        adjustment=-net["adjustment"], source_module=source_module,
        source_ref_id=source_ref_id, movement_type="Reversal"
    )

# ── FG canonical stock unit (Section 6) ──────────────────────────────────────
# Production is entered as a weight (MT internally, displayed/entered in
# whatever unit the sidebar UNIT SYSTEM selector is set to). Dispatch is
# entered as a plain "Qty" — historically and in every existing sales record,
# that number is a packed-unit count (bags/pieces), not a weight. Those are
# not the same kind of quantity and must never be added/subtracted directly.
# fg_product_unit.pack_weight_kg is the weight of one packed unit for a given
# product; once set, Production's weight is converted into that same packed
# unit before it's written to fg_stock. Dispatch's Qty is left as-is — it's
# already in the canonical unit by definition (that's what "Qty" bags means).
DEFAULT_FG_STOCK_UNIT = "Bags"

def get_fg_stock_unit_cfg(product: str) -> dict:
    row = cur.execute(
        "SELECT stock_unit, pack_weight_kg FROM fg_product_unit WHERE product=?", (product,)
    ).fetchone()
    if row:
        return {"stock_unit": row[0] or DEFAULT_FG_STOCK_UNIT, "pack_weight_kg": row[1]}
    return {"stock_unit": DEFAULT_FG_STOCK_UNIT, "pack_weight_kg": None}

def set_fg_stock_unit_cfg(product: str, stock_unit: str, pack_weight_kg: float | None,
                           updated_by: str) -> None:
    cur.execute(
        "INSERT INTO fg_product_unit (product,stock_unit,pack_weight_kg,updated_by,updated_at) "
        "VALUES (?,?,?,?,?) ON CONFLICT(product) DO UPDATE SET "
        "stock_unit=excluded.stock_unit, pack_weight_kg=excluded.pack_weight_kg, "
        "updated_by=excluded.updated_by, updated_at=excluded.updated_at",
        (product, stock_unit.strip() or DEFAULT_FG_STOCK_UNIT, pack_weight_kg,
         updated_by, _now_iso())
    )
    conn.commit()

def convert_production_qty_to_fg_unit(qty_display: float, product: str) -> tuple[float, bool, str]:
    """Converts a Production quantity (entered in the sidebar's weight unit,
    `qty_display`) into the product's canonical FG stock unit.
    Returns (converted_qty, is_exact, note).
    is_exact=False means no reliable conversion exists yet (no pack weight on
    file for a packed-unit product) — the caller must surface this rather
    than silently writing an incompatible-unit number to the ledger."""
    qty_kg = to_mt(qty_display) * 1000.0  # normalise via the existing MT converter
    cfg = get_fg_stock_unit_cfg(product)
    stock_unit = cfg["stock_unit"]
    pack_kg = cfg["pack_weight_kg"]
    su = stock_unit.strip().lower()
    if su in ("kg", "kilogram", "kilograms"):
        return qty_kg, True, ""
    if su in ("mt", "metric tonne", "metric tonnes", "tonne", "tonnes", "ton"):
        return qty_kg / 1000.0, True, ""
    # Packed-unit stock (bags, pieces, drums, ...) — needs a pack weight.
    if pack_kg and pack_kg > 0:
        return qty_kg / pack_kg, True, ""
    return qty_kg, False, (
        f"No pack weight on file for '{product}' (stock unit: {stock_unit}). "
        f"Recorded FG movement in KG as an interim value — set the pack weight in "
        f"Production → ⚙️ FG Stock Unit Settings so this converts correctly."
    )

def log_reconciliation(check_type: str, fac: str, item_code: str, period_start, period_end,
                        qty_a: float, qty_b: float, detail: str = "",
                        critical_threshold: float = 50) -> dict:
    """Compares two quantities, classifies severity, and appends one row to
    inventory_reconciliation. Never modifies qty_a/qty_b's source records."""
    diff = round((qty_a or 0) - (qty_b or 0), 4)
    if diff == 0:
        severity = "Matched"
    elif abs(diff) >= critical_threshold:
        severity = "Critical"
    else:
        severity = "Mismatch"
    cur.execute(
        "INSERT INTO inventory_reconciliation (check_type,factory,item_code,period_start,"
        "period_end,qty_source_a,qty_source_b,difference,severity,detail,checked_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (check_type, fac, item_code, str(period_start), str(period_end),
         qty_a, qty_b, diff, severity, detail, _now_iso())
    )
    conn.commit()
    return {"check_type": check_type, "factory": fac, "item_code": item_code,
            "qty_a": qty_a, "qty_b": qty_b, "difference": diff, "severity": severity,
            "detail": detail, "checked_at": _now_iso()}

def reconcile_rm_incoming(d_start_val, d_end_val, fac_filter: str | None = None) -> list[dict]:
    """QC Incoming (rm_batches, Approved) vs Stock Incoming (stock.received),
    aggregated per factory+material over the date window — the two sides
    don't share a transaction ID, so this compares totals, not line items."""
    results = []
    fac_clause = " AND factory=?" if fac_filter and fac_filter != ALL_FACTORIES else ""
    fac_param  = (fac_filter,) if fac_clause else ()
    qc_rows = cur.execute(
        "SELECT factory, material, SUM(quantity) FROM rm_batches "
        "WHERE status='Approved' AND received_date BETWEEN ? AND ?" + fac_clause +
        " GROUP BY factory, material",
        (str(d_start_val), str(d_end_val)) + fac_param
    ).fetchall()
    for fac, material, qc_qty in qc_rows:
        canon = canonical_material(material)
        stk_row = cur.execute(
            "SELECT COALESCE(SUM(received),0) FROM stock WHERE factory=? AND date BETWEEN ? AND ? "
            "AND material=?", (fac, str(d_start_val), str(d_end_val), canon)
        ).fetchone()
        stk_qty = stk_row[0] if stk_row else 0
        results.append(log_reconciliation(
            "RM_Incoming", fac, get_lab_code(canon) or canon, d_start_val, d_end_val,
            qc_qty or 0, stk_qty or 0, f"QC rm_batches vs Stock received — {canon}"
        ))
    return results

def reconcile_rm_used(d_start_val, d_end_val, fac_filter: str | None = None) -> list[dict]:
    """QC Material Used (production_batch_materials, via the rm_batch it drew
    from) vs Stock Material Used (stock.used), aggregated per factory+material."""
    results = []
    fac_clause = " AND rb.factory=?" if fac_filter and fac_filter != ALL_FACTORIES else ""
    fac_param  = (fac_filter,) if fac_clause else ()
    qc_rows = cur.execute(
        "SELECT rb.factory, rb.material, SUM(pbm.qty_used) FROM production_batch_materials pbm "
        "JOIN rm_batches rb ON rb.id = pbm.rm_batch_id "
        "JOIN production_batches pb ON pb.id = pbm.production_batch_id "
        "WHERE pb.created_at BETWEEN ? AND ?" + fac_clause +
        " GROUP BY rb.factory, rb.material",
        (str(d_start_val) + "T00:00:00", str(d_end_val) + "T23:59:59") + fac_param
    ).fetchall()
    for fac, material, qc_qty in qc_rows:
        canon = canonical_material(material)
        stk_row = cur.execute(
            "SELECT COALESCE(SUM(used),0) FROM stock WHERE factory=? AND date BETWEEN ? AND ? "
            "AND material=?", (fac, str(d_start_val), str(d_end_val), canon)
        ).fetchone()
        stk_qty = stk_row[0] if stk_row else 0
        results.append(log_reconciliation(
            "RM_Used", fac, get_lab_code(canon) or canon, d_start_val, d_end_val,
            qc_qty or 0, stk_qty or 0, f"QC production_batch_materials vs Stock used — {canon}"
        ))
    return results

def reconcile_dispatch_quality(d_start_val, d_end_val, fac_filter: str | None = None) -> list[dict]:
    """Dispatch (sales) vs Quality Dispatch — Section 11 fix.

    A batch COUNT is never treated as a quantity. Two genuinely different
    comparisons are run, and every result is labelled which one it is:

    1. LINKED — sales.production_batch_id points at a specific QC batch.
       Compares actual Dispatch qty vs that batch's recorded output quantity
       (production_batches.quantity — see the Quality module's "Create Batch"
       form). If the linked batch predates quantity capture and has none on
       file, the comparison is skipped and counted separately as
       "unverifiable" rather than silently scored as a match.
    2. FALLBACK — dispatches with no batch link at all (the norm for
       historical data, since the field is optional). Falls back to
       aggregate Dispatch qty vs aggregate Production output qty (the same
       source Production posts to FG Stock) for that factory+product+period.
       This is explicitly a weaker, aggregate-level proxy — never presented
       as a verified batch-level match.
    """
    results = []
    fac_clause = " AND s.factory=?" if fac_filter and fac_filter != ALL_FACTORIES else ""
    fac_param  = (fac_filter,) if fac_clause else ()

    # ── 1) LINKED: real batch-level quantity comparison ─────────────────────
    linked_rows = cur.execute(
        "SELECT s.factory, s.product, SUM(s.qty), "
        "       SUM(CASE WHEN pb.quantity IS NOT NULL THEN pb.quantity ELSE 0 END), "
        "       SUM(CASE WHEN pb.quantity IS NULL THEN 1 ELSE 0 END), COUNT(*) "
        "FROM sales s JOIN production_batches pb ON pb.id = s.production_batch_id "
        "WHERE s.date BETWEEN ? AND ?" + fac_clause + " GROUP BY s.factory, s.product",
        (str(d_start_val), str(d_end_val)) + fac_param
    ).fetchall()
    for fac, product, disp_qty, qc_qty, n_missing, n_total in linked_rows:
        if n_missing == n_total:
            # Every linked batch in this group is pre-quantity-capture — there is
            # nothing real to compare; log it as unverifiable, not as a match.
            results.append(log_reconciliation(
                "Dispatch_Quality_Unverifiable", fac, product, d_start_val, d_end_val,
                disp_qty or 0, 0,
                f"{n_total} dispatch(es) linked to a QC batch, but none of the linked "
                f"batches have an output quantity on file (created before quantity "
                f"capture was added) — cannot verify, do not treat as matched."
            ))
            continue
        detail = "Dispatch qty vs linked QC batch output quantity (production_batches.quantity)."
        if n_missing:
            detail += (f" {n_missing} of {n_total} linked batch(es) have no quantity on "
                       f"file and were excluded from the QC-side total below.")
        results.append(log_reconciliation(
            "Dispatch_Quality_Linked", fac, product, d_start_val, d_end_val,
            disp_qty or 0, qc_qty or 0, detail
        ))

    # ── 2) FALLBACK: unlinked dispatches, aggregate proxy vs Production ─────
    unlinked_rows = cur.execute(
        "SELECT s.factory, s.product, SUM(s.qty) FROM sales s "
        "WHERE s.production_batch_id IS NULL AND s.date BETWEEN ? AND ?" + fac_clause +
        " GROUP BY s.factory, s.product",
        (str(d_start_val), str(d_end_val)) + fac_param
    ).fetchall()
    prod_fac_clause = fac_clause.replace("s.factory", "factory")
    for fac, product, disp_qty in unlinked_rows:
        prod_row = cur.execute(
            "SELECT COALESCE(SUM(production),0) FROM production WHERE product=? "
            "AND date BETWEEN ? AND ?" + prod_fac_clause,
            (product, str(d_start_val), str(d_end_val)) + fac_param
        ).fetchone()
        prod_mt = prod_row[0] if prod_row else 0
        _fg_qty, _fg_exact, _ = convert_production_qty_to_fg_unit(from_mt(prod_mt or 0), product)
        results.append(log_reconciliation(
            "Dispatch_Quality_Fallback", fac, product, d_start_val, d_end_val,
            disp_qty or 0, _fg_qty,
            "⚠️ FALLBACK — no QC batch link on these dispatch records. Weak, "
            "aggregate-level match: total Dispatch qty vs total Production output "
            "(converted to FG stock unit) for this factory+product+period — "
            "not a verified batch-level check." +
            ("" if _fg_exact else " Production-side conversion is also unverified — "
             "no pack weight on file for this product.")
        ))
    return results

def reconcile_fg_stock(fac_filter: str | None = None) -> list[dict]:
    """Self-check: the latest fg_stock closing balance for each factory+product
    vs an independent re-derivation from the full fg_stock ledger."""
    results = []
    fac_clause = " AND factory=?" if fac_filter and fac_filter != ALL_FACTORIES else ""
    fac_param  = (fac_filter,) if fac_clause else ()
    pairs = cur.execute(
        "SELECT DISTINCT factory, product FROM fg_stock WHERE 1=1" + fac_clause, fac_param
    ).fetchall()
    for fac, product in pairs:
        recorded = get_fg_closing_stock(fac, product)
        derived_row = cur.execute(
            "SELECT COALESCE(SUM(production_in),0) - COALESCE(SUM(dispatch_out),0) "
            "+ COALESCE(SUM(adjustment),0) FROM fg_stock WHERE factory=? AND product=?",
            (fac, product)
        ).fetchone()
        derived = derived_row[0] if derived_row else 0
        results.append(log_reconciliation(
            "FG_Stock", fac, product, "-", "-", recorded, derived,
            "Latest fg_stock closing_stock vs full-ledger re-derivation"
        ))
    return results

def reconcile_rm_stock(fac_filter: str | None = None) -> list[dict]:
    """Self-check: the latest stock.closing_stock for each factory+material
    vs an independent re-derivation from the full stock ledger."""
    results = []
    fac_clause = " AND factory=?" if fac_filter and fac_filter != ALL_FACTORIES else ""
    fac_param  = (fac_filter,) if fac_clause else ()
    pairs = cur.execute(
        "SELECT DISTINCT factory, material FROM stock WHERE 1=1" + fac_clause, fac_param
    ).fetchall()
    for fac, material in pairs:
        recorded_row = cur.execute(
            "SELECT closing_stock FROM stock WHERE factory=? AND material=? ORDER BY id DESC LIMIT 1",
            (fac, material)
        ).fetchone()
        recorded = recorded_row[0] if recorded_row else 0
        derived_row = cur.execute(
            "SELECT COALESCE(SUM(received),0) - COALESCE(SUM(used),0) FROM stock "
            "WHERE factory=? AND material=?", (fac, material)
        ).fetchone()
        derived = derived_row[0] if derived_row else 0
        results.append(log_reconciliation(
            "RM_Stock", fac, get_lab_code(material) or material, "-", "-", recorded, derived,
            "Latest stock.closing_stock vs full-ledger re-derivation"
        ))
    return results

def run_all_reconciliations(d_start_val, d_end_val, fac_filter: str | None = None) -> dict:
    """Runs every check and returns a combined summary. Called on demand from
    the Reconciliation module — never runs automatically on every page load,
    to avoid writing to inventory_reconciliation on every single rerun."""
    return {
        "RM Incoming — QC vs Stock":       reconcile_rm_incoming(d_start_val, d_end_val, fac_filter),
        "RM Used — QC vs Stock":           reconcile_rm_used(d_start_val, d_end_val, fac_filter),
        "Dispatch vs Quality":             reconcile_dispatch_quality(d_start_val, d_end_val, fac_filter),
        "FG Stock self-check":             reconcile_fg_stock(fac_filter),
        "RM Stock self-check":             reconcile_rm_stock(fac_filter),
    }

# ── Customer master ───────────────────────────────────────────────────────
@st.cache_data(ttl=120)
@st.cache_data(show_spinner=False)
def _load_customers_cached(_version: int) -> list[str]:
    df = pd.read_sql_query("SELECT name FROM customers ORDER BY name", conn)
    return df["name"].tolist() if not df.empty else []

def load_customers() -> list[str]:
    return _load_customers_cached(_data_version["v"])

CUSTOMER_LIST = load_customers()

# ── load all tables (full + filtered) — NEW: skeleton loader instead of a
# bare spinner, since this runs on every module load for every user ────────
_data_skel = show_skeleton_cards(count=5)
prod_df       = load_filtered("production",  factory, d_start, d_end)
sand_df       = load_filtered("sand",        factory, d_start, d_end)
stock_df      = load_filtered("stock",       factory, d_start, d_end)
sales_df      = load_filtered("sales",       factory, d_start, d_end)   # Dispatch table
so_df         = load_filtered("sales_orders",factory, d_start, d_end)   # new Sales table
cost_df       = load_filtered("costs",       factory, d_start, d_end)
log_df        = load_filtered("daily_log",   factory, d_start, d_end)

prod_all      = load("production")
sales_all     = load("sales")          # Dispatch (used for P&L / Dashboard revenue)
so_all        = load("sales_orders")   # new Sales
cost_all      = load("costs")
_data_skel.empty()

# ── NEW: Low-stock → procurement auto-trigger ─────────────────────────────────
# Runs once per session per day (cheap guard via session_state) rather than on
# every single rerun. Admins can force an immediate re-scan from
# Procurement → Settings.
_today_str = str(datetime.date.today())
if st.session_state.get("procurement_scan_date") != _today_str:
    _new_proc_alerts = scan_low_stock_and_trigger_procurement()
    st.session_state["procurement_scan_date"] = _today_str
    for _alert in _new_proc_alerts:
        _toast_msg = f"⚠️ Low stock: {_alert['material']} @ {_alert['factory']} — PR-{_alert['request_id']:05d} opened"
        try:
            st.toast(_toast_msg, icon="⚠️")
        except Exception:
            # Older Streamlit versions may not have st.toast — fall back silently,
            # the alert is still visible in the Procurement module either way.
            pass

# ================= 360° DETAIL PAGES =================
# NEW: "click a batch / customer / material, see everything about it on one
# page" — instead of the same story being scattered across Quality, Stock,
# Dispatch, Sales, and Customers. These are opened via open_detail_view()
# (session_state override, checked once below, right before normal module
# routing) from: table rows in Quality/Stock/Customers, and from Global
# Search results.

def render_batch_detail_page(batch_no: str) -> None:
    detail_back_button("← Back to app")

    trace = get_batch_traceability(batch_no)
    if trace is None:
        st.error(f"Batch **{batch_no}** was not found — it may have been deleted.")
        return

    b = trace["batch"]
    st.title(f"🧪 Batch {b['batch_no']}")

    hc1, hc2, hc3, hc4 = st.columns(4)
    hc1.metric("Product", fg_label(b["product"]))
    hc2.metric("Factory", b["factory"])
    hc3.metric("Operator", b["operator"] or "—")
    with hc4:
        st.markdown(
            "<div style='font-size:10.5px;color:var(--fc-muted);text-transform:uppercase;"
            "letter-spacing:0.08em;font-weight:600;margin-bottom:6px;'>Status</div>",
            unsafe_allow_html=True,
        )
        _kind = ("error" if b["status"] in BATCH_HOLD_STAGE else
                 "success" if b["status"] == "Dispatched" else "info")
        st.markdown(status_pill(b["status"], _kind), unsafe_allow_html=True)

    st.markdown("#### 📍 Timeline")
    render_batch_progress(b["status"])

    tab_rm, tab_prod, tab_qc, tab_disp, tab_cust, tab_docs, tab_audit = st.tabs([
        "🧱 Raw Materials", "🏭 Production", "✅ QC Report", "🚚 Dispatch History",
        "🏢 Customer", "📄 Documents", "🕵️ Audit Trail"
    ])

    with tab_rm:
        if trace["materials"].empty:
            st.info("No raw materials linked to this batch yet.")
        else:
            st.dataframe(
                trace["materials"].rename(columns={
                    "material": "Material", "rm_batch_no": "RM Batch No.",
                    "supplier": "Supplier", "received_date": "Received",
                    "qty_used": "Qty Used", "incoming_decision": "Incoming QC"
                }),
                width='stretch', hide_index=True
            )

    with tab_prod:
        pc1, pc2 = st.columns(2)
        with pc1:
            st.markdown(f"**Formula / Recipe:** {b.get('formula') or '—'}")
            st.markdown(f"**Machine:** {b.get('machine') or '—'}")
        with pc2:
            st.markdown(f"**Shift:** {b.get('shift') or '—'}")
            st.markdown(f"**Created:** {(b.get('created_at') or '—')[:16]}")

    with tab_qc:
        for _label, _key in [("Process QC", "process_qc"), ("FG QC", "fg_qc"),
                              ("Packing QC", "packing_qc"), ("Dispatch QC", "dispatch_qc")]:
            _rec = trace[_key]
            with st.expander(_label, expanded=False):
                if not _rec:
                    st.caption("Not yet recorded.")
                else:
                    _show = {k: v for k, v in _rec.items()
                             if k not in ("id", "production_batch_id")}
                    st.table(pd.DataFrame(_show.items(), columns=["Field", "Value"]))
        if not trace["ncrs"].empty:
            st.markdown("##### ⚠️ Non-Conformance Reports")
            st.dataframe(
                trace["ncrs"][["source_stage", "description", "status", "raised_at"]]
                    .rename(columns={"source_stage": "Stage", "description": "Description",
                                      "status": "Status", "raised_at": "Raised"}),
                width='stretch', hide_index=True
            )

    with tab_disp:
        _dq = trace["dispatch_qc"]
        if not _dq:
            st.info("This batch hasn't reached Dispatch QC yet.")
        else:
            dc1, dc2, dc3 = st.columns(3)
            dc1.metric("Dispatch Status", _dq.get("status") or "—")
            dc2.metric("Approved By", _dq.get("approved_by") or "—")
            dc3.metric("Date", (_dq.get("date") or "—")[:10])
        st.caption(
            "Dispatch (sales) records in FCSC ERP are logged by product/customer/quantity, "
            "not by batch number, so there's no exact batch-to-invoice link yet. Shown "
            "below: recent dispatches of the same product from the same factory, for "
            "context — not a confirmed match to this specific batch."
        )
        _related_sales = pd.read_sql_query(
            "SELECT date, customer, qty, total, status, challan_no FROM sales "
            "WHERE product = ? AND factory = ? ORDER BY date DESC LIMIT 10",
            conn, params=(b["product"], b["factory"])
        )
        if _related_sales.empty:
            st.caption("No related dispatch records found.")
        else:
            _related_sales["total"] = _related_sales["total"].apply(fmt_inr)
            st.dataframe(
                _related_sales.rename(columns={"date": "Date", "customer": "Customer",
                                                 "qty": "Qty", "total": "Value",
                                                 "status": "Payment", "challan_no": "Challan No."}),
                width='stretch', hide_index=True
            )

    with tab_cust:
        st.caption(
            "Customer isn't captured at the batch level today — it's captured at the "
            "Dispatch/Sales level. Customers who purchased this product from this "
            "factory recently are listed here for reference, not a confirmed match."
        )
        _cust_matches = pd.read_sql_query(
            "SELECT DISTINCT customer FROM sales WHERE product = ? AND factory = ? "
            "ORDER BY customer LIMIT 10",
            conn, params=(b["product"], b["factory"])
        )
        if _cust_matches.empty:
            st.info("No matching customer records yet.")
        else:
            for _, _cm in _cust_matches.iterrows():
                ccol1, ccol2 = st.columns([5, 1])
                ccol1.markdown(f"🏢 {_cm['customer']}")
                if ccol2.button("360° →", key=f"batchpage_cust_{_cm['customer']}",
                                 use_container_width=True):
                    open_detail_view("customer", _cm["customer"])

    with tab_docs:
        dcol1, dcol2 = st.columns(2)
        with dcol1:
            if HAS_REPORTLAB:
                pdf_bytes = generate_traceability_pdf(trace)
                st.download_button(
                    "📥 Download Traceability Certificate (PDF)",
                    data=pdf_bytes, file_name=f"FCSC_Traceability_{batch_no}.pdf",
                    mime="application/pdf", key="batchpage_pdf_dl",
                )
            else:
                st.warning("Install `reportlab` (pip install reportlab) to enable PDF export.")
        with dcol2:
            if HAS_QRCODE:
                qr_png = generate_batch_qr_png(batch_no)
                st.image(qr_png, width=140, caption=f"Batch {batch_no}")
            else:
                st.warning("Install `qrcode` (pip install qrcode[pil]) to enable QR codes.")

    with tab_audit:
        _audit_rows = pd.read_sql_query(
            "SELECT timestamp, username, action, detail FROM audit_log "
            "WHERE tbl = 'production_batches' AND record_id = ? ORDER BY id DESC",
            conn, params=(str(b["id"]),)
        )
        if _audit_rows.empty:
            st.info("No audit entries recorded for this batch yet.")
        else:
            st.dataframe(
                _audit_rows.rename(columns={"timestamp": "When", "username": "User",
                                              "action": "Action", "detail": "Detail"}),
                width='stretch', hide_index=True
            )


def render_customer_360(customer_name: str) -> None:
    detail_back_button("← Back to app")

    _cust = cur.execute(
        "SELECT id, name, gstin, address, phone FROM customers WHERE name = ?",
        (customer_name,)
    ).fetchone()
    if _cust is None:
        st.error(f"Customer **{customer_name}** was not found — it may have been deleted.")
        return
    _cust_dict = {"id": _cust[0], "name": _cust[1], "gstin": _cust[2],
                   "address": _cust[3], "phone": _cust[4]}

    st.title(f"🏢 {_cust_dict['name']}")
    st.caption(f"GSTIN: {_cust_dict['gstin'] or '—'} · Phone: {_cust_dict['phone'] or '—'}")

    _orders = pd.read_sql_query(
        "SELECT * FROM sales_orders WHERE customer = ? ORDER BY date DESC",
        conn, params=(customer_name,))
    _dispatches = pd.read_sql_query(
        "SELECT * FROM sales WHERE customer = ? ORDER BY date DESC",
        conn, params=(customer_name,))

    _total_orders  = len(_orders) + len(_dispatches)
    _outstanding   = (_dispatches[_dispatches["status"].isin(["Pending", "Partial", "Overdue"])]["total"].sum()
                      if not _dispatches.empty and "status" in _dispatches.columns else 0)
    _last_dispatch = _dispatches["date"].max() if not _dispatches.empty else "—"
    _products      = sorted(
        set(_orders["product"].tolist() if not _orders.empty else []) |
        set(_dispatches["product"].tolist() if not _dispatches.empty else [])
    )

    kc1, kc2, kc3, kc4 = st.columns(4)
    kc1.metric("Total Orders", _total_orders)
    kc2.metric("Outstanding", fmt_inr(_outstanding))
    kc3.metric("Last Dispatch", _last_dispatch)
    kc4.metric("Products Purchased", len(_products))

    tab_orders, tab_products, tab_complaints, tab_payment, tab_docs, tab_contact = st.tabs([
        "📈 Orders", "📦 Products Purchased", "⚠️ Complaints",
        "💳 Payment History", "📄 Documents", "☎️ Contact"
    ])

    with tab_orders:
        st.markdown("##### Sales Orders")
        if _orders.empty:
            st.info("No sales orders on file.")
        else:
            _od = _orders.copy()
            _od["total"] = _od["total"].apply(fmt_inr)
            st.dataframe(_od.drop(columns=["id"], errors="ignore"), width='stretch', hide_index=True)
        st.markdown("##### Dispatches")
        if _dispatches.empty:
            st.info("No dispatch records on file.")
        else:
            _dd = _dispatches.copy()
            _dd["total"] = _dd["total"].apply(fmt_inr)
            st.dataframe(_dd.drop(columns=["id"], errors="ignore"), width='stretch', hide_index=True)

    with tab_products:
        if not _products:
            st.info("No products purchased yet.")
        else:
            for _p in _products:
                st.markdown(f"- {fg_label(_p)}")

    with tab_complaints:
        st.caption(
            "FCSC ERP doesn't have a dedicated customer-complaints module yet — "
            "NCRs are tracked per batch, not per customer. This section will "
            "populate once that link exists."
        )
        st.info("No complaints tracked yet.")

    with tab_payment:
        if _dispatches.empty or "status" not in _dispatches.columns:
            st.info("No payment history on file.")
        else:
            _pay = (_dispatches.groupby("status")["total"].agg(["sum", "count"]).reset_index()
                     .rename(columns={"status": "Status", "sum": "Amount", "count": "Orders"}))
            _pay["Amount"] = _pay["Amount"].apply(fmt_inr)
            st.dataframe(_pay, width='stretch', hide_index=True)
            _pd_ = _dispatches[["date", "product", "qty", "total", "status", "challan_no"]].copy()
            _pd_["total"] = _pd_["total"].apply(fmt_inr)
            _pd_.insert(2, "rm_code", _pd_["product"].apply(get_fg_code))
            st.dataframe(
                _pd_.rename(columns={"date": "Date", "product": "Product", "rm_code": "RM Code",
                                       "qty": "Qty", "total": "Value", "status": "Status",
                                       "challan_no": "Challan No."}),
                width='stretch', hide_index=True
            )

    with tab_docs:
        if _orders.empty:
            st.info("No sales orders to invoice yet.")
        elif not HAS_REPORTLAB:
            st.warning("Install `reportlab` (pip install reportlab) to enable invoice PDF export.")
        else:
            _o_opts = {
                f"#{r['id']:05d} — {fg_label(r['product'])} — {fmt_inr(r['total'])} ({r['date']})": r["id"]
                for _, r in _orders.iterrows()
            }
            _o_pick = st.selectbox("Select order to invoice", list(_o_opts.keys()),
                                    key="cust360_inv_pick")
            _o_id  = _o_opts[_o_pick]
            _o_row = _orders[_orders["id"] == _o_id].iloc[0].to_dict()
            pdf_bytes = generate_invoice_pdf(_o_row, _cust_dict)
            st.download_button(
                "📥 Download Invoice (PDF)", data=pdf_bytes,
                file_name=f"FCSC_Invoice_{_o_id:05d}.pdf", mime="application/pdf",
                key="cust360_inv_dl",
            )

    with tab_contact:
        st.markdown("**Contact on file:**")
        st.markdown(f"📍 {_cust_dict['address'] or '—'}")
        st.markdown(f"📞 {_cust_dict['phone'] or '—'}")
        st.markdown(f"🧾 GSTIN: {_cust_dict['gstin'] or '—'}")
        st.caption(
            "FCSC ERP currently stores one contact per customer. A multi-contact "
            "directory (names/roles per person) isn't tracked yet."
        )


def render_material_360(material_name: str) -> None:
    detail_back_button("← Back to app")

    st.title(f"🧱 {material_name}")

    _mm_row = cur.execute(
        "SELECT lab_code, procurement_code, category, status FROM materials_master WHERE name = ?",
        (material_name,)
    ).fetchone()
    if _mm_row:
        _lab_code, _proc_code, _category, _status = _mm_row
        idc1, idc2, idc3 = st.columns(3)
        idc1.metric("Lab Code", _lab_code or "—")
        idc2.metric("Procurement Code", _proc_code or "⏳ Pending")
        idc3.metric("Category", _category)
        if _status == "Pending Code Confirmation":
            st.warning("⏳ This material's Procurement Code is still awaiting plant-team "
                       "confirmation — see the Material Master tab under Stock to update it.")

    _hist = pd.read_sql_query(
        "SELECT * FROM stock WHERE material = ? ORDER BY date", conn, params=(material_name,))
    if _hist.empty:
        st.info(f"No stock records found yet for **{material_name}**.")
        return

    _hist_range = _hist[(_hist["date"] >= str(d_start)) & (_hist["date"] <= str(d_end))]
    _opening = None
    if not _hist_range.empty:
        _first = _hist_range.sort_values("date").iloc[0]
        _opening = _first["closing_stock"] - _first["received"] + _first["used"]

    _today_str_m = str(datetime.date.today())
    _today_used  = _hist[_hist["date"] == _today_str_m]["used"].sum()
    _avg_used    = _hist_range["used"].mean() if not _hist_range.empty else _hist["used"].mean()

    _vendor_name = get_default_vendor_for_material(material_name)
    _vendor      = get_vendor(_vendor_name) if _vendor_name else None

    _last_purchase = pd.read_sql_query(
        "SELECT supplier, batch_no, quantity, unit, received_date FROM rm_batches "
        "WHERE material = ? ORDER BY id DESC LIMIT 1", conn, params=(material_name,))

    kc1, kc2, kc3, kc4 = st.columns(4)
    kc1.metric("Opening Stock (range start)", f"{_opening:,.0f}" if _opening is not None else "—")
    kc2.metric("Today's Consumption", f"{_today_used:,.0f}")
    kc3.metric("Average Consumption", f"{_avg_used:,.1f}" if pd.notna(_avg_used) else "—")
    kc4.metric("Preferred Supplier", _vendor_name or "Not set")

    tab_stock, tab_supplier, tab_exhaust, tab_pr = st.tabs([
        "📦 Factory-wise Stock", "🚚 Supplier & Last Purchase",
        "⏳ Expected Exhaustion", "🛒 Purchase Requests"
    ])

    with tab_stock:
        _current = pd.read_sql_query(
            "SELECT material, factory, closing_stock, date FROM stock s1 "
            "WHERE material = ? AND id = (SELECT MAX(id) FROM stock s2 "
            "WHERE s2.material = s1.material AND s2.factory = s1.factory) ORDER BY factory",
            conn, params=(material_name,))
        if _current.empty:
            st.info("No current stock on file.")
        else:
            st.dataframe(
                _current.drop(columns=["material"])
                        .rename(columns={"factory": "Factory", "closing_stock": "Closing Stock",
                                          "date": "Last Updated"}),
                width='stretch', hide_index=True
            )
            _max = int(_current["closing_stock"].max()) or 1
            for _, row in _current.iterrows():
                _color = ("#6E1423" if row["closing_stock"] < 20 else
                          "#A8791E" if row["closing_stock"] < 50 else "#145C3C")
                progress_bar(row["factory"], row["closing_stock"], _max, color=_color)

    with tab_supplier:
        if _vendor:
            st.markdown(f"**Supplier:** {_vendor['name']}")
            st.markdown(f"**Email:** {_vendor['email'] or '—'}")
            st.markdown(f"**Phone:** {_vendor['phone'] or '—'}")
            st.markdown(f"**Lead Time:** {_vendor['lead_time_days']} day(s)")
        else:
            st.info("No preferred supplier linked yet — set one under Procurement → 🏭 Vendors.")
        st.markdown("---")
        st.markdown("##### Last Purchase")
        if _last_purchase.empty:
            st.caption("No incoming-material records on file for this material.")
        else:
            _lp = _last_purchase.iloc[0]
            lc1, lc2, lc3 = st.columns(3)
            lc1.metric("Supplier", _lp["supplier"] or "—")
            lc2.metric("Quantity", f"{_lp['quantity']:g} {_lp['unit']}")
            lc3.metric("Received", _lp["received_date"] or "—")

    with tab_exhaust:
        _forecast = reorder_forecast()
        if _forecast.empty:
            st.info("Not enough stock history yet to forecast exhaustion.")
        else:
            _mf = _forecast[_forecast["material"] == material_name]
            if _mf.empty:
                st.info("No forecast available for this material yet.")
            else:
                _mf_disp = _mf[["factory", "closing_stock", "avg_daily_used",
                                  "threshold", "days_to_threshold", "projected_reorder_date"]].copy()
                _mf_disp["days_to_threshold"] = _mf_disp["days_to_threshold"].apply(
                    lambda d: f"{d:.1f}" if pd.notna(d) else "—")
                st.dataframe(
                    _mf_disp.rename(columns={
                        "factory": "Factory", "closing_stock": "Current Stock",
                        "avg_daily_used": "Avg Daily Use", "threshold": "Reorder Threshold",
                        "days_to_threshold": "Days Remaining",
                        "projected_reorder_date": "Projected Reorder Date"}),
                    width='stretch', hide_index=True
                )

    with tab_pr:
        _prs = pd.read_sql_query(
            "SELECT id, created_at, factory, qty_suggested, unit, status, closed_at "
            "FROM procurement_requests WHERE material = ? ORDER BY id DESC LIMIT 20",
            conn, params=(material_name,))
        if _prs.empty:
            st.info("No purchase requests raised for this material yet.")
        else:
            st.dataframe(
                _prs.rename(columns={"id": "PR #", "created_at": "Created", "factory": "Factory",
                                       "qty_suggested": "Qty Suggested", "unit": "Unit",
                                       "status": "Status", "closed_at": "Closed"}),
                width='stretch', hide_index=True
            )


_DETAIL_RENDERERS = {
    "batch":    render_batch_detail_page,
    "customer": render_customer_360,
    "material": render_material_360,
}


# ================= AI ENGINE =================
def generate_ai_insights(p_df: pd.DataFrame, s_df: pd.DataFrame,
                          c_df: pd.DataFrame) -> list[tuple[str, str]]:
    insights = []

    if len(p_df) >= 2:
        df   = p_df.sort_values("date")
        last = df.iloc[-1]
        prev = df.iloc[-2]

        # FIX: Use safe_pct_change utility instead of inline guarded divisions.
        prod_chg = safe_pct_change(last["production"], prev["production"])
        if prod_chg is not None and last["production"] < prev["production"]:
            insights.append(("warning",
                f"Production dropped {abs(prod_chg):.1f}% vs previous entry "
                f"({from_mt(prev['production']):.2f} → {from_mt(last['production']):.2f} {unit})"))
        elif prod_chg is not None:
            insights.append(("success",
                f"Production up {prod_chg:.1f}% vs previous entry"))

        if last["efficiency"] < 0.5:
            insights.append(("error",
                f"Low efficiency on latest entry: {last['efficiency']:.4f} (threshold: 0.50)"))
        else:
            eff_chg = safe_pct_change(last["efficiency"], prev["efficiency"])
            if eff_chg is not None and eff_chg > 0:
                insights.append(("success",
                    f"Efficiency improved {eff_chg:.1f}% vs previous entry"))

        if last["labour"] > prev["labour"] and last["production"] <= prev["production"]:
            insights.append(("warning",
                "More workers deployed but output did not increase — review labour allocation"))

        if last["hours"] > prev["hours"] and last["efficiency"] < prev["efficiency"]:
            insights.append(("warning",
                "Longer hours but lower efficiency — possible fatigue or process bottleneck"))

    if not s_df.empty and not c_df.empty:
        rev    = s_df["total"].sum()
        cost   = c_df["amount"].sum()
        margin = safe_ratio_pct(rev - cost, rev)
        if cost > rev:
            insights.append(("error",
                f"⚠️ Running at LOSS — Costs ({fmt_inr(cost)}) > Revenue ({fmt_inr(rev)})"))
        elif margin is not None and margin < 10:
            insights.append(("warning",
                f"Thin margin: {margin:.1f}% — review pricing or cost structure"))
        else:
            m_str = f"{margin:.1f}%" if margin is not None else "—"
            insights.append(("success",
                f"Healthy margin: {m_str} | Revenue {fmt_inr(rev)} | Profit {fmt_inr(rev - cost)}"))

    if not s_df.empty and "status" in s_df.columns:
        pend = s_df[s_df["status"].isin(["Pending", "Overdue"])]["total"].sum()
        if pend > 0:
            insights.append(("warning", f"Pending / overdue payments: {fmt_inr(pend)}"))

    if not stock_df.empty:
        low = stock_df.sort_values("date").groupby(["factory", "material"]).last().reset_index()
        for _, row in low.iterrows():
            _th_row = cur.execute(
                "SELECT threshold FROM reorder_levels WHERE material=? AND factory=?",
                (row["material"], row["factory"])
            ).fetchone()
            _threshold = _th_row[0] if _th_row else DEFAULT_REORDER_THRESHOLD
            if row["closing_stock"] < _threshold:
                insights.append(("warning",
                    f"Low stock: {row['material']} at {row['factory']} "
                    f"({int(row['closing_stock'])} units, threshold {int(_threshold)}) — "
                    f"see Procurement module"))

    # NEW: surface open procurement requests so they aren't only visible
    # inside the Procurement module itself.
    _open_proc = cur.execute("SELECT COUNT(*) FROM procurement_requests WHERE status='Open'").fetchone()[0]
    if _open_proc:
        insights.append(("warning",
            f"🛒 {_open_proc} open procurement request(s) awaiting action"))

    # NEW: anomaly detection — flags a factory's efficiency dropping sharply
    # relative to ITS OWN trailing average, rather than only the fixed 0.50
    # cutoff above. A factory that normally runs at 0.55 and drops to 0.50
    # wouldn't trip the fixed threshold but is still a real anomaly for that
    # factory; this scales the bar to each factory's own normal range.
    if not p_df.empty and "factory" in p_df.columns:
        for _fac, _fac_df in p_df.groupby("factory"):
            _fac_df = _fac_df.sort_values("date")
            if len(_fac_df) < 6:
                continue  # not enough history for a trailing baseline yet
            _history = _fac_df["efficiency"].iloc[:-1]
            _latest_eff = _fac_df["efficiency"].iloc[-1]
            _mean, _std = _history.mean(), _history.std()
            if _std and _std > 0 and _latest_eff < _mean - 2 * _std:
                insights.append(("error",
                    f"📉 Anomaly at {_fac}: efficiency {_latest_eff:.3f} is more than 2 "
                    f"standard deviations below its own {len(_history)}-entry average "
                    f"({_mean:.3f} ± {_std:.3f}) — worth a closer look, even though it "
                    f"may be above the general 0.50 threshold"))

    if not insights:
        insights.append(("success", "✅ All systems stable — no issues detected"))

    return insights


# NEW: global search bar — rendered once, above every module, so it's
# always available regardless of which module is currently selected.
render_global_search(_is_admin, _user_factory, available_modules)


# ── 360° detail-page override ─────────────────────────────────────────────
# If a batch/customer/material 360° page is open, render it in place of the
# normal module content and stop — the sidebar (factory/module/date filters,
# logout, etc.) still renders as usual since it runs above this point.
_dv = st.session_state.get("_detail_view")
if _dv:
    _renderer = _DETAIL_RENDERERS.get(_dv.get("type"))
    if _renderer is None:
        st.error("Unknown detail view — returning to the app.")
        close_detail_view()
    else:
        _renderer(_dv["key"])
    st.stop()


# ─────────────────────────────────────────────────────────────────────────────
#  DASHBOARD
# ─────────────────────────────────────────────────────────────────────────────
if module == "Dashboard":

    fac_label = factory if factory != ALL_FACTORIES else "All Factories"

    # ── Page header: eyebrow / title / context — one clear read, no ornament ──
    st.markdown(
        f"<div class='fc-page-eyebrow'>{datetime.date.today().strftime('%A, %d %B %Y')}</div>"
        f"<h1 style='margin-bottom:0;'>Dashboard</h1>"
        f"<p class='fc-page-sub'>{fac_label}</p>",
        unsafe_allow_html=True,
    )
    st.markdown("<div class='fc-divider-tight'></div>", unsafe_allow_html=True)

    # Advisories folded under the header, not competing with it for attention.
    render_festival_banner(compact=True)
    render_monsoon_banner(compact=True)
    render_weather_advisory(None if factory == ALL_FACTORIES else factory)

    # ── Today: the number a plant manager checks first, promoted to the top
    # instead of buried in a collapsed expander ─────────────────────────────
    today_str  = str(datetime.date.today())
    _fac_q     = "AND factory=?" if factory != ALL_FACTORIES else ""
    _fac_p     = (factory,) if factory != ALL_FACTORIES else ()
    t_prod  = pd.read_sql_query(f"SELECT * FROM production WHERE date=? {_fac_q}",  conn, params=(today_str,*_fac_p))
    t_sales = pd.read_sql_query(f"SELECT * FROM sales WHERE date=? {_fac_q}",       conn, params=(today_str,*_fac_p))
    t_so    = pd.read_sql_query(f"SELECT * FROM sales_orders WHERE date=? {_fac_q}",conn, params=(today_str,*_fac_p))
    t_costs = pd.read_sql_query(f"SELECT * FROM costs WHERE date=? {_fac_q}",       conn, params=(today_str,*_fac_p))
    # FIX: Revenue = Dispatch only (goods actually shipped/invoiced). Sales
    # Orders are booked commitments, not revenue — see P&L module notes.
    _t_rev  = t_sales["total"].sum() if not t_sales.empty else 0
    _t_so   = t_so["total"].sum()    if not t_so.empty    else 0

    st.markdown("<div class='fc-section-label'>Today</div>", unsafe_allow_html=True)
    ts1, ts2, ts3, ts4 = st.columns(4)
    ts1.metric("Production", f"{from_mt(t_prod['production'].sum()):,.2f} {unit}" if not t_prod.empty else "—")
    ts2.metric("Revenue (Dispatched)", fmt_inr(_t_rev) if _t_rev else "—",
               help=f"Sales Orders booked today (not included): {fmt_inr(_t_so)}")
    ts3.metric("Costs",      fmt_inr(t_costs["amount"].sum()) if not t_costs.empty else "—")
    ts4.metric("Entries logged", len(t_prod) + len(t_sales) + len(t_so) + len(t_costs))

    st.markdown("<div class='fc-divider-tight'></div>", unsafe_allow_html=True)

    # FIX: Revenue = Dispatch only. Sales Orders (so_rev) are the order
    # book — shown alongside, never summed into recognised revenue.
    total_prod   = prod_df["production"].sum() if not prod_df.empty else 0
    disp_rev     = sales_df["total"].sum()     if not sales_df.empty else 0
    so_rev       = so_df["total"].sum()         if not so_df.empty   else 0
    revenue      = disp_rev             # Dispatch = recognised revenue
    cost         = cost_df["amount"].sum()     if not cost_df.empty else 0
    profit     = revenue - cost
    margin_pct = safe_ratio_pct(profit, revenue) or 0

    # ── Month-over-month comparison ────────────────────────────────────────
    _today      = datetime.date.today()
    _this_m     = _today.strftime("%Y-%m")
    _last_m     = (_today.replace(day=1) - datetime.timedelta(days=1)).strftime("%Y-%m")
    _fac_param  = (factory,) if factory != ALL_FACTORIES else ()
    _fac_clause = "AND factory=?" if factory != ALL_FACTORIES else ""

    def _month_sum(table: str, col: str, month: str) -> float:
        q  = f"SELECT COALESCE(SUM({col}),0) FROM {table} WHERE date LIKE ? {_fac_clause}"
        return pd.read_sql_query(q, conn, params=(f"{month}%", *_fac_param)).iloc[0,0]

    # FIX: month-over-month Revenue delta now tracks Dispatch only, matching
    # the Revenue metric it's attached to.
    _rev_this  = _month_sum("sales",        "total",      _this_m)
    _rev_last  = _month_sum("sales",        "total",      _last_m)
    _cost_this = _month_sum("costs",        "amount",     _this_m)
    _cost_last = _month_sum("costs",        "amount",     _last_m)
    _prod_this = _month_sum("production",   "production", _this_m)
    _prod_last = _month_sum("production",   "production", _last_m)

    def _mom_delta(this: float, last: float) -> str | None:
        chg = safe_pct_change(this, last)
        if chg is None: return None
        arrow = "▲" if chg >= 0 else "▼"
        return f"{arrow} {abs(chg):.1f}% vs last month"

    st.markdown(
        f"<div class='fc-section-label'>Selected range · "
        f"{d_start.strftime('%d %b')} – {d_end.strftime('%d %b %Y')}</div>",
        unsafe_allow_html=True,
    )
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric(f"Production ({unit})", f"{from_mt(total_prod):,.2f}",
              delta=_mom_delta(_prod_this, _prod_last))
    c2.metric("Revenue (Dispatched)",  fmt_inr(revenue),
              delta=_mom_delta(_rev_this,  _rev_last),
              help=f"Sales Orders booked in range (not included in Revenue): {fmt_inr(so_rev)}")
    c3.metric("Costs",    fmt_inr(cost),
              delta=_mom_delta(_cost_this, _cost_last),
              delta_color="inverse")
    c4.metric("Profit",   fmt_inr(profit),
              delta=f"{margin_pct:.1f}% margin" if revenue else None)
    c5.metric("Entries",  len(prod_df) + len(sales_df) + len(cost_df))

    # ── Attention: compact list, not stacked full-width alert boxes ────────
    _insights = generate_ai_insights(prod_df, sales_df, cost_df)
    if _insights:
        st.markdown("<div class='fc-section-label' style='margin-top:1.1rem;'>Attention</div>", unsafe_allow_html=True)
        _kind_map = {"error": "error", "warning": "warning", "success": "success"}
        _rows = "".join(
            f"<div style='display:flex;align-items:flex-start;gap:9px;padding:7px 0;"
            f"border-bottom:1px solid var(--fc-border-soft);font-size:13px;color:var(--fc-ink-soft);'>"
            f"<span class='fc-pill {_kind_map.get(k,'info')}' style='margin-top:1px;'>"
            f"{ {'error':'ISSUE','warning':'WATCH','success':'OK'}.get(k,'INFO') }</span>"
            f"<span>{msg}</span></div>"
            for k, msg in _insights
        )
        st.markdown(f"<div>{_rows}</div>", unsafe_allow_html=True)

    st.markdown("<div class='fc-divider-tight' style='margin-top:1.3rem;'></div>", unsafe_allow_html=True)

    col_l, col_r = st.columns(2)

    with col_l:
        st.markdown("<div class='fc-section-label'>Production over time</div>", unsafe_allow_html=True)
        if not prod_df.empty:
            ts = (prod_df.groupby("date")["production"]
                         .sum().reset_index().sort_values("date"))
            ts["production_display"] = ts["production"].apply(from_mt)
            if HAS_PLOTLY:
                fig = px.line(ts, x="date", y="production_display",
                              labels={"production_display": unit, "date": "Date"},
                              color_discrete_sequence=["#2B4C7E"],
                              markers=True, template="plotly_white")
                fig.update_layout(height=240, margin=dict(l=10,r=10,t=10,b=10),
                                   font_family="Inter", plot_bgcolor="rgba(0,0,0,0)",
                                   paper_bgcolor="rgba(0,0,0,0)")
                st.plotly_chart(fig, width='stretch')
            else:
                st.line_chart(ts.set_index("date")["production_display"])
        else:
            empty_chart_msg("No production data in selected range.")

    with col_r:
        st.markdown("<div class='fc-section-label'>Revenue vs. costs over time</div>", unsafe_allow_html=True)
        if not sales_df.empty or not cost_df.empty:
            rev_ts = (sales_df.groupby("date")["total"].sum().reset_index()
                      if not sales_df.empty else pd.DataFrame(columns=["date","total"]))
            cost_ts = (cost_df.groupby("date")["amount"].sum().reset_index()
                       if not cost_df.empty else pd.DataFrame(columns=["date","amount"]))
            rev_ts  = rev_ts.rename(columns={"total":  "Revenue"})
            cost_ts = cost_ts.rename(columns={"amount": "Costs"})
            merged = pd.merge(rev_ts, cost_ts, on="date", how="outer").fillna(0).sort_values("date")
            # FIX: when only Revenue or only Costs has rows in this range, the
            # other side starts as an empty, dtype-less placeholder DataFrame;
            # after the outer merge + fillna(0) that column can stay `object`
            # dtype while its sibling is float64, and Plotly Express refuses to
            # plot two y-columns of different dtypes ("cannot process wide-form
            # data with columns of different type"), crashing the whole page.
            merged["Revenue"] = merged["Revenue"].astype(float)
            merged["Costs"]   = merged["Costs"].astype(float)
            if HAS_PLOTLY:
                fig2 = px.line(merged, x="date", y=["Revenue", "Costs"],
                               color_discrete_map={"Revenue": "#1E6B45", "Costs": "#B3261E"},
                               markers=True, template="plotly_white")
                fig2.update_layout(height=240, margin=dict(l=10,r=10,t=10,b=10),
                                    legend=dict(orientation="h", y=-0.2),
                                    font_family="Inter", plot_bgcolor="rgba(0,0,0,0)",
                                    paper_bgcolor="rgba(0,0,0,0)")
                st.plotly_chart(fig2, width='stretch')
            else:
                st.line_chart(merged.set_index("date")[["Revenue", "Costs"]])
        else:
            empty_chart_msg("No sales or cost data.")

    st.markdown("<div class='fc-divider-tight'></div>", unsafe_allow_html=True)

    st.markdown("<div class='fc-section-label'>Factory profit ranking · all time</div>", unsafe_allow_html=True)
    if not sales_all.empty or not cost_all.empty:
        # Combine Dispatch + Sales Orders revenue per factory
        _disp_g  = sales_all.groupby("factory")["total"].sum().reset_index() \
                   if not sales_all.empty else pd.DataFrame(columns=["factory","total"])
        _so_g    = so_all.groupby("factory")["total"].sum().reset_index() \
                   if not so_all.empty else pd.DataFrame(columns=["factory","total"])
        _rev_combined = pd.merge(_disp_g, _so_g, on="factory", how="outer",
                                 suffixes=("_d","_s")).fillna(0)
        _rev_combined["total"] = _rev_combined.get("total_d",0) + _rev_combined.get("total_s",0)
        rev_g  = _rev_combined[["factory","total"]]
        cost_g = (cost_all.groupby("factory")["amount"].sum().reset_index()
                  if not cost_all.empty else pd.DataFrame(columns=["factory","amount"]))
        base = pd.DataFrame({"factory": FACTORIES})
        rank = base.merge(rev_g,  on="factory", how="left") \
                   .merge(cost_g, on="factory", how="left").fillna(0)
        rank["profit"] = rank["total"] - rank["amount"]
        rank["margin"] = rank.apply(
            lambda r: f"{(r['profit']/r['total']*100):.1f}%" if r["total"] else "—", axis=1
        )
        rank = rank.sort_values("profit", ascending=False).reset_index(drop=True)
        rank.insert(0, "Rank", [str(i + 1) for i in range(len(rank))])
        disp = rank.copy()
        for col in ["total", "amount", "profit"]:
            disp[col] = disp[col].apply(fmt_inr)
        st.dataframe(
            disp.rename(columns={
                "factory":"Factory","total":"Revenue",
                "amount":"Costs","profit":"Profit","margin":"Margin"
            }),
            width='stretch', hide_index=True
        )
        if HAS_PLOTLY:
            fig3 = px.bar(rank, x="factory", y="profit", text="margin",
                          color="profit",
                          color_continuous_scale=["#B3261E","#D9D9D9","#1E6B45"],
                          template="plotly_white",
                          labels={"factory":"Factory","profit":"Net Profit (₹)"})
            fig3.update_layout(height=240, margin=dict(l=10,r=10,t=10,b=10),
                                showlegend=False, font_family="Inter",
                                plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(fig3, width='stretch')
        else:
            st.bar_chart(rank.set_index("factory")["profit"])
    else:
        st.info("Enter sales and cost data to see factory ranking.")


# ─────────────────────────────────────────────────────────────────────────────
#  MY FACTORY  (supervisor-only mini-dashboard)
# ─────────────────────────────────────────────────────────────────────────────
elif module == "My Factory":

    fac = _user_factory or factory   # always the supervisor's own factory
    today_str  = str(datetime.date.today())
    month_str  = datetime.date.today().strftime("%Y-%m")

    st.markdown(f"# 🏭 {fac} — Factory Overview")
    st.markdown(
        f"<p style='color:#8C7B62;font-size:13px;margin-top:-10px;'>"
        f"Logged in as <strong style='color:#1E3A5F'>{st.session_state.display_name}</strong>"
        f" &nbsp;|&nbsp; {datetime.date.today().strftime('%d %B %Y')}</p>",
        unsafe_allow_html=True,
    )

    # NEW: festival/holiday reminder + weather advisory for this factory —
    # the most actionable spot for it, since supervisors are the ones who'd
    # actually cover stock or reschedule outdoor work in response.
    render_festival_banner(compact=True)
    render_monsoon_banner(compact=True)
    render_weather_advisory(fac)

    # ── pull factory-specific data ────────────────────────────────────────
    mf_prod_today  = pd.read_sql_query(
        "SELECT * FROM production WHERE factory=? AND date=?",
        conn, params=(fac, today_str))
    mf_sales_today = pd.read_sql_query(
        "SELECT * FROM sales WHERE factory=? AND date=?",
        conn, params=(fac, today_str))
    mf_costs_today = pd.read_sql_query(
        "SELECT * FROM costs WHERE factory=? AND date=?",
        conn, params=(fac, today_str))

    mf_prod_month  = pd.read_sql_query(
        "SELECT * FROM production WHERE factory=? AND date LIKE ?",
        conn, params=(fac, f"{month_str}%"))
    mf_sales_month = pd.read_sql_query(
        "SELECT * FROM sales WHERE factory=? AND date LIKE ?",
        conn, params=(fac, f"{month_str}%"))
    mf_costs_month = pd.read_sql_query(
        "SELECT * FROM costs WHERE factory=? AND date LIKE ?",
        conn, params=(fac, f"{month_str}%"))

    mf_stock_cur = pd.read_sql_query(
        "SELECT material, closing_stock, date FROM stock s1 "
        "WHERE factory=? AND id=(SELECT MAX(id) FROM stock s2 "
        "WHERE s2.material=s1.material AND s2.factory=s1.factory) "
        "ORDER BY closing_stock ASC",
        conn, params=(fac,))

    mf_log_pending = pd.read_sql_query(
        "SELECT * FROM daily_log WHERE factory=? AND status IN ('Pending','In Progress') "
        "ORDER BY date DESC LIMIT 10",
        conn, params=(fac,))

    # ── TODAY snapshot ─────────────────────────────────────────────────────
    st.subheader("📅 Today's Snapshot")
    t1, t2, t3, t4 = st.columns(4)
    t1.metric(f"Production ({unit})",
              f"{from_mt(mf_prod_today['production'].sum()):,.2f}"
              if not mf_prod_today.empty else "—")
    # FIX: Revenue = Dispatch only; Sales Orders booked today shown via help text.
    _mf_so_today = pd.read_sql_query(
        "SELECT * FROM sales_orders WHERE factory=? AND date=?",
        conn, params=(fac, today_str))
    _mf_today_rev = mf_sales_today["total"].sum() if not mf_sales_today.empty else 0
    _mf_so_today_total = _mf_so_today["total"].sum() if not _mf_so_today.empty else 0
    t2.metric("Revenue (Today)",
              fmt_inr(_mf_today_rev) if _mf_today_rev else "—",
              help=f"Sales Orders booked today (not included): {fmt_inr(_mf_so_today_total)}")
    t3.metric("Costs",
              fmt_inr(mf_costs_today["amount"].sum())
              if not mf_costs_today.empty else "—")
    t4.metric("Log Entries (today)",
              len(pd.read_sql_query(
                  "SELECT id FROM daily_log WHERE factory=? AND date=?",
                  conn, params=(fac, today_str))))

    st.markdown("---")

    # ── THIS MONTH ─────────────────────────────────────────────────────────
    st.subheader(f"📆 This Month — {datetime.date.today().strftime('%B %Y')}")
    m1, m2, m3, m4 = st.columns(4)
    # FIX: Revenue = Dispatch only. Sales Orders booked this month are
    # shown as a separate order-book figure, not summed into Revenue.
    month_prod     = mf_prod_month["production"].sum()   if not mf_prod_month.empty  else 0
    _mf_disp_rev   = mf_sales_month["total"].sum()       if not mf_sales_month.empty else 0
    _mf_so_month   = pd.read_sql_query(
        "SELECT * FROM sales_orders WHERE factory=? AND date LIKE ?",
        conn, params=(fac, f"{month_str}%"))
    _mf_so_rev     = _mf_so_month["total"].sum() if not _mf_so_month.empty else 0
    month_rev      = _mf_disp_rev               # Dispatch = recognised revenue
    month_cost  = mf_costs_month["amount"].sum()      if not mf_costs_month.empty else 0
    month_profit= month_rev - month_cost
    m1.metric(f"Production ({unit})", f"{from_mt(month_prod):,.2f}")
    m2.metric("Revenue",   fmt_inr(month_rev),
              help=f"Sales Orders booked this month (not included): {fmt_inr(_mf_so_rev)}")
    m3.metric("Costs",     fmt_inr(month_cost))
    m4.metric("Net Result",fmt_inr(month_profit),
              delta=("Profit" if month_profit >= 0 else "Loss"))

    # monthly production bar
    if not mf_prod_month.empty and HAS_PLOTLY:
        daily_prod = (mf_prod_month.groupby("date")["production"]
                                   .sum().reset_index().sort_values("date"))
        daily_prod["display"] = daily_prod["production"].apply(from_mt)
        fig_mp = px.bar(daily_prod, x="date", y="display",
                        color_discrete_sequence=["#6E1423"],
                        template="plotly_white",
                        title=f"Daily Production — {fac}",
                        labels={"date":"Date","display":f"Production ({unit})"})
        fig_mp.update_layout(height=220, margin=dict(l=10,r=10,t=36,b=10))
        st.plotly_chart(fig_mp, width='stretch')

    st.markdown("---")

    # ── STOCK ALERTS ───────────────────────────────────────────────────────
    st.subheader("📦 Stock Status")
    if mf_stock_cur.empty:
        st.info("No stock records for this factory yet.")
    else:
        critical = mf_stock_cur[mf_stock_cur["closing_stock"] < 20]
        low      = mf_stock_cur[(mf_stock_cur["closing_stock"] >= 20) &
                                 (mf_stock_cur["closing_stock"] < 50)]
        if not critical.empty:
            for _, row in critical.iterrows():
                st.error(f"🔴 CRITICAL — {row['material']}: only {int(row['closing_stock'])} units left")
        if not low.empty:
            for _, row in low.iterrows():
                st.warning(f"🟡 LOW — {row['material']}: {int(row['closing_stock'])} units")
        if critical.empty and low.empty:
            st.success("✅ All materials at healthy stock levels")

        # mini stock bar chart
        if HAS_PLOTLY:
            max_s = int(mf_stock_cur["closing_stock"].max()) or 1
            for _, row in mf_stock_cur.iterrows():
                color = ("#6E1423" if row["closing_stock"] < 20 else
                         "#A8791E" if row["closing_stock"] < 50 else "#145C3C")
                progress_bar(row["material"], row["closing_stock"], max_s, color=color)

    st.markdown("---")

    # ── PENDING ACTIVITIES ─────────────────────────────────────────────────
    st.subheader("📋 Open / Pending Activities")
    if mf_log_pending.empty:
        st.success("✅ No pending or in-progress activities.")
    else:
        st.dataframe(
            mf_log_pending[["date","category","activity","personnel","status","notes"]]
            .rename(columns={
                "date":"Date","category":"Category","activity":"Activity",
                "personnel":"Personnel","status":"Status","notes":"Notes"
            }),
            width='stretch', hide_index=True, height=280
        )

    st.markdown("---")

    # ── RECENT PRODUCTION (last 10) ────────────────────────────────────────
    st.subheader("⚙️ Recent Production Entries")
    mf_prod_recent = pd.read_sql_query(
        "SELECT date, product, labour, hours, production, efficiency "
        "FROM production WHERE factory=? ORDER BY id DESC LIMIT 10",
        conn, params=(fac,))
    if mf_prod_recent.empty:
        st.info("No production records yet.")
    else:
        mf_prod_recent["production"] = mf_prod_recent["production"].apply(
            lambda x: round(from_mt(x), 3))
        mf_prod_recent = mf_prod_recent.rename(columns={
            "production": f"Qty ({unit})", "efficiency": "Efficiency"})
        st.dataframe(mf_prod_recent, width='stretch', hide_index=True, height=240)


# ─────────────────────────────────────────────────────────────────────────────
#  DAILY LOG
# ─────────────────────────────────────────────────────────────────────────────
elif module == "Daily Log":

    st.title("📋 Daily Activity Log")
    tab_add, tab_view, tab_edit = st.tabs(["➕ Add Entry", "📋 View Log", "✏️ Edit Record"])

    with tab_add:
        st.subheader("New Log Entry")
        c1, c2, c3 = st.columns(3)
        with c1:
            dl_date    = st.date_input("Date", key="dl_d")
            dl_factory = st.selectbox("Factory", FACTORIES, key="dl_f",
                                       index=FACTORIES.index(factory) if factory in FACTORIES else 0)
            dl_cat     = st.selectbox("Category", LOG_CATEGORIES, key="dl_cat")
        with c2:
            dl_activity = st.text_input("Activity Description",
                                         placeholder="What was done today?", key="dl_act")
            dl_person   = st.text_input("Personnel / Team", key="dl_per")
        with c3:
            dl_status = st.selectbox("Status", LOG_STATUSES, key="dl_stat")
            dl_notes  = st.text_input("Notes (optional)", key="dl_notes")

        if st.button("💾 Save Log Entry"):
            if not dl_activity.strip():
                st.warning("Activity description is required.")
            else:
                # Duplicate guard: same date + factory + category + activity
                dup = pd.read_sql_query(
                    "SELECT id FROM daily_log WHERE date=? AND factory=? AND category=? AND activity=?",
                    conn, params=(str(dl_date), dl_factory, dl_cat, dl_activity.strip())
                )
                if not dup.empty:
                    st.warning(
                        f"⚠️ A **{dl_cat}** log entry with this activity description "
                        f"already exists for **{dl_factory}** on **{dl_date}**. "
                        f"Use the ✏️ Edit tab to update it."
                    )
                else:
                    try:
                        cur.execute(
                            "INSERT INTO daily_log VALUES (NULL,?,?,?,?,?,?,?)",
                            (str(dl_date), dl_factory, dl_cat,
                             dl_activity, dl_person, dl_status, dl_notes)
                        )
                        conn.commit()
                        log_audit("INSERT", "daily_log", "new",
                                  f"{dl_factory} | {dl_cat} | {dl_activity}")
                        st.success(f"✅ Log saved — [{dl_cat}] {dl_activity}")
                        st.rerun()
                    except sqlite3.Error as e:
                        st.error(f"Database error: {e}")

    with tab_view:
        st.subheader("Activity Log")
        if log_df.empty:
            st.info("No log entries for this factory / date range.")
        else:
            lk1, lk2, lk3, lk4 = st.columns(4)
            lk1.metric("Total Entries",   len(log_df))
            lk2.metric("Completed",
                        len(log_df[log_df["status"] == "Completed"]))
            lk3.metric("In Progress",
                        len(log_df[log_df["status"] == "In Progress"]))
            lk4.metric("Pending",
                        len(log_df[log_df["status"] == "Pending"]))

            if HAS_PLOTLY:
                cat_counts = log_df["category"].value_counts().reset_index()
                cat_counts.columns = ["Category", "Count"]
                fig_log = px.bar(cat_counts, x="Category", y="Count",
                                  color_discrete_sequence=["#1C120D"],
                                  template="plotly_white",
                                  title="Entries by Category")
                fig_log.update_layout(height=220,
                                       margin=dict(l=10,r=10,t=36,b=10))
                st.plotly_chart(fig_log, width='stretch')

            filtered_log = search_filter(log_df, "Search logs", key="log_search")
            filtered_log = paginate_df(filtered_log, key="log_page")
            st.dataframe(
                filtered_log.drop(columns=["id"], errors="ignore"),
                width='stretch', hide_index=True, height=300
            )
            delete_row_ui(log_df, "daily_log", "activity", "log")

    with tab_edit:
        st.subheader("Edit a Log Entry")
        if log_df.empty:
            st.info("No records to edit in the current date range.")
        else:
            opts = {
                f"ID {r['id']} — {r['activity']} ({r['date']})": r["id"]
                for _, r in log_df.iterrows()
            }
            sel_label = st.selectbox("Select record to edit", list(opts.keys()),
                                      key="log_edit_sel")
            sel_id  = opts[sel_label]
            sel_row = log_df[log_df["id"] == sel_id].iloc[0]

            ec1, ec2, ec3 = st.columns(3)
            with ec1:
                e_dl_date    = st.date_input("Date",
                    value=pd.to_datetime(sel_row["date"]).date(), key="e_dl_d")
                e_dl_factory = st.selectbox("Factory", FACTORIES, key="e_dl_f",
                    index=FACTORIES.index(sel_row["factory"])
                          if sel_row["factory"] in FACTORIES else 0,
                    disabled=not _is_admin)
                e_dl_cat = st.selectbox("Category", LOG_CATEGORIES, key="e_dl_cat",
                    index=LOG_CATEGORIES.index(sel_row["category"])
                          if sel_row["category"] in LOG_CATEGORIES else 0)
            with ec2:
                e_dl_activity = st.text_input("Activity Description",
                    value=sel_row["activity"], key="e_dl_act")
                e_dl_person   = st.text_input("Personnel / Team",
                    value=sel_row["personnel"], key="e_dl_per")
            with ec3:
                e_dl_status = st.selectbox("Status", LOG_STATUSES, key="e_dl_stat",
                    index=LOG_STATUSES.index(sel_row["status"])
                          if sel_row["status"] in LOG_STATUSES else 0)
                e_dl_notes  = st.text_input("Notes", value=sel_row["notes"] or "",
                    key="e_dl_notes")

            if st.button("💾 Update Log Entry", key="log_upd_btn"):
                if not e_dl_activity.strip():
                    st.warning("Activity description is required.")
                else:
                    try:
                        cur.execute(
                            "UPDATE daily_log SET date=?,factory=?,category=?,"
                            "activity=?,personnel=?,status=?,notes=? WHERE id=?",
                            (str(e_dl_date), e_dl_factory, e_dl_cat,
                             e_dl_activity, e_dl_person, e_dl_status,
                             e_dl_notes, sel_id)
                        )
                        conn.commit()
                        log_audit("UPDATE", "daily_log", sel_id,
                                  f"{e_dl_factory} | {e_dl_cat} | {e_dl_activity}")
                        st.success("✅ Log entry updated.")
                        st.rerun()
                    except sqlite3.Error as e:
                        st.error(f"Database error: {e}")


# ─────────────────────────────────────────────────────────────────────────────
#  PRODUCTION
# ─────────────────────────────────────────────────────────────────────────────
elif module == "Production":

    st.title("⚙️ Production")
    _prod_tab_labels = ["➕ Log Production", "📋 Records", "✏️ Edit Record"]
    if _is_admin:
        _prod_tab_labels.append("⚙️ FG Stock Unit Settings")
    _prod_tabs = st.tabs(_prod_tab_labels)
    tab_entry, tab_log, tab_edit_p = _prod_tabs[0], _prod_tabs[1], _prod_tabs[2]
    tab_fg_units = _prod_tabs[3] if _is_admin else None

    with tab_entry:
        st.subheader("New Production Entry")
        c1, c2, c3 = st.columns(3)
        with c1:
            pr_date    = st.date_input("Date", key="pr_d")
            pr_factory = st.selectbox("Factory", FACTORIES, key="pr_f",
                                       index=FACTORIES.index(factory) if factory in FACTORIES else 0)
            pr_product = st.selectbox("Product", FCSC_PRODUCTS, key="pr_p", format_func=fg_label)
            pr_custom  = st.text_input("Custom name (if 'Other / Custom')", key="pr_cust")
        with c2:
            pr_labour  = st.number_input("Labour (workers)", min_value=0, step=1, key="pr_l")
            pr_hours   = st.number_input("Hours worked", min_value=0.0, step=0.5, key="pr_h")
        with c3:
            pr_display = st.number_input(f"Production ({unit})", min_value=0.0, step=0.1, key="pr_v")
            pr_mt      = to_mt(pr_display)
            pr_eff     = pr_mt / (pr_labour * pr_hours) if (pr_labour and pr_hours) else 0.0
            st.metric("Efficiency Preview", f"{pr_eff:.4f} u/l·h")

            pr_target = st.number_input(f"Daily Target ({unit})", min_value=0.0,
                                         step=0.1, key="pr_target", value=0.0)
            if pr_target > 0:
                pct = min(int(pr_display / pr_target * 100), 100)
                progress_bar("Target achievement", pr_display, pr_target,
                             color="#145C3C" if pct >= 80 else "#A8791E" if pct >= 50 else "#6E1423")

        if st.button("💾 Save Production"):
            final_product = pr_custom.strip() if pr_product == "Other / Custom" and pr_custom.strip() else pr_product
            if not final_product or final_product == "Other / Custom":
                st.warning("Please enter a product name.")
            elif not pr_labour or not pr_hours:
                st.warning("Labour and hours are required to calculate efficiency.")
            else:
                # Duplicate guard: same date + factory + product
                dup = pd.read_sql_query(
                    "SELECT id FROM production WHERE date=? AND factory=? AND product=?",
                    conn, params=(str(pr_date), pr_factory, final_product)
                )
                if not dup.empty:
                    st.warning(
                        f"⚠️ A production entry for **{final_product}** at **{pr_factory}** "
                        f"on **{pr_date}** already exists. Use the ✏️ Edit tab to modify it, "
                        f"or change the date / product to save a new record."
                    )
                else:
                    try:
                        cur.execute(
                            "INSERT INTO production (date,factory,product,labour,hours,"
                            "production,efficiency) VALUES (?,?,?,?,?,?,?)",
                            (str(pr_date), pr_factory, final_product,
                             pr_labour, pr_hours, pr_mt, round(pr_eff, 4))
                        )
                        conn.commit()
                        _new_prod_id = cur.lastrowid
                        log_audit("INSERT", "production", "new",
                                  f"{pr_factory} | {final_product} | {pr_display} {unit}")
                        # Production -> FG Stock IN (Section 3). Converted into the
                        # product's canonical FG stock unit (Section 6) — Production
                        # is entered in a weight unit, Dispatch's "Qty" is a packed-unit
                        # count, and the two must never be mixed unconverted.
                        _fg_qty, _fg_exact, _fg_note = convert_production_qty_to_fg_unit(
                            pr_display, final_product)
                        _fg_unit = get_fg_stock_unit_cfg(final_product)["stock_unit"]
                        _new_fg_closing = record_fg_stock_movement(
                            pr_date, pr_factory, final_product,
                            production_in=_fg_qty, source_module="Production",
                            source_ref_id=_new_prod_id
                        )
                        st.success(f"✅ Saved — {pr_display:,.2f} {unit} of {final_product} | "
                                   f"Efficiency: {pr_eff:.4f} | FG Stock ({_fg_unit}) now "
                                   f"{_new_fg_closing:,.2f}")
                        if not _fg_exact:
                            st.warning(f"⚠️ {_fg_note}")
                        st.rerun()
                    except sqlite3.Error as e:
                        st.error(f"Database error: {e}")

    with tab_log:
        st.subheader("Production Records")
        if prod_df.empty:
            st.info("No records for this factory / date range.")
        else:
            disp = prod_df.copy()
            disp["production"] = disp["production"].apply(lambda x: round(from_mt(x), 3))
            disp.insert(disp.columns.get_loc("product") + 1, "rm_code", disp["product"].apply(get_fg_code))
            disp = disp.rename(columns={"production": f"Production ({unit})",
                                         "efficiency": "Efficiency", "rm_code": "RM Code"})

            disp = search_filter(disp, "Search production records", key="prod_search")
            disp = paginate_df(disp, key="prod_page")

            st.dataframe(disp.drop(columns=["id"], errors="ignore"),
                         width='stretch', hide_index=True, height=320)

            def _on_production_deleted(_row) -> None:
                # Section 7: deleting a Production record must not leave an
                # orphaned FG stock movement behind.
                _closing = reverse_fg_stock_for_source(
                    _row["factory"], _row["product"], "Production", int(_row["id"]))
                if _closing is not None:
                    log_audit("REVERSE", "fg_stock", int(_row["id"]),
                              f"Production #{int(_row['id'])} deleted — FG stock movement "
                              f"reversed | {_row['factory']} | {_row['product']} | "
                              f"FG stock now {_closing:,.2f}")

            delete_row_ui(prod_df, "production", "product", "prod",
                           on_delete=_on_production_deleted)

            st.markdown("---")
            st.subheader("Quick Summary")
            tot = prod_df["production"].sum()
            avg = prod_df["efficiency"].mean()
            sc1, sc2, sc3 = st.columns(3)
            sc1.metric(f"Total ({unit})", f"{from_mt(tot):,.2f}")
            sc2.metric("Avg Efficiency",  f"{avg:.4f}")
            sc3.metric("Records",         len(prod_df))

            if HAS_PLOTLY:
                by_prod = (prod_df.groupby("product")["production"]
                           .sum().reset_index().sort_values("production", ascending=False))
                by_prod["display"] = by_prod["production"].apply(from_mt)
                fig = px.bar(by_prod, x="product", y="display",
                             labels={"product":"Product","display":unit},
                             color_discrete_sequence=["#6E1423"],
                             template="plotly_white", title="Units by Product")
                fig.update_layout(height=240, margin=dict(l=10,r=10,t=36,b=10))
                st.plotly_chart(fig, width='stretch')
            else:
                by_prod = prod_df.groupby("product")["production"].sum()
                st.bar_chart(by_prod.apply(from_mt))

    with tab_edit_p:
        st.subheader("Edit a Production Record")
        if prod_df.empty:
            st.info("No records to edit in the current date range.")
        else:
            opts = {
                f"ID {r['id']} — {fg_label(r['product'])} ({r['date']})": r["id"]
                for _, r in prod_df.iterrows()
            }
            sel_label = st.selectbox("Select record to edit", list(opts.keys()),
                                      key="prod_edit_sel")
            sel_id  = opts[sel_label]
            sel_row = prod_df[prod_df["id"] == sel_id].iloc[0]

            pc1, pc2, pc3 = st.columns(3)
            with pc1:
                e_pr_date    = st.date_input("Date",
                    value=pd.to_datetime(sel_row["date"]).date(), key="e_pr_d")
                e_pr_factory = st.selectbox("Factory", FACTORIES, key="e_pr_f",
                    index=FACTORIES.index(sel_row["factory"])
                          if sel_row["factory"] in FACTORIES else 0,
                    disabled=not _is_admin)
                cur_prod_idx = FCSC_PRODUCTS.index(sel_row["product"]) \
                               if sel_row["product"] in FCSC_PRODUCTS else len(FCSC_PRODUCTS) - 1
                e_pr_product = st.selectbox("Product", FCSC_PRODUCTS, key="e_pr_p",
                    index=cur_prod_idx, format_func=fg_label)
                e_pr_custom  = st.text_input("Custom name (if Other / Custom)",
                    value=sel_row["product"] if sel_row["product"] not in FCSC_PRODUCTS else "",
                    key="e_pr_cust")
            with pc2:
                e_pr_labour = st.number_input("Labour (workers)",
                    min_value=0, step=1, value=int(sel_row["labour"]), key="e_pr_l")
                e_pr_hours  = st.number_input("Hours worked",
                    min_value=0.0, step=0.5, value=float(sel_row["hours"]), key="e_pr_h")
            with pc3:
                cur_display  = round(from_mt(sel_row["production"]), 3)
                e_pr_display = st.number_input(f"Production ({unit})",
                    min_value=0.0, step=0.1, value=cur_display, key="e_pr_v")
                e_pr_mt  = to_mt(e_pr_display)
                e_pr_eff = e_pr_mt / (e_pr_labour * e_pr_hours) \
                           if (e_pr_labour and e_pr_hours) else 0.0
                st.metric("New Efficiency", f"{e_pr_eff:.4f} u/l·h")

            if st.button("💾 Update Production", key="prod_upd_btn"):
                final_p = e_pr_custom.strip() \
                          if e_pr_product == "Other / Custom" and e_pr_custom.strip() \
                          else e_pr_product
                if not final_p or final_p == "Other / Custom":
                    st.warning("Please enter a product name.")
                elif not e_pr_labour or not e_pr_hours:
                    st.warning("Labour and hours are required.")
                else:
                    try:
                        cur.execute(
                            "UPDATE production SET date=?,factory=?,product=?,"
                            "labour=?,hours=?,production=?,efficiency=? WHERE id=?",
                            (str(e_pr_date), e_pr_factory, final_p,
                             e_pr_labour, e_pr_hours, e_pr_mt, round(e_pr_eff, 4), sel_id)
                        )
                        conn.commit()
                        log_audit("UPDATE", "production", sel_id,
                                  f"{e_pr_factory} | {final_p} | {e_pr_display} {unit}")
                        # Section 7: an edit must correct FG Stock too, not just the
                        # production row — reverse the old movement (posted under the
                        # *old* factory/product, in case those changed) then apply the
                        # new one, so the final FG impact reflects only the new value.
                        reverse_fg_stock_for_source(
                            sel_row["factory"], sel_row["product"], "Production", int(sel_id))
                        _e_fg_qty, _e_fg_exact, _e_fg_note = convert_production_qty_to_fg_unit(
                            e_pr_display, final_p)
                        _e_fg_unit = get_fg_stock_unit_cfg(final_p)["stock_unit"]
                        _e_fg_closing = record_fg_stock_movement(
                            e_pr_date, e_pr_factory, final_p,
                            production_in=_e_fg_qty, source_module="Production",
                            source_ref_id=int(sel_id), movement_type="Correction"
                        )
                        st.success(f"✅ Production record updated — FG Stock ({_e_fg_unit}) "
                                   f"for {final_p} @ {e_pr_factory} now {_e_fg_closing:,.2f}.")
                        if not _e_fg_exact:
                            st.warning(f"⚠️ {_e_fg_note}")
                        st.rerun()
                    except sqlite3.Error as e:
                        st.error(f"Database error: {e}")


    if tab_fg_units is not None:
        with tab_fg_units:
            st.subheader("FG Stock Unit Settings")
            st.caption(
                "Section 6 fix: Production is logged as a weight (MT/KG); Dispatch's "
                "\"Qty\" field is a packed-unit count that's already the de-facto FG "
                "stock unit. To combine them safely in one ledger, set each product's "
                "canonical stock unit and, for packed-unit products, the pack weight — "
                "Production entries are converted into that unit before they hit FG Stock. "
                "Left unconfigured, a product defaults to **Bags** with no conversion, "
                "which is flagged on every Production save until it's set here."
            )
            _fgu_rows = []
            for _p in FCSC_PRODUCTS:
                if _p == "Other / Custom":
                    continue
                _cfg = get_fg_stock_unit_cfg(_p)
                _fgu_rows.append({"Product": _p, "Stock Unit": _cfg["stock_unit"],
                                   "Pack Weight (KG)": _cfg["pack_weight_kg"]})
            st.dataframe(pd.DataFrame(_fgu_rows), width='stretch', hide_index=True, height=280)

            st.markdown("---")
            st.subheader("Set / Update a Product's FG Stock Unit")
            fu1, fu2, fu3 = st.columns(3)
            with fu1:
                fu_product = st.selectbox("Product", [p for p in FCSC_PRODUCTS
                                                       if p != "Other / Custom"], key="fu_product")
            with fu2:
                fu_unit = st.selectbox("Stock Unit", ["Bags", "Pieces", "Drums", "KG", "MT"],
                                        key="fu_unit")
            with fu3:
                fu_pack_kg = st.number_input(
                    "Pack Weight (KG per unit)", min_value=0.0, step=0.5, value=0.0,
                    key="fu_pack_kg",
                    help="Required for packed-unit stock (Bags/Pieces/Drums) so Production's "
                         "weight can be converted. Not needed if the stock unit is KG or MT."
                )
            if st.button("💾 Save FG Stock Unit", key="fu_save"):
                set_fg_stock_unit_cfg(
                    fu_product, fu_unit, fu_pack_kg if fu_pack_kg > 0 else None,
                    st.session_state.get("username", "")
                )
                log_audit("UPDATE", "fg_product_unit", fu_product,
                          f"stock_unit={fu_unit} | pack_weight_kg={fu_pack_kg or '—'}")
                st.success(f"✅ {fu_product} → {fu_unit}"
                          + (f" (pack weight {fu_pack_kg:g} KG)" if fu_pack_kg > 0 else ""))
                st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
#  SAND
# ─────────────────────────────────────────────────────────────────────────────
elif module == "Formulation":

    st.title("📐 Formulation / Bill of Materials")
    st.markdown(
        "<p style='color:#8C7B62;font-size:13px;margin-top:-10px;'>"
        "Standard formulas per product — used to calculate raw material needs for a "
        "planned production run, and as a reference when creating a production batch. "
        "This is the plan; the batch's own material record stays the source of truth "
        "for what was actually used.</p>",
        unsafe_allow_html=True,
    )

    _fm_tab_labels = ["📐 Requirement Calculator", "📋 Active Formulations"]
    if _is_admin:
        _fm_tab_labels.append("✏️ Manage Formulas")
    _fm_tabs = st.tabs(_fm_tab_labels)
    tab_fm_calc, tab_fm_view = _fm_tabs[0], _fm_tabs[1]
    tab_fm_manage = _fm_tabs[2] if _is_admin else None

    # ── REQUIREMENT CALCULATOR ──────────────────────────────────────────────
    with tab_fm_calc:
        st.subheader("Material Requirement Calculator")
        fc1, fc2, fc3 = st.columns(3)
        with fc1:
            fm_calc_product = st.selectbox("Product", FCSC_PRODUCTS, key="fm_calc_product", format_func=fg_label)
        with fc2:
            fm_calc_qty = st.number_input("Planned Production Qty", min_value=0.0, step=1.0,
                                           value=100.0, key="fm_calc_qty")
        with fc3:
            fm_calc_fac_opts = ["All Factories"] + FACTORIES
            fm_calc_factory = st.selectbox("Check stock at", fm_calc_fac_opts, key="fm_calc_factory")

        _fm_bom = get_active_bom(fm_calc_product)
        if _fm_bom is None:
            st.info(f"No active formula on file for **{fm_calc_product}** yet." +
                     (" Add one in ✏️ Manage Formulas." if _is_admin else ""))
        else:
            st.caption(f"Using formula **{_fm_bom['version']}** "
                        f"({_fm_bom['formula_code'] or 'no code'}) — reference batch: "
                        f"{_fm_bom['batch_size']:g} {_fm_bom['batch_unit']}")
            _fm_fac = None if fm_calc_factory == "All Factories" else fm_calc_factory
            fm_req_df = calculate_material_requirement(fm_calc_product, fm_calc_qty, _fm_fac)
            if fm_req_df.empty:
                st.info("This formula doesn't have any material lines yet.")
            else:
                _fm_short = fm_req_df[fm_req_df["shortage"] > 0]
                rm1, rm2 = st.columns(2)
                rm1.metric("Materials Needed", len(fm_req_df))
                rm2.metric("Short on Stock", len(_fm_short))
                if not _fm_short.empty:
                    st.warning(f"⚠️ {len(_fm_short)} material(s) don't have enough stock "
                                f"for this run at the selected scope.")
                st.dataframe(
                    fm_req_df.rename(columns={
                        "material": "Material", "unit": "Unit", "required_qty": "Required",
                        "available_qty": "Available", "shortage": "Shortage"
                    }),
                    width='stretch', hide_index=True
                )

                _fm_cost = bom_standard_cost(fm_calc_product)
                if _fm_cost:
                    _scaled_cost = _fm_cost * fm_calc_qty / _fm_bom["batch_size"] if _fm_bom["batch_size"] else 0
                    cst1, cst2 = st.columns(2)
                    cst1.metric("Standard Cost / Reference Batch", fmt_inr(_fm_cost))
                    cst2.metric("Estimated Cost for This Run", fmt_inr(_scaled_cost))
                    st.caption("Only materials with a unit cost on file (Manage Formulas → "
                                "Material Unit Costs) are included — this is a partial estimate "
                                "until all materials have a cost set.")

                if not _fm_short.empty and st.button(
                        "🛒 Raise procurement requests for shortages", key="fm_raise_proc"):
                    _fm_target_factory = _fm_fac or (factory if factory != ALL_FACTORIES else FACTORIES[0])
                    _fm_raised = []
                    for _, _row in _fm_short.iterrows():
                        _rid = _open_procurement_request(
                            _row["material"], _fm_target_factory, "manual", _row["shortage"],
                            _row["unit"],
                            f"Shortage identified via Formulation calculator for "
                            f"{fm_calc_product} (planned qty {fm_calc_qty:g})"
                        )
                        _fm_raised.append(_rid)
                    st.success(f"✅ Raised {len(_fm_raised)} procurement request(s): "
                                + ", ".join(f"PR-{r:05d}" for r in _fm_raised))
                    st.rerun()

    # ── ACTIVE FORMULATIONS (read-only view) ────────────────────────────────
    with tab_fm_view:
        st.subheader("Active Formulations")
        _fm_all_active = pd.read_sql_query(
            "SELECT * FROM bom_headers WHERE is_active=1 ORDER BY product", conn)
        if _fm_all_active.empty:
            st.info("No formulations saved yet.")
        else:
            _fm_search = search_filter(_fm_all_active, "Search products", key="fm_view_search")
            for _, _b in _fm_search.iterrows():
                with st.expander(f"{fg_label(_b['product'])} — {_b['version']} "
                                   f"({_b['formula_code'] or 'no code'})"):
                    st.caption(f"Reference batch: {_b['batch_size']:g} {_b['batch_unit']}"
                                + (f" · {_b['notes']}" if _b['notes'] else ""))
                    _fm_lines = get_bom_lines(_b["id"])
                    if _fm_lines.empty:
                        st.caption("No material lines.")
                    else:
                        st.dataframe(
                            _fm_lines[["material", "qty_per_batch", "unit", "notes"]]
                                .rename(columns={"material": "Material", "qty_per_batch": "Qty/Batch",
                                                  "unit": "Unit", "notes": "Notes"}),
                            width='stretch', hide_index=True
                        )
                    _fm_view_cost = bom_standard_cost(_b["product"])
                    if _fm_view_cost:
                        st.metric("Standard Cost / Batch", fmt_inr(_fm_view_cost))

    # ── MANAGE FORMULAS (admin only) ────────────────────────────────────────
    if tab_fm_manage is not None:
        with tab_fm_manage:
            st.subheader("✏️ Create / Update a Formulation")
            st.caption("Saving a new version becomes the active formula for that product "
                        "immediately — the previous version is kept, not deleted, so old "
                        "batches still trace back to whichever formula was active then.")

            mb1, mb2, mb3 = st.columns(3)
            with mb1:
                mb_product = st.selectbox("Product", FCSC_PRODUCTS, key="fm_mgmt_product", format_func=fg_label)
                _fm_existing = get_active_bom(mb_product)
                if _fm_existing:
                    st.caption(f"Current active version: **{_fm_existing['version']}**")
            with mb2:
                mb_version = st.text_input("Version Label", value="v1", key="fm_mgmt_version")
                mb_code    = st.text_input("Formula Code", key="fm_mgmt_code",
                                            placeholder="e.g. TG3.0-STD")
            with mb3:
                mb_batch_size = st.number_input("Reference Batch Size", min_value=0.01,
                                                  value=100.0, step=1.0, key="fm_mgmt_size")
                mb_batch_unit = st.selectbox("Batch Unit", ["KG", "MT", "Litres", "Bags"],
                                               key="fm_mgmt_unit")
            mb_notes = st.text_area("Notes", key="fm_mgmt_notes")

            st.markdown("#### Material Lines")
            if "fm_line_count" not in st.session_state:
                st.session_state.fm_line_count = 3
            bl1, bl2 = st.columns([1, 5])
            with bl1:
                if st.button("➕ Add Line", key="fm_add_line"):
                    st.session_state.fm_line_count += 1
                    st.rerun()

            fm_lines_input = []
            for _i in range(st.session_state.fm_line_count):
                lc1, lc2, lc3, lc4 = st.columns([3, 1.5, 1, 2])
                _show_labels = (_i == 0)
                with lc1:
                    _m = st.selectbox("Material", MATERIALS, key=f"fm_line_mat_{_i}",
                                       format_func=material_label,
                                       label_visibility="visible" if _show_labels else "collapsed")
                with lc2:
                    _q = st.number_input("Qty/Batch", min_value=0.0, step=0.1, key=f"fm_line_qty_{_i}",
                                          label_visibility="visible" if _show_labels else "collapsed")
                with lc3:
                    _u = st.selectbox("Unit", ["KG", "Litres", "MT", "Bags", "Units"],
                                       key=f"fm_line_unit_{_i}",
                                       label_visibility="visible" if _show_labels else "collapsed")
                with lc4:
                    _n = st.text_input("Notes", key=f"fm_line_notes_{_i}",
                                        label_visibility="visible" if _show_labels else "collapsed")
                if _q > 0:
                    fm_lines_input.append({"material": _m, "qty_per_batch": _q, "unit": _u, "notes": _n})

            if st.button("💾 Save Formulation", key="fm_save"):
                ok, msg, bom_id = create_bom(mb_product, mb_version, mb_code, mb_batch_size,
                                               mb_batch_unit, mb_notes, fm_lines_input)
                if ok:
                    _activate_bom(bom_id, mb_product)
                    st.success(f"✅ {msg} Set as the active formula for {mb_product}.")
                    st.session_state.fm_line_count = 3
                    st.rerun()
                else:
                    st.error(msg)

            st.markdown("---")
            st.markdown("#### Version History")
            _fm_hist = pd.read_sql_query(
                "SELECT id, version, formula_code, is_active, created_at, created_by "
                "FROM bom_headers WHERE product=? ORDER BY id DESC",
                conn, params=(mb_product,)
            )
            if _fm_hist.empty:
                st.caption("No versions saved yet for this product.")
            else:
                _fm_hist_disp = _fm_hist.copy()
                _fm_hist_disp["is_active"] = _fm_hist_disp["is_active"].apply(
                    lambda x: "🟢 Active" if x else "")
                st.dataframe(
                    _fm_hist_disp.rename(columns={
                        "id": "ID", "version": "Version", "formula_code": "Code",
                        "is_active": "Status", "created_at": "Created", "created_by": "By"
                    }),
                    width='stretch', hide_index=True
                )
                _fm_reactivate_opts = _fm_hist[_fm_hist["is_active"] == 0]["id"].tolist()
                if _fm_reactivate_opts:
                    _fm_re_id = st.selectbox("Re-activate an older version", _fm_reactivate_opts,
                                              key="fm_reactivate")
                    if st.button("↩️ Make this version active", key="fm_reactivate_btn"):
                        _activate_bom(int(_fm_re_id), mb_product)
                        log_audit("UPDATE", "bom_headers", _fm_re_id, f"Re-activated for {mb_product}")
                        st.success("Version re-activated.")
                        st.rerun()

            st.markdown("---")
            st.markdown("#### Material Unit Costs")
            st.caption("Optional — set a ₹/unit cost per material to see standard batch costs above.")
            uc1, uc2, uc3 = st.columns([2, 1, 1])
            with uc1:
                uc_material = st.selectbox("Material", MATERIALS, key="fm_uc_material", format_func=material_label)
            with uc2:
                _uc_row = cur.execute("SELECT unit_cost FROM material_codes WHERE material=?",
                                       (uc_material,)).fetchone()
                _uc_current = _uc_row[0] if _uc_row and _uc_row[0] else 0.0
                uc_cost = st.number_input("Unit Cost (₹)", min_value=0.0, step=0.5,
                                           value=float(_uc_current), key="fm_uc_cost")
            with uc3:
                st.write("")
                st.write("")
                if st.button("💾 Save Cost", key="fm_uc_save", width='stretch'):
                    cur.execute(
                        "INSERT INTO material_codes(material,code,unit_cost) VALUES (?,?,?) "
                        "ON CONFLICT(material) DO UPDATE SET unit_cost=excluded.unit_cost",
                        (uc_material, get_material_code(uc_material), uc_cost)
                    )
                    conn.commit()
                    log_audit("UPDATE", "material_codes", uc_material, f"unit_cost={uc_cost}")
                    st.success(f"✅ {uc_material} → ₹{uc_cost}/unit")
                    st.rerun()


elif module == "Sand":

    st.title("🏗️ Sand Usage")
    tab_entry, tab_log, tab_edit_s = st.tabs(["➕ Log Sand", "📋 Records", "✏️ Edit Record"])

    with tab_entry:
        st.subheader("New Sand Entry")
        c1, c2 = st.columns(2)
        with c1:
            s_date    = st.date_input("Date", key="s_d")
            s_factory = st.selectbox("Factory", FACTORIES, key="s_f",
                                      index=FACTORIES.index(factory) if factory in FACTORIES else 0)
        with c2:
            s_qty  = st.number_input("Quantity", min_value=0, step=1, key="s_q")
            s_unit = st.selectbox("Unit", SAND_UNITS, key="s_unit")
            s_type = st.selectbox("Sand Type", SAND_TYPES, key="s_t")

        if st.button("💾 Save Sand"):
            if not s_qty:
                st.warning("Please enter a quantity greater than 0.")
            else:
                # Duplicate guard: same date + factory + sand_type
                dup = pd.read_sql_query(
                    "SELECT id FROM sand WHERE date=? AND factory=? AND sand_type=?",
                    conn, params=(str(s_date), s_factory, s_type)
                )
                if not dup.empty:
                    st.warning(
                        f"⚠️ A **{s_type}** sand entry for **{s_factory}** on **{s_date}** "
                        f"already exists. Use the ✏️ Edit tab to modify it."
                    )
                else:
                    try:
                        cur.execute(
                            "INSERT INTO sand(date,factory,qty,sand_type,unit) VALUES (?,?,?,?,?)",
                            (str(s_date), s_factory, s_qty, s_type, s_unit)
                        )
                        conn.commit()
                        log_audit("INSERT", "sand", "new",
                                  f"{s_factory} | {s_type} | {s_qty} {s_unit}")
                        st.success(f"✅ Saved — {s_qty:,} {s_unit} of {s_type} at {s_factory}")
                        st.rerun()
                    except sqlite3.Error as e:
                        st.error(f"Database error: {e}")

    with tab_log:
        st.subheader("Sand Records")
        thismonth = datetime.date.today().strftime("%Y-%m")
        month_total = sand_df[sand_df["date"].str.startswith(thismonth)]["qty"].sum() if not sand_df.empty else 0

        k1, k2, k3 = st.columns(3)
        k1.metric("Total (Range)",  f"{int(sand_df['qty'].sum()):,}" if not sand_df.empty else "0")
        k2.metric("This Month",     f"{int(month_total):,}")
        k3.metric("Entries",        len(sand_df))

        if sand_df.empty:
            st.info("No sand records for this factory / date range.")
        else:
            if HAS_PLOTLY:
                sand_ts = sand_df.groupby("date")["qty"].sum().reset_index().sort_values("date")
                fig_sand = px.bar(sand_ts, x="date", y="qty",
                                   color_discrete_sequence=["#A8791E"],
                                   template="plotly_white",
                                   title="Sand Usage Over Time",
                                   labels={"date":"Date","qty":"Quantity (units)"})
                fig_sand.update_layout(height=220, margin=dict(l=10,r=10,t=36,b=10))
                st.plotly_chart(fig_sand, width='stretch')

            if HAS_PLOTLY and "sand_type" in sand_df.columns:
                by_type = sand_df.groupby("sand_type")["qty"].sum().reset_index()
                fig_type = px.pie(by_type, names="sand_type", values="qty",
                                   hole=0.4,
                                   color_discrete_sequence=["#A8791E","#1E3A5F",
                                                             "#145C3C","#6E1423","#5B2C6F"],
                                   template="plotly_white",
                                   title="Usage by Sand Type")
                fig_type.update_layout(height=220, margin=dict(l=10,r=10,t=36,b=10))
                st.plotly_chart(fig_type, width='stretch')

            filtered_sand = search_filter(sand_df, "Search sand records", key="sand_search")
            filtered_sand = paginate_df(filtered_sand, key="sand_page")
            st.dataframe(filtered_sand.drop(columns=["id"], errors="ignore"),
                         width='stretch', hide_index=True, height=280)
            delete_row_ui(sand_df, "sand", "sand_type", "sand")

    with tab_edit_s:
        st.subheader("Edit a Sand Record")
        if sand_df.empty:
            st.info("No records to edit in the current date range.")
        else:
            opts = {
                f"ID {r['id']} — {r['sand_type']} ({r['date']})": r["id"]
                for _, r in sand_df.iterrows()
            }
            sel_label = st.selectbox("Select record to edit", list(opts.keys()),
                                      key="sand_edit_sel")
            sel_id  = opts[sel_label]
            sel_row = sand_df[sand_df["id"] == sel_id].iloc[0]

            sc1, sc2 = st.columns(2)
            with sc1:
                e_s_date    = st.date_input("Date",
                    value=pd.to_datetime(sel_row["date"]).date(), key="e_s_d")
                e_s_factory = st.selectbox("Factory", FACTORIES, key="e_s_f",
                    index=FACTORIES.index(sel_row["factory"])
                          if sel_row["factory"] in FACTORIES else 0,
                    disabled=not _is_admin)
            with sc2:
                e_s_qty  = st.number_input("Quantity",
                    min_value=0, step=1, value=int(sel_row["qty"]), key="e_s_q")
                _s_cur_unit = sel_row.get("unit", "Bags (50 KG)") or "Bags (50 KG)"
                e_s_unit = st.selectbox("Unit", SAND_UNITS, key="e_s_unit",
                    index=SAND_UNITS.index(_s_cur_unit) if _s_cur_unit in SAND_UNITS else 0)
                e_s_type = st.selectbox("Sand Type", SAND_TYPES, key="e_s_t",
                    index=SAND_TYPES.index(sel_row["sand_type"])
                          if sel_row["sand_type"] in SAND_TYPES else 0)

            if st.button("💾 Update Sand Record", key="sand_upd_btn"):
                if not e_s_qty:
                    st.warning("Quantity must be greater than 0.")
                else:
                    try:
                        cur.execute(
                            "UPDATE sand SET date=?,factory=?,qty=?,sand_type=?,unit=? WHERE id=?",
                            (str(e_s_date), e_s_factory, e_s_qty, e_s_type, e_s_unit, sel_id)
                        )
                        conn.commit()
                        log_audit("UPDATE", "sand", sel_id,
                                  f"{e_s_factory} | {e_s_type} | {e_s_qty} {e_s_unit}")
                        st.success("✅ Sand record updated.")
                        st.rerun()
                    except sqlite3.Error as e:
                        st.error(f"Database error: {e}")


# ─────────────────────────────────────────────────────────────────────────────
#  STOCK
# ─────────────────────────────────────────────────────────────────────────────
elif module == "Stock":

    st.title("🧱 Raw Material Stock")
    st.caption("Finished Goods stock (produced automatically from Production, consumed by "
               "Dispatch) is in the **📦 Finished Goods Stock** tab below.")

    # ── Persistent reorder banner — visible on every tab ─────────────────────
    _fac_for_banner = factory if factory != ALL_FACTORIES else None
    _banner_query   = (
        "SELECT material, factory, closing_stock FROM stock s1 "
        "WHERE id = (SELECT MAX(id) FROM stock s2 "
        "WHERE s2.material=s1.material AND s2.factory=s1.factory)"
        + (" AND factory=?" if _fac_for_banner else "")
    )
    _banner_df = pd.read_sql_query(
        _banner_query, conn,
        params=(_fac_for_banner,) if _fac_for_banner else ()
    )
    if not _banner_df.empty:
        _critical = _banner_df[_banner_df["closing_stock"] < 20]
        _low      = _banner_df[(_banner_df["closing_stock"] >= 20) &
                                (_banner_df["closing_stock"] < 50)]
        if not _critical.empty:
            _c_lines = ", ".join(
                f"**{r['material']}** ({r['factory']}) — {int(r['closing_stock'])} units"
                for _, r in _critical.iterrows()
            )
            st.error(f"🔴 **CRITICAL STOCK** — Reorder immediately: {_c_lines}")
        if not _low.empty:
            _l_lines = ", ".join(
                f"**{r['material']}** ({r['factory']}) — {int(r['closing_stock'])} units"
                for _, r in _low.iterrows()
            )
            st.warning(f"🟡 **LOW STOCK** — Plan reorder soon: {_l_lines}")
        if _critical.empty and _low.empty:
            st.success("✅ All materials at healthy stock levels")

    tab_entry, tab_log, tab_edit_stk, tab_status, tab_fg, tab_master, tab_fgmaster, tab_codes = st.tabs(
        ["➕ Log Stock", "📋 Records", "✏️ Edit Record", "📦 Current Levels",
         "🏭 Finished Goods Stock", "📇 Material Master", "🏷️ Finished Goods Master",
         "🏷️ Material Codes (legacy)"]
    )

    with tab_entry:
        st.subheader("New Stock Entry")
        c1, c2, c3 = st.columns(3)
        with c1:
            st_date    = st.date_input("Date", key="stk_d")
            st_factory = st.selectbox("Factory", FACTORIES, key="stk_f",
                                       index=FACTORIES.index(factory) if factory in FACTORIES else 0)
        with c2:
            st_material = st.selectbox("Material", MATERIALS, key="stk_m", format_func=lab_code_label)
            _stk_lab_code = get_lab_code(st_material)
            if _stk_lab_code:
                st.text_input("Lab Code", value=_stk_lab_code, key="stk_code_display", disabled=True,
                              help="From the official Material Master — not editable here.")
                st_code = _stk_lab_code
            else:
                st_code = st.text_input(
                    "Lab Code", value=get_material_code(st_material), key="stk_code",
                    placeholder="e.g. C0665/01",
                    help="This material isn't in the official Material Master yet — "
                         "enter its code manually, or add it via the Material Master tab.")
            st_received = st.number_input("Received (units)", min_value=0, step=1, key="stk_r")
        with c3:
            st_used = st.number_input("Used (units)", min_value=0, step=1, key="stk_u")
            st_unit = st.selectbox(
                "Unit", ["KG", "Bags", "Litres", "MT", "Barrel", "Units", "Other"], key="stk_unit")
            prev_row = pd.read_sql_query(
                "SELECT closing_stock FROM stock WHERE factory=? AND material=? ORDER BY id DESC LIMIT 1",
                conn, params=(st_factory, st_material)
            )
            last_close = int(prev_row.iloc[0, 0]) if not prev_row.empty else 0
            closing    = last_close + st_received - st_used
            st.metric("Closing Stock Preview", f"{closing:,}")

        if st.button("💾 Save Stock"):
            try:
                # FIX: duplicate-check + insert now run inside _write_lock so
                # two sessions saving the same date/factory/material at
                # nearly the same moment can't both pass the "no duplicate
                # yet" check before either has inserted — the second one now
                # waits for the first to commit, then correctly sees the
                # duplicate. recompute_stock_chain() re-derives closing_stock
                # for the whole (factory, material) ledger from the stored
                # received/used values afterwards, so the row's closing
                # balance is always correct regardless of what else was
                # written concurrently.
                with _write_lock():
                    _stk_dup = pd.read_sql_query(
                        "SELECT id FROM stock WHERE date=? AND factory=? AND material=?",
                        conn, params=(str(st_date), st_factory, st_material)
                    )
                    if not _stk_dup.empty:
                        _stk_saved = False
                    else:
                        cur.execute(
                            "INSERT INTO stock (date,factory,material,received,used,"
                            "closing_stock,unit,code) VALUES (?,?,?,?,?,?,?,?)",
                            (str(st_date), st_factory, st_material, st_received, st_used,
                             closing, st_unit, st_code.strip())
                        )
                        _stk_saved = True

                if not _stk_saved:
                    st.warning(
                        f"⚠️ A **{lab_code_label(st_material)}** entry for **{st_factory}** on "
                        f"**{st_date}** already exists. Use the ✏️ Edit tab to modify it."
                    )
                else:
                    recompute_stock_chain(st_factory, st_material)
                    # Only sync to the legacy material_codes table for items with no
                    # official Lab Code on file (e.g. "Other / Custom") — materials
                    # already in materials_master keep their authoritative code and
                    # are never overwritten from a stock entry.
                    if not _stk_lab_code and st_code.strip():
                        set_material_code(st_material, st_code.strip())
                    log_audit("INSERT", "stock", "new",
                              f"{st_factory} | {st_material} ({st_code.strip() or 'no code'}) | closing={closing}")
                    st.success(f"✅ {lab_code_label(st_material)} closing stock: {closing:,} units")
                    st.rerun()
            except sqlite3.Error as e:
                st.error(f"Database error: {e}")

    with tab_log:
        if stock_df.empty:
            st.info("No records.")
        else:
            _stk_k1, _stk_k2, _stk_k3 = st.columns(3)
            _stk_k1.metric("Total Entries",   len(stock_df))
            _stk_k2.metric("Total Received",  f"{int(stock_df['received'].sum()):,} units")
            _stk_k3.metric("Total Used",      f"{int(stock_df['used'].sum()):,} units")
            # Display copy with Lab Code in place of the material name (per the
            # Stock module's display rule) — deletion below still keys off `id`,
            # never the label text, so this swap is purely cosmetic and safe.
            # FIX: keep the raw (factory, material) around under a hidden
            # column so on_delete can recompute the right ledger chain after
            # a deletion — the visible table still drops it before display.
            _stock_df_disp = stock_df.copy()
            _stock_df_disp["_raw_material"] = _stock_df_disp["material"]
            _stock_df_disp["material"] = _stock_df_disp["material"].apply(lab_code_label)
            _stock_df_disp = _stock_df_disp.rename(columns={"material": "Lab Code"})
            filtered_stock = search_filter(_stock_df_disp, "Search stock records", key="stk_search")
            filtered_stock = paginate_df(filtered_stock, key="stk_page")
            st.dataframe(filtered_stock.drop(columns=["id", "_raw_material"], errors="ignore"),
                         width='stretch', hide_index=True, height=320)

            def _on_stock_delete(_row) -> None:
                # FIX: a deleted row's later chain-mates would otherwise
                # keep whatever closing_stock they had *including* the
                # deleted row's received/used — recompute the chain for
                # the pair the deleted row belonged to.
                recompute_stock_chain(_row["factory"], _row["_raw_material"])

            delete_row_ui(_stock_df_disp, "stock", "Lab Code", "stock", on_delete=_on_stock_delete)

    with tab_edit_stk:
        st.subheader("Edit a Stock Record")
        if stock_df.empty:
            st.info("No records to edit in the current date range.")
        else:
            opts = {
                f"ID {r['id']} — {lab_code_label(r['material'])} ({r['date']})": r["id"]
                for _, r in stock_df.iterrows()
            }
            sel_label = st.selectbox("Select record to edit", list(opts.keys()),
                                      key="stk_edit_sel")
            sel_id  = opts[sel_label]
            sel_row = stock_df[stock_df["id"] == sel_id].iloc[0]

            skc1, skc2, skc3 = st.columns(3)
            with skc1:
                e_st_date    = st.date_input("Date",
                    value=pd.to_datetime(sel_row["date"]).date(), key="e_stk_d")
                e_st_factory = st.selectbox("Factory", FACTORIES, key="e_stk_f",
                    index=FACTORIES.index(sel_row["factory"])
                          if sel_row["factory"] in FACTORIES else 0,
                    disabled=not _is_admin)
            with skc2:
                e_st_material = st.selectbox("Material", MATERIALS, key="e_stk_m",
                    index=MATERIALS.index(sel_row["material"])
                          if sel_row["material"] in MATERIALS else 0,
                    format_func=lab_code_label)
                _e_stk_lab_code = get_lab_code(e_st_material)
                if _e_stk_lab_code:
                    st.text_input("Lab Code", value=_e_stk_lab_code, key="e_stk_code_display",
                                  disabled=True,
                                  help="From the official Material Master — not editable here.")
                    e_st_code = _e_stk_lab_code
                else:
                    e_st_code = st.text_input(
                        "Lab Code", value=sel_row.get("code", "") or get_material_code(e_st_material),
                        key="e_stk_code",
                        help="This material isn't in the official Material Master yet — "
                             "enter its code manually, or add it via the Material Master tab.")
                e_st_received = st.number_input("Received (units)",
                    min_value=0, step=1, value=int(sel_row["received"]), key="e_stk_r")
            with skc3:
                e_st_used   = st.number_input("Used (units)",
                    min_value=0, step=1, value=int(sel_row["used"]), key="e_stk_u")
                _e_stk_units = ["KG", "Bags", "Litres", "MT", "Barrel", "Units", "Other"]
                _e_stk_unit_cur = sel_row.get("unit", "") or "KG"
                e_st_unit = st.selectbox("Unit", _e_stk_units, key="e_stk_unit",
                    index=_e_stk_units.index(_e_stk_unit_cur) if _e_stk_unit_cur in _e_stk_units else 0)
                e_st_prev   = pd.read_sql_query(
                    "SELECT closing_stock FROM stock WHERE factory=? AND material=? "
                    "AND id < ? ORDER BY id DESC LIMIT 1",
                    conn, params=(sel_row["factory"], sel_row["material"], sel_id)
                )
                e_st_last   = int(e_st_prev.iloc[0, 0]) if not e_st_prev.empty else 0
                e_st_close  = e_st_last + e_st_received - e_st_used
                st.metric("New Closing Stock", f"{e_st_close:,}")

            if st.button("💾 Update Stock Record", key="stk_upd_btn"):
                # FIX: remember the pair this row belonged to *before* the
                # update — needed below to fix up the old chain too, since
                # factory/material are editable and the row may be moving
                # to a different (factory, material) ledger entirely.
                _old_factory, _old_material = sel_row["factory"], sel_row["material"]
                try:
                    cur.execute(
                        "UPDATE stock SET date=?,factory=?,material=?,"
                        "received=?,used=?,closing_stock=?,unit=?,code=? WHERE id=?",
                        (str(e_st_date), e_st_factory, e_st_material,
                         e_st_received, e_st_used, e_st_close, e_st_unit,
                         e_st_code.strip(), sel_id)
                    )
                    conn.commit()
                    # FIX: this edit can change received/used on a row that
                    # has later rows chained after it (and/or move the row
                    # to a different material/factory) — recompute both the
                    # old chain (rows that used to follow this one) and the
                    # new chain (rows this one now belongs to) so nothing
                    # downstream is left showing a stale closing_stock.
                    recompute_stock_chain(_old_factory, _old_material)
                    recompute_stock_chain(e_st_factory, e_st_material)
                    if not _e_stk_lab_code and e_st_code.strip():
                        set_material_code(e_st_material, e_st_code.strip())
                    log_audit("UPDATE", "stock", sel_id,
                              f"{e_st_factory} | {e_st_material} | closing={e_st_close}")
                    st.success("✅ Stock record updated — downstream closing balances "
                               "for this material recalculated.")
                    st.rerun()
                except sqlite3.Error as e:
                    st.error(f"Database error: {e}")

    with tab_status:
        st.subheader("Current Stock Levels (Latest per Material)")
        # FIX: Replaced f-string SQL injection in stock query with parameterised version.
        if factory != ALL_FACTORIES:
            current = pd.read_sql_query(
                "SELECT material, factory, closing_stock, date, code FROM stock s1 "
                "WHERE id = (SELECT MAX(id) FROM stock s2 "
                "WHERE s2.material = s1.material AND s2.factory = s1.factory) "
                "AND factory = ? ORDER BY material",
                conn, params=(factory,)
            )
        else:
            current = pd.read_sql_query(
                "SELECT material, factory, closing_stock, date, code FROM stock s1 "
                "WHERE id = (SELECT MAX(id) FROM stock s2 "
                "WHERE s2.material = s1.material AND s2.factory = s1.factory) "
                "ORDER BY material",
                conn
            )
        if current.empty:
            st.info("No stock data yet.")
        else:
            def stock_status_label(qty: int) -> str:
                if qty < 20:   return "🔴 Critical"
                if qty < 50:   return "🟡 Low"
                if qty < 200:  return "🟢 OK"
                return "🔵 High"
            current["Status"] = current["closing_stock"].apply(stock_status_label)
            # Lab Code is the primary identifier shown here — authoritative code
            # from the Material Master, falling back to the legacy free-text code
            # (or the bare name as a last resort) only for items not yet catalogued.
            current["Lab Code"] = current.apply(
                lambda r: get_lab_code(r["material"]) or r["code"] or r["material"], axis=1)
            st.dataframe(
                current[["Lab Code","factory","closing_stock","date","Status"]]
                    .rename(columns={
                        "factory":"Factory",
                        "closing_stock":"Closing Stock","date":"Last Updated"
                    }),
                width='stretch', hide_index=True
            )

            if not current.empty:
                st.markdown("---")
                st.markdown("**Stock Level Visualisation**")
                max_stock = int(current["closing_stock"].max()) or 1
                for _, row in current.iterrows():
                    color = ("#6E1423" if row["closing_stock"] < 20 else
                             "#A8791E" if row["closing_stock"] < 50 else "#145C3C")
                    progress_bar(
                        f"{row['Lab Code']} ({row['factory']})",
                        row["closing_stock"],
                        max_stock,
                        color=color
                    )

            st.markdown("---")
            st.markdown("**Open a Material's 360° view**")
            st.caption("Opening stock, consumption trend, supplier, factory-wise stock, "
                        "and exhaustion forecast — all in one page.")
            for _mat in sorted(current["material"].unique()):
                mrow1, mrow2 = st.columns([5, 1])
                mrow1.markdown(f"🧱 **{lab_code_label(_mat)}**")
                if mrow2.button("360° →", key=f"mat360_{_mat}", use_container_width=True):
                    open_detail_view("material", _mat)

            if HAS_PLOTLY and not current.empty:
                fig_stk = px.bar(
                    current.sort_values("closing_stock", ascending=True),
                    x="closing_stock", y="Lab Code",
                    orientation="h",
                    color="closing_stock",
                    color_continuous_scale=["#6E1423","#D4AF37","#145C3C"],
                    template="plotly_white",
                    title="Current Stock by Material",
                    labels={"closing_stock":"Closing Stock","Lab Code":"Lab Code"}
                )
                fig_stk.update_layout(height=max(220, len(current) * 30 + 60),
                                       margin=dict(l=10,r=10,t=36,b=10),
                                       showlegend=False)
                st.plotly_chart(fig_stk, width='stretch')

    with tab_fg:
        st.subheader("🏭 Finished Goods Stock")
        st.caption("Derived automatically — Production entries add to it, Dispatch entries "
                   "subtract from it. Nothing is typed in here directly except manual "
                   "adjustments below.")

        _fg_fac_clause = " AND factory=?" if factory != ALL_FACTORIES else ""
        _fg_fac_param  = (factory,) if factory != ALL_FACTORIES else ()
        _fg_current = pd.read_sql_query(
            "SELECT factory, product, closing_stock, date FROM fg_stock f1 "
            "WHERE id = (SELECT MAX(id) FROM fg_stock f2 "
            "WHERE f2.factory = f1.factory AND f2.product = f1.product)"
            + _fg_fac_clause + " ORDER BY product",
            conn, params=_fg_fac_param
        )
        if _fg_current.empty:
            st.info("No Finished Goods stock movements yet — save a Production or Dispatch "
                    "entry to start the ledger.")
        else:
            _fg_current_disp = _fg_current.copy()
            _fg_current_disp.insert(2, "rm_code", _fg_current_disp["product"].apply(get_fg_code))
            st.dataframe(
                _fg_current_disp.rename(columns={
                    "factory": "Factory", "product": "Product", "rm_code": "RM Code",
                    "closing_stock": "Closing FG Stock", "date": "Last Movement"
                }),
                width='stretch', hide_index=True, height=300
            )
            if HAS_PLOTLY:
                fig_fg = px.bar(
                    _fg_current.sort_values("closing_stock", ascending=True),
                    x="closing_stock", y="product", orientation="h",
                    color="closing_stock",
                    color_continuous_scale=["#6E1423", "#D4AF37", "#145C3C"],
                    template="plotly_white", title="Current FG Stock by Product",
                    labels={"closing_stock": "Closing Stock", "product": "Product"}
                )
                fig_fg.update_layout(height=max(220, len(_fg_current) * 30 + 60),
                                      margin=dict(l=10, r=10, t=36, b=10), showlegend=False)
                st.plotly_chart(fig_fg, width='stretch')

        st.markdown("---")
        st.markdown("#### ➕ Manual Adjustment")
        st.caption("For opening balances, physical count corrections, or damage/write-offs — "
                   "not for routine production or dispatch, which are captured automatically.")
        fgc1, fgc2, fgc3 = st.columns(3)
        with fgc1:
            fg_adj_factory = st.selectbox("Factory", FACTORIES, key="fg_adj_f",
                                           index=FACTORIES.index(factory) if factory in FACTORIES else 0)
            fg_adj_product = st.selectbox("Product", FCSC_PRODUCTS, key="fg_adj_p", format_func=fg_label)
        with fgc2:
            fg_adj_custom = st.text_input("Custom name (if 'Other / Custom')", key="fg_adj_p_cust")
            fg_adj_qty    = st.number_input("Adjustment (+/-)", step=1.0, key="fg_adj_qty",
                                             help="Positive to add stock, negative to remove.")
        with fgc3:
            fg_adj_reason = st.text_input("Reason", key="fg_adj_reason",
                                           placeholder="e.g. Opening balance, physical count")
            _fg_adj_final_product = (fg_adj_custom.strip()
                                      if fg_adj_product == "Other / Custom" and fg_adj_custom.strip()
                                      else fg_adj_product)
            if _fg_adj_final_product and _fg_adj_final_product != "Other / Custom":
                st.metric("Current FG Stock",
                          f"{get_fg_closing_stock(fg_adj_factory, _fg_adj_final_product):,.2f}")
        if st.button("💾 Save Adjustment", key="fg_adj_save"):
            if not _fg_adj_final_product or _fg_adj_final_product == "Other / Custom":
                st.warning("Please select or enter a product.")
            elif fg_adj_qty == 0:
                st.warning("Enter a non-zero adjustment.")
            else:
                _fg_new_closing = record_fg_stock_movement(
                    datetime.date.today(), fg_adj_factory, _fg_adj_final_product,
                    adjustment=fg_adj_qty, source_module="Manual Adjustment"
                )
                log_audit("INSERT", "fg_stock", "adjustment",
                          f"{fg_adj_factory} | {_fg_adj_final_product} | {fg_adj_qty:+} | {fg_adj_reason}")
                st.success(f"✅ Adjustment saved — {_fg_adj_final_product} @ {fg_adj_factory} "
                           f"FG Stock now {_fg_new_closing:,.2f}")
                st.rerun()

    with tab_master:
        st.subheader("📇 Material Master")
        st.caption("The official codification — Raw Materials, Packaging, Labels/Stickers, "
                    "and Process/Intermediate items — sourced from the plant team's "
                    "Codification_for_System.xlsx. This is the single source of truth used "
                    "by every dropdown across the ERP.")

        _mm_all = get_material_master_df()
        _mm_pending = _mm_all[_mm_all["status"] == "Pending Code Confirmation"]

        cmm1, cmm2, cmm3 = st.columns(3)
        cmm1.metric("Total Materials", len(_mm_all))
        cmm2.metric("Confirmed", len(_mm_all) - len(_mm_pending))
        cmm3.metric("⏳ Pending Code Confirmation", len(_mm_pending))

        if not _mm_pending.empty:
            with st.expander(f"⏳ {len(_mm_pending)} materials awaiting plant-team code confirmation", expanded=False):
                st.caption("These materials had a code collision in the source sheet (the same "
                           "Procurement Code assigned to two different materials, or a material "
                           "listed twice with two different codes). They work everywhere in the "
                           "ERP already — they're just flagged until the plant QC head confirms "
                           "the correct code. Update the code below the moment you hear back; "
                           "no other change is needed anywhere else in the app.")
                st.dataframe(
                    _mm_pending[["lab_code", "name", "category"]].rename(
                        columns={"lab_code": "Lab Code", "name": "Material", "category": "Category"}),
                    width='stretch', hide_index=True
                )

        st.markdown("---")
        st.markdown("#### Browse Material Master")
        _mm_cat = st.selectbox(
            "Category", ["All"] + sorted(_mm_all["category"].unique().tolist()), key="mm_cat_filter"
        )
        _mm_view = _mm_all if _mm_cat == "All" else _mm_all[_mm_all["category"] == _mm_cat]
        _mm_view = search_filter(_mm_view, "Search materials, lab codes, or procurement codes", key="mm_search")
        st.dataframe(
            _mm_view[["lab_code", "name", "procurement_code", "category", "status"]].rename(
                columns={"lab_code": "Lab Code", "name": "Material Name",
                         "procurement_code": "Procurement Code", "category": "Category",
                         "status": "Status"}),
            width='stretch', hide_index=True, height=360
        )

        st.markdown("---")
        st.markdown("#### Confirm a Pending Procurement Code")
        st.caption("Use this once the plant team resolves a code collision — this is the only "
                    "place you need to update it.")
        if not _mm_pending.empty:
            mmp1, mmp2 = st.columns([2, 1])
            with mmp1:
                mm_pending_pick = st.selectbox(
                    "Material", _mm_pending["name"].tolist(), key="mm_pending_pick")
            with mmp2:
                mm_new_code = st.text_input("Confirmed Procurement Code", key="mm_new_code",
                                             placeholder="e.g. R1009")
            if st.button("✅ Confirm Code", key="mm_confirm_code"):
                if not mm_new_code.strip():
                    st.error("Enter the confirmed code before saving.")
                else:
                    cur.execute(
                        "UPDATE materials_master SET procurement_code = ?, status = 'Confirmed' "
                        "WHERE name = ?", (mm_new_code.strip(), mm_pending_pick)
                    )
                    conn.commit()
                    log_audit("UPDATE", "materials_master", mm_pending_pick,
                               f"procurement_code confirmed = {mm_new_code.strip()}")
                    st.success(f"✅ {mm_pending_pick} → {mm_new_code.strip()} (now Confirmed)")
                    st.rerun()
        else:
            st.success("✅ No materials currently pending code confirmation.")

        st.markdown("---")
        st.markdown("#### ➕ Add New Material")
        am1, am2, am3 = st.columns(3)
        with am1:
            am_name = st.text_input("Material Name *", key="mm_add_name")
            am_lab_code = st.text_input("Lab Code / RM Code", key="mm_add_lab", placeholder="e.g. C9999/01")
        with am2:
            am_proc_code = st.text_input("Procurement Code", key="mm_add_proc", placeholder="e.g. R9999")
            am_category = st.selectbox("Category",
                ["Raw Material", "Packaging", "Label/Sticker", "Process/Intermediate"], key="mm_add_cat")
        with am3:
            am_status = st.selectbox("Status", ["Confirmed", "Pending Code Confirmation"], key="mm_add_status")
        if st.button("💾 Add Material", key="mm_add_btn"):
            ok, msg = add_material_master(am_lab_code, am_name, am_proc_code, am_category, am_status)
            (st.success if ok else st.error)(msg)
            if ok:
                st.rerun()

        st.markdown("---")
        st.markdown("#### ✏️ Edit / Deactivate a Material")
        _mm_edit_names = _mm_all["name"].tolist()
        if _mm_edit_names:
            em_pick = st.selectbox("Material", _mm_edit_names, key="mm_edit_pick")
            _em_row = _mm_all[_mm_all["name"] == em_pick].iloc[0]
            _cat_opts = ["Raw Material", "Packaging", "Label/Sticker", "Process/Intermediate"]
            em1, em2, em3 = st.columns(3)
            with em1:
                em_lab = st.text_input("Lab Code / RM Code", value=_em_row["lab_code"] or "", key="mm_edit_lab")
            with em2:
                em_proc = st.text_input("Procurement Code", value=_em_row["procurement_code"] or "", key="mm_edit_proc")
            with em3:
                _status_opts = ["Confirmed", "Pending Code Confirmation", "Inactive"]
                _cur_status = _em_row["status"] if _em_row["status"] in _status_opts else "Confirmed"
                em_status = st.selectbox("Status", _status_opts, index=_status_opts.index(_cur_status), key="mm_edit_status")
            em_cat = st.selectbox("Category", _cat_opts,
                index=(_cat_opts.index(_em_row["category"]) if _em_row["category"] in _cat_opts else 0),
                key="mm_edit_cat")
            if st.button("💾 Save Changes", key="mm_edit_save"):
                ok, msg = update_material_master(int(_em_row["id"]), em_lab, em_proc, em_cat, em_status)
                (st.success if ok else st.error)(msg)
                if ok:
                    st.rerun()
            st.caption("Setting status to **Inactive** removes it from every dropdown (Stock, Quality, "
                        "Procurement, Formulation) without touching historical records that reference it.")

        st.markdown("---")
        st.markdown("#### 📤 Import Material Master (Excel / CSV)")
        st.caption("Columns expected: lab_code, name, procurement_code, category, status. "
                    "Matches on name — existing materials update, new names get added.")
        mm_upload = st.file_uploader("Upload file", type=["xlsx", "csv"], key="mm_upload")
        if mm_upload is not None:
            try:
                _imp_df = pd.read_csv(mm_upload) if mm_upload.name.endswith(".csv") else pd.read_excel(mm_upload)
                _imp_df.columns = [c.strip().lower() for c in _imp_df.columns]
                if "name" not in _imp_df.columns:
                    st.error("File must include at least a 'name' column.")
                else:
                    st.dataframe(_imp_df.head(10), width='stretch', hide_index=True)
                    if st.button(f"✅ Import {len(_imp_df)} row(s)", key="mm_import_btn"):
                        _added, _updated = 0, 0
                        for _, _r in _imp_df.iterrows():
                            _nm = str(_r.get("name", "")).strip()
                            if not _nm:
                                continue
                            _lc = str(_r.get("lab_code", "") or "").strip() or None
                            _pc = str(_r.get("procurement_code", "") or "").strip() or None
                            _ct = str(_r.get("category", "") or "Raw Material").strip() or "Raw Material"
                            _st_ = str(_r.get("status", "") or "Confirmed").strip() or "Confirmed"
                            _exist = cur.execute("SELECT id FROM materials_master WHERE name=?", (_nm,)).fetchone()
                            if _exist:
                                cur.execute(
                                    "UPDATE materials_master SET lab_code=?, procurement_code=?, category=?, status=? WHERE id=?",
                                    (_lc, _pc, _ct, _st_, _exist[0]))
                                _updated += 1
                            else:
                                cur.execute(
                                    "INSERT INTO materials_master(lab_code,name,procurement_code,category,status,created_at) "
                                    "VALUES (?,?,?,?,?,?)",
                                    (_lc, _nm, _pc, _ct, _st_, datetime.datetime.now().isoformat(timespec="seconds")))
                                _added += 1
                        conn.commit()
                        log_audit("INSERT", "materials_master", "bulk_import",
                                   f"{_added} added, {_updated} updated by {st.session_state.username}")
                        st.success(f"✅ Import complete — {_added} added, {_updated} updated.")
                        st.rerun()
            except Exception as e:
                st.error(f"Could not read file: {e}")

        st.markdown("---")
        st.markdown("#### 📥 Export Material Master")
        _mm_export_buf = BytesIO()
        with pd.ExcelWriter(_mm_export_buf, engine="openpyxl") as _mm_writer:
            _mm_all.to_excel(_mm_writer, sheet_name="Material Master", index=False)
        _mm_export_buf.seek(0)
        st.download_button(
            "📥 Download Material Master (Excel)", data=_mm_export_buf,
            file_name=f"FCSC_MaterialMaster_{datetime.date.today()}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="mm_export_btn"
        )

    with tab_fgmaster:
        st.subheader("🏷️ Finished Goods Master")
        st.caption("The official finished-product codification — sourced from the plant team's "
                    "finished_good_codification.xlsx. This is the single source of truth used "
                    "by every Product dropdown across the ERP (Production, Sales, Dispatch, "
                    "Formulation, Quality).")

        _fgm_all = get_finished_goods_master_df()
        _fgm_pending = _fgm_all[_fgm_all["status"] == "Pending Code Confirmation"]

        cfg1, cfg2, cfg3 = st.columns(3)
        cfg1.metric("Total Finished Products", len(_fgm_all))
        cfg2.metric("Confirmed", len(_fgm_all) - len(_fgm_pending))
        cfg3.metric("⏳ Pending Code Confirmation", len(_fgm_pending))

        if not _fgm_pending.empty:
            with st.expander(f"⏳ {len(_fgm_pending)} products awaiting a code", expanded=False):
                st.caption("These finished products had no code assigned yet in the source "
                           "sheet. They work everywhere in the ERP already — they're just "
                           "flagged until the plant team assigns the code. Update it below the "
                           "moment you hear back; no other change is needed anywhere else in "
                           "the app.")
                st.dataframe(
                    _fgm_pending[["name"]].rename(columns={"name": "Product"}),
                    width='stretch', hide_index=True
                )

        st.markdown("---")
        st.markdown("#### Browse Finished Goods Master")
        _fgm_view = search_filter(_fgm_all, "Search products or codes", key="fgm_search")
        st.dataframe(
            _fgm_view[["name", "code", "status"]].rename(
                columns={"name": "Product", "code": "RM Code", "status": "Status"}),
            width='stretch', hide_index=True, height=360
        )

        st.markdown("---")
        st.markdown("#### Confirm a Pending Code")
        st.caption("Use this once the plant team assigns the code — this is the only place "
                    "you need to update it.")
        if not _fgm_pending.empty:
            fgmp1, fgmp2 = st.columns([2, 1])
            with fgmp1:
                fgm_pending_pick = st.selectbox(
                    "Product", _fgm_pending["name"].tolist(), key="fgm_pending_pick")
            with fgmp2:
                fgm_new_code = st.text_input("Confirmed RM Code", key="fgm_new_code",
                                              placeholder="e.g. FPS_C010_1K")
            if st.button("✅ Confirm Code", key="fgm_confirm_code"):
                if not fgm_new_code.strip():
                    st.error("Enter the confirmed code before saving.")
                else:
                    cur.execute(
                        "UPDATE finished_goods_master SET code = ?, status = 'Confirmed' "
                        "WHERE name = ?", (fgm_new_code.strip(), fgm_pending_pick)
                    )
                    conn.commit()
                    log_audit("UPDATE", "finished_goods_master", fgm_pending_pick,
                               f"code confirmed = {fgm_new_code.strip()}")
                    st.success(f"✅ {fgm_pending_pick} → {fgm_new_code.strip()} (now Confirmed)")
                    st.rerun()
        else:
            st.success("✅ No finished products currently pending a code.")

        st.markdown("---")
        st.markdown("#### ➕ Add New Finished Product")
        afg1, afg2 = st.columns(2)
        with afg1:
            afg_name = st.text_input("Product Name *", key="fgm_add_name")
        with afg2:
            afg_code = st.text_input("RM Code", key="fgm_add_code", placeholder="e.g. FPS_C010_1K")
        afg_status = st.selectbox("Status", ["Confirmed", "Pending Code Confirmation"], key="fgm_add_status")
        if st.button("💾 Add Finished Product", key="fgm_add_btn"):
            ok, msg = add_finished_good(afg_name, afg_code, afg_status)
            (st.success if ok else st.error)(msg)
            if ok:
                st.rerun()

        st.markdown("---")
        st.markdown("#### ✏️ Edit / Deactivate a Finished Product")
        _fgm_edit_names = _fgm_all["name"].tolist()
        if _fgm_edit_names:
            efg_pick = st.selectbox("Product", _fgm_edit_names, key="fgm_edit_pick")
            _efg_row = _fgm_all[_fgm_all["name"] == efg_pick].iloc[0]
            efg1, efg2 = st.columns(2)
            with efg1:
                efg_code = st.text_input("RM Code", value=_efg_row["code"] or "", key="fgm_edit_code")
            with efg2:
                _fgm_status_opts = ["Confirmed", "Pending Code Confirmation", "Inactive"]
                _fgm_cur_status = _efg_row["status"] if _efg_row["status"] in _fgm_status_opts else "Confirmed"
                efg_status = st.selectbox("Status", _fgm_status_opts,
                    index=_fgm_status_opts.index(_fgm_cur_status), key="fgm_edit_status")
            if st.button("💾 Save Changes", key="fgm_edit_save"):
                ok, msg = update_finished_good(int(_efg_row["id"]), efg_code, efg_status)
                (st.success if ok else st.error)(msg)
                if ok:
                    st.rerun()
            st.caption("Setting status to **Inactive** removes it from every dropdown (Production, "
                        "Sales, Dispatch, Formulation) without touching historical records that "
                        "reference it.")

        st.markdown("---")
        st.markdown("#### 📤 Import Finished Goods Master (Excel / CSV)")
        st.caption("Columns expected: name, code, status. Matches on name — existing products "
                    "update, new names get added.")
        fgm_upload = st.file_uploader("Upload file", type=["xlsx", "csv"], key="fgm_upload")
        if fgm_upload is not None:
            try:
                _fgm_imp_df = pd.read_csv(fgm_upload) if fgm_upload.name.endswith(".csv") else pd.read_excel(fgm_upload)
                _fgm_imp_df.columns = [c.strip().lower() for c in _fgm_imp_df.columns]
                if "name" not in _fgm_imp_df.columns:
                    st.error("File must include at least a 'name' column.")
                else:
                    st.dataframe(_fgm_imp_df.head(10), width='stretch', hide_index=True)
                    if st.button(f"✅ Import {len(_fgm_imp_df)} row(s)", key="fgm_import_btn"):
                        _fgm_added, _fgm_updated = 0, 0
                        for _, _r in _fgm_imp_df.iterrows():
                            _nm = str(_r.get("name", "")).strip()
                            if not _nm:
                                continue
                            _cd = str(_r.get("code", "") or "").strip() or None
                            _st_ = str(_r.get("status", "") or "Confirmed").strip() or "Confirmed"
                            _exist = cur.execute("SELECT id FROM finished_goods_master WHERE name=?", (_nm,)).fetchone()
                            if _exist:
                                cur.execute(
                                    "UPDATE finished_goods_master SET code=?, status=? WHERE id=?",
                                    (_cd, _st_, _exist[0]))
                                _fgm_updated += 1
                            else:
                                cur.execute(
                                    "INSERT INTO finished_goods_master(name,code,status,created_at) "
                                    "VALUES (?,?,?,?)",
                                    (_nm, _cd, _st_, datetime.datetime.now().isoformat(timespec="seconds")))
                                _fgm_added += 1
                        conn.commit()
                        log_audit("INSERT", "finished_goods_master", "bulk_import",
                                   f"{_fgm_added} added, {_fgm_updated} updated by {st.session_state.username}")
                        st.success(f"✅ Import complete — {_fgm_added} added, {_fgm_updated} updated.")
                        st.rerun()
            except Exception as e:
                st.error(f"Could not read file: {e}")

        st.markdown("---")
        st.markdown("#### 📥 Export Finished Goods Master")
        _fgm_export_buf = BytesIO()
        with pd.ExcelWriter(_fgm_export_buf, engine="openpyxl") as _fgm_writer:
            _fgm_all.to_excel(_fgm_writer, sheet_name="Finished Goods Master", index=False)
        _fgm_export_buf.seek(0)
        st.download_button(
            "📥 Download Finished Goods Master (Excel)", data=_fgm_export_buf,
            file_name=f"FCSC_FinishedGoodsMaster_{datetime.date.today()}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="fgm_export_btn"
        )

    with tab_codes:
        st.subheader("🏷️ Material Codes (legacy)")
        st.info("Superseded by the **📇 Material Master** tab above, which is now the "
                 "authoritative source. This legacy editor is kept only for any custom/"
                 "not-yet-catalogued materials — new materials should be added to the "
                 "official master (Codification_for_System.xlsx), not typed in here.")
        st.caption("Internal codes (e.g. C0665/01) for raw materials, pre-loaded from "

                    "the factory's RM Daily Stock tracker. These auto-fill the "
                    "'Material Code' field whenever that material is logged in Stock.")

        _codes_all = pd.read_sql_query(
            "SELECT * FROM material_codes ORDER BY material", conn)
        cm1, cm2 = st.columns(2)
        cm1.metric("Materials with a Code on File", len(_codes_all))
        cm2.metric("Total Materials in Master List", len(MATERIALS))

        st.markdown("---")

        if not _codes_all.empty:
            _codes_search = search_filter(_codes_all, "Search materials or codes", key="code_search")
            st.dataframe(
                _codes_search.rename(columns={"material": "Material", "code": "Code"}),
                width='stretch', hide_index=True, height=320
            )
        else:
            st.info("No material codes saved yet.")

        st.markdown("#### Set / Update a Material's Code")
        mc1, mc2 = st.columns([2, 1])
        with mc1:
            mc_material = st.selectbox("Material", MATERIALS, key="mc_material", format_func=material_label)
        with mc2:
            mc_code = st.text_input(
                "Code", value=get_material_code(st.session_state.get("mc_material", MATERIALS[0])),
                key="mc_code", placeholder="e.g. C0665/01")
        if st.button("💾 Save Code", key="mc_save"):
            set_material_code(mc_material, mc_code)
            log_audit("UPDATE", "material_codes", mc_material, f"code={mc_code.strip()}")
            st.success(f"✅ {mc_material} → {mc_code.strip() or '(cleared)'}")
            st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
#  PROCUREMENT  (NEW — low-stock alerts → tracked purchase workflow)
# ─────────────────────────────────────────────────────────────────────────────
elif module == "Procurement":

    st.title("🛒 Procurement")
    st.markdown(
        "<p style='color:#8C7B62;font-size:13px;margin-top:-10px;'>"
        "Low stock automatically opens a request and emails the purchase team. "
        "Store, plant and purchase staff track it through to Stock Updated.</p>",
        unsafe_allow_html=True,
    )

    _proc_factory_filter = None if _is_admin else _user_factory

    tab_proc_active, tab_proc_new, tab_proc_forecast, tab_proc_vendors, tab_proc_history, tab_proc_settings = st.tabs(
        ["📋 Active Requests", "➕ New Request", "📈 Forecast", "🏭 Vendors", "✅ History",
         "⚙️ Settings" if _is_admin else "ℹ️ Info"]
    )

    # ── ACTIVE REQUESTS ─────────────────────────────────────────────────────
    with tab_proc_active:
        _q = "SELECT * FROM procurement_requests WHERE status='Open'"
        _params: list = []
        if _proc_factory_filter:
            _q += " AND factory = ?"
            _params.append(_proc_factory_filter)
        _q += " ORDER BY created_at DESC"
        open_reqs = pd.read_sql_query(_q, conn, params=_params)

        pm1, pm2, pm3 = st.columns(3)
        pm1.metric("Open Requests", len(open_reqs))

        overdue_count = 0
        if not open_reqs.empty:
            _ids = tuple(int(x) for x in open_reqs["id"].tolist())
            _ph = ",".join("?" * len(_ids))
            overdue_count = cur.execute(
                f"SELECT COUNT(*) FROM procurement_stages WHERE request_id IN ({_ph}) "
                f"AND status NOT IN ('Completed','Skipped') AND due_date < ?",
                (*_ids, str(datetime.date.today()))
            ).fetchone()[0]
        pm2.metric("Overdue Stages", overdue_count)
        pm3.metric("Auto-Triggered",
                    int((open_reqs["trigger_type"] == "auto_low_stock").sum()) if not open_reqs.empty else 0)

        st.markdown("---")

        if open_reqs.empty:
            st.info("No open procurement requests. New ones appear automatically when stock runs low, "
                     "or raise one manually in the ➕ New Request tab.")
        else:
            for _, req in open_reqs.iterrows():
                req_id = int(req["id"])
                stages_df = pd.read_sql_query(
                    "SELECT id, seq, stage_name, status, owner, due_date FROM procurement_stages "
                    "WHERE request_id = ? ORDER BY seq",
                    conn, params=[req_id]
                )
                done = int(stages_df["status"].isin(["Completed", "Skipped"]).sum())
                total_stages = len(stages_df)
                pct = (done / total_stages * 100) if total_stages else 0
                trigger_tag = "🤖 Auto (Low Stock)" if req["trigger_type"] == "auto_low_stock" else "✍️ Manual"
                _proc_code = material_procurement_code(req["material"])
                _mat_display = f"{_proc_code} – {req['material']}" if _proc_code else req["material"]

                with st.expander(
                    f"PR-{req_id:05d} — {_mat_display} @ {req['factory']}  ·  "
                    f"{trigger_tag}  ·  {pct:.0f}% complete",
                    expanded=False,
                ):
                    st.caption(f"Opened {req['created_at'][:16]} — {req['notes']}")

                    # ── Vendor linkage ──────────────────────────────────────
                    _all_vendor_names = [r[0] for r in cur.execute(
                        "SELECT name FROM vendors ORDER BY name").fetchall()]
                    _cur_vendor = req["vendor"] or ""
                    _vendor_opts = ["— No vendor linked —"] + _all_vendor_names
                    _vendor_idx = (_vendor_opts.index(_cur_vendor)
                                   if _cur_vendor in _vendor_opts else 0)

                    vcol1, vcol2, vcol3 = st.columns([3, 1, 1])
                    with vcol1:
                        _picked_vendor = st.selectbox(
                            "Vendor", _vendor_opts, index=_vendor_idx,
                            key=f"proc_vendor_pick_{req_id}", label_visibility="collapsed")
                    _picked_clean = _picked_vendor if _picked_vendor != "— No vendor linked —" else ""
                    with vcol2:
                        if st.button("💾 Save", key=f"proc_save_vendor_{req_id}",
                                      width='stretch', disabled=(_picked_clean == _cur_vendor)):
                            cur.execute("UPDATE procurement_requests SET vendor=? WHERE id=?",
                                        (_picked_clean, req_id))
                            conn.commit()
                            log_audit("UPDATE", "procurement_requests", req_id,
                                       f"Vendor set to {_picked_clean or '(none)'}")
                            st.rerun()
                    with vcol3:
                        if st.button("📧 Notify", key=f"proc_notify_vendor_{req_id}",
                                      width='stretch'):
                            if _picked_clean != _cur_vendor:
                                cur.execute("UPDATE procurement_requests SET vendor=? WHERE id=?",
                                            (_picked_clean, req_id))
                                conn.commit()
                            ok, msg = send_vendor_email(
                                _picked_clean, req["material"], req["factory"],
                                req["qty_suggested"], req["unit"], req_id)
                            (st.success if ok else st.warning)(msg)

                    progress_bar("Workflow progress", done, total_stages)

                    editor_df = stages_df.drop(columns=["id", "seq"]).rename(
                        columns={"stage_name": "Stage", "status": "Status",
                                 "owner": "Owner", "due_date": "Due Date"}
                    )
                    editor_df["Due Date"] = pd.to_datetime(editor_df["Due Date"], errors="coerce")

                    edited = st.data_editor(
                        editor_df,
                        column_config={
                            "Stage": st.column_config.TextColumn(disabled=True),
                            "Status": st.column_config.SelectboxColumn(
                                options=STAGE_STATUSES, required=True),
                            "Owner": st.column_config.TextColumn(),
                            "Due Date": st.column_config.DateColumn(),
                        },
                        hide_index=True, width='stretch',
                        key=f"proc_editor_{req_id}",
                    )

                    if st.button("💾 Save Progress", key=f"proc_save_{req_id}"):
                        for (_, orig), (_, new) in zip(stages_df.iterrows(), edited.iterrows(), strict=True):
                            new_due = str(new["Due Date"].date()) if pd.notna(new["Due Date"]) else None
                            if (new["Status"] != orig["status"] or new["Owner"] != orig["owner"]
                                    or new_due != orig["due_date"]):
                                completed_at = (
                                    datetime.datetime.now().isoformat(timespec="seconds")
                                    if new["Status"] in ("Completed", "Skipped") else None
                                )
                                try:
                                    cur.execute(
                                        "UPDATE procurement_stages SET status=?, owner=?, due_date=?, "
                                        "completed_at=?, updated_by=? WHERE id=?",
                                        (new["Status"], new["Owner"], new_due, completed_at,
                                         st.session_state.username, int(orig["id"]))
                                    )
                                except sqlite3.Error as e:
                                    st.error(f"Database error while saving: {e}")
                        conn.commit()
                        log_audit("UPDATE", "procurement_stages", req_id, "Stage progress updated")

                        remaining = cur.execute(
                            "SELECT COUNT(*) FROM procurement_stages WHERE request_id = ? "
                            "AND status NOT IN ('Completed','Skipped')",
                            (req_id,)
                        ).fetchone()[0]
                        if remaining == 0:
                            cur.execute(
                                "UPDATE procurement_requests SET status='Closed', closed_at=? WHERE id=?",
                                (datetime.datetime.now().isoformat(timespec="seconds"), req_id)
                            )
                            conn.commit()
                            log_audit("UPDATE", "procurement_requests", req_id,
                                       "Auto-closed — all stages complete")
                            st.success("✅ All stages complete — request closed.")
                        st.rerun()

    # ── NEW REQUEST (manual) ────────────────────────────────────────────────
    with tab_proc_new:
        st.subheader("Raise a Manual Procurement Request")
        st.caption("Use this when the plant or store team needs to start a purchase "
                    "before it's automatically triggered by a low-stock reading.")

        nr1, nr2 = st.columns(2)
        with nr1:
            nr_factory = st.selectbox(
                "Factory", FACTORIES if _is_admin else [_user_factory], key="nr_factory")
            nr_material = st.selectbox("Material", MATERIALS, key="nr_material", format_func=material_label)
        with nr2:
            nr_qty  = st.number_input("Quantity Needed", min_value=0.0, step=1.0, key="nr_qty")
            nr_unit = st.selectbox(
                "Unit", ["Bags", "KG", "MT", "Litres", "Units", "Other"], key="nr_unit")

        _suggested_vendor = get_default_vendor_for_material(nr_material)
        _all_vendor_names_nr = [r[0] for r in cur.execute(
            "SELECT name FROM vendors ORDER BY name").fetchall()]
        _nr_vendor_opts = ["— No vendor —"] + _all_vendor_names_nr
        _nr_default_idx = (_nr_vendor_opts.index(_suggested_vendor)
                            if _suggested_vendor in _nr_vendor_opts else 0)
        if _suggested_vendor:
            st.caption(f"💡 Default vendor on file for **{nr_material}**: **{_suggested_vendor}**")
        nr_vendor_pick = st.selectbox("Vendor", _nr_vendor_opts, index=_nr_default_idx, key="nr_vendor")

        nr_notes  = st.text_area("Notes / Reason", key="nr_notes")
        nr_notify = st.checkbox("📧 Notify purchase department by email now",
                                  value=True, key="nr_notify")
        nr_notify_vendor = st.checkbox("📧 Also notify the vendor directly (if linked)",
                                         value=bool(_suggested_vendor), key="nr_notify_vendor")

        if st.button("🚀 Raise Procurement Request", key="nr_submit"):
            if not nr_material:
                st.warning("Select a material.")
            else:
                _nr_vendor = nr_vendor_pick if nr_vendor_pick != "— No vendor —" else ""
                req_id = _open_procurement_request(
                    nr_material, nr_factory, "manual", nr_qty, nr_unit, nr_notes.strip(),
                    vendor=_nr_vendor
                )
                if nr_notify:
                    sent, msg = send_procurement_alert_email(
                        nr_material, nr_factory, nr_qty, nr_qty, nr_unit, req_id)
                    (st.success if sent else st.warning)(msg)
                if nr_notify_vendor and _nr_vendor:
                    vsent, vmsg = send_vendor_email(
                        _nr_vendor, nr_material, nr_factory, nr_qty, nr_unit, req_id)
                    (st.success if vsent else st.warning)(vmsg)
                st.success(f"✅ Procurement request PR-{req_id:05d} raised for {nr_material} @ {nr_factory}.")
                st.rerun()

    # ── FORECAST (reorder-point projection) ─────────────────────────────────
    with tab_proc_forecast:
        st.subheader("📈 Reorder-Point Forecast")
        st.caption("Projects when each material will hit its reorder threshold, based on "
                    "the average daily 'used' quantity logged in Stock over the last 30 days — "
                    "so you can see a shortage coming instead of only finding out once it's already low.")

        fc_days = st.slider("Lookback window (days)", 7, 90, 30, key="fc_lookback")
        forecast_df = reorder_forecast(days_history=fc_days)

        if _proc_factory_filter and not forecast_df.empty:
            forecast_df = forecast_df[forecast_df["factory"] == _proc_factory_filter]

        if forecast_df.empty:
            st.info("Not enough stock history yet to forecast. Log a few days of Stock entries first.")
        else:
            critical = forecast_df[forecast_df["days_to_threshold"].notna()
                                    & (forecast_df["days_to_threshold"] <= 7)]
            fcm1, fcm2, fcm3 = st.columns(3)
            fcm1.metric("Materials Tracked", len(forecast_df))
            fcm2.metric("Critical (≤7 days)", len(critical))
            fcm3.metric("No usage trend", int(forecast_df["days_to_threshold"].isna().sum()))

            if not critical.empty:
                st.error(f"⚠️ {len(critical)} material(s) projected to hit reorder threshold within a week.")

            disp_fc = forecast_df.copy()
            disp_fc["days_to_threshold"] = disp_fc["days_to_threshold"].apply(
                lambda d: f"{d:.1f}" if pd.notna(d) else "—")
            disp_fc["avg_daily_used"] = disp_fc["avg_daily_used"].round(2)
            st.dataframe(
                disp_fc.rename(columns={
                    "factory": "Factory", "material": "Material",
                    "closing_stock": "Closing Stock", "avg_daily_used": "Avg Daily Usage",
                    "threshold": "Reorder Threshold", "days_to_threshold": "Days to Threshold",
                    "projected_reorder_date": "Projected Reorder Date"
                }),
                width='stretch', hide_index=True, height=420
            )
            st.caption("'—' means usage has been flat or zero over the lookback window, so no "
                        "reliable trend could be computed yet.")

    # ── VENDORS (vendor master) ────────────────────────────────────────────
    with tab_proc_vendors:
        st.subheader("🏭 Vendor Master")
        st.caption("39 vendors were pre-loaded from the factory's own RM Daily Stock "
                    "records, mapped to 154 materials with lead times. Emails/phones "
                    "were not in that source data — add them below so 'Notify Vendor' "
                    "can actually send to the right people.")

        _vendors_all = pd.read_sql_query("SELECT * FROM vendors ORDER BY name", conn)
        vm1, vm2, vm3 = st.columns(3)
        vm1.metric("Total Vendors", len(_vendors_all))
        vm2.metric("With Email on File",
                    int((_vendors_all["email"].str.strip() != "").sum()) if not _vendors_all.empty else 0)
        vm3.metric("Materials Mapped",
                    cur.execute("SELECT COUNT(*) FROM vendor_materials").fetchone()[0])

        st.markdown("---")

        sub_view, sub_add, sub_map, sub_perf = st.tabs(
            ["📋 View / Edit Vendors", "➕ Add Vendor", "🔗 Material → Vendor Mapping",
             "📊 Performance"]
        )

        with sub_view:
            if _vendors_all.empty:
                st.info("No vendors yet. Add one in the ➕ Add Vendor tab.")
            else:
                _v_search = search_filter(_vendors_all, "Search vendors", key="vendor_search")
                st.dataframe(
                    _v_search.rename(columns={
                        "name": "Vendor", "email": "Email", "phone": "Phone",
                        "lead_time_days": "Lead Time (days)", "notes": "Notes",
                        "created_at": "Added"
                    }),
                    width='stretch', hide_index=True, height=280
                )

                st.markdown("#### Edit a Vendor")
                _v_names = _vendors_all["name"].tolist()
                _v_sel = st.selectbox("Select vendor", _v_names, key="v_edit_sel")
                _v_row = _vendors_all[_vendors_all["name"] == _v_sel].iloc[0]

                ve1, ve2 = st.columns(2)
                with ve1:
                    _v_email = st.text_input("Email", value=_v_row["email"] or "", key="v_edit_email")
                    _v_phone = st.text_input("Phone", value=_v_row["phone"] or "", key="v_edit_phone")
                with ve2:
                    _v_lead = st.number_input("Lead Time (days)", min_value=0, step=1,
                        value=int(_v_row["lead_time_days"] or 0), key="v_edit_lead")
                    _v_notes = st.text_input("Notes", value=_v_row["notes"] or "", key="v_edit_notes")

                if st.button("💾 Save Vendor", key="v_edit_save"):
                    ok, msg = upsert_vendor(_v_sel, _v_email, _v_phone, _v_lead, _v_notes)
                    (st.success if ok else st.error)(msg)
                    if ok:
                        log_audit("UPDATE", "vendors", _v_sel, "Vendor details updated")
                        st.rerun()

        with sub_add:
            st.markdown("#### Add a New Vendor")
            na1, na2 = st.columns(2)
            with na1:
                new_v_name  = st.text_input("Vendor Name *", key="v_new_name")
                new_v_email = st.text_input("Email", key="v_new_email")
            with na2:
                new_v_phone = st.text_input("Phone", key="v_new_phone")
                new_v_lead  = st.number_input("Lead Time (days)", min_value=0, step=1, key="v_new_lead")
            new_v_notes = st.text_area("Notes", key="v_new_notes")
            if st.button("💾 Add Vendor", key="v_new_save"):
                ok, msg = upsert_vendor(new_v_name, new_v_email, new_v_phone, new_v_lead, new_v_notes)
                (st.success if ok else st.error)(msg)
                if ok:
                    log_audit("INSERT", "vendors", new_v_name.strip(), "New vendor added")
                    st.rerun()

        with sub_map:
            st.markdown("#### Which Vendor Supplies Each Material")
            st.caption("This drives the vendor auto-suggested when a procurement "
                        "request is opened for a material — either automatically "
                        "(low stock) or manually.")

            _vm_all = pd.read_sql_query(
                "SELECT * FROM vendor_materials ORDER BY material", conn)
            _vm_search = search_filter(_vm_all, "Search materials", key="vm_search")
            st.dataframe(
                _vm_search.rename(columns={
                    "material": "Material", "vendor_name": "Vendor",
                    "lead_time_days": "Lead Time (days)", "pack_size": "Pack Size"
                }),
                width='stretch', hide_index=True, height=280
            )

            st.markdown("#### Set / Change a Material's Vendor")
            mm1, mm2 = st.columns(2)
            with mm1:
                mm_material = st.selectbox("Material", MATERIALS, key="mm_material", format_func=material_label)
            with mm2:
                _mm_vendor_names = [r[0] for r in cur.execute(
                    "SELECT name FROM vendors ORDER BY name").fetchall()]
                if _mm_vendor_names:
                    mm_vendor = st.selectbox("Vendor", _mm_vendor_names, key="mm_vendor")
                else:
                    st.info("Add a vendor first in the ➕ Add Vendor tab.")
                    mm_vendor = None
            mm3, mm4 = st.columns(2)
            with mm3:
                mm_lead = st.number_input("Lead Time (days)", min_value=0, step=1, key="mm_lead")
            with mm4:
                mm_pack = st.text_input("Pack Size", key="mm_pack", placeholder="e.g. 25 KG BAG")

            if mm_vendor and st.button("💾 Save Mapping", key="mm_save"):
                set_material_vendor(mm_material, mm_vendor, mm_lead, mm_pack)
                log_audit("UPDATE", "vendor_materials", mm_material, f"vendor={mm_vendor}")
                st.success(f"✅ {mm_material} → {mm_vendor}")
                st.rerun()

        with sub_perf:
            st.markdown("#### Vendor Delivery Performance")
            st.caption("Compares each vendor's promised delivery date (the 'Material Received' "
                        "stage's due date, set from their lead time when the request opens) "
                        "against the date that stage was actually marked Completed. Only "
                        "requests that have reached that stage are counted.")
            perf_df = vendor_performance_summary()
            if perf_df.empty:
                st.info("No completed deliveries yet to score — performance data appears once "
                         "a procurement request's 'Material Received' stage has been marked Completed.")
            else:
                best = perf_df.iloc[0]
                worst = perf_df.iloc[-1]
                pf1, pf2, pf3 = st.columns(3)
                pf1.metric("Vendors Scored", len(perf_df))
                pf2.metric("Most Reliable", best["vendor"], f"{best['on_time_pct']:.0f}% on-time")
                pf3.metric("Needs Attention", worst["vendor"], f"{worst['on_time_pct']:.0f}% on-time")

                if HAS_PLOTLY:
                    fig_vp = px.bar(perf_df, x="vendor", y="on_time_pct",
                                     color="on_time_pct",
                                     color_continuous_scale=["#6E1423", "#D4AF37", "#145C3C"],
                                     range_color=[0, 100], template="plotly_white",
                                     labels={"vendor": "Vendor", "on_time_pct": "On-Time %"})
                    fig_vp.update_layout(height=280, margin=dict(l=10, r=10, t=20, b=10),
                                          showlegend=False, coloraxis_showscale=False)
                    st.plotly_chart(fig_vp, width='stretch')
                else:
                    st.bar_chart(perf_df.set_index("vendor")["on_time_pct"])

                st.dataframe(
                    perf_df.rename(columns={
                        "vendor": "Vendor", "POs": "Completed POs",
                        "on_time_pct": "On-Time %", "avg_delay_days": "Avg Delay (days)"
                    }),
                    width='stretch', hide_index=True, height=260
                )
                st.caption("Negative 'Avg Delay' means deliveries arrived ahead of schedule on average.")

    # ── HISTORY ──────────────────────────────────────────────────────────────
    with tab_proc_history:
        _hq = "SELECT * FROM procurement_requests WHERE status='Closed'"
        _hparams: list = []
        if _proc_factory_filter:
            _hq += " AND factory = ?"
            _hparams.append(_proc_factory_filter)
        _hq += " ORDER BY closed_at DESC LIMIT 200"
        closed_reqs = pd.read_sql_query(_hq, conn, params=_hparams)

        if closed_reqs.empty:
            st.info("No completed procurement requests yet.")
        else:
            st.dataframe(
                closed_reqs[["id", "material", "factory", "trigger_type", "created_at", "closed_at"]]
                    .rename(columns={"id": "PR #", "material": "Material", "factory": "Factory",
                                      "trigger_type": "Trigger", "created_at": "Opened",
                                      "closed_at": "Closed"}),
                width='stretch', hide_index=True, height=420,
            )

    # ── SETTINGS (admin) ────────────────────────────────────────────────────
    with tab_proc_settings:
        if not _is_admin:
            st.info("Reorder thresholds and email alert setup are managed by an administrator.")
        else:
            st.subheader("Reorder Thresholds")
            st.caption("Stock below this level automatically opens a procurement request "
                        f"and emails the purchase department. Default is "
                        f"{DEFAULT_REORDER_THRESHOLD} units where no custom threshold is set.")

            rl1, rl2, rl3 = st.columns(3)
            with rl1:
                rl_factory = st.selectbox("Factory", FACTORIES, key="rl_factory")
            with rl2:
                rl_material = st.selectbox("Material", MATERIALS, key="rl_material", format_func=material_label)
            with rl3:
                rl_threshold = st.number_input(
                    "Reorder Threshold", min_value=0.0, value=float(DEFAULT_REORDER_THRESHOLD),
                    step=1.0, key="rl_threshold")

            if st.button("💾 Save Threshold", key="rl_save"):
                try:
                    cur.execute(
                        "INSERT INTO reorder_levels VALUES (?,?,?) "
                        "ON CONFLICT(material,factory) DO UPDATE SET threshold=excluded.threshold",
                        (rl_material, rl_factory, rl_threshold)
                    )
                    conn.commit()
                    log_audit("UPDATE", "reorder_levels", f"{rl_material}/{rl_factory}",
                               f"threshold={rl_threshold}")
                    st.success("Saved.")
                    st.rerun()
                except sqlite3.Error as e:
                    st.error(f"Database error: {e}")

            existing_rl = pd.read_sql_query(
                "SELECT * FROM reorder_levels ORDER BY factory, material", conn)
            if not existing_rl.empty:
                st.dataframe(
                    existing_rl.rename(columns={
                        "material": "Material", "factory": "Factory", "threshold": "Threshold"}),
                    width='stretch', hide_index=True,
                )
            else:
                st.caption(f"No custom thresholds set yet — the default of "
                            f"{DEFAULT_REORDER_THRESHOLD} applies everywhere.")

            st.markdown("---")
            st.subheader("📧 Email Alerts")

            _transport = _get_smtp_transport()
            if _transport:
                st.success(f"SMTP server configured ({_transport['host']}:{_transport['port']}).")
                _masked_user = _transport['user'] or "(none)"
                _has_pw = "set" if _transport['password'] else "⚠️ NOT set"
                st.caption(f"User: {_masked_user}  ·  Password: {_has_pw}  ·  "
                            f"Sender: {_transport['sender'] or '(none)'}  ·  "
                            f"TLS: {_transport['use_tls']}")
            else:
                st.warning(
                    "SMTP server isn't configured yet — recipients below can still "
                    "be saved, but no mail will actually send until the server is "
                    "set up. Add a `[smtp]` block to `.streamlit/secrets.toml` with "
                    "`host`, `port`, `user`, `password`, `sender`, or set the "
                    "SMTP_HOST / SMTP_PORT / SMTP_USER / SMTP_PASSWORD / SMTP_SENDER "
                    "environment variables — then **restart the app** (secrets/env "
                    "vars are only read at startup, not on every rerun)."
                )

            st.markdown("**Alert Recipients**")
            st.caption("Everyone on this list gets emailed the moment a low-stock "
                        "alert opens a new procurement request.")

            rc1, rc2 = st.columns([3, 1])
            with rc1:
                new_recipient = st.text_input(
                    "Add an email address", placeholder="purchase.team@fcsc.com",
                    key="proc_new_recipient", label_visibility="collapsed")
            with rc2:
                if st.button("➕ Add", key="proc_add_recipient", width='stretch'):
                    ok, msg = add_alert_recipient(new_recipient, st.session_state.username)
                    if ok:
                        log_audit("INSERT", "procurement_recipients", new_recipient.strip().lower(),
                                   f"added by {st.session_state.username}")
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)

            _recipients = get_alert_recipients()
            if not _recipients:
                st.caption("No recipients added yet — alerts won't be emailed to anyone until you add one.")
            else:
                for _email in _recipients:
                    _rcol1, _rcol2 = st.columns([4, 1])
                    _rcol1.markdown(f"✉️ {_email}")
                    if _rcol2.button("Remove", key=f"proc_remove_{_email}"):
                        remove_alert_recipient(_email)
                        log_audit("DELETE", "procurement_recipients", _email,
                                   f"removed by {st.session_state.username}")
                        st.rerun()

            if _recipients and st.button("Send test alert email", key="proc_test_email"):
                ok, msg = send_procurement_alert_email(
                    "TEST MATERIAL", rl_factory, 0, 0, "Units", 0)
                (st.success if ok else st.error)(msg)

            st.markdown("---")
            st.subheader("📱 WhatsApp / SMS Alerts")

            _twilio_cfg = _get_twilio_config()
            if not HAS_REQUESTS:
                st.warning("The `requests` package isn't installed — WhatsApp/SMS sending is "
                            "unavailable until it's added (`pip install requests`).")
            elif _twilio_cfg:
                st.success("Twilio configured.")
                st.caption(f"WhatsApp sender: {_twilio_cfg['whatsapp_from'] or '(not set)'}  ·  "
                            f"SMS sender: {_twilio_cfg['sms_from'] or '(not set)'}")
            else:
                st.warning(
                    "Twilio isn't configured yet — recipients below can still be saved, but "
                    "nothing will actually send until it's set up. Add a `[twilio]` block to "
                    "`.streamlit/secrets.toml` with `account_sid`, `auth_token`, "
                    "`whatsapp_from`, `sms_from`, or set the TWILIO_ACCOUNT_SID / "
                    "TWILIO_AUTH_TOKEN / TWILIO_WHATSAPP_FROM / TWILIO_SMS_FROM environment "
                    "variables — then **restart the app**."
                )

            st.markdown("**Recipients**")
            st.caption("Each recipient picks WhatsApp or SMS, and which alert types they get.")
            wc1, wc2, wc3, wc4 = st.columns([2, 1, 2, 1])
            with wc1:
                wa_phone = st.text_input("Phone", placeholder="+919812345678",
                                          key="wa_new_phone", label_visibility="collapsed")
            with wc2:
                wa_channel = st.selectbox("Channel", ["whatsapp", "sms"], key="wa_new_channel",
                                           label_visibility="collapsed")
            with wc3:
                wa_events = st.multiselect("Alerts", ["low_stock", "ncr"],
                                            default=["low_stock", "ncr"],
                                            key="wa_new_events", label_visibility="collapsed")
            with wc4:
                if st.button("➕ Add", key="wa_add_btn", width='stretch'):
                    ok, msg = add_phone_recipient(wa_phone, wa_channel, wa_events,
                                                   st.session_state.username)
                    if ok:
                        log_audit("INSERT", "whatsapp_recipients", wa_phone.strip(),
                                   f"channel={wa_channel}, events={','.join(wa_events)}")
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)

            _wa_all = pd.read_sql_query("SELECT * FROM whatsapp_recipients ORDER BY phone", conn)
            if _wa_all.empty:
                st.caption("No WhatsApp/SMS recipients added yet.")
            else:
                for _, _r in _wa_all.iterrows():
                    wr1, wr2, wr3 = st.columns([3, 3, 1])
                    wr1.markdown(f"📱 {_r['phone']} ({_r['channel']})")
                    wr2.caption(f"Alerts: {_r['events']}")
                    if wr3.button("Remove", key=f"wa_remove_{_r['phone']}"):
                        remove_phone_recipient(_r["phone"])
                        log_audit("DELETE", "whatsapp_recipients", _r["phone"], "removed")
                        st.rerun()

                if st.button("Send test WhatsApp/SMS", key="wa_test_send"):
                    _results = broadcast_phone_alert(
                        "low_stock",
                        "🔔 FCSC ERP test alert — if you got this, alerts are working.")
                    if not _results:
                        st.info("No recipients are subscribed to 'low_stock' to test with.")
                    for _phone, _ok, _msg in _results:
                        (st.success if _ok else st.error)(f"{_phone}: {_msg}")

            st.markdown("---")
            if st.button("🔄 Re-scan stock levels now", key="proc_rescan"):
                _alerts = scan_low_stock_and_trigger_procurement()
                if _alerts:
                    st.success(f"Scan complete — {len(_alerts)} new request(s) opened.")
                else:
                    st.success("Scan complete — no new low-stock items found.")
                st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
#  QUALITY  (NEW — RM Receipt → Incoming QC → Production Batch → Process QC →
#  FG QC → Packing QC → Dispatch QC, with full batch traceability + NCR/CAPA)
# ─────────────────────────────────────────────────────────────────────────────
elif module == "Quality":

    st.title("🧪 Quality & Batch Traceability")
    st.markdown(
        "<p style='color:#8C7B62;font-size:13px;margin-top:-10px;'>"
        "A batch only advances once the stage before it has passed. "
        "Every inspection is logged and traceable end to end.</p>",
        unsafe_allow_html=True,
    )

    _q_factory_filter = None if _is_admin else _user_factory

    # NOTE: the batch-progress stepper (render_batch_progress) now lives at
    # module (global) level — see near get_batch_traceability() — so the
    # Batch Detail 360° page can reuse it too.

    (tab_incoming, tab_incoming_qc, tab_prod_batch, tab_process_qc,
     tab_fg_qc, tab_packing_qc, tab_dispatch_qc, tab_ncr, tab_trace, tab_qdash) = st.tabs([
        "📥 Incoming Material", "🔍 Incoming QC", "🏭 Production Batch",
        "⚙️ Process QC", "✅ FG QC", "📦 Packing QC", "🚚 Dispatch QC",
        "⚠️ NCR & CAPA", "🧾 Traceability", "📊 Quality Dashboard"
    ])

    # ── STAGE 1: INCOMING MATERIAL (Stores) ─────────────────────────────────
    with tab_incoming:
        st.subheader("Log Incoming Material")
        _vendor_names_q = [r[0] for r in cur.execute("SELECT name FROM vendors ORDER BY name").fetchall()]
        ic1, ic2, ic3 = st.columns(3)
        with ic1:
            im_supplier = st.selectbox("Supplier", ["— Type below —"] + _vendor_names_q, key="im_supplier_pick")
            im_supplier_manual = st.text_input("Or type supplier name", key="im_supplier_manual")
            im_supplier_final = (im_supplier if im_supplier != "— Type below —"
                                  else im_supplier_manual.strip())
            im_po = st.text_input("PO Number", key="im_po")
        with ic2:
            im_material = st.selectbox("Material", MATERIALS, key="im_material", format_func=lab_code_label)
            im_batch_no = st.text_input("Supplier Batch Number", key="im_batch_no")
        with ic3:
            im_qty  = st.number_input("Quantity", min_value=0.0, step=1.0, key="im_qty")
            im_unit = st.selectbox("Unit", ["KG", "Bags", "Litres", "MT", "Barrel", "Units"], key="im_unit")
            im_factory = st.selectbox("Factory", FACTORIES if _is_admin else [_user_factory], key="im_factory")
            im_date = st.date_input("Received Date", key="im_date")

        if st.button("💾 Save — Awaiting QC", key="im_save"):
            if not im_supplier_final or not im_batch_no.strip():
                st.warning("Supplier and batch number are required.")
            else:
                rm_id = create_rm_batch(im_supplier_final, im_po.strip(), im_material,
                                          im_batch_no.strip(), im_qty, im_unit, im_factory, im_date)
                st.success(f"✅ Logged — RM-{rm_id:05d} — status: **Awaiting QC**")
                st.rerun()

        st.markdown("---")
        st.markdown("#### Recent Incoming Material")
        _rm_recent_q = "SELECT * FROM rm_batches" + (" WHERE factory=?" if _q_factory_filter else "") + " ORDER BY id DESC LIMIT 50"
        _rm_recent = pd.read_sql_query(_rm_recent_q, conn,
                                        params=(_q_factory_filter,) if _q_factory_filter else ())
        if _rm_recent.empty:
            st.info("No incoming material logged yet.")
        else:
            def _rm_status_badge(s):
                return {"Awaiting QC": "🟡 Awaiting QC", "Approved": "🟢 Approved", "Rejected": "🔴 Rejected"}.get(s, s)
            _rm_disp = _rm_recent.copy()
            _rm_disp["status"] = _rm_disp["status"].apply(_rm_status_badge)
            st.dataframe(
                _rm_disp[["id","supplier","material","batch_no","quantity","unit","factory","received_date","status"]]
                    .rename(columns={"id":"RM #","supplier":"Supplier","material":"Material",
                                      "batch_no":"Batch No","quantity":"Qty","unit":"Unit",
                                      "factory":"Factory","received_date":"Received","status":"Status"}),
                width='stretch', hide_index=True, height=280
            )

    # ── STAGE 2: INCOMING QC ──────────────────────────────────────────────────
    with tab_incoming_qc:
        st.subheader("Pending Incoming Inspections")
        _pending_q = "SELECT * FROM rm_batches WHERE status='Awaiting QC'" + \
                     (" AND factory=?" if _q_factory_filter else "") + " ORDER BY id"
        _pending_rm = pd.read_sql_query(_pending_q, conn,
                                         params=(_q_factory_filter,) if _q_factory_filter else ())
        if _pending_rm.empty:
            st.success("✅ No pending incoming inspections.")
        else:
            for _, rm in _pending_rm.iterrows():
                with st.expander(f"RM-{rm['id']:05d} — {rm['material']} — {rm['supplier']} "
                                  f"(batch {rm['batch_no']}) @ {rm['factory']}"):
                    qc1, qc2 = st.columns(2)
                    with qc1:
                        _iq_appearance = st.text_input("Appearance", key=f"iq_app_{rm['id']}")
                        _iq_colour     = st.text_input("Colour", key=f"iq_col_{rm['id']}")
                        _iq_moisture   = st.text_input("Moisture", key=f"iq_moi_{rm['id']}")
                    with qc2:
                        _iq_particle   = st.text_input("Particle Size", key=f"iq_par_{rm['id']}")
                        _iq_remarks    = st.text_area("Remarks", key=f"iq_rem_{rm['id']}")
                        _iq_decision   = st.radio("Decision", ["Pass", "Fail"], key=f"iq_dec_{rm['id']}",
                                                    horizontal=True)
                    if st.button("💾 Submit Inspection", key=f"iq_submit_{rm['id']}"):
                        record_incoming_inspection(
                            rm["id"], _iq_appearance, _iq_colour, _iq_moisture, _iq_particle,
                            _iq_remarks, _iq_decision, st.session_state.username
                        )
                        if _iq_decision == "Pass":
                            st.success(f"✅ RM-{rm['id']:05d} Approved — Stores can now issue this material.")
                        else:
                            st.error(f"🔴 RM-{rm['id']:05d} Rejected — blocked, Supplier Return Note generated, NCR raised.")
                        st.rerun()

    # ── STAGE 3: PRODUCTION BATCH ────────────────────────────────────────────
    with tab_prod_batch:
        sub_create, sub_all = st.tabs(["➕ Create Batch", "📋 All Batches"])

        with sub_create:
            st.subheader("Create Production Batch")
            st.caption("Only QC-Approved raw material batches can be selected — this is "
                        "enforced server-side, not just hidden in the dropdown.")

            pcb1, pcb2 = st.columns(2)
            with pcb1:
                pb_product = st.selectbox("Product", FCSC_PRODUCTS, key="pb_product", format_func=fg_label)
                pb_formula = st.text_input("Formula / Recipe reference", key="pb_formula",
                                             placeholder="e.g. TG3.0-STD-v2")
                pb_factory = st.selectbox("Factory", FACTORIES if _is_admin else [_user_factory], key="pb_factory")
            with pcb2:
                pb_operator = st.text_input("Operator", key="pb_operator")
                pb_machine  = st.text_input("Machine", key="pb_machine")
                pb_shift    = st.selectbox("Shift", SHIFTS, key="pb_shift")

            st.caption("Output quantity (optional, but needed for an accurate Dispatch ↔ "
                       "Quality reconciliation later — without it, dispatches linked to this "
                       "batch can only be checked with a weaker fallback).")
            pqc1, pqc2 = st.columns(2)
            with pqc1:
                pb_out_qty = st.number_input("Output Quantity", min_value=0.0, step=1.0,
                                              value=0.0, key="pb_out_qty")
            with pqc2:
                pb_out_unit = st.selectbox(
                    "Output Unit", ["Bags", "Pieces", "Drums", "KG", "MT"], key="pb_out_unit")

            _pb_bom = get_active_bom(pb_product)
            if _pb_bom:
                st.info(f"📐 Formula on file: **{_pb_bom['version']}** "
                        f"({_pb_bom['formula_code'] or 'no code'}) — reference batch "
                        f"{_pb_bom['batch_size']:g} {_pb_bom['batch_unit']}. See the "
                        f"Formulation module to check required quantities for this run.")

            _approved_rm = pd.read_sql_query(
                "SELECT id, material, batch_no, quantity, unit FROM rm_batches "
                "WHERE status='Approved'" + (" AND factory=?" if _q_factory_filter else "") + " ORDER BY id DESC",
                conn, params=(_q_factory_filter,) if _q_factory_filter else ()
            )
            if _approved_rm.empty:
                st.warning("No QC-Approved raw material batches available yet — "
                            "nothing can be selected for production.")
                _selected_rm_ids = []
                _qty_used_map = {}
            else:
                _rm_opts = {
                    f"RM-{r['id']:05d} — {r['material']} (batch {r['batch_no']}, {r['quantity']} {r['unit']} avail.)": r["id"]
                    for _, r in _approved_rm.iterrows()
                }
                _picked_labels = st.multiselect("Raw Materials Used (Approved only)",
                                                  list(_rm_opts.keys()), key="pb_rm_pick")
                _selected_rm_ids = [_rm_opts[l] for l in _picked_labels]
                _qty_used_map = {}
                if _selected_rm_ids:
                    st.caption("Quantity used from each selected batch:")
                    for rid in _selected_rm_ids:
                        _label = next(l for l, v in _rm_opts.items() if v == rid)
                        _qty_used_map[rid] = st.number_input(
                            _label, min_value=0.0, step=1.0, key=f"pb_qty_{rid}")

            if st.button("🚀 Create Batch", key="pb_create"):
                if not pb_operator.strip():
                    st.warning("Operator is required.")
                elif not _selected_rm_ids:
                    st.warning("Select at least one QC-Approved raw material batch.")
                else:
                    pb_id, result = create_production_batch(
                        pb_product, pb_formula.strip(), pb_factory, pb_operator.strip(),
                        pb_machine.strip(), pb_shift, _selected_rm_ids, _qty_used_map,
                        quantity=(pb_out_qty if pb_out_qty > 0 else None),
                        quantity_unit=(pb_out_unit if pb_out_qty > 0 else "")
                    )
                    if pb_id is None:
                        st.error(result)
                    else:
                        st.success(f"✅ Batch **{result}** created — status: **Production Started**")
                        st.rerun()

        with sub_all:
            st.subheader("All Production Batches")
            _pb_q = "SELECT * FROM production_batches" + \
                    (" WHERE factory=?" if _q_factory_filter else "") + " ORDER BY id DESC LIMIT 100"
            _pb_all = pd.read_sql_query(_pb_q, conn, params=(_q_factory_filter,) if _q_factory_filter else ())
            if _pb_all.empty:
                st.info("No production batches yet.")
            else:
                for _, pb in _pb_all.iterrows():
                    with st.expander(f"{pb['batch_no']} — {fg_label(pb['product'])} @ {pb['factory']} — {pb['status']}"):
                        if st.button("🔍 Open Batch 360° page →", key=f"batch360_{pb['id']}"):
                            open_detail_view("batch", pb["batch_no"])
                        render_batch_progress(pb["status"])
                        st.caption(f"Operator: {pb['operator']} · Machine: {pb['machine']} · "
                                    f"Shift: {pb['shift']} · Created: {pb['created_at'][:16]}")
                        _mats_used = pd.read_sql_query(
                            "SELECT r.material, r.batch_no, pbm.qty_used, r.unit FROM production_batch_materials pbm "
                            "JOIN rm_batches r ON r.id = pbm.rm_batch_id WHERE pbm.production_batch_id = ?",
                            conn, params=(pb["id"],)
                        )
                        if not _mats_used.empty:
                            st.markdown("**Raw Materials Used (traceability):**")
                            st.dataframe(
                                _mats_used.rename(columns={"material":"Material","batch_no":"RM Batch",
                                                             "qty_used":"Qty Used","unit":"Unit"}),
                                width='stretch', hide_index=True
                            )

    # ── STAGE 4: PROCESS QC ──────────────────────────────────────────────────
    with tab_process_qc:
        st.subheader("Pending Process QC")
        _proc_q = "SELECT * FROM production_batches WHERE status='Production Started'" + \
                   (" AND factory=?" if _q_factory_filter else "") + " ORDER BY id"
        _proc_pending = pd.read_sql_query(_proc_q, conn, params=(_q_factory_filter,) if _q_factory_filter else ())
        if _proc_pending.empty:
            st.success("✅ No batches awaiting Process QC.")
        else:
            for _, pb in _proc_pending.iterrows():
                with st.expander(f"{pb['batch_no']} — {fg_label(pb['product'])} @ {pb['factory']}"):
                    pq1, pq2 = st.columns(2)
                    with pq1:
                        _pq_visc = st.text_input("Viscosity", key=f"pq_visc_{pb['id']}")
                        _pq_dens = st.text_input("Density", key=f"pq_dens_{pb['id']}")
                    with pq2:
                        _pq_temp = st.text_input("Temperature", key=f"pq_temp_{pb['id']}")
                        _pq_app  = st.text_input("Appearance", key=f"pq_app_{pb['id']}")
                    _pq_remarks = st.text_area("Remarks", key=f"pq_rem_{pb['id']}")
                    _pq_decision = st.radio("Decision", ["Pass", "Fail"], key=f"pq_dec_{pb['id']}", horizontal=True)
                    if st.button("💾 Submit", key=f"pq_submit_{pb['id']}"):
                        record_process_inspection(pb["id"], _pq_visc, _pq_dens, _pq_temp,
                                                    _pq_app, _pq_remarks, _pq_decision, st.session_state.username)
                        if _pq_decision == "Pass":
                            st.success(f"✅ {pb['batch_no']} → Process QC Passed")
                        else:
                            st.error(f"🛑 {pb['batch_no']} → On Hold — NCR raised")
                        st.rerun()

    # ── STAGE 5: FINISHED GOODS QC ───────────────────────────────────────────
    with tab_fg_qc:
        st.subheader("Pending Finished Goods QC")
        _fg_q = "SELECT * FROM production_batches WHERE status='Process QC Passed'" + \
                 (" AND factory=?" if _q_factory_filter else "") + " ORDER BY id"
        _fg_pending = pd.read_sql_query(_fg_q, conn, params=(_q_factory_filter,) if _q_factory_filter else ())
        if _fg_pending.empty:
            st.success("✅ No batches awaiting Finished Goods QC.")
        else:
            for _, pb in _fg_pending.iterrows():
                with st.expander(f"{pb['batch_no']} — {fg_label(pb['product'])} @ {pb['factory']}"):
                    fg1, fg2 = st.columns(2)
                    with fg1:
                        _fg_adh = st.text_input("Adhesion", key=f"fg_adh_{pb['id']}")
                        _fg_str = st.text_input("Strength", key=f"fg_str_{pb['id']}")
                        _fg_con = st.text_input("Consistency", key=f"fg_con_{pb['id']}")
                    with fg2:
                        _fg_col = st.text_input("Colour", key=f"fg_col_{pb['id']}")
                        _fg_wt  = st.text_input("Weight", key=f"fg_wt_{pb['id']}")
                    _fg_decision = st.radio("Decision", ["Pass", "Fail"], key=f"fg_dec_{pb['id']}", horizontal=True)
                    if st.button("💾 Submit", key=f"fg_submit_{pb['id']}"):
                        record_fg_inspection(pb["id"], _fg_adh, _fg_str, _fg_con, _fg_col, _fg_wt,
                                              _fg_decision, st.session_state.username)
                        if _fg_decision == "Pass":
                            st.success(f"✅ {pb['batch_no']} → FG QC Passed")
                        else:
                            st.error(f"🛑 {pb['batch_no']} → Rejected — NCR raised")
                        st.rerun()

    # ── STAGE 6: PACKING QC ──────────────────────────────────────────────────
    with tab_packing_qc:
        st.subheader("Pending Packing QC")
        _pk_q = "SELECT * FROM production_batches WHERE status='FG QC Passed'" + \
                 (" AND factory=?" if _q_factory_filter else "") + " ORDER BY id"
        _pk_pending = pd.read_sql_query(_pk_q, conn, params=(_q_factory_filter,) if _q_factory_filter else ())
        if _pk_pending.empty:
            st.success("✅ No batches awaiting Packing QC.")
        else:
            for _, pb in _pk_pending.iterrows():
                with st.expander(f"{pb['batch_no']} — {fg_label(pb['product'])} @ {pb['factory']}"):
                    pk1, pk2 = st.columns(2)
                    with pk1:
                        _pk_bag   = st.checkbox("Correct Bag", key=f"pk_bag_{pb['id']}")
                        _pk_label = st.checkbox("Correct Label", key=f"pk_lab_{pb['id']}")
                    with pk2:
                        _pk_batch = st.checkbox("Correct Batch", key=f"pk_bat_{pb['id']}")
                        _pk_wt_ok = st.checkbox("Net Weight OK", key=f"pk_wt_{pb['id']}")
                        _pk_seal  = st.checkbox("Seal Quality OK", key=f"pk_seal_{pb['id']}")
                    if st.button("💾 Submit", key=f"pk_submit_{pb['id']}"):
                        record_packing_inspection(pb["id"], _pk_bag, _pk_label, _pk_batch,
                                                    _pk_wt_ok, _pk_seal, st.session_state.username)
                        if all([_pk_bag, _pk_label, _pk_batch, _pk_wt_ok, _pk_seal]):
                            st.success(f"✅ {pb['batch_no']} → Packing QC Passed")
                        else:
                            st.error(f"🛑 {pb['batch_no']} → Rework — NCR raised")
                        st.rerun()

    # ── STAGE 7: DISPATCH QC (PDI) ───────────────────────────────────────────
    with tab_dispatch_qc:
        st.subheader("Pending Pre-Dispatch Inspection (PDI)")
        _pdi_q = "SELECT * FROM production_batches WHERE status='Packing QC Passed'" + \
                  (" AND factory=?" if _q_factory_filter else "") + " ORDER BY id"
        _pdi_pending = pd.read_sql_query(_pdi_q, conn, params=(_q_factory_filter,) if _q_factory_filter else ())
        if _pdi_pending.empty:
            st.info("No batches awaiting PDI.")
        else:
            for _, pb in _pdi_pending.iterrows():
                with st.expander(f"{pb['batch_no']} — {fg_label(pb['product'])} @ {pb['factory']}"):
                    _pdi_done = st.checkbox("PDI Completed?", key=f"pdi_{pb['id']}")
                    if st.button("💾 Submit", key=f"pdi_submit_{pb['id']}"):
                        record_dispatch_approval(pb["id"], _pdi_done, st.session_state.username)
                        if _pdi_done:
                            st.success(f"✅ {pb['batch_no']} → Dispatch Approved")
                        else:
                            st.error(f"🛑 {pb['batch_no']} → Dispatch Blocked")
                        st.rerun()

        st.markdown("---")
        st.subheader("Cleared for Dispatch")
        _cleared_q = "SELECT * FROM production_batches WHERE status='Dispatch Approved'" + \
                      (" AND factory=?" if _q_factory_filter else "") + " ORDER BY id"
        _cleared = pd.read_sql_query(_cleared_q, conn, params=(_q_factory_filter,) if _q_factory_filter else ())
        if _cleared.empty:
            st.caption("No batches currently cleared and waiting to leave the factory.")
        else:
            for _, pb in _cleared.iterrows():
                ccol1, ccol2 = st.columns([4, 1])
                ccol1.markdown(
                    f"{status_pill('Cleared', 'success')} &nbsp; "
                    f"<code style='font-size:12.5px;'>{pb['batch_no']}</code> — "
                    f"{fg_label(pb['product'])} @ {pb['factory']}",
                    unsafe_allow_html=True
                )
                if ccol2.button("🚚 Mark Dispatched", key=f"dispatched_{pb['id']}"):
                    mark_batch_dispatched(pb["id"])
                    st.success(f"{pb['batch_no']} marked Dispatched.")
                    st.rerun()

    # ── NCR & CAPA ────────────────────────────────────────────────────────────
    with tab_ncr:
        st.subheader("⚠️ Non-Conformance Records & Corrective Actions")
        _ncr_open = pd.read_sql_query(
            "SELECT * FROM ncr_capa WHERE status='Open' ORDER BY raised_at DESC", conn)
        if _ncr_open.empty:
            st.success("✅ No open NCRs.")
        else:
            for _, ncr in _ncr_open.iterrows():
                with st.expander(f"NCR-{ncr['id']:04d} — {ncr['source_stage']} — batch {ncr['batch_no']}"):
                    st.markdown(status_pill(f"{ncr['source_stage']} QC", "error"), unsafe_allow_html=True)
                    st.caption(f"Raised by {ncr['raised_by']} on {ncr['raised_at'][:16]}")
                    st.write(ncr["description"])
                    _capa_text = st.text_area("Corrective Action", key=f"capa_{ncr['id']}")
                    if st.button("✅ Close NCR", key=f"capa_close_{ncr['id']}"):
                        cur.execute(
                            "UPDATE ncr_capa SET corrective_action=?, status='Closed', closed_at=? WHERE id=?",
                            (_capa_text, _now_iso(), ncr["id"])
                        )
                        conn.commit()
                        log_audit("UPDATE", "ncr_capa", ncr["id"], "NCR closed")
                        st.success("NCR closed.")
                        st.rerun()

        st.markdown("---")
        st.markdown("#### Closed NCRs (recent)")
        _ncr_closed = pd.read_sql_query(
            "SELECT * FROM ncr_capa WHERE status='Closed' ORDER BY closed_at DESC LIMIT 30", conn)
        if _ncr_closed.empty:
            st.caption("None yet.")
        else:
            st.dataframe(
                _ncr_closed[["id","source_stage","batch_no","description","corrective_action","closed_at"]]
                    .rename(columns={"id":"NCR #","source_stage":"Stage","batch_no":"Batch",
                                      "description":"Issue","corrective_action":"Corrective Action",
                                      "closed_at":"Closed"}),
                width='stretch', hide_index=True, height=260
            )

    # ── QUALITY DASHBOARD ────────────────────────────────────────────────────
    with tab_trace:
        st.subheader("🧾 Batch Traceability Certificate")
        st.caption("Pulls RM receipt, incoming QC, process QC, FG QC, packing QC and dispatch "
                    "approval for one batch into a single report — for a customer audit, a "
                    "recall, or just answering 'what happened to this batch?' in one place.")

        _all_batch_nos = [r[0] for r in cur.execute(
            "SELECT batch_no FROM production_batches ORDER BY id DESC").fetchall()]
        if not _all_batch_nos:
            st.info("No production batches yet.")
        else:
            trace_batch_no = st.selectbox("Select batch number", _all_batch_nos, key="trace_batch_sel")
            if st.button("🔍 Open as full Batch 360° page →", key="trace_open_360"):
                open_detail_view("batch", trace_batch_no)
            trace = get_batch_traceability(trace_batch_no)

            if trace is None:
                st.error("Batch not found.")
            else:
                b = trace["batch"]
                tc1, tc2, tc3, tc4 = st.columns(4)
                tc1.metric("Product", fg_label(b["product"]))
                tc2.metric("Factory", b["factory"])
                tc3.metric("Status", b["status"])
                tc4.metric("Operator", b["operator"])

                st.markdown("#### Raw Materials Used")
                if trace["materials"].empty:
                    st.caption("No raw materials linked yet.")
                else:
                    st.dataframe(
                        trace["materials"].rename(columns={
                            "material": "Material", "rm_batch_no": "RM Batch No.",
                            "supplier": "Supplier", "received_date": "Received",
                            "qty_used": "Qty Used", "incoming_decision": "Incoming QC"
                        }),
                        width='stretch', hide_index=True
                    )

                st.markdown("#### QC Stage Results")
                _stage_labels = [("Process QC", "process_qc"), ("FG QC", "fg_qc"),
                                  ("Packing QC", "packing_qc"), ("Dispatch QC", "dispatch_qc")]
                for _label, _key in _stage_labels:
                    _rec = trace[_key]
                    with st.expander(_label, expanded=False):
                        if not _rec:
                            st.caption("Not yet recorded.")
                        else:
                            _show = {k: v for k, v in _rec.items()
                                     if k not in ("id", "production_batch_id")}
                            st.table(pd.DataFrame(_show.items(), columns=["Field", "Value"]))

                if not trace["ncrs"].empty:
                    st.markdown("#### Non-Conformance Reports")
                    st.dataframe(
                        trace["ncrs"][["source_stage", "description", "status", "raised_at"]]
                            .rename(columns={"source_stage": "Stage", "description": "Description",
                                              "status": "Status", "raised_at": "Raised"}),
                        width='stretch', hide_index=True
                    )

                st.markdown("---")
                tcol1, tcol2 = st.columns(2)
                with tcol1:
                    if HAS_REPORTLAB:
                        pdf_bytes = generate_traceability_pdf(trace)
                        st.download_button(
                            "📥 Download Traceability Certificate (PDF)",
                            data=pdf_bytes,
                            file_name=f"FCSC_Traceability_{trace_batch_no}.pdf",
                            mime="application/pdf",
                        )
                    else:
                        st.warning("Install `reportlab` (pip install reportlab) to enable PDF export.")
                with tcol2:
                    if HAS_QRCODE:
                        qr_png = generate_batch_qr_png(trace_batch_no)
                        st.image(qr_png, width=140, caption=f"Batch {trace_batch_no}")
                        st.caption("Print this on the bag label. It encodes the batch number — "
                                    "whoever scans it can type it into this tab to pull up the report.")
                    else:
                        st.warning("Install `qrcode` (pip install qrcode[pil]) to enable QR codes.")

    with tab_qdash:
        st.subheader("📊 Quality Dashboard")

        _all_rm = pd.read_sql_query("SELECT * FROM rm_batches", conn)
        _all_pb = pd.read_sql_query("SELECT * FROM production_batches", conn)

        qd1, qd2, qd3, qd4 = st.columns(4)
        qd1.metric("RM Batches Received", len(_all_rm))
        _rm_rejected = len(_all_rm[_all_rm["status"] == "Rejected"]) if not _all_rm.empty else 0
        qd2.metric("Incoming Rejection Rate",
                    f"{(_rm_rejected/len(_all_rm)*100):.1f}%" if not _all_rm.empty else "—")
        qd3.metric("Production Batches", len(_all_pb))
        _open_ncr_count = cur.execute("SELECT COUNT(*) FROM ncr_capa WHERE status='Open'").fetchone()[0]
        qd4.metric("Open NCRs", _open_ncr_count)

        st.markdown("---")
        st.markdown("#### Batches by Current Status")
        if not _all_pb.empty:
            _status_counts = _all_pb["status"].value_counts().reset_index()
            _status_counts.columns = ["Status", "Count"]
            if HAS_PLOTLY:
                fig_qc = px.bar(_status_counts, x="Status", y="Count",
                                 color_discrete_sequence=["#6E1423"],
                                 template="plotly_white", title="Batches by Status")
                fig_qc.update_layout(height=260, margin=dict(l=10,r=10,t=36,b=10))
                st.plotly_chart(fig_qc, width='stretch')
            else:
                st.dataframe(_status_counts, width='stretch', hide_index=True)
        else:
            st.info("No production batches yet.")

        st.markdown("#### Pass/Fail by Stage")
        _stage_tables = [
            ("Incoming",  "incoming_inspection"),
            ("Process",   "process_inspection"),
            ("FG",        "fg_inspection"),
            ("Packing",   "packing_inspection"),
        ]
        _stage_rows = []
        for _label, _tbl in _stage_tables:
            _passed = cur.execute(f"SELECT COUNT(*) FROM {_tbl} WHERE decision='Pass'").fetchone()[0]
            _failed = cur.execute(f"SELECT COUNT(*) FROM {_tbl} WHERE decision='Fail'").fetchone()[0]
            _stage_rows.append({"Stage": _label, "Pass": _passed, "Fail": _failed})
        _stage_df = pd.DataFrame(_stage_rows)
        if HAS_PLOTLY and _stage_df[["Pass","Fail"]].sum().sum() > 0:
            fig_stage = px.bar(_stage_df.melt(id_vars="Stage", value_vars=["Pass","Fail"],
                                                var_name="Result", value_name="Count"),
                                 x="Stage", y="Count", color="Result", barmode="group",
                                 color_discrete_map={"Pass":"#145C3C","Fail":"#6E1423"},
                                 template="plotly_white")
            fig_stage.update_layout(height=260, margin=dict(l=10,r=10,t=36,b=10),
                                      legend=dict(orientation="h", y=-0.25))
            st.plotly_chart(fig_stage, width='stretch')
        else:
            st.dataframe(_stage_df, width='stretch', hide_index=True)


# ─────────────────────────────────────────────────────────────────────────────
#  DISPATCH  (renamed from Sales — delivery & payment tracking)
# ─────────────────────────────────────────────────────────────────────────────
elif module == "Dispatch":

    st.title("🚚 Dispatch")
    tab_entry, tab_log, tab_edit_sl = st.tabs(["➕ Add Dispatch", "📋 Records", "✏️ Edit Record"])

    with tab_entry:
        st.subheader("New Dispatch Entry")
        c1, c2, c3 = st.columns(3)
        with c1:
            sl_date    = st.date_input("Date", key="sl_d")
            sl_factory = st.selectbox("Factory", FACTORIES, key="sl_f",
                                       index=FACTORIES.index(factory) if factory in FACTORIES else 0)
            # Customer dropdown from master, with manual fallback
            _sl_cust_opts = ["— Type below —"] + CUSTOMER_LIST
            _sl_cust_pick = st.selectbox("Customer (from master)", _sl_cust_opts, key="sl_cust_pick")
            sl_cust_manual = st.text_input("Or enter new customer name", key="sl_cust_manual",
                                            placeholder="New / one-time customer")
            sl_cust = _sl_cust_pick if _sl_cust_pick != "— Type below —" else sl_cust_manual.strip()
        with c2:
            sl_product    = st.selectbox("Product", FCSC_PRODUCTS, key="sl_p_sel", format_func=fg_label)
            sl_custom_prd = st.text_input("Custom name (if 'Other / Custom')", key="sl_p_cust")
            sl_qty        = st.number_input("Qty", min_value=0, step=1, key="sl_q")
            sl_price      = st.number_input("Unit Price (₹)", min_value=0.0, step=0.01,
                                             format="%.2f", key="sl_p")
            # Optional link to a QC-cleared batch, for Dispatch <-> Quality
            # reconciliation. Purely optional — leaving it unset just means
            # that reconciliation falls back to a factory+product proxy match.
            _sl_batch_opts = pd.read_sql_query(
                "SELECT id, batch_no, product FROM production_batches "
                "WHERE factory=? AND status IN ('Dispatch Approved','Dispatched') "
                "ORDER BY id DESC LIMIT 50", conn, params=(sl_factory,)
            )
            _sl_batch_map = {"— None / not batch-tracked —": None}
            _sl_batch_map.update({
                f"{r['batch_no']} ({r['product']})": r["id"] for _, r in _sl_batch_opts.iterrows()
            })
            sl_batch_label = st.selectbox("Link to QC Batch (optional)", list(_sl_batch_map.keys()),
                                           key="sl_batch_link",
                                           help="Links this dispatch to a QC-cleared production batch "
                                                "for accurate Dispatch <-> Quality reconciliation.")
            sl_batch_id = _sl_batch_map[sl_batch_label]
        with c3:
            sl_status   = st.selectbox("Payment Status",
                                        ["Paid","Pending","Partial","Overdue"], key="sl_s")
            sl_challan  = st.text_input("Challan No.", placeholder="e.g. CH-2025-001",
                                        key="sl_challan")
            sl_gstin    = st.text_input("Customer GSTIN", placeholder="22AAAAA0000A1Z5",
                                        key="sl_gstin")
            sl_hsn      = st.text_input("HSN Code", placeholder="e.g. 3214",
                                        key="sl_hsn")
            sl_gst_rate = st.selectbox("GST Rate (%)", GST_RATES,
                                        index=GST_RATES.index(18.0), key="sl_gst_rate")
            sl_total    = sl_qty * sl_price
            sl_tax_amt  = round(sl_total * sl_gst_rate / 100, 2)
            sl_grand    = sl_total + sl_tax_amt
            gc1, gc2 = st.columns(2)
            gc1.metric("Taxable Amount", fmt_inr(sl_total))
            gc2.metric(f"Total incl. GST {sl_gst_rate}%", fmt_inr(sl_grand))

        if st.button("💾 Save Dispatch"):
            final_sl_product = (sl_custom_prd.strip()
                                if sl_product == "Other / Custom" and sl_custom_prd.strip()
                                else sl_product)
            if not sl_cust.strip() or not final_sl_product or final_sl_product == "Other / Custom":
                st.warning("Customer and product are required.")
            else:
                dup = pd.read_sql_query(
                    "SELECT id FROM sales WHERE date=? AND factory=? AND customer=? AND product=?",
                    conn, params=(str(sl_date), sl_factory, sl_cust.strip(), final_sl_product)
                )
                if not dup.empty:
                    st.warning(
                        f"⚠️ A dispatch of **{final_sl_product}** to **{sl_cust}** at "
                        f"**{sl_factory}** on **{sl_date}** already exists. "
                        f"Use the ✏️ Edit tab to modify it."
                    )
                else:
                    # Dispatch -> FG Stock OUT (Section 4 of the reconciliation spec):
                    # flag/require override rather than silently allowing negative
                    # FG stock, since a genuine backdated correction is legitimate.
                    _sl_available = get_fg_closing_stock(sl_factory, final_sl_product)
                    _sl_override_needed = sl_qty > _sl_available
                    _sl_proceed = True
                    if _sl_override_needed:
                        st.error(
                            f"🚨 **Dispatch exceeds available FG stock** — "
                            f"{final_sl_product} @ {sl_factory}: available {_sl_available:,.2f}, "
                            f"dispatching {sl_qty:,.2f}. This will push FG stock negative."
                        )
                        _sl_proceed = st.checkbox(
                            "Proceed anyway (e.g. backdated entry, opening stock not yet logged)",
                            key="sl_force_negative"
                        )
                    if not _sl_proceed:
                        st.stop()
                    try:
                        cur.execute(
                            "INSERT INTO sales(date,factory,customer,product,qty,price,total,"
                            "status,challan_no,gstin,hsn_code,gst_rate,production_batch_id)"
                            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (str(sl_date), sl_factory, sl_cust,
                             final_sl_product, sl_qty, sl_price, round(sl_total, 2),
                             sl_status, sl_challan.strip(),
                             sl_gstin.strip(), sl_hsn.strip(), sl_gst_rate, sl_batch_id)
                        )
                        conn.commit()
                        _new_sale_id = cur.lastrowid
                        log_audit("INSERT", "sales", "new",
                                  f"{sl_factory} | {final_sl_product} | {sl_cust} | {fmt_inr(sl_total)} | {sl_status}")
                        _new_fg_closing = record_fg_stock_movement(
                            sl_date, sl_factory, final_sl_product,
                            dispatch_out=sl_qty, source_module="Dispatch",
                            source_ref_id=_new_sale_id
                        )
                        st.success(f"✅ Dispatch saved — {fmt_inr(sl_total)} | {sl_cust} | {sl_status} | "
                                   f"FG Stock now {_new_fg_closing:,.2f}")
                        st.rerun()
                    except sqlite3.Error as e:
                        st.error(f"Database error: {e}")

    with tab_log:
        st.subheader("Dispatch Records")
        if sales_df.empty:
            st.info("No dispatch records for this factory / date range.")
        else:
            rev  = sales_df["total"].sum()
            pend = sales_df[sales_df["status"].isin(["Pending","Overdue"])]["total"].sum() \
                   if "status" in sales_df.columns else 0
            k1, k2, k3 = st.columns(3)
            k1.metric("Dispatched Value (Range)", fmt_inr(rev))
            k2.metric("Dispatch Orders",          len(sales_df))
            k3.metric("Avg Order",                fmt_inr(rev / len(sales_df)))

            disp = sales_df.copy()
            disp["total"] = disp["total"].apply(fmt_inr)
            disp["price"] = disp["price"].apply(fmt_inr)
            if "product" in disp.columns:
                disp.insert(disp.columns.get_loc("product") + 1, "RM Code",
                            disp["product"].apply(get_fg_code))

            disp = search_filter(disp, "Search sales records", key="sales_search")
            disp = paginate_df(disp, key="sales_page")
            st.dataframe(disp.drop(columns=["id"], errors="ignore"),
                         width='stretch', hide_index=True, height=320)

            def _on_dispatch_deleted(_row) -> None:
                # Section 8: deleting a Dispatch record must not leave an
                # orphaned FG stock movement behind.
                _closing = reverse_fg_stock_for_source(
                    _row["factory"], _row["product"], "Dispatch", int(_row["id"]))
                if _closing is not None:
                    log_audit("REVERSE", "fg_stock", int(_row["id"]),
                              f"Dispatch #{int(_row['id'])} deleted — FG stock movement "
                              f"reversed | {_row['factory']} | {_row['product']} | "
                              f"FG stock now {_closing:,.2f}")

            delete_row_ui(sales_df, "sales", "customer", "sales",
                           on_delete=_on_dispatch_deleted)

            if HAS_PLOTLY and not sales_df.empty:
                ca, cb = st.columns(2)
                with ca:
                    by_prod = (sales_df.groupby("product")["total"]
                                       .sum().reset_index()
                                       .sort_values("total", ascending=False).head(8))
                    fig = px.bar(by_prod, x="product", y="total",
                                 color_discrete_sequence=["#145C3C"],
                                 template="plotly_white", title="Top Products by Dispatch Value",
                                 labels={"product":"Product","total":"Value (₹)"})
                    fig.update_layout(height=240, margin=dict(l=10,r=10,t=36,b=10))
                    st.plotly_chart(fig, width='stretch')

                with cb:
                    by_cust = (sales_df.groupby("customer")["total"]
                                       .sum().reset_index()
                                       .sort_values("total", ascending=False).head(8))
                    fig_c = px.bar(by_cust, x="customer", y="total",
                                   color_discrete_sequence=["#1E3A5F"],
                                   template="plotly_white", title="Top Customers by Revenue",
                                   labels={"customer":"Customer","total":"Revenue (₹)"})
                    fig_c.update_layout(height=240, margin=dict(l=10,r=10,t=36,b=10))
                    st.plotly_chart(fig_c, width='stretch')

            if "status" in sales_df.columns:
                st.markdown("---")
                st.subheader("Payment Status Breakdown")
                status_grp = (sales_df.groupby("status")["total"]
                              .agg(["sum","count"]).reset_index()
                              .rename(columns={"status":"Status","sum":"Amount","count":"Orders"}))
                status_grp["Amount"] = status_grp["Amount"].apply(fmt_inr)
                st.dataframe(status_grp, width='stretch', hide_index=True)

    with tab_edit_sl:
        st.subheader("Edit a Dispatch Record")
        if sales_df.empty:
            st.info("No records to edit in the current date range.")
        else:
            opts = {
                f"ID {r['id']} — {r['customer']} | {fg_label(r['product'])} ({r['date']})": r["id"]
                for _, r in sales_df.iterrows()
            }
            sel_label = st.selectbox("Select record to edit", list(opts.keys()),
                                      key="sl_edit_sel")
            sel_id  = opts[sel_label]
            sel_row = sales_df[sales_df["id"] == sel_id].iloc[0]

            slc1, slc2, slc3 = st.columns(3)
            with slc1:
                e_sl_date    = st.date_input("Date",
                    value=pd.to_datetime(sel_row["date"]).date(), key="e_sl_d")
                e_sl_factory = st.selectbox("Factory", FACTORIES, key="e_sl_f",
                    index=FACTORIES.index(sel_row["factory"])
                          if sel_row["factory"] in FACTORIES else 0,
                    disabled=not _is_admin)
                e_sl_cust    = st.text_input("Customer",
                    value=sel_row["customer"], key="e_sl_cust")
            with slc2:
                cur_sl_prod_idx = FCSC_PRODUCTS.index(sel_row["product"]) \
                                  if sel_row["product"] in FCSC_PRODUCTS else len(FCSC_PRODUCTS) - 1
                e_sl_product    = st.selectbox("Product", FCSC_PRODUCTS, key="e_sl_p_sel",
                    index=cur_sl_prod_idx, format_func=fg_label)
                e_sl_custom_prd = st.text_input("Custom name (if Other / Custom)",
                    value=sel_row["product"] if sel_row["product"] not in FCSC_PRODUCTS else "",
                    key="e_sl_p_cust")
                e_sl_qty   = st.number_input("Qty",
                    min_value=0, step=1, value=int(sel_row["qty"]), key="e_sl_q")
                e_sl_price = st.number_input("Unit Price (₹)",
                    min_value=0.0, step=0.01, format="%.2f",
                    value=float(sel_row["price"]), key="e_sl_p")
            with slc3:
                _sl_status_opts = ["Paid","Pending","Partial","Overdue"]
                _sl_cur_status  = sel_row.get("status","Paid") or "Paid"
                e_sl_status = st.selectbox("Payment Status", _sl_status_opts,
                    index=_sl_status_opts.index(_sl_cur_status)
                          if _sl_cur_status in _sl_status_opts else 0,
                    key="e_sl_status")
                e_sl_challan   = st.text_input("Challan No.",
                    value=str(sel_row.get("challan_no","") or ""), key="e_sl_challan")
                e_sl_gstin     = st.text_input("Customer GSTIN",
                    value=str(sel_row.get("gstin","") or ""), key="e_sl_gstin")
                e_sl_hsn       = st.text_input("HSN Code",
                    value=str(sel_row.get("hsn_code","") or ""), key="e_sl_hsn")
                _e_sl_gst_cur  = float(sel_row.get("gst_rate", 18.0) or 18.0)
                e_sl_gst_rate  = st.selectbox("GST Rate (%)", GST_RATES,
                    index=GST_RATES.index(_e_sl_gst_cur) if _e_sl_gst_cur in GST_RATES else 2,
                    key="e_sl_gst_rate")
                e_sl_total = e_sl_qty * e_sl_price
                st.metric("Updated Total (excl. GST)", fmt_inr(e_sl_total))

            if st.button("💾 Update Sale", key="sl_upd_btn"):
                final_e_product = (e_sl_custom_prd.strip()
                                   if e_sl_product == "Other / Custom" and e_sl_custom_prd.strip()
                                   else e_sl_product)
                if not e_sl_cust.strip() or not final_e_product or final_e_product == "Other / Custom":
                    st.warning("Customer and product are required.")
                else:
                    try:
                        cur.execute(
                            "UPDATE sales SET date=?,factory=?,customer=?,"
                            "product=?,qty=?,price=?,total=?,status=?,challan_no=?,"
                            "gstin=?,hsn_code=?,gst_rate=? WHERE id=?",
                            (str(e_sl_date), e_sl_factory, e_sl_cust,
                             final_e_product, e_sl_qty, e_sl_price,
                             round(e_sl_total, 2), e_sl_status,
                             e_sl_challan.strip(), e_sl_gstin.strip(),
                             e_sl_hsn.strip(), e_sl_gst_rate, sel_id)
                        )
                        conn.commit()
                        log_audit("UPDATE", "sales", sel_id,
                                  f"{e_sl_factory} | {final_e_product} | {e_sl_cust} | {fmt_inr(e_sl_total)} | {e_sl_status}")
                        # Section 8: an edit must correct FG Stock too — reverse the
                        # old dispatch-out movement (posted under the *old*
                        # factory/product, in case those changed) then apply the new
                        # one, so the final FG impact reflects only the new quantity.
                        reverse_fg_stock_for_source(
                            sel_row["factory"], sel_row["product"], "Dispatch", int(sel_id))
                        _e_sl_fg_closing = record_fg_stock_movement(
                            e_sl_date, e_sl_factory, final_e_product,
                            dispatch_out=e_sl_qty, source_module="Dispatch",
                            source_ref_id=int(sel_id), movement_type="Correction"
                        )
                        st.success(f"✅ Sale record updated — FG Stock for {final_e_product} "
                                   f"@ {e_sl_factory} now {_e_sl_fg_closing:,.2f}.")
                        if _e_sl_fg_closing < 0:
                            st.warning(
                                "⚠️ This edit has pushed FG stock negative for "
                                f"{final_e_product} @ {e_sl_factory}. Review the dispatch "
                                "quantity or log the missing opening/production stock."
                            )
                        st.rerun()
                    except sqlite3.Error as e:
                        st.error(f"Database error: {e}")


# ─────────────────────────────────────────────────────────────────────────────
#  RECONCILIATION  (NEW — Stock <-> Production <-> QC <-> Dispatch verification)
# ─────────────────────────────────────────────────────────────────────────────
elif module == "Reconciliation":

    st.title("🔎 Inventory Reconciliation")
    st.caption("Cross-checks Stock, Production, QC and Dispatch against each other. "
               "Nothing here ever edits a source record — mismatches are logged and "
               "surfaced for investigation, never auto-corrected.")

    rc_f1, rc_f2 = st.columns([1, 1])
    with rc_f1:
        rc_fac = st.selectbox("Factory", [ALL_FACTORIES] + FACTORIES, key="rc_fac",
                               index=([ALL_FACTORIES] + FACTORIES).index(factory)
                               if factory in ([ALL_FACTORIES] + FACTORIES) else 0)
    with rc_f2:
        rc_days = st.selectbox("Period", [7, 14, 30, 90], index=2, key="rc_days",
                                format_func=lambda d: f"Last {d} days")
    rc_end   = datetime.date.today()
    rc_start = rc_end - datetime.timedelta(days=rc_days)

    if st.button("▶️ Run Reconciliation", type="primary", key="rc_run"):
        with st.spinner("Running checks..."):
            _rc_results = run_all_reconciliations(
                rc_start, rc_end, rc_fac if rc_fac != ALL_FACTORIES else None
            )
        st.session_state["rc_last_run"] = _rc_results
        st.session_state["rc_last_run_at"] = _now_iso()
        log_audit("RUN", "inventory_reconciliation", "manual",
                  f"Reconciliation run by {st.session_state.get('username')} | "
                  f"{rc_fac} | {rc_start} to {rc_end}")
        st.rerun()

    tab_summary, tab_history = st.tabs(["📊 Latest Run", "📜 Full History"])

    with tab_summary:
        _rc_last = st.session_state.get("rc_last_run")
        if not _rc_last:
            st.info("No reconciliation run yet this session — click **▶️ Run Reconciliation** above.")
        else:
            st.caption(f"Last run: {st.session_state.get('rc_last_run_at', '—')}")
            _rc_summary_rows = []
            for _check_name, _results in _rc_last.items():
                for _r in _results:
                    _rc_summary_rows.append({
                        "Verification": _check_name,
                        "Check Type": _r["check_type"],
                        "Factory": _r["factory"],
                        "Item": _r["item_code"],
                        "Source A": _r["qty_a"],
                        "Source B": _r["qty_b"],
                        "Difference": _r["difference"],
                        "Status": {"Matched": "✅ Matched", "Mismatch": "⚠️ Mismatch",
                                   "Critical": "🚨 Critical"}[_r["severity"]],
                        "Detail": _r.get("detail", ""),
                        "Checked At": _r.get("checked_at", ""),
                    })
            if not _rc_summary_rows:
                st.info("No transactions found in this period/factory to reconcile.")
            else:
                _rc_df = pd.DataFrame(_rc_summary_rows)
                rk1, rk2, rk3, rk4 = st.columns(4)
                rk1.metric("Checks Run", len(_rc_df))
                rk2.metric("✅ Matched", int((_rc_df["Status"] == "✅ Matched").sum()))
                rk3.metric("⚠️ Mismatch", int((_rc_df["Status"] == "⚠️ Mismatch").sum()))
                rk4.metric("🚨 Critical", int((_rc_df["Status"] == "🚨 Critical").sum()))

                _rc_show_only_issues = st.checkbox("Show mismatches/critical only", value=True,
                                                    key="rc_filter_issues")
                _rc_view = _rc_df if not _rc_show_only_issues else _rc_df[_rc_df["Status"] != "✅ Matched"]
                if _rc_view.empty:
                    st.success("✅ Everything matched for this period and factory.")
                else:
                    st.dataframe(_rc_view, width='stretch', hide_index=True, height=360)

    with tab_history:
        st.subheader("Reconciliation History")
        _rc_hist_clause = " WHERE factory=?" if rc_fac != ALL_FACTORIES else ""
        _rc_hist_param  = (rc_fac,) if rc_fac != ALL_FACTORIES else ()
        _rc_hist = pd.read_sql_query(
            "SELECT check_type, factory, item_code, period_start, period_end, "
            "qty_source_a, qty_source_b, difference, severity, detail, checked_at "
            "FROM inventory_reconciliation" + _rc_hist_clause +
            " ORDER BY id DESC LIMIT 500", conn, params=_rc_hist_param
        )
        if _rc_hist.empty:
            st.info("No reconciliation history yet.")
        else:
            _rc_hist_filtered = search_filter(_rc_hist, "Search history", key="rc_hist_search")
            _rc_hist_filtered = paginate_df(_rc_hist_filtered, key="rc_hist_page")
            st.dataframe(_rc_hist_filtered, width='stretch', hide_index=True, height=380)


# ─────────────────────────────────────────────────────────────────────────────
#  SALES  (new — commercial order tracking with targets)
# ─────────────────────────────────────────────────────────────────────────────
elif module == "Sales":

    st.title("📈 Sales")
    tab_add, tab_records, tab_edit_so, tab_targets, tab_invoice, tab_order_status = st.tabs([
        "➕ New Order", "📋 Records", "✏️ Edit Record", "🎯 Targets",
        "🧾 Invoice", "🔎 Order Status"
    ])

    # ── collect all sales reps from existing records for dropdown ─────────
    _known_reps = sorted(
        pd.read_sql_query("SELECT DISTINCT sales_rep FROM sales_orders WHERE sales_rep != ''",
                          conn)["sales_rep"].tolist()
    )

    with tab_add:
        st.subheader("New Sales Order")
        c1, c2, c3 = st.columns(3)
        with c1:
            so_date    = st.date_input("Date", key="so_d")
            so_factory = st.selectbox("Factory", FACTORIES, key="so_f",
                                       index=FACTORIES.index(factory)
                                             if factory in FACTORIES else 0)
            # Customer dropdown from master
            _so_cust_opts = ["— Type below —"] + CUSTOMER_LIST
            _so_cust_pick = st.selectbox("Customer (from master)", _so_cust_opts, key="so_cust_pick")
            so_cust_manual = st.text_input("Or enter new customer name", key="so_cust_manual",
                                            placeholder="New / one-time customer")
            so_cust = (_so_cust_pick if _so_cust_pick != "— Type below —"
                        else so_cust_manual.strip())
        with c2:
            so_product    = st.selectbox("Product", FCSC_PRODUCTS, key="so_p_sel", format_func=fg_label)
            so_custom_prd = st.text_input("Custom name (if 'Other / Custom')", key="so_p_cust")
            so_qty        = st.number_input("Quantity", min_value=0, step=1, key="so_qty")
            so_price      = st.number_input("Unit Price (₹)", min_value=0.0,
                                             step=0.01, format="%.2f", key="so_price")
        with c3:
            # Sales rep — free-text with autocomplete from past entries
            so_rep_manual = st.text_input(
                "Sales Representative",
                placeholder="Type name…",
                key="so_rep"
            )
            if _known_reps:
                so_rep_pick = st.selectbox(
                    "Or pick from previous reps",
                    ["— type above —"] + _known_reps,
                    key="so_rep_pick"
                )
                so_rep = so_rep_pick if so_rep_pick != "— type above —" else so_rep_manual.strip()
            else:
                so_rep = so_rep_manual.strip()

            so_gstin    = st.text_input("Customer GSTIN", placeholder="22AAAAA0000A1Z5",
                                         key="so_gstin")
            so_hsn      = st.text_input("HSN Code", placeholder="e.g. 3214",
                                         key="so_hsn")
            so_gst_rate = st.selectbox("GST Rate (%)", GST_RATES,
                                        index=GST_RATES.index(18.0), key="so_gst_rate")
            so_total    = so_qty * so_price
            so_tax_amt  = round(so_total * so_gst_rate / 100, 2)
            so_grand    = so_total + so_tax_amt
            sc1, sc2 = st.columns(2)
            sc1.metric("Taxable Amount", fmt_inr(so_total))
            sc2.metric(f"Total incl. GST {so_gst_rate}%", fmt_inr(so_grand))

        if st.button("💾 Save Sales Order"):
            final_so_product = (so_custom_prd.strip()
                                if so_product == "Other / Custom" and so_custom_prd.strip()
                                else so_product)
            if not so_cust.strip():
                st.warning("Customer name is required.")
            elif not final_so_product or final_so_product == "Other / Custom":
                st.warning("Please select or enter a product.")
            elif not so_rep:
                st.warning("Sales representative name is required.")
            else:
                dup = pd.read_sql_query(
                    "SELECT id FROM sales_orders "
                    "WHERE date=? AND factory=? AND customer=? AND product=? AND sales_rep=?",
                    conn, params=(str(so_date), so_factory,
                                  so_cust.strip(), final_so_product, so_rep)
                )
                if not dup.empty:
                    st.warning(
                        f"⚠️ An order for **{final_so_product}** by **{so_rep}** to "
                        f"**{so_cust}** on **{so_date}** already exists. "
                        f"Use ✏️ Edit Record to modify it."
                    )
                else:
                    try:
                        cur.execute(
                            "INSERT INTO sales_orders"
                            "(date,factory,customer,sales_rep,product,unit_price,qty,total,"
                            "gstin,hsn_code,gst_rate)"
                            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                            (str(so_date), so_factory, so_cust.strip(), so_rep,
                             final_so_product, so_price, so_qty, round(so_total, 2),
                             so_gstin.strip(), so_hsn.strip(), so_gst_rate)
                        )
                        conn.commit()
                        log_audit("INSERT", "sales_orders", "new",
                                  f"{so_factory} | {final_so_product} | {so_cust} "
                                  f"| {so_rep} | {fmt_inr(so_total)}")
                        st.success(f"✅ Order saved — {fmt_inr(so_total)} | {so_cust} via {so_rep}")
                        st.rerun()
                    except sqlite3.Error as e:
                        st.error(f"Database error: {e}")

    with tab_records:
        st.subheader("Sales Orders")
        if so_df.empty:
            st.info("No sales orders for this factory / date range.")
        else:
            so_rev = so_df["total"].sum()
            k1, k2, k3, k4 = st.columns(4)
            k1.metric("Total Sales Value",  fmt_inr(so_rev))
            k2.metric("Orders",             len(so_df))
            k3.metric("Avg Order Value",    fmt_inr(so_rev / len(so_df)))
            k4.metric("Unique Customers",
                       so_df["customer"].nunique() if "customer" in so_df.columns else "—")

            disp_so = so_df.copy()
            disp_so["total"]      = disp_so["total"].apply(fmt_inr)
            disp_so["unit_price"] = disp_so["unit_price"].apply(fmt_inr)
            if "product" in disp_so.columns:
                disp_so.insert(disp_so.columns.get_loc("product") + 1, "rm_code",
                                disp_so["product"].apply(get_fg_code))
            disp_so = search_filter(disp_so, "Search orders", key="so_search")
            disp_so = paginate_df(disp_so, key="so_page")
            st.dataframe(
                disp_so.drop(columns=["id"], errors="ignore")
                        .rename(columns={
                            "date":"Date","factory":"Factory",
                            "customer":"Customer","sales_rep":"Sales Rep",
                            "product":"Product","rm_code":"RM Code","unit_price":"Unit Price",
                            "qty":"Qty","total":"Total"
                        }),
                width='stretch', hide_index=True, height=340
            )
            delete_row_ui(so_df, "sales_orders", "customer", "so")

            if HAS_PLOTLY and not so_df.empty:
                ch1, ch2, ch3 = st.columns(3)
                with ch1:
                    by_rep = (so_df.groupby("sales_rep")["total"]
                              .sum().reset_index()
                              .sort_values("total", ascending=False))
                    fig_r = px.bar(by_rep, x="sales_rep", y="total",
                                   color_discrete_sequence=["#1E3A5F"],
                                   template="plotly_white",
                                   title="Sales by Representative",
                                   labels={"sales_rep":"Rep","total":"Value (₹)"})
                    fig_r.update_layout(height=240, margin=dict(l=10,r=10,t=36,b=10))
                    st.plotly_chart(fig_r, width='stretch')
                with ch2:
                    by_cust = (so_df.groupby("customer")["total"]
                               .sum().reset_index()
                               .sort_values("total", ascending=False).head(8))
                    fig_c = px.bar(by_cust, x="customer", y="total",
                                   color_discrete_sequence=["#145C3C"],
                                   template="plotly_white",
                                   title="Top Customers",
                                   labels={"customer":"Customer","total":"Value (₹)"})
                    fig_c.update_layout(height=240, margin=dict(l=10,r=10,t=36,b=10))
                    st.plotly_chart(fig_c, width='stretch')
                with ch3:
                    by_prod = (so_df.groupby("product")["total"]
                               .sum().reset_index()
                               .sort_values("total", ascending=False).head(8))
                    fig_p = px.bar(by_prod, x="product", y="total",
                                   color_discrete_sequence=["#6E1423"],
                                   template="plotly_white",
                                   title="Top Products",
                                   labels={"product":"Product","total":"Value (₹)"})
                    fig_p.update_layout(height=240, margin=dict(l=10,r=10,t=36,b=10))
                    st.plotly_chart(fig_p, width='stretch')

    with tab_edit_so:
        st.subheader("Edit a Sales Order")
        if so_df.empty:
            st.info("No records to edit in the current date range.")
        else:
            opts_so = {
                f"ID {r['id']} — {r['customer']} | {fg_label(r['product'])} | {r['sales_rep']} ({r['date']})": r["id"]
                for _, r in so_df.iterrows()
            }
            sel_so_label = st.selectbox("Select order to edit",
                                         list(opts_so.keys()), key="so_edit_sel")
            sel_so_id  = opts_so[sel_so_label]
            sel_so_row = so_df[so_df["id"] == sel_so_id].iloc[0]

            ec1, ec2, ec3 = st.columns(3)
            with ec1:
                e_so_date    = st.date_input("Date",
                    value=pd.to_datetime(sel_so_row["date"]).date(), key="e_so_d")
                e_so_factory = st.selectbox("Factory", FACTORIES, key="e_so_f",
                    index=FACTORIES.index(sel_so_row["factory"])
                          if sel_so_row["factory"] in FACTORIES else 0,
                    disabled=not _is_admin)
                e_so_cust = st.text_input("Customer",
                    value=sel_so_row["customer"], key="e_so_cust")
            with ec2:
                cur_so_idx = FCSC_PRODUCTS.index(sel_so_row["product"]) \
                             if sel_so_row["product"] in FCSC_PRODUCTS else len(FCSC_PRODUCTS) - 1
                e_so_product    = st.selectbox("Product", FCSC_PRODUCTS,
                    index=cur_so_idx, key="e_so_p_sel", format_func=fg_label)
                e_so_custom_prd = st.text_input("Custom name (if Other / Custom)",
                    value=sel_so_row["product"] if sel_so_row["product"] not in FCSC_PRODUCTS else "",
                    key="e_so_p_cust")
                e_so_qty   = st.number_input("Quantity", min_value=0, step=1,
                    value=int(sel_so_row["qty"]), key="e_so_qty")
                e_so_price = st.number_input("Unit Price (₹)", min_value=0.0,
                    step=0.01, format="%.2f",
                    value=float(sel_so_row["unit_price"]), key="e_so_price")
            with ec3:
                e_so_rep      = st.text_input("Sales Representative",
                    value=sel_so_row["sales_rep"], key="e_so_rep")
                e_so_gstin    = st.text_input("Customer GSTIN",
                    value=str(sel_so_row.get("gstin","") or ""), key="e_so_gstin")
                e_so_hsn      = st.text_input("HSN Code",
                    value=str(sel_so_row.get("hsn_code","") or ""), key="e_so_hsn")
                _e_so_gst_cur = float(sel_so_row.get("gst_rate", 18.0) or 18.0)
                e_so_gst_rate = st.selectbox("GST Rate (%)", GST_RATES,
                    index=GST_RATES.index(_e_so_gst_cur) if _e_so_gst_cur in GST_RATES else 2,
                    key="e_so_gst_rate")
                e_so_total = e_so_qty * e_so_price
                st.metric("Updated Total (excl. GST)", fmt_inr(e_so_total))

            if st.button("💾 Update Sales Order", key="so_upd_btn"):
                final_e_so_product = (e_so_custom_prd.strip()
                                      if e_so_product == "Other / Custom" and e_so_custom_prd.strip()
                                      else e_so_product)
                if not e_so_cust.strip() or not final_e_so_product:
                    st.warning("Customer and product are required.")
                elif not e_so_rep.strip():
                    st.warning("Sales representative is required.")
                else:
                    try:
                        cur.execute(
                            "UPDATE sales_orders SET date=?,factory=?,customer=?,"
                            "sales_rep=?,product=?,unit_price=?,qty=?,total=?,"
                            "gstin=?,hsn_code=?,gst_rate=? WHERE id=?",
                            (str(e_so_date), e_so_factory, e_so_cust.strip(),
                             e_so_rep.strip(), final_e_so_product,
                             e_so_price, e_so_qty, round(e_so_total, 2),
                             e_so_gstin.strip(), e_so_hsn.strip(),
                             e_so_gst_rate, sel_so_id)
                        )
                        conn.commit()
                        log_audit("UPDATE", "sales_orders", sel_so_id,
                                  f"{e_so_factory} | {final_e_so_product} | "
                                  f"{e_so_cust} | {e_so_rep} | {fmt_inr(e_so_total)}")
                        st.success("✅ Sales order updated.")
                        st.rerun()
                    except sqlite3.Error as e:
                        st.error(f"Database error: {e}")

    with tab_targets:
        st.subheader("🎯 Monthly Sales Targets")
        st.markdown(
            "<p style='color:#8C7B62;font-size:13px;'>"
            "Set monthly targets per factory and sales representative. "
            "Actual performance is calculated from orders logged above.</p>",
            unsafe_allow_html=True
        )

        _tgt_month = st.selectbox(
            "Month",
            [( datetime.date.today().replace(day=1)
               - datetime.timedelta(days=i*28) ).strftime("%Y-%m")
             for i in range(-1, 13)],
            key="tgt_month"
        )

        # ── Set / update a target ──────────────────────────────────────────
        if _is_admin:
            with st.expander("➕ Set / Update a Target", expanded=True):
                tg1, tg2, tg3, tg4 = st.columns(4)
                tgt_factory  = tg1.selectbox("Factory",    FACTORIES,   key="tgt_fac")
                tgt_rep_list = ["All Reps"] + _known_reps
                tgt_rep      = tg2.selectbox("Sales Rep",  tgt_rep_list, key="tgt_rep")
                tgt_amt      = tg3.number_input("Target Amount (₹)", min_value=0.0,
                                                 step=1000.0, format="%.0f", key="tgt_amt")
                tgt_qty      = tg4.number_input("Target Qty (units)", min_value=0,
                                                 step=1, key="tgt_qty")
                if st.button("💾 Save Target", key="tgt_save"):
                    rep_val = "" if tgt_rep == "All Reps" else tgt_rep
                    existing = pd.read_sql_query(
                        "SELECT id FROM sales_targets WHERE month=? AND factory=? AND sales_rep=?",
                        conn, params=(_tgt_month, tgt_factory, rep_val)
                    )
                    try:
                        if not existing.empty:
                            cur.execute(
                                "UPDATE sales_targets SET target_amt=?,target_qty=?"
                                " WHERE month=? AND factory=? AND sales_rep=?",
                                (tgt_amt, tgt_qty, _tgt_month, tgt_factory, rep_val)
                            )
                        else:
                            cur.execute(
                                "INSERT INTO sales_targets(month,factory,sales_rep,target_qty,target_amt)"
                                " VALUES (?,?,?,?,?)",
                                (_tgt_month, tgt_factory, rep_val, tgt_qty, tgt_amt)
                            )
                        conn.commit()
                        log_audit("INSERT", "sales_targets", "new",
                                  f"{tgt_factory} | {tgt_rep} | {_tgt_month} | {fmt_inr(tgt_amt)}")
                        st.success(f"✅ Target saved for {tgt_factory} / {tgt_rep} — {_tgt_month}")
                        st.rerun()
                    except sqlite3.Error as e:
                        st.error(f"Database error: {e}")

        # ── Actual vs Target table ─────────────────────────────────────────
        st.markdown(f"#### Actual vs Target — {_tgt_month}")
        tgts = pd.read_sql_query(
            "SELECT * FROM sales_targets WHERE month=?",
            conn, params=(_tgt_month,)
        )
        actuals_month = pd.read_sql_query(
            "SELECT factory, sales_rep, SUM(total) AS actual_amt, SUM(qty) AS actual_qty"
            " FROM sales_orders WHERE date LIKE ?"
            + (" AND factory=?" if factory != ALL_FACTORIES else ""),
            conn,
            params=(_tgt_month + "%", factory) if factory != ALL_FACTORIES
                   else (_tgt_month + "%",)
        )

        if tgts.empty and actuals_month.empty:
            st.info("No targets or orders recorded for this month yet.")
        else:
            # Merge targets with actuals
            merged_t = pd.merge(
                tgts[["factory","sales_rep","target_amt","target_qty"]],
                actuals_month.rename(columns={"actual_amt":"actual_amt",
                                               "actual_qty":"actual_qty"}),
                on=["factory","sales_rep"], how="outer"
            ).fillna(0)
            merged_t["Achv %"] = merged_t.apply(
                lambda r: f"{(r['actual_amt']/r['target_amt']*100):.1f}%"
                          if r["target_amt"] > 0 else "—", axis=1
            )
            merged_t["factory"]    = merged_t["factory"].replace("", "All Factories")
            merged_t["sales_rep"]  = merged_t["sales_rep"].replace("", "All Reps")
            merged_t["target_amt"] = merged_t["target_amt"].apply(fmt_inr)
            merged_t["actual_amt"] = merged_t["actual_amt"].apply(fmt_inr)

            st.dataframe(
                merged_t.rename(columns={
                    "factory":"Factory","sales_rep":"Sales Rep",
                    "target_amt":"Target (₹)","actual_amt":"Actual (₹)",
                    "target_qty":"Target Qty","actual_qty":"Actual Qty",
                    "Achv %":"Achievement"
                }),
                width='stretch', hide_index=True
            )

            # Progress bars per factory/rep
            if HAS_PLOTLY:
                _chart_data = pd.read_sql_query(
                    "SELECT factory, sales_rep, SUM(total) AS actual_amt"
                    " FROM sales_orders WHERE date LIKE ? GROUP BY factory, sales_rep",
                    conn, params=(_tgt_month + "%",)
                )
                _tgt_chart = pd.read_sql_query(
                    "SELECT factory, sales_rep, target_amt FROM sales_targets WHERE month=?",
                    conn, params=(_tgt_month,)
                )
                if not _tgt_chart.empty and not _chart_data.empty:
                    _merged_chart = pd.merge(_tgt_chart, _chart_data,
                                              on=["factory","sales_rep"], how="left").fillna(0)
                    _merged_chart["label"] = _merged_chart["factory"] + " / " + _merged_chart["sales_rep"].replace("","All Reps")
                    fig_tgt = px.bar(
                        _merged_chart.melt(id_vars="label",
                                            value_vars=["target_amt","actual_amt"],
                                            var_name="Type", value_name="Amount"),
                        x="label", y="Amount", color="Type",
                        barmode="group",
                        color_discrete_map={"target_amt":"#E2D4B8","actual_amt":"#6E1423"},
                        template="plotly_white",
                        title="Target vs Actual Sales",
                        labels={"label":"Factory / Rep","Amount":"₹","Type":""}
                    )
                    fig_tgt.update_layout(height=280, margin=dict(l=10,r=10,t=36,b=10),
                                           legend=dict(orientation="h", y=-0.25))
                    st.plotly_chart(fig_tgt, width='stretch')

    # ── INVOICE (PDF generation for a sales order) ──────────────────────────
    with tab_invoice:
        st.subheader("🧾 Generate Invoice")
        st.caption("Builds a printable tax invoice PDF for a sales order. "
                    "Edit COMPANY_INFO near the top of the file with your real GSTIN before "
                    "using these for actual customer-facing invoices.")

        _all_so = pd.read_sql_query("SELECT * FROM sales_orders ORDER BY id DESC", conn)
        if _all_so.empty:
            st.info("No sales orders yet.")
        else:
            _so_opts = {
                f"#{r['id']:05d} — {r['customer']} — {r['product']} — {fmt_inr(r['total'])}": r["id"]
                for _, r in _all_so.iterrows()
            }
            _inv_pick = st.selectbox("Select order", list(_so_opts.keys()), key="inv_pick")
            _inv_id = _so_opts[_inv_pick]
            _inv_row = _all_so[_all_so["id"] == _inv_id].iloc[0].to_dict()

            _cust_row = cur.execute(
                "SELECT name, gstin, address, phone FROM customers WHERE name = ?",
                (_inv_row["customer"],)
            ).fetchone()
            _cust_dict = ({"name": _cust_row[0], "gstin": _cust_row[1],
                           "address": _cust_row[2], "phone": _cust_row[3]}
                          if _cust_row else None)

            if HAS_REPORTLAB:
                pdf_bytes = generate_invoice_pdf(_inv_row, _cust_dict)
                st.download_button(
                    "📥 Download Invoice (PDF)",
                    data=pdf_bytes,
                    file_name=f"FCSC_Invoice_{_inv_id:05d}.pdf",
                    mime="application/pdf",
                )
            else:
                st.warning("Install `reportlab` (pip install reportlab) to enable PDF invoices.")

    # ── ORDER STATUS (simple customer-facing lookup) ────────────────────────
    with tab_order_status:
        st.subheader("🔎 Order Status Lookup")
        st.caption("Quick 'has my order shipped' answer — matches the order to the most "
                    "recent production batch of the same product at the same factory, since "
                    "orders aren't yet linked to a specific batch number directly.")

        _os_id = st.number_input("Order #", min_value=1, step=1, key="os_order_id")
        if st.button("🔍 Look up", key="os_lookup_btn"):
            result = get_order_status(int(_os_id))
            if result is None:
                st.error("No order found with that number.")
            else:
                o = result["order"]
                st.markdown(f"**Order #{o['id']:05d}** — {o['customer']} — {o['product']} "
                            f"({o['qty']:g} units) — {fmt_inr(o['total'])}")
                if result["batch_no"]:
                    st.success(
                        f"Likely batch: **{result['batch_no']}** — status: "
                        f"**{result['batch_status']}**" +
                        (f" — dispatched {result['dispatch_date']}" if result["dispatch_date"] else "")
                    )
                    st.caption("Match is based on product + factory, not a guaranteed batch link — "
                                "confirm against the Dispatch module for anything customer-facing.")
                else:
                    st.info("No matching production batch found yet for this order's product/factory.")


# ─────────────────────────────────────────────────────────────────────────────
#  COST
# ─────────────────────────────────────────────────────────────────────────────
elif module == "Cost":

    st.title("🔖 Cost Entry")
    tab_entry, tab_log, tab_edit_co = st.tabs(["➕ Add Cost", "📋 Records", "✏️ Edit Record"])

    with tab_entry:
        st.subheader("New Cost Entry")
        c1, c2, c3 = st.columns(3)
        with c1:
            co_date    = st.date_input("Date", key="co_d")
            co_factory = st.selectbox("Factory", FACTORIES, key="co_f",
                                       index=FACTORIES.index(factory) if factory in FACTORIES else 0)
        with c2:
            co_cat = st.selectbox("Category", COST_CATS, key="co_cat")
            co_amt = st.number_input("Amount (₹)", min_value=0.0, step=1.0,
                                      format="%.2f", key="co_amt")
        with c3:
            co_desc = st.text_input("Description (optional)", key="co_desc")

        if st.button("💾 Save Cost"):
            if not co_amt:
                st.warning("Please enter an amount greater than 0.")
            else:
                # Duplicate guard: same date + factory + category + amount
                dup = pd.read_sql_query(
                    "SELECT id FROM costs WHERE date=? AND factory=? AND category=? AND amount=?",
                    conn, params=(str(co_date), co_factory, co_cat, co_amt)
                )
                if not dup.empty:
                    st.warning(
                        f"⚠️ A **{co_cat}** entry of **{fmt_inr(co_amt)}** already exists "
                        f"for {co_factory} on {co_date}. Use the ✏️ Edit tab to modify it, "
                        f"or change the date / amount to save a new record."
                    )
                else:
                    try:
                        cur.execute(
                            "INSERT INTO costs(date,factory,category,amount,description)"
                            " VALUES (?,?,?,?,?)",
                            (str(co_date), co_factory, co_cat, co_amt, co_desc.strip())
                        )
                        conn.commit()
                        log_audit("INSERT", "costs", "new",
                                  f"{co_factory} | {co_cat} | {fmt_inr(co_amt)}"
                                  + (f" | {co_desc}" if co_desc.strip() else ""))
                        st.success(f"✅ Cost saved — {co_cat}: {fmt_inr(co_amt)}")
                        st.rerun()
                    except sqlite3.Error as e:
                        st.error(f"Database error: {e}")

    with tab_log:
        st.subheader("Cost Records")
        if cost_df.empty:
            st.info("No cost records for this factory / date range.")
        else:
            total = cost_df["amount"].sum()
            k1, k2 = st.columns(2)
            k1.metric("Total Costs", fmt_inr(total))
            k2.metric("Entries",     len(cost_df))

            disp = cost_df.copy()
            disp["amount"] = disp["amount"].apply(fmt_inr)

            disp = search_filter(disp, "Search cost records", key="cost_search")
            # FIX: Pagination applied.
            disp = paginate_df(disp, key="cost_page")
            st.dataframe(disp.drop(columns=["id"], errors="ignore"),
                         width='stretch', hide_index=True, height=320)

            delete_row_ui(cost_df, "costs", "category", "cost")

            if HAS_PLOTLY:
                ch1, ch2 = st.columns(2)
                with ch1:
                    by_cat = cost_df.groupby("category")["amount"].sum().reset_index()
                    fig = px.pie(by_cat, names="category", values="amount", hole=0.40,
                                 color_discrete_sequence=["#6E1423","#1E3A5F","#A8791E",
                                                           "#145C3C","#5B2C6F","#4A7A80",
                                                           "#7A6A50","#B8860B","#1E8A5F"],
                                 template="plotly_white", title="Costs by Category")
                    fig.update_layout(height=260, margin=dict(l=10,r=10,t=36,b=10))
                    st.plotly_chart(fig, width='stretch')

                with ch2:
                    cost_df["month"] = cost_df["date"].astype(str).str[:7]
                    monthly_cost = (cost_df.groupby("month")["amount"]
                                           .sum().reset_index()
                                           .sort_values("month"))
                    fig_trend = px.bar(monthly_cost, x="month", y="amount",
                                        color_discrete_sequence=["#6E1423"],
                                        template="plotly_white",
                                        title="Monthly Cost Trend",
                                        labels={"month":"Month","amount":"Amount (₹)"})
                    fig_trend.update_layout(height=260, margin=dict(l=10,r=10,t=36,b=10))
                    st.plotly_chart(fig_trend, width='stretch')
            else:
                st.bar_chart(cost_df.groupby("category")["amount"].sum())

    with tab_edit_co:
        st.subheader("Edit a Cost Record")
        if cost_df.empty:
            st.info("No records to edit in the current date range.")
        else:
            opts_co = {
                f"ID {r['id']} — {r['category']} {fmt_inr(r['amount'])} ({r['date']})": r["id"]
                for _, r in cost_df.iterrows()
            }
            sel_co_label = st.selectbox("Select record to edit", list(opts_co.keys()),
                                         key="co_edit_sel")
            sel_co_id  = opts_co[sel_co_label]
            sel_co_row = cost_df[cost_df["id"] == sel_co_id].iloc[0]

            cc1, cc2 = st.columns(2)
            with cc1:
                e_co_date    = st.date_input("Date",
                    value=pd.to_datetime(sel_co_row["date"]).date(), key="e_co_d")
                e_co_factory = st.selectbox("Factory", FACTORIES, key="e_co_f",
                    index=FACTORIES.index(sel_co_row["factory"])
                          if sel_co_row["factory"] in FACTORIES else 0,
                    disabled=not _is_admin)
            with cc2:
                e_co_cat = st.selectbox("Category", COST_CATS, key="e_co_cat",
                    index=COST_CATS.index(sel_co_row["category"])
                          if sel_co_row["category"] in COST_CATS else 0)
                e_co_amt = st.number_input("Amount (₹)",
                    min_value=0.0, step=1.0, format="%.2f",
                    value=float(sel_co_row["amount"]), key="e_co_amt")
            e_co_desc = st.text_input("Description",
                value=str(sel_co_row.get("description", "") or ""),
                key="e_co_desc")

            if st.button("💾 Update Cost Record", key="co_upd_btn"):
                if not e_co_amt:
                    st.warning("Amount must be greater than 0.")
                else:
                    try:
                        cur.execute(
                            "UPDATE costs SET date=?,factory=?,category=?,amount=?,description=?"
                            " WHERE id=?",
                            (str(e_co_date), e_co_factory, e_co_cat,
                             e_co_amt, e_co_desc.strip(), sel_co_id)
                        )
                        conn.commit()
                        log_audit("UPDATE", "costs", sel_co_id,
                                  f"{e_co_factory} | {e_co_cat} | {fmt_inr(e_co_amt)}")
                        st.success("✅ Cost record updated.")
                        st.rerun()
                    except sqlite3.Error as e:
                        st.error(f"Database error: {e}")


# ─────────────────────────────────────────────────────────────────────────────
#  P&L
# ─────────────────────────────────────────────────────────────────────────────
elif module == "P&L":

    st.title("⚖️ Profit & Loss Statement")
    fac_label = factory if factory != ALL_FACTORIES else "All Factories"
    st.markdown(
        f"<p style='color:#8C7B62;font-size:13px;'>"
        f"Factory: <strong style='color:#6E1423'>{fac_label}</strong> | "
        f"Range: {d_start} → {d_end}</p>",
        unsafe_allow_html=True,
    )

    # FIX: Revenue is recognised on DISPATCH only. A Sales Order is a
    # commercial commitment / order-book entry, not yet invoiced or shipped
    # goods — summing it into Revenue double-counted the same business once
    # it later dispatches (Order booked ₹10L + Dispatched ₹6L was being
    # reported as ₹16L "Revenue" when only ₹6L had actually been earned).
    # Sales Orders are shown as a separate Order Book figure below instead.
    _disp_rev = sales_df["total"].sum() if not sales_df.empty else 0
    _so_booked = so_df["total"].sum()   if not so_df.empty    else 0
    revenue   = _disp_rev              # Dispatch = recognised revenue
    cost      = cost_df["amount"].sum() if not cost_df.empty  else 0
    profit    = revenue - cost
    margin    = safe_ratio_pct(profit, revenue) or 0

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Revenue (Dispatched)", fmt_inr(revenue))
    k2.metric("Total Costs",  fmt_inr(cost))
    k3.metric("Net Profit",   fmt_inr(profit),
              delta=f"{margin:.1f}% margin" if revenue else None)
    k4.metric("Break-Even",   "✅ Profitable" if profit >= 0 else "❌ Loss")
    st.caption(
        f"📖 Order Book (Sales Orders booked, not yet dispatched/invoiced): "
        f"**{fmt_inr(_so_booked)}** — shown separately, not included in Revenue above."
    )

    st.markdown("---")

    col_pl, col_charts = st.columns([1.3, 1])

    with col_pl:
        def pl_row(label: str, value: float, style: str = "normal") -> None:
            if style == "section":
                bg, fw, color = "#EFE4CC", "700", "#1C120D"
                val_str = ""
            elif style == "total":
                bg = "#E9F3EA" if value >= 0 else "#F6E6E4"
                fw = "800"
                color = "#145C3C" if value >= 0 else "#6E1423"
                val_str = fmt_inr(value)
            else:
                bg, fw, color = "#FFFBF2", "400", "#6B5540"
                val_str = fmt_inr(value)
            st.markdown(
                f"<div style='display:flex;justify-content:space-between;"
                f"padding:8px 16px;background:{bg};border-bottom:1px solid #E2D4B8;"
                f"font-size:13px;'>"
                f"<span style='font-weight:{fw};color:{color}'>{label}</span>"
                f"<span style='font-family:monospace;font-weight:{fw};color:{color}'>{val_str}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )

        pl_row("INCOME", 0, "section")
        pl_row("  Dispatch Revenue", _disp_rev)
        pl_row("GROSS INCOME", revenue, "total")

        pl_row("ORDER BOOK (memo — not yet dispatched, excluded from Income)", 0, "section")
        pl_row("  Sales Orders Booked", _so_booked)

        pl_row("OPERATING COSTS", 0, "section")
        if not cost_df.empty:
            for cat, grp in cost_df.groupby("category"):
                pl_row(f"  {cat}", grp["amount"].sum())
        else:
            pl_row("  No cost data", 0)
        pl_row("TOTAL EXPENSES", cost, "total")

        pl_row("PROFITABILITY", 0, "section")
        st.markdown(
            f"<div style='display:flex;justify-content:space-between;"
            f"padding:8px 16px;background:#{'F0FDF4' if profit>=0 else 'FEF2F2'};"
            f"border-bottom:1px solid #E2D4B8;font-size:13px;'>"
            f"<span style='color:#6B5540'>  Profit Margin</span>"
            f"<span style='font-family:monospace;font-weight:600;"
            f"color:{'#145C3C' if profit>=0 else '#6E1423'}'>{margin:.2f}%</span>"
            f"</div>",
            unsafe_allow_html=True,
        )
        pl_row("NET PROFIT / (LOSS)", profit, "total")

        if revenue > 0:
            st.markdown(
                f"<div style='padding:10px 16px;background:#F3E7D0;"
                f"border-radius:0 0 8px 8px;font-size:12px;color:#8C7B62;'>"
                f"💡 To break even, revenue must exceed <strong>{fmt_inr(cost)}</strong>. "
                f"Current gap: <strong style='color:{'#145C3C' if profit>=0 else '#6E1423'}'>"
                f"{fmt_inr(abs(profit))}</strong> {'surplus' if profit>=0 else 'shortfall'}."
                f"</div>",
                unsafe_allow_html=True,
            )

    with col_charts:
        pnl_df = pd.DataFrame({
            "Label":  ["Revenue", "Expenses", "Net P&L"],
            "Amount": [revenue,   cost,        abs(profit)],
            "Color":  ["#145C3C", "#6E1423",   "#1E3A5F" if profit >= 0 else "#6E1423"],
        })
        if HAS_PLOTLY:
            fig = go.Figure(go.Bar(
                x=pnl_df["Label"], y=pnl_df["Amount"],
                marker_color=pnl_df["Color"],
                text=pnl_df.apply(
                    lambda r: fmt_inr(r["Amount"]) + (" (Loss)" if profit < 0 and r["Label"] == "Net P&L" else ""),
                    axis=1
                ),
                textposition="outside", textfont=dict(size=10),
            ))
            fig.update_layout(title="Revenue vs Expenses", height=240,
                               margin=dict(l=10,r=10,t=40,b=10),
                               template="plotly_white", showlegend=False)
            st.plotly_chart(fig, width='stretch')
        else:
            st.bar_chart(pnl_df.set_index("Label")["Amount"])

        # FIX: monthly trend uses Dispatch revenue only, matching the
        # Revenue figure above — Sales Orders are booked value, not
        # recognised revenue, so they no longer feed this chart either.
        months: dict = {}
        if not sales_df.empty:
            for _, row in sales_df.iterrows():
                m = str(row["date"])[:7]
                months.setdefault(m, {"rev": 0, "cost": 0})["rev"] += row["total"]
        if not cost_df.empty:
            for _, row in cost_df.iterrows():
                m = str(row["date"])[:7]
                months.setdefault(m, {"rev": 0, "cost": 0})["cost"] += row["amount"]

        if months:
            trend = pd.DataFrame([
                {"Month": m, "Revenue": v["rev"], "Costs": v["cost"]}
                for m, v in sorted(months.items())
            ])
            trend["Profit"] = trend["Revenue"] - trend["Costs"]
            if HAS_PLOTLY:
                fig2 = px.line(trend, x="Month", y=["Revenue","Costs","Profit"],
                               color_discrete_map={
                                   "Revenue":"#145C3C","Costs":"#6E1423","Profit":"#1E3A5F"
                               },
                               markers=True, template="plotly_white",
                               title="Monthly P&L Trend")
                fig2.update_layout(height=240, margin=dict(l=10,r=10,t=40,b=10),
                                    legend=dict(orientation="h", y=-0.25))
                st.plotly_chart(fig2, width='stretch')
            else:
                st.line_chart(trend.set_index("Month")[["Revenue","Costs","Profit"]])


# ─────────────────────────────────────────────────────────────────────────────
#  ANALYSIS
# ─────────────────────────────────────────────────────────────────────────────
elif module == "Analysis":

    st.title("📊 Analysis")
    fac_label = factory if factory != ALL_FACTORIES else "All Factories"
    st.markdown(f"<p style='color:#8C7B62;font-size:13px;'>Scope: <strong style='color:#6E1423'>{fac_label}</strong></p>",
                unsafe_allow_html=True)

    if prod_df.empty:
        st.info("No production data in selected range. Log production first.")
    else:
        total_u = prod_df["production"].sum()
        avg_eff = prod_df["efficiency"].mean()
        tot_lab = prod_df["labour"].sum()
        avg_hrs = prod_df["hours"].mean()

        k1,k2,k3,k4,k5 = st.columns(5)
        k1.metric(f"Total ({unit})",  f"{from_mt(total_u):,.2f}")
        k2.metric("Avg Efficiency",   f"{avg_eff:.4f}")
        k3.metric("Total Labour",     f"{int(tot_lab):,}")
        k4.metric("Avg Hours/Entry",  f"{avg_hrs:.1f}")
        k5.metric("Records",          len(prod_df))

        st.markdown("---")

        col_l, col_r = st.columns(2)

        with col_l:
            ts = (prod_df.groupby("date")["production"].sum()
                         .reset_index().sort_values("date"))
            ts["display"] = ts["production"].apply(from_mt)
            if HAS_PLOTLY:
                fig = px.line(ts, x="date", y="display",
                              labels={"date":"Date","display":f"Production ({unit})"},
                              color_discrete_sequence=["#6E1423"],
                              markers=True, template="plotly_white",
                              title="Production Over Time")
                fig.update_layout(height=240, margin=dict(l=10,r=10,t=36,b=10))
                st.plotly_chart(fig, width='stretch')
            else:
                st.line_chart(ts.set_index("date")["display"])

        with col_r:
            es = (prod_df.groupby("date")["efficiency"].mean()
                         .reset_index().sort_values("date"))
            if HAS_PLOTLY:
                fig2 = px.line(es, x="date", y="efficiency",
                               color_discrete_sequence=["#1E3A5F"],
                               markers=True, template="plotly_white",
                               title="Efficiency Over Time")
                fig2.add_hline(y=0.5, line_dash="dash", line_color="#6E1423",
                               annotation_text="Threshold 0.5")
                fig2.update_layout(height=240, margin=dict(l=10,r=10,t=36,b=10))
                st.plotly_chart(fig2, width='stretch')
            else:
                st.line_chart(es.set_index("date")["efficiency"])

        st.markdown("---")

        st.subheader("Heatmaps — Product × Date")
        hm_l, hm_r = st.columns(2)

        with hm_l:
            st.markdown("**Production Heatmap**")
            try:
                pivot_p = prod_df.pivot_table(
                    index="product", columns="date",
                    values="production", aggfunc="sum", fill_value=0
                )
                pivot_p_disp = pivot_p.apply(lambda col: col.map(from_mt))
                if HAS_PLOTLY and not pivot_p_disp.empty:
                    fig3 = go.Figure(go.Heatmap(
                        z=pivot_p_disp.values,
                        x=[str(c)[:10] for c in pivot_p_disp.columns],
                        y=pivot_p_disp.index.tolist(),
                        colorscale="Reds",
                        text=pivot_p_disp.values.round(2),
                        texttemplate="%{text}",
                        hoverongaps=False,
                    ))
                    fig3.update_layout(
                        height=max(200, len(pivot_p_disp) * 45 + 80),
                        margin=dict(l=10,r=10,t=10,b=10),
                        xaxis_title="Date", yaxis_title=""
                    )
                    st.plotly_chart(fig3, width='stretch')
                else:
                    st.dataframe(pivot_p_disp.round(2), width='stretch')
            except Exception as e:
                st.info(f"Heatmap unavailable: {e}")

        with hm_r:
            st.markdown("**Efficiency Heatmap**")
            try:
                pivot_e = prod_df.pivot_table(
                    index="product", columns="date",
                    values="efficiency", aggfunc="mean", fill_value=0
                )
                if HAS_PLOTLY and not pivot_e.empty:
                    fig4 = go.Figure(go.Heatmap(
                        z=pivot_e.values.round(4),
                        x=[str(c)[:10] for c in pivot_e.columns],
                        y=pivot_e.index.tolist(),
                        colorscale="Blues",
                        text=pivot_e.values.round(4),
                        texttemplate="%{text}",
                        hoverongaps=False,
                    ))
                    fig4.update_layout(
                        height=max(200, len(pivot_e) * 45 + 80),
                        margin=dict(l=10,r=10,t=10,b=10),
                        xaxis_title="Date", yaxis_title=""
                    )
                    st.plotly_chart(fig4, width='stretch')
                else:
                    st.dataframe(pivot_e.round(4), width='stretch')
            except Exception as e:
                st.info(f"Heatmap unavailable: {e}")

        st.markdown("---")

        r1, r2 = st.columns(2)

        with r1:
            st.subheader("Factory Ranking (All Time)")
            rank_df = pd.read_sql_query(
                "SELECT factory, SUM(production) AS production, AVG(efficiency) AS efficiency "
                "FROM production GROUP BY factory ORDER BY efficiency DESC",
                conn
            )
            if not rank_df.empty:
                rank_df["production"] = rank_df["production"].apply(
                    lambda x: f"{from_mt(x):,.2f} {unit}"
                )
                rank_df["efficiency"] = rank_df["efficiency"].apply(lambda x: f"{x:.4f}")
                rank_df.insert(0, "Rank", ["🥇","🥈","🥉","4th"][:len(rank_df)])
                st.dataframe(
                    rank_df.rename(columns={
                        "factory":"Factory","production":"Total","efficiency":"Avg Efficiency"
                    }),
                    width='stretch', hide_index=True
                )

        with r2:
            st.subheader(f"Product Ranking — {fac_label}")
            pr = (prod_df.groupby("product")
                         .agg(production=("production","sum"),
                              efficiency=("efficiency","mean"))
                         .reset_index()
                         .sort_values("production", ascending=False))
            if not pr.empty:
                pr["production"] = pr["production"].apply(lambda x: f"{from_mt(x):,.2f} {unit}")
                pr["efficiency"] = pr["efficiency"].apply(lambda x: f"{x:.4f}")
                pr.insert(0, "Rank", [f"#{i+1}" for i in range(len(pr))])
                st.dataframe(
                    pr.rename(columns={
                        "product":"Product","production":"Total","efficiency":"Avg Efficiency"
                    }),
                    width='stretch', hide_index=True
                )

        st.markdown("---")

        st.subheader("Best Performance Days — All Factories")
        all_p = pd.read_sql_query("SELECT * FROM production", conn)
        for _fac_perf in FACTORIES:
            with st.expander(f"🏭 {_fac_perf}", expanded=(_fac_perf == factory)):
                fd = all_p[all_p["factory"] == _fac_perf]
                if fd.empty:
                    st.info("No data."); continue
                daily = fd.groupby("date").agg({
                    "production":"sum","labour":"sum",
                    "hours":"mean","efficiency":"mean"
                })
                bc1, bc2, bc3, bc4 = st.columns(4)
                bc1.metric("Best Production",  str(daily["production"].idxmax()))
                bc2.metric("Best Efficiency",  str(daily["efficiency"].idxmax()))
                bc3.metric("Most Labour",      str(daily["labour"].idxmax()))
                bc4.metric("Longest Hours",    str(daily["hours"].idxmax()))

        st.markdown("---")

        st.subheader("🧠 Smart Insights")
        df_s = prod_df.sort_values("date")
        if len(df_s) >= 2:
            last, prev = df_s.iloc[-1], df_s.iloc[-2]
            insights = []
            prod_chg = safe_pct_change(last["production"], prev["production"])
            if prod_chg is not None and last["production"] < prev["production"]:
                insights.append(("warning", f"Production fell {abs(prod_chg):.1f}% vs previous entry"))
            if last["labour"] > prev["labour"] and last["production"] <= prev["production"]:
                insights.append(("warning", "More workers deployed but output didn't increase"))
            if last["hours"] > prev["hours"] and last["efficiency"] < prev["efficiency"]:
                insights.append(("warning", "Longer hours but lower efficiency — possible fatigue"))
            eff_chg = safe_pct_change(last["efficiency"], prev["efficiency"])
            if eff_chg is not None and eff_chg > 0:
                insights.append(("success", f"Efficiency up {eff_chg:.1f}% vs previous entry"))
            if prod_chg is not None and prod_chg > 0:
                insights.append(("success", f"Production up {prod_chg:.1f}% vs previous entry"))
            if last["efficiency"] < 0.5:
                insights.append(("error", f"Latest efficiency {last['efficiency']:.4f} is below 0.5 threshold"))
            for kind, msg in insights or [("success","Operations stable — no anomalies detected")]:
                if kind == "error":    st.error(msg)
                elif kind == "warning": st.warning(msg)
                else:                   st.success(msg)
        else:
            st.info("Need at least 2 entries in range to generate trend insights.")


# ─────────────────────────────────────────────────────────────────────────────
#  REPORTS
# ─────────────────────────────────────────────────────────────────────────────
elif module == "Reports":

    st.title("📄 Reports & Export")

    rc1, rc2, rc3 = st.columns(3)
    # Supervisors are hard-locked to their own factory — hide the scope toggle.
    if _is_admin:
        rpt_scope = rc1.selectbox("Factory Scope", [SCOPE_ACTIVE, SCOPE_ALL])
    else:
        rpt_scope = SCOPE_ACTIVE
        rc1.info(f"🔒 Scope locked to **{factory}**")
    rpt_period  = rc2.selectbox("Period", ["In Date Range", "This Month", "This Year", "All Time"])
    rpt_type    = rc3.selectbox("Report Type", [
        "Full Summary", "Production", "Sand", "Stock", "Dispatch", "Sales Orders", "Costs"
    ])

    # FIX: get_report_df moved here as a proper function (not a nested closure),
    # and ALL string interpolation of factory replaced with parameterised queries.
    def get_report_df(table: str) -> pd.DataFrame:
        assert table in _ALLOWED_TABLES, f"Invalid table: {table}"
        fac_filter = factory if rpt_scope == SCOPE_ACTIVE and factory != ALL_FACTORIES else None

        if rpt_period == "All Time":
            if fac_filter:
                return pd.read_sql_query(
                    f"SELECT * FROM {table} WHERE factory = ? ORDER BY date DESC",
                    conn, params=(fac_filter,)
                )
            return pd.read_sql_query(
                f"SELECT * FROM {table} ORDER BY date DESC", conn
            )
        elif rpt_period == "This Month":
            m = datetime.date.today().strftime("%Y-%m")
            if fac_filter:
                return pd.read_sql_query(
                    f"SELECT * FROM {table} WHERE date LIKE ? AND factory = ?",
                    conn, params=(f"{m}%", fac_filter)
                )
            return pd.read_sql_query(
                f"SELECT * FROM {table} WHERE date LIKE ?",
                conn, params=(f"{m}%",)
            )
        elif rpt_period == "This Year":
            y = datetime.date.today().strftime("%Y")
            if fac_filter:
                return pd.read_sql_query(
                    f"SELECT * FROM {table} WHERE date LIKE ? AND factory = ?",
                    conn, params=(f"{y}%", fac_filter)
                )
            return pd.read_sql_query(
                f"SELECT * FROM {table} WHERE date LIKE ?",
                conn, params=(f"{y}%",)
            )
        else:
            scope = factory if rpt_scope == SCOPE_ACTIVE else ALL_FACTORIES
            return load_filtered(table, scope, d_start, d_end)

    r_prod    = get_report_df("production")
    r_sand    = get_report_df("sand")
    r_stock   = get_report_df("stock")
    r_sales   = get_report_df("sales")          # Dispatch table
    r_so      = get_report_df("sales_orders")   # new Sales table
    r_costs   = get_report_df("costs")

    rev_r      = r_sales["total"].sum()      if not r_sales.empty else 0
    so_rev_r   = r_so["total"].sum()         if not r_so.empty    else 0
    cost_r     = r_costs["amount"].sum()     if not r_costs.empty else 0
    prod_r     = r_prod["production"].sum()  if not r_prod.empty  else 0

    st.markdown(f"### {rpt_type} Report — "
                f"{'All Factories' if rpt_scope == SCOPE_ALL else factory} | {rpt_period}")
    st.markdown(f"<span style='font-size:12px;color:#8C7B62;'>Generated: "
                f"{datetime.datetime.now().strftime('%d %B %Y, %H:%M')}</span>",
                unsafe_allow_html=True)
    st.markdown("---")

    if rpt_type in ["Full Summary", "Production"]:
        k1, k2, k3 = st.columns(3)
        k1.metric(f"Total ({unit})", f"{from_mt(prod_r):,.2f}")
        k2.metric("Avg Efficiency",  f"{r_prod['efficiency'].mean():.4f}" if not r_prod.empty else "—")
        k3.metric("Batches",         len(r_prod))
        if not r_prod.empty:
            disp = r_prod.copy()
            disp["production"] = disp["production"].apply(lambda x: round(from_mt(x), 3))
            disp = disp.rename(columns={"production": f"Production ({unit})"})
            st.dataframe(paginate_df(disp.drop(columns=["id"], errors="ignore"), key="rpt_prod_pg"),
                         width='stretch', hide_index=True)

    if rpt_type in ["Full Summary", "Dispatch"]:
        st.markdown("#### Dispatch")
        k1, k2 = st.columns(2)
        k1.metric("Dispatched Value", fmt_inr(rev_r))
        k2.metric("Orders",           len(r_sales))
        if not r_sales.empty:
            st.dataframe(paginate_df(r_sales.drop(columns=["id"], errors="ignore"), key="rpt_disp_pg"),
                         width='stretch', hide_index=True)

    if rpt_type in ["Full Summary", "Sales Orders"]:
        st.markdown("#### Sales Orders")
        k1, k2 = st.columns(2)
        k1.metric("Sales Value", fmt_inr(so_rev_r))
        k2.metric("Orders",      len(r_so))
        if not r_so.empty:
            st.dataframe(paginate_df(r_so.drop(columns=["id"], errors="ignore"), key="rpt_so_pg"),
                         width='stretch', hide_index=True)

    if rpt_type in ["Full Summary", "Costs"]:
        st.markdown("#### Costs")
        k1, k2 = st.columns(2)
        k1.metric("Total Costs", fmt_inr(cost_r))
        k2.metric("Net P&L",     fmt_inr(rev_r + so_rev_r - cost_r))  # combined revenue
        if not r_costs.empty:
            st.dataframe(paginate_df(r_costs.drop(columns=["id"], errors="ignore"), key="rpt_cost_pg"),
                         width='stretch', hide_index=True)

    if rpt_type == "Sand" and not r_sand.empty:
        st.dataframe(paginate_df(r_sand.drop(columns=["id"], errors="ignore"), key="rpt_sand_pg"),
                     width='stretch', hide_index=True)

    if rpt_type == "Stock" and not r_stock.empty:
        st.dataframe(paginate_df(r_stock.drop(columns=["id"], errors="ignore"), key="rpt_stk_pg"),
                     width='stretch', hide_index=True)

    st.markdown("---")
    st.caption("Firstchoice Speciality Chemicals Pvt. Ltd. | support@fcsc.co.in | +91 33 3500 0230")

    st.markdown("#### Download Excel Report")
    buffer = BytesIO()
    scope_label = factory if rpt_scope == SCOPE_ACTIVE else "All"
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        for df_, sheet in [(r_prod,"Production"),(r_sand,"Sand"),
                            (r_stock,"Stock"),(r_sales,"Dispatch"),
                            (r_so,"Sales Orders"),(r_costs,"Costs")]:
            if not df_.empty:
                df_.drop(columns=["id"], errors="ignore").to_excel(writer, sheet_name=sheet, index=False)
        summary = pd.DataFrame({
            "Metric":  ["Dispatch Value", "Sales Orders Value", "Costs", "Net P&L",
                         f"Total Production ({unit})", "Avg Efficiency"],
            "Value":   [fmt_inr(rev_r), fmt_inr(so_rev_r), fmt_inr(cost_r),
                        fmt_inr(rev_r + so_rev_r - cost_r),  # combined revenue
                         f"{from_mt(prod_r):,.2f}",
                         f"{r_prod['efficiency'].mean():.4f}" if not r_prod.empty else "—"],
        })
        summary.to_excel(writer, sheet_name="Summary", index=False)
    buffer.seek(0)

    fname = f"FCSC_{scope_label}_{rpt_type.replace(' ','_')}_{datetime.date.today()}.xlsx"
    st.download_button(
        label="📥 Download Excel Report",
        data=buffer,
        file_name=fname,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    if _is_admin:
        st.markdown("---")
        st.markdown("#### 📧 Scheduled Email Digest")
        st.caption(
            "This button sends a summary digest immediately. Streamlit only runs while "
            "someone has the app open, so it can't fire an email on a timer by itself — "
            "for a real 'every morning at 8am' schedule, point an OS-level scheduler "
            "(cron / Windows Task Scheduler) at the standalone `digest_job.py` script "
            "included alongside this app instead."
        )
        dg1, dg2 = st.columns([2, 1])
        with dg1:
            digest_period = st.selectbox("Digest covers", ["Today", "Last 7 Days", "This Month"],
                                          key="digest_period")
        with dg2:
            st.write("")
            if st.button("📧 Send Digest Now", key="send_digest_btn", width='stretch'):
                sent, msg = send_digest_email(digest_period)
                (st.success if sent else st.warning)(msg)

        with st.expander("Manage digest recipients", expanded=False):
            _dg_recipients = get_digest_recipients()
            if _dg_recipients:
                for _email in _dg_recipients:
                    rcol1, rcol2 = st.columns([4, 1])
                    rcol1.write(_email)
                    if rcol2.button("🗑️", key=f"dg_rm_{_email}"):
                        remove_digest_recipient(_email)
                        st.rerun()
            else:
                st.caption("No recipients yet.")
            new_dg_email = st.text_input("Add recipient email", key="new_dg_email")
            if st.button("➕ Add", key="add_dg_email_btn"):
                ok, msg = add_digest_recipient(new_dg_email, st.session_state.username)
                (st.success if ok else st.error)(msg)
                if ok:
                    st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
#  CUSTOMERS  (admin only — master list of customers with GST details)
# ─────────────────────────────────────────────────────────────────────────────
elif module == "Customers":

    st.title("🏢 Customer Master")
    st.markdown(
        "<p style='color:#8C7B62;font-size:13px;margin-top:-10px;'>"
        "Manage customer records, GSTIN, and contact details. "
        "Customers added here appear in Dispatch and Sales dropdowns.</p>",
        unsafe_allow_html=True,
    )

    tab_add_cust, tab_view_cust, tab_edit_cust = st.tabs(
        ["➕ Add Customer", "📋 View Customers", "✏️ Edit Customer"]
    )

    with tab_add_cust:
        st.subheader("New Customer")
        ca1, ca2 = st.columns(2)
        with ca1:
            cust_name    = st.text_input("Customer / Company Name *", key="cn_name")
            cust_gstin   = st.text_input("GSTIN", placeholder="22AAAAA0000A1Z5", key="cn_gstin")
        with ca2:
            cust_phone   = st.text_input("Phone", placeholder="+91 98765 43210", key="cn_phone")
            cust_address = st.text_area("Address", height=80, key="cn_addr")

        if st.button("💾 Save Customer", key="cust_save"):
            if not cust_name.strip():
                st.warning("Customer name is required.")
            else:
                dup_c = pd.read_sql_query(
                    "SELECT id FROM customers WHERE name=?",
                    conn, params=(cust_name.strip(),)
                )
                if not dup_c.empty:
                    st.warning(f"⚠️ **{cust_name}** already exists in the customer master.")
                else:
                    try:
                        cur.execute(
                            "INSERT INTO customers(name,gstin,address,phone) VALUES (?,?,?,?)",
                            (cust_name.strip(), cust_gstin.strip(),
                             cust_address.strip(), cust_phone.strip())
                        )
                        conn.commit()
                        log_audit("INSERT", "customers", "new", cust_name.strip())
                        # Invalidate cache so dropdown updates immediately
                        load_customers.clear()
                        st.success(f"✅ Customer **{cust_name}** added.")
                        st.rerun()
                    except sqlite3.Error as e:
                        st.error(f"Database error: {e}")

    with tab_view_cust:
        st.subheader("All Customers")
        cust_all = pd.read_sql_query(
            "SELECT * FROM customers ORDER BY name", conn)
        if cust_all.empty:
            st.info("No customers yet. Add one using the ➕ Add Customer tab.")
        else:
            cv1, cv2 = st.columns(2)
            cv1.metric("Total Customers", len(cust_all))
            cv2.metric("With GSTIN",
                       len(cust_all[cust_all["gstin"].str.strip().str.len() > 0]))
            cust_search = search_filter(cust_all, "Search customers", key="cust_search")
            st.dataframe(
                cust_search.drop(columns=["id"], errors="ignore")
                           .rename(columns={"name":"Customer","gstin":"GSTIN",
                                            "address":"Address","phone":"Phone"}),
                width='stretch', hide_index=True, height=400
            )

            st.markdown("**Open a customer's 360° view**")
            st.caption("Orders, outstanding, last dispatch, products purchased, "
                        "payment history and documents — all in one page.")
            for _, _cr in cust_search.iterrows():
                crow1, crow2, crow3 = st.columns([4, 3, 1])
                crow1.markdown(f"🏢 **{_cr['name']}**")
                crow2.caption(_cr.get("gstin") or "No GSTIN on file")
                if crow3.button("360° →", key=f"cust360_{_cr['id']}", use_container_width=True):
                    open_detail_view("customer", _cr["name"])

            delete_row_ui(cust_all, "customers", "name", "cust")

    with tab_edit_cust:
        st.subheader("Edit a Customer")
        cust_all_e = pd.read_sql_query("SELECT * FROM customers ORDER BY name", conn)
        if cust_all_e.empty:
            st.info("No customers to edit yet.")
        else:
            cust_opts = {
                f"{r['name']}": r["id"] for _, r in cust_all_e.iterrows()
            }
            sel_cust_lbl = st.selectbox("Select customer", list(cust_opts.keys()),
                                         key="cust_edit_sel")
            sel_cust_id  = cust_opts[sel_cust_lbl]
            sel_cust_row = cust_all_e[cust_all_e["id"] == sel_cust_id].iloc[0]

            ce1, ce2 = st.columns(2)
            with ce1:
                e_cust_name  = st.text_input("Name",
                    value=sel_cust_row["name"], key="e_cn_name")
                e_cust_gstin = st.text_input("GSTIN",
                    value=str(sel_cust_row.get("gstin","") or ""), key="e_cn_gstin")
            with ce2:
                e_cust_phone = st.text_input("Phone",
                    value=str(sel_cust_row.get("phone","") or ""), key="e_cn_phone")
                e_cust_addr  = st.text_area("Address",
                    value=str(sel_cust_row.get("address","") or ""),
                    height=80, key="e_cn_addr")

            if st.button("💾 Update Customer", key="cust_upd_btn"):
                if not e_cust_name.strip():
                    st.warning("Name is required.")
                else:
                    try:
                        cur.execute(
                            "UPDATE customers SET name=?,gstin=?,address=?,phone=? WHERE id=?",
                            (e_cust_name.strip(), e_cust_gstin.strip(),
                             e_cust_addr.strip(), e_cust_phone.strip(), sel_cust_id)
                        )
                        conn.commit()
                        log_audit("UPDATE", "customers", sel_cust_id, e_cust_name.strip())
                        load_customers.clear()
                        st.success("✅ Customer updated.")
                        st.rerun()
                    except sqlite3.Error as e:
                        st.error(f"Database error: {e}")


# ─────────────────────────────────────────────────────────────────────────────
#  PILOT DASHBOARD  (admin only — listed in ADMIN_MODULES, not in SUPERVISOR_MODULES)
#  The pilot's control room: who's actually using FC Central, where, on what,
#  what's breaking, and what people are asking for — one page instead of
#  having to ask around.
# ─────────────────────────────────────────────────────────────────────────────
elif module == "Pilot Dashboard":

    st.title("🚦 Pilot Dashboard")
    st.markdown(
        "<p style='color:#8A93A1;font-size:13px;margin-top:-10px;'>"
        "Live signal on pilot adoption — logins, module usage, errors and feedback. "
        "Visible to admins only.</p>",
        unsafe_allow_html=True,
    )

    _pd_users     = pd.read_sql_query("SELECT username, role, factory, display FROM users", conn)
    _pd_logins    = pd.read_sql_query("SELECT * FROM login_log ORDER BY id DESC", conn)
    _pd_modules   = pd.read_sql_query("SELECT * FROM module_usage ORDER BY id DESC", conn)
    _pd_errors    = pd.read_sql_query("SELECT * FROM app_errors ORDER BY id DESC", conn)
    _pd_feedback  = pd.read_sql_query("SELECT * FROM feedback ORDER BY id DESC", conn)
    _pd_today_str = datetime.date.today().isoformat()

    # ── top-line metrics ────────────────────────────────────────────────────
    _today_logins   = _pd_logins[_pd_logins["timestamp"].str[:10] == _pd_today_str] if not _pd_logins.empty else _pd_logins
    _users_today    = _today_logins["username"].nunique() if not _today_logins.empty else 0
    _total_users    = len(_pd_users)
    _errors_7d      = 0
    if not _pd_errors.empty:
        _cutoff = (datetime.datetime.now() - datetime.timedelta(days=7)).isoformat(timespec="seconds")
        _errors_7d = len(_pd_errors[_pd_errors["timestamp"] >= _cutoff])
    _pending_fb     = len(_pd_feedback[_pd_feedback["status"] == "pending"]) if not _pd_feedback.empty else 0

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Logged in today",   f"{_users_today} / {_total_users}")
    m2.metric("Total logins",      len(_pd_logins))
    m3.metric("Errors (7 days)",   _errors_7d)
    m4.metric("Pending feedback",  _pending_fb)
    m5.metric("Modules tracked",   _pd_modules["module"].nunique() if not _pd_modules.empty else 0)

    st.markdown("---")

    # ── plant-wise login counts ─────────────────────────────────────────────
    st.subheader("Plant-wise Login Counts")
    if _pd_logins.empty:
        st.info("No logins recorded yet.")
    else:
        _plant_counts = _pd_logins.copy()
        _plant_counts["factory"] = _plant_counts["factory"].fillna("Admin / HQ")
        _plant_counts = (_plant_counts.groupby("factory").size()
                          .reset_index(name="logins").sort_values("logins", ascending=False))
        pc1, pc2 = st.columns([3, 2])
        with pc1:
            if HAS_PLOTLY:
                fig_pc = px.bar(_plant_counts, x="factory", y="logins",
                                 template="plotly_white", title="Total logins by plant",
                                 color_discrete_sequence=["#2B4C7E"])
                fig_pc.update_layout(height=280, margin=dict(l=10, r=10, t=36, b=10))
                st.plotly_chart(fig_pc, width='stretch')
            else:
                st.bar_chart(_plant_counts.set_index("factory")["logins"])
        with pc2:
            st.dataframe(_plant_counts.rename(columns={"factory": "Plant", "logins": "Logins"}),
                         hide_index=True, width='stretch', height=280)

    st.markdown("---")

    # ── most-used modules ────────────────────────────────────────────────────
    st.subheader("Most-Used Modules")
    if _pd_modules.empty:
        st.info("No module views recorded yet.")
    else:
        _mod_counts = (_pd_modules.groupby("module").size()
                        .reset_index(name="views").sort_values("views", ascending=False))
        mc1, mc2 = st.columns([3, 2])
        with mc1:
            if HAS_PLOTLY:
                fig_mc = px.bar(_mod_counts.head(15), x="views", y="module", orientation="h",
                                 template="plotly_white", title="Views per module",
                                 color_discrete_sequence=["#1E6B45"])
                fig_mc.update_layout(height=320, margin=dict(l=10, r=10, t=36, b=10),
                                      yaxis=dict(categoryorder="total ascending"))
                st.plotly_chart(fig_mc, width='stretch')
            else:
                st.bar_chart(_mod_counts.set_index("module")["views"])
        with mc2:
            st.dataframe(_mod_counts.rename(columns={"module": "Module", "views": "Views"}),
                         hide_index=True, width='stretch', height=320)

    st.markdown("---")

    # ── errors reported ──────────────────────────────────────────────────────
    st.subheader("Errors Reported")
    if _pd_errors.empty:
        st.success("No errors logged. 🎉")
    else:
        ec1, ec2 = st.columns(2)
        ec1.metric("Total errors/warnings", len(_pd_errors))
        ec2.metric("Last 7 days", _errors_7d)

        def _lvl_pill(l: str) -> str:
            return {"ERROR": "🔴 ERROR", "CRITICAL": "🔴 CRITICAL",
                    "WARNING": "🟡 WARNING"}.get(l, l)

        _disp_err = _pd_errors.head(50).copy()
        _disp_err["level"] = _disp_err["level"].apply(_lvl_pill)
        st.dataframe(
            _disp_err[["timestamp", "level", "username", "message"]]
                .rename(columns={"timestamp": "Timestamp", "level": "Level",
                                  "username": "User", "message": "Message"}),
            hide_index=True, width='stretch', height=280
        )
        st.caption("Showing the 50 most recent. Full history also lives in fcsc_app.log on disk.")

    st.markdown("---")

    # ── pending feedback ─────────────────────────────────────────────────────
    st.subheader("Pending Feedback")
    if _pd_feedback.empty:
        st.info("No feedback submitted yet. Users can send feedback from the sidebar.")
    else:
        _pending = _pd_feedback[_pd_feedback["status"] == "pending"]
        if _pending.empty:
            st.success("Nothing pending — all feedback has been reviewed. 🎉")
        for _, _fb in _pending.iterrows():
            with st.container(border=True):
                fb1, fb2 = st.columns([5, 1])
                with fb1:
                    st.markdown(f"**{_fb['username']}** "
                                f"({_fb['factory'] or 'Admin'}) — "
                                f"<span style='color:#8A93A1;font-size:12px;'>"
                                f"{_fb['timestamp'][:16].replace('T',' ')}</span>",
                                unsafe_allow_html=True)
                    st.write(_fb["message"])
                with fb2:
                    if st.button("✅ Resolve", key=f"fb_resolve_{_fb['id']}"):
                        cur.execute("UPDATE feedback SET status='resolved' WHERE id=?", (_fb["id"],))
                        conn.commit()
                        st.rerun()

        with st.expander(f"Show resolved feedback ({len(_pd_feedback) - len(_pending)})"):
            _resolved = _pd_feedback[_pd_feedback["status"] != "pending"]
            if _resolved.empty:
                st.caption("None yet.")
            else:
                st.dataframe(
                    _resolved[["timestamp", "username", "factory", "message"]]
                        .rename(columns={"timestamp": "Timestamp", "username": "User",
                                          "factory": "Plant", "message": "Message"}),
                    hide_index=True, width='stretch'
                )

    st.markdown("---")

    # ── last login per user ──────────────────────────────────────────────────
    st.subheader("Last Login per User")
    if _pd_logins.empty:
        _last_login = pd.DataFrame(columns=["username", "timestamp"])
    else:
        _last_login = (_pd_logins.sort_values("timestamp")
                        .groupby("username", as_index=False).last()[["username", "timestamp"]])

    _user_summary = _pd_users.merge(_last_login, on="username", how="left")
    _user_summary["factory"] = _user_summary["factory"].fillna("Admin / HQ")
    _user_summary["timestamp"] = _user_summary["timestamp"].fillna("Never logged in")
    _user_summary = _user_summary.sort_values("timestamp", ascending=False)

    st.dataframe(
        _user_summary[["display", "username", "role", "factory", "timestamp"]]
            .rename(columns={"display": "Name", "username": "Username", "role": "Role",
                              "factory": "Plant", "timestamp": "Last Login"}),
        hide_index=True, width='stretch', height=300
    )

    _never = _user_summary[_user_summary["timestamp"] == "Never logged in"]
    if not _never.empty:
        st.warning(f"⚠️ {len(_never)} user(s) have never logged in: "
                   f"{', '.join(_never['display'].tolist())}")


# ─────────────────────────────────────────────────────────────────────────────
#  AUDIT TRAIL  (admin only — listed in ADMIN_MODULES, not in SUPERVISOR_MODULES)
# ─────────────────────────────────────────────────────────────────────────────
elif module == "Audit Trail":

    st.title("🔍 Audit Trail")
    st.markdown(
        "<p style='color:#8C7B62;font-size:13px;margin-top:-10px;'>"
        "Complete record of every INSERT, UPDATE and DELETE performed by all users.</p>",
        unsafe_allow_html=True,
    )

    # ── summary metrics ────────────────────────────────────────────────────
    audit_all = pd.read_sql_query(
        "SELECT * FROM audit_log ORDER BY id DESC", conn)

    if audit_all.empty:
        st.info("No audit events recorded yet. Events are logged as soon as data is added, edited or deleted.")
    else:
        a1, a2, a3, a4 = st.columns(4)
        a1.metric("Total Events",   len(audit_all))
        a2.metric("Inserts",        len(audit_all[audit_all["action"] == "INSERT"]))
        a3.metric("Updates",        len(audit_all[audit_all["action"] == "UPDATE"]))
        a4.metric("Deletes",        len(audit_all[audit_all["action"] == "DELETE"]))

        st.markdown("---")

        # ── filters ───────────────────────────────────────────────────────
        fc1, fc2, fc3 = st.columns(3)
        with fc1:
            all_users = sorted(audit_all["username"].unique().tolist())
            sel_user  = st.selectbox("Filter by User",
                                      ["All"] + all_users, key="at_user")
        with fc2:
            sel_action = st.selectbox("Filter by Action",
                                       ["All", "INSERT", "UPDATE", "DELETE"], key="at_action")
        with fc3:
            all_tables = sorted(audit_all["tbl"].unique().tolist())
            sel_table  = st.selectbox("Filter by Table",
                                       ["All"] + all_tables, key="at_table")

        filtered_audit = audit_all.copy()
        if sel_user   != "All": filtered_audit = filtered_audit[filtered_audit["username"] == sel_user]
        if sel_action != "All": filtered_audit = filtered_audit[filtered_audit["action"]   == sel_action]
        if sel_table  != "All": filtered_audit = filtered_audit[filtered_audit["tbl"]      == sel_table]

        st.caption(f"{len(filtered_audit)} event(s) matching current filters")

        # ── colour-code action column ──────────────────────────────────────
        def _action_icon(a: str) -> str:
            return {"INSERT": "➕ INSERT", "UPDATE": "✏️ UPDATE",
                    "DELETE": "🗑️ DELETE"}.get(a, a)

        disp_audit = filtered_audit.copy()
        disp_audit["action"]    = disp_audit["action"].apply(_action_icon)
        disp_audit["timestamp"] = disp_audit["timestamp"].str[:19]   # trim microseconds

        disp_audit = paginate_df(disp_audit, page_size=100, key="audit_page")
        st.dataframe(
            disp_audit.drop(columns=["id"], errors="ignore")
                      .rename(columns={
                          "timestamp": "Timestamp", "username": "User",
                          "action": "Action", "tbl": "Table",
                          "record_id": "Record ID", "detail": "Detail"
                      }),
            width='stretch', hide_index=True, height=460
        )

        st.markdown("---")

        # ── per-user activity chart ────────────────────────────────────────
        if HAS_PLOTLY and len(audit_all) > 0:
            ac1, ac2 = st.columns(2)
            with ac1:
                user_counts = (audit_all.groupby(["username","action"])
                               .size().reset_index(name="count"))
                fig_u = px.bar(user_counts, x="username", y="count", color="action",
                               color_discrete_map={
                                   "INSERT": "#145C3C",
                                   "UPDATE": "#1E3A5F",
                                   "DELETE": "#6E1423",
                               },
                               template="plotly_white",
                               title="Activity by User",
                               labels={"username":"User","count":"Events","action":"Action"})
                fig_u.update_layout(height=260, margin=dict(l=10,r=10,t=36,b=10),
                                     legend=dict(orientation="h", y=-0.25))
                st.plotly_chart(fig_u, width='stretch')

            with ac2:
                tbl_counts = (audit_all.groupby("tbl")
                              .size().reset_index(name="count")
                              .sort_values("count", ascending=False))
                fig_t = px.pie(tbl_counts, names="tbl", values="count", hole=0.4,
                               color_discrete_sequence=[
                                   "#6E1423","#1E3A5F","#145C3C",
                                   "#A8791E","#5B2C6F","#4A7A80"],
                               template="plotly_white",
                               title="Events by Table")
                fig_t.update_layout(height=260, margin=dict(l=10,r=10,t=36,b=10))
                st.plotly_chart(fig_t, width='stretch')

        # ── export audit log ───────────────────────────────────────────────
        st.markdown("---")
        audit_buf = BytesIO()
        with pd.ExcelWriter(audit_buf, engine="openpyxl") as writer:
            audit_all.drop(columns=["id"], errors="ignore").to_excel(
                writer, sheet_name="Audit Log", index=False)
        audit_buf.seek(0)
        st.download_button(
            label="📥 Export Audit Log (Excel)",
            data=audit_buf,
            file_name=f"FCSC_AuditLog_{datetime.date.today()}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )