
from datetime import datetime
from threading import Event, Lock, Thread
from copy import deepcopy
from math import ceil, isfinite
from time import perf_counter_ns
from uuid import uuid4
import json
import os
import shutil
import subprocess
from pathlib import Path

import numpy as np
from fastapi import FastAPI, HTTPException, Request
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
from backend.database import SessionLocal
from backend.models import Channel, Machine
from backend.scanner_worker import (
    UhdScannerError,
    UhdScannerManager,
)

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


BENCHMARK_SCHEMA_VERSION = 1
benchmark_lock = Lock()
benchmark_sessions: dict[str, dict] = {}


def benchmark_enabled() -> bool:
    return os.environ.get("USRP_BENCHMARK_ENABLED") == "1"


def benchmark_classifier_breakdown_enabled() -> bool:
    return benchmark_enabled() and os.environ.get(
        "USRP_BENCHMARK_CLASSIFIER_BREAKDOWN"
    ) == "1"


def benchmark_ms_since(start_ns: int) -> float:
    return (perf_counter_ns() - start_ns) / 1_000_000


def safe_benchmark_log(prefix: str, payload: dict) -> None:
    """Benchmark output is strictly best-effort and never affects scans."""
    try:
        print(prefix + " " + json.dumps(payload, separators=(",", ":")))
    except Exception:
        pass


def percentile_values(values: list[float]) -> dict:
    if not values:
        return {"p50": None, "p95": None, "p99": None}
    return {
        "p50": float(np.percentile(values, 50)),
        "p95": float(np.percentile(values, 95)),
        "p99": float(np.percentile(values, 99)),
    }


def create_benchmark_session(state: dict) -> None:
    if not benchmark_enabled() or not state.get("session_id"):
        return
    with benchmark_lock:
        benchmark_sessions[state["session_id"]] = {
            "session_id": state["session_id"],
            "scan_owner": state.get("scan_owner"),
            "range_start_mhz": state["config"]["start_frequency_mhz"],
            "range_end_mhz": state["config"]["end_frequency_mhz"],
            "expected_window_count": state["sweep"]["total_windows"],
            "started_ns": perf_counter_ns(), "last_request_start_ns": None,
            "last_response_finish_ns": None, "windows": [],
            "acquisition_error_count": 0, "in_flight_count": 0,
            "completed": False, "summary_emitted": False,
            "terminal_outcome": None,
            "snapshot_request_count": 0, "snapshot_last_request_start_ns": None,
            "snapshot_last_response_finish_ns": None, "snapshot_polls": [],
            "architecture_mode": "continuous_rolling_sweep",
        }


def register_benchmark_poll(context: dict) -> None:
    """Attach polling gaps after the endpoint has identified the session."""
    session_id = context.get("session_id")
    if not session_id:
        return
    with benchmark_lock:
        session = benchmark_sessions.get(session_id)
        if session is None:
            return
        if context.get("benchmark_registered"):
            return
        start_ns = context["request_start_ns"]
        previous_start = session["last_request_start_ns"]
        previous_finish = session["last_response_finish_ns"]
        if previous_start is not None:
            context["timings_ms"]["request_start_gap_ms"] = (
                start_ns - previous_start
            ) / 1_000_000
        if previous_finish is not None:
            context["timings_ms"]["poll_idle_ms"] = (
                start_ns - previous_finish
            ) / 1_000_000
        session["last_request_start_ns"] = start_ns
        session["in_flight_count"] += 1
        context["benchmark_registered"] = True


def discard_benchmark_session(session_id: str | None, reason: str) -> None:
    """Remove an aborted benchmark session without affecting scan lifecycle."""
    if not benchmark_enabled() or not session_id:
        return
    try:
        with benchmark_lock:
            session = benchmark_sessions.get(session_id)
            # A completed scan owns the successful terminal event.  A late Stop,
            # disconnect, or acquisition exception must not turn it into abort.
            if session is None or session.get("completed") or session.get("terminal_outcome"):
                return False
            session["terminal_outcome"] = "sweep_aborted"
            benchmark_sessions.pop(session_id, None)
        if session is not None:
            safe_benchmark_log("[BENCH]", {
                "event": "sweep_aborted", "schema_version": BENCHMARK_SCHEMA_VERSION,
                "session_id": session_id, "scan_owner": session.get("scan_owner"),
                "reason": reason,
            })
        return True
    except Exception:
        return False


def register_benchmark_snapshot_poll(context: dict) -> None:
    """Record read-only spectrum polling independently of acquisition windows."""
    session_id = context.get("session_id")
    if not session_id:
        return
    with benchmark_lock:
        session = benchmark_sessions.get(session_id)
        if session is None or session.get("terminal_outcome"):
            return
        started_ns = context["request_start_ns"]
        previous_start = session["snapshot_last_request_start_ns"]
        previous_finish = session["snapshot_last_response_finish_ns"]
        if previous_start is not None:
            context["timings_ms"]["snapshot_request_gap_ms"] = (
                started_ns - previous_start
            ) / 1_000_000
        if previous_finish is not None:
            context["timings_ms"]["snapshot_poll_idle_ms"] = (
                started_ns - previous_finish
            ) / 1_000_000
        session["snapshot_last_request_start_ns"] = started_ns
        session["snapshot_request_count"] += 1
        context["snapshot_registered"] = True


def finish_benchmark_snapshot_poll(context: dict) -> None:
    """Finish an HTTP snapshot metric without changing acquisition state."""
    if not context.get("snapshot_request"):
        return
    try:
        finished_ns = perf_counter_ns()
        context["timings_ms"]["snapshot_request_latency_ms"] = (
            finished_ns - context["request_start_ns"]
        ) / 1_000_000
        session_id = context.get("session_id")
        with benchmark_lock:
            session = benchmark_sessions.get(session_id)
            if session is not None and context.get("snapshot_registered"):
                session["snapshot_last_response_finish_ns"] = finished_ns
                session["snapshot_polls"].append({
                    "latency_ms": context["timings_ms"]["snapshot_request_latency_ms"],
                    "response_bytes": context.get("response_bytes", 0),
                    "gap_ms": context["timings_ms"].get("snapshot_request_gap_ms"),
                })
        safe_benchmark_log("[BENCH]", {
            "event": "spectrum_snapshot", "schema_version": BENCHMARK_SCHEMA_VERSION,
            "architecture_mode": "autonomous_single_sweep", "session_id": session_id,
            "response_bytes": context.get("response_bytes", 0),
            "timings_ms": context["timings_ms"],
        })
    except Exception:
        pass


def finish_benchmark_window(context: dict) -> None:
    """Emit the window event only after the final ASGI body chunk is sent."""
    try:
        session_id = context.get("session_id")
        if not session_id or not context.get("window"):
            return
        with benchmark_lock:
            session = benchmark_sessions.get(session_id)
            if session is None:
                return
            session["last_response_finish_ns"] = perf_counter_ns()
            if context.get("benchmark_registered"):
                session["in_flight_count"] = max(
                    0, session["in_flight_count"] - 1
                )
                context["benchmark_registered"] = False
            if context.get("sweep_completed"):
                session["completed"] = True
            event = None
            if context.get("success"):
                timings = context["timings_ms"]
                session["windows"].append(context)
                event = {
                    "event": "spectrum_window", "schema_version": BENCHMARK_SCHEMA_VERSION,
                    "architecture_mode": "request_driven", "session_id": session_id,
                    "request_id": context["request_id"], "scan_owner": context["scan_owner"],
                    "window_index": context["window_index"], "total_windows": context["total_windows"],
                    "window_start_mhz": context["window_start_mhz"],
                    "window_end_mhz": context["window_end_mhz"],
                    "sample_count": context.get("sample_count", 0),
                    "threshold_bin_count": context.get("threshold_bin_count", 0),
                    "detection_count": context.get("detection_count", 0),
                    "cumulative_detection_count": context.get("cumulative_detection_count", 0),
                    "channel_measurement_count": context.get("channel_measurement_count", 0),
                    "threshold_detection_invariant_ok": context.get("threshold_detection_invariant_ok", False),
                    "worker_reused": timings.get("worker_reused", False),
                    "worker_started_this_call": timings.get("worker_started_this_call", False),
                    "response_bytes": context.get("response_bytes", 0), "timings_ms": timings,
                }
            summary_needed = (
                session["completed"]
                and session["in_flight_count"] == 0
                and not session["summary_emitted"]
            )
            if summary_needed:
                session["summary_emitted"] = True
        if event is not None:
            safe_benchmark_log("[BENCH]", event)
        if summary_needed:
            emit_benchmark_summary(session_id)
    except Exception:
        pass


