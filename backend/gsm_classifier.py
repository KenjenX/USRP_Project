from __future__ import annotations

from math import floor
from typing import Any, Optional

# =========================
# DATA BAND GSM
# =========================
# Data band GSM digabung ke file ini agar tidak perlu file terpisah.
# Mode awal sistem: Downlink only, BTS -> perangkat.

CHANNEL_SPACING_MHZ = 0.2


# Band dengan ARFCN tetap.
# Rumus umum nanti:
# DL = dl_base_mhz + (ARFCN - arfcn_base) * 0.2
FIXED_CHANNEL_BLOCKS = [
    # =========================
    # GSM 900 FAMILY
    # =========================

    # Blok utama GSM 900.
    {
        "profile": "P-GSM 900",
        "family": "GSM 900 Family",
        "display_code": "B8",
        "arfcn_min": 1,
        "arfcn_max": 124,
        "arfcn_base": 0,
        "dl_base_mhz": 935.0,
        "ul_offset_from_dl_mhz": -45.0,
    },
    {
        "profile": "E-GSM 900",
        "family": "GSM 900 Family",
        "display_code": "B8",
        "arfcn_min": 0,
        "arfcn_max": 124,
        "arfcn_base": 0,
        "dl_base_mhz": 935.0,
        "ul_offset_from_dl_mhz": -45.0,
    },
    {
        "profile": "R-GSM 900",
        "family": "GSM 900 Family",
        "display_code": "B8",
        "arfcn_min": 0,
        "arfcn_max": 124,
        "arfcn_base": 0,
        "dl_base_mhz": 935.0,
        "ul_offset_from_dl_mhz": -45.0,
    },
    {
        "profile": "ER-GSM 900",
        "family": "GSM 900 Family",
        "display_code": "B8",
        "arfcn_min": 0,
        "arfcn_max": 124,
        "arfcn_base": 0,
        "dl_base_mhz": 935.0,
        "ul_offset_from_dl_mhz": -45.0,
    },

    # Blok extended GSM 900.
    {
        "profile": "E-GSM 900",
        "family": "GSM 900 Family",
        "display_code": "B8",
        "arfcn_min": 975,
        "arfcn_max": 1023,
        "arfcn_base": 1024,
        "dl_base_mhz": 935.0,
        "ul_offset_from_dl_mhz": -45.0,
    },
    {
        "profile": "R-GSM 900",
        "family": "GSM 900 Family",
        "display_code": "B8",
        "arfcn_min": 955,
        "arfcn_max": 1023,
        "arfcn_base": 1024,
        "dl_base_mhz": 935.0,
        "ul_offset_from_dl_mhz": -45.0,
    },
    {
        "profile": "ER-GSM 900",
        "family": "GSM 900 Family",
        "display_code": "B8",
        "arfcn_min": 940,
        "arfcn_max": 1023,
        "arfcn_base": 1024,
        "dl_base_mhz": 935.0,
        "ul_offset_from_dl_mhz": -45.0,
    },

    # =========================
    # GSM 400 / 850
    # =========================
    {
        "profile": "GSM 450",
        "family": "GSM 450",
        "display_code": "GSM 450",
        "arfcn_min": 259,
        "arfcn_max": 293,
        "arfcn_base": 259,
        "dl_base_mhz": 460.6,
        "ul_offset_from_dl_mhz": -10.0,
    },
    {
        "profile": "GSM 480",
        "family": "GSM 480",
        "display_code": "GSM 480",
        "arfcn_min": 306,
        "arfcn_max": 340,
        "arfcn_base": 306,
        "dl_base_mhz": 489.0,
        "ul_offset_from_dl_mhz": -10.0,
    },
    {
        "profile": "GSM 850",
        "family": "GSM 850",
        "display_code": "B5",
        "arfcn_min": 128,
        "arfcn_max": 251,
        "arfcn_base": 128,
        "dl_base_mhz": 869.2,
        "ul_offset_from_dl_mhz": -45.0,
    },

    # =========================
    # GSM 1800 / 1900
    # =========================
    {
        "profile": "DCS 1800",
        "family": "GSM 1800",
        "display_code": "B3",
        "arfcn_min": 512,
        "arfcn_max": 885,
        "arfcn_base": 512,
        "dl_base_mhz": 1805.2,
        "ul_offset_from_dl_mhz": -95.0,
    },
    {
        "profile": "PCS 1900",
        "family": "GSM 1900",
        "display_code": "B2",
        "arfcn_min": 512,
        "arfcn_max": 810,
        "arfcn_base": 512,
        "dl_base_mhz": 1930.2,
        "ul_offset_from_dl_mhz": -80.0,
    },
]


# Band yang di Sqimway menampilkan ARFCN: Dynamic.
# Program dapat mengenali range downlink, tetapi tidak menghitung
# angka ARFCN spesifik.
DYNAMIC_BANDS = [
    {
        "profile": "T-GSM 380",
        "family": "GSM 380",
        "display_code": "T-GSM 380",
        "arfcn": "Dynamic",
        "dl_low_mhz": 390.2,
        "dl_high_mhz": 399.8,
        "ul_offset_from_dl_mhz": -10.0,
    },
    {
        "profile": "T-GSM 410",
        "family": "GSM 410",
        "display_code": "T-GSM 410",
        "arfcn": "Dynamic",
        "dl_low_mhz": 420.2,
        "dl_high_mhz": 429.8,
        "ul_offset_from_dl_mhz": -10.0,
    },
    {
        "profile": "GSM 710",
        "family": "GSM 710",
        "display_code": "GSM 710",
        "arfcn": "Dynamic",
        "dl_low_mhz": 728.2,
        "dl_high_mhz": 746.2,
        "ul_offset_from_dl_mhz": -30.0,
    },
    {
        "profile": "GSM 750",
        "family": "GSM 750",
        "display_code": "GSM 750",
        "arfcn": "Dynamic",
        "dl_low_mhz": 747.2,
        "dl_high_mhz": 763.2,
        "ul_offset_from_dl_mhz": 30.0,
    },
    {
        "profile": "T-GSM 810",
        "family": "GSM 810",
        "display_code": "T-GSM 810",
        "arfcn": "Dynamic",
        "dl_low_mhz": 851.2,
        "dl_high_mhz": 866.2,
        "ul_offset_from_dl_mhz": -45.0,
    },
]


# =========================
# KONFIGURASI CLASSIFIER GSM
# =========================
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