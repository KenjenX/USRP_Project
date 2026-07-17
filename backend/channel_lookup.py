from __future__ import annotations

from typing import Any

from backend.gsm_classifier import (
    CHANNEL_SPACING_MHZ,
    FIXED_CHANNEL_BLOCKS,
)
from backend.lte_classifier import (
    LTE_BANDS,
    LTE_CHANNEL_SPACING_MHZ,
)
from backend.nr_classifier import NR_FR1_BANDS


USRP_MIN_FREQUENCY_MHZ = 50.0
USRP_MAX_FREQUENCY_MHZ = 6000.0


# Nama ini nantinya menjadi value dropdown pada frontend.
SUPPORTED_INPUT_MODES = {
    "2G E-GSM 900": "E-GSM 900",
    "2G DCS 1800": "DCS 1800",
    "3G UMTS": "UMTS",
    "4G LTE": "LTE",
    "5G NR": "NR",
}


# Registry khusus Channel Lookup:
# UARFCN -> frekuensi UMTS FDD.
#
# Format setiap sisi:
# (uarfcn_low, uarfcn_high, frequency_low_mhz)
#
# Frekuensi berikutnya dihitung menggunakan channel spacing 0.2 MHz.
UMTS_FDD_CHANNEL_SPACING_MHZ = 0.2

UMTS_FDD_LOOKUP_BANDS: list[dict[str, Any]] = [
    {
        "band": "1",
        "name": "2100",
        "dl": (10562, 10838, 2112.4),
        "ul": (9612, 9888, 1922.4),
    },
    {
        "band": "2",
        "name": "1900 PCS",
        "dl": (9662, 9938, 1932.4),
        "ul": (9262, 9538, 1852.4),
    },
    {
        "band": "3",
        "name": "1800 DCS",
        "dl": (1162, 1513, 1807.4),
        "ul": (937, 1288, 1712.4),
    },
    {
        "band": "4",
        "name": "AWS-1",
        "dl": (1537, 1738, 2112.4),
        "ul": (1312, 1513, 1712.4),
    },
    {
        "band": "5",
        "name": "850",
        "dl": (4357, 4458, 871.4),
        "ul": (4132, 4233, 826.4),
    },
    {
        "band": "6",
        "name": "850 Japan",
        "dl": (4387, 4413, 877.4),
        "ul": (4162, 4188, 832.4),
    },
    {
        "band": "7",
        "name": "2600",
        "dl": (2237, 2563, 2622.4),
        "ul": (2012, 2338, 2502.4),
    },
    {
        "band": "8",
        "name": "900 GSM",
        "dl": (2937, 3088, 927.4),
        "ul": (2712, 2863, 882.4),
    },
    {
        "band": "9",
        "name": "1800 Japan",
        "dl": (9237, 9387, 1847.4),
        "ul": (8762, 8912, 1752.4),
    },
    {
        "band": "10",
        "name": "AWS-1+",
        "dl": (3112, 3388, 2112.4),
        "ul": (2887, 3163, 1712.4),
    },
    {
        "band": "11",
        "name": "1500 Lower",
        "dl": (3712, 3787, 1478.4),
        "ul": (3487, 3562, 1430.4),
    },
    {
        "band": "12",
        "name": "700 a",
        "dl": (3842, 3903, 731.4),
        "ul": (3617, 3678, 701.4),
    },
    {
        "band": "13",
        "name": "700 c",
        "dl": (4017, 4043, 748.4),
        "ul": (3792, 3818, 779.4),
    },
    {
        "band": "14",
        "name": "700 PS",
        "dl": (4117, 4143, 760.4),
        "ul": (3892, 3918, 790.4),
    },
    {
        "band": "19",
        "name": "800 Japan",
        "dl": (712, 763, 877.4),
        "ul": (312, 363, 832.4),
    },
    {
        "band": "20",
        "name": "800 DD",
        "dl": (4512, 4638, 793.4),
        "ul": (4287, 4413, 834.4),
    },
    {
        "band": "21",
        "name": "1500 Upper",
        "dl": (862, 912, 1498.4),
        "ul": (462, 512, 1450.4),
    },
    {
        "band": "22",
        "name": "3500",
        "dl": (4662, 5038, 3512.4),
        "ul": (4437, 4813, 3412.4),
    },
    {
        "band": "25",
        "name": "1900+",
        "dl": (5112, 5413, 1932.4),
        "ul": (4887, 5188, 1852.4),
    },
    {
        "band": "26",
        "name": "850+",
        "dl": (5762, 5913, 861.4),
        "ul": (5537, 5688, 816.4),
    },
    {
        "band": "32",
        "name": "1500 L-band",
        "dl": (6617, 6813, 1454.4),
        "ul": None,
    },
]

