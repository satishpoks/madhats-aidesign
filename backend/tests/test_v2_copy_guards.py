"""Guards on the v2 canvas copy.

These are cheap regression pins on things that are easy to reintroduce by
hand-editing one constant: copy that points at the toolbar's OLD position, and
casual phrasing the brand has moved away from.
"""
import re

from app import prompts
from app.services.conversation import canvas_steps as cs


def _v2_copy_strings() -> list[str]:
    """Every customer-facing v2 string: registry copy + the shared constants."""
    out: list[str] = []
    for step in cs.REGISTRY:
        for s in (step.ask, step.ask_retry, step.tip, step.instructions):
            if s:
                out.append(s)
        for chip in step.chips:
            out.append(chip.label)
    out.extend(prompts.V2_TOOL_TIPS.values())
    out.extend([
        prompts.V2_BG_INSTRUCTIONS,
        prompts.V2_REWORK_INSTRUCTIONS,
        prompts.V2_ASK_NAME,
        prompts.V2_ASK_NAME_RETRY,
        prompts.V2_ASK_EMAIL_RETRY,
        prompts.V2_DEFAULT_INTRO,
        prompts.V2_EMAIL_VERIFY_NOTICE,
        prompts.V2_COLOUR_DISCLAIMER,
        prompts.V2_STALL_REPLY,
        prompts.V2_NUDGE_REPLY,
        prompts.V2_ABUSE_DECLINE,
    ])
    return out


def test_no_v2_copy_hard_codes_the_adjust_panels_position():
    """The panel's position is RESPONSIVE — the tool rail on desktop, above the
    cap on mobile (see frontend useIsDesktop). Any hard-coded position is wrong
    in one of the two layouts, so the copy must name the panel and stop there.
    Supersedes the old "under the cap" check, which only caught one of three."""
    for s in _v2_copy_strings():
        low = s.lower()
        for stale in ("above the cap", "below the cap", "under the cap"):
            assert stale not in low, f"hard-coded panel position {stale!r} in: {s!r}"


def test_the_adjust_panel_is_named_where_the_customer_needs_it():
    """The tool tips are the only place a customer is told how to restyle what
    they placed, and they are concatenated verbatim (never through a model), so
    naming the panel there is what makes it discoverable."""
    for key in ("text", "shape"):
        assert "Adjust panel" in prompts.V2_TOOL_TIPS[key]
    assert "Adjust panel" in prompts.V2_BG_INSTRUCTIONS


# Phrases from the pre-2026-07-26 casual register. Not a style engine — just a
# pin on the specific wording that was rewritten, so a later hand-edit that
# reintroduces the old voice fails loudly instead of shipping.
#
# Matched on a leading word boundary rather than as a plain substring: a plain
# `"tap " in low` check requires a literal trailing space, so it missed "Tap.",
# "Tap!" and "tapping" (no space follows "tap" in any of those). Anchoring only
# on the left edge (`\btap`) still catches all of those — "tapping" starts with
# "tap" at a word boundary — while a real word boundary on the left keeps it
# from firing inside an unrelated word like "stapler".
_CASUAL = ("pop your", "pop it", "grab your", "love where", "no worries",
           "are you after", "tap")

_CASUAL_PATTERNS = [(phrase, re.compile(r"\b" + re.escape(phrase))) for phrase in _CASUAL]


def test_v2_copy_stays_out_of_the_casual_register():
    for s in _v2_copy_strings():
        low = s.lower()
        for phrase, pattern in _CASUAL_PATTERNS:
            assert not pattern.search(low), f"casual phrasing {phrase!r} in: {s!r}"


def test_the_colour_disclaimer_hedges_instead_of_promising_an_exact_match():
    """Hard constraint documented above V2_COLOUR_DISCLAIMER: the copy must
    never promise exact colour, only a "closest match" hedge. A prior copy
    rewrite dropped the test that pinned this phrase while leaving the wording
    itself unchanged — this restores the guard so a future rewrite can't drop
    the hedge silently."""
    assert "closest" in prompts.V2_COLOUR_DISCLAIMER
