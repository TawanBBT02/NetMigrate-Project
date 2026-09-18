"""
Tests for the AI fallback. No live API calls -- every test injects a fake
client, so the suite runs offline and deterministically.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from netmigrate.ai_fallback import (  # noqa: E402
    AiFallback,
    build_prompt,
    make_fallback,
    parse_response,
)
from netmigrate.engine import convert  # noqa: E402
from netmigrate.ir import Provenance, Vendor  # noqa: E402
from netmigrate.rules_cisco import parse_cisco  # noqa: E402

C, H = Vendor.CISCO, Vendor.HUAWEI


class FakeClient:
    """Records prompts, returns a scripted response."""

    def __init__(self, response="[]", raises=None):
        self.response = response
        self.raises = raises
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if self.raises:
            raise self.raises
        return self.response


def reply(*items) -> str:
    return json.dumps(list(items))


# --------------------------------------------------------------------------
# Response parsing
# --------------------------------------------------------------------------


def test_parse_plain_json():
    got = parse_response(reply(
        {"line": 5, "suggestion": "traffic classifier X",
         "rationale": "closest match", "confidence": 0.7}
    ))
    assert got[5]["suggestion"] == "traffic classifier X"
    assert got[5]["confidence"] == 0.7


def test_parse_strips_markdown_fences():
    raw = '```json\n[{"line": 1, "suggestion": "a", "rationale": "b"}]\n```'
    assert parse_response(raw)[1]["suggestion"] == "a"


def test_parse_extracts_array_from_prose():
    raw = 'Here you go:\n[{"line": 2, "suggestion": "x", "rationale": "y"}]\nHope that helps!'
    assert parse_response(raw)[2]["suggestion"] == "x"


def test_parse_malformed_returns_empty():
    for raw in ("", "not json", "{broken", "null", '{"line": 1}', "[1,2,3]"):
        assert parse_response(raw) == {}, raw


def test_parse_skips_items_with_bad_line_number():
    got = parse_response(reply(
        {"line": "abc", "suggestion": "x", "rationale": "y"},
        {"line": 3, "suggestion": "ok", "rationale": "y"},
    ))
    assert list(got) == [3]


def test_parse_rejects_out_of_range_confidence():
    got = parse_response(reply(
        {"line": 1, "suggestion": "x", "rationale": "y", "confidence": 5.0}
    ))
    assert got[1]["confidence"] is None


def test_parse_missing_confidence_is_none():
    got = parse_response(reply({"line": 1, "suggestion": "x", "rationale": "y"}))
    assert got[1]["confidence"] is None


# --------------------------------------------------------------------------
# Eligibility -- the security boundary
# --------------------------------------------------------------------------


def test_credentials_are_never_sent():
    cfg = parse_cisco(
        "enable secret 5 $1$mERr$H2s\n"
        "username admin privilege 15 secret 9 $9$xyz\n"
        "ip nbar protocol-discovery\n"
    )
    client = FakeClient(reply())
    fallback = AiFallback(H, client=client)
    stats = fallback(cfg)

    assert stats.skipped_credential == 2
    assert stats.eligible == 1

    prompt = client.prompts[0]
    assert "$1$mERr" not in prompt
    assert "$9$xyz" not in prompt
    assert "nbar" in prompt


def test_no_request_when_only_credentials_unmapped():
    cfg = parse_cisco("enable secret 5 $1$abc\n")
    client = FakeClient(reply())
    stats = AiFallback(H, client=client)(cfg)
    assert client.prompts == []
    assert stats.requested == 0
    assert stats.skipped_credential == 1


def test_suggestion_containing_credentials_is_rejected():
    """Defence in depth: even if the model returns a hash, we refuse it."""
    cfg = parse_cisco("ip nbar protocol-discovery\n")
    client = FakeClient(reply(
        {"line": 1, "suggestion": "local-user admin password cipher $1c$K",
         "rationale": "nope", "confidence": 0.9}
    ))
    stats = AiFallback(H, client=client)(cfg)
    assert cfg.unmapped[0].suggestion is None
    assert stats.suggested == 0
    assert any("credential" in e for e in stats.errors)


# --------------------------------------------------------------------------
# Behaviour
# --------------------------------------------------------------------------


def test_suggestion_is_applied():
    cfg = parse_cisco("ip nbar protocol-discovery\n")
    client = FakeClient(reply(
        {"line": 1, "suggestion": "traffic classifier APP",
         "rationale": "nearest VRP construct", "confidence": 0.6}
    ))
    stats = AiFallback(H, client=client)(cfg)
    assert cfg.unmapped[0].suggestion == "traffic classifier APP"
    assert cfg.unmapped[0].rationale == "nearest VRP construct"
    assert stats.suggested == 1


def test_empty_suggestion_records_rationale_only():
    """Model says no equivalent exists -- line stays plain UNMAPPED."""
    cfg = parse_cisco("ip nbar protocol-discovery\n")
    client = FakeClient(reply(
        {"line": 1, "suggestion": "",
         "rationale": "no VRP equivalent", "confidence": 0.9}
    ))
    stats = AiFallback(H, client=client)(cfg)
    assert cfg.unmapped[0].suggestion is None
    assert cfg.unmapped[0].rationale == "no VRP equivalent"
    assert stats.suggested == 0


def test_hallucinated_line_number_ignored():
    cfg = parse_cisco("ip nbar protocol-discovery\n")
    client = FakeClient(reply(
        {"line": 999, "suggestion": "something", "rationale": "x"}
    ))
    stats = AiFallback(H, client=client)(cfg)
    assert cfg.unmapped[0].suggestion is None
    assert stats.suggested == 0


def test_api_error_degrades_quietly():
    cfg = parse_cisco("ip nbar protocol-discovery\n")
    client = FakeClient(raises=RuntimeError("503 unavailable"))
    stats = AiFallback(H, client=client)(cfg)
    assert cfg.unmapped[0].suggestion is None
    assert stats.errors and "RuntimeError" in stats.errors[0]


def test_malformed_response_degrades_quietly():
    cfg = parse_cisco("ip nbar protocol-discovery\n")
    stats = AiFallback(H, client=FakeClient("garbage"))(cfg)
    assert cfg.unmapped[0].suggestion is None
    assert "unparseable response" in stats.errors


def test_no_unmapped_makes_no_request():
    cfg = parse_cisco("hostname SW1\n")
    client = FakeClient(reply())
    stats = AiFallback(H, client=client)(cfg)
    assert client.prompts == []
    assert stats.eligible == 0


def test_batching_splits_large_input():
    lines = "\n".join(f"ip nbar rule-{i}" for i in range(60))
    cfg = parse_cisco(lines + "\n")
    client = FakeClient(reply())
    stats = AiFallback(H, client=client)(cfg)
    assert len(client.prompts) == 3  # 25 + 25 + 10
    assert stats.requested == 60


def test_disabled_without_key(monkeypatch=None):
    import os
    saved = os.environ.pop("GEMINI_API_KEY", None)
    try:
        fallback = AiFallback(H)
        assert fallback.enabled is False
        assert make_fallback(H) is None
        cfg = parse_cisco("ip nbar protocol-discovery\n")
        stats = fallback(cfg)
        assert stats.enabled is False
        assert stats.requested == 0
    finally:
        if saved is not None:
            os.environ["GEMINI_API_KEY"] = saved


# --------------------------------------------------------------------------
# Integration with the engine
# --------------------------------------------------------------------------


def test_engine_marks_ai_lines_and_comments_them():
    client = FakeClient(reply(
        {"line": 2, "suggestion": "traffic classifier APP",
         "rationale": "nearest construct", "confidence": 0.6}
    ))
    result = convert(
        "hostname SW1\nip nbar protocol-discovery\n",
        C, H,
        ai_fallback=AiFallback(H, client=client),
    )

    assert result.ai_lines == 1
    assert result.unmapped_lines == 0

    # Every AI line must be commented.
    for line in result.lines:
        if line.provenance is Provenance.AI:
            assert line.text.lstrip().startswith("#"), line.text

    assert "traffic classifier APP" in result.output_text
    for text_line in result.output_text.splitlines():
        if "traffic classifier APP" in text_line:
            assert text_line.lstrip().startswith("#")


def test_coverage_unchanged_by_fallback():
    """The fallback must not inflate rule coverage."""
    src = "hostname SW1\nip nbar protocol-discovery\n"
    without = convert(src, C, H)
    with_ai = convert(
        src, C, H,
        ai_fallback=AiFallback(H, client=FakeClient(reply(
            {"line": 2, "suggestion": "x", "rationale": "y"}
        ))),
    )
    assert with_ai.rule_lines == without.rule_lines
    assert with_ai.rule_coverage == without.rule_coverage


def test_fallback_not_consulted_for_mapped_lines():
    """Nothing the rule engine handled may appear in the prompt."""
    client = FakeClient(reply())
    convert(
        "hostname SW1\nvlan 10\n name SALES\ninterface Gi0/1\n"
        " switchport mode access\nip nbar protocol-discovery\n",
        C, H,
        ai_fallback=AiFallback(H, client=client),
    )
    prompt = client.prompts[0]
    for mapped in ("hostname", "vlan 10", "SALES", "switchport"):
        assert mapped not in prompt, mapped


def test_prompt_names_both_vendors():
    cfg = parse_cisco("ip nbar protocol-discovery\n")
    prompt = build_prompt(cfg.unmapped, C, H)
    assert "Cisco IOS-XE" in prompt
    assert "Huawei VRP" in prompt
    assert "JSON only" in prompt


if __name__ == "__main__":
    tests = [(n, o) for n, o in sorted(globals().items())
             if n.startswith("test_") and callable(o)]
    passed = failed = 0
    for name, fn in tests:
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL  {name}: {type(exc).__name__}: {exc}")
        else:
            passed += 1
    print(f"\n{passed} passed, {failed} failed, {len(tests)} total")
    sys.exit(1 if failed else 0)
