
from datetime import datetime
from threading import Lock
from copy import deepcopy
from math import ceil

import numpy as np
import uhd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend.gsm_classifier import classify_gsm
from backend.umts_classifier import classify_umts
from backend.lte_classifier import classify_lte
from backend.nr_classifier import classify_nr


# =========================
# KONFIGURASI USRP
# =========================
USRP_SERIAL = "000000929"
CHANNEL = 0
RX_ANTENNA = "RX2"
GAIN_DB = 35

# Jumlah sample FFT per window sweep.
# Semakin besar nilainya, resolusi frekuensi semakin detail,
# tetapi proses scan juga semakin berat.
NUM_SAMPS = 1024
DISPLAY_POINTS = NUM_SAMPS

# Batas frekuensi valid USRP B210 berdasarkan probe perangkat Anda.
USRP_MIN_FREQUENCY_MHZ = 50.0
USRP_MAX_FREQUENCY_MHZ = 6000.0

# Ukuran potongan scan otomatis.
# Input web boleh 50–6000 MHz, tetapi backend tetap membaca bertahap.
# 20 MHz dipilih sebagai nilai awal yang lebih aman daripada memaksa 56 MHz.
SWEEP_WINDOW_MHZ = 56

# Mode deteksi baru dari pembimbing:
# setiap titik FFT yang melewati threshold dihitung satu per satu.
DETECTION_MODE = "threshold_points"


app = FastAPI(title="USRP B210 Spectrum API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ScanRequest(BaseModel):
    threshold_db: float
    start_frequency_mhz: float
    end_frequency_mhz: float


default_config = {
    "threshold_db": 0.0,
    "start_frequency_mhz": 99.0,
    "end_frequency_mhz": 101.0,
    "center_frequency_mhz": 100.0,
    "sample_rate_mhz": 2.0,
    "sweep_window_mhz": SWEEP_WINDOW_MHZ,
}

scan_state = {
    "running": False,
    "completed": False,
    "config": default_config.copy(),
    "sweep": {
        "current_start_mhz": default_config["start_frequency_mhz"],
        "current_end_mhz": default_config["end_frequency_mhz"],
        "last_window_start_mhz": None,
        "last_window_end_mhz": None,
        "total_windows": 1,
        "scanned_windows": 0,
        "progress_percent": 0.0,
    },
    "detections": [],
    "last_window_detections": [],
    "last_peak": None,
    "last_error": None,
    "started_at": None,
    "updated_at": None,
}

state_lock = Lock()
device_lock = Lock()
usrp_device = None


def validate_scan_range(start_mhz: float, end_mhz: float) -> float:
    """
    Validasi input web.

    Sekarang input boleh selebar 50–6000 MHz, tetapi backend tidak
    membaca range besar itu sekaligus. Backend akan melakukan sweep
    otomatis per window SWEEP_WINDOW_MHZ.
    """

    if start_mhz <= 0 or end_mhz <= 0:
        raise HTTPException(
            status_code=400,
            detail="Frekuensi harus lebih besar dari 0 MHz.",
        )

    if end_mhz <= start_mhz:
        raise HTTPException(
            status_code=400,
            detail="End Frequency harus lebih besar dari Start Frequency.",
        )

    if (
        start_mhz < USRP_MIN_FREQUENCY_MHZ
        or end_mhz > USRP_MAX_FREQUENCY_MHZ
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "Frekuensi di luar batas USRP B210. "
                f"Range yang didukung: {USRP_MIN_FREQUENCY_MHZ}–"
                f"{USRP_MAX_FREQUENCY_MHZ} MHz."
            ),
        )

    return end_mhz - start_mhz


def get_usrp():
    global usrp_device

    with device_lock:
        if usrp_device is None:
            try:
                usrp_device = uhd.usrp.MultiUSRP(
                    f"serial={USRP_SERIAL}"
                )
                usrp_device.set_rx_antenna(RX_ANTENNA, CHANNEL)

            except Exception as error:
                usrp_device = None
                raise HTTPException(
                    status_code=503,
                    detail=f"USRP tidak dapat diakses: {error}",
                ) from error

    return usrp_device


def get_current_state():
    with state_lock:
        return deepcopy(scan_state)


def calculate_total_windows(start_mhz: float, end_mhz: float) -> int:
    scan_width_mhz = end_mhz - start_mhz
    return max(1, int(ceil(scan_width_mhz / SWEEP_WINDOW_MHZ)))