def emit_benchmark_summary(
    session_id: str,
    *,
    terminal_event: str = "sweep_summary",
    continuous_state: dict | None = None,
) -> None:
    try:
        with benchmark_lock:
            session = benchmark_sessions.get(session_id)
            if session is None or session.get("terminal_outcome"):
                return
            if (
                not session.get("summary_emitted")
                and session.get("architecture_mode") != "continuous_rolling_sweep"
            ):
                return
            session["terminal_outcome"] = terminal_event
            benchmark_sessions.pop(session_id, None)
        if session is None:
            return
        windows = session["windows"]
        architecture_mode = session.get("architecture_mode", "request_driven")
        active_metric = (
            "controller_window_active_ms"
            if architecture_mode in {
                "autonomous_single_sweep",
                "continuous_rolling_sweep",
            }
            else "endpoint_logic_ms"
        )
        metrics = (active_metric, "http_total_ms", "poll_idle_ms", "manager_acquire_total_ms",
                   "uhd_recv_num_samps_ms", "fft_ms", "threshold_index_ms",
                   "classification_total_ms", "channel_measurement_ms", "preview_append_ms",
                   "state_deepcopy_ms", "preview_finalize_ms", "response_prepare_ms",
                   "response_bytes")
        def percentiles(source):
            return {name: percentile_values([w["timings_ms"].get(name, w.get(name))
                    for w in source if w["timings_ms"].get(name, w.get(name)) is not None]) for name in metrics}
        poll_idle_total = sum(w["timings_ms"].get("poll_idle_ms", 0.0) for w in windows)
        snapshot_polls = session["snapshot_polls"]
        snapshot_gaps = [
            poll["gap_ms"] for poll in snapshot_polls if poll["gap_ms"] is not None
        ]
        snapshot_mean_gap_ms = (
            sum(snapshot_gaps) / len(snapshot_gaps) if snapshot_gaps else None
        )
        wall_ms = (perf_counter_ns() - session["started_ns"]) / 1_000_000
        if architecture_mode == "continuous_rolling_sweep":
            expected_window = lambda index: (index % session["expected_window_count"]) + 1
            sequence_gap_count = sum(
                1 for index, window in enumerate(windows)
                if window["window_index"] != expected_window(index)
            )
        else:
            sequence_gap_count = sum(
                1 for index, window in enumerate(windows, 1)
                if window["window_index"] != index
            )
        summary = {
            "event": terminal_event, "schema_version": BENCHMARK_SCHEMA_VERSION,
            "architecture_mode": architecture_mode, "session_id": session_id,
            "scan_owner": session["scan_owner"], "range_start_mhz": session["range_start_mhz"],
            "range_end_mhz": session["range_end_mhz"], "window_count": len(windows),
            "expected_window_count": session["expected_window_count"], "sweep_wall_ms": wall_ms,
            "active_pipeline_metric": active_metric,
            "active_pipeline_total_ms": sum(w["timings_ms"].get(active_metric, 0.0) for w in windows),
            "poll_idle_total_ms": poll_idle_total,
            "poll_idle_percent": (poll_idle_total / wall_ms * 100) if wall_ms else 0.0,
            "hop_per_second": (len(windows) / (wall_ms / 1000)) if wall_ms else 0.0,
            "sample_count_total": sum(w.get("sample_count", 0) for w in windows),
            "detection_count_total": sum(w.get("detection_count", 0) for w in windows),
            "response_bytes_total": sum(w.get("response_bytes", 0) for w in windows),
            "snapshot_polling": {
                "request_count": session["snapshot_request_count"],
                "request_gap_percentiles_ms": percentile_values(snapshot_gaps),
                "mean_polling_frequency_hz": (
                    1000 / snapshot_mean_gap_ms if snapshot_mean_gap_ms else None
                ),
                "request_latency_percentiles_ms": percentile_values([
                    poll["latency_ms"] for poll in snapshot_polls
                ]),
                "response_bytes_total": sum(poll["response_bytes"] for poll in snapshot_polls),
            },
            "acquisition_error_count": session["acquisition_error_count"],
            "window_sequence_gap_count": sequence_gap_count,
            "deadline_metrics_supported": False,
            "timing_percentiles_ms": {"all_windows": percentiles(windows),
                "warm_windows_excluding_first": percentiles(windows[1:])},
        }
        if continuous_state is not None:
            summary.update({
                "completed_cycle_count": continuous_state.get("completed_cycles", 0),
                "current_rolling_detection_count": len(
                    continuous_state.get("detections", [])
                ),
            })
        safe_benchmark_log("[BENCH]", summary)
    except Exception:
        pass


class BenchmarkHttpMiddleware:
    """ASGI send observer; it does not alter or buffer the response."""
    def __init__(self, app): self.app = app

    async def __call__(self, scope, receive, send):
        enabled = benchmark_enabled() and scope.get("path") == "/api/spectrum"
        if not enabled:
            await self.app(scope, receive, send)
            return
        context = {"request_start_ns": perf_counter_ns(), "timings_ms": {}}
        scope.setdefault("state", {})["benchmark_context"] = context
        response_start_ns = None
        async def observed_send(message):
            nonlocal response_start_ns
            if message["type"] == "http.response.start":
                response_start_ns = perf_counter_ns()
                context["timings_ms"]["response_prepare_ms"] = (
                    response_start_ns - context.get("endpoint_logic_end_ns", response_start_ns)
                ) / 1_000_000
            elif message["type"] == "http.response.body":
                context["response_bytes"] = context.get("response_bytes", 0) + len(message.get("body", b""))
                if not message.get("more_body", False):
                    # These durations end when the downstream ASGI send completes.
                    await send(message)
                    finished_ns = perf_counter_ns()
                    context["timings_ms"]["http_total_ms"] = (finished_ns - context["request_start_ns"]) / 1_000_000
                    context["timings_ms"]["response_body_emit_ms"] = (finished_ns - (response_start_ns or finished_ns)) / 1_000_000
                    if context.get("snapshot_request"):
                        finish_benchmark_snapshot_poll(context)
                    else:
                        finish_benchmark_window(context)
                    return
            await send(message)
        await self.app(scope, receive, observed_send)


app.add_middleware(BenchmarkHttpMiddleware)


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
    "selected_machine_name": None,
    # Target Channel hanya dipakai oleh Specific Scan. Data ini diambil sekali
    # saat scan dimulai agar backend tidak perlu query database setiap window.
    "specific_channel_targets": [],
    # Measurement aktual per Channel/side. Bentuk internal berupa dict agar
    # hasil target yang sama pada batas window dapat diperbarui tanpa duplikat.
    "channel_measurements": {},
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
    # Rolling per-window state. Public `detections` remains a stable flattened
    # view for compatibility, while this map prevents growth across cycles.
    "detections_by_window": {},
    "last_window_detections": [],
    "latest_window_snapshot": None,
    "spectrum_preview": {
        "segments": {},
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
    "history_save_error": None,
    "cycle_index": 1,
    "completed_cycles": 0,
    "cycle_window_index": 0,
    "cycle_total_windows": 1,
    "cycle_progress_percent": 0.0,
    "last_completed_cycle_at": None,
}

state_lock = Lock()
# Serializes worker release against the narrow start/controller-registration
# interval so a stale lifecycle action cannot release a newer worker.
scan_lifecycle_lock = Lock()
scanner_manager = UhdScannerManager(
    serial=USRP_SERIAL,
    channel=CHANNEL,
    rx_antenna=RX_ANTENNA,
    gain_db=GAIN_DB,
)

# The controller owns autonomous window progression; these objects are never
# stored in scan_state or persisted to scan history.
controller_lock = Lock()
controller_thread = None
controller_session_id = None
controller_stop_event = None

# Detector USB pasif. Detector ini hanya membaca daftar perangkat Plug and
# Play Windows (konsep yang setara dengan lsusb di Linux). Detector tidak
# menjalankan UHD dan tidak membuat MultiUSRP.
USB_DETECT_INTERVAL_SECONDS = 5
USB_DEVICE_MATCH_TERMS = (
    "usrp",
    "b200",
    "b210",
    "ettus",
    USRP_SERIAL.lower(),
)

usb_status_lock = Lock()
usb_detector_stop_event = Event()
usb_detector_thread = None
usb_device_state = {
    "connected": None,
    "status": "unknown",
    "device": "USRP B210",
    "serial": USRP_SERIAL,
    "detector": "windows_pnp" if os.name == "nt" else "lsusb",
    "friendly_name": None,
    "instance_id": None,
    "detail": "The USB detector has not completed a check yet.",
    "checked_at": None,
    "changed_at": None,
}


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
            detail="Frequency must be greater than 0 MHz.",
        )

    if end_mhz <= start_mhz:
        raise HTTPException(
            status_code=400,
            detail="End Frequency must be greater than Start Frequency.",
        )

    if (
        start_mhz < USRP_MIN_FREQUENCY_MHZ
        or end_mhz > USRP_MAX_FREQUENCY_MHZ
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "Frequency is outside the USRP B210 limits. "
                f"Supported range: {USRP_MIN_FREQUENCY_MHZ}–"
                f"{USRP_MAX_FREQUENCY_MHZ} MHz."
            ),
        )

    return end_mhz - start_mhz


def select_reference_sweep_rate_mhz(start_mhz: float, stop_mhz: float) -> float:
    """C++ SDRScannerEngine scan-rate policy for the full requested span."""
    if not isfinite(start_mhz) or not isfinite(stop_mhz) or stop_mhz <= start_mhz:
        raise ValueError("scan range must be finite with stop greater than start")
    return 20.0 if (stop_mhz - start_mhz) < 100.0 else 56.0


def build_reference_hop_plan(start_mhz: float, stop_mhz: float) -> tuple[float, tuple[float, ...]]:
    """Immutable, index-built equivalent of the reference C++ center loop."""
    rate_mhz = select_reference_sweep_rate_mhz(start_mhz, stop_mhz)
    span_mhz = stop_mhz - start_mhz
    if span_mhz <= rate_mhz:
        return rate_mhz, (start_mhz + span_mhz / 2.0,)
    # The C++ condition is center < stop + rate / 2.  Computing each center
    # from its integer index avoids endpoint drift from repeated additions.
    hop_count = int(ceil(span_mhz / rate_mhz))
    centers = tuple(start_mhz + rate_mhz * (index + 0.5) for index in range(hop_count))
    return rate_mhz, centers