# Registry UMTS TDD 1.28 Mcps untuk Channel Lookup.
#
# UTRA TDD memakai shared frequency untuk uplink dan downlink.
# Untuk 1.28 Mcps TDD, frekuensi carrier dihitung dengan:
#     frequency_mhz = UARFCN / 5
#
# Rentang berikut mengikuti 3GPP TS 25.102 Release 18,
# Table 5.2 (1.28 Mcps TDD Option).
UMTS_TDD_LOOKUP_BANDS: list[dict[str, Any]] = [
    {
        "band": "33",
        "name": "TD 1900",
        "legacy_name": "A(lo)",
        "uarfcn_low": 9504,
        "uarfcn_high": 9596,
    },
    {
        "band": "34",
        "name": "TD 2000",
        "legacy_name": "A(hi)",
        "uarfcn_low": 10054,
        "uarfcn_high": 10121,
    },
    {
        "band": "35",
        "name": "TD PCS Lower",
        "legacy_name": "B(lo)",
        "uarfcn_low": 9254,
        "uarfcn_high": 9546,
    },
    {
        "band": "36",
        "name": "TD PCS Upper",
        "legacy_name": "B(hi)",
        "uarfcn_low": 9654,
        "uarfcn_high": 9946,
    },
    {
        "band": "37",
        "name": "TD PCS Center gap",
        "legacy_name": "C",
        "uarfcn_low": 9554,
        "uarfcn_high": 9646,
    },
    {
        "band": "38",
        "name": "TD 2600",
        "legacy_name": "D",
        "uarfcn_low": 12854,
        "uarfcn_high": 13096,
    },
    {
        "band": "39",
        "name": "TD 1900+",
        "legacy_name": "F",
        "uarfcn_low": 9404,
        "uarfcn_high": 9596,
    },
    {
        "band": "40",
        "name": "TD 2300",
        "legacy_name": "E",
        "uarfcn_low": 11504,
        "uarfcn_high": 11996,
    },
]



def _normalize_input_mode(input_mode: str) -> str:
    """
    Mengubah penulisan input menjadi nama mode canonical.

    Contoh:
    '2g e-gsm 900' -> '2G E-GSM 900'
    """
    if not isinstance(input_mode, str):
        raise ValueError("input_mode harus berupa teks.")

    cleaned_mode = input_mode.strip()

    for supported_mode in SUPPORTED_INPUT_MODES:
        if cleaned_mode.casefold() == supported_mode.casefold():
            return supported_mode

    raise ValueError(
        "Mode belum didukung. Gunakan salah satu: "
        + ", ".join(SUPPORTED_INPUT_MODES)
    )


def _validate_fcn(input_fcn: int) -> int:
    """
    FCN wajib berupa integer non-negatif.
    Boolean ditolak karena bool merupakan turunan int di Python.
    """
    if isinstance(input_fcn, bool) or not isinstance(input_fcn, int):
        raise ValueError("FCN harus berupa bilangan bulat.")

    if input_fcn < 0:
        raise ValueError("FCN tidak boleh bernilai negatif.")

    return input_fcn


def _round_frequency(value: float) -> float:
    return round(float(value), 6)


def _is_monitorable(*frequencies_mhz: float | None) -> bool:
    """
    Memastikan seluruh frekuensi yang tersedia berada dalam
    rentang monitoring project 50–6000 MHz.
    """
    available_frequencies = [
        frequency
        for frequency in frequencies_mhz
        if frequency is not None
    ]

    if not available_frequencies:
        return False

    return all(
        USRP_MIN_FREQUENCY_MHZ
        <= frequency
        <= USRP_MAX_FREQUENCY_MHZ
        for frequency in available_frequencies
    )


def _make_profile_key(profile: str) -> str:
    return (
        profile.upper()
        .replace("-", "_")
        .replace(" ", "_")
    )


def _lookup_gsm(
    canonical_input_mode: str,
    input_fcn: int,
) -> list[dict[str, Any]]:
    """
    Melakukan lookup ARFCN -> frekuensi GSM.

    Scope project:
    - E-GSM 900
    - DCS 1800
    """
    required_profile = SUPPORTED_INPUT_MODES[canonical_input_mode]
    candidates: list[dict[str, Any]] = []

    for block in FIXED_CHANNEL_BLOCKS:
        if block["profile"] != required_profile:
            continue

        if not (
            block["arfcn_min"]
            <= input_fcn
            <= block["arfcn_max"]
        ):
            continue

        dl_frequency_mhz = (
            block["dl_base_mhz"]
            + (
                input_fcn - block["arfcn_base"]
            )
            * CHANNEL_SPACING_MHZ
        )

        ul_frequency_mhz = (
            dl_frequency_mhz
            + block["ul_offset_from_dl_mhz"]
        )

        dl_frequency_mhz = _round_frequency(
            dl_frequency_mhz
        )
        ul_frequency_mhz = _round_frequency(
            ul_frequency_mhz
        )

        profile_key = _make_profile_key(
            required_profile
        )

        candidates.append(
            {
                "candidate_key": (
                    f"2G_GSM:{profile_key}:"
                    f"ARFCN:{input_fcn}"
                ),
                "technology": "2G GSM",
                "input_mode": canonical_input_mode,
                "fcn_type": "ARFCN",
                "requested_fcn": input_fcn,
                "band": block["display_code"],
                "band_name": required_profile,
                "duplex_mode": "FDD",
                "direction": "DL_UL",
                "mode": canonical_input_mode,
                "freq_dl_mhz": dl_frequency_mhz,
                "freq_ul_mhz": ul_frequency_mhz,
                "fcn_dl": input_fcn,
                "fcn_ul": input_fcn,
                "monitorable": _is_monitorable(
                    dl_frequency_mhz,
                    ul_frequency_mhz,
                ),
            }
        )

    return candidates


