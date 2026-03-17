"""Test persona compression (Strategy 1).

Validates that persona prompts use 300-char structured tags instead of 2000-char
free-form text, and that the OasisProfileGenerator no longer depends on Zep.
"""

import sys
import os
import types
import importlib.util

import pytest

# ---------------------------------------------------------------------------
# Bootstrap: import oasis_profile_generator without triggering the full
# app.services.__init__.py chain (which pulls in zep_cloud).
#
# Strategy: register lightweight stub packages for `app`, `app.config`,
# `app.utils`, `app.utils.logger`, and `app.services` so that the relative
# imports inside oasis_profile_generator.py resolve correctly.
# ---------------------------------------------------------------------------

_services_dir = os.path.normpath(
    os.path.join(os.path.dirname(__file__), os.pardir, "app", "services")
)


def _stub_package(name, parent=None):
    """Register a stub package module in sys.modules if not already present."""
    if name not in sys.modules:
        mod = types.ModuleType(name)
        mod.__path__ = []  # mark as package
        mod.__package__ = name
        sys.modules[name] = mod
    return sys.modules[name]


# Create the package hierarchy
_stub_package("app")
_stub_package("app.services")
_stub_package("app.utils")

# -- app.config stub -------------------------------------------------------
_config_mod = types.ModuleType("app.config")
_config_mod.__package__ = "app"


class _StubConfig:
    LLM_API_KEY = "test-key"
    LLM_BASE_URL = "http://localhost:8080/v1"
    LLM_MODEL_NAME = "test-model"


_config_mod.Config = _StubConfig
sys.modules["app.config"] = _config_mod

# -- app.utils.logger stub -------------------------------------------------
_logger_mod = types.ModuleType("app.utils.logger")
_logger_mod.__package__ = "app.utils"

import logging as _logging


def _get_logger(name="test"):
    return _logging.getLogger(name)


_logger_mod.get_logger = _get_logger
sys.modules["app.utils.logger"] = _logger_mod

# -- app.services.local_graph_service (real module) -------------------------
_lgs_spec = importlib.util.spec_from_file_location(
    "app.services.local_graph_service",
    os.path.join(_services_dir, "local_graph_service.py"),
    submodule_search_locations=[],
)
_lgs_mod = importlib.util.module_from_spec(_lgs_spec)
_lgs_mod.__package__ = "app.services"
sys.modules["app.services.local_graph_service"] = _lgs_mod
_lgs_spec.loader.exec_module(_lgs_mod)

# -- app.services.oasis_profile_generator (real module) ---------------------
_opg_spec = importlib.util.spec_from_file_location(
    "app.services.oasis_profile_generator",
    os.path.join(_services_dir, "oasis_profile_generator.py"),
    submodule_search_locations=[],
)
_opg_mod = importlib.util.module_from_spec(_opg_spec)
_opg_mod.__package__ = "app.services"
sys.modules["app.services.oasis_profile_generator"] = _opg_mod
_opg_spec.loader.exec_module(_opg_mod)

OasisProfileGenerator = _opg_mod.OasisProfileGenerator


# ---------------------------------------------------------------------------
# Helper: create a generator without calling __init__ (avoids OpenAI client)
# ---------------------------------------------------------------------------


def _make_generator():
    gen = OasisProfileGenerator.__new__(OasisProfileGenerator)
    # Set minimal attributes that prompt-building methods need
    gen.graph_service = None
    gen.graph_id = None
    return gen


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPersonaCompression:
    """Validate that persona prompts switched from 2000 to 300 chars."""

    def test_individual_prompt_300_chars(self):
        gen = _make_generator()
        prompt = gen._build_individual_persona_prompt(
            entity_name="Alice",
            entity_type="student",
            entity_summary="A student",
            entity_attributes={},
            context="",
        )
        assert "300" in prompt
        assert "2000" not in prompt

    def test_group_prompt_300_chars(self):
        gen = _make_generator()
        prompt = gen._build_group_persona_prompt(
            entity_name="MIT",
            entity_type="university",
            entity_summary="A university",
            entity_attributes={},
            context="",
        )
        assert "300" in prompt
        assert "2000" not in prompt

    def test_individual_prompt_has_structured_tags(self):
        gen = _make_generator()
        prompt = gen._build_individual_persona_prompt(
            entity_name="Alice",
            entity_type="student",
            entity_summary="A student",
            entity_attributes={},
            context="",
        )
        assert "[성격:" in prompt

    def test_group_prompt_has_structured_tags(self):
        gen = _make_generator()
        prompt = gen._build_group_persona_prompt(
            entity_name="MIT",
            entity_type="university",
            entity_summary="A university",
            entity_attributes={},
            context="",
        )
        assert "[성격:" in prompt

    def test_individual_prompt_contains_example(self):
        gen = _make_generator()
        prompt = gen._build_individual_persona_prompt(
            entity_name="Alice",
            entity_type="student",
            entity_summary="A student",
            entity_attributes={},
            context="",
        )
        assert "예시:" in prompt or "[행동:" in prompt

    def test_group_prompt_contains_example(self):
        gen = _make_generator()
        prompt = gen._build_group_persona_prompt(
            entity_name="MIT",
            entity_type="university",
            entity_summary="A university",
            entity_attributes={},
            context="",
        )
        assert "예시:" in prompt or "[행동:" in prompt


class TestZepRemoved:
    """Verify that Zep references are gone from the constructor."""

    def test_no_zep_client_attribute(self):
        gen = _make_generator()
        assert not hasattr(gen, "zep_client")

    def test_no_zep_api_key_attribute(self):
        gen = _make_generator()
        assert not hasattr(gen, "zep_api_key")

    def test_has_graph_service_attribute(self):
        gen = _make_generator()
        assert hasattr(gen, "graph_service")

    def test_search_returns_empty_without_service(self):
        """_search_zep_for_entity returns empty when graph_service is None."""
        gen = _make_generator()
        entity = _lgs_mod.EntityNode(
            uuid="test-uuid",
            name="Alice",
            labels=["Student", "Entity"],
            summary="A student",
            attributes={},
        )
        result = gen._search_zep_for_entity(entity)
        assert result == {"facts": [], "node_summaries": [], "context": ""}
