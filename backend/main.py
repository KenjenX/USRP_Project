
from datetime import datetime
from threading import Lock
from copy import deepcopy
from math import ceil
import json
import os
import shutil
import subprocess
from pathlib import Path

import numpy as np
import uhd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend.gsm_classifier import classify_gsm
from backend.umts_classifier import classify_umts
from backend.lte_classifier import classify_lte
from backend.nr_classifier import classify_nr

from backend.gsm_classifier import classify_gsm
from backend.umts_classifier import classify_umts
from backend.lte_classifier import classify_lte
from backend.nr_classifier import classify_nr
from backend.machine_routes import router as machine_router
from backend.channel_lookup_routes import router as channel_lookup_router
from backend.channel_routes import router as channel_router

# =========================
# KONFIGURASI USRP
# =========================
USRP_SERIAL = "8004374"
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

# Penyimpanan riwayat scan lokal.
# Folder ini akan dibuat otomatis dan sebaiknya tetap masuk .gitignore.
SCAN_HISTORY_DIR = Path(__file__).resolve().parent / "scan_history"

# Jumlah titik maksimum untuk visual spectrum yang disimpan ke setiap file
# Scan History. Data FFT penuh tidak disimpan agar file JSON tetap ringan.
SPECTRUM_PREVIEW_TARGET_POINTS = 1600

# Pemilik scan. General dan Specific tetap memakai satu perangkat dan satu
# state backend, tetapi hanya satu mode yang boleh aktif pada satu waktu.
SCAN_OWNER_GENERAL = "general"
SCAN_OWNER_SPECIFIC = "specific"
VALID_SCAN_OWNERS = {
    SCAN_OWNER_GENERAL,
    SCAN_OWNER_SPECIFIC,
}
SCAN_MODE_RANGE_SWEEP = "range_sweep"


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
app.include_router(machine_router)
app.include_router(channel_lookup_router)
app.include_router(channel_router)


class ScanRequest(BaseModel):
    threshold_db: float
    start_frequency_mhz: float
    end_frequency_mhz: float
    scan_owner: str = SCAN_OWNER_GENERAL
    selected_machine_id: int | None = None


class StopScanRequest(BaseModel):
    scan_owner: str


default_config = {
    "threshold_db": 0.0,
    "start_frequency_mhz": 50.0,
    "end_frequency_mhz": 6000.0,
    "center_frequency_mhz": 3025.0,
    "sample_rate_mhz": 5950.0,
    "sweep_window_mhz": SWEEP_WINDOW_MHZ,
}

