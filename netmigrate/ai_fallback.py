"""
AI fallback: bounded suggestion engine for constructs with no rule.

Design constraints, all load-bearing (see CLAUDE.md §2):

1. **Invoked only on UnmappedBlock.** Never consulted for a construct the
   rule engine handled. If it ran on every conversion, the rule-coverage
   metric would measure nothing.

2. **Never writes into the configuration body.** It fills ``suggestion`` and
   ``rationale`` on UnmappedBlock; the renderers emit those as comments with
   a review tag. The engine has no code path that promotes a suggestion to a
   live configuration line.

3. **Credential lines are never sent.** Password hashes are excluded before
   the request is built. Transmitting credential material from a customer
   configuration to a third-party API would be a security failure regardless
   of how useful the suggestion might be. Credentials already receive
   deterministic manual-entry guidance from transforms.credential_guidance().

4. **Confidence is recorded, not trusted.** The model's self-reported score
   is stored for display and excluded from every evaluation metric. It is not
   a validated reliability measure -- a fluent, well-formed, confidently
   scored suggestion can be semantically wrong, and the model has no reliable
   internal signal distinguishing the two cases.

5. **No key means no-op.** The whole system works with the fallback absent.
   That keeps evaluation runs reproducible and keeps the rule engine testable
   without network access.

6. **Never raises.** Any failure -- missing library, bad key, timeout,
   malformed response -- degrades to leaving suggestions unset, which the
   renderers already handle as plain UNMAPPED.

Privacy note for Chapter 5: enabling the fallback transmits unmapped
configuration lines (which may include hostnames and addressing) to an
external service. That is a real limitation of the design and should be
stated, not glossed.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Callable, Protocol

from netmigrate.ir import DeviceConfig, UnmappedBlock, Vendor

# Default model is read from the environment so no version string is pinned in
# source or in the thesis -- model generations deprecate faster than the
# project lifecycle.
DEFAULT_MODEL_ENV = "NETMIGRATE_GEMINI_MODEL"
DEFAULT_MODEL = "gemini-flash-latest"
API_KEY_ENV = "GEMINI_API_KEY"

MAX_BLOCKS_PER_REQUEST = 25
MAX_LINE_CHARS = 300

VENDOR_LABEL = {
    Vendor.CISCO: "Cisco IOS-XE",
    Vendor.HUAWEI: "Huawei VRP",
}


class LlmClient(Protocol):
    """Minimal interface the fallback needs.

    Declared as a Protocol so tests inject a fake and the module never
    imports the SDK during a test run.
    """

    def generate(self, prompt: str) -> str:
        ...


@dataclass
class FallbackStats:
    """What happened on the last run. Feeds the H5 measurement."""

    eligible: int = 0          # unmapped blocks that could be sent
    skipped_credential: int = 0
    requested: int = 0
    suggested: int = 0         # blocks that came back with a suggestion
    errors: list[str] = field(default_factory=list)
    enabled: bool = False

    @property
    def suggestion_rate(self) -> float:
        if self.requested == 0:
            return 0.0
        return self.suggested / self.requested


# --------------------------------------------------------------------------
# Prompt
# --------------------------------------------------------------------------

PROMPT = """You are assisting a network engineer migrating a device \
configuration from {source} to {target}.

The following lines could not be translated by a deterministic rule engine. \
For each, suggest the closest equivalent {target} configuration, or state \
that no equivalent exists.

Rules for your response:
- Respond with JSON only. No prose, no markdown fences.
- Return an array of objects with keys: "line" (the integer line number), \
"suggestion" (string, the {target} commands, or empty string if no \
equivalent exists), "rationale" (one short sentence), "confidence" (number \
between 0 and 1).
- If a construct is proprietary with no equivalent, return an empty \
suggestion and say so in the rationale. Do not invent commands.
- Do not include passwords, keys or hashes in any suggestion.

