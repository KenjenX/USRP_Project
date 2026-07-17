from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class MachineCreate(BaseModel):
    name: str = Field(
        min_length=1,
        max_length=100,
    )
    description: str | None = None


class MachineUpdate(BaseModel):
    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
    )
    description: str | None = None


class MachineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None
    created_at: datetime
    updated_at: datetime


class ChannelRasterOptionResponse(BaseModel):
    raster_khz: int
    nref_step_size: int


class ChannelCandidateResponse(BaseModel):
    candidate_key: str
    technology: str
    input_mode: str
    fcn_type: str
    requested_fcn: int
    band: str
    band_name: str
    legacy_band_name: str | None = None
    duplex_mode: str
    direction: str
    mode: str
    freq_dl_mhz: float | None
    freq_ul_mhz: float | None
    fcn_dl: int | None
    fcn_ul: int | None
    raster_options: list[ChannelRasterOptionResponse] = Field(
        default_factory=list,
    )
    monitorable: bool


class ChannelLookupResponse(BaseModel):
    input_mode: str
    input_fcn: int
    candidate_count: int
    candidates: list[ChannelCandidateResponse]
