from datetime import datetime
from threading import Lock

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
NUM_SAMPS = 1024
DISPLAY_POINTS = NUM_SAMPS
# Merge gap dinonaktifkan agar cluster lebih sederhana:
# cluster hanya terbentuk dari titik FFT yang benar-benar berurutan
# dan berada di atas threshold.
CLUSTER_MERGE_GAP_MHZ = 0.0

# Versi awal hanya scan satu window spectrum.
# Sesuai konfigurasi awal Anda: maksimal 2 MHz.
MAX_SCAN_WINDOW_MHZ = 2.0

# Batas frekuensi valid USRP B210 berdasarkan probe perangkat.
# Input di luar range ini ditolak agar grafik web tidak menyesatkan.
USRP_MIN_FREQUENCY_MHZ = 50.0
USRP_MAX_FREQUENCY_MHZ = 6000.0


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
}

scan_state = {
    "running": False,
    "config": default_config.copy(),
}

state_lock = Lock()
device_lock = Lock()
usrp_device = None


def validate_scan_range(start_mhz, end_mhz):
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

    scan_width_mhz = end_mhz - start_mhz

    if scan_width_mhz > MAX_SCAN_WINDOW_MHZ:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Rentang scan sementara maksimal {MAX_SCAN_WINDOW_MHZ} MHz. "
                "Contoh yang benar: 99 sampai 101 MHz. "
                "Sweep scan untuk rentang besar akan dibuat nanti."
            ),
        )

    return scan_width_mhz


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
        return scan_state["running"], scan_state["config"].copy()
    
def build_threshold_clusters(
    frequency_axis_mhz,
    power_db,
    threshold_db,
):
    """
    Membuat cluster threshold aktual.

    raw_clusters:
        titik FFT berurutan dengan power >= threshold.

    merged_clusters:
        saat merge gap dinonaktifkan, nilainya sama dengan raw_clusters.
    """

    raw_clusters = []
    index = 0

    while index < len(power_db):
        if power_db[index] < threshold_db:
            index += 1
            continue

        cluster_start = index

        while (
            index + 1 < len(power_db)
            and power_db[index + 1] >= threshold_db
        ):
            index += 1

        cluster_end = index

        raw_clusters.append(
            (cluster_start, cluster_end)
        )

        index += 1

    # Merge gap dinonaktifkan.
    # Artinya cluster akhir sama dengan raw cluster:
    # jika sinyal turun di bawah threshold, cluster langsung berhenti.
    merged_clusters = raw_clusters.copy()

    return raw_clusters, merged_clusters


def build_detections_from_clusters(
    frequency_axis_mhz,
    power_db,
    merged_clusters,
):
    detections = []

    for cluster_start, cluster_end in merged_clusters:
        cluster_power = power_db[
            cluster_start:cluster_end + 1
        ]

        local_peak_offset = int(
            np.argmax(cluster_power)
        )

        peak_index = (
            cluster_start + local_peak_offset
        )

        detected_frequency_mhz = float(
            frequency_axis_mhz[peak_index]
        )

        detected_power_db = float(
            power_db[peak_index]
        )

        detections.append(
            {
                "frequency_mhz": detected_frequency_mhz,
                "power_db": detected_power_db,
                "gsm": classify_gsm(
                    detected_frequency_mhz
                ),
                "umts": classify_umts(
                    detected_frequency_mhz
                ),
                "lte": classify_lte(
                    detected_frequency_mhz
                ),
                "nr": classify_nr(
                    detected_frequency_mhz
                ),
            }
        )

    return detections


def build_cluster_debug_items(
    frequency_axis_mhz,
    power_db,
    clusters,
):
    debug_items = []

    for index, (cluster_start, cluster_end) in enumerate(clusters):
        cluster_power = power_db[
            cluster_start:cluster_end + 1
        ]

        local_peak_offset = int(
            np.argmax(cluster_power)
        )

        peak_index = (
            cluster_start + local_peak_offset
        )

        start_mhz = float(
            frequency_axis_mhz[cluster_start]
        )

        end_mhz = float(
            frequency_axis_mhz[cluster_end]
        )

        peak_mhz = float(
            frequency_axis_mhz[peak_index]
        )

        peak_power_db = float(
            power_db[peak_index]
        )

        debug_items.append(
            {
                "id": index + 1,
                "start_mhz": start_mhz,
                "end_mhz": end_mhz,
                "peak_mhz": peak_mhz,
                "peak_power_db": peak_power_db,
                "width_khz": abs(end_mhz - start_mhz) * 1000,
                "point_count": int(cluster_end - cluster_start + 1),
            }
        )

    return debug_items