def _normalize_usb_probe_result(connected, **extra):
    now = datetime.now().isoformat(timespec="seconds")
    status = "connected" if connected is True else (
        "disconnected" if connected is False else "unknown"
    )

    return {
        "connected": connected,
        "status": status,
        "device": "USRP B210",
        "serial": USRP_SERIAL,
        "detector": extra.get(
            "detector",
            "windows_pnp" if os.name == "nt" else "lsusb",
        ),
        "friendly_name": extra.get("friendly_name"),
        "instance_id": extra.get("instance_id"),
        "detail": extra.get("detail"),
        "checked_at": now,
        "changed_at": None,
    }


def _probe_windows_pnp_device():
    """Membaca perangkat PnP yang sedang hadir tanpa menyentuh UHD."""

    powershell = shutil.which("powershell.exe") or shutil.which("powershell")

    if not powershell:
        return _normalize_usb_probe_result(
            None,
            detector="windows_pnp",
            detail="PowerShell was not found to read the PnP device.",
        )

    match_pattern = "|".join(
        term.replace("'", "''") for term in USB_DEVICE_MATCH_TERMS
    )
    script = rf"""
$ErrorActionPreference = 'Stop'
$OutputEncoding = [Console]::OutputEncoding = [Text.UTF8Encoding]::new()
$pattern = '{match_pattern}'
$device = Get-PnpDevice -PresentOnly -ErrorAction Stop |
    Where-Object {{
        ($_.FriendlyName -and $_.FriendlyName -match $pattern) -or
        ($_.InstanceId -and $_.InstanceId -match $pattern)
    }} |
    Select-Object -First 1 Status, Class, FriendlyName, InstanceId

if ($null -ne $device) {{
    $device | ConvertTo-Json -Compress
}}
""".strip()

    creation_flags = 0
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        creation_flags = subprocess.CREATE_NO_WINDOW

    try:
        result = subprocess.run(
            [
                str(powershell),
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=4,
            check=False,
            creationflags=creation_flags,
        )
    except subprocess.TimeoutExpired:
        return _normalize_usb_probe_result(
            None,
            detector="windows_pnp",
            detail="The PnP device check timed out.",
        )
    except Exception as error:
        return _normalize_usb_probe_result(
            None,
            detector="windows_pnp",
            detail=f"The PnP device check failed: {error}",
        )

    output = result.stdout.strip()

    if result.returncode != 0:
        compact_error = " ".join(result.stderr.split())[:220]
        return _normalize_usb_probe_result(
            None,
            detector="windows_pnp",
            detail=(
                "Windows could not read the PnP device list."
                + (f" {compact_error}" if compact_error else "")
            ),
        )

    if not output:
        return _normalize_usb_probe_result(
            False,
            detector="windows_pnp",
            detail="USRP was not found in the Windows PnP device list.",
        )

    try:
        device = json.loads(output)
    except json.JSONDecodeError:
        return _normalize_usb_probe_result(
            None,
            detector="windows_pnp",
            detail="The PnP detector output could not be read.",
        )

    if isinstance(device, list):
        device = device[0] if device else {}

    return _normalize_usb_probe_result(
        True,
        detector="windows_pnp",
        friendly_name=device.get("FriendlyName"),
        instance_id=device.get("InstanceId"),
        detail="USRP was found through the Windows PnP device list.",
    )


def _probe_linux_usb_device():
    """Fallback Linux menggunakan lsusb, tetap tanpa membuka UHD."""

    lsusb_path = shutil.which("lsusb")

    if not lsusb_path:
        return _normalize_usb_probe_result(
            None,
            detector="lsusb",
            detail="The lsusb command was not found.",
        )

    try:
        result = subprocess.run(
            [lsusb_path],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=4,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return _normalize_usb_probe_result(
            None,
            detector="lsusb",
            detail="The lsusb check timed out.",
        )
    except Exception as error:
        return _normalize_usb_probe_result(
            None,
            detector="lsusb",
            detail=f"The lsusb check failed: {error}",
        )

    if result.returncode != 0:
        return _normalize_usb_probe_result(
            None,
            detector="lsusb",
            detail="lsusb could not read the USB device list.",
        )

    normalized_output = result.stdout.lower()
    connected = any(term in normalized_output for term in USB_DEVICE_MATCH_TERMS)

    return _normalize_usb_probe_result(
        connected,
        detector="lsusb",
        detail=(
            "USRP was found through lsusb."
            if connected
            else "USRP was not found through lsusb."
        ),
    )


def probe_usb_device():
    if os.name == "nt":
        return _probe_windows_pnp_device()

    return _probe_linux_usb_device()


def update_usb_device_state(next_state):
    """Menyimpan hasil detector dan hanya mencetak log saat status berubah."""

    with usb_status_lock:
        previous_status = usb_device_state.get("status")
        next_status = next_state.get("status", "unknown")
        changed_at = usb_device_state.get("changed_at")

        if next_status != previous_status:
            changed_at = next_state.get("checked_at")

        usb_device_state.clear()
        usb_device_state.update(next_state)
        usb_device_state["changed_at"] = changed_at

    if next_status != previous_status:
        print(f"[DEVICE] SDR USB status: {next_status.upper()}")

        # Worker UHD berada di proses terpisah. Ketika USB hilang, proses
        # scanner dihentikan paksa agar crash native tidak menjatuhkan FastAPI.
        if next_status == "disconnected":
            scan_lifecycle_lock.acquire()
            with state_lock:
                disconnected_session_id = scan_state.get("session_id")
                if scan_state.get("running"):
                    now = datetime.now().isoformat(timespec="seconds")
                    scan_state["running"] = False
                    scan_state["completed"] = False
                    scan_state["last_error"] = (
                        "The USRP connection was lost while the scan was running."
                    )
                    scan_state["updated_at"] = now
            # The session id is captured while state is protected, then all
            # potentially blocking controller/worker operations happen outside.
            _signal_controller_stop(disconnected_session_id)
            try:
                scanner_manager.release("USB disconnected", force=True)
            except Exception:
                pass
            discard_benchmark_session(
                disconnected_session_id,
                "usb_disconnected",
            )
            scan_lifecycle_lock.release()


def get_usb_device_state():
    with usb_status_lock:
        return deepcopy(usb_device_state)


def usb_detector_loop():
    while not usb_detector_stop_event.is_set():
        update_usb_device_state(probe_usb_device())
        usb_detector_stop_event.wait(USB_DETECT_INTERVAL_SECONDS)


def start_usb_detector():
    global usb_detector_thread

    if usb_detector_thread and usb_detector_thread.is_alive():
        return

    usb_detector_stop_event.clear()
    usb_detector_thread = Thread(
        target=usb_detector_loop,
        name="usb-device-detector",
        daemon=True,
    )
    usb_detector_thread.start()


def stop_usb_detector():
    usb_detector_stop_event.set()

    if usb_detector_thread and usb_detector_thread.is_alive():
        usb_detector_thread.join(timeout=1.0)


@app.on_event("startup")
def app_startup():
    start_usb_detector()


@app.on_event("shutdown")
def app_shutdown():
    stop_usb_detector()
    scan_lifecycle_lock.acquire()
    state = get_current_state()
    session_id = state.get("session_id")
    _signal_controller_stop(session_id)
    try:
        scanner_manager.release("application shutdown", force=True)
    except Exception:
        pass
    finally:
        _join_controller(session_id)
        discard_benchmark_session(session_id, "application_shutdown")
        scan_lifecycle_lock.release()


def get_current_state():
    with state_lock:
        return deepcopy(scan_state)


def normalize_scan_owner(value: str) -> str:
    owner = str(value or "").strip().lower()

    if owner not in VALID_SCAN_OWNERS:
        raise HTTPException(
            status_code=422,
            detail="scan_owner must be either general or specific.",
        )

    return owner


def get_scan_identity(state: dict) -> dict:
    return {
        "scan_owner": state.get("scan_owner"),
        "scan_mode": state.get("scan_mode"),
        "selected_machine_id": state.get("selected_machine_id"),
        "selected_machine_name": state.get("selected_machine_name"),
    }


def release_scan_lock_after_error(
    expected_session_id: str | None,
    error_message: str,
) -> dict:
    """Menghentikan scan gagal agar ownership scanner tidak tertinggal."""

    scan_lifecycle_lock.acquire()
    with state_lock:
        with controller_lock:
            controller_matches = controller_session_id == expected_session_id
            stop_requested = (
                controller_matches
                and controller_stop_event is not None
                and controller_stop_event.is_set()
            )
        if (
            expected_session_id is None
            or scan_state.get("session_id") != expected_session_id
            or not scan_state.get("running")
            or not controller_matches
            or stop_requested
        ):
            scan_lifecycle_lock.release()
            return {"transitioned": False, "state": deepcopy(scan_state)}

        now = datetime.now().isoformat(timespec="seconds")
        scan_state["running"] = False
        scan_state["completed"] = False
        scan_state["last_error"] = str(error_message)
        scan_state["updated_at"] = now
        failed_state = deepcopy(scan_state)

    _signal_controller_stop(expected_session_id)
    try:
        scanner_manager.release("scan error", force=True)
    except Exception:
        pass
    discard_benchmark_session(expected_session_id, "scan_error")
    scan_lifecycle_lock.release()
    return {"transitioned": True, "state": failed_state}


def resolve_specific_machine(machine_id: int) -> dict:
    """Memastikan Specific Scan terikat ke satu Machine yang valid."""

    db = SessionLocal()

    try:
        machine = (
            db.query(Machine)
            .filter(Machine.id == machine_id)
            .first()
        )

        if machine is None:
            raise HTTPException(
                status_code=404,
                detail="Machine for Specific Scan not found.",
            )

        channels = (
            db.query(Channel)
            .filter(Channel.machine_id == machine_id)
            .order_by(Channel.id.asc())
            .all()
        )

        if not channels:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Specific Scan membutuhkan minimal satu Channel pada "
                    f'Machine "{machine.name}".'
                ),
            )

        channel_targets: list[dict] = []

        for channel in channels:
            channel_target_frequencies: list[tuple[str, float]] = []

            if channel.freq_dl_mhz is not None:
                channel_target_frequencies.append(
                    ("DL", float(channel.freq_dl_mhz))
                )

            if channel.freq_ul_mhz is not None:
                uplink_frequency = float(channel.freq_ul_mhz)

                # TDD dapat memiliki DL dan UL pada frekuensi yang sama.
                # Satu measurement cukup agar kartu tidak menghitung target
                # identik dua kali.
                already_registered = any(
                    abs(existing_frequency - uplink_frequency) < 0.000001
                    for _, existing_frequency in channel_target_frequencies
                )

                if not already_registered:
                    channel_target_frequencies.append(
                        ("UL", uplink_frequency)
                    )

            for side, target_frequency_mhz in channel_target_frequencies:
                channel_targets.append(
                    {
                        "channel_id": int(channel.id),
                        "channel_number": str(channel.channel_number),
                        "side": side,
                        "target_frequency_mhz": target_frequency_mhz,
                    }
                )

        if not channel_targets:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Specific Scan requires at least one DL/UL frequency "
                    f'for Machine "{machine.name}".'
                ),
            )

        return {
            "id": int(machine.id),
            "name": str(machine.name),
            "channel_count": len(channels),
            "channel_targets": channel_targets,
        }
    finally:
        db.close()


