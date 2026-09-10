"""Compatibility wrapper for conservative regulatory-table extractors.

The Streamlit app imports both candidate builders from this module.  PSM Annex
13 now uses a dedicated semantic word-row parser because the official PDF has
stable item anchors but pdfplumber does not reliably expose each visual row as
a table row.  CAP Appendix 3 continues to use the existing fail-closed parser
until its own dedicated parser is validated.
"""

from __future__ import annotations

from .psm_annex13_parser import build_psm_annex13_candidate
from .regulatory_tables import build_cap_accident_quantity_candidate

__all__ = [
    "build_psm_annex13_candidate",
    "build_cap_accident_quantity_candidate",
]
