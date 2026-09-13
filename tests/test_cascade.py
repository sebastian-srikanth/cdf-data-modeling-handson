"""The contextualization cascade: rungs, bands, vetoes and retraction."""
from conftest import FakeClient, FakeRow


# ------------------------------------------------------------------ rung 1: rules ----
def test_rules_load_from_raw(match_documents, rules_table):
    client = FakeClient({("db", "rules"): rules_table})
    rules = match_documents._load_mapping_rules(client, "db", "rules")
    assert [r["target"] for r in rules] == ["TRN-21-SEP", "21-PA-2001A"]


def test_a_missing_rule_table_is_a_valid_state(match_documents):
    """Somebody who has not created the table yet must still get a working cascade."""
    assert match_documents._load_mapping_rules(FakeClient(), "db", "nope") == []


def test_rows_missing_a_pattern_or_target_are_skipped(match_documents):
    client = FakeClient({("db", "rules"): [
        FakeRow("a", {"sourcePattern": "x.pdf", "targetExternalId": ""}),
        FakeRow("b", {"sourcePattern": "", "targetExternalId": "ASSET-1"}),
        FakeRow("c", {"sourcePattern": "y.pdf", "targetExternalId": "ASSET-2"}),
    ]})
    assert [r["target"] for r in
            match_documents._load_mapping_rules(client, "db", "rules")] == ["ASSET-2"]


def test_exact_rules_are_tried_before_regex(match_documents):
    """Order in the table is policy: a person naming one pair beats a generalisation."""
    rules = [
        {"pattern": r".*\.pdf", "target": "GENERAL", "matchType": "regex"},
        {"pattern": "specific.pdf", "target": "SPECIFIC", "matchType": "exact"},
    ]
    assert match_documents._apply_rules(rules, "f1", "specific.pdf") == "SPECIFIC"


def test_a_malformed_regex_in_a_data_row_does_not_break_the_pipeline(match_documents):
    """The moment humans can edit rules, one of them will be `(unclosed`."""
    rules = [
        {"pattern": "(unclosed", "target": "BAD", "matchType": "regex"},
        {"pattern": "good.pdf", "target": "GOOD", "matchType": "exact"},
    ]
    assert match_documents._apply_rules(rules, "f1", "good.pdf") == "GOOD"


def test_no_rule_matches_returns_none(match_documents, rules_table):
    client = FakeClient({("db", "rules"): rules_table})
    rules = match_documents._load_mapping_rules(client, "db", "rules")
    assert match_documents._apply_rules(rules, "f9", "something-else.pdf") is None


# ------------------------------------------------------------------ rung 2: regex ----
def test_the_tag_regex_finds_a_tag_anywhere_in_a_name(match_documents):
    m = match_documents.TAG_IN_FILENAME.search("TRN-21-PA-2001A-Datasheet.pdf")
    assert m and m.group(1) == "21-PA-2001A"


def test_the_tag_regex_keeps_the_duty_standby_suffix(match_documents):
    a = match_documents.TAG_IN_FILENAME.search("21-PA-2001A.pdf").group(1)
    b = match_documents.TAG_IN_FILENAME.search("21-PA-2001B.pdf").group(1)
    assert (a, b) == ("21-PA-2001A", "21-PA-2001B")


def test_the_tag_regex_does_not_match_inside_a_longer_number(match_documents):
    assert match_documents.TAG_IN_FILENAME.search("991-PA-20011.pdf") is None


# ------------------------------------------------------------------ bands -------------
def test_bands(match_documents):
    band = match_documents._band
    assert band(0.99) == "auto-applied"
    assert band(match_documents.AUTO_APPLY_AT) == "auto-applied"   # inclusive
    assert band(0.79) == "needs-review"
    assert band(match_documents.REVIEW_AT) == "needs-review"       # inclusive
    assert band(0.44) == "rejected"
    assert band(0.0) == "rejected"


def test_the_review_band_is_not_empty(match_documents):
    """A 'band' that spans no scores is a threshold wearing a disguise."""
    assert match_documents.REVIEW_AT < match_documents.AUTO_APPLY_AT


# ------------------------------------------------------------------ human vetoes ------
def _prior(**rows):
    return {xid: props for xid, props in rows.items()}


def test_only_a_person_counts_as_a_veto(match_documents):
    prior = _prior(
        a={"sourceExternalId": "f1", "targetExternalId": "A",
           "decision": "rejected", "decidedBy": "sebastian"},
        b={"sourceExternalId": "f2", "targetExternalId": "B",
           "decision": "rejected", "decidedBy": "pipeline"},
    )
    assert match_documents._human_vetoes(prior) == {"f1|A": "rejected"}


def test_an_approval_is_a_veto_too(match_documents):
    """Approval and rejection are both decisions the pipeline must not overwrite."""
    prior = _prior(a={"sourceExternalId": "f1", "targetExternalId": "A",
                      "decision": "approved", "decidedBy": "sebastian"})
    assert match_documents._human_vetoes(prior) == {"f1|A": "approved"}


# ------------------------------------------------------------------ retraction --------
def test_a_human_rejection_retracts_the_link(match_documents):
    prior = _prior(a={"sourceExternalId": "f1", "targetExternalId": "A",
                      "decision": "rejected", "decidedBy": "sebastian"})
    assert match_documents._retractions(prior, {}) == [("f1", "A")]


def test_a_pair_we_no_longer_produce_is_retracted(match_documents):
    prior = _prior(a={"sourceExternalId": "f1", "targetExternalId": "A",
                      "decision": "auto-applied", "decidedBy": "pipeline"})
    assert match_documents._retractions(prior, {}) == [("f1", "A")]


def test_a_pair_we_still_produce_is_not_retracted(match_documents):
    prior = _prior(a={"sourceExternalId": "f1", "targetExternalId": "A",
                      "decision": "auto-applied", "decidedBy": "pipeline"})
    resolved = {"f1": {"target": "A", "how": "rule"}}
    assert match_documents._retractions(prior, resolved) == []


def test_a_pipeline_retraction_never_touches_what_a_person_approved(match_documents):
    """We only remove what we can prove we applied. Their link is not ours to drop."""
    prior = _prior(a={"sourceExternalId": "f1", "targetExternalId": "A",
                      "decision": "approved", "decidedBy": "sebastian"})
    assert match_documents._retractions(prior, {}) == []


def test_a_needs_review_row_is_not_retracted(match_documents):
    """Nothing was ever applied, so there is no link to take off."""
    prior = _prior(a={"sourceExternalId": "f1", "targetExternalId": "A",
                      "decision": "needs-review", "decidedBy": "pipeline"})
    assert match_documents._retractions(prior, {}) == []


def test_a_suggestion_with_no_target_is_ignored(match_documents):
    prior = _prior(a={"sourceExternalId": "f1", "targetExternalId": None,
                      "decision": "unresolved", "decidedBy": "pipeline"})
    assert match_documents._retractions(prior, {}) == []