def get_channel_measurements(state: dict) -> list[dict]:
    """Mengubah measurement internal menjadi list stabil untuk response JSON."""

    measurements = state.get("channel_measurements") or {}

    if isinstance(measurements, dict):
        values = list(measurements.values())
    elif isinstance(measurements, list):
        values = measurements
    else:
        values = []

    return sorted(
        (deepcopy(item) for item in values),
        key=lambda item: (
            int(item.get("channel_id", 0)),
            str(item.get("side", "")),
        ),
    )


def calculate_total_windows(start_mhz: float, end_mhz: float) -> int:
    return len(build_reference_hop_plan(start_mhz, end_mhz)[1])


def create_empty_spectrum_preview() -> dict:
    """
    Membuat accumulator spectrum preview untuk satu scan session.
    """

    return {
        "segments": {},
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
    segments = preview.get("segments") or {}
    if segments:
        frequency_values = []
        power_values = []
        for _, segment in sorted(segments.items(), key=lambda item: int(item[0])):
            point_count = min(
                len(segment.get("frequency_mhz", [])),
                len(segment.get("power_db", [])),
            )
            frequency_values.extend(segment.get("frequency_mhz", [])[:point_count])
            power_values.extend(segment.get("power_db", [])[:point_count])
    else:
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

    sorted_frequency = []
    sorted_power = []
    seen_frequency = set()
    for index in order:
        frequency = float(frequency_values[index])
        power = float(power_values[index])
        key = format(frequency, ".12g")
        if key not in seen_frequency:
            seen_frequency.add(key)
            sorted_frequency.append(frequency)
            sorted_power.append(power)

    config = state.get("config", {})

    return {
        "format": "peak_preserving_min_max_v1",
        "frequency_mhz": sorted_frequency,
        "power_db": sorted_power,
        "point_count": len(sorted_frequency),
        "source_point_count": int(sum(
            int(segment.get("source_point_count", 0))
            for segment in segments.values()
        )) if segments else int(preview.get("source_point_count", 0)),
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
            detail="Invalid session ID.",
        )

    return safe_id


def get_scan_history_file_path(session_id: str) -> Path:
    safe_id = sanitize_session_id(session_id)
    return SCAN_HISTORY_DIR / f"{safe_id}.json"


def build_scan_history_title(
    completed_at: str | None,
    session_id: str,
    scan_owner: str | None = None,
    selected_machine_name: str | None = None,
) -> str:
    owner_label = {
        SCAN_OWNER_GENERAL: "General Scan",
        SCAN_OWNER_SPECIFIC: "Specific Scan",
    }.get(scan_owner, "Scan")

    if scan_owner == SCAN_OWNER_SPECIFIC and selected_machine_name:
        owner_label = f"{owner_label} — {selected_machine_name}"

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
            state.get("selected_machine_name"),
        ),
        "startedAt": state.get("started_at"),
        "started_at": state.get("started_at"),
        "completedAt": completed_at,
        "completed_at": completed_at,
        **get_scan_identity(state),
        "config": state.get("config", {}),
        "sweep": state.get("sweep", {}),
        **get_cycle_state(state),
        "peak": state.get("last_peak"),
        "spectrum_preview": spectrum_preview,
        "detections": detections,
        "channel_measurements": get_channel_measurements(state),
        "detectionCount": len(detections),
        "detection_count": len(detections),
        "last_error": state.get("last_error"),
        "history_save_error": state.get("history_save_error"),
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


def save_completed_session_if_needed_locked(allow_stopped: bool = False) -> dict | None:
    """
    Dipanggil saat state_lock sedang aktif.
    Menyimpan hasil scan sekali saja ketika scan completed.
    """

    if not scan_state.get("completed") and not allow_stopped:
        return None

    if scan_state.get("session_saved"):
        return None

    completed_at = scan_state.get("completed_at") or datetime.now().isoformat(
        timespec="seconds"
    )

    scan_state["completed_at"] = completed_at

    try:
        session_payload = build_scan_session_payload(
            deepcopy(scan_state),
            completed_at,
        )
        save_scan_session_payload(session_payload)
    except Exception as error:
        # History persistence is best-effort after RF completion; it must not
        # prevent benchmark finalization, worker release, or thread cleanup.
        scan_state["session_saved"] = False
        scan_state["history_save_error"] = f"Unable to save scan history: {error}"
        print(f"[HISTORY] {scan_state['history_save_error']}")
        return None

    scan_state["session_saved"] = True
    scan_state["history_save_error"] = None
    return session_payload


def load_scan_session(session_id: str) -> dict:
    """
    Membaca satu file scan session dari folder scan_history.
    """

    file_path = get_scan_history_file_path(session_id)

    if not file_path.exists():
        raise HTTPException(
            status_code=404,
            detail="Scan session not found.",
        )

    try:
        with file_path.open("r", encoding="utf-8") as file:
            return json.load(file)

    except json.JSONDecodeError as error:
        raise HTTPException(
            status_code=500,
            detail=f"Scan history file is corrupted: {file_path.name}",
        ) from error