Lines to translate:
{lines}
"""


def build_prompt(blocks: list[UnmappedBlock], source: Vendor, target: Vendor) -> str:
    lines = "\n".join(
        f'{b.source_line}: {b.text[:MAX_LINE_CHARS]}' for b in blocks
    )
    return PROMPT.format(
        source=VENDOR_LABEL[source],
        target=VENDOR_LABEL[target],
        lines=lines,
    )


# --------------------------------------------------------------------------
# Response parsing
# --------------------------------------------------------------------------

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def parse_response(text: str) -> dict[int, dict]:
    """Parse the model's JSON into {line_number: fields}.

    Tolerates markdown fences and leading prose, because models add them
    despite instructions. Returns an empty dict on anything unparseable --
    a malformed response must degrade to "no suggestion", never to a crash
    or to a half-applied result.
    """
    if not text:
        return {}

    cleaned = _FENCE.sub("", text).strip()

    # If the model wrapped the array in commentary, take the outermost array.
    if not cleaned.startswith("["):
        start, end = cleaned.find("["), cleaned.rfind("]")
        if start == -1 or end <= start:
            return {}
        cleaned = cleaned[start:end + 1]

    try:
        payload = json.loads(cleaned)
    except (ValueError, TypeError):
        return {}

    if not isinstance(payload, list):
        return {}

    out: dict[int, dict] = {}
    for item in payload:
        if not isinstance(item, dict):
            continue
        try:
            line_no = int(item["line"])
        except (KeyError, TypeError, ValueError):
            continue

        suggestion = item.get("suggestion") or ""
        rationale = item.get("rationale") or ""
        if not isinstance(suggestion, str) or not isinstance(rationale, str):
            continue

        confidence = item.get("confidence")
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            confidence = None
        if confidence is not None and not 0.0 <= confidence <= 1.0:
            confidence = None

        out[line_no] = {
            "suggestion": suggestion.strip(),
            "rationale": rationale.strip(),
            "confidence": confidence,
        }
    return out


# --------------------------------------------------------------------------
# The fallback
# --------------------------------------------------------------------------


class AiFallback:
    """Callable that fills suggestions on a DeviceConfig's unmapped blocks.

    Pass to engine.convert() as ``ai_fallback=``. Construct with an explicit
    client in tests; in production leave it None and it builds a Gemini
    client from the environment, or disables itself if it cannot.
    """

    def __init__(
        self,
        target: Vendor,
        client: LlmClient | None = None,
        api_key: str | None = None,
        model: str | None = None,
    ) -> None:
        self.target = target
        self.model = model or os.environ.get(DEFAULT_MODEL_ENV, DEFAULT_MODEL)
        self.stats = FallbackStats()
        self._client = client
        if client is None:
            self._client = self._build_client(api_key)
        self.enabled = self._client is not None
        self.stats.enabled = self.enabled

    # -- client construction -------------------------------------------------

    def _build_client(self, api_key: str | None) -> LlmClient | None:
        key = api_key or os.environ.get(API_KEY_ENV)
        if not key:
            return None
        try:
            from google import genai  # type: ignore
        except ImportError:
            return None

        model = self.model

        class _GeminiClient:
            def __init__(self) -> None:
                self._inner = genai.Client(api_key=key)

            def generate(self, prompt: str) -> str:
                response = self._inner.models.generate_content(
                    model=model, contents=prompt
                )
                return getattr(response, "text", "") or ""

        try:
            return _GeminiClient()
        except Exception:  # noqa: BLE001 -- never let setup break conversion
            return None

    # -- eligibility ---------------------------------------------------------

    @staticmethod
    def eligible(block: UnmappedBlock) -> bool:
        """Blocks that may be sent to the model.

        Credentials are excluded: sending password hashes to a third-party
        API would be a security failure, and they already get deterministic
        manual-entry guidance.
        """
        if block.category == "credential":
            return False
        if not block.text.strip():
            return False
        # Never send anything that already looks like secret material, even
        # if the category tag was missed.
        from netmigrate import transforms as tf

        return not tf.is_credential_line(block.text)

    # -- main entry point ----------------------------------------------------

    def __call__(self, cfg: DeviceConfig) -> FallbackStats:
        self.stats = FallbackStats(enabled=self.enabled)

        if not cfg.unmapped:
            return self.stats

        candidates = []
        for block in cfg.unmapped:
            if block.category == "credential":
                self.stats.skipped_credential += 1
                continue
            if self.eligible(block):
                candidates.append(block)

        self.stats.eligible = len(candidates)

        if not self.enabled or not candidates:
            return self.stats

        for start in range(0, len(candidates), MAX_BLOCKS_PER_REQUEST):
            batch = candidates[start:start + MAX_BLOCKS_PER_REQUEST]
            self._process(batch, cfg)

        return self.stats

    def _process(self, batch: list[UnmappedBlock], cfg: DeviceConfig) -> None:
        source = cfg.source_vendor or Vendor.CISCO
        prompt = build_prompt(batch, source, self.target)

        self.stats.requested += len(batch)

        try:
            raw = self._client.generate(prompt)  # type: ignore[union-attr]
        except Exception as exc:  # noqa: BLE001
            # Any transport or API failure degrades to no suggestions.
            self.stats.errors.append(f"{type(exc).__name__}: {exc}")
            return

        parsed = parse_response(raw)
        if not parsed:
            self.stats.errors.append("unparseable response")
            return

        by_line = {b.source_line: b for b in batch}
        for line_no, fields in parsed.items():
            block = by_line.get(line_no)
            if block is None:
                continue  # model hallucinated a line number; ignore it

            suggestion = fields["suggestion"]
            if not suggestion:
                # Model says no equivalent exists. Record the reasoning but
                # leave suggestion unset so the line stays plain UNMAPPED.
                block.rationale = fields["rationale"] or None
                continue

            # Defence in depth: never accept a suggestion carrying secrets.
            from netmigrate import transforms as tf

            if tf.is_credential_line(suggestion):
                self.stats.errors.append(
                    f"line {line_no}: suggestion rejected, contained "
                    f"credential material"
                )
                continue

            block.suggestion = suggestion
            block.rationale = fields["rationale"] or None
            self.stats.suggested += 1


# --------------------------------------------------------------------------
# Convenience
# --------------------------------------------------------------------------


def make_fallback(
    target: Vendor,
    client: LlmClient | None = None,
) -> Callable[[DeviceConfig], FallbackStats] | None:
    """Return a fallback for ``target``, or None if it cannot be enabled.

    Returning None rather than a disabled object lets callers pass the result
    straight to convert(), where None means "no fallback".
    """
    fallback = AiFallback(target, client=client)
    return fallback if fallback.enabled else None