def build_empty_debug_clusters():
    """
    Frontend lama mungkin masih membaca debug_clusters.
    Karena cluster sudah tidak dipakai, field ini tetap dikirim tetapi kosong.
    """

    return {
        "detection_mode": DETECTION_MODE,
        "message": (
            "Cluster detection disabled. "
            "Every FFT bin above threshold is counted."
        ),
        "merge_gap_mhz": None,
        "raw_clusters": [],
        "merged_clusters": [],
    }


def classify_frequency(frequency_mhz: float) -> dict:
    """
    Menjalankan semua classifier untuk satu titik frekuensi.
    """

    return {
        "gsm": classify_gsm(frequency_mhz),
        "umts": classify_umts(frequency_mhz),
        "lte": classify_lte(frequency_mhz),
        "nr": classify_nr(frequency_mhz),
    }


def build_detections_from_threshold_points(
    *,
    frequency_axis_mhz,
    power_db,
    threshold_db: float,
    window_start_mhz: float,
    window_end_mhz: float,
    window_index: int,
) -> list[dict]:
    """
    Konsep baru:
    semua titik FFT yang power-nya >= threshold dihitung.

    Tidak ada cluster.
    Tidak ada pemilihan peak terkuat per cluster.
    Setiap index FFT di atas threshold menjadi satu detection.
    """

    threshold_indexes = np.where(power_db >= threshold_db)[0]
    detections = []

    for index in threshold_indexes:
        detected_frequency_mhz = float(frequency_axis_mhz[index])
        detected_power_db = float(power_db[index])
        classification = classify_frequency(detected_frequency_mhz)

        detections.append(
            {
                "frequency_mhz": detected_frequency_mhz,
                "power_db": detected_power_db,
                "threshold_db": float(threshold_db),
                "above_threshold": True,
                "fft_index": int(index),
                "window_index": int(window_index),
                "window_start_mhz": float(window_start_mhz),
                "window_end_mhz": float(window_end_mhz),
                **classification,
            }
        )

    return detections


def get_display_spectrum(
    frequency_axis_mhz,
    power_db,
):
    """
    Mengirim data spectrum aktual dari FFT ke frontend.
    Untuk tahap awal sweep, grafik menampilkan window yang sedang discan.
    """

    return frequency_axis_mhz, power_db


def scan_frequency_window(
    *,
    window_start_mhz: float,
    window_end_mhz: float,
    threshold_db: float,
    window_index: int,
) -> dict:
    """
    Membaca satu window frekuensi, menghitung FFT, dan mengambil semua
    titik yang melewati threshold.
    """

    center_frequency_mhz = (window_start_mhz + window_end_mhz) / 2
    sample_rate_mhz = window_end_mhz - window_start_mhz

    center_frequency_hz = center_frequency_mhz * 1e6
    sample_rate_hz = sample_rate_mhz * 1e6

    try:
        usrp = get_usrp()

        with device_lock:
            samples = usrp.recv_num_samps(
                NUM_SAMPS,
                center_frequency_hz,
                sample_rate_hz,
                [CHANNEL],
                GAIN_DB,
            )

    except HTTPException:
        raise

    except Exception as error:
        raise HTTPException(
            status_code=503,
            detail=(
                "Gagal membaca sample dari USRP pada window "
                f"{window_start_mhz:.6f}–{window_end_mhz:.6f} MHz: {error}"
            ),
        ) from error

    iq_samples = np.asarray(samples[0])

    if len(iq_samples) == 0:
        raise HTTPException(
            status_code=503,
            detail="USRP tidak mengirim IQ sample.",
        )

    window = np.hanning(len(iq_samples))

    fft_data = np.fft.fftshift(
        np.fft.fft(iq_samples * window)
    )

    power_db = 20 * np.log10(np.abs(fft_data) + 1e-12)

    frequency_axis_mhz = (
        np.fft.fftshift(
            np.fft.fftfreq(
                len(iq_samples),
                d=1 / sample_rate_hz,
            )
        )
        + center_frequency_hz
    ) / 1e6

    peak_index = int(np.argmax(power_db))
    peak_frequency_mhz = float(frequency_axis_mhz[peak_index])
    peak_power_db = float(power_db[peak_index])

    detections = build_detections_from_threshold_points(
        frequency_axis_mhz=frequency_axis_mhz,
        power_db=power_db,
        threshold_db=threshold_db,
        window_start_mhz=window_start_mhz,
        window_end_mhz=window_end_mhz,
        window_index=window_index,
    )

    (
        display_frequency_mhz,
        display_power_db,
    ) = get_display_spectrum(
        frequency_axis_mhz,
        power_db,
    )

    return {
        "window": {
            "window_index": int(window_index),
            "start_frequency_mhz": float(window_start_mhz),
            "end_frequency_mhz": float(window_end_mhz),
            "center_frequency_mhz": float(center_frequency_mhz),
            "sample_rate_mhz": float(sample_rate_mhz),
            "sample_count": int(len(iq_samples)),
            "threshold_point_count": int(len(detections)),
        },
        "spectrum": {
            "frequency_mhz": display_frequency_mhz.tolist(),
            "power_db": display_power_db.tolist(),
        },
        "peak": {
            "frequency_mhz": peak_frequency_mhz,
            "power_db": peak_power_db,
            "above_threshold": bool(peak_power_db >= threshold_db),
        },
        "detections": detections,
    }


