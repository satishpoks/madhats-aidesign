"""Shared Gemini compositing logic for the Flash (preview) and Pro (final) tiers.

Always sends the real product reference photo as the first image part so the model
composites onto it rather than inventing a cap shape.
"""
from __future__ import annotations

import io
import time

import google.generativeai as genai
import httpx
import structlog
from PIL import Image

from app.config import settings
from app.services.image.image_provider import (
    GenerationParams,
    GenerationResult,
    ImageProvider,
)
from app.storage import write_generated

log = structlog.get_logger()

# Rough per-image cost estimates (USD) — real figures come from billing later.
_COST_BY_TIER = {"preview": 0.002, "final": 0.01}

# Every generated image is normalised to this exact square size before storage,
# so the output is a consistent 1000x1000 PNG on a white backdrop regardless of
# what the model returns (the prompt asks for white + square, this guarantees it).
_OUTPUT_SIZE = 1000

# Role labels interleaved before each image part. Reinforces the FIRST/SECOND
# image references in the prompt so the model applies the logo onto the cap
# instead of reproducing it as a separate panel.
_FIRST_IMAGE_LABEL = (
    "FIRST IMAGE — the exact product cap to reproduce. Its shape, framing and "
    "square 1:1 aspect ratio define the OUTPUT; match it exactly."
)
_SECOND_IMAGE_LABEL = (
    "SECOND IMAGE — the customer's artwork to apply onto the cap as decoration "
    "ONLY. Use it as a reference; never reproduce it as a separate element. It "
    "does NOT set the output shape, size or aspect ratio — those come only from "
    "the FIRST image, whatever this artwork's proportions are."
)
_PRIOR_DESIGN_LABEL = (
    "CURRENT DESIGN — this image is the customer's existing design on this cap. "
    "REFINE it: reproduce it exactly and change ONLY what the customer requested "
    "below; keep every other detail identical. It does NOT change the output "
    "shape or aspect ratio — those come only from the FIRST image."
)


async def _fetch_bytes(url: str) -> tuple[bytes, str]:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.content, resp.headers.get("content-type", "image/png")


