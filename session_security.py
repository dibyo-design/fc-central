"""
session_security.py
--------------------
Server-side session security for FCSC ERP on Streamlit Community Cloud.

IMPORTANT LIMITATION — read before assuming this covers "HTTPS-only
cookies":
Streamlit Community Cloud already serves the app over HTTPS, so
transport security is covered. But Streamlit does not give your script
control over HTTP response headers, so you cannot set real
`Secure` / `HttpOnly` cookie flags from here — that requires a reverse
proxy (nginx) in front of the app, which only exists if you self-host.

The safest available substitute on Community Cloud is to NOT use a
browser cookie for session state at all. This module keeps session
data in `st.session_state`, which lives server-side in memory and is
never exposed to client-side JavaScript or the browser's cookie jar.
The tradeoff: the session doesn't survive a browser refresh across a
full app restart, and there's no "remember me" — the user re-logs-in
each new browser session. That's the correct tradeoff for an ERP
handling production/costing data.

INTEGRATION:
1. Call init_session_security() once, right after a successful login.
2. Call enforce_session_timeout(timeout_minutes=30) at the top of
   every page/tab render (before showing any protected content).
3. Call touch_session() on any user interaction if you want activity
   (not just page loads) to reset the timer — usually not necessary
   since Streamlit reruns on every interaction anyway.
"""

from datetime import datetime, timedelta

import streamlit as st


DEFAULT_TIMEOUT_MINUTES = 30


def init_session_security(username: str = None):
    """Call immediately after successful login."""
    now = datetime.utcnow()
    st.session_state["session_login_time"] = now
    st.session_state["session_last_activity"] = now
    if username:
        st.session_state["session_username"] = username


def touch_session():
    """Refresh the activity timestamp. Called automatically by enforce_session_timeout."""
    st.session_state["session_last_activity"] = datetime.utcnow()


def enforce_session_timeout(timeout_minutes: int = DEFAULT_TIMEOUT_MINUTES):
    """
    Call at the top of every protected page. Logs the user out and
    stops rendering if they've been idle too long. Returns True if the
    session is valid, False if it just expired (caller should st.stop()).
    """
    last_activity = st.session_state.get("session_last_activity")

    if last_activity is None:
        # No active session at all — let the normal login gate handle it.
        return True

    idle_for = datetime.utcnow() - last_activity

    if idle_for > timedelta(minutes=timeout_minutes):
        _expire_session()
        st.warning("Your session expired due to inactivity. Please log in again.")
        st.stop()
        return False

    touch_session()
    return True


def _expire_session():
    """Clear auth-related session state without nuking unrelated app state."""
    for key in ["logged_in", "session_username", "session_login_time",
                "session_last_activity", "user_role", "auth_token"]:
        st.session_state.pop(key, None)


def render_session_status(sidebar: bool = True):
    """Optional: small session countdown indicator in the sidebar."""
    last_activity = st.session_state.get("session_last_activity")
    if not last_activity:
        return
    target = sidebar and st.sidebar or st
    minutes_idle = (datetime.utcnow() - last_activity).total_seconds() / 60
    target.caption(f"Session active — idle {minutes_idle:.0f} min")