@app.get("/")
def root():
    return {
        "message": "USRP B210 Spectrum API berjalan.",
        "device": "USRP B210",
        "serial": USRP_SERIAL,
        "detection_mode": DETECTION_MODE,
        "sweep_window_mhz": SWEEP_WINDOW_MHZ,
    }


@app.get("/api/device")
def device_status():
    get_usrp()

    return {
        "status": "ready",
        "device": "USRP B210",
        "serial": USRP_SERIAL,
        "channel": CHANNEL,
        "antenna": RX_ANTENNA,
        "gain_db": GAIN_DB,
        "frequency_range_mhz": {
            "min": USRP_MIN_FREQUENCY_MHZ,
            "max": USRP_MAX_FREQUENCY_MHZ,
        },
        "sweep_window_mhz": SWEEP_WINDOW_MHZ,
        "detection_mode": DETECTION_MODE,
    }


@app.get("/api/status")
def scan_status():
    state = get_current_state()

    return {
        "running": state["running"],
        "completed": state["completed"],
        "config": state["config"],
        "sweep": state["sweep"],
        "detection_count": len(state["detections"]),
        "last_window_detection_count": len(
            state["last_window_detections"]
        ),
        "last_peak": state["last_peak"],
        "last_error": state["last_error"],
        "started_at": state["started_at"],
        "updated_at": state["updated_at"],
    }


@app.post("/api/scan/start")
def start_scan(request: ScanRequest):
    start_mhz = float(request.start_frequency_mhz)
    end_mhz = float(request.end_frequency_mhz)
    threshold_db = float(request.threshold_db)

    scan_width_mhz = validate_scan_range(start_mhz, end_mhz)
    total_windows = calculate_total_windows(start_mhz, end_mhz)

    new_config = {
        "threshold_db": threshold_db,
        "start_frequency_mhz": start_mhz,
        "end_frequency_mhz": end_mhz,
        "center_frequency_mhz": (start_mhz + end_mhz) / 2,
        "sample_rate_mhz": scan_width_mhz,
        "sweep_window_mhz": SWEEP_WINDOW_MHZ,
        "detection_mode": DETECTION_MODE,
    }

    now = datetime.now().isoformat(timespec="seconds")

    with state_lock:
        scan_state["running"] = True
        scan_state["completed"] = False
        scan_state["config"] = new_config
        scan_state["sweep"] = {
            "current_start_mhz": start_mhz,
            "current_end_mhz": min(
                start_mhz + SWEEP_WINDOW_MHZ,
                end_mhz,
            ),
            "last_window_start_mhz": None,
            "last_window_end_mhz": None,
            "total_windows": total_windows,
            "scanned_windows": 0,
            "progress_percent": 0.0,
        }
        scan_state["detections"] = []
        scan_state["last_window_detections"] = []
        scan_state["last_peak"] = None
        scan_state["last_error"] = None
        scan_state["started_at"] = now
        scan_state["updated_at"] = now

    return {
        "message": "Sweep scan USRP dimulai.",
        "running": True,
        "completed": False,
        "config": new_config,
        "sweep": get_current_state()["sweep"],
    }


@app.post("/api/scan/stop")
def stop_scan():
    with state_lock:
        scan_state["running"] = False
        scan_state["updated_at"] = datetime.now().isoformat(
            timespec="seconds"
        )
        state = deepcopy(scan_state)

    return {
        "message": "Scan USRP dihentikan.",
        "running": False,
        "completed": state["completed"],
        "config": state["config"],
        "sweep": state["sweep"],
        "detection_count": len(state["detections"]),
    }