def delete_scan_session_file(session_id: str) -> dict:
    """
    Menghapus satu file scan session dari folder scan_history.
    """

    file_path = get_scan_history_file_path(session_id)

    if not file_path.exists():
        raise HTTPException(
            status_code=404,
            detail="Scan session not found.",
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


def classify_frequency(frequency_mhz: float, metrics: dict | None = None) -> dict:
    """
    Menjalankan semua classifier untuk satu titik frekuensi.
    """

    if metrics is None:
        return {
            "gsm": classify_gsm(frequency_mhz),
            "umts": classify_umts(frequency_mhz),
            "lte": classify_lte(frequency_mhz),
            "nr": classify_nr(frequency_mhz),
        }
    breakdown = benchmark_classifier_breakdown_enabled()
    result = {}
    for name, classifier in (("gsm", classify_gsm), ("umts", classify_umts),
                             ("lte", classify_lte), ("nr", classify_nr)):
        started_ns = perf_counter_ns() if breakdown else 0
        result[name] = classifier(frequency_mhz)
        if breakdown:
            metric_name = f"{name}_classifier_ms"
            metrics[metric_name] = metrics.get(metric_name, 0.0) + benchmark_ms_since(started_ns)
    return result


def build_detections_from_threshold_points(
    *,
    frequency_axis_mhz,
    power_db,
    threshold_db: float,
    window_start_mhz: float,
    window_end_mhz: float,
    window_index: int,
    metrics: dict | None = None,
) -> list[dict]:
    """
    Konsep baru:
    semua titik FFT yang power-nya >= threshold dihitung.

    Tidak ada cluster.
    Tidak ada pemilihan peak terkuat per cluster.
    Setiap index FFT di atas threshold menjadi satu detection.
    """

    threshold_started_ns = perf_counter_ns() if metrics is not None else 0
    threshold_indexes = np.where(power_db >= threshold_db)[0]
    if metrics is not None:
        metrics["threshold_index_ms"] = benchmark_ms_since(threshold_started_ns)
        metrics["threshold_bin_count"] = int(len(threshold_indexes))
        metrics["classification_total_ms"] = 0.0
        if benchmark_classifier_breakdown_enabled():
            for name in ("gsm", "umts", "lte", "nr"):
                metrics[f"{name}_classifier_ms"] = 0.0
    detections = []
    detection_started_ns = perf_counter_ns() if metrics is not None else 0

    for index in threshold_indexes:
        detected_frequency_mhz = float(frequency_axis_mhz[index])
        detected_power_db = float(power_db[index])
        classification_started_ns = perf_counter_ns() if metrics is not None else 0
        classification = classify_frequency(detected_frequency_mhz, metrics)
        if metrics is not None:
            metrics["classification_total_ms"] = metrics.get(
                "classification_total_ms", 0.0
            ) + benchmark_ms_since(classification_started_ns)

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

    if metrics is not None:
        metrics["detection_build_total_ms"] = benchmark_ms_since(detection_started_ns)
    return detections


def build_channel_measurements_from_fft(
    *,
    frequency_axis_mhz,
    power_db,
    threshold_db: float,
    window_start_mhz: float,
    window_end_mhz: float,
    window_index: int,
    channel_targets: list[dict] | None,
) -> list[dict]:
    """
    Mengambil nilai power FFT terdekat untuk setiap target Channel Specific.

    Berbeda dari detections, measurement tetap dibuat walaupun power berada
    di bawah threshold. Nilai ini dipakai kartu Specific sebagai Measured Power.
    """

    if not channel_targets:
        return []

    frequency_array = np.asarray(frequency_axis_mhz, dtype=float)
    power_array = np.asarray(power_db, dtype=float)
    point_count = min(len(frequency_array), len(power_array))

    if point_count <= 0:
        return []

    frequency_array = frequency_array[:point_count]
    power_array = power_array[:point_count]
    measurements: list[dict] = []

    for target in channel_targets:
        target_frequency_mhz = float(target["target_frequency_mhz"])

        if (
            target_frequency_mhz < window_start_mhz - 0.000001
            or target_frequency_mhz > window_end_mhz + 0.000001
        ):
            continue

        nearest_index = int(
            np.argmin(np.abs(frequency_array - target_frequency_mhz))
        )
        measured_frequency_mhz = float(frequency_array[nearest_index])
        measured_power_db = float(power_array[nearest_index])
        frequency_offset_khz = (
            measured_frequency_mhz - target_frequency_mhz
        ) * 1000.0

        measurements.append(
            {
                "channel_id": int(target["channel_id"]),
                "channel_number": str(target["channel_number"]),
                "side": str(target["side"]),
                "target_frequency_mhz": target_frequency_mhz,
                "measured_frequency_mhz": measured_frequency_mhz,
                "frequency_offset_khz": frequency_offset_khz,
                "power_db": measured_power_db,
                "threshold_db": float(threshold_db),
                "above_threshold": bool(
                    measured_power_db >= threshold_db
                ),
                "fft_index": nearest_index,
                "window_index": int(window_index),
                "window_start_mhz": float(window_start_mhz),
                "window_end_mhz": float(window_end_mhz),
            }
        )

    return measurements


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
    channel_targets: list[dict] | None = None,
    metrics: dict | None = None,
    request_id: str | None = None,
    benchmark_context: dict | None = None,
    acquisition_center_mhz: float | None = None,
    acquisition_sample_rate_mhz: float | None = None,
) -> dict:
    """
    Membaca satu window frekuensi, menghitung FFT, dan mengambil semua
    titik yang melewati threshold.
    """

    center_frequency_mhz = (
        (window_start_mhz + window_end_mhz) / 2
        if acquisition_center_mhz is None else float(acquisition_center_mhz)
    )
    sample_rate_mhz = (
        window_end_mhz - window_start_mhz
        if acquisition_sample_rate_mhz is None else float(acquisition_sample_rate_mhz)
    )

    center_frequency_hz = center_frequency_mhz * 1e6
    sample_rate_hz = sample_rate_mhz * 1e6

    try:
        iq_samples = scanner_manager.acquire_samples(
            num_samps=NUM_SAMPS,
            center_frequency_hz=center_frequency_hz,
            sample_rate_hz=sample_rate_hz,
            metrics=metrics,
            request_id=request_id,
            benchmark_context=benchmark_context,
        )

    except UhdScannerError as error:
        raise HTTPException(
            status_code=503,
            detail=(
                "Failed to read samples from the USRP in the "
                f"{window_start_mhz:.6f}–{window_end_mhz:.6f} MHz window: {error}"
            ),
        ) from error

    except Exception as error:
        raise HTTPException(
            status_code=503,
            detail=(
                "The scanner worker could not be used in the "
                f"{window_start_mhz:.6f}–{window_end_mhz:.6f} MHz window: {error}"
            ),
        ) from error

    asarray_started_ns = perf_counter_ns() if metrics is not None else 0
    iq_samples = np.asarray(iq_samples)
    if metrics is not None:
        metrics["main_iq_asarray_ms"] = benchmark_ms_since(asarray_started_ns)

    if len(iq_samples) == 0:
        raise HTTPException(
            status_code=503,
            detail="The USRP did not send IQ samples.",
        )

    hann_started_ns = perf_counter_ns() if metrics is not None else 0
    window = np.hanning(len(iq_samples))
    if metrics is not None:
        metrics["hann_ms"] = benchmark_ms_since(hann_started_ns)

    fft_started_ns = perf_counter_ns() if metrics is not None else 0
    fft_data = np.fft.fftshift(
        np.fft.fft(iq_samples * window)
    )
    if metrics is not None:
        metrics["fft_ms"] = benchmark_ms_since(fft_started_ns)

    power_started_ns = perf_counter_ns() if metrics is not None else 0
    power_db = 20 * np.log10(np.abs(fft_data) + 1e-12)
    if metrics is not None:
        metrics["power_conversion_ms"] = benchmark_ms_since(power_started_ns)

    axis_started_ns = perf_counter_ns() if metrics is not None else 0
    frequency_axis_mhz = (
        np.fft.fftshift(
            np.fft.fftfreq(
                len(iq_samples),
                d=1 / sample_rate_hz,
            )
        )
        + center_frequency_hz
    ) / 1e6
    if metrics is not None:
        metrics["frequency_axis_ms"] = benchmark_ms_since(axis_started_ns)

    # A final reference hop can intentionally capture past stop.  Keep its
    # hardware block intact, but never expose out-of-requested-range bins to
    # spectrum, detections, measurements, or peak telemetry.
    crop_started_ns = perf_counter_ns() if metrics is not None else 0
    in_requested_range = (
        (frequency_axis_mhz >= float(window_start_mhz))
        & (frequency_axis_mhz <= float(window_end_mhz))
    )
    frequency_axis_mhz = frequency_axis_mhz[in_requested_range]
    power_db = power_db[in_requested_range]
    if metrics is not None:
        metrics["range_crop_ms"] = benchmark_ms_since(crop_started_ns)
    if len(frequency_axis_mhz) == 0:
        raise HTTPException(
            status_code=503,
            detail="The USRP capture contained no samples in the requested range.",
        )

    peak_started_ns = perf_counter_ns() if metrics is not None else 0
    peak_index = int(np.argmax(power_db))
    peak_frequency_mhz = float(frequency_axis_mhz[peak_index])
    peak_power_db = float(power_db[peak_index])
    if metrics is not None:
        metrics["peak_lookup_ms"] = benchmark_ms_since(peak_started_ns)

    detections = build_detections_from_threshold_points(
        frequency_axis_mhz=frequency_axis_mhz,
        power_db=power_db,
        threshold_db=threshold_db,
        window_start_mhz=window_start_mhz,
        window_end_mhz=window_end_mhz,
        window_index=window_index,
        metrics=metrics,
    )

    channel_started_ns = perf_counter_ns() if metrics is not None else 0
    channel_measurements = build_channel_measurements_from_fft(
        frequency_axis_mhz=frequency_axis_mhz,
        power_db=power_db,
        threshold_db=threshold_db,
        window_start_mhz=window_start_mhz,
        window_end_mhz=window_end_mhz,
        window_index=window_index,
        channel_targets=channel_targets,
    )
    if metrics is not None:
        metrics["channel_measurement_ms"] = benchmark_ms_since(channel_started_ns)

    (
        display_frequency_mhz,
        display_power_db,
    ) = get_display_spectrum(
        frequency_axis_mhz,
        power_db,
    )

    list_started_ns = perf_counter_ns() if metrics is not None else 0
    result = {
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
        "channel_measurements": channel_measurements,
    }
    if metrics is not None:
        metrics["spectrum_to_list_ms"] = benchmark_ms_since(list_started_ns)
    return result


def get_cycle_state(state: dict) -> dict:
    """Public, serializable rolling-cycle fields shared by scan endpoints."""
    return {
        "cycle_index": state.get("cycle_index", 1),
        "completed_cycles": state.get("completed_cycles", 0),
        "cycle_window_index": state.get("cycle_window_index", 0),
        "cycle_total_windows": state.get("cycle_total_windows", 1),
        "cycle_progress_percent": state.get("cycle_progress_percent", 0.0),
        "last_completed_cycle_at": state.get("last_completed_cycle_at"),
    }


