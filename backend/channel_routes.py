from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.channel_lookup import lookup_channel_candidates
from backend.database import get_db
from backend.models import Channel, Machine
from backend.schemas import (
    ChannelCreate,
    ChannelResponse,
    ChannelUpdate,
)


FREQUENCY_QUANTUM = Decimal("0.000001")


def _to_frequency_decimal(value: float | None) -> Decimal | None:
    if value is None:
        return None

    return Decimal(str(value)).quantize(FREQUENCY_QUANTUM)


router = APIRouter(tags=["Channels"])


def get_machine_or_404(machine_id: int, db: Session) -> Machine:
    machine = (
        db.query(Machine)
        .filter(Machine.id == machine_id)
        .first()
    )

    if machine is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Machine tidak ditemukan.",
        )

    return machine


def get_channel_or_404(channel_id: int, db: Session) -> Channel:
    channel = (
        db.query(Channel)
        .filter(Channel.id == channel_id)
        .first()
    )

    if channel is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Channel tidak ditemukan.",
        )

    return channel


def resolve_selected_candidate(
    *,
    input_mode: str,
    input_fcn: int,
    candidate_key: str,
) -> dict[str, Any]:
    cleaned_candidate_key = candidate_key.strip()

    if not cleaned_candidate_key:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="candidate_key tidak boleh kosong.",
        )

    try:
        candidates = lookup_channel_candidates(
            input_mode,
            input_fcn,
        )
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(error),
        ) from error

    if not candidates:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Tidak ada kandidat Channel untuk "
                "Technology/Profile dan FCN tersebut."
            ),
        )

    selected_candidate = next(
        (
            candidate
            for candidate in candidates
            if candidate["candidate_key"] == cleaned_candidate_key
        ),
        None,
    )

    if selected_candidate is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": (
                    "candidate_key tidak cocok dengan hasil lookup terbaru."
                ),
                "valid_candidate_keys": [
                    candidate["candidate_key"]
                    for candidate in candidates
                ],
            },
        )

    if not selected_candidate["monitorable"]:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Kandidat berada di luar rentang monitoring "
                "USRP B210 50–6000 MHz."
            ),
        )

    return selected_candidate


def get_next_channel_number(
    machine_id: int,
    db: Session,
) -> str:
    existing_numbers = (
        db.query(Channel.channel_number)
        .filter(Channel.machine_id == machine_id)
        .all()
    )

    highest_number = 0

    for row in existing_numbers:
        channel_number = row[0]

        if not isinstance(channel_number, str):
            continue

        if not channel_number.upper().startswith("CH"):
            continue

        numeric_part = channel_number[2:]

        if numeric_part.isdigit():
            highest_number = max(
                highest_number,
                int(numeric_part),
            )

    return f"CH{highest_number + 1}"


def apply_candidate_to_channel(
    channel: Channel,
    candidate: dict[str, Any],
) -> None:
    channel.input_mode = candidate["input_mode"]
    channel.input_fcn = candidate["requested_fcn"]

    channel.freq_dl_mhz = _to_frequency_decimal(
        candidate["freq_dl_mhz"]
    )
    channel.freq_ul_mhz = _to_frequency_decimal(
        candidate["freq_ul_mhz"]
    )

    channel.fcn_dl = candidate["fcn_dl"]
    channel.fcn_ul = candidate["fcn_ul"]

    channel.band = candidate["band"]
    channel.mode = candidate["mode"]


@router.get(
    "/api/machines/{machine_id}/channels",
    response_model=list[ChannelResponse],
)
def get_machine_channels(
    machine_id: int,
    db: Session = Depends(get_db),
):
    get_machine_or_404(machine_id, db)

    return (
        db.query(Channel)
        .filter(Channel.machine_id == machine_id)
        .order_by(Channel.id.asc())
        .all()
    )


@router.post(
    "/api/machines/{machine_id}/channels",
    response_model=ChannelResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_channel(
    machine_id: int,
    payload: ChannelCreate,
    db: Session = Depends(get_db),
):
    get_machine_or_404(machine_id, db)

    selected_candidate = resolve_selected_candidate(
        input_mode=payload.input_mode,
        input_fcn=payload.input_fcn,
        candidate_key=payload.candidate_key,
    )

    channel = Channel(
        machine_id=machine_id,
        channel_number=get_next_channel_number(
            machine_id,
            db,
        ),
    )
    apply_candidate_to_channel(
        channel,
        selected_candidate,
    )

    db.add(channel)

    try:
        db.commit()
        db.refresh(channel)
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Nomor Channel bentrok dengan data lain. "
                "Silakan ulangi proses pembuatan Channel."
            ),
        ) from error
    except Exception:
        db.rollback()
        raise

    return channel


@router.get(
    "/api/channels/{channel_id}",
    response_model=ChannelResponse,
)
def get_channel(
    channel_id: int,
    db: Session = Depends(get_db),
):
    return get_channel_or_404(channel_id, db)


@router.put(
    "/api/channels/{channel_id}",
    response_model=ChannelResponse,
)
def update_channel(
    channel_id: int,
    payload: ChannelUpdate,
    db: Session = Depends(get_db),
):
    channel = get_channel_or_404(channel_id, db)

    selected_candidate = resolve_selected_candidate(
        input_mode=payload.input_mode,
        input_fcn=payload.input_fcn,
        candidate_key=payload.candidate_key,
    )

    apply_candidate_to_channel(
        channel,
        selected_candidate,
    )

    try:
        db.commit()
        db.refresh(channel)
    except Exception:
        db.rollback()
        raise

    return channel


@router.delete("/api/channels/{channel_id}")
def delete_channel(
    channel_id: int,
    db: Session = Depends(get_db),
):
    channel = get_channel_or_404(channel_id, db)

    deleted_data = {
        "channel_id": channel.id,
        "machine_id": channel.machine_id,
        "channel_number": channel.channel_number,
    }

    db.delete(channel)

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

    return {
        "message": "Channel berhasil dihapus.",
        **deleted_data,
    }
