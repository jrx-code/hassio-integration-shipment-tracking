"""Process-wide SSL context for blocking urllib carrier clients.

``ssl.create_default_context()`` loads system CAs (``load_default_certs`` /
``set_default_verify_paths``) and is blocking. Home Assistant flags that when
it runs on the event loop. Every carrier client here is urllib-based and only
called from an executor, but a fresh ``create_default_context`` per client
still races the first poll; warming one shared context off the loop during
setup (see ``async_setup_entry``) clears the warning.

Prefer Home Assistant's cached ``client_context()`` when available — core
builds it during bootstrap — and fall back to stdlib for unit tests.
"""
from __future__ import annotations

import ssl

_context: ssl.SSLContext | None = None


def create_ssl_context() -> ssl.SSLContext:
    """Build (or reuse HA's) client SSL context. Call from an executor."""
    try:
        from homeassistant.util.ssl import client_context

        return client_context()
    except ImportError:
        return ssl.create_default_context()


def set_ssl_context(ctx: ssl.SSLContext) -> None:
    """Install the process-wide context (called once from setup, off-loop)."""
    global _context
    _context = ctx


def get_ssl_context() -> ssl.SSLContext:
    """Return the shared context, creating a stdlib fallback if unset.

    The fallback path is for unit tests and any call that somehow races setup;
    production setup warms the context via ``set_ssl_context`` first.
    """
    global _context
    if _context is None:
        _context = create_ssl_context()
    return _context
