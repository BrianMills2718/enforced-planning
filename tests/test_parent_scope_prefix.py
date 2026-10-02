"""--parent-scope accepts the <project>:<scope> form the tool itself prints."""

from enforced_planning.coordination_claims import normalize_claim, normalize_parent_scope


def test_prefix_of_the_claims_own_project_is_stripped():
    assert normalize_parent_scope("brent-chatgpt:roadmap/STATUS.md", "brent-chatgpt") == "roadmap/STATUS.md"
    assert normalize_parent_scope("roadmap/STATUS.md", "brent-chatgpt") == "roadmap/STATUS.md"
    # Another project's prefix is not ours to strip.
    assert normalize_parent_scope("other:roadmap/STATUS.md", "brent-chatgpt") == "other:roadmap/STATUS.md"
    assert normalize_parent_scope(None, "brent-chatgpt") is None


def test_stored_prefixed_parent_scope_is_read_as_the_bare_scope():
    claim = normalize_claim({
        "agent": "claude-code",
        "projects": ["brent-chatgpt"],
        "scope": "tests/test_corridor_candidates.py",
        "intent": "child lane",
        "claim_type": "program",
        "status": "active",
        "parent_scope": "brent-chatgpt:roadmap/STATUS.md",
    })
    assert claim is not None
    assert claim.parent_scope == "roadmap/STATUS.md"
