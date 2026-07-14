"""The single interface for all image generation.

A route never calls a model API directly — it always goes through an ImageProvider
returned by router.get_provider(). Every call passes the real product reference
photo as conditioning input.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class GenerationParams:
    tier: str  # preview | final
    placement_zone: str = "front_panel"
    placement_position: str = "centre"
    decoration_type: str = "print"  # embroidery | print | patch
    remove_bg: bool = False
    pin_annotations: list[dict] = field(default_factory=list)
    resolution: str = "standard"  # standard | 2k


@dataclass
class GenerationResult:
    image_url: str  # storage path of the clean generated image
    cost_usd: float
    latency_ms: int
    model: str
    # Optional audit payloads (populated by real adapters, logged to generation_logs).
    raw_response: dict | None = None  # full serialised provider response
    response_meta: dict | None = None  # compact summary (finish reason, safety, etc.)
    # The exact final payload sent to the image model: model name + ordered
    # content parts (text verbatim; images as role/mime/source/byte-size — the
    # bytes themselves live in Storage). Logged to generation_logs.request_payload.
    request_payload: dict | None = None


class ImageProvider(ABC):
    @abstractmethod
    async def generate(
        self,
        prompt: str,
        reference_image_url: str,  # real product photo — always required
        uploaded_asset_url: str | None,  # customer logo/artwork, if any
        params: GenerationParams,
        prior_design_url: str | None = None,  # previous render to REFINE (edits only)
        layout_guide_url: str | None = None,  # flattened canvas — layout guide (canvas flow)
    ) -> GenerationResult:
        ...
