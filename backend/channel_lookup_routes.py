from fastapi import APIRouter, HTTPException, Query, status

from backend.channel_lookup import (
    SUPPORTED_INPUT_MODES,
    lookup_channel_candidates,
)
from backend.schemas import ChannelLookupResponse


router = APIRouter(
    prefix="/api/channel-lookup",
    tags=["Channel Lookup"],
)


def _canonical_input_mode(input_mode: str) -> str:
    cleaned_mode = input_mode.strip()

    if not cleaned_mode:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Technology/Profile tidak boleh kosong.",
        )

    for supported_mode in SUPPORTED_INPUT_MODES:
        if cleaned_mode.casefold() == supported_mode.casefold():
            return supported_mode

    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=(
            "Technology/Profile tidak didukung. Gunakan salah satu: "
            + ", ".join(SUPPORTED_INPUT_MODES)
        ),
    )


@router.get(
    "",
    response_model=ChannelLookupResponse,
)
def preview_channel_lookup(
    input_mode: str = Query(
        ...,
        min_length=1,
        description=(
            "Technology/Profile: 2G E-GSM 900, 2G DCS 1800, "
            "3G UMTS, 4G LTE, atau 5G NR."
        ),
    ),
    fcn: int = Query(
        ...,
        ge=0,
        description="ARFCN, UARFCN, EARFCN, atau NR-ARFCN.",
    ),
):
    canonical_input_mode = _canonical_input_mode(input_mode)

    try:
        candidates = lookup_channel_candidates(
            canonical_input_mode,
            fcn,
        )
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(error),
        ) from error

    return {
        "input_mode": canonical_input_mode,
        "input_fcn": fcn,
        "candidate_count": len(candidates),
        "candidates": candidates,
    }
