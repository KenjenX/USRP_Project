"""Isolasi akses UHD di proses terpisah dari FastAPI.

Tujuan utama modul ini adalah memastikan crash atau hang pada library native
UHD tidak menghentikan proses utama FastAPI. Satu worker dipakai selama satu
sesi scan dan dilepas ketika scan selesai, dihentikan, gagal, atau perangkat
USB terputus.
"""

from __future__ import annotations

from multiprocessing import get_context
from threading import Lock
from time import monotonic, perf_counter_ns, sleep
import json
import os
from uuid import uuid4

import numpy as np
import uhd


def _parse_explicit_streamer_enabled(value: str | None) -> bool:
    """Parse the deliberate rollout switch; never guess an invalid value."""
    if value is None:
        return True
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(
        "USRP_EXPLICIT_STREAMER_ENABLED must be one of "
        "1/0, true/false, yes/no, or on/off."
    )


EXPLICIT_STREAMER_ENABLED = _parse_explicit_streamer_enabled(
    os.environ.get("USRP_EXPLICIT_STREAMER_ENABLED")
)


def _acquisition_backend_name(enabled: bool = EXPLICIT_STREAMER_ENABLED) -> str:
    return "explicit_streamer" if enabled else "legacy_recv_num_samps"


def _ms_since(start_ns: int) -> float:
    return (perf_counter_ns() - start_ns) / 1_000_000


def _safe_worker_benchmark_log(payload: dict) -> None:
    """Best-effort worker benchmark logging must never affect acquisition."""
    try:
        print("[BENCH_WORKER] " + json.dumps(payload, separators=(",", ":")))
    except Exception:
        pass


class UhdScannerError(RuntimeError):
    """Kesalahan yang terjadi di scanner worker UHD."""


class UhdScannerTimeoutError(UhdScannerError):
    """Scanner worker tidak memberikan respons dalam batas waktu."""


class UhdAcquisitionError(UhdScannerError):
    """A single hardware acquisition failed and contains its UHD detail."""


