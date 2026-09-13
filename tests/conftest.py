"""Fake CDF clients, so handler logic can be tested without a project.

The argument for these tests is narrow and worth stating. They do **not** test that
CDF behaves as documented -- only a live run does that, which is what `tools/live_e2e.py`
is for. They test the part of a handler that is *pure decision*: which rung resolved a
file, whether a human's veto is honoured, what gets retracted, how a score is banded.

That logic is where the expensive bugs have actually been, and it is exactly the part
a live run is worst at exercising: reaching the middle confidence band, or the
rule-removed case, requires contriving data in a real project and waiting minutes per
attempt. Here it is a dictionary and a millisecond.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys
import types

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
REFERENCE = ROOT / "training" / "modules" / "reference" / "functions"


def load_handler(function_dir: str) -> types.ModuleType:
    """Import a reference handler by path, the way Cognite Functions does."""
    path = REFERENCE / function_dir / "handler.py"
    spec = importlib.util.spec_from_file_location(f"handler_{function_dir}", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FakeRow:
    def __init__(self, key: str, columns: dict):
        self.key = key
        self.columns = columns


class FakeRaw:
    """Just enough of client.raw to serve mapping rules."""

    def __init__(self, tables: dict[tuple[str, str], list[FakeRow]]):
        self._tables = tables
        self.rows = self

    def list(self, db_name=None, table_name=None, limit=None):
        try:
            return self._tables[(db_name, table_name)]
        except KeyError:
            # RAW raises on an unknown table; the handler must treat that as "no rules"
            raise RuntimeError(f"table {db_name}.{table_name} does not exist")


class FakeClient:
    def __init__(self, raw_tables=None):
        self.raw = FakeRaw(raw_tables or {})


@pytest.fixture(scope="session")
def match_documents():
    return load_handler("fnc_REFERENCE_Training_MatchDocuments")


@pytest.fixture(scope="session")
def quality_gate():
    return load_handler("fnc_REFERENCE_Training_QualityGate")


@pytest.fixture
def rules_table():
    return [
        FakeRow("rule-001", {
            "sourcePattern": "TRN-21-SEP-PID.pdf",
            "targetExternalId": "TRN-21-SEP",
            "matchType": "exact",
            "addedBy": "course", "reason": "the P&ID carries no tag"}),
        FakeRow("rule-002", {
            "sourcePattern": "^TRN-21-PA-2001A-Datasheet",
            "targetExternalId": "21-PA-2001A",
            "matchType": "regex",
            "addedBy": "course", "reason": "vendor naming"}),
    ]
