"""Isolasi akses UHD di proses terpisah dari FastAPI.

Tujuan utama modul ini adalah memastikan crash atau hang pada library native
UHD tidak menghentikan proses utama FastAPI. Satu worker dipakai selama satu
sesi scan dan dilepas ketika scan selesai, dihentikan, gagal, atau perangkat
USB terputus.
"""

from __future__ import annotations

from multiprocessing import get_context
from threading import Lock
from time import monotonic
from uuid import uuid4

import numpy as np
import uhd


class UhdScannerError(RuntimeError):
    """Kesalahan yang terjadi di scanner worker UHD."""


class UhdScannerTimeoutError(UhdScannerError):
    """Scanner worker tidak memberikan respons dalam batas waktu."""


def _safe_send(connection, payload: dict) -> None:
    """Mengirim payload tanpa membuat worker gagal saat parent sudah menutup."""

    try:
        connection.send(payload)
    except (BrokenPipeError, EOFError, OSError):
        pass


def _scanner_worker_main(connection, config: dict) -> None:
    """Entry point proses anak. Semua objek UHD hanya hidup di sini."""

    usrp_device = None

    try:
        try:
            usrp_device = uhd.usrp.MultiUSRP(
                f"serial={config['serial']}"
            )
            usrp_device.set_rx_antenna(
                config["rx_antenna"],
                config["channel"],
            )
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

            try:
                samples = usrp_device.recv_num_samps(
                    int(command["num_samps"]),
                    float(command["center_frequency_hz"]),
                    float(command["sample_rate_hz"]),
                    [int(config["channel"])],
                    float(config["gain_db"]),
                )

                iq_samples = np.asarray(samples[0]).copy()

                _safe_send(
                    connection,
                    {
                        "type": "result",
                        "request_id": request_id,
                        "ok": True,
                        "samples": iq_samples,
                    },
                )

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
    ) -> dict:
        deadline = monotonic() + timeout_seconds

        while monotonic() < deadline:
            if not process.is_alive():
                exit_code = process.exitcode
                raise UhdScannerError(
                    "Proses scanner UHD berhenti tiba-tiba"
                    + (
                        f" dengan exit code {exit_code}."
                        if exit_code is not None
                        else "."
                    )
                )

            try:
                has_message = connection.poll(0.1)
            except (EOFError, OSError) as error:
                raise UhdScannerError(
                    "Koneksi ke proses scanner UHD terputus."
                ) from error

            if not has_message:
                continue

            try:
                message = connection.recv()
            except (EOFError, OSError) as error:
                raise UhdScannerError(
                    "Proses scanner UHD menutup koneksi tanpa respons."
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
            "Proses scanner UHD tidak merespons dalam "
            f"{timeout_seconds:.0f} detik."
        )

    def _start_worker(self):
        existing_process, existing_connection = self._get_current_worker()

        if (
            existing_process is not None
            and existing_connection is not None
            and existing_process.is_alive()
        ):
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
                "USRP tidak dapat diinisialisasi."
            )
            if self._detach_if_current(process, parent_connection):
                self._dispose_worker(
                    process,
                    parent_connection,
                    force=True,
                )
            raise UhdScannerError(error_message)

        return process, parent_connection

    def acquire_samples(
        self,
        *,
        num_samps: int,
        center_frequency_hz: float,
        sample_rate_hz: float,
        timeout_seconds: float | None = None,
    ) -> np.ndarray:
        """Membaca IQ sample melalui proses worker terisolasi."""

        timeout = (
            self._acquire_timeout_seconds
            if timeout_seconds is None
            else float(timeout_seconds)
        )

        with self._command_lock:
            process, connection = self._start_worker()
            request_id = uuid4().hex

            try:
                connection.send(
                    {
                        "type": "acquire",
                        "request_id": request_id,
                        "num_samps": int(num_samps),
                        "center_frequency_hz": float(
                            center_frequency_hz
                        ),
                        "sample_rate_hz": float(sample_rate_hz),
                    }
                )

                result_message = self._wait_for_message(
                    process=process,
                    connection=connection,
                    timeout_seconds=timeout,
                    expected_type="result",
                    request_id=request_id,
                )

                if not result_message.get("ok"):
                    raise UhdScannerError(
                        result_message.get("error")
                        or "Worker gagal membaca IQ sample."
                    )

                return np.asarray(result_message["samples"])

            except BaseException:
                if self._detach_if_current(process, connection):
                    self._dispose_worker(
                        process,
                        connection,
                        force=True,
                    )
                raise
