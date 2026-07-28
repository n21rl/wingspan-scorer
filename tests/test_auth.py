"""The passphrase gate: off by default, constant-time when on.

These exercise the gate logic directly rather than driving the Streamlit
UI -- require_passphrase() only calls st.stop()/st.rerun(), which are not
meaningfully testable outside a running app, but the decision it makes is.
"""

from __future__ import annotations

import secrets

from wingspan import auth


def test_no_passphrase_set_means_the_gate_is_off(monkeypatch):
    monkeypatch.delenv("WINGSPAN_PASSPHRASE", raising=False)
    assert auth.required_passphrase() == ""


def test_empty_passphrase_also_means_the_gate_is_off(monkeypatch):
    monkeypatch.setenv("WINGSPAN_PASSPHRASE", "")
    assert auth.required_passphrase() == ""


def test_passphrase_set_is_read_back_verbatim(monkeypatch):
    monkeypatch.setenv("WINGSPAN_PASSPHRASE", "let-the-birds-in")
    assert auth.required_passphrase() == "let-the-birds-in"


def test_correct_passphrase_passes():
    assert auth.check_passphrase("let-the-birds-in", "let-the-birds-in")


def test_wrong_passphrase_fails():
    assert not auth.check_passphrase("guess", "let-the-birds-in")


def test_wrong_passphrase_of_different_length_fails():
    assert not auth.check_passphrase("", "let-the-birds-in")


def test_check_passphrase_uses_compare_digest(monkeypatch):
    """Pin the implementation to secrets.compare_digest, not `==`, so a
    future edit can't silently reintroduce a timing side channel."""
    calls = []
    real_compare_digest = secrets.compare_digest

    def spy(a, b):
        calls.append((a, b))
        return real_compare_digest(a, b)

    monkeypatch.setattr(auth.secrets, "compare_digest", spy)
    auth.check_passphrase("attempt", "expected")
    # As bytes: compare_digest rejects non-ASCII str, so the gate encodes
    # first and a passphrase with an accent in it doesn't raise TypeError.
    assert calls == [(b"attempt", b"expected")]


def test_non_ascii_passphrase_is_comparable():
    """compare_digest raises TypeError on non-ASCII str, which would take the
    login page down rather than just rejecting the attempt."""
    assert auth.check_passphrase("mésange-huppée", "mésange-huppée")
    assert not auth.check_passphrase("mésange", "mésange-huppée")
