"""Claim parsing preserves safe YAML semantics on both provisioned parsers."""

import pytest
import yaml

from enforced_planning import coordination_claims


@pytest.mark.parametrize("raw", [
    "scope: test\npaths: [a.py, b.py]\nactive: true\nempty: null\n",
    "base: &base {scope: test}\ncopy: *base\n",
    "date: 2026-10-09\nnested: {count: 4, value: 1.5}\n",
])
def test_claim_loader_preserves_safe_values(raw):
    assert coordination_claims.load_claim_yaml(raw) == yaml.safe_load(raw)


def test_claim_loader_rejects_python_objects():
    with pytest.raises(yaml.constructor.ConstructorError):
        coordination_claims.load_claim_yaml("!!python/object/apply:os.system ['false']")


def test_claim_loader_falls_back_without_libyaml(monkeypatch):
    monkeypatch.delattr(yaml, "CSafeLoader", raising=False)
    assert coordination_claims.load_claim_yaml(b"scope: fallback\n") == {"scope": "fallback"}


def test_claim_loader_preserves_parse_errors():
    with pytest.raises(yaml.YAMLError):
        coordination_claims.load_claim_yaml("paths: [unfinished")


def test_claim_loader_preserves_existing_error_text():
    raw = "agent: codex\nbroader_goal: build: inspect\n"
    with pytest.raises(yaml.YAMLError) as expected:
        yaml.safe_load(raw)
    with pytest.raises(yaml.YAMLError) as actual:
        coordination_claims.load_claim_yaml(raw)
    assert str(actual.value) == str(expected.value)
