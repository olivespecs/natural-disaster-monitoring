"""
Bug condition exploration tests for frontend-model-update bugfix spec.

These tests are written against UNFIXED code and are EXPECTED TO FAIL.
Failure confirms the bugs exist. DO NOT fix the code to make these pass.

Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5
"""
from pathlib import Path
from html.parser import HTMLParser


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

WORKSPACE_ROOT = Path(__file__).parent.parent
CURRENT_MODEL = "gemma-4-26b-a4b-it"
LEGACY_MODEL_TOKENS = ("gemini", "1.5", "flash")

REQUIRED_DOM_IDS = {
    "header-clock",
    "s-total",
    "s-critical",
    "s-high",
    "s-processed",
    "inference-badge",
    "inference-icon",
    "inference-label",
    "filter-all",
    "filter-critical",
    "modal-backdrop",
    "modal-body",
    "event-feed",
    "feed-badge",
    "cat-chart",
    "risk-chart",
    "q-queued",
    "q-started",
    "q-finished",
    "q-failed",
    "worker-label",
    "last-poll",
    "next-poll",
    "poll-fill",
    "map",
}


class IDCollector(HTMLParser):
    """Collect all id= attribute values and inline <script> text from HTML."""

    def __init__(self):
        super().__init__()
        self.ids: set[str] = set()
        self.script_blocks: list[str] = []
        self._in_script = False
        self._current_script: list[str] = []

    def handle_starttag(self, tag, attrs):
        attr_dict = dict(attrs)
        if "id" in attr_dict:
            self.ids.add(attr_dict["id"])
        if tag == "script":
            # Only collect inline scripts (no src attribute)
            if "src" not in attr_dict:
                self._in_script = True
                self._current_script = []

    def handle_endtag(self, tag):
        if tag == "script" and self._in_script:
            self._in_script = False
            self.script_blocks.append("".join(self._current_script))
            self._current_script = []

    def handle_data(self, data):
        if self._in_script:
            self._current_script.append(data)


# ---------------------------------------------------------------------------
# Bug A — Wrong model name in source files
# ---------------------------------------------------------------------------

def test_config_py_contains_correct_model_name():
    """
    Bug A: app/config.py should contain the current Gemini model name.
    Validates: Requirement 1.1
    """
    content = (WORKSPACE_ROOT / "app" / "config.py").read_text()
    assert CURRENT_MODEL in content, (
        f"COUNTEREXAMPLE: '{CURRENT_MODEL}' not found in app/config.py."
    )


def test_models_py_does_not_contain_old_model_name():
    """
    Bug A: app/models.py comment should not reference the legacy model name.
    Validates: Requirement 1.2
    """
    content = (WORKSPACE_ROOT / "app" / "models.py").read_text()
    assert all(token not in content for token in LEGACY_MODEL_TOKENS), (
        "COUNTEREXAMPLE: legacy model tokens found in app/models.py. "
        "The inference_mode comment still references the old model name."
    )


def test_env_example_contains_correct_model_name():
    """
    Bug A: .env.example should show the current Gemini model value.
    Validates: Requirement 1.3
    """
    content = (WORKSPACE_ROOT / ".env.example").read_text()
    assert f"GEMINI_MODEL={CURRENT_MODEL}" in content, (
        f"COUNTEREXAMPLE: 'GEMINI_MODEL={CURRENT_MODEL}' not found in .env.example."
    )


# ---------------------------------------------------------------------------
# Bug B — Broken DOM structure in index.html
# ---------------------------------------------------------------------------

def _parse_index_html():
    html = (WORKSPACE_ROOT / "app" / "static" / "index.html").read_text()
    parser = IDCollector()
    parser.feed(html)
    return html, parser


def test_index_html_contains_all_required_dom_ids():
    """
    Bug B: index.html must contain every ID that app.js expects.
    EXPECTED TO FAIL on unfixed code (most IDs are absent).
    Validates: Requirements 1.4, 1.5
    """
    _, parser = _parse_index_html()
    missing = REQUIRED_DOM_IDS - parser.ids
    assert not missing, (
        f"COUNTEREXAMPLE: {len(missing)} required DOM IDs missing from index.html: "
        + ", ".join(sorted(missing))
    )