class _PersistentRxAcquirer:
    """Owns the explicit UHD RX streamer and its non-escaping receive buffer."""

    CPU_FORMAT = "fc32"
    WIRE_FORMAT = "sc16"
    RECEIVE_TIMEOUT_SECONDS = 0.1
    SETTLE_SECONDS = 0.002

    def __init__(self, usrp_device, config: dict) -> None:
        self._usrp_device = usrp_device
        self._config = config
        self._streamer = None
        self._streamer_key = None
        self._metadata = None
        self._buffer = None

    def clear(self) -> None:
        self._streamer = None
        self._streamer_key = None
        self._metadata = None
        self._buffer = None

    def _ensure_streamer(self, sample_rate_hz: float) -> bool:
        channel = int(self._config["channel"])
        key = (float(sample_rate_hz), channel, self.CPU_FORMAT, self.WIRE_FORMAT)
        if self._streamer is not None and self._streamer_key == key:
            return False

        # These settings belong to the active scan configuration, not a hop.
        self._usrp_device.set_master_clock_rate(float(sample_rate_hz))
        self._usrp_device.set_rx_rate(float(sample_rate_hz), channel)
        self._usrp_device.set_rx_gain(float(self._config["gain_db"]), channel)
        self._usrp_device.set_rx_antenna(self._config["rx_antenna"], channel)
        stream_args = uhd.usrp.StreamArgs(self.CPU_FORMAT, self.WIRE_FORMAT)
        stream_args.channels = [channel]
        self._streamer = self._usrp_device.get_rx_stream(stream_args)
        self._metadata = uhd.types.RXMetadata()
        self._streamer_key = key
        self._buffer = None
        return True

    @staticmethod
    def _metadata_error(
        metadata, *, received: int, expected: int, backend: str
    ) -> str | None:
        error_code = getattr(metadata, "error_code", None)
        no_error = getattr(getattr(uhd.types, "RXMetadataErrorCode", None), "none", None)
        if error_code is None or error_code == no_error:
            return None
        # Some UHD bindings stringify the enum as "none" rather than exposing
        # the enum singleton above.
        if str(error_code).strip().lower() in {"none", "rxmetadataerrorcode.none"}:
            return None
        diagnostic = getattr(metadata, "strerror", None)
        if callable(diagnostic):
            try:
                diagnostic = diagnostic()
            except Exception as error:
                diagnostic = f"strerror() failed: {type(error).__name__}: {error}"
        if diagnostic is None:
            diagnostic = "no metadata diagnostic"
        return (
            f"metadata error code={error_code}; message={diagnostic}; "
            f"received={received}; expected={expected}; backend={backend}"
        )

    @staticmethod
    def _num_done_stream_mode():
        try:
            return uhd.types.StreamMode.num_done
        except AttributeError as error:
            raise UhdAcquisitionError(
                "Installed UHD binding is incompatible: "
                "uhd.types.StreamMode.num_done is required for finite RX streaming."
            ) from error

    def acquire(self, *, num_samps: int, center_frequency_hz: float,
                sample_rate_hz: float, timings: dict | None = None) -> np.ndarray:
        if num_samps <= 0:
            raise UhdAcquisitionError("num_samps must be positive.")
        self._ensure_streamer(sample_rate_hz)
        channel = int(self._config["channel"])
        if self._buffer is None or self._buffer.shape != (1, int(num_samps)):
            # UHD 4.10 RX examples use channel-major (channels, samples)
            # arrays. RXMetadata is overwritten by each recv(), so retaining
            # this one object is safe and avoids per-hop allocations.
            self._buffer = np.empty((1, int(num_samps)), dtype=np.complex64)

        tune_started_ns = perf_counter_ns() if timings is not None else None
        self._usrp_device.set_rx_freq(float(center_frequency_hz), channel)
        if timings is not None:
            timings["uhd_tune_call_ms"] = _ms_since(tune_started_ns)
        settle_started_ns = perf_counter_ns() if timings is not None else None
        sleep(self.SETTLE_SECONDS)
        if timings is not None:
            timings["uhd_settle_ms"] = _ms_since(settle_started_ns)

        command_started_ns = perf_counter_ns() if timings is not None else None
        command = uhd.types.StreamCMD(self._num_done_stream_mode())
        command.num_samps = int(num_samps)
        command.stream_now = True
        self._streamer.issue_stream_cmd(command)
        if timings is not None:
            timings["uhd_stream_command_ms"] = _ms_since(command_started_ns)

        recv_started_ns = perf_counter_ns() if timings is not None else None
        received = self._streamer.recv(
            self._buffer, self._metadata, self.RECEIVE_TIMEOUT_SECONDS
        )
        if timings is not None:
            timings["uhd_receive_ms"] = _ms_since(recv_started_ns)
        backend = _acquisition_backend_name(True)
        metadata_error = self._metadata_error(
            self._metadata,
            received=int(received),
            expected=int(num_samps),
            backend=backend,
        )
        if metadata_error:
            raise UhdAcquisitionError(metadata_error)
        if int(received) != int(num_samps):
            raise UhdAcquisitionError(
                f"short receive: expected={num_samps}; received={received}; "
                f"backend={backend}."
            )
        # The worker buffer is intentionally reused; it must never cross the
        # process boundary by reference or be mistaken for a later receive.
        return self._buffer[0, :int(received)].copy()


def _safe_send(connection, payload: dict) -> None:
    """Mengirim payload tanpa membuat worker gagal saat parent sudah menutup."""

    try:
        connection.send(payload)
    except (BrokenPipeError, EOFError, OSError):
        pass


