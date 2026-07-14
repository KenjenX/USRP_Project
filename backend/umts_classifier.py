from __future__ import annotations

from math import floor
from typing import Any


UMTS_CHANNEL_SPACING_MHZ = 0.2
MAX_CHANNEL_OFFSET_MHZ = 0.1


# Data awal diambil dari tabel UTRA frequency band FDD.
# Fokus versi pertama:
# - Downlink only untuk pencocokan sinyal yang diterima USRP.
# - FDD only.
# - Hasil adalah kandidat berdasarkan frekuensi, bukan bukti sinyal UMTS.
#
# uarfcn_ref dipakai untuk menghitung UARFCN dengan jarak kanal 0.2 MHz:
# UARFCN = reference_uarfcn + round((frequency - reference_frequency) / 0.2)
UMTS_FDD_BANDS = [
    {
        "band": "1",
        "name": "2100",
        "mode": "FDD",
        "dl_low_mhz": 2110.0,
        "dl_high_mhz": 2170.0,
        "ul_low_mhz": 1920.0,
        "ul_high_mhz": 1980.0,
        "dl_ref_mhz": 2140.0,
        "dl_uarfcn_ref": 10700,
        "ul_ref_mhz": 1950.0,
        "ul_uarfcn_ref": 9750,
        "equivalent_gsm_band": None,
    },
    {
        "band": "2",
        "name": "1900 PCS",
        "mode": "FDD",
        "dl_low_mhz": 1930.0,
        "dl_high_mhz": 1990.0,
        "ul_low_mhz": 1850.0,
        "ul_high_mhz": 1910.0,
        "dl_ref_mhz": 1960.0,
        "dl_uarfcn_ref": 9800,
        "ul_ref_mhz": 1880.0,
        "ul_uarfcn_ref": 9400,
        "equivalent_gsm_band": "PCS 1900",
    },
    {
        "band": "3",
        "name": "1800 DCS",
        "mode": "FDD",
        "dl_low_mhz": 1805.0,
        "dl_high_mhz": 1880.0,
        "ul_low_mhz": 1710.0,
        "ul_high_mhz": 1785.0,
        "dl_ref_mhz": 1842.5,
        "dl_uarfcn_ref": 1338,
        "ul_ref_mhz": 1747.5,
        "ul_uarfcn_ref": 1113,
        "equivalent_gsm_band": "DCS 1800",
    },
    {
        "band": "4",
        "name": "AWS-1",
        "mode": "FDD",
        "dl_low_mhz": 2110.0,
        "dl_high_mhz": 2155.0,
        "ul_low_mhz": 1710.0,
        "ul_high_mhz": 1755.0,
        "dl_ref_mhz": 2132.5,
        "dl_uarfcn_ref": 1688,
        "ul_ref_mhz": 1732.5,
        "ul_uarfcn_ref": 1413,
        "equivalent_gsm_band": None,
    },
    {
        "band": "5",
        "name": "850",
        "mode": "FDD",
        "dl_low_mhz": 869.0,
        "dl_high_mhz": 894.0,
        "ul_low_mhz": 824.0,
        "ul_high_mhz": 849.0,
        "dl_ref_mhz": 881.5,
        "dl_uarfcn_ref": 4408,
        "ul_ref_mhz": 836.5,
        "ul_uarfcn_ref": 4183,
        "equivalent_gsm_band": "GSM 850",
    },
    {
        "band": "6",
        "name": "850 Japan",
        "mode": "FDD",
        "dl_low_mhz": 875.0,
        "dl_high_mhz": 885.0,
        "ul_low_mhz": 830.0,
        "ul_high_mhz": 840.0,
        "dl_ref_mhz": 880.0,
        "dl_uarfcn_ref": 4400,
        "ul_ref_mhz": 835.0,
        "ul_uarfcn_ref": 4175,
        "equivalent_gsm_band": None,
    },
    {
        "band": "7",
        "name": "2600",
        "mode": "FDD",
        "dl_low_mhz": 2620.0,
        "dl_high_mhz": 2690.0,
        "ul_low_mhz": 2500.0,
        "ul_high_mhz": 2570.0,
        "dl_ref_mhz": 2655.0,
        "dl_uarfcn_ref": 2400,
        "ul_ref_mhz": 2535.0,
        "ul_uarfcn_ref": 2175,
        "equivalent_gsm_band": None,
    },
    {
        "band": "8",
        "name": "900 GSM",
        "mode": "FDD",
        "dl_low_mhz": 925.0,
        "dl_high_mhz": 960.0,
        "ul_low_mhz": 880.0,
        "ul_high_mhz": 915.0,
        "dl_ref_mhz": 942.5,
        "dl_uarfcn_ref": 3013,
        "ul_ref_mhz": 897.5,
        "ul_uarfcn_ref": 2788,
        "equivalent_gsm_band": "E-GSM 900",
    },
    {
        "band": "9",
        "name": "1800 Japan",
        "mode": "FDD",
        "dl_low_mhz": 1845.0,
        "dl_high_mhz": 1879.8,
        "ul_low_mhz": 1750.0,
        "ul_high_mhz": 1784.8,
        "dl_ref_mhz": 1862.4,
        "dl_uarfcn_ref": 9312,
        "ul_ref_mhz": 1767.4,
        "ul_uarfcn_ref": 8837,
        "equivalent_gsm_band": None,
    },
    {
        "band": "10",
        "name": "AWS-1+",
        "mode": "FDD",
        "dl_low_mhz": 2110.0,
        "dl_high_mhz": 2170.0,
        "ul_low_mhz": 1710.0,
        "ul_high_mhz": 1770.0,
        "dl_ref_mhz": 2140.0,
        "dl_uarfcn_ref": 3250,
        "ul_ref_mhz": 1740.0,
        "ul_uarfcn_ref": 3025,
        "equivalent_gsm_band": None,
    },
    {
        "band": "11",
        "name": "1500 Lower",
        "mode": "FDD",
        "dl_low_mhz": 1475.9,
        "dl_high_mhz": 1495.9,
        "ul_low_mhz": 1428.0,
        "ul_high_mhz": 1447.9,
        "dl_ref_mhz": 1486.0,
        "dl_uarfcn_ref": 3750,
        "ul_ref_mhz": 1438.0,
        "ul_uarfcn_ref": 3525,
        "equivalent_gsm_band": None,
    },
    {
        "band": "12",
        "name": "700 a",
        "mode": "FDD",
        "dl_low_mhz": 729.0,
        "dl_high_mhz": 746.0,
        "ul_low_mhz": 699.0,
        "ul_high_mhz": 716.0,
        "dl_ref_mhz": 737.5,
        "dl_uarfcn_ref": 3873,
        "ul_ref_mhz": 707.5,
        "ul_uarfcn_ref": 3648,
        "equivalent_gsm_band": None,
    },
    {
        "band": "13",
        "name": "700 c",
        "mode": "FDD",
        "dl_low_mhz": 746.0,
        "dl_high_mhz": 756.0,
        "ul_low_mhz": 777.0,
        "ul_high_mhz": 787.0,
        "dl_ref_mhz": 751.0,
        "dl_uarfcn_ref": 4030,
        "ul_ref_mhz": 782.0,
        "ul_uarfcn_ref": 3905,
        "equivalent_gsm_band": None,
    },
    {
        "band": "14",
        "name": "700 PS",
        "mode": "FDD",
        "dl_low_mhz": 758.0,
        "dl_high_mhz": 768.0,
        "ul_low_mhz": 788.0,
        "ul_high_mhz": 798.0,
        "dl_ref_mhz": 763.0,
        "dl_uarfcn_ref": 4130,
        "ul_ref_mhz": 793.0,
        "ul_uarfcn_ref": 3905,
        "equivalent_gsm_band": None,
    },
    {
        "band": "19",
        "name": "800 Japan",
        "mode": "FDD",
        "dl_low_mhz": 875.0,
        "dl_high_mhz": 890.0,
        "ul_low_mhz": 830.0,
        "ul_high_mhz": 845.0,
        "dl_ref_mhz": 882.5,
        "dl_uarfcn_ref": 738,
        "ul_ref_mhz": 837.5,
        "ul_uarfcn_ref": 338,
        "equivalent_gsm_band": None,
    },
    {
        "band": "20",
        "name": "800 DD",
        "mode": "FDD",
        "dl_low_mhz": 791.0,
        "dl_high_mhz": 821.0,
        "ul_low_mhz": 832.0,
        "ul_high_mhz": 862.0,
        "dl_ref_mhz": 806.0,
        "dl_uarfcn_ref": 4575,
        "ul_ref_mhz": 847.0,
        "ul_uarfcn_ref": 4350,
        "equivalent_gsm_band": None,
    },
    {
        "band": "21",
        "name": "1500 Upper",
        "mode": "FDD",
        "dl_low_mhz": 1495.9,
        "dl_high_mhz": 1510.9,
        "ul_low_mhz": 1448.0,
        "ul_high_mhz": 1462.8,
        "dl_ref_mhz": 1503.4,
        "dl_uarfcn_ref": 887,
        "ul_ref_mhz": 1455.4,
        "ul_uarfcn_ref": 487,
        "equivalent_gsm_band": None,
    },
    {
        "band": "22",
        "name": "3500",
        "mode": "FDD",
        "dl_low_mhz": 3510.0,
        "dl_high_mhz": 3590.0,
        "ul_low_mhz": 3410.0,
        "ul_high_mhz": 3490.0,
        "dl_ref_mhz": 3550.0,
        "dl_uarfcn_ref": 4850,
        "ul_ref_mhz": 3450.0,
        "ul_uarfcn_ref": 4625,
        "equivalent_gsm_band": None,
    },
    {
        "band": "25",
        "name": "1900+",
        "mode": "FDD",
        "dl_low_mhz": 1930.0,
        "dl_high_mhz": 1995.0,
        "ul_low_mhz": 1850.0,
        "ul_high_mhz": 1915.0,
        "dl_ref_mhz": 1962.5,
        "dl_uarfcn_ref": 5263,
        "ul_ref_mhz": 1882.5,
        "ul_uarfcn_ref": 5038,
        "equivalent_gsm_band": None,
    },
    {
        "band": "26",
        "name": "850+",
        "mode": "FDD",
        "dl_low_mhz": 859.0,
        "dl_high_mhz": 894.0,
        "ul_low_mhz": 814.0,
        "ul_high_mhz": 849.0,
        "dl_ref_mhz": 876.5,
        "dl_uarfcn_ref": 5838,
        "ul_ref_mhz": 831.5,
        "ul_uarfcn_ref": 5613,
        "equivalent_gsm_band": None,
    },
    {
        "band": "32",
        "name": "1500 L-band",
        "mode": "FDD",
        "dl_low_mhz": 1452.0,
        "dl_high_mhz": 1496.0,
        "ul_low_mhz": None,
        "ul_high_mhz": None,
        "dl_ref_mhz": 1474.0,
        "dl_uarfcn_ref": 6715,
        "ul_ref_mhz": None,
        "ul_uarfcn_ref": None,
        "equivalent_gsm_band": None,
    },
]