def test_index_html_does_not_load_tailwind_cdn():
    """
    Bug B: index.html must NOT load the Tailwind CDN script.
    EXPECTED TO FAIL on unfixed code (Tailwind CDN is present).
    Validates: Requirement 1.4
    """
    html, _ = _parse_index_html()
    assert "cdn.tailwindcss.com" not in html, (
        "COUNTEREXAMPLE: 'cdn.tailwindcss.com' found in index.html. "
        "Tailwind CDN is still loaded, conflicting with style.css."
    )


def test_index_html_has_no_inline_websocket_script():
    """
    Bug B: No inline <script> block in index.html should open a WebSocket.
    EXPECTED TO FAIL on unfixed code (inline WS logic is present).
    Validates: Requirement 1.4
    """
    _, parser = _parse_index_html()
    offending = [
        block for block in parser.script_blocks if "new WebSocket(" in block
    ]
    assert not offending, (
        f"COUNTEREXAMPLE: {len(offending)} inline <script> block(s) contain "
        "'new WebSocket(' in index.html. Inline WebSocket logic duplicates app.js."
    )


# ---------------------------------------------------------------------------
# Preservation — Property 3: Env-var override always wins
# ---------------------------------------------------------------------------

import os
import sys

from hypothesis import given, settings as h_settings
from hypothesis import strategies as st


def _settings_with_env(model_value: str):
    """Instantiate Settings with GEMINI_MODEL set in the environment."""
    # Temporarily patch the environment so pydantic-settings picks it up
    old = os.environ.get("GEMINI_MODEL")
    os.environ["GEMINI_MODEL"] = model_value
    try:
        # Force a fresh import / instantiation (avoid module-level singleton)
        from app.config import Settings
        s = Settings()
        return s.gemini_model
    finally:
        if old is None:
            del os.environ["GEMINI_MODEL"]
        else:
            os.environ["GEMINI_MODEL"] = old


@given(v=st.text(min_size=1, alphabet=st.characters(blacklist_categories=("Cs",), blacklist_characters="\x00")))
@h_settings(max_examples=100)
def test_env_override_always_wins(v):
    """
    Property 3: For any non-empty string v, setting GEMINI_MODEL=v in the
    environment means Settings().gemini_model == v (env override beats default).

    EXPECTED TO PASS on unfixed code (confirms baseline to preserve).
    Validates: Requirement 3.1

    **Validates: Requirements 3.1**
    """
    result = _settings_with_env(v)
    assert result == v, (
        f"COUNTEREXAMPLE: GEMINI_MODEL='{v}' in env but Settings().gemini_model='{result}'"
    )


# ---------------------------------------------------------------------------
# Preservation — Property 4: Non-affected files are byte-for-byte unchanged
# ---------------------------------------------------------------------------

def test_test_eonet_retry_is_readable():
    """
    Non-interference: tests/test_eonet_retry.py must exist and be readable.
    Validates: Requirement 3.2
    """
    path = WORKSPACE_ROOT / "tests" / "test_eonet_retry.py"
    assert path.exists(), "tests/test_eonet_retry.py does not exist"
    content = path.read_bytes()
    assert len(content) > 0, "tests/test_eonet_retry.py is empty"


def test_test_gemini_fallback_is_readable():
    """
    Non-interference: tests/test_gemini_fallback.py must exist and be readable.
    Validates: Requirement 3.2
    """
    path = WORKSPACE_ROOT / "tests" / "test_gemini_fallback.py"
    assert path.exists(), "tests/test_gemini_fallback.py does not exist"
    content = path.read_bytes()
    assert len(content) > 0, "tests/test_gemini_fallback.py is empty"


def test_app_js_is_readable():
    """
    Non-interference: app/static/app.js must exist and be readable.
    Validates: Requirement 3.4
    """
    path = WORKSPACE_ROOT / "app" / "static" / "app.js"
    assert path.exists(), "app/static/app.js does not exist"
    content = path.read_bytes()
    assert len(content) > 0, "app/static/app.js is empty"


def test_style_css_is_readable():
    """
    Non-interference: app/static/style.css must exist and be readable.
    Validates: Requirement 3.4
    """
    path = WORKSPACE_ROOT / "app" / "static" / "style.css"
    assert path.exists(), "app/static/style.css does not exist"
    content = path.read_bytes()
    assert len(content) > 0, "app/static/style.css is empty"