def flatten_rolling_detections(detections_by_window: dict) -> list[dict]:
    """Stable API order without changing the one-detection-per-bin rule."""
    flattened = []
    for window_index, detections in sorted(
        detections_by_window.items(), key=lambda item: int(item[0])
    ):
        flattened.extend(sorted(
            detections,
            key=lambda item: (
                float(item.get("frequency_mhz", 0.0)),
                float(item.get("power_db", 0.0)),
            ),
        ))
    return flattened


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


def build_device_status_response():
    device_state = get_usb_device_state()
    scan = get_current_state()

    return {
        **device_state,
        "channel": CHANNEL,
        "antenna": RX_ANTENNA,
        "gain_db": GAIN_DB,
        "frequency_range_mhz": {
            "min": USRP_MIN_FREQUENCY_MHZ,
            "max": USRP_MAX_FREQUENCY_MHZ,
        },
        "sweep_window_mhz": SWEEP_WINDOW_MHZ,
        "detection_mode": DETECTION_MODE,
        "scanner_busy": bool(scan["running"]),
        "scan_owner": scan.get("scan_owner"),
        "selected_machine_id": scan.get("selected_machine_id"),
        "selected_machine_name": scan.get("selected_machine_name"),
    }


@app.get("/api/device/status")
def passive_device_status():
    # Selalu HTTP 200. Tidak adanya USRP adalah kondisi normal dan tidak boleh
    # menghentikan CRUD, Scan History, atau endpoint lain.
    return build_device_status_response()


@app.get("/api/device")
def legacy_device_status_alias():
    # Alias untuk kompatibilitas dengan frontend lama. Endpoint ini sekarang
    # memakai cache detector USB pasif dan tidak lagi menjalankan UHD.
    return build_device_status_response()


@app.get("/api/status")
def scan_status():
    state = get_current_state()

    return {
        "running": state["running"],
        "completed": state["completed"],
        **get_scan_identity(state),
        "config": state["config"],
        "sweep": state["sweep"],
        **get_cycle_state(state),
        "detection_count": len(state["detections"]),
        "last_window_detection_count": len(
            state["last_window_detections"]
        ),
        "channel_measurement_count": len(
            get_channel_measurements(state)
        ),
        "last_peak": state["last_peak"],
        "last_error": state["last_error"],
        "session_id": state["session_id"],
        "started_at": state["started_at"],
        "completed_at": state["completed_at"],
        "updated_at": state["updated_at"],
        "session_saved": state["session_saved"],
        "history_save_error": state["history_save_error"],
    }


def _controller_is_active() -> bool:
    with controller_lock:
        return controller_thread is not None and controller_thread.is_alive()


def _signal_controller_stop(session_id: str | None) -> None:
    with controller_lock:
        if controller_session_id == session_id and controller_stop_event is not None:
            controller_stop_event.set()


def _clear_controller_reference(session_id: str) -> None:
    global controller_thread, controller_session_id, controller_stop_event
    with controller_lock:
        if controller_session_id == session_id:
            controller_thread = None
            controller_session_id = None
            controller_stop_event = None


def _join_controller(session_id: str | None, timeout: float = 2.0) -> None:
    with controller_lock:
        thread = (
            controller_thread
            if controller_session_id == session_id
            else None
        )
    if thread is not None:
        thread.join(timeout=timeout)


def _record_autonomous_window(context: dict, completed: bool) -> None:
    """Record controller-owned window timing without involving HTTP polling."""
    if not benchmark_enabled():
        return
    try:
        session_id = context["session_id"]
        with benchmark_lock:
            session = benchmark_sessions.get(session_id)
            if session is None:
                return
            session["windows"].append(context)
        safe_benchmark_log("[BENCH]", {
            "event": "spectrum_window", "schema_version": 1,
            "architecture_mode": "continuous_rolling_sweep",
            "session_id": session_id, "request_id": context["request_id"],
            "scan_owner": context["scan_owner"], "window_index": context["window_index"],
            "total_windows": context["total_windows"],
            "window_start_mhz": context["window_start_mhz"], "window_end_mhz": context["window_end_mhz"],
            "sample_count": context["sample_count"], "threshold_bin_count": context["threshold_bin_count"],
            "detection_count": context["detection_count"], "cumulative_detection_count": context["cumulative_detection_count"],
            "channel_measurement_count": context["channel_measurement_count"],
            "threshold_detection_invariant_ok": context["threshold_detection_invariant_ok"],
            "worker_reused": context["timings_ms"].get("worker_reused", False),
            "worker_started_this_call": context["timings_ms"].get("worker_started_this_call", False),
            "response_bytes": 0, "timings_ms": context["timings_ms"],
        })
    except Exception:
        pass


def _record_benchmark_cycle_summary(
    session_id: str,
    cycle_index: int,
    windows: list[dict],
    cycle_started_ns: int,
) -> None:
    """Emit a non-terminal cycle summary; the session remains active."""
    if not benchmark_enabled() or not windows:
        return
    try:
        duration_ms = benchmark_ms_since(cycle_started_ns)
        safe_benchmark_log("[BENCH]", {
            "event": "sweep_cycle_summary", "schema_version": BENCHMARK_SCHEMA_VERSION,
            "architecture_mode": "continuous_rolling_sweep", "session_id": session_id,
            "cycle_index": cycle_index, "window_count": len(windows),
            "expected_window_count": windows[-1]["total_windows"],
            "cycle_duration_ms": duration_ms,
            "hop_per_second": (len(windows) / (duration_ms / 1000)) if duration_ms else 0.0,
            "detection_count": sum(window["detection_count"] for window in windows),
            "acquisition_error_count": 0,
        })
    except Exception:
        pass


def _commit_autonomous_window(
    session_id: str,
    stop_event: Event,
    scan_result: dict,
    window_start_mhz: float,
    window_end_mhz: float,
    window_index: int,
    range_end_mhz: float,
    metrics: dict | None,
) -> tuple[bool, bool, int]:
    """Atomically publish one fully processed window if its session is active."""
    lock_started_ns = perf_counter_ns() if metrics is not None else None
    with state_lock:
        if (
            stop_event.is_set()
            or scan_state.get("session_id") != session_id
            or not scan_state.get("running")
        ):
            return False, False, 0
        if metrics is not None:
            metrics["state_lock_wait_ms"] = benchmark_ms_since(lock_started_ns)
        update_started_ns = perf_counter_ns() if metrics is not None else None
        extend_started_ns = perf_counter_ns() if metrics is not None else None
        detections_by_window = scan_state.setdefault("detections_by_window", {})
        detections_by_window[str(window_index)] = deepcopy(scan_result["detections"])
        scan_state["detections"] = flatten_rolling_detections(detections_by_window)
        if metrics is not None:
            metrics["detections_extend_ms"] = benchmark_ms_since(extend_started_ns)
        scan_state["last_window_detections"] = scan_result["detections"]
        measurement_windows = scan_state.setdefault("channel_measurements_by_window", {})
        measurement_windows[str(window_index)] = deepcopy(scan_result["channel_measurements"])
        scan_state["channel_measurements"] = {}
        for measurements in measurement_windows.values():
            for measurement in measurements:
                measurement_key = f'{measurement["channel_id"]}:{measurement["side"]}'
                previous = scan_state["channel_measurements"].get(measurement_key)
                if previous is None or abs(measurement["frequency_offset_khz"]) <= abs(previous["frequency_offset_khz"]):
                    scan_state["channel_measurements"][measurement_key] = measurement
        preview_started_ns = perf_counter_ns() if metrics is not None else None
        replace_spectrum_preview_window(
            scan_state["spectrum_preview"],
            window_index,
            scan_result["spectrum"],
            scan_state["sweep"]["total_windows"],
        )
        if metrics is not None:
            metrics["preview_append_ms"] = benchmark_ms_since(preview_started_ns)
        completed = window_index >= scan_state["sweep"]["total_windows"]
        next_start_mhz = window_end_mhz
        timestamp = datetime.now().isoformat(timespec="seconds")
        scan_state["last_peak"] = scan_result["peak"]
        current_window = deepcopy(scan_result["window"])
        current_window["cycle_index"] = scan_state["cycle_index"]
        scan_state["latest_window_snapshot"] = {
            "current_window": current_window, "spectrum": scan_result["spectrum"],
            "peak": scan_result["peak"], "detections": scan_result["detections"],
            "last_window_detection_count": len(scan_result["detections"]),
            "timestamp": timestamp, "debug_clusters": build_empty_debug_clusters(),
        }
        sweep = scan_state["sweep"]
        sweep["last_window_start_mhz"] = window_start_mhz
        sweep["last_window_end_mhz"] = window_end_mhz
        sweep["current_start_mhz"] = next_start_mhz
        sweep["current_end_mhz"] = min(
            next_start_mhz + float(scan_state["config"].get("sweep_window_mhz", SWEEP_WINDOW_MHZ)),
            range_end_mhz,
        )
        sweep["scanned_windows"] = window_index
        sweep["progress_percent"] = round((window_index / sweep["total_windows"]) * 100, 2)
        scan_state["cycle_window_index"] = window_index
        scan_state["cycle_progress_percent"] = sweep["progress_percent"]
        scan_state["running"] = True
        scan_state["completed"] = False
        scan_state["updated_at"] = timestamp
        if completed:
            scan_state["completed_cycles"] += 1
            scan_state["last_completed_cycle_at"] = timestamp
            scan_state["cycle_index"] += 1
            scan_state["cycle_window_index"] = 0
            scan_state["cycle_progress_percent"] = 0.0
            sweep["current_start_mhz"] = scan_state["config"]["start_frequency_mhz"]
            sweep["current_end_mhz"] = min(
                scan_state["config"]["start_frequency_mhz"]
                + float(scan_state["config"].get("sweep_window_mhz", SWEEP_WINDOW_MHZ)),
                scan_state["config"]["end_frequency_mhz"],
            )
            sweep["scanned_windows"] = 0
            sweep["progress_percent"] = 0.0
        if metrics is not None:
            metrics["state_update_locked_ms"] = benchmark_ms_since(update_started_ns)
        return True, completed, len(scan_state["detections"])