def _frequency_from_fcn(
    input_fcn: int,
    channel_range: tuple[int, int, float],
    spacing_mhz: float,
) -> float:
    """
    Menghitung frekuensi berdasarkan FCN pertama dan
    frekuensi pertama dalam suatu rentang.
    """
    fcn_low, _, frequency_low_mhz = channel_range

    frequency_mhz = (
        frequency_low_mhz
        + (input_fcn - fcn_low) * spacing_mhz
    )

    return _round_frequency(frequency_mhz)


def _is_fcn_in_range(
    input_fcn: int,
    channel_range: tuple[int, int, float] | None,
) -> bool:
    if channel_range is None:
        return False

    fcn_low, fcn_high, _ = channel_range

    return fcn_low <= input_fcn <= fcn_high


def _build_umts_fdd_candidate(
    *,
    canonical_input_mode: str,
    input_fcn: int,
    band: dict[str, Any],
    input_direction: str,
) -> dict[str, Any]:
    dl_range = band["dl"]
    ul_range = band["ul"]

    fcn_dl: int | None = None
    fcn_ul: int | None = None
    freq_dl_mhz: float | None = None
    freq_ul_mhz: float | None = None

    if input_direction == "DL":
        fcn_dl = input_fcn
        freq_dl_mhz = _frequency_from_fcn(
            input_fcn,
            dl_range,
            UMTS_FDD_CHANNEL_SPACING_MHZ,
        )

        if ul_range is not None:
            dl_fcn_low = dl_range[0]
            ul_fcn_low = ul_range[0]

            fcn_ul = (
                input_fcn
                + ul_fcn_low
                - dl_fcn_low
            )

            if _is_fcn_in_range(fcn_ul, ul_range):
                freq_ul_mhz = _frequency_from_fcn(
                    fcn_ul,
                    ul_range,
                    UMTS_FDD_CHANNEL_SPACING_MHZ,
                )
            else:
                fcn_ul = None

    elif input_direction == "UL":
        if ul_range is None:
            raise ValueError(
                "Band UMTS ini tidak memiliki uplink."
            )

        fcn_ul = input_fcn
        freq_ul_mhz = _frequency_from_fcn(
            input_fcn,
            ul_range,
            UMTS_FDD_CHANNEL_SPACING_MHZ,
        )

        dl_fcn_low = dl_range[0]
        ul_fcn_low = ul_range[0]

        fcn_dl = (
            input_fcn
            + dl_fcn_low
            - ul_fcn_low
        )

        if _is_fcn_in_range(fcn_dl, dl_range):
            freq_dl_mhz = _frequency_from_fcn(
                fcn_dl,
                dl_range,
                UMTS_FDD_CHANNEL_SPACING_MHZ,
            )
        else:
            fcn_dl = None

    else:
        raise ValueError(
            f"Direction UMTS tidak dikenal: {input_direction}"
        )

    band_code = f"B{band['band']}"

    return {
        "candidate_key": (
            f"3G_UMTS:FDD:{band_code}:"
            f"{input_direction}:UARFCN:{input_fcn}"
        ),
        "technology": "3G UMTS",
        "input_mode": canonical_input_mode,
        "fcn_type": "UARFCN",
        "requested_fcn": input_fcn,
        "band": band_code,
        "band_name": band["name"],
        "duplex_mode": "FDD",
        "direction": input_direction,
        "mode": "3G UMTS FDD",
        "freq_dl_mhz": freq_dl_mhz,
        "freq_ul_mhz": freq_ul_mhz,
        "fcn_dl": fcn_dl,
        "fcn_ul": fcn_ul,
        "monitorable": _is_monitorable(
            freq_dl_mhz,
            freq_ul_mhz,
        ),
    }


def _lookup_umts_fdd(
    canonical_input_mode: str,
    input_fcn: int,
) -> list[dict[str, Any]]:
    """
    Mencari UARFCN sebagai kemungkinan:

    - UARFCN downlink
    - UARFCN uplink

    Satu UARFCN dapat menghasilkan lebih dari satu kandidat.
    """
    candidates: list[dict[str, Any]] = []

    for band in UMTS_FDD_LOOKUP_BANDS:
        dl_range = band["dl"]
        ul_range = band["ul"]

        if _is_fcn_in_range(input_fcn, dl_range):
            candidates.append(
                _build_umts_fdd_candidate(
                    canonical_input_mode=canonical_input_mode,
                    input_fcn=input_fcn,
                    band=band,
                    input_direction="DL",
                )
            )

        if _is_fcn_in_range(input_fcn, ul_range):
            candidates.append(
                _build_umts_fdd_candidate(
                    canonical_input_mode=canonical_input_mode,
                    input_fcn=input_fcn,
                    band=band,
                    input_direction="UL",
                )
            )

    return candidates


