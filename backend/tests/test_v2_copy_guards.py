"""Guards on the v2 canvas copy.

These are cheap regression pins on things that are easy to reintroduce by
hand-editing one constant: copy that points at the toolbar's OLD position, and
casual phrasing the brand has moved away from.
"""
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
        prompts.V2_DEFAULT_INTRO,
        prompts.V2_EMAIL_VERIFY_NOTICE,
        prompts.V2_COLOUR_DISCLAIMER,
        prompts.V2_STALL_REPLY,
        prompts.V2_NUDGE_REPLY,
        prompts.V2_BACK_RESTART_ACK,
    ])
    return out


def test_no_v2_copy_points_below_the_cap():
    """The Adjust panel moved ABOVE the cap. Copy saying "under the cap" sends
    the customer looking at empty space — and on a phone that was exactly the
    bug this move fixes."""
    for s in _v2_copy_strings():
        assert "under the cap" not in s.lower(), f"stale toolbar position in: {s!r}"


def test_the_adjust_panel_is_named_where_the_customer_needs_it():
    """The tool tips are the only place a customer is told how to restyle what
    they placed, and they are concatenated verbatim (never through a model), so
    naming the panel there is what makes it discoverable."""
    for key in ("text", "shape"):
        assert "Adjust panel above the cap" in prompts.V2_TOOL_TIPS[key]
    assert "Adjust panel above the cap" in prompts.V2_BG_INSTRUCTIONS


# Phrases from the pre-2026-07-26 casual register. Not a style engine — just a
# pin on the specific wording that was rewritten, so a later hand-edit that
# reintroduces the old voice fails loudly instead of shipping.
_CASUAL = ("pop your", "pop it", "grab your", "love where", "no worries",
           "are you after", "tap ")


def test_v2_copy_stays_out_of_the_casual_register():
    for s in _v2_copy_strings():
        low = s.lower()
        for phrase in _CASUAL:
            assert phrase not in low, f"casual phrasing {phrase!r} in: {s!r}"