scan_state = {
    "running": False,
    "completed": False,
    "scan_owner": None,
    "scan_mode": None,
    "selected_machine_id": None,
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
    "spectrum_preview": {
        "frequency_mhz": [],
        "power_db": [],
        "source_point_count": 0,
        "point_count": 0,
    },
    "last_peak": None,
    "last_error": None,
    "session_id": None,
    "started_at": None,
    "completed_at": None,
    "updated_at": None,
    "session_saved": False,
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


def check_usrp_connection():
    """Mengecek USRP lewat proses UHD terpisah agar API lain tidak macet.

    Sebelumnya endpoint /api/device memanggil ``uhd.usrp.MultiUSRP`` langsung
    di proses FastAPI. Pada beberapa kondisi Windows, pencarian UHD dapat
    menunggu sangat lama ketika perangkat tidak terhubung dan membuat Machine,
    Channel, Swagger, serta Scan History ikut tidak responsif.

    Pemeriksaan ini menjalankan ``uhd_find_devices`` sebagai child process.
    Jika UHD macet, child process dihentikan setelah timeout; proses FastAPI
    tetap hidup sehingga CRUD tidak bergantung pada keberadaan USRP.
    """

    discovered_tool = (
        shutil.which("uhd_find_devices.exe")
        or shutil.which("uhd_find_devices")
    )

    candidate_paths = [
        Path(r"C:\Program Files\UHD\bin\uhd_find_devices.exe"),
        Path(r"C:\Program Files (x86)\UHD\bin\uhd_find_devices.exe"),
    ]

    tool_path = Path(discovered_tool) if discovered_tool else None

    if tool_path is None:
        tool_path = next(
            (candidate for candidate in candidate_paths if candidate.exists()),
            None,
        )

    if tool_path is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "USRP offline: uhd_find_devices.exe tidak ditemukan. "
                "Pastikan UHD terpasang atau folder UHD/bin ada di PATH."
            ),
        )

    creation_flags = 0
    if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
        creation_flags = subprocess.CREATE_NO_WINDOW

    try:
        result = subprocess.run(
            [str(tool_path), "--args", f"serial={USRP_SERIAL}"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=4,
            check=False,
            creationflags=creation_flags,
        )
    except subprocess.TimeoutExpired as error:
        raise HTTPException(
            status_code=503,
            detail=(
                "USRP offline: pemeriksaan perangkat melewati batas waktu "
                "4 detik. API CRUD tetap dapat digunakan."
            ),
        ) from error
    except Exception as error:
        raise HTTPException(
            status_code=503,
            detail=f"USRP offline: pemeriksaan perangkat gagal: {error}",
        ) from error

    output = "\n".join(
        part.strip()
        for part in (result.stdout, result.stderr)
        if part and part.strip()
    )
    normalized_output = output.lower()

    no_device_markers = (
        "no uhd devices found",
        "no devices found",
        "lookup error",
        "keyerror",
    )
    target_found = USRP_SERIAL.lower() in normalized_output
    explicitly_missing = any(
        marker in normalized_output for marker in no_device_markers
    )

    if result.returncode != 0 or explicitly_missing or not target_found:
        detail = "USRP offline: perangkat dengan serial target tidak ditemukan."

        # Batasi pesan UHD agar indikator frontend tidak menjadi terlalu panjang.
        if output:
            compact_output = " ".join(output.split())
            detail = f"{detail} {compact_output[:220]}"

        raise HTTPException(status_code=503, detail=detail)

    return {
        "connected": True,
        "tool": str(tool_path),
    }


def get_current_state():
    with state_lock:
        return deepcopy(scan_state)


def normalize_scan_owner(value: str) -> str:
    owner = str(value or "").strip().lower()

    if owner not in VALID_SCAN_OWNERS:
        raise HTTPException(
            status_code=422,
            detail="scan_owner harus bernilai general atau specific.",
        )

    return owner


def get_scan_identity(state: dict) -> dict:
    return {
        "scan_owner": state.get("scan_owner"),
        "scan_mode": state.get("scan_mode"),
        "selected_machine_id": state.get("selected_machine_id"),
    }


def calculate_total_windows(start_mhz: float, end_mhz: float) -> int:
    scan_width_mhz = end_mhz - start_mhz
    return max(1, int(ceil(scan_width_mhz / SWEEP_WINDOW_MHZ)))


def create_empty_spectrum_preview() -> dict:
    """
    Membuat accumulator spectrum preview untuk satu scan session.
    """

    return {
        "frequency_mhz": [],
        "power_db": [],
        "source_point_count": 0,
        "point_count": 0,
    }


def downsample_spectrum_peak_preserving(
    frequency_values,
    power_values,
    target_points: int,
) -> tuple[list[float], list[float]]:
    """
    Mengecilkan satu window FFT sambil mempertahankan nilai minimum dan
    maksimum setiap bucket. Puncak sinyal tetap terlihat, tetapi jumlah data
    yang disimpan ke JSON jauh lebih kecil daripada FFT mentah.
    """

    frequency_array = np.asarray(frequency_values, dtype=float)
    power_array = np.asarray(power_values, dtype=float)

    point_count = min(len(frequency_array), len(power_array))

    if point_count <= 0 or target_points <= 0:
        return [], []

    frequency_array = frequency_array[:point_count]
    power_array = power_array[:point_count]

    finite_mask = np.isfinite(frequency_array) & np.isfinite(power_array)
    frequency_array = frequency_array[finite_mask]
    power_array = power_array[finite_mask]
    point_count = len(frequency_array)

    if point_count <= 0:
        return [], []

    if point_count <= target_points:
        return frequency_array.tolist(), power_array.tolist()

    bucket_count = max(1, target_points // 2)
    bucket_edges = np.linspace(
        0,
        point_count,
        bucket_count + 1,
        dtype=int,
    )

    selected_indexes: list[int] = []

    for bucket_index in range(bucket_count):
        start_index = int(bucket_edges[bucket_index])
        end_index = int(bucket_edges[bucket_index + 1])

        if end_index <= start_index:
            continue

        bucket_power = power_array[start_index:end_index]
        minimum_index = start_index + int(np.argmin(bucket_power))
        maximum_index = start_index + int(np.argmax(bucket_power))

        selected_indexes.extend(sorted({minimum_index, maximum_index}))

    if target_points % 2 == 1 and selected_indexes:
        selected_indexes.append(point_count - 1)

    selected_indexes = sorted(set(selected_indexes))[:target_points]

    return (
        frequency_array[selected_indexes].tolist(),
        power_array[selected_indexes].tolist(),
    )


def append_spectrum_preview_window(
    preview: dict,
    spectrum: dict,
    total_windows: int,
) -> None:
    """
    Menambahkan preview dari satu window ke accumulator session.

    Alokasi titik dibagi menurut jumlah window, sehingga scan pendek tetap
    memiliki detail tinggi dan sweep 50–6000 MHz tetap sekitar 1.600 titik.
    """

    frequency_values = spectrum.get("frequency_mhz", [])
    power_values = spectrum.get("power_db", [])
    source_point_count = min(len(frequency_values), len(power_values))

    if source_point_count <= 0:
        return

    points_per_window = max(
        8,
        int(ceil(SPECTRUM_PREVIEW_TARGET_POINTS / max(1, total_windows))),
    )

    preview_frequency, preview_power = downsample_spectrum_peak_preserving(
        frequency_values,
        power_values,
        points_per_window,
    )

    preview["frequency_mhz"].extend(preview_frequency)
    preview["power_db"].extend(preview_power)
    preview["source_point_count"] += int(source_point_count)
    preview["point_count"] = len(preview["frequency_mhz"])


def finalize_spectrum_preview(state: dict) -> dict | None:
    """
    Menyiapkan spectrum preview final yang aman disimpan ke JSON.
    """

    preview = deepcopy(state.get("spectrum_preview") or {})
    frequency_values = preview.get("frequency_mhz", [])
    power_values = preview.get("power_db", [])
    point_count = min(len(frequency_values), len(power_values))

    if point_count <= 0:
        return None

    frequency_values = frequency_values[:point_count]
    power_values = power_values[:point_count]

    order = sorted(
        range(point_count),
        key=lambda index: float(frequency_values[index]),
    )

    sorted_frequency = [float(frequency_values[index]) for index in order]
    sorted_power = [float(power_values[index]) for index in order]

    config = state.get("config", {})

    return {
        "format": "peak_preserving_min_max_v1",
        "frequency_mhz": sorted_frequency,
        "power_db": sorted_power,
        "point_count": len(sorted_frequency),
        "source_point_count": int(preview.get("source_point_count", 0)),
        "target_point_count": SPECTRUM_PREVIEW_TARGET_POINTS,
        "start_frequency_mhz": config.get("start_frequency_mhz"),
        "end_frequency_mhz": config.get("end_frequency_mhz"),
        "threshold_db": config.get("threshold_db"),
        "min_power_db": min(sorted_power),
        "max_power_db": max(sorted_power),
    }


def ensure_scan_history_dir() -> None:
    """
    Membuat folder penyimpanan riwayat scan jika belum ada.
    """

    SCAN_HISTORY_DIR.mkdir(parents=True, exist_ok=True)


def create_scan_session_id() -> str:
    """
    Membuat ID session yang aman untuk nama file.
    """

    return datetime.now().strftime("scan_%Y%m%d_%H%M%S_%f")


def sanitize_session_id(session_id: str) -> str:
    """
    Mencegah path traversal saat membaca file history berdasarkan session_id.
    """

    safe_id = "".join(
        char for char in str(session_id)
        if char.isalnum() or char in {"_", "-"}
    )

    if not safe_id:
        raise HTTPException(
            status_code=400,
            detail="Session ID tidak valid.",
        )

    return safe_id


def get_scan_history_file_path(session_id: str) -> Path:
    safe_id = sanitize_session_id(session_id)
    return SCAN_HISTORY_DIR / f"{safe_id}.json"


def build_scan_history_title(
    completed_at: str | None,
    session_id: str,
    scan_owner: str | None = None,
) -> str:
    owner_label = {
        SCAN_OWNER_GENERAL: "General Scan",
        SCAN_OWNER_SPECIFIC: "Specific Scan",
    }.get(scan_owner, "Scan")

    if completed_at:
        return f"{owner_label} {completed_at.replace('T', ' ')}"

    return f"{owner_label} {session_id}"


def build_scan_session_payload(state: dict, completed_at: str) -> dict:
    """
    Membuat payload JSON untuk satu scan session.
    """

    session_id = state.get("session_id") or create_scan_session_id()
    detections = state.get("detections", [])
    spectrum_preview = finalize_spectrum_preview(state)

    return {
        "id": session_id,
        "session_id": session_id,
        "title": build_scan_history_title(
            completed_at,
            session_id,
            state.get("scan_owner"),
        ),
        "startedAt": state.get("started_at"),
        "started_at": state.get("started_at"),
        "completedAt": completed_at,
        "completed_at": completed_at,
        **get_scan_identity(state),
        "config": state.get("config", {}),
        "sweep": state.get("sweep", {}),
        "peak": state.get("last_peak"),
        "spectrum_preview": spectrum_preview,
        "detections": detections,
        "detectionCount": len(detections),
        "detection_count": len(detections),
        "last_error": state.get("last_error"),
    }


def save_scan_session_payload(session_payload: dict) -> None:
    """
    Menyimpan satu scan session ke file JSON.
    """

    ensure_scan_history_dir()

    session_id = session_payload["session_id"]
    file_path = get_scan_history_file_path(session_id)

    with file_path.open("w", encoding="utf-8") as file:
        json.dump(session_payload, file, ensure_ascii=False, indent=2)


def save_completed_session_if_needed_locked() -> dict | None:
    """
    Dipanggil saat state_lock sedang aktif.
    Menyimpan hasil scan sekali saja ketika scan completed.
    """

    if not scan_state.get("completed"):
        return None

    if scan_state.get("session_saved"):
        return None

    completed_at = scan_state.get("completed_at") or datetime.now().isoformat(
        timespec="seconds"
    )

    scan_state["completed_at"] = completed_at

    session_payload = build_scan_session_payload(
        deepcopy(scan_state),
        completed_at,
    )

    save_scan_session_payload(session_payload)
    scan_state["session_saved"] = True

    return session_payload


def load_scan_session(session_id: str) -> dict:
    """
    Membaca satu file scan session dari folder scan_history.
    """

    file_path = get_scan_history_file_path(session_id)

    if not file_path.exists():
        raise HTTPException(
            status_code=404,
            detail="Scan session tidak ditemukan.",
        )

    try:
        with file_path.open("r", encoding="utf-8") as file:
            return json.load(file)

    except json.JSONDecodeError as error:
        raise HTTPException(
            status_code=500,
            detail=f"File scan history rusak: {file_path.name}",
        ) from error


def delete_scan_session_file(session_id: str) -> dict:
    """
    Menghapus satu file scan session dari folder scan_history.
    """

    file_path = get_scan_history_file_path(session_id)

    if not file_path.exists():
        raise HTTPException(
            status_code=404,
            detail="Scan session tidak ditemukan.",
        )

    safe_id = sanitize_session_id(session_id)
    file_path.unlink()

    return {
        "deleted": True,
        "session_id": safe_id,
        "filename": file_path.name,
    }


def delete_all_scan_session_files() -> dict:
    """
    Menghapus semua file JSON scan history.
    """

    ensure_scan_history_dir()

    deleted_files = []

    for file_path in SCAN_HISTORY_DIR.glob("*.json"):
        try:
            file_path.unlink()
            deleted_files.append(file_path.name)
        except FileNotFoundError:
            continue

    return {
        "deleted": True,
        "deleted_count": len(deleted_files),
        "deleted_files": deleted_files,
    }


def load_all_scan_sessions() -> list[dict]:
    """
    Membaca seluruh scan session yang tersimpan.
    Data diurutkan dari scan terbaru ke scan terlama.
    """

    ensure_scan_history_dir()

    sessions = []

    for file_path in SCAN_HISTORY_DIR.glob("*.json"):
        try:
            with file_path.open("r", encoding="utf-8") as file:
                session = json.load(file)

            sessions.append(session)

        except json.JSONDecodeError:
            # Abaikan file JSON yang rusak agar endpoint history tetap berjalan.
            continue

    return sorted(
        sessions,
        key=lambda session: session.get("completed_at")
        or session.get("completedAt")
        or session.get("started_at")
        or session.get("startedAt")
        or "",
        reverse=True,
    )


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
        "scan_history_storage": "json",
    }


@app.get("/api/device")
def device_status():
    check_usrp_connection()

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
        "checked_at": datetime.now().isoformat(timespec="seconds"),
    }


