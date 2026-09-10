"""Compatibility wrapper for conservative regulatory-table extractors.

The Streamlit app imports both candidate builders from this module. PSM Annex
13 and CAP Appendix 3 each use a dedicated fail-closed parser validated against
their current monitored official PDFs.
"""

from __future__ import annotations

from .cap_app3_parser import build_cap_accident_quantity_candidate
from .psm_annex13_parser import build_psm_annex13_candidate

__all__ = [
    "build_psm_annex13_candidate",
    "build_cap_accident_quantity_candidate",
]
