"""fcsc_core — pure, side-effect-free logic extracted from app.py.

NEW: app.py is a single ~15k-line Streamlit script that executes UI code
and opens a real database connection at import time, which makes it
effectively impossible to unit test directly (importing it means running
the login page). Rather than fight that with a fragile fake-streamlit
mocking harness, the handful of functions here that are pure computation —
no `st.*` calls, no database access, no side effects — live in this
module instead. app.py imports them from here, and test_fcsc_core.py
exercises them directly. This is also the natural first step if a future
refactor wants to pull more logic out of app.py incrementally.
"""
from __future__ import annotations

import datetime
import hashlib
import hmac
import secrets

# ── Password hashing ─────────────────────────────────────────────────────
# scrypt is a slow, purpose-built password KDF, salted per-user, so the
# same password never hashes the same way twice and can't be cracked with
# precomputed rainbow tables the way a single fast hash (e.g. plain
# SHA-256) can be.
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2 ** 14, 8, 1


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt,
                             n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32)
    return f"{salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, digest_hex = stored.split("$")
        salt = bytes.fromhex(salt_hex)
        candidate = hashlib.scrypt(password.encode(), salt=salt,
                                    n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32)
        # Constant-time comparison — avoids leaking timing information about
        # how many bytes of the hash matched.
        return hmac.compare_digest(candidate.hex(), digest_hex)
    except Exception:
        return False


# ── GST invoice numbering ────────────────────────────────────────────────
def financial_year_label(d: datetime.date) -> str:
    """India's financial year runs 1 Apr - 31 Mar, conventionally labelled
    e.g. "24-25" for Apr 2024 - Mar 2025."""
    start_year = d.year if d.month >= 4 else d.year - 1
    return f"{start_year % 100:02d}-{(start_year + 1) % 100:02d}"


def format_invoice_no(prefix: str, fy: str, seq: int) -> str:
    return f"{prefix}/{fy}/{seq:05d}"