@app.get("/api/status")
def scan_status():
    state = get_current_state()

    return {
        "running": state["running"],
        "completed": state["completed"],
        **get_scan_identity(state),
        "config": state["config"],
        "sweep": state["sweep"],
        "detection_count": len(state["detections"]),
        "last_window_detection_count": len(
            state["last_window_detections"]
        ),
        "last_peak": state["last_peak"],
        "last_error": state["last_error"],
        "session_id": state["session_id"],
        "started_at": state["started_at"],
        "completed_at": state["completed_at"],
        "updated_at": state["updated_at"],
        "session_saved": state["session_saved"],
    }


@app.post("/api/scan/start")
def start_scan(request: ScanRequest):
    start_mhz = float(request.start_frequency_mhz)
    end_mhz = float(request.end_frequency_mhz)
    threshold_db = float(request.threshold_db)
    requested_owner = normalize_scan_owner(request.scan_owner)

    selected_machine_id = (
        int(request.selected_machine_id)
        if request.selected_machine_id is not None
        else None
    )

    if requested_owner == SCAN_OWNER_GENERAL:
        selected_machine_id = None

    if (
        requested_owner == SCAN_OWNER_SPECIFIC
        and selected_machine_id is None
    ):
        raise HTTPException(
            status_code=422,
            detail="Specific Scan membutuhkan Machine yang dipilih.",
        )

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
    session_id = create_scan_session_id()

    # Pemeriksaan dan pengambilan ownership dilakukan dalam lock yang sama.
    # Request kedua tidak dapat menimpa scan yang masih berjalan.
    with state_lock:
        if scan_state["running"]:
            active_owner = scan_state.get("scan_owner") or "unknown"
            raise HTTPException(
                status_code=409,
                detail=(
                    "Scanner sedang digunakan oleh "
                    f"{active_owner.title()} Scan."
                ),
            )

        scan_state["running"] = True
        scan_state["completed"] = False
        scan_state["scan_owner"] = requested_owner
        scan_state["scan_mode"] = SCAN_MODE_RANGE_SWEEP
        scan_state["selected_machine_id"] = selected_machine_id
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
        scan_state["spectrum_preview"] = create_empty_spectrum_preview()
        scan_state["last_peak"] = None
        scan_state["last_error"] = None
        scan_state["session_id"] = session_id
        scan_state["started_at"] = now
        scan_state["completed_at"] = None
        scan_state["updated_at"] = now
        scan_state["session_saved"] = False
        started_state = deepcopy(scan_state)

    return {
        "message": (
            f"{requested_owner.title()} sweep scan dimulai."
        ),
        "running": True,
        "completed": False,
        **get_scan_identity(started_state),
        "config": new_config,
        "sweep": started_state["sweep"],
        "session_id": session_id,
    }