def _scanner_worker_main(connection, config: dict) -> None:
    """Entry point proses anak. Semua objek UHD hanya hidup di sini."""

    usrp_device = None
    explicit_acquirer = None

    try:
        try:
            usrp_device = uhd.usrp.MultiUSRP(
                f"serial={config['serial']}"
            )
            if EXPLICIT_STREAMER_ENABLED:
                explicit_acquirer = _PersistentRxAcquirer(usrp_device, config)
            else:
                usrp_device.set_rx_antenna(config["rx_antenna"], config["channel"])
        except BaseException as error:
            _safe_send(
                connection,
                {
                    "type": "ready",
                    "ok": False,
                    "error": f"{type(error).__name__}: {error}",
                },
            )
            return

        _safe_send(
            connection,
            {
                "type": "ready",
                "ok": True,
            },
        )

        while True:
            try:
                command = connection.recv()
            except (EOFError, OSError):
                break

            command_type = command.get("type")

            if command_type == "shutdown":
                break

            if command_type != "acquire":
                continue

            request_id = command.get("request_id")
            if "benchmark_enabled" in command:
                benchmark_enabled = bool(command.get("benchmark_enabled"))
                benchmark_context = (
                    command.get("benchmark_context") or {}
                    if benchmark_enabled
                    else None
                )
            else:
                benchmark_enabled = False
                benchmark_context = None

            try:
                worker_timings = {} if benchmark_enabled else None
                acquisition_started_ns = perf_counter_ns() if benchmark_enabled else None
                if EXPLICIT_STREAMER_ENABLED:
                    iq_samples = explicit_acquirer.acquire(
                        num_samps=int(command["num_samps"]),
                        center_frequency_hz=float(command["center_frequency_hz"]),
                        sample_rate_hz=float(command["sample_rate_hz"]),
                        timings=worker_timings,
                    )
                    acquisition_backend = _acquisition_backend_name(True)
                else:
                    recv_started_ns = perf_counter_ns() if benchmark_enabled else None
                    samples = usrp_device.recv_num_samps(
                        int(command["num_samps"]),
                        float(command["center_frequency_hz"]),
                        float(command["sample_rate_hz"]),
                        [int(config["channel"])],
                        float(config["gain_db"]),
                    )
                    iq_samples = np.asarray(samples[0]).copy()
                    if worker_timings is not None:
                        worker_timings["uhd_recv_num_samps_ms"] = _ms_since(recv_started_ns)
                    acquisition_backend = _acquisition_backend_name(False)

                copy_started_ns = perf_counter_ns() if benchmark_enabled else None
                # This is retained for benchmark compatibility.  Explicit
                # acquisition already made an independent copy above.
                iq_samples = np.asarray(iq_samples).copy()
                copy_ms = (
                    _ms_since(copy_started_ns)
                    if copy_started_ns is not None
                    else None
                )

                payload = {
                    "type": "result",
                    "request_id": request_id,
                    "ok": True,
                    "samples": iq_samples,
                }
                if benchmark_enabled:
                    worker_timings.update({
                        "worker_iq_copy_ms": copy_ms,
                        "worker_pre_send_total_ms": _ms_since(acquisition_started_ns),
                        "acquisition_backend": acquisition_backend,
                    })
                    payload["worker_timings_ms"] = worker_timings

                send_started_ns = perf_counter_ns() if benchmark_enabled else None
                _safe_send(connection, payload)
                if benchmark_enabled:
                    _safe_worker_benchmark_log({
                        "event": "worker_result_send",
                        "schema_version": 1,
                        "request_id": request_id,
                        "worker_result_send_ms": _ms_since(send_started_ns),
                        **benchmark_context,
                    })

            except BaseException as error:
                # Setelah error UHD, worker ini dianggap tidak aman untuk
                # dipakai kembali. Parent akan membuat worker baru pada sesi
                # scan berikutnya.
                _safe_send(
                    connection,
                    {
                        "type": "result",
                        "request_id": request_id,
                        "ok": False,
                        "error": f"{type(error).__name__}: {error}",
                    },
                )
                break

    finally:
        if explicit_acquirer is not None:
            explicit_acquirer.clear()
        try:
            connection.close()
        except OSError:
            pass

        # Objek UHD sengaja dibiarkan mati bersama proses worker. Apabila
        # destructor native macet karena USB hilang, parent tetap dapat
        # menghentikan proses anak secara paksa.
        usrp_device = None


