"""Optional shared-passphrase gate for the whole app.

This app has no user accounts and is deployed with a public, unauthenticated
URL. Until it is rewritten as a FastAPI + React PWA, a single shared
passphrase is enough to keep it off search engines and randos -- it is not a
substitute for real auth, and it does not protect everything: uploaded player
avatars are served by Streamlit's media endpoint at unguessable-but-unguarded
URLs regardless of whether the visitor ever passed this gate.

Deleting this file and its one call site in app.py fully removes the gate.
"""

from __future__ import annotations

import os
import secrets

import streamlit as st

SESSION_KEY = "wingspan_authenticated"


def required_passphrase() -> str:
    """The configured passphrase, or "" if the gate is turned off.

    Reading this fresh (rather than caching it) matters for the empty-string
    check below: an operator who unsets the secret and restarts the app
    should get an open app back, not a locked one nobody can pass.
    """
    return os.environ.get("WINGSPAN_PASSPHRASE", "")


def check_passphrase(attempt: str, expected: str) -> bool:
    """Constant-time comparison so a wrong guess can't be timed to leak
    how many leading characters it got right.

    Compared as UTF-8 bytes rather than as str: compare_digest only accepts
    ASCII-only strings and raises TypeError otherwise, which would take the
    login page down for anyone who chose a passphrase with an accent or an
    emoji in it.
    """
    return secrets.compare_digest(attempt.encode("utf-8"), expected.encode("utf-8"))


def require_passphrase() -> None:
    """Block the rest of the script until the passphrase is entered.

    A no-op when WINGSPAN_PASSPHRASE is unset or empty, so local dev and the
    test suite never need it set. Must run before anything else that renders
    page content, because Streamlit re-executes this whole script on every
    interaction -- there is no "already past this point" to rely on.
    """
    expected = required_passphrase()
    if not expected:
        return
    if st.session_state.get(SESSION_KEY):
        return

    st.title("🐦 Wingspan Scores")
    # A form, so the phone keyboard's "Go" key submits rather than just
    # dismissing itself and leaving the button to be found by hand.
    with st.form("passphrase", border=False):
        attempt = st.text_input("Passphrase", type="password")
        if st.form_submit_button("Enter", type="primary", width="stretch"):
            if check_passphrase(attempt, expected):
                st.session_state[SESSION_KEY] = True
                st.rerun()
            st.error("Wrong passphrase.")
    st.stop()