@app.post("/api/scan/stop")
def stop_scan(request: StopScanRequest):
    requested_owner = normalize_scan_owner(request.scan_owner)

    with state_lock:
        active_owner = scan_state.get("scan_owner")

        if scan_state["running"] and active_owner != requested_owner:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Scan hanya dapat dihentikan dari halaman pemiliknya. "
                    f"Scanner sedang digunakan oleh "
                    f"{str(active_owner).title()} Scan."
                ),
            )

        scan_state["running"] = False
        scan_state["updated_at"] = datetime.now().isoformat(
            timespec="seconds"
        )
        state = deepcopy(scan_state)

    return {
        "message": f"{requested_owner.title()} Scan dihentikan.",
        "running": False,
        "completed": state["completed"],
        **get_scan_identity(state),
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
        **get_scan_identity(state),
        "config": state["config"],
        "sweep": state["sweep"],
        "detection_count": len(state["detections"]),
        "detections": state["detections"],
        "last_window_detections": state["last_window_detections"],
        "spectrum_preview": finalize_spectrum_preview(state),
        "last_peak": state["last_peak"],
        "last_error": state["last_error"],
        "session_id": state["session_id"],
        "started_at": state["started_at"],
        "completed_at": state["completed_at"],
        "session_saved": state["session_saved"],
    }



