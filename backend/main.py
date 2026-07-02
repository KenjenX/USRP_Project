from datetime import datetime
from threading import Lock

import numpy as np
import uhd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel


# =========================
# KONFIGURASI USRP
# =========================
USRP_SERIAL = "8004374"
CHANNEL = 0
RX_ANTENNA = "RX2"
GAIN_DB = 35
NUM_SAMPS = 4096
DISPLAY_POINTS = 512

# Versi awal hanya scan satu window spectrum.
# Sesuai konfigurasi awal Anda: maksimal 2 MHz.
MAX_SCAN_WINDOW_MHZ = 2.0


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

    step = max(1, len(power_db) // DISPLAY_POINTS)

    display_frequency_mhz = frequency_axis_mhz[::step][
        :DISPLAY_POINTS
    ]

    display_power_db = power_db[::step][:DISPLAY_POINTS]

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
                peak_power_db > config["threshold_db"]
            ),
        },
    }