def _nearest_integer(value: float) -> int:
    """Membulatkan ke channel frekuensi terdekat."""

    return floor(value + 0.5)


def _calculate_uarfcn(
    *,
    frequency_mhz: float,
    reference_frequency_mhz: float | None,
    reference_uarfcn: int | None,
) -> int | None:
    if reference_frequency_mhz is None or reference_uarfcn is None:
        return None

    return int(
        reference_uarfcn
        + _nearest_integer(
            (frequency_mhz - reference_frequency_mhz)
            / UMTS_CHANNEL_SPACING_MHZ
        )
    )


def _round_or_none(value: float | None) -> float | None:
    if value is None:
        return None

    return round(value, 6)


def _build_result(
    *,
    raw_dl_mhz: float,
    band: dict[str, Any],
) -> dict[str, Any]:
    uarfcn_dl = _calculate_uarfcn(
        frequency_mhz=raw_dl_mhz,
        reference_frequency_mhz=band["dl_ref_mhz"],
        reference_uarfcn=band["dl_uarfcn_ref"],
    )

    uplink_offset_from_dl_mhz = None
    freq_ul_mhz = None
    uarfcn_ul = None

    if (
        band["ul_ref_mhz"] is not None
        and band["ul_uarfcn_ref"] is not None
    ):
        uplink_offset_from_dl_mhz = (
            band["ul_ref_mhz"] - band["dl_ref_mhz"]
        )
        freq_ul_mhz = raw_dl_mhz + uplink_offset_from_dl_mhz

        uarfcn_ul = _calculate_uarfcn(
            frequency_mhz=freq_ul_mhz,
            reference_frequency_mhz=band["ul_ref_mhz"],
            reference_uarfcn=band["ul_uarfcn_ref"],
        )

    return {
        "mode": "3G UMTS",
        "technology": "UMTS",
        "generation": "3G",
        # Nama utama dibuat mengikuti nama asli dari tabel Sqimway,
        # contoh: "900 GSM", "2100", "2600".
        "band": band["name"],
        "band_number": band["band"],
        "band_code": f"B{band['band']}",
        "standard_band": f"UMTS Band {band['band']}",
        "name": band["name"],
        "duplex_mode": band["mode"],
        "direction": "Downlink",
        "detected_freq_dl_mhz": round(raw_dl_mhz, 6),
        "freq_dl_mhz": round(raw_dl_mhz, 6),
        "freq_ul_mhz": _round_or_none(freq_ul_mhz),
        "uarfcn_dl": uarfcn_dl,
        "uarfcn_ul": uarfcn_ul,
        "fcn": uarfcn_dl,
        "fcn_ul": uarfcn_ul,
        "dl_low_mhz": band["dl_low_mhz"],
        "dl_high_mhz": band["dl_high_mhz"],
        "ul_low_mhz": band["ul_low_mhz"],
        "ul_high_mhz": band["ul_high_mhz"],
        "duplex_spacing_mhz": (
            abs(uplink_offset_from_dl_mhz)
            if uplink_offset_from_dl_mhz is not None
            else None
        ),
        "uplink_offset_from_dl_mhz": uplink_offset_from_dl_mhz,
        "channel_spacing_mhz": UMTS_CHANNEL_SPACING_MHZ,
        "channel_offset_khz": 0.0,
        "equivalent_gsm_band": band["equivalent_gsm_band"],
        "classification_note": (
            "Frequency-based UMTS FDD downlink candidate"
        ),
    }


def classify_umts(
    freq_dl_mhz: float,
) -> list[dict[str, Any]]:
    """
    Mencocokkan satu peak frekuensi downlink dengan band UMTS FDD.

    Catatan:
    - Versi awal hanya UMTS FDD.
    - Mode saat ini hanya Downlink, BTS -> perangkat.
    - Hasil adalah kandidat berdasarkan lokasi frekuensi.
    - Hasil belum membuktikan sinyal tersebut benar-benar UMTS/3G.
    - Fungsi mengembalikan list karena satu frekuensi dapat overlap
      dengan beberapa band UMTS.
    """

    try:
        frequency = float(freq_dl_mhz)
    except (TypeError, ValueError):
        return []

    if frequency <= 0:
        return []

    matches = []

    for band in UMTS_FDD_BANDS:
        if band["dl_low_mhz"] <= frequency <= band["dl_high_mhz"]:
            matches.append(
                _build_result(
                    raw_dl_mhz=frequency,
                    band=band,
                )
            )

    return matches