def _lookup_umts_tdd(
    canonical_input_mode: str,
    input_fcn: int,
) -> list[dict[str, Any]]:
    """
    Mencari kandidat UMTS TDD 1.28 Mcps.

    Pada TDD, uplink dan downlink memakai satu frekuensi
    yang sama secara bergantian. Untuk penyimpanan Channel:
    - freq_dl_mhz menyimpan shared frequency
    - freq_ul_mhz = None
    - fcn_dl menyimpan shared UARFCN
    - fcn_ul = None
    """
    candidates: list[dict[str, Any]] = []

    for band in UMTS_TDD_LOOKUP_BANDS:
        if not (
            band["uarfcn_low"]
            <= input_fcn
            <= band["uarfcn_high"]
        ):
            continue

        shared_frequency_mhz = _round_frequency(
            input_fcn / 5.0
        )
        band_code = f"B{band['band']}"

        candidates.append(
            {
                "candidate_key": (
                    f"3G_UMTS:TDD:{band_code}:"
                    f"SHARED:UARFCN:{input_fcn}"
                ),
                "technology": "3G UMTS",
                "input_mode": canonical_input_mode,
                "fcn_type": "UARFCN",
                "requested_fcn": input_fcn,
                "band": band_code,
                "band_name": band["name"],
                "legacy_band_name": band["legacy_name"],
                "duplex_mode": "TDD",
                "direction": "SHARED",
                "mode": "3G UMTS TDD",
                "freq_dl_mhz": shared_frequency_mhz,
                "freq_ul_mhz": None,
                "fcn_dl": input_fcn,
                "fcn_ul": None,
                "monitorable": _is_monitorable(
                    shared_frequency_mhz
                ),
            }
        )

    return candidates


def _lookup_umts(
    canonical_input_mode: str,
    input_fcn: int,
) -> list[dict[str, Any]]:
    """Menggabungkan kandidat UMTS FDD dan TDD."""
    return [
        *_lookup_umts_fdd(
            canonical_input_mode,
            input_fcn,
        ),
        *_lookup_umts_tdd(
            canonical_input_mode,
            input_fcn,
        ),
    ]



def _lte_frequency_from_earfcn(
    input_earfcn: int,
    earfcn_low: int,
    frequency_low_mhz: float,
) -> float:
    """Hitung frekuensi pusat LTE dari EARFCN pertama suatu band."""
    return _round_frequency(
        frequency_low_mhz
        + (input_earfcn - earfcn_low)
        * LTE_CHANNEL_SPACING_MHZ
    )


def _lte_earfcn_in_range(
    input_earfcn: int,
    earfcn_low: int | None,
    earfcn_high: int | None,
) -> bool:
    if earfcn_low is None or earfcn_high is None:
        return False

    return earfcn_low <= input_earfcn <= earfcn_high


def _build_lte_fdd_candidate(
    *,
    canonical_input_mode: str,
    input_fcn: int,
    band: dict[str, Any],
    input_direction: str,
) -> dict[str, Any]:
    """Bangun kandidat LTE FDD dari EARFCN DL atau UL."""
    fcn_dl: int | None = None
    fcn_ul: int | None = None
    freq_dl_mhz: float | None = None
    freq_ul_mhz: float | None = None

    dl_earfcn_low = band["dl_earfcn_low"]
    dl_earfcn_high = band["dl_earfcn_high"]
    ul_earfcn_low = band["ul_earfcn_low"]
    ul_earfcn_high = band["ul_earfcn_high"]

    if input_direction == "DL":
        fcn_dl = input_fcn
        freq_dl_mhz = _lte_frequency_from_earfcn(
            input_fcn,
            dl_earfcn_low,
            band["dl_low_mhz"],
        )

        if ul_earfcn_low is not None:
            possible_fcn_ul = (
                input_fcn
                + ul_earfcn_low
                - dl_earfcn_low
            )

            # Beberapa band, seperti B66 dan B70, mempunyai
            # bagian downlink yang lebih lebar daripada uplink.
            # Pada bagian extension tersebut pasangan UL tetap None.
            if _lte_earfcn_in_range(
                possible_fcn_ul,
                ul_earfcn_low,
                ul_earfcn_high,
            ):
                fcn_ul = possible_fcn_ul
                freq_ul_mhz = _lte_frequency_from_earfcn(
                    fcn_ul,
                    ul_earfcn_low,
                    band["ul_low_mhz"],
                )

    elif input_direction == "UL":
        if ul_earfcn_low is None:
            raise ValueError(
                "Band LTE ini tidak memiliki uplink."
            )

        fcn_ul = input_fcn
        freq_ul_mhz = _lte_frequency_from_earfcn(
            input_fcn,
            ul_earfcn_low,
            band["ul_low_mhz"],
        )

        possible_fcn_dl = (
            input_fcn
            + dl_earfcn_low
            - ul_earfcn_low
        )

        if _lte_earfcn_in_range(
            possible_fcn_dl,
            dl_earfcn_low,
            dl_earfcn_high,
        ):
            fcn_dl = possible_fcn_dl
            freq_dl_mhz = _lte_frequency_from_earfcn(
                fcn_dl,
                dl_earfcn_low,
                band["dl_low_mhz"],
            )

    else:
        raise ValueError(
            f"Direction LTE FDD tidak dikenal: {input_direction}"
        )

    band_code = f"B{band['band']}"

    return {
        "candidate_key": (
            f"4G_LTE:FDD:{band_code}:"
            f"{input_direction}:EARFCN:{input_fcn}"
        ),
        "technology": "4G LTE",
        "input_mode": canonical_input_mode,
        "fcn_type": "EARFCN",
        "requested_fcn": input_fcn,
        "band": band_code,
        "band_name": band["name"],
        "duplex_mode": "FDD",
        "direction": input_direction,
        "mode": "4G LTE FDD",
        "freq_dl_mhz": freq_dl_mhz,
        "freq_ul_mhz": freq_ul_mhz,
        "fcn_dl": fcn_dl,
        "fcn_ul": fcn_ul,
        "monitorable": _is_monitorable(
            freq_dl_mhz,
            freq_ul_mhz,
        ),
    }