@app.get("/api/scan/results")
def scan_results():
    """
    Mengambil hasil deteksi kumulatif dari seluruh window yang sudah discan.
    """

    state = get_current_state()

    return {
        "running": state["running"],
        "completed": state["completed"],
        "config": state["config"],
        "sweep": state["sweep"],
        "detection_count": len(state["detections"]),
        "detections": state["detections"],
        "last_window_detections": state["last_window_detections"],
        "last_peak": state["last_peak"],
        "last_error": state["last_error"],
    }


@app.get("/api/spectrum")
def get_spectrum():
    """
    Endpoint ini sekarang menjalankan sweep secara bertahap.

    Setiap kali frontend memanggil /api/spectrum:
    - backend membaca 1 window frekuensi
    - semua titik FFT yang melewati threshold dihitung
    - hasilnya ditambahkan ke detections kumulatif
    - current_start_mhz maju ke window berikutnya
    """

    state = get_current_state()

    if not state["running"]:
        return {
            "running": False,
            "completed": state["completed"],
            "config": state["config"],
            "sweep": state["sweep"],
            "spectrum": {
                "frequency_mhz": [],
                "power_db": [],
            },
            "peak": state["last_peak"],
            "detections": state["last_window_detections"],
            "detection_count": len(state["detections"]),
            "debug_clusters": build_empty_debug_clusters(),
        }

    config = state["config"]
    sweep = state["sweep"]

    full_end_mhz = config["end_frequency_mhz"]
    window_start_mhz = sweep["current_start_mhz"]
    window_end_mhz = min(
        window_start_mhz + SWEEP_WINDOW_MHZ,
        full_end_mhz,
    )
    window_index = int(sweep["scanned_windows"]) + 1

    # Jika sudah tidak ada window tersisa, tandai selesai.
    if window_start_mhz >= full_end_mhz:
        with state_lock:
            scan_state["running"] = False
            scan_state["completed"] = True
            scan_state["sweep"]["progress_percent"] = 100.0
            scan_state["updated_at"] = datetime.now().isoformat(
                timespec="seconds"
            )
            finished_state = deepcopy(scan_state)

        return {
            "running": False,
            "completed": True,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "config": finished_state["config"],
            "sweep": finished_state["sweep"],
            "spectrum": {
                "frequency_mhz": [],
                "power_db": [],
            },
            "peak": finished_state["last_peak"],
            "detections": finished_state["last_window_detections"],
            "detection_count": len(finished_state["detections"]),
            "debug_clusters": build_empty_debug_clusters(),
        }

    scan_result = scan_frequency_window(
        window_start_mhz=window_start_mhz,
        window_end_mhz=window_end_mhz,
        threshold_db=config["threshold_db"],
        window_index=window_index,
    )

    next_start_mhz = window_end_mhz
    completed = next_start_mhz >= full_end_mhz

    with state_lock:
        scan_state["detections"].extend(scan_result["detections"])
        scan_state["last_window_detections"] = scan_result["detections"]
        scan_state["last_peak"] = scan_result["peak"]
        scan_state["sweep"]["last_window_start_mhz"] = window_start_mhz
        scan_state["sweep"]["last_window_end_mhz"] = window_end_mhz
        scan_state["sweep"]["current_start_mhz"] = next_start_mhz
        scan_state["sweep"]["current_end_mhz"] = min(
            next_start_mhz + SWEEP_WINDOW_MHZ,
            full_end_mhz,
        )
        scan_state["sweep"]["scanned_windows"] = window_index
        scan_state["sweep"]["progress_percent"] = round(
            (window_index / scan_state["sweep"]["total_windows"]) * 100,
            2,
        )
        scan_state["running"] = not completed
        scan_state["completed"] = completed
        scan_state["updated_at"] = datetime.now().isoformat(
            timespec="seconds"
        )
        updated_state = deepcopy(scan_state)

    return {
        "running": updated_state["running"],
        "completed": updated_state["completed"],
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "config": updated_state["config"],
        "sweep": updated_state["sweep"],
        "current_window": scan_result["window"],
        "spectrum": scan_result["spectrum"],
        "peak": scan_result["peak"],
        # Untuk kompatibilitas frontend lama:
        # detections berisi hasil window terakhir.
        # Hasil lengkap ada di /api/scan/results.
        "detections": scan_result["detections"],
        "last_window_detection_count": len(scan_result["detections"]),
        "detection_count": len(updated_state["detections"]),
        "debug_clusters": build_empty_debug_clusters(),
    }
