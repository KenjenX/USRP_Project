"""
Registry data band GSM.

File ini hanya menyimpan data band.
Perhitungan dan pencocokan frekuensi tetap berada di gsm_classifier.py.

Mode awal sistem:
- Downlink only
- BTS -> perangkat
"""

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