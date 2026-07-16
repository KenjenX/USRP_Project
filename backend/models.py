from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import relationship

from backend.database import Base


class Machine(Base):
    __tablename__ = "machines"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)

    created_at = Column(
        DateTime,
        nullable=False,
        server_default=func.now(),
    )
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    channels = relationship(
        "Channel",
        back_populates="machine",
        cascade="all, delete-orphan",
    )


class Channel(Base):
    __tablename__ = "channels"

    id = Column(Integer, primary_key=True, index=True)

    machine_id = Column(
        Integer,
        ForeignKey("machines.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    channel_number = Column(String(20), nullable=False)

    input_mode = Column(String(50), nullable=False)
    input_fcn = Column(Integer, nullable=False)

    freq_dl_mhz = Column(Float, nullable=True)
    freq_ul_mhz = Column(Float, nullable=True)

    fcn_dl = Column(Integer, nullable=True)
    fcn_ul = Column(Integer, nullable=True)

    band = Column(String(30), nullable=False)
    mode = Column(String(50), nullable=False)

    created_at = Column(
        DateTime,
        nullable=False,
        server_default=func.now(),
    )
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    machine = relationship(
        "Machine",
        back_populates="channels",
    )

    __table_args__ = (
        UniqueConstraint(
            "machine_id",
            "channel_number",
            name="uq_machine_channel_number",
        ),
    )