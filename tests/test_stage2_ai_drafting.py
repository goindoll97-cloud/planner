from __future__ import annotations

from io import BytesIO
from pathlib import Path
import unittest

from docx import Document

from engine.stage2.ai_drafting import (
    FakeJSONLLMClient if False else None,
)
