from __future__ import annotations

"""Make the CURRENT approved law.go.kr CAP template outrank stale project copies.

The report engine still accepts a project-uploaded official template as a manual
fallback. Once the central legal archive contains a CURRENT approved CAP form,
that version becomes the runtime source of truth so an older project attachment
cannot silently override a newly amended legal form.
"""

from typing import Any, Mapping


def install_current_cap_template_priority() -> None:
    from . import cap_hwpx

    if getattr(cap_hwpx, "_current_template_priority_installed", False):
        return

    original_registered = cap_hwpx.registered_cap_template

    def registered_cap_template_current_first(project) -> Mapping[str, Any] | None:
        current = cap_hwpx._approved_current_cap_template_meta()
        if current is not None:
            return current
        return original_registered(project)

    cap_hwpx.registered_cap_template = registered_cap_template_current_first
    cap_hwpx._current_template_priority_installed = True