def _build_lte_downlink_only_candidate(
    *,
    canonical_input_mode: str,
    input_fcn: int,
    band: dict[str, Any],
    duplex_mode: str,
    direction: str,
) -> dict[str, Any]:
    """Bangun kandidat LTE TDD shared atau SDL downlink-only."""
    frequency_mhz = _lte_frequency_from_earfcn(
        input_fcn,
        band["dl_earfcn_low"],
        band["dl_low_mhz"],
    )
    band_code = f"B{band['band']}"

    return {
        "candidate_key": (
            f"4G_LTE:{duplex_mode}:{band_code}:"
            f"{direction}:EARFCN:{input_fcn}"
        ),
        "technology": "4G LTE",
        "input_mode": canonical_input_mode,
        "fcn_type": "EARFCN",
        "requested_fcn": input_fcn,
        "band": band_code,
        "band_name": band["name"],
        "duplex_mode": duplex_mode,
        "direction": direction,
        "mode": f"4G LTE {duplex_mode}",
        "freq_dl_mhz": frequency_mhz,
        "freq_ul_mhz": None,
        "fcn_dl": input_fcn,
        "fcn_ul": None,
        "monitorable": _is_monitorable(
            frequency_mhz
        ),
    }


def _lookup_lte(
    canonical_input_mode: str,
    input_fcn: int,
) -> list[dict[str, Any]]:
    """
    Cari EARFCN pada seluruh LTE band registry.

    - FDD diperiksa sebagai kemungkinan DL dan UL.
    - TDD disimpan sebagai shared frequency.
    - SDL disimpan sebagai downlink-only.
    - Semua band yang cocok dikembalikan sebagai kandidat.
    """
    candidates: list[dict[str, Any]] = []

    for band in LTE_BANDS:
        band_mode = band["mode"]

        if band_mode == "FDD":
            if _lte_earfcn_in_range(
                input_fcn,
                band["dl_earfcn_low"],
                band["dl_earfcn_high"],
            ):
                candidates.append(
                    _build_lte_fdd_candidate(
                        canonical_input_mode=canonical_input_mode,
                        input_fcn=input_fcn,
                        band=band,
                        input_direction="DL",
                    )
                )

            if _lte_earfcn_in_range(
                input_fcn,
                band["ul_earfcn_low"],
                band["ul_earfcn_high"],
            ):
                candidates.append(
                    _build_lte_fdd_candidate(
                        canonical_input_mode=canonical_input_mode,
                        input_fcn=input_fcn,
                        band=band,
                        input_direction="UL",
                    )
                )

        elif band_mode == "TDD":
            if _lte_earfcn_in_range(
                input_fcn,
                band["dl_earfcn_low"],
                band["dl_earfcn_high"],
            ):
                candidates.append(
                    _build_lte_downlink_only_candidate(
                        canonical_input_mode=canonical_input_mode,
                        input_fcn=input_fcn,
                        band=band,
                        duplex_mode="TDD",
                        direction="SHARED",
                    )
                )

        elif band_mode == "SDL":
            if _lte_earfcn_in_range(
                input_fcn,
                band["dl_earfcn_low"],
                band["dl_earfcn_high"],
            ):
                candidates.append(
                    _build_lte_downlink_only_candidate(
                        canonical_input_mode=canonical_input_mode,
                        input_fcn=input_fcn,
                        band=band,
                        duplex_mode="SDL",
                        direction="DL",
                    )
                )

    return candidates


# Band-specific NR channel raster configurations.
#
# Most FR1 bands use 100 kHz channel raster with Nref step size 20.
# Entries below override that default for bands with 15/30 kHz raster,
# multiple raster options, or NTN 10 kHz raster.
#
# Each tuple contains:
#     (raster_khz, nref_step_size)
NR_RASTER_OPTIONS: dict[str, list[tuple[int, int]]] = {
    "n41": [(15, 3), (30, 6)],
    "n46": [(15, 1)],
    "n47": [(15, 1)],
    "n48": [(15, 1), (30, 2)],
    "n77": [(15, 1), (30, 2)],
    "n78": [(15, 1), (30, 2)],
    "n79": [(15, 1), (30, 2)],
    "n90": [(15, 3), (30, 6), (100, 20)],
    "n96": [(15, 1)],
    "n102": [(15, 1)],
    "n104": [(15, 1), (30, 2)],
    "n247": [(15, 1), (30, 2)],
    "n248": [(15, 1), (30, 2)],
    "n250": [(100, 20), (10, 2)],
    "n251": [(100, 20), (10, 2)],
    "n252": [(100, 20), (10, 2)],
    "n253": [(100, 20), (10, 2)],
    "n254": [(100, 20), (10, 2)],
    "n255": [(100, 20), (10, 2)],
    "n256": [(100, 20), (10, 2)],
}