def _run_autonomous_single_sweep(snapshot: dict, stop_event: Event) -> None:
    session_id = snapshot["session_id"]
    previous_window_finished_ns = perf_counter_ns() if benchmark_enabled() else None
    sample_rate_mhz = snapshot.get("sample_rate_mhz")
    hop_centers_mhz = snapshot.get("hop_centers_mhz")
    if sample_rate_mhz is None or hop_centers_mhz is None:
        # Backward-compatible internal snapshot shape for lifecycle tests and
        # any already-created controller snapshot during a rolling deploy.
        sample_rate_mhz, hop_centers_mhz = build_reference_hop_plan(
            snapshot["range_start_mhz"], snapshot["range_end_mhz"]
        )
    try:
        while not stop_event.is_set():
            with state_lock:
                if scan_state.get("session_id") != session_id or not scan_state.get("running"):
                    return
                cycle_index = scan_state["cycle_index"]
            cycle_started_ns = perf_counter_ns()
            cycle_windows = []
            for window_index, center_mhz in enumerate(hop_centers_mhz, start=1):
                if stop_event.is_set():
                    return
                with state_lock:
                    if scan_state.get("session_id") != session_id or not scan_state.get("running"):
                        return
                capture_start_mhz = center_mhz - sample_rate_mhz / 2.0
                capture_end_mhz = center_mhz + sample_rate_mhz / 2.0
                window_start_mhz = max(snapshot["range_start_mhz"], capture_start_mhz)
                window_end_mhz = min(snapshot["range_end_mhz"], capture_end_mhz)
                timings = {} if benchmark_enabled() else None
                window_started_ns = perf_counter_ns() if timings is not None else None
                if timings is not None and previous_window_finished_ns is not None:
                    timings["inter_window_backend_gap_ms"] = benchmark_ms_since(previous_window_finished_ns)
                    timings["controller_task_startup_ms"] = benchmark_ms_since(snapshot["controller_started_ns"])
                request_id = uuid4().hex
                try:
                    result = scan_frequency_window(
                        window_start_mhz=window_start_mhz, window_end_mhz=window_end_mhz,
                        threshold_db=snapshot["config"]["threshold_db"], window_index=window_index,
                        channel_targets=snapshot["specific_channel_targets"], metrics=timings,
                        request_id=request_id,
                        benchmark_context={"session_id": session_id, "scan_owner": snapshot["scan_owner"], "window_index": window_index},
                        acquisition_center_mhz=center_mhz,
                        acquisition_sample_rate_mhz=sample_rate_mhz,
                    )
                except Exception as error:
                    release_scan_lock_after_error(
                        session_id, str(getattr(error, "detail", error))
                    )
                    return
                if stop_event.is_set():
                    return
                committed, cycle_completed, rolling_count = _commit_autonomous_window(
                    session_id, stop_event, result, window_start_mhz, window_end_mhz,
                    window_index, snapshot["range_end_mhz"], timings,
                )
                if not committed:
                    return
                if timings is not None:
                    timings["controller_window_active_ms"] = benchmark_ms_since(window_started_ns)
                    context = {
                        "session_id": session_id, "request_id": request_id,
                        "scan_owner": snapshot["scan_owner"], "window_index": window_index,
                        "cycle_index": cycle_index, "total_windows": snapshot["total_windows"],
                        "window_start_mhz": window_start_mhz, "window_end_mhz": window_end_mhz,
                        "sample_count": result["window"]["sample_count"],
                        "threshold_bin_count": timings.get("threshold_bin_count", 0),
                        "detection_count": len(result["detections"]), "cumulative_detection_count": rolling_count,
                        "channel_measurement_count": len(result["channel_measurements"]),
                        "threshold_detection_invariant_ok": timings.get("threshold_bin_count", 0) == len(result["detections"]),
                        "timings_ms": timings,
                    }
                    _record_autonomous_window(context, cycle_completed)
                    cycle_windows.append(context)
                if cycle_completed:
                    if stop_event.is_set():
                        return
                    _record_benchmark_cycle_summary(session_id, cycle_index, cycle_windows, cycle_started_ns)
                    break
                previous_window_finished_ns = perf_counter_ns() if timings is not None else None
    finally:
        _clear_controller_reference(session_id)


@app.post("/api/scan/start")
def start_scan(request: ScanRequest):
    start_mhz = float(request.start_frequency_mhz)
    end_mhz = float(request.end_frequency_mhz)
    threshold_db = float(request.threshold_db)
    requested_owner = normalize_scan_owner(request.scan_owner)

    device_state = get_usb_device_state()

    if device_state.get("connected") is not True:
        raise HTTPException(
            status_code=503,
            detail=(
                "The USRP B210 device is not connected or its USB status is still being checked. "
                "Wait for the SDR 1 indicator to turn green before starting a scan."
            ),
        )

    selected_machine_id = (
        int(request.selected_machine_id)
        if request.selected_machine_id is not None
        else None
    )
    selected_machine_name = None
    selected_channel_targets: list[dict] = []

    if requested_owner == SCAN_OWNER_GENERAL:
        selected_machine_id = None
    elif selected_machine_id is None:
        raise HTTPException(
            status_code=422,
            detail="Specific Scan requires a selected Machine.",
        )
    else:
        machine_identity = resolve_specific_machine(selected_machine_id)
        selected_machine_id = machine_identity["id"]
        selected_machine_name = machine_identity["name"]
        selected_channel_targets = machine_identity["channel_targets"]

    validate_scan_range(start_mhz, end_mhz)
    reference_rate_mhz, reference_hop_centers_mhz = build_reference_hop_plan(
        start_mhz, end_mhz
    )
    total_windows = len(reference_hop_centers_mhz)

    new_config = {
        "threshold_db": threshold_db,
        "start_frequency_mhz": start_mhz,
        "end_frequency_mhz": end_mhz,
        "center_frequency_mhz": (start_mhz + end_mhz) / 2,
        "sample_rate_mhz": reference_rate_mhz,
        "sweep_window_mhz": reference_rate_mhz,
        "detection_mode": DETECTION_MODE,
    }

    now = datetime.now().isoformat(timespec="seconds")
    session_id = create_scan_session_id()

    scan_lifecycle_lock.acquire()
    if _controller_is_active():
        scan_lifecycle_lock.release()
        raise HTTPException(
            status_code=409,
            detail="The previous scan controller is still stopping.",
        )

    # Pemeriksaan dan pengambilan ownership dilakukan dalam lock yang sama.
    # Request kedua tidak dapat menimpa scan yang masih berjalan.
    with state_lock:
        if scan_state["running"]:
            active_owner = scan_state.get("scan_owner") or "unknown"
            scan_lifecycle_lock.release()
            raise HTTPException(
                status_code=409,
                detail=(
                    "The scanner is currently in use by "
                    f"{active_owner.title()} Scan."
                ),
            )

        scan_state["running"] = True
        scan_state["completed"] = False
        scan_state["scan_owner"] = requested_owner
        scan_state["scan_mode"] = SCAN_MODE_RANGE_SWEEP
        scan_state["selected_machine_id"] = selected_machine_id
        scan_state["selected_machine_name"] = selected_machine_name
        scan_state["specific_channel_targets"] = deepcopy(
            selected_channel_targets
        )
        scan_state["channel_measurements"] = {}
        scan_state["config"] = new_config
        scan_state["sweep"] = {
            "current_start_mhz": start_mhz,
            "current_end_mhz": min(
                start_mhz + reference_rate_mhz,
                end_mhz,
            ),
            "last_window_start_mhz": None,
            "last_window_end_mhz": None,
            "total_windows": total_windows,
            "scanned_windows": 0,
            "progress_percent": 0.0,
        }
        scan_state["detections"] = []
        scan_state["detections_by_window"] = {}
        scan_state["last_window_detections"] = []
        scan_state["latest_window_snapshot"] = None
        scan_state["spectrum_preview"] = create_empty_spectrum_preview()
        scan_state["channel_measurements_by_window"] = {}
        scan_state["last_peak"] = None
        scan_state["last_error"] = None
        scan_state["session_id"] = session_id
        scan_state["started_at"] = now
        scan_state["completed_at"] = None
        scan_state["updated_at"] = now
        scan_state["session_saved"] = False
        scan_state["history_save_error"] = None
        scan_state["cycle_index"] = 1
        scan_state["completed_cycles"] = 0
        scan_state["cycle_window_index"] = 0
        scan_state["cycle_total_windows"] = total_windows
        scan_state["cycle_progress_percent"] = 0.0
        scan_state["last_completed_cycle_at"] = None
        started_state = deepcopy(scan_state)

    create_benchmark_session(started_state)
    controller_snapshot = {
        "session_id": session_id, "scan_owner": requested_owner,
        "config": deepcopy(new_config), "range_start_mhz": start_mhz,
        "range_end_mhz": end_mhz, "total_windows": total_windows,
        "sample_rate_mhz": reference_rate_mhz,
        "hop_centers_mhz": reference_hop_centers_mhz,
        "specific_channel_targets": deepcopy(selected_channel_targets),
        "controller_started_ns": perf_counter_ns(),
    }
    stop_event = Event()
    thread = Thread(
        target=_run_autonomous_single_sweep,
        args=(controller_snapshot, stop_event),
        name="autonomous-sweep-controller",
        daemon=True,
    )
    global controller_thread, controller_session_id, controller_stop_event
    with controller_lock:
        if controller_thread is not None and controller_thread.is_alive():
            discard_benchmark_session(session_id, "controller_busy")
            with state_lock:
                if scan_state.get("session_id") == session_id:
                    scan_state["running"] = False
            scan_lifecycle_lock.release()
            raise HTTPException(
                status_code=409,
                detail="The previous scan controller is still stopping.",
            )
        controller_thread = thread
        controller_session_id = session_id
        controller_stop_event = stop_event
    try:
        thread.start()
    except BaseException:
        _clear_controller_reference(session_id)
        with state_lock:
            if scan_state.get("session_id") == session_id:
                scan_state["running"] = False
                scan_state["completed"] = False
                scan_state["scan_owner"] = None
                scan_state["scan_mode"] = None
                scan_state["selected_machine_id"] = None
                scan_state["selected_machine_name"] = None
                scan_state["specific_channel_targets"] = []
                scan_state["session_id"] = None
                scan_state["config"] = default_config.copy()
                scan_state["sweep"] = {
                    "current_start_mhz": default_config["start_frequency_mhz"],
                    "current_end_mhz": default_config["end_frequency_mhz"],
                    "last_window_start_mhz": None, "last_window_end_mhz": None,
                    "total_windows": 1, "scanned_windows": 0,
                    "progress_percent": 0.0,
                }
                scan_state["latest_window_snapshot"] = None
                scan_state["detections"] = []
                scan_state["last_window_detections"] = []
                scan_state["channel_measurements"] = {}
                scan_state["spectrum_preview"] = create_empty_spectrum_preview()
                scan_state["last_peak"] = None
                scan_state["started_at"] = None
                scan_state["completed_at"] = None
                scan_state["session_saved"] = False
                scan_state["history_save_error"] = None
                scan_state["last_error"] = "Failed to start the scan controller."
                scan_state["updated_at"] = datetime.now().isoformat(timespec="seconds")
        try:
            scanner_manager.release("controller start failed", force=True)
        except Exception:
            pass
        discard_benchmark_session(session_id, "controller_start_failed")
        scan_lifecycle_lock.release()
        raise

    scan_lifecycle_lock.release()

    return {
        "message": (
            f"{requested_owner.title()} sweep scan started."
        ),
        "running": True,
        "completed": False,
        **get_scan_identity(started_state),
        "config": new_config,
        "sweep": started_state["sweep"],
        **get_cycle_state(started_state),
        "session_id": session_id,
    }


