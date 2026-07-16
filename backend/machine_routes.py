from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import Machine
from backend.schemas import (
    MachineCreate,
    MachineResponse,
    MachineUpdate,
)


router = APIRouter(
    prefix="/api/machines",
    tags=["Machines"],
)


def get_machine_or_404(machine_id: int, db: Session) -> Machine:
    machine = db.query(Machine).filter(Machine.id == machine_id).first()

    if machine is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Machine tidak ditemukan.",
        )

    return machine


@router.get(
    "",
    response_model=list[MachineResponse],
)
def get_machines(db: Session = Depends(get_db)):
    return (
        db.query(Machine)
        .order_by(Machine.id.desc())
        .all()
    )


@router.post(
    "",
    response_model=MachineResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_machine(
    payload: MachineCreate,
    db: Session = Depends(get_db),
):
    machine_name = payload.name.strip()

    if not machine_name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Nama Machine tidak boleh kosong.",
        )

    machine = Machine(
        name=machine_name,
        description=(
            payload.description.strip()
            if payload.description
            else None
        ),
    )

    db.add(machine)

    try:
        db.commit()
        db.refresh(machine)
    except Exception:
        db.rollback()
        raise

    return machine


@router.get(
    "/{machine_id}",
    response_model=MachineResponse,
)
def get_machine(
    machine_id: int,
    db: Session = Depends(get_db),
):
    return get_machine_or_404(machine_id, db)


@router.put(
    "/{machine_id}",
    response_model=MachineResponse,
)
def update_machine(
    machine_id: int,
    payload: MachineUpdate,
    db: Session = Depends(get_db),
):
    machine = get_machine_or_404(machine_id, db)
    update_data = payload.model_dump(exclude_unset=True)

    if "name" in update_data:
        if update_data["name"] is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Nama Machine tidak boleh null.",
            )

        machine_name = update_data["name"].strip()

        if not machine_name:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Nama Machine tidak boleh kosong.",
            )

        machine.name = machine_name

    if "description" in update_data:
        description = update_data["description"]

        machine.description = (
            description.strip()
            if description
            else None
        )

    try:
        db.commit()
        db.refresh(machine)
    except Exception:
        db.rollback()
        raise

    return machine


@router.delete("/{machine_id}")
def delete_machine(
    machine_id: int,
    db: Session = Depends(get_db),
):
    machine = get_machine_or_404(machine_id, db)

    db.delete(machine)

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

    return {
        "message": "Machine berhasil dihapus.",
        "machine_id": machine_id,
    }