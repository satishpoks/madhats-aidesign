"""All Claude Haiku calls live here. Every prompt comes from app.prompts.

Haiku is used only to interpret freeform input into structured data and to word
Ricardo's scripted reply — never to make routing decisions.

When ``settings.anthropic_api_key`` is empty (local dev / CI without a key),
every function falls back to a deterministic heuristic or a canned reply from
``app.prompts.CANNED_REPLIES``.  The real Haiku path is unchanged when a key
is present.
"""
from __future__ import annotations

import json
import re

import structlog

from app import prompts
from app.config import settings

log = structlog.get_logger()

# Evaluated once at import time.  Every function checks this flag before
# touching the Anthropic SDK so we never even construct the client when the
# key is absent.
_has_llm: bool = bool(settings.anthropic_api_key)

# Lazy Anthropic client — only created when _has_llm is True.
_client = None


def _get_client():
    global _client
    if _client is None:
        import anthropic  # noqa: PLC0415 — intentional lazy import
        _client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _client


async def _complete(
    prompt: str,
    *,
    system: str = prompts.RICARDO_SYSTEM_PROMPT,
    max_tokens: int = 400,
) -> str:
    resp = await _get_client().messages.create(
        model=settings.claude_haiku_model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    parts = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
    return "".join(parts).strip()


def _parse_json(text: str) -> dict:
    """Best-effort JSON extraction from a model reply."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1].lstrip("json").strip()
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1:
        text = text[start : end + 1]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        log.warning("json_parse_failed")
        return {}


# ---------------------------------------------------------------------------
# Deterministic / heuristic helpers (used when _has_llm is False)
# ---------------------------------------------------------------------------

# Longest phrases listed first so the scan short-circuits on the most specific
# match (e.g. "a dozen" before "dozen", "a few" before "few").
_WORD_TO_QTY: list[tuple[str, int]] = [
    ("not sure", 0),
    ("a dozen", 12),
    ("dozen", 12),
    ("twelve", 12),
    ("a few", 3),
    ("few", 3),
    ("couple", 2),
    ("single", 1),
    ("one", 1),
]

_YOUTH_KEYWORDS: frozenset[str] = frozenset(
    {"kid", "kids", "child", "children", "youth", "school", "junior"}
)


def _parse_quantity_heuristic(message: str) -> int:
    """Return a quantity integer from free-form text without calling an LLM.

    Priority:
      1. "not sure" → 0  (checked before digit scan to avoid matching "one")
      2. First digit run found, e.g. "25 hats" → 25, "50-99" → 50 (lower bound)
      3. Word map (longest match wins), e.g. "a dozen" → 12
      4. Fallback → 0
    """
    low = message.lower()
    if "not sure" in low:
        return 0
    # Digits win: for ranges like "50-99" the first integer is the lower bound.
    m = re.search(r"\b(\d+)(?:-\d+)?\b", low)
    if m:
        return int(m.group(1))
    # Word map: list is already sorted longest-first.
    for phrase, qty in _WORD_TO_QTY:
        if phrase in low:
            return qty
    return 0


def _detect_youth_heuristic(message: str) -> bool:
    """Return True if the message contains any youth/school keyword."""
    low = message.lower()
    return any(kw in low for kw in _YOUTH_KEYWORDS)


def _generate_reply_canned(state: str, collected: dict, persona_name: str) -> str:
    """Return a canned, user-facing reply for the given state.  No LLM call."""
    template = prompts.CANNED_REPLIES.get(
        state, "Let's keep going — what would you like to do next?"
    )
    try:
        return template.format(
            name=collected.get("name", "there"),
            quantity=collected.get("quantity", ""),
            decoration_type=collected.get("decoration_type", ""),
            placement_zone=collected.get("placement_zone", ""),
            persona=persona_name,
        )
    except (KeyError, IndexError):
        return template


# Internal state-machine bookkeeping that must never reach an LLM context: the
# model reads these and narrates about them (leaking chain-of-thought and field
# names to the customer). Only real design data should be handed to Haiku.
_INTERNAL_KEY_SUFFIXES = (
    "_asked", "_shown", "_offered", "_sent", "_captured", "_verified",
    "_referred", "_done", "_blocked", "_reached", "_mode", "_idx", "_flag",
)
_INTERNAL_KEYS = frozenset({"lead_id"})


def _safe_collected(collected: dict) -> dict:
    """Strip PII **and internal bookkeeping flags** before the dict is ever
    placed into an LLM context (reply wording or turn interpretation)."""
    redacted: dict = {}
    for key, value in collected.items():
        if key in ("email", "phone") or key in _INTERNAL_KEYS:
            continue
        if any(key.endswith(suffix) for suffix in _INTERNAL_KEY_SUFFIXES):
            continue
        redacted[key] = value
    return redacted


# ---------------------------------------------------------------------------
# Outgoing-reply hygiene: strip leaked model reasoning and repair mojibake so
# nothing internal or garbled ever reaches the customer.
# ---------------------------------------------------------------------------

# The model sometimes prefixes its answer with its own reasoning followed by a
# label like "Here's Ricardo's message:". Take everything after the last such
# marker. A genuine reply never contains this phrase, so clean text is untouched.
_META_PREAMBLE_MARKER = re.compile(r"here'?s\s+[\w' ]+?message\s*:", re.IGNORECASE)


def _strip_meta_preamble(text: str) -> str:
    """Drop any leaked "…Here's <persona>'s message:" reasoning preamble."""
    marker = None
    for marker in _META_PREAMBLE_MARKER.finditer(text):
        pass  # keep the last match
    if marker is not None:
        return text[marker.end():].strip().strip('"').strip()
    return text


def repair_mojibake(text: str) -> str:
    """Repair UTF-8 text that was mis-decoded as CP1252 (e.g. an em-dash "—"
    showing up as "â€""). Only strings carrying a mojibake signature that round-
    trip losslessly are repaired; clean text (including legitimate accents) is
    returned unchanged."""
    if not text or not any(marker in text for marker in ("Ã", "â€", "Â")):
        return text
    try:
        return text.encode("cp1252").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text


# Pure greetings / fillers that must not be captured as a customer's name.
_GREETING_TOKENS = frozenset({
    "hi", "hii", "hiii", "hey", "heya", "hiya", "hello", "helo", "hullo",
    "yo", "sup", "howdy", "greetings", "hola", "morning", "afternoon", "evening",
})
_GREETING_FILLERS = frozenset({"there", "good", "oh", "hey", "well"})


def _is_greeting_only(text: str) -> bool:
    """True when `text` is nothing but a greeting/filler (e.g. "hi", "hey
    there", "good morning") — so it is never mistaken for a name."""
    tokens = re.findall(r"[a-z]+", text.lower())
    if not tokens:
        return False
    if not all(t in _GREETING_TOKENS or t in _GREETING_FILLERS for t in tokens):
        return False
    return any(t in _GREETING_TOKENS for t in tokens)


# ---------------------------------------------------------------------------
# Public API — each function has a fallback when _has_llm is False
# ---------------------------------------------------------------------------


async def detect_backtrack(
    message: str, current_state: str, allowed_targets: list[str]
) -> str | None:
    """Return a target state slug if the user wants to go back, else None.

    Without a key: acceptable degradation — backtrack detection is disabled.
    """
    if not allowed_targets:
        return None
    if not _has_llm:
        return None
    prompt = prompts.BACKTRACK_DETECTION_PROMPT.format(
        current_state=current_state,
        message=message,
        allowed_targets=", ".join(allowed_targets),
    )
    data = _parse_json(await _complete(prompt, max_tokens=120))
    if data.get("backtrack") and data.get("target") in allowed_targets:
        return data["target"]
    return None


async def parse_quantity(message: str) -> int:
    """Extract a hat quantity from free-form user text."""
    if not _has_llm:
        return _parse_quantity_heuristic(message)
    prompt = prompts.QUANTITY_EXTRACTION_PROMPT.format(message=message)
    data = _parse_json(await _complete(prompt, max_tokens=60))
    try:
        return max(0, int(data.get("quantity", 0)))
    except (TypeError, ValueError):
        return 0


async def detect_youth(message: str) -> bool:
    """Return True if the message indicates the order is for children / youth."""
    if not _has_llm:
        return _detect_youth_heuristic(message)
    prompt = prompts.YOUTH_DETECTION_PROMPT.format(message=message)
    data = _parse_json(await _complete(prompt, max_tokens=40))
    return bool(data.get("youth", False))


async def extract_design_description(message: str) -> dict:
    """Extract structured design context from the customer's description."""
    if not _has_llm:
        return {"summary": message.strip()}
    prompt = prompts.DESIGN_EXTRACTION_PROMPT.format(message=message)
    data = _parse_json(await _complete(prompt, max_tokens=400))
    return data or {"summary": message}


_SIZE_WORDS = {"small": "small", "tiny": "small", "little": "small",
               "medium": "medium", "mid": "medium",
               "large": "large", "big": "large", "huge": "large"}

# Word-boundary matching for defer detection — a plain substring scan matches
# the bare word "any" (one of the DEFER_WORDS) inside unrelated words like
# "company", "many", "anywhere", silently discarding real attributes the
# customer gave. Mirrors the `_DONE_ELEMENTS_RE` word-boundary pattern in
# orchestrator.py.
_DEFER_RE = re.compile(r"\b(" + "|".join(re.escape(p) for p in prompts.DEFER_WORDS) + r")\b")

# Finding 1 (whole-branch review): without an API key, `_extract_attrs_heuristic`
# recognised defer/zone/size/position but never `remove_bg` -- a logo element's
# FIRST attribute is remove_bg, so "Yes, remove it" returned `{}`, remove_bg
# stayed unset, and `next_attribute` re-asked it forever (only "you choose"
# escaped, via the defer path above). Only set remove_bg when the message
# clearly signals yes/no; word-boundary matched so "no" doesn't match inside
# "not"/"none" etc.
_REMOVE_BG_YES_RE = re.compile(r"\b(remove|clean[- ]?up|yes|yep|yeah)\b")
_REMOVE_BG_NO_RE = re.compile(r"\b(keep|no|nope|leave|as[- ]is)\b")


def decide_remove_bg(message: str) -> bool | None:
    """Resolve the remove-background yes/no from the raw message.

    remove_bg is a strict yes/no, so the message itself is authoritative — the
    LLM extractor sometimes omits it (e.g. it reads "keep as is" as giving no
    value), which left it unset and re-asked the question in a loop. Returns
    True (remove), False (keep), or None (genuinely unclear)."""
    low = message.lower()
    yes = bool(_REMOVE_BG_YES_RE.search(low))
    no = bool(_REMOVE_BG_NO_RE.search(low))
    if yes and not no:
        return True
    if no and not yes:
        return False
    return None


def _extract_attrs_heuristic(el_type: str, message: str) -> dict:
    low = message.lower()
    out: dict = {}
    if _DEFER_RE.search(low):
        out["defer"] = True
        return out
    if el_type == "logo":
        wants_removed = bool(_REMOVE_BG_YES_RE.search(low))
        wants_kept = bool(_REMOVE_BG_NO_RE.search(low))
        if wants_removed and not wants_kept:
            out["remove_bg"] = True
        elif wants_kept and not wants_removed:
            out["remove_bg"] = False
    zone = _zone_from_text(message)
    if zone:
        out["placement_zone"] = zone
    for w, val in _SIZE_WORDS.items():
        if w in low:
            out["size"] = val
            break
    if "left" in low:
        out["placement_position"] = "left"
    elif "right" in low:
        out["placement_position"] = "right"
    elif "centre" in low or "center" in low or "middle" in low:
        out["placement_position"] = "centre"
    return out


async def extract_element_attributes(
    el_type: str, message: str, ask_for: str | None = None
) -> dict:
    """Extract recognised per-element attributes from freeform text.

    Used by the per-element deep-dive flow to fill in content/font/size/
    colour/style/placement for a single decoration element without forcing
    the customer through one question per attribute when they volunteer
    several at once (or defer the choice to us).

    ``ask_for`` (optional): the attribute we just asked about. Passed to the
    model so a short answer (e.g. "Back" answering placement) is read as THAT
    attribute rather than greedily inferred as ``content``.
    """
    if not _has_llm:
        return _extract_attrs_heuristic(el_type, message)
    prompt = prompts.ELEMENT_ATTRIBUTE_PROMPT.format(
        el_type=el_type, message=message, ask_for=ask_for or "any attribute they mention"
    )
    data = _parse_json(await _complete(prompt, max_tokens=200))
    return data if isinstance(data, dict) else {}


_VIEW_WORDS = ("front", "back", "side", "left", "right", "under", "brim", "peak")


async def refine_followups(change: str, collected: dict) -> list[str]:
    """Up to 3 clarifying questions for a requested design change (or [] if clear).

    With a key: Haiku proposes questions tailored to the change. Without a key:
    a single canned question — ask which part of the cap the change applies to,
    but only when the change didn't already name a view.
    """
    low = (change or "").lower()
    if not _has_llm:
        if not any(w in low for w in _VIEW_WORDS):
            return ["Which part of the cap should this change apply to — the front, back, or a side?"]
        return []
    try:
        raw = await _complete(
            prompts.REFINE_FOLLOWUP_PROMPT.format(change=(change or "")[:400]), max_tokens=200
        )
        data = _parse_json(raw)
        questions = data.get("questions") if isinstance(data, dict) else None
        return [str(q).strip() for q in (questions or []) if str(q).strip()][:3]
    except Exception:  # noqa: BLE001 — never break the flow on a followup miss
        return []


async def generate_reply(
    state: str,
    collected: dict,
    persona_name: str,
    aside: str | None = None,
    ask_for: str | None = None,
    ask_text: str | None = None,
    element: dict | None = None,
) -> str:
    """Word Ricardo's reply for the given state.

    Without a key: returns a canned reply from prompts.CANNED_REPLIES.
    With a key: calls Haiku with the STATE_PROMPTS instruction template.

    ``aside`` (optional): a short answer to a side-question the customer asked;
    when present it is spoken first, before the state's question is re-asked.

    ``ask_for`` (optional): the slug of a single element attribute (e.g.
    "font", "colour") we still need. When set, the reply asks for that
    attribute specifically instead of the state's default question — used by
    the per-element deep-dive flow.
    """
    if not _has_llm:
        if ask_text:
            base = ask_text
        elif ask_for:
            base = prompts.ATTRIBUTE_QUESTIONS.get(ask_for, "Tell me a bit more.")
        else:
            base = _generate_reply_canned(state, collected, persona_name)
        reply = f"{aside} {base}" if aside else base
        return repair_mojibake(reply)

    if ask_text:
        instruction = (
            "Briefly acknowledge what the customer just said, then ask them exactly "
            f"this, in your own warm words: {ask_text}"
        )
    elif ask_for:
        question = prompts.ATTRIBUTE_QUESTIONS.get(ask_for, "Tell me a bit more.")
        el_ctx = ""
        if element:
            etype = element.get("type", "element")
            content = element.get("content")
            el_ctx = f" You are asking about the customer's {etype} element"
            # A logo's `content` is a placeholder ("uploaded logo"), never text
            # to speak back; only quote real text/graphic content.
            if content and etype in ("text", "graphic"):
                el_ctx += f' (which says "{content}")'
            el_ctx += f". Refer to it as their {etype}, not as anything else."
        instruction = (
            f"Acknowledge what the customer just said.{el_ctx} Then ask: {question} "
            "Let them say 'you choose' or similar to leave it to you."
        )
    else:
        instruction = prompts.STATE_PROMPTS.get(state, "Continue the conversation politely.")
        try:
            instruction = instruction.format(
                name=collected.get("name", "there"),
                quantity=collected.get("quantity", ""),
                decoration_type=collected.get("decoration_type", ""),
                placement_zone=collected.get("placement_zone", ""),
            )
        except (KeyError, IndexError):
            pass

    system = prompts.RICARDO_SYSTEM_PROMPT.replace("Ricardo", persona_name)
    prompt = prompts.REPLY_GENERATION_PROMPT.format(
        state_instruction=(
            f"First briefly answer: '{aside}'. Then: {instruction}" if aside else instruction
        ),
        collected=json.dumps(_safe_collected(collected)),
    )
    raw = await _complete(prompt, system=system, max_tokens=200)
    return repair_mojibake(_strip_meta_preamble(raw))


# ---------------------------------------------------------------------------
# Single per-turn interpreter — classifies the message and extracts fields in
# one call. Replaces the old separate backtrack call + per-state keyword
# ingest. The state machine still owns routing; this only classifies/extracts.
# ---------------------------------------------------------------------------

_VALID_INTENTS = {"answer", "provide_info", "ask_question", "revise", "chitchat", "backtrack"}
_VALID_ZONES = {"front_panel", "side", "back", "under_brim"}


def _zone_from_text(message: str) -> str | None:
    low = message.lower()
    if "under" in low or "brim" in low:
        return "under_brim"
    if "side" in low:
        return "side"
    if "back" in low:
        return "back"
    if "front" in low or "panel" in low:
        return "front_panel"
    return None


def _extract_fields_for_state(state: str, message: str, collected: dict) -> dict:
    """No-LLM per-state extraction — mirrors the pre-existing keyword ingest so
    behaviour without an API key is unchanged (answer-to-current-step only)."""
    fields: dict = {}
    low = message.lower()
    if state == "ask_name":
        name = message.strip().split("\n")[0][:60]
        if name:
            fields["name"] = name
    elif state == "ask_purpose":
        fields["purpose"] = message.strip()
        fields["youth_flag"] = _detect_youth_heuristic(message)
    elif state == "ask_quantity":
        fields["quantity"] = _parse_quantity_heuristic(message)
    elif state in ("warn_print_setup", "recommend_decoration", "recommend_embroidery"):
        if "embroid" in low:
            fields["decoration_type"] = "embroidery"
        elif "patch" in low:
            fields["decoration_type"] = "patch"
        elif "print" in low:
            fields["decoration_type"] = "print"
    elif state == "ask_has_logo":
        fields["has_logo"] = ("upload" in low or "logo" in low or "yes" in low or "artwork" in low) and not (
            "describe" in low or "instead" in low or "don't" in low
        )
    elif state == "ask_remove_bg":
        fields["remove_bg"] = ("yes" in low or "remove" in low) and "no" not in low
    elif state == "describe_design":
        fields["design_description"] = {"summary": message.strip()}
    elif state == "ask_placement_zone":
        fields["placement_zone"] = _zone_from_text(message) or "front_panel"
    elif state == "ask_placement_position":
        fields["placement_position"] = message.strip()[:60]
    return fields


def _normalize_interpretation(data: dict, allowed_targets: list[str]) -> dict:
    intent = data.get("intent")
    # Guard set membership against non-string / unhashable model output: Haiku
    # sometimes returns a list here, and `list not in {a_set}` raises
    # TypeError: unhashable type: 'list', which 500'd the whole chat turn.
    if not isinstance(intent, str) or intent not in _VALID_INTENTS:
        intent = "answer"
    fields = data.get("fields")
    fields = fields if isinstance(fields, dict) else {}
    # Guard the enumerated zone value — same unhashable hazard as `intent`.
    zone = fields.get("placement_zone")
    if not isinstance(zone, str) or zone not in _VALID_ZONES:
        fields.pop("placement_zone", None)
    revise = data.get("revise_target")
    backtrack = data.get("backtrack_target")
    if revise not in allowed_targets:
        revise = None
    if backtrack not in allowed_targets:
        backtrack = None
    return {
        "intent": intent,
        "fields": fields,
        "revise_target": revise,
        "backtrack_target": backtrack,
        "question_answer": (data.get("question_answer") or "").strip(),
        "on_topic": bool(data.get("on_topic", True)),
    }


async def interpret_turn(
    state: str,
    message: str,
    collected: dict,
    allowed_targets: list[str],
    faq: str,
) -> dict:
    """Single per-turn interpretation. Structured intent + extracted fields.

    Without an API key: deterministic answer-only fallback (current step only).
    """
    if not _has_llm:
        return {
            "intent": "answer",
            "fields": _extract_fields_for_state(state, message, collected),
            "revise_target": None,
            "backtrack_target": None,
            "question_answer": "",
            "on_topic": True,
        }
    prompt = prompts.TURN_INTERPRETER_PROMPT.format(
        current_state=state,
        collected=json.dumps(_safe_collected(collected)),
        allowed_targets=", ".join(allowed_targets) or "(none)",
        faq=faq or "(no FAQ provided)",
        message=message,
    )
    data = _parse_json(await _complete(prompt, max_tokens=400))
    return _normalize_interpretation(data, allowed_targets)


# ---------------------------------------------------------------------------
# v2 step-by-step canvas orchestrator: the LLM fills slots, it never routes.
# See canvas_steps.py / state_machine_v2.py for the deterministic router that
# owns "what happens next" — this module only turns free text into fields.
# ---------------------------------------------------------------------------


class LLMUnavailable(RuntimeError):
    """Haiku is unreachable (no key, or the call failed).

    v2 has no keyword fallback by design: a wrong field corrupts the design, so
    the turn stalls rather than guessing. See orchestrator_v2.
    """


def validate_fields(raw: dict) -> dict:
    """Keep only declared, well-typed slots. The containment boundary: a
    hallucinated or internal key can never reach `collected`."""
    from app.services.conversation import canvas_steps as cs  # noqa: PLC0415 cycle

    out: dict = {}
    for key, val in (raw or {}).items():
        if key not in cs.WRITABLE_SLOTS:
            continue
        allowed = cs.SLOT_ENUMS.get(key)
        if allowed is not None:
            if isinstance(val, str) and val.lower() in allowed:
                out[key] = val.lower()
            continue
        if key == "quantity":
            try:
                out[key] = int(val)
            except (TypeError, ValueError):
                pass
            continue
        out[key] = val
    return out


_SLOT_DOCS: dict[str, str] = {
    "name": "name (string) — the customer's first name",
    "has_logo": "has_logo (bool) — true if they have a logo/image to upload, false if they want text only",
    "logo_face": "logo_face (one of: front, back, left, right)",
    "logo_placed": "logo_placed (bool) — true when they say the logo looks right / they're done",
    "logo_bg": "logo_bg (one of: removed, none) — 'removed' if they removed the logo's background, 'none' if it doesn't need it",
    "another_logo": "another_logo (bool) — true if they want to add ANOTHER logo",
    "decor_choice": "decor_choice (one of: text, shape)",
    "decor_face": "decor_face (one of: front, back, left, right) — where the text/shape goes",
    "decor_placed": "decor_placed (bool) — true when they're happy with it",
    "more_decor": "more_decor (bool) — true if they want to add something else",
    "decor_done": "decor_done (bool) — true if they want NO text/shapes at all, or nothing MORE added",
    "quantity": "quantity (integer) — how many caps; 0 means not sure",
    "needed_by": "needed_by (string) — when the customer needs the caps by; a rough timeframe (e.g. 'ASAP', '2-4 weeks', '1-2 months') or a specific date they give. Use 'Just exploring' when there is no firm date",
    "decoration_types": "decoration_types (list of strings) — decoration methods they chose, copied EXACTLY from the options offered in the question",
    "decoration_mix": "decoration_mix (bool) — true if they want a MIX of more than one decoration method, or aren't sure which single one they want",
    "decoration_mix_note": "decoration_mix_note (string) — their description of the mix of methods they want, in their own words",
    "email": "email (string)",
    "purpose": "purpose (string) — what the hat is for",
    "quote_requested": "quote_requested (bool) — true if they want to send the design to the team for a quote",
    "design_confirmed": "design_confirmed (bool) — true if they're happy with the finished design and ready to submit it",
    "design_rework": "design_rework (bool) — true if they want to go back and change something on the design before submitting",
}


async def interpret_turn_v2(step, message: str, collected: dict) -> dict:
    """Structured fields from one free-text turn. Raises LLMUnavailable rather
    than guessing — v2 stalls instead of falling back to keywords."""
    from app.services.conversation import canvas_steps as cs  # noqa: PLC0415 cycle

    if not _has_llm:
        raise LLMUnavailable("no anthropic api key")
    prompt = prompts.V2_TURN_INTERPRETER_PROMPT.format(
        ask=step.ask,
        asked_slots=", ".join(step.slots) or "(nothing)",
        slot_docs="\n".join(f"- {_SLOT_DOCS[s]}" for s in sorted(cs.WRITABLE_SLOTS)
                            if s in _SLOT_DOCS),
        message=message,
    )
    try:
        raw = await _complete(prompt, max_tokens=300)
    except Exception as exc:  # noqa: BLE001 — any SDK error is "unavailable"
        # err=type(exc).__name__, not str(exc): at ASK_EMAIL the prompt carries
        # the customer's email address, and some SDK errors stringify request
        # content — str(exc) could leak it into the logs (hard PII rule).
        log.warning("v2_interpret_failed", err=type(exc).__name__)
        raise LLMUnavailable(str(exc)) from exc
    return validate_fields(_parse_json(raw).get("fields") or {})


async def write_ack(persona: str, fields: dict) -> str:
    """One warm sentence acknowledging the turn, or "" if unavailable.

    Best-effort by design: the instructions are concatenated from the registry
    afterwards, so an outage makes the bot terse, never uninstructive.

    Deliberately takes NO raw customer message. v1's reply-wording path
    (`generate_reply`) never sees one either — only `interpret_turn` does,
    because interpreting requires it. At ASK_EMAIL the raw message IS the email
    address, so passing it here would send PII to the model on every turn. The
    validated `fields` carry the substance the ack needs, and
    `_safe_collected` strips `email`/`phone` from them.
    """
    if not _has_llm:
        return ""
    safe = _safe_collected(fields)
    if not safe:
        return ""                      # nothing non-PII to acknowledge
    try:
        text = await _complete(
            prompts.V2_ACK_PROMPT.format(persona=persona, fields=json.dumps(safe)),
            max_tokens=80,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("v2_ack_failed", err=type(exc).__name__)
        return ""
    return _strip_meta_preamble(repair_mojibake(text)).strip()


# ---------------------------------------------------------------------------
# Refine on the canvas: read a described change into closed-vocab ops.
# canvas_edit.resolve_ops does every bit of the arithmetic — this only reads
# WHAT the customer wants. See canvas_edit.py for the split rationale.
# ---------------------------------------------------------------------------


async def interpret_canvas_edit(message: str, inventory: list[dict]) -> list[dict]:
    """Raw closed-vocabulary ops for one described change.

    Raises LLMUnavailable rather than guessing — geometry is exactly where a
    wrong guess wrecks a design the customer already approved. `[]` is a real
    answer meaning "not expressible on the canvas" (the refuse path).
    """
    if not _has_llm:
        raise LLMUnavailable("no anthropic api key")
    lines = "\n".join(
        f"- id={e['id']} ({e['face']} face): {e['description']}" for e in inventory
    ) or "(nothing on the design)"
    prompt = prompts.CANVAS_EDIT_PROMPT.format(inventory=lines, message=message)
    try:
        raw = await _complete(prompt, max_tokens=400)
    except Exception as exc:  # noqa: BLE001 — any SDK error is "unavailable"
        # err=type(exc).__name__, not str(exc): the prompt carries the
        # customer's own words and some SDK errors stringify request content.
        log.warning("canvas_edit_interpret_failed", err=type(exc).__name__)
        raise LLMUnavailable(str(exc)) from exc
    ops = _parse_json(raw).get("ops")
    return ops if isinstance(ops, list) else []


async def interpret_edit_confirm(message: str) -> bool:
    """Is the customer happy with the just-applied canvas edit?

    Raises LLMUnavailable rather than guessing — misreading free text as
    approval spends a render and burns the daily design cap (the harm the
    CONFIRM_CANVAS_EDIT gate exists to prevent). Chip taps ("Looks right" /
    "Not quite") never reach this function; only free text does.
    """
    if not _has_llm:
        raise LLMUnavailable("no anthropic api key")
    prompt = prompts.CANVAS_EDIT_CONFIRM_PROMPT.format(message=message)
    try:
        raw = await _complete(prompt, max_tokens=60)
    except Exception as exc:  # noqa: BLE001 — any SDK error is "unavailable"
        # err=type(exc).__name__, not str(exc): the prompt carries the
        # customer's own words and some SDK errors stringify request content.
        log.warning("edit_confirm_interpret_failed", err=type(exc).__name__)
        raise LLMUnavailable(str(exc)) from exc
    return bool(_parse_json(raw).get("happy"))