def _to_square(image_bytes: bytes) -> bytes:
    """Pad an image to a 1:1 square (white background, centred).

    Gemini image models tend to match the input image's aspect ratio, so sending
    a square reference strongly biases a square, single-cap output and leaves no
    room for the side-by-side/second-panel collage. Returns the input unchanged
    if it is already square or can't be decoded (never break generation on this).
    """
    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception:  # noqa: BLE001
        return image_bytes
    w, h = img.size
    if w == h:
        return image_bytes
    side = max(w, h)
    canvas = Image.new("RGB", (side, side), (255, 255, 255))
    canvas.paste(img, ((side - w) // 2, (side - h) // 2))
    out = io.BytesIO()
    canvas.save(out, format="PNG")
    return out.getvalue()


def _to_square_logo(image_bytes: bytes) -> bytes:
    """Center-pad an uploaded logo/artwork to a 1:1 square on a TRANSPARENT canvas.

    The output aspect ratio must follow the reference CAP (the first image),
    never the logo. A long/wide logo sent at its native aspect ratio biases
    Gemini toward a wide output, which then letterboxes/distorts the cap once we
    square it. Padding the logo to a square removes that bias while leaving the
    artwork itself untouched — the padding is transparent, so no white box is
    introduced around the logo. Returns the input unchanged if it is already
    square or can't be decoded (never break generation on this).
    """
    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
    except Exception:  # noqa: BLE001
        return image_bytes
    w, h = img.size
    if w == h:
        return image_bytes
    side = max(w, h)
    canvas = Image.new("RGBA", (side, side), (255, 255, 255, 0))
    canvas.alpha_composite(img, ((side - w) // 2, (side - h) // 2))
    out = io.BytesIO()
    canvas.save(out, format="PNG")
    return out.getvalue()


def _normalise_output(image_bytes: bytes) -> bytes:
    """Force the generated image to an exact ``_OUTPUT_SIZE`` square PNG on white.

    Gemini returns whatever dimensions it likes and can leave a non-white or
    off-square canvas even when the prompt asks for one. To make the delivered
    asset consistent every time, pad the image onto a pure-white square (any
    transparency composited over white) and resize to exactly 1000x1000. Returns
    the input unchanged only if it can't be decoded (never break generation).
    """
    try:
        img = Image.open(io.BytesIO(image_bytes))
    except Exception:  # noqa: BLE001
        return image_bytes
    # Flatten any alpha onto white so transparent corners don't render grey/black.
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        canvas = Image.new("RGBA", img.size, (255, 255, 255, 255))
        canvas.alpha_composite(img)
        img = canvas.convert("RGB")
    else:
        img = img.convert("RGB")
    w, h = img.size
    side = max(w, h)
    if w != h:
        square = Image.new("RGB", (side, side), (255, 255, 255))
        square.paste(img, ((side - w) // 2, (side - h) // 2))
        img = square
    if img.size != (_OUTPUT_SIZE, _OUTPUT_SIZE):
        img = img.resize((_OUTPUT_SIZE, _OUTPUT_SIZE), Image.LANCZOS)
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


class _GeminiAdapter(ImageProvider):
    tier: str = "preview"

    def __init__(self, model_name: str):
        if not settings.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY is not configured")
        genai.configure(api_key=settings.gemini_api_key)
        self.model_name = model_name

    async def generate(
        self,
        prompt: str,
        reference_image_url: str,
        uploaded_asset_url: str | None,
        params: GenerationParams,
        prior_design_url: str | None = None,
    ) -> GenerationResult:
        if not reference_image_url:
            raise ValueError("reference_image_url is required — never generate a cap from scratch")

        started = time.monotonic()

        ref_bytes, ref_mime = await _fetch_bytes(reference_image_url)
        # Square the reference so the model returns a square, single-cap image
        # (these models follow the input aspect ratio) — kills the wide canvas
        # the model was filling with a side-by-side title panel.
        squared = _to_square(ref_bytes)
        if squared is not ref_bytes:
            ref_bytes, ref_mime = squared, "image/png"
        # Label each image part so the model can't conflate the two inputs and
        # echo the logo back as its own panel (the two-panel collage failure).
        contents: list = [
            _FIRST_IMAGE_LABEL,
            {"mime_type": ref_mime, "data": ref_bytes},
        ]

        # On an edit, the previous render rides along as the design to REFINE.
        if prior_design_url:
            try:
                prior_bytes, prior_mime = await _fetch_bytes(prior_design_url)
                contents.append(_PRIOR_DESIGN_LABEL)
                contents.append({"mime_type": prior_mime, "data": prior_bytes})
            except httpx.HTTPError:
                log.warning("prior_design_fetch_failed", tier=self.tier)

        if uploaded_asset_url:
            try:
                logo_bytes, logo_mime = await _fetch_bytes(uploaded_asset_url)
                # Square the logo (transparently) so its aspect ratio can't bias
                # the output shape — the output follows the reference cap only.
                squared_logo = _to_square_logo(logo_bytes)
                if squared_logo is not logo_bytes:
                    logo_bytes, logo_mime = squared_logo, "image/png"
                contents.append(_SECOND_IMAGE_LABEL)
                contents.append({"mime_type": logo_mime, "data": logo_bytes})
            except httpx.HTTPError:
                log.warning("logo_fetch_failed", tier=self.tier)

        contents.append(prompt)

        model = genai.GenerativeModel(self.model_name)
        response = await model.generate_content_async(contents)

        image_bytes = _extract_image(response)
        if image_bytes is None:
            raise RuntimeError("Gemini returned no image data")

        # Guarantee a consistent 500x500 white-background PNG regardless of what
        # the model actually returned.
        image_bytes = _normalise_output(image_bytes)
        storage_path = write_generated(image_bytes, tier=self.tier)
        latency_ms = int((time.monotonic() - started) * 1000)

        meta = _response_meta(response)
        meta["model"] = self.model_name

        return GenerationResult(
            image_url=storage_path,
            cost_usd=_COST_BY_TIER.get(self.tier, 0.0),
            latency_ms=latency_ms,
            model=self.model_name,
            raw_response=_serialise_response(response),
            response_meta=meta,
        )


def _extract_image(response) -> bytes | None:
    """Pull inline image bytes out of a Gemini response."""
    try:
        for candidate in response.candidates:
            for part in candidate.content.parts:
                inline = getattr(part, "inline_data", None)
                if inline and getattr(inline, "data", None):
                    return inline.data
    except (AttributeError, IndexError):
        pass
    return None


def _serialise_response(response) -> dict:
    """Serialise a Gemini response to a JSON-safe dict for the audit log.

    Bytes fields (the generated image) become base64 automatically. Best-effort:
    tries the SDK's own conversion, then protobuf, then falls back to a repr so a
    quirky/mocked response can never break logging.
    """
    try:
        return type(response).to_dict(response)  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        pass
    try:
        from google.protobuf.json_format import MessageToDict

        return MessageToDict(response._result)  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        return {"unserialisable": True, "repr": repr(response)[:2000]}


def _response_meta(response) -> dict:
    """Compact summary of a Gemini response for quick scanning in the log."""
    meta: dict = {
        "image_returned": _extract_image(response) is not None,
        "candidate_count": 0,
        "finish_reason": None,
        "safety_ratings": None,
    }
    try:
        candidates = list(response.candidates or [])
        meta["candidate_count"] = len(candidates)
        if candidates:
            first = candidates[0]
            fr = getattr(first, "finish_reason", None)
            meta["finish_reason"] = getattr(fr, "name", None) or (str(fr) if fr is not None else None)
            ratings = getattr(first, "safety_ratings", None)
            if ratings:
                meta["safety_ratings"] = [str(r) for r in ratings]
    except Exception:  # noqa: BLE001
        pass
    return meta
