"""
ui_enhancements.py
-------------------
Favicon, branded loading screen, and branded 404/error page for FCSC ERP.

INTEGRATION:

1. FAVICON — pass your logo into st.set_page_config, first line of app.py:

    import streamlit as st
    st.set_page_config(
        page_title="FirstChoice Central",
        page_icon="assets/fcsc_favicon.png",   # local PNG/ICO, or a PIL Image, or an emoji
        layout="wide",
    )

   Put your logo (square, ideally 512x512 or 32x32 PNG) at
   assets/fcsc_favicon.png in your repo. This sets both the browser tab
   icon and the icon shown in Streamlit's multipage nav.

2. LOADING SCREEN — call render_loading_screen() as the very first
   Streamlit call after set_page_config, before any data loading:

    from ui_enhancements import render_loading_screen
    render_loading_screen()
    # ... your existing DB connects / data loads happen here ...

   It shows a full-screen branded overlay immediately, then fades out
   automatically once the rest of the page has rendered.

3. BRANDED 404 — Streamlit doesn't have real URL routing, so "404" in
   practice means: a bad/missing query param (e.g. ?record_id=99999
   that doesn't exist) or a bad deep link. Call render_not_found_page()
   wherever you currently do the equivalent of "if record not found:
   st.error(...)":

    from ui_enhancements import render_not_found_page
    record = fetch_batch_by_id(conn, batch_id)
    if record is None:
        render_not_found_page(context=f"Batch ID {batch_id}")
        st.stop()
"""

import streamlit as st


BRAND_RED = "#C41E3A"       # adjust to your actual FCSC brand red
BRAND_NAVY = "#1A2332"      # adjust to your actual navy-grey


def render_loading_screen():
    """Full-screen branded splash that fades out once the page finishes rendering."""
    st.markdown(
        f"""
        <style>
        @keyframes fcsc-fadeout {{
            0%   {{ opacity: 1; visibility: visible; }}
            85%  {{ opacity: 1; visibility: visible; }}
            100% {{ opacity: 0; visibility: hidden; }}
        }}
        @keyframes fcsc-spin {{
            to {{ transform: rotate(360deg); }}
        }}
        #fcsc-loading-overlay {{
            position: fixed;
            inset: 0;
            z-index: 999999;
            background: {BRAND_NAVY};
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            animation: fcsc-fadeout 1.4s ease forwards;
            animation-delay: 0.3s;
        }}
        #fcsc-loading-overlay .fcsc-title {{
            color: #fff;
            font-family: 'JetBrains Mono', monospace;
            letter-spacing: 0.15em;
            font-size: 1.4rem;
            margin-top: 1.2rem;
        }}
        #fcsc-loading-overlay .fcsc-spinner {{
            width: 42px;
            height: 42px;
            border: 3px solid rgba(255,255,255,0.2);
            border-top-color: {BRAND_RED};
            border-radius: 50%;
            animation: fcsc-spin 0.8s linear infinite;
        }}
        </style>
        <div id="fcsc-loading-overlay">
            <div class="fcsc-spinner"></div>
            <div class="fcsc-title">FIRSTCHOICE CENTRAL</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_not_found_page(context: str = None, back_label: str = "Back to Dashboard", back_page: str = None):
    """
    Branded 'not found' state for missing records or bad deep links.
    Call st.stop() right after this in your calling code.
    """
    st.markdown(
        f"""
        <style>
        .fcsc-404 {{
            text-align: center;
            padding: 4rem 1rem;
        }}
        .fcsc-404 .code {{
            font-family: 'JetBrains Mono', monospace;
            font-size: 4rem;
            font-weight: 700;
            color: {BRAND_RED};
            letter-spacing: 0.05em;
            line-height: 1;
        }}
        .fcsc-404 .bar {{
            width: 60px;
            height: 4px;
            background: {BRAND_RED};
            margin: 1.2rem auto;
            border-radius: 2px;
        }}
        .fcsc-404 .msg {{
            font-size: 1.1rem;
            color: #444;
            margin-top: 0.5rem;
        }}
        .fcsc-404 .ctx {{
            font-family: 'JetBrains Mono', monospace;
            color: #888;
            font-size: 0.9rem;
            margin-top: 0.4rem;
        }}
        </style>
        <div class="fcsc-404">
            <div class="code">404</div>
            <div class="bar"></div>
            <div class="msg">Record not found</div>
            {f'<div class="ctx">{context}</div>' if context else ''}
        </div>
        """,
        unsafe_allow_html=True,
    )
    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        if st.button(back_label, use_container_width=True):
            if back_page:
                st.switch_page(back_page)
            else:
                st.rerun()