# Exact Nref boundaries are needed where a band edge is not aligned with
# the global 15 kHz NR-ARFCN grid, or where each raster option has a
# different first/last valid Nref.
#
# Format:
#   band -> direction -> list of
#   (raster_khz, step, first_valid_nref, last_valid_nref)
NR_EXACT_RASTER_RANGES: dict[
    str,
    dict[str, list[tuple[int, int, int, int]]],
] = {
    "n41": {
        "DL": [
            (15, 3, 499200, 537999),
            (30, 6, 499200, 537996),
        ],
    },
    "n46": {
        "DL": [(15, 1, 743334, 795000)],
    },
    "n47": {
        "DL": [(15, 1, 790334, 795000)],
    },
    "n48": {
        "DL": [
            (15, 1, 636667, 646666),
            (30, 2, 636668, 646666),
        ],
    },
    "n77": {
        "DL": [
            (15, 1, 620000, 680000),
            (30, 2, 620000, 680000),
        ],
    },
    "n78": {
        "DL": [
            (15, 1, 620000, 653333),
            (30, 2, 620000, 653332),
        ],
    },
    "n79": {
        "DL": [
            (15, 1, 693334, 733333),
            (30, 2, 693334, 733332),
        ],
    },
    "n90": {
        "DL": [
            (15, 3, 499200, 537999),
            (30, 6, 499200, 537996),
            (100, 20, 499200, 538000),
        ],
    },
    "n96": {
        "DL": [(15, 1, 795000, 875000)],
    },
    "n102": {
        "DL": [(15, 1, 795000, 828333)],
    },
    "n104": {
        "DL": [
            (15, 1, 828334, 875000),
            (30, 2, 828334, 875000),
        ],
    },
    "n247": {
        "DL": [
            (15, 1, 1113334, 1250000),
            (30, 2, 1113334, 1250000),
        ],
        "UL": [
            (15, 1, 1316667, 1333333),
            (30, 2, 1316668, 1333332),
        ],
    },
    "n248": {
        "DL": [
            (15, 1, 1113334, 1250000),
            (30, 2, 1113334, 1250000),
        ],
        "UL": [
            (15, 1, 1333334, 1366666),
            (30, 2, 1333334, 1366666),
        ],
    },
}


def _nr_frequency_from_arfcn(input_fcn: int) -> float | None:
    """Convert global NR-ARFCN to frequency in MHz for FR1 ranges."""
    if 0 <= input_fcn < 600000:
        return _round_frequency(input_fcn * 0.005)

    if 600000 <= input_fcn <= 2016666:
        return _round_frequency(
            3000.0 + (input_fcn - 600000) * 0.015
        )

    return None


def _nr_arfcn_from_frequency(frequency_mhz: float) -> int | None:
    """Convert frequency in MHz to the nearest global NR-ARFCN."""
    if frequency_mhz < 0:
        return None

    if frequency_mhz < 3000.0:
        return int(round(frequency_mhz / 0.005))

    if frequency_mhz <= 24250.08:
        return int(
            round(
                600000
                + (frequency_mhz - 3000.0) / 0.015
            )
        )

    return None


def _nr_frequency_in_direction_range(
    band: dict[str, Any],
    frequency_mhz: float,
    direction: str,
) -> bool:
    prefix = "ul" if direction == "UL" else "dl"
    low = band.get(f"{prefix}_low_mhz")
    high = band.get(f"{prefix}_high_mhz")

    if low is None or high is None:
        return False

    tolerance_mhz = 0.000001
    return (
        float(low) - tolerance_mhz
        <= frequency_mhz
        <= float(high) + tolerance_mhz
    )


