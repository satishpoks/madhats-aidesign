"""canvas_steps.observe_canvas — read a manually-ticked "Remove background".

Pure over plain dicts: no DB, no HTTP, no model. The blob is whatever the
frontend's canvasStore.toCanvasDesign() produces.
"""
from __future__ import annotations

from app.services.conversation import canvas_steps as cs


def _design(front_elements):
    return {"colourway": None,
            "faces": {"front": front_elements, "back": [], "left": [], "right": []}}


def _img(**kw):
    base = {"type": "image", "locked": False, "removeBg": False}
    base.update(kw)
    return base


def test_a_ticked_logo_is_recorded_as_removed():
    c = {"pending_logo": {"face": "front", "placed": True}}
    assert cs.observe_canvas(c, _design([_img(removeBg=True)])) is True
    assert c["pending_logo"]["bg"] == "removed"


def test_an_unticked_logo_writes_nothing():
    """Absence of a tick is silence, not a "no" — the step must still be asked."""
    c = {"pending_logo": {"face": "front", "placed": True}}
    assert cs.observe_canvas(c, _design([_img(removeBg=False)])) is False
    assert "bg" not in c["pending_logo"]


def test_an_already_answered_bg_is_never_overwritten():
    """The customer answered the chip "No, it's fine as it is". A stale tick on
    the canvas must not silently flip their answer."""
    c = {"pending_logo": {"face": "front", "bg": "none"}}
    assert cs.observe_canvas(c, _design([_img(removeBg=True)])) is False
    assert c["pending_logo"]["bg"] == "none"


def test_a_locked_ticked_image_is_ignored():
    """Second pass of the logo loop: the FIRST logo is locked and was ticked;
    the new pending one is not. Reading the locked one would answer this step
    with the previous logo's setting."""
    c = {"pending_logo": {"face": "front", "placed": True}}
    design = _design([_img(locked=True, removeBg=True), _img(removeBg=False)])
    assert cs.observe_canvas(c, design) is False
    assert "bg" not in c["pending_logo"]


def test_it_reads_the_last_unlocked_image_not_the_first():
    c = {"pending_logo": {"face": "front", "placed": True}}
    design = _design([_img(removeBg=False), _img(removeBg=True)])
    assert cs.observe_canvas(c, design) is True


def test_non_image_elements_are_skipped():
    """A text element placed after the logo must not shadow it."""
    c = {"pending_logo": {"face": "front", "placed": True}}
    design = _design([_img(removeBg=True), {"type": "text", "locked": False}])
    assert cs.observe_canvas(c, design) is True


def test_it_reads_the_pending_logos_own_face():
    c = {"pending_logo": {"face": "back", "placed": True}}
    design = {"colourway": None,
              "faces": {"front": [_img(removeBg=True)], "back": [_img(removeBg=False)],
                        "left": [], "right": []}}
    assert cs.observe_canvas(c, design) is False


def test_no_pending_logo_is_a_no_op():
    c = {"logos_done": True, "pending_logo": None}
    assert cs.observe_canvas(c, _design([_img(removeBg=True)])) is False


def test_a_pending_logo_with_no_face_is_a_no_op():
    """Before ASK_LOGO_PLACEMENT is answered there is no face to read."""
    c = {"pending_logo": {}}
    assert cs.observe_canvas(c, _design([_img(removeBg=True)])) is False


def test_a_missing_or_malformed_blob_never_raises():
    for blob in (None, {}, {"faces": None}, {"faces": {"front": None}},
                 {"faces": {"front": ["not-a-dict"]}}, "nonsense", []):
        c = {"pending_logo": {"face": "front", "placed": True}}
        assert cs.observe_canvas(c, blob) is False
        assert "bg" not in c["pending_logo"]
