"""Core modules for the chemical safety planning assistant.

UI side effects intentionally do not live in this package.  Download buttons,
Streamlit widgets and other presentation logic belong under ``ui/`` so engine
imports remain deterministic in the app and in tests.
"""

from __future__ import annotations
