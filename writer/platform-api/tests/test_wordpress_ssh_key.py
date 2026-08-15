"""WordPress SSH private-key normalization.

Pasting a multi-line PEM / OpenSSH key into a KEY=VALUE env editor mangles it in
ways asyncssh rejects as a bare "Invalid private key" (observed in production on
the WORDPRESS_SSH_PRIVATE_KEY var). `_normalize_private_key` coerces those back
to the exact bytes asyncssh expects; these pin that every mangling collapses to
the same clean key, and that a clean key passes through unchanged.

(CI-only: importing services.wordpress_publish pulls the config/settings chain.)
"""

from services.wordpress_publish import _normalize_private_key

_BODY = (
    "-----BEGIN OPENSSH PRIVATE KEY-----\n"
    "b3BlbnNzaC1rZXktdjEAAAAAdGVzdA==\n"
    "-----END OPENSSH PRIVATE KEY-----"
)
_WANT = _BODY + "\n"


def test_clean_key_passes_through():
    assert _normalize_private_key(_BODY) == _WANT


def test_literal_backslash_n_is_unescaped():
    assert _normalize_private_key(_BODY.replace("\n", "\\n")) == _WANT


def test_literal_crlf_escape_is_unescaped():
    assert _normalize_private_key(_BODY.replace("\n", "\\r\\n")) == _WANT


def test_real_crlf_is_collapsed_to_lf():
    # asyncssh's OpenSSH-format parser is CR-intolerant — this was the likely
    # production failure (a Windows/CRLF paste).
    out = _normalize_private_key(_BODY.replace("\n", "\r\n"))
    assert out == _WANT
    assert "\r" not in out


def test_stray_cr_is_collapsed_to_lf():
    out = _normalize_private_key(_BODY.replace("\n", "\r"))
    assert out == _WANT
    assert "\r" not in out


def test_surrounding_whitespace_is_trimmed():
    assert _normalize_private_key(_BODY + "\n\n  ") == _WANT


def test_empty_is_just_a_newline():
    # An unset key is guarded earlier (ssh_selftest returns before this); the
    # helper itself must not crash on empty.
    assert _normalize_private_key("") == "\n"