def _nr_default_raster_ranges(
    band: dict[str, Any],
    direction: str,
) -> list[tuple[int, int, int, int]]:
    """Build channel raster ranges for bands without exact overrides."""
    prefix = "ul" if direction == "UL" else "dl"
    low_frequency = band.get(f"{prefix}_low_mhz")
    high_frequency = band.get(f"{prefix}_high_mhz")

    if low_frequency is None or high_frequency is None:
        return []

    first_nref = _nr_arfcn_from_frequency(
        float(low_frequency)
    )
    last_nref = _nr_arfcn_from_frequency(
        float(high_frequency)
    )

    if first_nref is None or last_nref is None:
        return []

    options = NR_RASTER_OPTIONS.get(
        band["band"],
        [(100, 20)],
    )

    ranges: list[tuple[int, int, int, int]] = []

    for raster_khz, step in options:
        # Keep only the final Nref belonging to the sequence that begins at
        # the band's first valid Nref.
        aligned_last = (
            first_nref
            + ((last_nref - first_nref) // step) * step
        )
        ranges.append(
            (
                raster_khz,
                step,
                first_nref,
                aligned_last,
            )
        )

    return ranges


def _nr_matching_raster_options(
    band: dict[str, Any],
    direction: str,
    input_fcn: int,
) -> list[dict[str, int]]:
    exact_by_direction = NR_EXACT_RASTER_RANGES.get(
        band["band"],
        {},
    )
    raster_ranges = exact_by_direction.get(direction)

    if raster_ranges is None:
        raster_ranges = _nr_default_raster_ranges(
            band,
            direction,
        )

    matching_options: list[dict[str, int]] = []

    for (
        raster_khz,
        step,
        first_nref,
        last_nref,
    ) in raster_ranges:
        if not first_nref <= input_fcn <= last_nref:
            continue

        if (input_fcn - first_nref) % step != 0:
            continue

        matching_options.append(
            {
                "raster_khz": raster_khz,
                "nref_step_size": step,
            }
        )

    return matching_options


def _nr_pair_from_frequency(
    *,
    band: dict[str, Any],
    source_frequency_mhz: float,
    source_direction: str,
) -> tuple[int | None, float | None]:
    duplex_spacing = band.get("duplex_spacing_mhz")

    if duplex_spacing is None:
        return None, None

    if source_direction == "DL":
        paired_direction = "UL"
        paired_frequency = (
            source_frequency_mhz
            - float(duplex_spacing)
        )
    elif source_direction == "UL":
        paired_direction = "DL"
        paired_frequency = (
            source_frequency_mhz
            + float(duplex_spacing)
        )
    else:
        raise ValueError(
            f"Direction NR FDD tidak dikenal: {source_direction}"
        )

    paired_frequency = _round_frequency(
        paired_frequency
    )

    if not _nr_frequency_in_direction_range(
        band,
        paired_frequency,
        paired_direction,
    ):
        return None, None

    paired_fcn = _nr_arfcn_from_frequency(
        paired_frequency
    )

    if paired_fcn is None:
        return None, None

    if not _nr_matching_raster_options(
        band,
        paired_direction,
        paired_fcn,
    ):
        return None, None

    return paired_fcn, paired_frequency


def _build_nr_fdd_candidate(
    *,
    canonical_input_mode: str,
    input_fcn: int,
    input_frequency_mhz: float,
    band: dict[str, Any],
    input_direction: str,
    raster_options: list[dict[str, int]],
) -> dict[str, Any]:
    fcn_dl: int | None = None
    fcn_ul: int | None = None
    freq_dl_mhz: float | None = None
    freq_ul_mhz: float | None = None

    if input_direction == "DL":
        fcn_dl = input_fcn
        freq_dl_mhz = input_frequency_mhz
        fcn_ul, freq_ul_mhz = _nr_pair_from_frequency(
            band=band,
            source_frequency_mhz=input_frequency_mhz,
            source_direction="DL",
        )
    elif input_direction == "UL":
        fcn_ul = input_fcn
        freq_ul_mhz = input_frequency_mhz
        fcn_dl, freq_dl_mhz = _nr_pair_from_frequency(
            band=band,
            source_frequency_mhz=input_frequency_mhz,
            source_direction="UL",
        )
    else:
        raise ValueError(
            f"Direction NR FDD tidak dikenal: {input_direction}"
        )

    return {
        "candidate_key": (
            f"5G_NR:FDD:{band['band']}:"
            f"{input_direction}:NR_ARFCN:{input_fcn}"
        ),
        "technology": "5G NR",
        "input_mode": canonical_input_mode,
        "fcn_type": "NR-ARFCN",
        "requested_fcn": input_fcn,
        "band": band["band"],
        "band_name": band["name"],
        "duplex_mode": "FDD",
        "direction": input_direction,
        "mode": "5G NR FDD",
        "freq_dl_mhz": freq_dl_mhz,
        "freq_ul_mhz": freq_ul_mhz,
        "fcn_dl": fcn_dl,
        "fcn_ul": fcn_ul,
        "raster_options": raster_options,
        "monitorable": _is_monitorable(
            freq_dl_mhz,
            freq_ul_mhz,
        ),
    }


def _build_nr_single_side_candidate(
    *,
    canonical_input_mode: str,
    input_fcn: int,
    input_frequency_mhz: float,
    band: dict[str, Any],
    duplex_mode: str,
    direction: str,
    raster_options: list[dict[str, int]],
) -> dict[str, Any]:
    if duplex_mode in {"TDD", "SDL"}:
        freq_dl_mhz = input_frequency_mhz
        freq_ul_mhz = None
        fcn_dl = input_fcn
        fcn_ul = None
    elif duplex_mode == "SUL":
        freq_dl_mhz = None
        freq_ul_mhz = input_frequency_mhz
        fcn_dl = None
        fcn_ul = input_fcn
    else:
        raise ValueError(
            f"Mode NR satu sisi tidak dikenal: {duplex_mode}"
        )

    return {
        "candidate_key": (
            f"5G_NR:{duplex_mode}:{band['band']}:"
            f"{direction}:NR_ARFCN:{input_fcn}"
        ),
        "technology": "5G NR",
        "input_mode": canonical_input_mode,
        "fcn_type": "NR-ARFCN",
        "requested_fcn": input_fcn,
        "band": band["band"],
        "band_name": band["name"],
        "duplex_mode": duplex_mode,
        "direction": direction,
        "mode": f"5G NR {duplex_mode}",
        "freq_dl_mhz": freq_dl_mhz,
        "freq_ul_mhz": freq_ul_mhz,
        "fcn_dl": fcn_dl,
        "fcn_ul": fcn_ul,
        "raster_options": raster_options,
        "monitorable": _is_monitorable(
            freq_dl_mhz,
            freq_ul_mhz,
        ),
    }


def _lookup_nr(
    canonical_input_mode: str,
    input_fcn: int,
) -> list[dict[str, Any]]:
    """
    Cari NR-ARFCN pada seluruh registry 5G NR FR1.

    - FDD diperiksa sebagai kemungkinan DL dan UL.
    - TDD disimpan sebagai shared frequency.
    - SDL disimpan sebagai downlink-only.
    - SUL disimpan sebagai uplink-only.
    - Nref wajib cocok dengan channel raster/step size band.
    - Semua band yang cocok dikembalikan sebagai kandidat.
    """
    input_frequency_mhz = _nr_frequency_from_arfcn(
        input_fcn
    )

    if input_frequency_mhz is None:
        return []

    candidates: list[dict[str, Any]] = []

    for band in NR_FR1_BANDS:
        band_mode = band["mode"]

        if band_mode == "FDD":
            if _nr_frequency_in_direction_range(
                band,
                input_frequency_mhz,
                "DL",
            ):
                raster_options = _nr_matching_raster_options(
                    band,
                    "DL",
                    input_fcn,
                )

                if raster_options:
                    candidates.append(
                        _build_nr_fdd_candidate(
                            canonical_input_mode=canonical_input_mode,
                            input_fcn=input_fcn,
                            input_frequency_mhz=input_frequency_mhz,
                            band=band,
                            input_direction="DL",
                            raster_options=raster_options,
                        )
                    )

            if _nr_frequency_in_direction_range(
                band,
                input_frequency_mhz,
                "UL",
            ):
                raster_options = _nr_matching_raster_options(
                    band,
                    "UL",
                    input_fcn,
                )

                if raster_options:
                    candidates.append(
                        _build_nr_fdd_candidate(
                            canonical_input_mode=canonical_input_mode,
                            input_fcn=input_fcn,
                            input_frequency_mhz=input_frequency_mhz,
                            band=band,
                            input_direction="UL",
                            raster_options=raster_options,
                        )
                    )

        elif band_mode == "TDD":
            if not _nr_frequency_in_direction_range(
                band,
                input_frequency_mhz,
                "DL",
            ):
                continue

            raster_options = _nr_matching_raster_options(
                band,
                "DL",
                input_fcn,
            )

            if raster_options:
                candidates.append(
                    _build_nr_single_side_candidate(
                        canonical_input_mode=canonical_input_mode,
                        input_fcn=input_fcn,
                        input_frequency_mhz=input_frequency_mhz,
                        band=band,
                        duplex_mode="TDD",
                        direction="SHARED",
                        raster_options=raster_options,
                    )
                )

        elif band_mode == "SDL":
            if not _nr_frequency_in_direction_range(
                band,
                input_frequency_mhz,
                "DL",
            ):
                continue

            raster_options = _nr_matching_raster_options(
                band,
                "DL",
                input_fcn,
            )

            if raster_options:
                candidates.append(
                    _build_nr_single_side_candidate(
                        canonical_input_mode=canonical_input_mode,
                        input_fcn=input_fcn,
                        input_frequency_mhz=input_frequency_mhz,
                        band=band,
                        duplex_mode="SDL",
                        direction="DL",
                        raster_options=raster_options,
                    )
                )

        elif band_mode == "SUL":
            if not _nr_frequency_in_direction_range(
                band,
                input_frequency_mhz,
                "UL",
            ):
                continue

            raster_options = _nr_matching_raster_options(
                band,
                "UL",
                input_fcn,
            )

            if raster_options:
                candidates.append(
                    _build_nr_single_side_candidate(
                        canonical_input_mode=canonical_input_mode,
                        input_fcn=input_fcn,
                        input_frequency_mhz=input_frequency_mhz,
                        band=band,
                        duplex_mode="SUL",
                        direction="UL",
                        raster_options=raster_options,
                    )
                )

    return candidates

def lookup_channel_candidates(
    input_mode: str,
    input_fcn: int,
) -> list[dict[str, Any]]:
    """
    Entry point Channel Lookup.

    Input user:
    - Technology/Profile
    - FCN

    Output:
    - List kandidat channel
    """
    canonical_input_mode = _normalize_input_mode(
        input_mode
    )
    validated_fcn = _validate_fcn(input_fcn)

    if canonical_input_mode in {
        "2G E-GSM 900",
        "2G DCS 1800",
    }:
        return _lookup_gsm(
            canonical_input_mode,
            validated_fcn,
        )

    if canonical_input_mode == "3G UMTS":
        return _lookup_umts(
            canonical_input_mode,
            validated_fcn,
        )

    if canonical_input_mode == "4G LTE":
        return _lookup_lte(
            canonical_input_mode,
            validated_fcn,
        )

    if canonical_input_mode == "5G NR":
        return _lookup_nr(
            canonical_input_mode,
            validated_fcn,
        )

    raise ValueError(
        f"Mode belum memiliki lookup: {canonical_input_mode}"
    )
