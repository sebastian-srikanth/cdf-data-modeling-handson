"""The entity-matching rung.

These exist because of a bug that shipped and survived every other test: a loop
variable named `prior` shadowed the dict of existing suggestions, so the first
entity-matching result turned `prior` into a string and the retraction step crashed
on it. Every test passed, because on this lab's two documents the mapping rules
resolve everything and this code path never runs.

That is the trap worth naming: **the rung you exercise least is the rung that breaks.**
A cascade is designed so the expensive path is rare, which means the expensive path is
also the least tested — by construction, not by neglect.
"""
import sys
import types

import pytest


class FakeRow:
    def __init__(self, key, columns):
        self.key, self.columns = key, columns


class FakeRaw:
    def __init__(self, rows):
        self._rows, self.rows = rows, self

    def list(self, db_name=None, table_name=None, limit=None):
        return self._rows


class FakeNode:
    def __init__(self, external_id, props, view):
        self.external_id, self.space = external_id, "isp_X_TRN"
        self.properties = {view: props}


class FakeInstances:
    def __init__(self, files, assets, suggestions, view_file, view_asset, view_sug):
        self._files, self._assets, self._sugs = files, assets, suggestions
        self._vf, self._va, self._vs = view_file, view_asset, view_sug
        self.applied = []

    def retrieve_nodes(self, nodes=None, sources=None):
        return self._files

    def list(self, instance_type=None, sources=None, space=None, limit=None):
        if sources == self._va or (isinstance(sources, list) and self._va in sources):
            return self._assets
        return self._sugs

    def apply(self, nodes=None, edges=None, **kw):
        self.applied.append((nodes, edges))


class FakeJob:
    def __init__(self, result=None, status="Completed", job_id=1):
        self._result, self.status, self.id = result, status, job_id

    def wait_for_completion(self, timeout=None):
        return self

    def get_result(self):
        return self._result


class FakeEntityMatching:
    def __init__(self, matches):
        self._matches = matches
        self.deleted = []

    def fit(self, **kw):
        return FakeJob(job_id=7)

    def predict(self, **kw):
        return FakeJob(result={"items": self._matches})

    def delete(self, **kw):
        self.deleted.append(kw)


class FakeClient:
    def __init__(self, *, rules, files, assets, suggestions, matches, views):
        vf, va, vs = views
        self.raw = FakeRaw(rules)
        self.entity_matching = FakeEntityMatching(matches)
        self.data_modeling = types.SimpleNamespace(
            instances=FakeInstances(files, assets, suggestions, vf, va, vs))


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("PARTICIPANT", "X")
    monkeypatch.setenv("INSTANCE_SPACE", "isp_X_TRN")
    monkeypatch.setenv("SCHEMA_SPACE_SDM", "ssp_X_MaintenanceInsight_sdm")
    monkeypatch.setenv("SCHEMA_SPACE_EDM", "ssp_X_TrainingCore_edm")
    monkeypatch.setenv("MODEL_VERSION", "v1.0.0")
    monkeypatch.setenv("RAW_DB", "rwd_X_Training_TRN")


def build(match_documents, *, score, suggestions=()):
    """No mapping rules and an unmatchable name, so the cascade must reach the model."""
    from cognite.client.data_classes.data_modeling import ViewId
    vf = ViewId("cdf_cdm", "CogniteFile", "v1")
    va = ViewId("cdf_cdm", "CogniteAsset", "v1")
    vs = ViewId("ssp_X_MaintenanceInsight_sdm", "ContextualizationSuggestion", "v1.0.0")
    files = [FakeNode("file_X_TRN_PID_21_SEP", {"name": "scan-0042.pdf"}, vf)]
    assets = [FakeNode("21-PA-2001A", {"name": "21-PA-2001A"}, va)]
    matches = [{"source": {"id": "file_X_TRN_PID_21_SEP"},
                "matches": [{"target": {"id": "21-PA-2001A"}, "score": score}]}]
    return FakeClient(rules=[], files=files, assets=assets,
                      suggestions=list(suggestions), matches=matches,
                      views=(vf, va, vs))


def test_the_model_path_runs_at_all(match_documents, env):
    """The regression test for the shadowed variable. Before the fix this raised
    AttributeError: 'NoneType' object has no attribute 'values'."""
    client = build(match_documents, score=0.95)
    result = match_documents.handle(client, data={})
    assert result["entity_matching_used"] is True
    assert result["resolved_by"] == {"entity-matching": 1}


def test_a_high_score_is_applied(match_documents, env):
    result = match_documents.handle(build(match_documents, score=0.95), data={})
    assert result["matches"][0]["target"] == "21-PA-2001A"
    assert result["below_threshold"] == []


def test_a_middle_score_goes_to_review_not_to_the_graph(match_documents, env):
    result = match_documents.handle(build(match_documents, score=0.60), data={})
    assert result["matches"] == []
    assert result["below_threshold"][0]["decision"] == "needs-review"


def test_a_low_score_is_rejected_but_still_recorded(match_documents, env):
    result = match_documents.handle(build(match_documents, score=0.20), data={})
    assert result["below_threshold"][0]["decision"] == "rejected"


def test_the_model_is_deleted_on_the_success_path(match_documents, env):
    """EM models are project-global; leaving one behind collides with the cohort."""
    client = build(match_documents, score=0.95)
    match_documents.handle(client, data={})
    assert client.entity_matching.deleted, "the fitted model was never deleted"


def test_a_caller_supplied_run_id_is_honoured(match_documents, env):
    result = match_documents.handle(build(match_documents, score=0.95),
                                    data={"runId": "ctxrun-pinned"})
    assert result["run_id"] == "ctxrun-pinned"
