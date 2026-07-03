from typing import Optional


CHANNEL_SPACING_MHZ = 0.2
MAX_CHANNEL_OFFSET_MHZ = 0.1


def _nearest_integer(value: float) -> int:
    """Membulatkan ke channel terdekat."""
    return int(value + 0.5)


def _build_result(
    *,
    raw_dl_mhz: float,
    band: str,
    band_code: str,
    arfcn: int,
    channel_dl_mhz: float,
    duplex_spacing_mhz: float,
) -> dict:
    channel_ul_mhz = channel_dl_mhz - duplex_spacing_mhz

    return {
        "mode": "2G GSM",
        "band": band,
        "band_code": band_code,
        "arfcn": arfcn,
        "fcn": arfcn,
        "fcn_ul": arfcn,
        "detected_freq_dl_mhz": round(raw_dl_mhz, 6),
        "freq_dl_mhz": round(channel_dl_mhz, 6),
        "freq_ul_mhz": round(channel_ul_mhz, 6),
        "duplex_spacing_mhz": duplex_spacing_mhz,
        "channel_offset_khz": round(
            (raw_dl_mhz - channel_dl_mhz) * 1000,
            3,
        ),
        "classification_note": "Frequency-based GSM candidate",
    }


def _classify_gsm_900(freq_dl_mhz: float) -> Optional[dict]:
    """
    Label disederhanakan menjadi GSM 900.

    Mencakup:
    - ARFCN 0–124   : DL 935.0–959.8 MHz
    - ARFCN 975–1023: DL 925.2–934.8 MHz
    """

    # Bagian utama GSM 900 / E-GSM 900.
    arfcn = _nearest_integer(
        (freq_dl_mhz - 935.0) / CHANNEL_SPACING_MHZ
    )

    if 0 <= arfcn <= 124:
        channel_dl_mhz = 935.0 + (
            arfcn * CHANNEL_SPACING_MHZ
        )

        if abs(freq_dl_mhz - channel_dl_mhz) <= MAX_CHANNEL_OFFSET_MHZ:
            return _build_result(
                raw_dl_mhz=freq_dl_mhz,
                band="GSM 900",
                band_code="B8",
                arfcn=arfcn,
                channel_dl_mhz=channel_dl_mhz,
                duplex_spacing_mhz=45.0,
            )

    # Bagian tambahan E-GSM 900.
    arfcn = _nearest_integer(
        1024 + ((freq_dl_mhz - 935.0) / CHANNEL_SPACING_MHZ)
    )

    if 975 <= arfcn <= 1023:
        channel_dl_mhz = 935.0 + (
            (arfcn - 1024) * CHANNEL_SPACING_MHZ
        )

        if abs(freq_dl_mhz - channel_dl_mhz) <= MAX_CHANNEL_OFFSET_MHZ:
            return _build_result(
                raw_dl_mhz=freq_dl_mhz,
                band="GSM 900",
                band_code="B8",
                arfcn=arfcn,
                channel_dl_mhz=channel_dl_mhz,
                duplex_spacing_mhz=45.0,
            )

    return None


def _classify_gsm_1800(freq_dl_mhz: float) -> Optional[dict]:
    """
    DCS 1800 / GSM 1800:
    ARFCN 512–885
    DL 1805.2–1879.8 MHz
    UL 1710.2–1784.8 MHz
    """

    arfcn = _nearest_integer(
        512 + ((freq_dl_mhz - 1805.2) / CHANNEL_SPACING_MHZ)
    )

    if not 512 <= arfcn <= 885:
        return None

    channel_dl_mhz = 1805.2 + (
        (arfcn - 512) * CHANNEL_SPACING_MHZ
    )

    if abs(freq_dl_mhz - channel_dl_mhz) > MAX_CHANNEL_OFFSET_MHZ:
        return None

    return _build_result(
        raw_dl_mhz=freq_dl_mhz,
        band="GSM 1800",
        band_code="B3",
        arfcn=arfcn,
        channel_dl_mhz=channel_dl_mhz,
        duplex_spacing_mhz=95.0,
    )


def classify_gsm(freq_dl_mhz: float) -> Optional[dict]:
    """
    Mencocokkan frekuensi downlink terhadap band GSM 900 atau GSM 1800.

    Catatan:
    Hasil ini hanya klasifikasi berdasarkan lokasi frekuensi.
    Ini belum membuktikan sinyal tersebut benar-benar GSM.
    """

    try:
        frequency = float(freq_dl_mhz)
    except (TypeError, ValueError):
        return None

    if frequency <= 0:
        return None

    result = _classify_gsm_900(frequency)

    if result is not None:
        return result

    return _classify_gsm_1800(frequency)