@app.post("/api/scan/stop")
def stop_scan(request: StopScanRequest):
    requested_owner = normalize_scan_owner(request.scan_owner)

    scan_lifecycle_lock.acquire()
    with state_lock:
        active_owner = scan_state.get("scan_owner")

        if scan_state["running"] and active_owner != requested_owner:
            scan_lifecycle_lock.release()
            raise HTTPException(
                status_code=409,
                detail=(
                    "The scan can only be stopped from its owner's page. "
                    f"The scanner is currently in use by "
                    f"{str(active_owner).title()} Scan."
                ),
            )

        # Completion is terminal.  Do not convert a successful completed
        # benchmark/session into a manual abort while its controller unwinds.
        if scan_state["completed"] and not scan_state["running"]:
            state = deepcopy(scan_state)
            response = {
                "message": f"{requested_owner.title()} Scan already completed.",
                "running": False,
                "completed": True,
                **get_scan_identity(state),
                "config": state["config"],
                "sweep": state["sweep"],
                "detection_count": len(state["detections"]),
            }
            scan_lifecycle_lock.release()
            return response

        scan_state["running"] = False
        scan_state["updated_at"] = datetime.now().isoformat(
            timespec="seconds"
        )
        save_completed_session_if_needed_locked(allow_stopped=True)
        state = deepcopy(scan_state)

    # Continuous scans are terminal only on Stop.  Claim and emit the normal
    # Start-to-Stop summary before stopping the controller; unlike errors this
    # must not be reported as a sweep abort.
    try:
        emit_benchmark_summary(
            state.get("session_id"),
            terminal_event="continuous_sweep_summary",
            continuous_state=state,
        )
    except Exception:
        # Benchmark reporting is best-effort; Stop cleanup must continue.
        pass
    _signal_controller_stop(state.get("session_id"))
    try:
        scanner_manager.release("scan stopped", force=True)
    except Exception:
        # A forced worker release racing an intentional stop is expected.
        pass

    _join_controller(state.get("session_id"))
    scan_lifecycle_lock.release()

    return {
        "message": f"{requested_owner.title()} Scan stopped.",
        "running": False,
        "completed": state["completed"],
        **get_scan_identity(state),
        "config": state["config"],
        "sweep": state["sweep"],
        **get_cycle_state(state),
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
        **get_cycle_state(state),
        "detection_count": len(state["detections"]),
        "detections": state["detections"],
        "last_window_detections": state["last_window_detections"],
        "channel_measurements": get_channel_measurements(state),
        "spectrum_preview": finalize_spectrum_preview(state),
        "last_peak": state["last_peak"],
        "last_error": state["last_error"],
        "session_id": state["session_id"],
        "started_at": state["started_at"],
        "completed_at": state["completed_at"],
        "session_saved": state["session_saved"],
        "history_save_error": state["history_save_error"],
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
        "message": "All scan history was deleted successfully.",
        **result,
    }


@app.delete("/api/scan/history/{session_id}")
def delete_scan_history_detail(session_id: str):
    """
    Menghapus satu scan session berdasarkan session_id.
    """

    result = delete_scan_session_file(session_id)

    return {
        "message": "Scan history was deleted successfully.",
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
def get_spectrum(request: Request):
    """
    Mengembalikan snapshot atomik read-only dari window terakhir controller.
    """

    benchmark_context = getattr(request.state, "benchmark_context", None)
    endpoint_started_ns = perf_counter_ns() if benchmark_context is not None else 0
    state = get_current_state()

    latest_snapshot = state.get("latest_window_snapshot") or {
        "current_window": None,
        "spectrum": {"frequency_mhz": [], "power_db": []},
        "peak": state["last_peak"],
        "detections": state["last_window_detections"],
        "last_window_detection_count": len(state["last_window_detections"]),
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "debug_clusters": build_empty_debug_clusters(),
    }
    channel_snapshot = get_channel_measurements(state)
    spectrum_preview = finalize_spectrum_preview(state)
    response_started_ns = perf_counter_ns() if benchmark_context is not None else 0
    response = {
        "running": state["running"], "completed": state["completed"],
        "timestamp": latest_snapshot["timestamp"], **get_scan_identity(state),
        "config": state["config"], "sweep": state["sweep"], **get_cycle_state(state),
        "current_window": latest_snapshot["current_window"],
        "spectrum": latest_snapshot["spectrum"], "peak": latest_snapshot["peak"],
        "detections": state["detections"],
        "last_window_detections": latest_snapshot["detections"],
        "last_window_detection_count": latest_snapshot["last_window_detection_count"],
        "detection_count": len(state["detections"]),
        "channel_measurements": channel_snapshot,
        "spectrum_preview": spectrum_preview,
        "session_id": state["session_id"], "completed_at": state["completed_at"],
        "session_saved": state["session_saved"],
        "history_save_error": state["history_save_error"],
        "debug_clusters": latest_snapshot["debug_clusters"],
    }
    if benchmark_context is not None:
        benchmark_context.update({
            "snapshot_request": True, "session_id": state.get("session_id"),
            "endpoint_logic_end_ns": perf_counter_ns(),
        })
        benchmark_context["timings_ms"]["snapshot_response_prepare_ms"] = benchmark_ms_since(response_started_ns)
        benchmark_context["timings_ms"]["snapshot_endpoint_logic_ms"] = benchmark_ms_since(endpoint_started_ns)
        register_benchmark_snapshot_poll(benchmark_context)
    return response


def replace_spectrum_preview_window(
    preview: dict,
    window_index: int,
    spectrum: dict,
    total_windows: int,
) -> None:
    """Replace one bounded preview segment with the latest window result."""
    frequency_values = spectrum.get("frequency_mhz", [])
    power_values = spectrum.get("power_db", [])
    source_point_count = min(len(frequency_values), len(power_values))
    segments = preview.setdefault("segments", {})
    key = str(int(window_index))

    if source_point_count <= 0:
        segments[key] = {"frequency_mhz": [], "power_db": [], "source_point_count": 0}
        return

    points_per_window = max(
        8,
        int(ceil(SPECTRUM_PREVIEW_TARGET_POINTS / max(1, total_windows))),
    )
    frequency, power = downsample_spectrum_peak_preserving(
        frequency_values, power_values, points_per_window,
    )
    segments[key] = {
        "frequency_mhz": frequency,
        "power_db": power,
        "source_point_count": int(source_point_count),
    }