class UhdScannerManager:
    """Mengelola satu proses UHD worker untuk satu sesi scan."""

    def __init__(
        self,
        *,
        serial: str,
        channel: int,
        rx_antenna: str,
        gain_db: float,
        startup_timeout_seconds: float = 45.0,
        acquire_timeout_seconds: float = 20.0,
        shutdown_timeout_seconds: float = 2.0,
    ) -> None:
        self._context = get_context("spawn")
        self._config = {
            "serial": str(serial),
            "channel": int(channel),
            "rx_antenna": str(rx_antenna),
            "gain_db": float(gain_db),
        }
        self._startup_timeout_seconds = float(startup_timeout_seconds)
        self._acquire_timeout_seconds = float(acquire_timeout_seconds)
        self._shutdown_timeout_seconds = float(shutdown_timeout_seconds)

        # command_lock memastikan hanya satu request acquisition yang masuk ke
        # worker. state_lock menjaga referensi proses dan Pipe.
        self._command_lock = Lock()
        self._state_lock = Lock()
        self._process = None
        self._connection = None

    def _get_current_worker(self):
        with self._state_lock:
            return self._process, self._connection

    def _detach_current_worker(self):
        with self._state_lock:
            process = self._process
            connection = self._connection
            self._process = None
            self._connection = None
            return process, connection

    def _detach_if_current(self, process, connection):
        with self._state_lock:
            if self._process is process and self._connection is connection:
                self._process = None
                self._connection = None
                return True

            return False

    @staticmethod
    def _close_connection(connection) -> None:
        if connection is None:
            return

        try:
            connection.close()
        except OSError:
            pass

    def _terminate_process(self, process, *, force: bool) -> None:
        if process is None:
            return

        if process.is_alive() and not force:
            process.join(timeout=self._shutdown_timeout_seconds)

        if process.is_alive():
            process.terminate()
            process.join(timeout=self._shutdown_timeout_seconds)

        if process.is_alive() and hasattr(process, "kill"):
            process.kill()
            process.join(timeout=self._shutdown_timeout_seconds)

        try:
            process.close()
        except (ValueError, OSError):
            pass

    def _dispose_worker(
        self,
        process,
        connection,
        *,
        force: bool,
    ) -> None:
        if connection is not None and process is not None:
            if process.is_alive() and not force:
                try:
                    connection.send({"type": "shutdown"})
                except (BrokenPipeError, EOFError, OSError):
                    pass

        self._close_connection(connection)
        self._terminate_process(process, force=force)

    def release(self, reason: str = "", *, force: bool = False) -> bool:
        """Menghentikan worker tanpa menghentikan proses FastAPI."""

        process, connection = self._detach_current_worker()

        if process is None and connection is None:
            return False

        self._dispose_worker(
            process,
            connection,
            force=force,
        )

        reason_suffix = f" ({reason})" if reason else ""
        print(f"[UHD] Scanner worker released{reason_suffix}.")
        return True

    def _wait_for_message(
        self,
        *,
        process,
        connection,
        timeout_seconds: float,
        expected_type: str,
        request_id: str | None = None,
        metrics: dict | None = None,
    ) -> dict:
        deadline = monotonic() + timeout_seconds

        while monotonic() < deadline:
            if not process.is_alive():
                exit_code = process.exitcode
                raise UhdScannerError(
                    "The UHD scanner process stopped unexpectedly"
                    + (
                        f" with exit code {exit_code}."
                        if exit_code is not None
                        else "."
                    )
                )

            try:
                poll_started_ns = perf_counter_ns() if metrics is not None else None
                has_message = connection.poll(0.1)
                if metrics is not None:
                    metrics["pipe_wait_total_ms"] = metrics.get(
                        "pipe_wait_total_ms", 0.0
                    ) + _ms_since(poll_started_ns)
            except (EOFError, OSError) as error:
                raise UhdScannerError(
                    "The connection to the UHD scanner process was lost."
                ) from error

            if not has_message:
                continue

            try:
                recv_started_ns = perf_counter_ns() if metrics is not None else None
                message = connection.recv()
                if metrics is not None:
                    metrics["pipe_result_recv_ms"] = metrics.get(
                        "pipe_result_recv_ms", 0.0
                    ) + _ms_since(recv_started_ns)
            except (EOFError, OSError) as error:
                raise UhdScannerError(
                    "The UHD scanner process closed the connection without a response."
                ) from error

            if message.get("type") != expected_type:
                continue

            if (
                request_id is not None
                and message.get("request_id") != request_id
            ):
                continue

            return message

        raise UhdScannerTimeoutError(
            "The UHD scanner process did not respond within "
            f"{timeout_seconds:.0f} seconds."
        )

    def _start_worker(self, metrics: dict | None = None):
        prepare_started_ns = perf_counter_ns() if metrics is not None else None
        existing_process, existing_connection = self._get_current_worker()

        if (
            existing_process is not None
            and existing_connection is not None
            and existing_process.is_alive()
        ):
            if metrics is not None:
                metrics["worker_reused"] = True
                metrics["worker_started_this_call"] = False
                metrics["worker_prepare_ms"] = _ms_since(prepare_started_ns)
            return existing_process, existing_connection

        if existing_process is not None or existing_connection is not None:
            detached_process, detached_connection = (
                self._detach_current_worker()
            )
            self._dispose_worker(
                detached_process,
                detached_connection,
                force=True,
            )

        parent_connection, child_connection = self._context.Pipe(
            duplex=True
        )
        process = self._context.Process(
            target=_scanner_worker_main,
            args=(child_connection, self._config),
            name="uhd-scanner-worker",
            daemon=True,
        )

        with self._state_lock:
            self._process = process
            self._connection = parent_connection

        try:
            process.start()
        except BaseException:
            self._detach_if_current(process, parent_connection)
            self._close_connection(parent_connection)
            self._close_connection(child_connection)
            raise
        finally:
            # Parent tidak menggunakan ujung Pipe milik proses anak.
            self._close_connection(child_connection)

        print(f"[UHD] Scanner worker started (PID {process.pid}).")

        try:
            ready_message = self._wait_for_message(
                process=process,
                connection=parent_connection,
                timeout_seconds=self._startup_timeout_seconds,
                expected_type="ready",
            )
        except BaseException:
            if self._detach_if_current(process, parent_connection):
                self._dispose_worker(
                    process,
                    parent_connection,
                    force=True,
                )
            raise

        if not ready_message.get("ok"):
            error_message = ready_message.get("error") or (
                "The USRP could not be initialized."
            )
            if self._detach_if_current(process, parent_connection):
                self._dispose_worker(
                    process,
                    parent_connection,
                    force=True,
                )
            raise UhdScannerError(error_message)

        if metrics is not None:
            metrics["worker_reused"] = False
            metrics["worker_started_this_call"] = True
            metrics["worker_prepare_ms"] = _ms_since(prepare_started_ns)
        return process, parent_connection

    def acquire_samples(
        self,
        *,
        num_samps: int,
        center_frequency_hz: float,
        sample_rate_hz: float,
        timeout_seconds: float | None = None,
        metrics: dict | None = None,
        request_id: str | None = None,
        benchmark_context: dict | None = None,
    ) -> np.ndarray:
        """Membaca IQ sample melalui proses worker terisolasi."""

        timeout = (
            self._acquire_timeout_seconds
            if timeout_seconds is None
            else float(timeout_seconds)
        )

        acquire_started_ns = perf_counter_ns() if metrics is not None else None
        command_wait_started_ns = (
            perf_counter_ns() if metrics is not None else None
        )
        with self._command_lock:
            if metrics is not None:
                metrics["command_lock_wait_ms"] = _ms_since(command_wait_started_ns)
            process, connection = self._start_worker(metrics=metrics)
            request_id = request_id or uuid4().hex

            try:
                command = {
                    "type": "acquire",
                    "request_id": request_id,
                    "num_samps": int(num_samps),
                    "center_frequency_hz": float(center_frequency_hz),
                    "sample_rate_hz": float(sample_rate_hz),
                }
                if metrics is not None:
                    command["benchmark_enabled"] = True
                    command["benchmark_context"] = benchmark_context or {}
                    send_started_ns = perf_counter_ns()
                connection.send(command)
                if metrics is not None:
                    metrics["pipe_command_send_ms"] = _ms_since(send_started_ns)

                result_message = self._wait_for_message(
                    process=process,
                    connection=connection,
                    timeout_seconds=timeout,
                    expected_type="result",
                    request_id=request_id,
                    metrics=metrics,
                )

                if not result_message.get("ok"):
                    raise UhdScannerError(
                        result_message.get("error")
                        or "The worker failed to read IQ samples."
                    )

                array_started_ns = perf_counter_ns() if metrics is not None else None
                result = np.asarray(result_message["samples"])
                if metrics is not None:
                    metrics["parent_result_array_ms"] = _ms_since(array_started_ns)
                    metrics.update(result_message.get("worker_timings_ms") or {})
                return result

            except BaseException:
                if self._detach_if_current(process, connection):
                    self._dispose_worker(
                        process,
                        connection,
                        force=True,
                    )
                raise
            finally:
                if metrics is not None:
                    metrics["manager_acquire_total_ms"] = _ms_since(
                        acquire_started_ns
                    )
