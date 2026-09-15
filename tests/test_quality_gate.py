"""The gate. These are the tests that matter most, because a gate that cannot fail
is indistinguishable from a gate that works right up until the day you need it."""
import os

import pytest


class FakeNode:
    def __init__(self, props, view):
        self.properties = {view: props}
        self.external_id = props.get("runId")


class FakeInstances:
    def __init__(self, runs):
        self._runs = runs
        self.calls = 0

    def list(self, sources=None, space=None, limit=None):
        self.calls += 1
        return [FakeNode(r, sources) for r in self._runs]


class FakeDM:
    def __init__(self, runs):
        self.instances = FakeInstances(runs)


class FakeClient:
    def __init__(self, runs):
        self.data_modeling = FakeDM(runs)


HEALTHY = {
    "runId": "ctxrun-1", "technique": "entity-matching", "status": "completed",
    "rulesVersion": "rules:2", "startedTime": "2026-09-13T10:00:00.000+00:00",
    "failedCount": 0, "unresolvedCount": 0, "reviewCount": 0, "staleRemovedCount": 0,
}


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("INSTANCE_SPACE", "isp_X_TRN")
    monkeypatch.setenv("SCHEMA_SPACE_SDM", "ssp_X_MaintenanceInsight_sdm")
    monkeypatch.setenv("MODEL_VERSION", "v1.0.0")
    for k in ("MAX_UNRESOLVED", "MAX_REVIEW_BACKLOG", "MAX_STALE_REMOVED"):
        monkeypatch.delenv(k, raising=False)


def run_gate(quality_gate, runs, data=None, timeout=0.1):
    quality_gate.SETTLE_TIMEOUT = timeout
    quality_gate.SETTLE_INTERVAL = 0.01
    return quality_gate.handle(FakeClient(runs), data=data)


def test_a_healthy_run_passes(quality_gate):
    assert run_gate(quality_gate, [HEALTHY])["passed"] is True


def test_the_gate_raises_rather_than_returning_a_sad_dict(quality_gate):
    """A Workflow task goes red if and only if the Function raises. Returning
    {"passed": False} produces a green workflow with a complaint nobody reads."""
    bad = {**HEALTHY, "unresolvedCount": 3}
    with pytest.raises(quality_gate.QualityGateFailed):
        run_gate(quality_gate, [bad])


def test_a_failed_item_is_a_bug_and_no_threshold_excuses_it(quality_gate, monkeypatch):
    monkeypatch.setenv("MAX_UNRESOLVED", "999")
    monkeypatch.setenv("MAX_REVIEW_BACKLOG", "999")
    monkeypatch.setenv("MAX_STALE_REMOVED", "999")
    with pytest.raises(quality_gate.QualityGateFailed, match="failedCount"):
        run_gate(quality_gate, [{**HEALTHY, "failedCount": 1}])


def test_a_run_still_marked_running_fails(quality_gate):
    """A Function that died without saying so leaves exactly this trace."""
    with pytest.raises(quality_gate.QualityGateFailed, match="never finished"):
        run_gate(quality_gate, [{**HEALTHY, "status": "running"}])


def test_no_runs_at_all_fails(quality_gate):
    with pytest.raises(quality_gate.QualityGateFailed, match="no ContextualizationRun"):
        run_gate(quality_gate, [])


def test_budgets_come_from_env_not_from_code(quality_gate, monkeypatch):
    monkeypatch.setenv("MAX_REVIEW_BACKLOG", "2")
    assert run_gate(quality_gate, [{**HEALTHY, "reviewCount": 2}])["passed"] is True
    with pytest.raises(quality_gate.QualityGateFailed, match="reviewCount=3"):
        run_gate(quality_gate, [{**HEALTHY, "reviewCount": 3}])


def test_a_nonsense_budget_falls_back_to_the_default(quality_gate, monkeypatch):
    monkeypatch.setenv("MAX_UNRESOLVED", "not-a-number")
    assert run_gate(quality_gate, [HEALTHY])["passed"] is True


def test_every_breach_is_reported_not_just_the_first(quality_gate):
    bad = {**HEALTHY, "unresolvedCount": 5, "reviewCount": 99, "staleRemovedCount": 99}
    with pytest.raises(quality_gate.QualityGateFailed) as exc:
        run_gate(quality_gate, [bad])
    message = str(exc.value)
    assert all(f in message for f in
               ("unresolvedCount", "reviewCount", "staleRemovedCount"))


# ---- the race this gate exists to survive ------------------------------------------
def test_pinning_to_a_run_id_rejects_an_older_healthy_run(quality_gate):
    """The whole point. Data modeling reads lag writes, so "the latest run" can
    quietly mean "the previous run" -- which passes on last night's numbers."""
    with pytest.raises(quality_gate.QualityGateFailed, match="never recorded"):
        run_gate(quality_gate, [HEALTHY], data={"runId": "ctxrun-2"})


def test_pinning_finds_the_right_run_among_several(quality_gate):
    older = {**HEALTHY, "runId": "ctxrun-1", "unresolvedCount": 0}
    newer = {**HEALTHY, "runId": "ctxrun-2",
             "startedTime": "2026-09-13T11:00:00.000+00:00", "unresolvedCount": 4}
    with pytest.raises(quality_gate.QualityGateFailed, match="unresolvedCount=4"):
        run_gate(quality_gate, [older, newer], data={"runId": "ctxrun-2"})


def test_unpinned_the_gate_takes_the_most_recent_run(quality_gate):
    older = {**HEALTHY, "runId": "ctxrun-1", "unresolvedCount": 9}
    newer = {**HEALTHY, "runId": "ctxrun-2",
             "startedTime": "2026-09-13T11:00:00.000+00:00"}
    assert run_gate(quality_gate, [older, newer])["passed"] is True


def test_started_after_excludes_a_stale_run(quality_gate):
    with pytest.raises(quality_gate.QualityGateFailed, match="never wrote a record"):
        run_gate(quality_gate, [HEALTHY],
                 data={"startedAfter": "2026-09-13T10:30:00.000+00:00"})


def test_the_gate_polls_rather_than_giving_up_immediately(quality_gate):
    client = FakeClient([HEALTHY])
    quality_gate.SETTLE_TIMEOUT = 0.1
    quality_gate.SETTLE_INTERVAL = 0.01
    with pytest.raises(quality_gate.QualityGateFailed):
        quality_gate.handle(client, data={"runId": "missing"})
    assert client.data_modeling.instances.calls > 1, "it gave up after one read"


def test_the_report_names_the_budgets_it_checked(quality_gate):
    report = run_gate(quality_gate, [HEALTHY])
    assert set(report["budgets"]) == {
        "unresolvedCount", "reviewCount", "staleRemovedCount"}
    assert report["runId"] == "ctxrun-1"
    assert report["rulesVersion"] == "rules:2"