@app.get("/api/scan/history")
def scan_history():
    """
    Mengambil seluruh scan session yang sudah disimpan ke file JSON.
    """

    sessions = load_all_scan_sessions()

    return {
        "count": len(sessions),
        "storage": "json",
        "sessions": sessions,
    }


@app.delete("/api/scan/history")
def delete_all_scan_history():
    """
    Menghapus semua file JSON scan history.
    """

    result = delete_all_scan_session_files()

    return {
        "message": "Semua scan history berhasil dihapus.",
        **result,
    }


@app.delete("/api/scan/history/{session_id}")
def delete_scan_history_detail(session_id: str):
    """
    Menghapus satu scan session berdasarkan session_id.
    """

    result = delete_scan_session_file(session_id)

    return {
        "message": "Scan history berhasil dihapus.",
        **result,
    }


@app.get("/api/scan/history/{session_id}")
def scan_history_detail(session_id: str):
    """
    Mengambil detail satu scan session berdasarkan session_id.
    """

    session = load_scan_session(session_id)

    return session


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
            **get_scan_identity(state),
            "config": state["config"],
            "sweep": state["sweep"],
            "spectrum": {
                "frequency_mhz": [],
                "power_db": [],
            },
            "peak": state["last_peak"],
            "detections": state["last_window_detections"],
            "detection_count": len(state["detections"]),
            "spectrum_preview": finalize_spectrum_preview(state),
            "session_id": state["session_id"],
            "completed_at": state["completed_at"],
            "session_saved": state["session_saved"],
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
            completed_at = datetime.now().isoformat(timespec="seconds")
            scan_state["completed_at"] = completed_at
            scan_state["updated_at"] = completed_at
            save_completed_session_if_needed_locked()
            finished_state = deepcopy(scan_state)

        return {
            "running": False,
            "completed": True,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            **get_scan_identity(finished_state),
            "config": finished_state["config"],
            "sweep": finished_state["sweep"],
            "spectrum": {
                "frequency_mhz": [],
                "power_db": [],
            },
            "peak": finished_state["last_peak"],
            "detections": finished_state["last_window_detections"],
            "detection_count": len(finished_state["detections"]),
            "spectrum_preview": finalize_spectrum_preview(finished_state),
            "session_id": finished_state["session_id"],
            "completed_at": finished_state["completed_at"],
            "session_saved": finished_state["session_saved"],
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
        append_spectrum_preview_window(
            scan_state["spectrum_preview"],
            scan_result["spectrum"],
            scan_state["sweep"]["total_windows"],
        )
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
        updated_at = datetime.now().isoformat(timespec="seconds")
        scan_state["updated_at"] = updated_at

        if completed:
            scan_state["completed_at"] = updated_at
            save_completed_session_if_needed_locked()

        updated_state = deepcopy(scan_state)

    return {
        "running": updated_state["running"],
        "completed": updated_state["completed"],
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        **get_scan_identity(updated_state),
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
        "spectrum_preview": finalize_spectrum_preview(updated_state),
        "session_id": updated_state["session_id"],
        "completed_at": updated_state["completed_at"],
        "session_saved": updated_state["session_saved"],
        "debug_clusters": build_empty_debug_clusters(),
    }