def find_threshold_detections(
    frequency_axis_mhz,
    power_db,
    threshold_db,
):
    """
    Mencari peak dari setiap sinyal yang memenuhi threshold.
    """

    _, merged_clusters = build_threshold_clusters(
        frequency_axis_mhz,
        power_db,
        threshold_db,
    )

    return build_detections_from_clusters(
        frequency_axis_mhz,
        power_db,
        merged_clusters,
    )


def get_display_spectrum(
    frequency_axis_mhz,
    power_db,
):
    """
    Mengirim data spectrum aktual dari FFT ke frontend.

    Tidak memakai peak-preserving bucket dan tidak memilih peak per bagian.
    Tujuannya agar grafik yang tampil sama dengan data FFT yang dipakai
    untuk threshold dan cluster.
    """

    return frequency_axis_mhz, power_db

@app.get("/")
def root():
    return {
        "message": "USRP B210 Spectrum API berjalan.",
        "device": "USRP B210",
        "serial": USRP_SERIAL,
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
    }


@app.get("/api/status")
def scan_status():
    running, config = get_current_state()

    return {
        "running": running,
        "config": config,
    }


@app.post("/api/scan/start")
def start_scan(request: ScanRequest):
    start_mhz = float(request.start_frequency_mhz)
    end_mhz = float(request.end_frequency_mhz)
    threshold_db = float(request.threshold_db)

    scan_width_mhz = validate_scan_range(start_mhz, end_mhz)

    new_config = {
        "threshold_db": threshold_db,
        "start_frequency_mhz": start_mhz,
        "end_frequency_mhz": end_mhz,
        "center_frequency_mhz": (start_mhz + end_mhz) / 2,
        "sample_rate_mhz": scan_width_mhz,
    }

    with state_lock:
        scan_state["running"] = True
        scan_state["config"] = new_config

    return {
        "message": "Scan USRP dimulai.",
        "running": True,
        "config": new_config,
    }


@app.post("/api/scan/stop")
def stop_scan():
    with state_lock:
        scan_state["running"] = False
        config = scan_state["config"].copy()

    return {
        "message": "Scan USRP dihentikan.",
        "running": False,
        "config": config,
    }


@app.get("/api/spectrum")
def get_spectrum():
    running, config = get_current_state()

    if not running:
        return {
            "running": False,
            "config": config,
            "spectrum": {
                "frequency_mhz": [],
                "power_db": [],
            },
            "peak": None,
            "detections": [],
            "debug_clusters": {
                "merge_gap_mhz": CLUSTER_MERGE_GAP_MHZ,
                "raw_clusters": [],
                "merged_clusters": [],
            },
        }

    center_frequency_hz = config["center_frequency_mhz"] * 1e6
    sample_rate_hz = config["sample_rate_mhz"] * 1e6

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
            detail=f"Gagal membaca sample dari USRP: {error}",
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

    (
        raw_clusters,
        merged_clusters,
    ) = build_threshold_clusters(
        frequency_axis_mhz,
        power_db,
        config["threshold_db"],
    )

    detections = build_detections_from_clusters(
        frequency_axis_mhz,
        power_db,
        merged_clusters,
    )

    debug_clusters = {
        "merge_gap_mhz": CLUSTER_MERGE_GAP_MHZ,
        "raw_clusters": build_cluster_debug_items(
            frequency_axis_mhz,
            power_db,
            raw_clusters,
        ),
        "merged_clusters": build_cluster_debug_items(
            frequency_axis_mhz,
            power_db,
            merged_clusters,
        ),
    }

    # Grafik frontend menampilkan data FFT aktual yang sama
    # dengan data yang dipakai untuk threshold, cluster, dan detection.
    (
        display_frequency_mhz,
        display_power_db,
    ) = get_display_spectrum(
        frequency_axis_mhz,
        power_db,
    )

    return {
        "running": True,
        "timestamp": datetime.now().isoformat(
            timespec="seconds"
        ),
        "config": config,
        "spectrum": {
            "frequency_mhz": display_frequency_mhz.tolist(),
            "power_db": display_power_db.tolist(),
        },
        "peak": {
            "frequency_mhz": peak_frequency_mhz,
            "power_db": peak_power_db,
            "above_threshold": bool(
                peak_power_db >= config["threshold_db"]
            ),
        },
        "detections": detections,
        "debug_clusters": debug_clusters,
    }