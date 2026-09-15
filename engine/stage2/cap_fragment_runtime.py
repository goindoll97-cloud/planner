from __future__ import annotations

"""Hardening for CURRENT CAP forms that are split across several official files.

The multi-form runtime intentionally allows one official HWPX to contain only a
subset of the CAP appendices, because law.go.kr can publish the statutory forms
as separate files.  The original builder, however, performs a monolithic
all-markers validation at entry.  This adapter relaxes that one check only while
an already-approved CURRENT split-form file is being filled.  All ordinary
manual/single-template validation remains strict.
"""

from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from io import StringIO
from threading import RLock

from . import cap_hwpx
from . import cap_multi_form_runtime as multi


WRAPPER_MARKER = "_cap_fragment_runtime_wrapper"
_VALIDATION_LOCK = RLock()


def _partial_builder_threadsafe(original_build):
    strict_validation = cap_hwpx.validate_cap_hwpx_template

    def relaxed_validation(data: bytes):
        validation = strict_validation(data)
        if validation.found_markers:
            return replace(validation, ok=True)
        return validation

    def build_partial(project, template_bytes: bytes | None = None):
        if template_bytes is None:
            return original_build(project)
        # cap_hwpx.build_cap_hwpx_draft resolves validate_cap_hwpx_template from
        # the module globals at call time.  Swap it only inside a lock and always
        # restore it, avoiding the fragile FunctionType/global-copy shortcut.
        with _VALIDATION_LOCK:
            current = cap_hwpx.validate_cap_hwpx_template
            cap_hwpx.validate_cap_hwpx_template = relaxed_validation
            try:
                return original_build(project, template_bytes=template_bytes)
            finally:
                cap_hwpx.validate_cap_hwpx_template = current

    return build_partial


def install_cap_fragment_runtime() -> None:
    if bool(getattr(multi, "_cap_fragment_runtime_installed", False)):
        return

    multi._partial_builder = _partial_builder_threadsafe

    current_convert = cap_hwpx.convert_hwp_to_hwpx
    if not bool(getattr(current_convert, WRAPPER_MARKER, False)):
        def quiet_convert(file_bytes: bytes, file_name: str) -> bytes:
            # pyhwpx prints its FilePathCheckerModule DLL path during COM setup.
            # It is diagnostic noise, not a user prompt or AI message.
            sink = StringIO()
            with redirect_stdout(sink), redirect_stderr(sink):
                return current_convert(file_bytes, file_name)

        setattr(quiet_convert, WRAPPER_MARKER, True)
        cap_hwpx.convert_hwp_to_hwpx = quiet_convert

    multi._cap_fragment_runtime_installed = True
