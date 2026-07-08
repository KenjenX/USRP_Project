from __future__ import annotations

from math import floor
from typing import Any, Optional

from backend.gsm_band_registry import (
    CHANNEL_SPACING_MHZ,
    DYNAMIC_BANDS,
    FIXED_CHANNEL_BLOCKS,
)


MAX_CHANNEL_OFFSET_MHZ = 0.1


def _nearest_integer(value: float) -> int:
    """Membulatkan ke channel frekuensi terdekat."""
    return floor(value + 0.5)


def _build_result(
    *,
    raw_dl_mhz: float,
    family: str,
    band_code: str,
    arfcn: int | str,
    channel_dl_mhz: float,
    ul_offset_from_dl_mhz: float,
    possible_profiles: list[str],
    arfcn_type: str,
) -> dict[str, Any]:
    """
    Membentuk hasil klasifikasi yang dikirim ke main.py dan React.
    """

    channel_ul_mhz = channel_dl_mhz + ul_offset_from_dl_mhz

    return {
        "mode": "2G GSM",
        "band": family,
        "band_code": band_code,
        "arfcn": arfcn,
        "fcn": arfcn,
        "fcn_ul": arfcn,
        "arfcn_type": arfcn_type,
        "possible_profiles": possible_profiles,
        "direction": "Downlink",
        "detected_freq_dl_mhz": round(raw_dl_mhz, 6),
        "freq_dl_mhz": round(channel_dl_mhz, 6),
        "freq_ul_mhz": round(channel_ul_mhz, 6),
        "duplex_spacing_mhz": abs(ul_offset_from_dl_mhz),
        "uplink_offset_from_dl_mhz": ul_offset_from_dl_mhz,
        "channel_spacing_mhz": CHANNEL_SPACING_MHZ,
        "channel_offset_khz": round(
            (raw_dl_mhz - channel_dl_mhz) * 1000,
            3,
        ),
        "classification_note": (
            "Frequency-based GSM downlink candidate"
        ),
    }


def _find_fixed_matches(freq_dl_mhz: float) -> list[dict[str, Any]]:
    """
    Mencari semua blok fixed-ARFCN yang cocok.

    Satu frekuensi dapat cocok dengan beberapa profile,
    contohnya P-GSM/E-GSM/R-GSM/ER-GSM 900.
    """

    matches: list[dict[str, Any]] = []

    for block in FIXED_CHANNEL_BLOCKS:
        arfcn = _nearest_integer(
            block["arfcn_base"]
            + (
                (freq_dl_mhz - block["dl_base_mhz"])
                / CHANNEL_SPACING_MHZ
            )
        )

        if not block["arfcn_min"] <= arfcn <= block["arfcn_max"]:
            continue

        channel_dl_mhz = block["dl_base_mhz"] + (
            (arfcn - block["arfcn_base"])
            * CHANNEL_SPACING_MHZ
        )

        if abs(freq_dl_mhz - channel_dl_mhz) > MAX_CHANNEL_OFFSET_MHZ:
            continue

        matches.append(
            {
                **block,
                "arfcn": arfcn,
                "channel_dl_mhz": channel_dl_mhz,
            }
        )

    return matches


def _classify_fixed_band(
    freq_dl_mhz: float,
) -> Optional[dict[str, Any]]:
    """Membuat hasil klasifikasi untuk band dengan ARFCN tetap."""

    matches = _find_fixed_matches(freq_dl_mhz)

    if not matches:
        return None

    first_match = matches[0]

    # Menghapus profile duplikat, tetapi urutan tetap dipertahankan.
    possible_profiles = list(
        dict.fromkeys(
            match["profile"]
            for match in matches
        )
    )

    return _build_result(
        raw_dl_mhz=freq_dl_mhz,
        family=first_match["family"],
        band_code=first_match["display_code"],
        arfcn=first_match["arfcn"],
        channel_dl_mhz=first_match["channel_dl_mhz"],
        ul_offset_from_dl_mhz=(
            first_match["ul_offset_from_dl_mhz"]
        ),
        possible_profiles=possible_profiles,
        arfcn_type="Fixed",
    )


def _classify_dynamic_band(
    freq_dl_mhz: float,
) -> Optional[dict[str, Any]]:
    """
    Mencocokkan band dengan ARFCN Dynamic.

    Nomor ARFCN tidak dihitung karena tabel Sqimway
    memang menandainya sebagai Dynamic.
    """

    for band in DYNAMIC_BANDS:
        channel_index = _nearest_integer(
            (freq_dl_mhz - band["dl_low_mhz"])
            / CHANNEL_SPACING_MHZ
        )

        channel_dl_mhz = band["dl_low_mhz"] + (
            channel_index * CHANNEL_SPACING_MHZ
        )

        if not (
            band["dl_low_mhz"]
            <= channel_dl_mhz
            <= band["dl_high_mhz"]
        ):
            continue

        if abs(freq_dl_mhz - channel_dl_mhz) > MAX_CHANNEL_OFFSET_MHZ:
            continue

        return _build_result(
            raw_dl_mhz=freq_dl_mhz,
            family=band["family"],
            band_code=band["display_code"],
            arfcn=band["arfcn"],
            channel_dl_mhz=channel_dl_mhz,
            ul_offset_from_dl_mhz=(
                band["ul_offset_from_dl_mhz"]
            ),
            possible_profiles=[band["profile"]],
            arfcn_type="Dynamic",
        )

    return None


def classify_gsm(
    freq_dl_mhz: float,
) -> Optional[dict[str, Any]]:
    """
    Mencocokkan satu peak frekuensi downlink dengan registry GSM.

    Catatan:
    - Mode saat ini hanya Downlink, BTS -> perangkat.
    - Hasil adalah kandidat berdasarkan lokasi frekuensi.
    - Hasil belum membuktikan sinyal tersebut benar-benar GSM.
    """

    try:
        frequency = float(freq_dl_mhz)
    except (TypeError, ValueError):
        return None

    if frequency <= 0:
        return None

    fixed_result = _classify_fixed_band(frequency)

    if fixed_result is not None:
        return fixed_result

    return _classify_dynamic_band(frequency)