from __future__ import annotations

"""Make the CURRENT approved law.go.kr CAP template the layout authority.

A project-uploaded official template is allowed only as a fallback while the
central CAP legal source is not CURRENT. Once law.go.kr has been refreshed and
approved as CURRENT, an older project copy must never silently reappear merely
because the new official HWP/HWPX cannot be mapped by the current template
engine. In that case report generation fails closed until the new form mapping
is supported.
"""

from typing import Any, Mapping


def install_current_cap_template_priority() -> None:
    from ..law_attachment_archive import approved_source_is_current
    from . import cap_hwpx

    if getattr(cap_hwpx, "_current_template_priority_installed", False):
        return

    original_registered = cap_hwpx.registered_cap_template

    def registered_cap_template_current_first(project) -> Mapping[str, Any] | None:
        current = cap_hwpx._approved_current_cap_template_meta()
        if current is not None:
            return current

        # A CURRENT central legal source exists, but no compatible current HWPX
        # could be resolved. Returning an older project template here would make
        # a newly amended form look successfully supported. Fail closed instead.
        if approved_source_is_current(cap_hwpx.CAP_LAW_SOURCE_KEY):
            return None

        return original_registered(project)

    cap_hwpx.registered_cap_template = registered_cap_template_current_first
    cap_hwpx._current_template_priority_installed = True
