"""Compatibility wrapper for conservative regulatory-table extractors.

The Streamlit app imports fail-closed candidate builders from this module.
PSM Annex 13 and CAP Appendices 2/3 each use dedicated parsers validated against
their current monitored official PDFs. Candidate extraction never equals legal
approval; an administrator must review before the table becomes decision data.
"""

from __future__ import annotations

from .cap_app2_parser import build_cap_appendix2_candidate
from .cap_app3_parser import build_cap_accident_quantity_candidate
from .psm_annex13_parser import build_psm_annex13_candidate

__all__ = [
    "build_psm_annex13_candidate",
    "build_cap_appendix2_candidate",
    "build_cap_accident_quantity_candidate",
]
