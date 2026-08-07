"""No-hardware lifecycle regression tests for the autonomous sweep controller."""
import asyncio
import os
import unittest
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

import backend.main as main


class DummyManager:
    def __init__(self, raises=False):
        self.calls = []
        self.raises = raises

    def release(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if self.raises:
            raise RuntimeError("forced release failed")


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.original_state = deepcopy(main.scan_state)
        self.original_manager = main.scanner_manager
        self.original_controller = (
            main.controller_thread, main.controller_session_id,
            main.controller_stop_event,
        )
        self.original_usb_state = deepcopy(main.usb_device_state)
        main.benchmark_sessions.clear()
        main.usb_device_state.clear()
        main.usb_device_state.update(deepcopy(self.original_usb_state))
        main.scan_state.update(deepcopy(self.original_state))
        main.controller_thread = None
        main.controller_session_id = None
        main.controller_stop_event = None

    def tearDown(self):
        main.scan_state.clear()
        main.scan_state.update(self.original_state)
        main.scanner_manager = self.original_manager
        (main.controller_thread, main.controller_session_id,
         main.controller_stop_event) = self.original_controller
        main.benchmark_sessions.clear()
        main.usb_device_state.clear()
        main.usb_device_state.update(self.original_usb_state)

    def _active(self, session="s1"):
        main.scan_state.update({"running": True, "completed": False,
                                "session_id": session, "scan_owner": "general"})
        main.controller_session_id = session
        main.controller_stop_event = main.Event()

    @staticmethod
    def _window_result():
        return {
            "window": {"window_index": 1, "start_frequency_mhz": 50.0,
                       "end_frequency_mhz": 56.0, "sample_count": 1},
            "spectrum": {"frequency_mhz": [50.0], "power_db": [-20.0]},
            "peak": {"frequency_mhz": 50.0, "power_db": -20.0},
            "detections": [], "channel_measurements": [],
        }

    def _one_window_controller_state(self, session="s1"):
        self._active(session)
        config = deepcopy(main.default_config)
        config.update({"start_frequency_mhz": 50.0, "end_frequency_mhz": 56.0,
                       "threshold_db": 0.0})
        main.scan_state.update({
            "config": config, "specific_channel_targets": [],
            "channel_measurements": {}, "detections": [],
            "detections_by_window": {}, "channel_measurements_by_window": {},
            "last_window_detections": [], "latest_window_snapshot": None,
            "spectrum_preview": main.create_empty_spectrum_preview(),
            "last_peak": None,
            "sweep": {"current_start_mhz": 50.0, "current_end_mhz": 56.0,
                      "last_window_start_mhz": None, "last_window_end_mhz": None,
                      "total_windows": 1, "scanned_windows": 0,
                      "progress_percent": 0.0},
            "cycle_index": 1, "completed_cycles": 0,
            "cycle_window_index": 0, "cycle_total_windows": 1,
            "cycle_progress_percent": 0.0, "last_completed_cycle_at": None,
        })

    def test_stop_before_error_commit_skips_error_transition(self):
        self._active()
        main.controller_stop_event.set()
        result = main.release_scan_lock_after_error("s1", "acquisition failed")
        self.assertFalse(result["transitioned"])
        self.assertTrue(main.scan_state["running"])
        self.assertIsNone(main.scan_state["last_error"])

    def test_disconnect_then_acquisition_exception_preserves_disconnect(self):
        self._active()
        main.scanner_manager = DummyManager()
        with patch.object(main, "_signal_controller_stop"):
            main.update_usb_device_state({"status": "disconnected", "checked_at": "now"})
        result = main.release_scan_lock_after_error("s1", "released worker")
        self.assertFalse(result["transitioned"])
        self.assertIn("connection was lost", main.scan_state["last_error"])

    def test_completed_stop_preserves_terminal_benchmark(self):
        self._active()
        main.scan_state.update({"running": False, "completed": True})
        with patch.object(main, "discard_benchmark_session") as discard:
            response = main.stop_scan(main.StopScanRequest(scan_owner="general"))
        self.assertTrue(response["completed"])
        discard.assert_not_called()

    def test_stale_controller_cannot_mutate_new_session(self):
        self._active("new")
        result = main.release_scan_lock_after_error("old", "stale")
        self.assertFalse(result["transitioned"])
        self.assertTrue(main.scan_state["running"])

    def test_duplicate_start_is_rejected_while_old_controller_lives(self):
        request = main.ScanRequest(start_frequency_mhz=50, end_frequency_mhz=56,
                                   threshold_db=0, scan_owner="general")
        with patch.object(main, "get_usb_device_state", return_value={"connected": True}), \
             patch.object(main, "_controller_is_active", return_value=True):
            with self.assertRaises(main.HTTPException) as error:
                main.start_scan(request)
        self.assertEqual(error.exception.status_code, 409)

    def test_thread_start_failure_restores_inactive_state(self):
        class BrokenThread:
            def __init__(self, *args, **kwargs):
                pass
            def start(self):
                raise RuntimeError("cannot start")
            def is_alive(self):
                return False
        request = main.ScanRequest(start_frequency_mhz=50, end_frequency_mhz=56,
                                   threshold_db=0, scan_owner="general")
        main.scanner_manager = DummyManager()
        with patch.object(main, "get_usb_device_state", return_value={"connected": True}), \
             patch.object(main, "Thread", BrokenThread):
            with self.assertRaises(RuntimeError):
                main.start_scan(request)
        self.assertFalse(main.scan_state["running"])
        self.assertIsNone(main.scan_state["session_id"])
        self.assertIsNone(main.scan_state["scan_owner"])

    def test_shutdown_continues_when_release_raises(self):
        self._active()
        main.scanner_manager = DummyManager(raises=True)
        with patch.object(main, "stop_usb_detector"), patch.object(main, "_join_controller") as join, \
             patch.object(main, "discard_benchmark_session") as discard:
            asyncio.run(main.app_shutdown())
        join.assert_called_once_with("s1")
        discard.assert_called_once_with("s1", "application_shutdown")

    def test_benchmark_has_one_terminal_event(self):
        old = os.environ.get("USRP_BENCHMARK_ENABLED")
        os.environ["USRP_BENCHMARK_ENABLED"] = "1"
        try:
            self._active()
            main.create_benchmark_session(main.scan_state)
            with patch.object(main, "safe_benchmark_log") as log:
                self.assertTrue(main.discard_benchmark_session("s1", "stop"))
                self.assertFalse(main.discard_benchmark_session("s1", "again"))
            self.assertEqual(log.call_count, 1)
        finally:
            if old is None:
                os.environ.pop("USRP_BENCHMARK_ENABLED", None)
            else:
                os.environ["USRP_BENCHMARK_ENABLED"] = old

    def test_autonomous_summary_uses_controller_active_time(self):
        old = os.environ.get("USRP_BENCHMARK_ENABLED")
        os.environ["USRP_BENCHMARK_ENABLED"] = "1"
        try:
            self._active()
            main.create_benchmark_session(main.scan_state)
            with main.benchmark_lock:
                session = main.benchmark_sessions["s1"]
                session["completed"] = True
                session["summary_emitted"] = True
                session["windows"] = [{"window_index": 1, "sample_count": 1,
                    "detection_count": 0, "response_bytes": 0,
                    "timings_ms": {"controller_window_active_ms": 12.5}}]
            with patch.object(main, "safe_benchmark_log") as log:
                main.emit_benchmark_summary("s1")
            self.assertEqual(log.call_args.args[1]["active_pipeline_total_ms"], 12.5)
        finally:
            if old is None:
                os.environ.pop("USRP_BENCHMARK_ENABLED", None)
            else:
                os.environ["USRP_BENCHMARK_ENABLED"] = old

    def test_real_scan_frequency_window_returns_complete_dsp_result_without_uhd(self):
        class FakeScannerManager:
            def acquire_samples(self, **kwargs):
                self.kwargs = kwargs
                return np.exp(2j * np.pi * np.arange(64) / 8)

        fake_manager = FakeScannerManager()
        main.scanner_manager = fake_manager
        metrics = {}
        result = main.scan_frequency_window(
            window_start_mhz=50.0,
            window_end_mhz=56.0,
            threshold_db=-1000.0,
            window_index=1,
            metrics=metrics,
        )
        self.assertIsInstance(result, dict)
        self.assertEqual(fake_manager.kwargs["num_samps"], main.NUM_SAMPS)
        self.assertTrue(result["spectrum"]["frequency_mhz"])
        self.assertTrue(result["spectrum"]["power_db"])
        self.assertEqual(
            len(result["detections"]), metrics["threshold_bin_count"]
        )
        self.assertEqual(
            result["window"]["threshold_point_count"], len(result["detections"])
        )
        self.assertIn("fft_ms", metrics)

    def test_continuous_summary_sums_two_controller_windows(self):
        old = os.environ.get("USRP_BENCHMARK_ENABLED")
        os.environ["USRP_BENCHMARK_ENABLED"] = "1"
        try:
            self._active()
            main.create_benchmark_session(main.scan_state)
            with main.benchmark_lock:
                session = main.benchmark_sessions["s1"]
                session["windows"] = [
                    {"window_index": 1, "sample_count": 2, "detection_count": 0,
                     "response_bytes": 0, "timings_ms": {"controller_window_active_ms": 12.5}},
                    {"window_index": 1, "sample_count": 3, "detection_count": 0,
                     "response_bytes": 0, "timings_ms": {"controller_window_active_ms": 7.5}},
                ]
            with patch.object(main, "safe_benchmark_log") as log:
                main.emit_benchmark_summary(
                    "s1", terminal_event="continuous_sweep_summary",
                    continuous_state=main.scan_state,
                )
            summary = log.call_args.args[1]
            self.assertEqual(summary["active_pipeline_metric"], "controller_window_active_ms")
            self.assertEqual(summary["active_pipeline_total_ms"], 20.0)
            self.assertEqual(summary["window_sequence_gap_count"], 0)
        finally:
            if old is None:
                os.environ.pop("USRP_BENCHMARK_ENABLED", None)
            else:
                os.environ["USRP_BENCHMARK_ENABLED"] = old

    def test_cycle_summary_does_not_claim_continuous_session(self):
        old = os.environ.get("USRP_BENCHMARK_ENABLED")
        os.environ["USRP_BENCHMARK_ENABLED"] = "1"
        try:
            self._active()
            main.create_benchmark_session(main.scan_state)
            with patch.object(main, "safe_benchmark_log") as log:
                main._record_benchmark_cycle_summary(
                    "s1", 1, [{"window_index": 1, "detection_count": 0,
                                "total_windows": 1}], main.perf_counter_ns(),
                )
            self.assertEqual(log.call_args.args[1]["event"], "sweep_cycle_summary")
            self.assertIn("s1", main.benchmark_sessions)
            self.assertIsNone(main.benchmark_sessions["s1"]["terminal_outcome"])
        finally:
            if old is None:
                os.environ.pop("USRP_BENCHMARK_ENABLED", None)
            else:
                os.environ["USRP_BENCHMARK_ENABLED"] = old

    def test_manual_stop_emits_one_continuous_summary_not_abort(self):
        old = os.environ.get("USRP_BENCHMARK_ENABLED")
        os.environ["USRP_BENCHMARK_ENABLED"] = "1"
        try:
            self._one_window_controller_state()
            main.scanner_manager = DummyManager()
            main.create_benchmark_session(main.scan_state)
            with patch.object(main, "safe_benchmark_log") as log:
                main.stop_scan(main.StopScanRequest(scan_owner="general"))
                main.discard_benchmark_session("s1", "late_stop")
            events = [call.args[1]["event"] for call in log.call_args_list]
            self.assertEqual(events, ["continuous_sweep_summary"])
            self.assertNotIn("sweep_aborted", events)
        finally:
            if old is None:
                os.environ.pop("USRP_BENCHMARK_ENABLED", None)
            else:
                os.environ["USRP_BENCHMARK_ENABLED"] = old

    def test_summary_failure_does_not_skip_manual_stop_release(self):
        self._one_window_controller_state()
        main.scanner_manager = DummyManager()
        with patch.object(main, "emit_benchmark_summary", side_effect=RuntimeError("log failed")):
            response = main.stop_scan(main.StopScanRequest(scan_owner="general"))
        self.assertFalse(response["running"])
        self.assertEqual(len(main.scanner_manager.calls), 1)

    def test_spectrum_is_read_only(self):
        with patch.object(main, "scan_frequency_window", side_effect=AssertionError):
            response = main.get_spectrum(SimpleNamespace(state=SimpleNamespace()))
        self.assertIn("spectrum", response)

    def test_stop_does_not_depend_on_scan_history_persistence(self):
        self._one_window_controller_state()
        main.scanner_manager = DummyManager()
        response = main.stop_scan(main.StopScanRequest(scan_owner="general"))
        self.assertFalse(response["running"])
        self.assertEqual(len(main.scanner_manager.calls), 1)
        self.assertFalse(hasattr(main, "SCAN_HISTORY_DIR"))
        self.assertFalse(hasattr(main, "save_scan_session_payload"))
        self.assertFalse(hasattr(main, "save_completed_session_if_needed_locked"))
        self.assertFalse(
            any(
                getattr(route, "path", "").startswith("/api/scan/history")
                for route in main.app.routes
            )
        )

    def test_stop_immediately_before_commit_discards_result_and_aborts_once(self):
        old = os.environ.get("USRP_BENCHMARK_ENABLED")
        os.environ["USRP_BENCHMARK_ENABLED"] = "1"
        try:
            self._one_window_controller_state()
            main.create_benchmark_session(main.scan_state)
            main.controller_stop_event.set()
            committed, completed, _ = main._commit_autonomous_window(
                "s1", main.controller_stop_event, self._window_result(), 50.0, 56.0,
                1, 56.0, {},
            )
            with patch.object(main, "safe_benchmark_log") as log:
                main.discard_benchmark_session("s1", "manual_stop")
            self.assertFalse(committed)
            self.assertFalse(completed)
            self.assertIsNone(main.scan_state["latest_window_snapshot"])
            self.assertEqual(log.call_args.args[1]["event"], "sweep_aborted")
        finally:
            if old is None:
                os.environ.pop("USRP_BENCHMARK_ENABLED", None)
            else:
                os.environ["USRP_BENCHMARK_ENABLED"] = old

    def test_stop_after_final_commit_preserves_pending_summary(self):
        old = os.environ.get("USRP_BENCHMARK_ENABLED")
        os.environ["USRP_BENCHMARK_ENABLED"] = "1"
        try:
            self._one_window_controller_state()
            main.create_benchmark_session(main.scan_state)
            committed, completed, total = main._commit_autonomous_window(
                "s1", main.controller_stop_event, self._window_result(), 50.0,
                56.0, 1, 56.0, {"controller_window_active_ms": 1.0},
            )
            response = main.stop_scan(main.StopScanRequest(scan_owner="general"))
            context = {
                "session_id": "s1", "request_id": "r1", "scan_owner": "general",
                "window_index": 1, "total_windows": 1, "window_start_mhz": 50.0,
                "window_end_mhz": 56.0, "sample_count": 1, "threshold_bin_count": 0,
                "detection_count": 0, "cumulative_detection_count": total,
                "channel_measurement_count": 0, "threshold_detection_invariant_ok": True,
                "timings_ms": {"controller_window_active_ms": 1.0},
            }
            with patch.object(main, "safe_benchmark_log") as log:
                main._record_autonomous_window(context, completed)
            events = [call.args[1]["event"] for call in log.call_args_list]
            self.assertTrue(committed)
            self.assertFalse(response["completed"])
            self.assertEqual(events.count("sweep_summary"), 0)
            self.assertNotIn("sweep_aborted", events)
        finally:
            if old is None:
                os.environ.pop("USRP_BENCHMARK_ENABLED", None)
            else:
                os.environ["USRP_BENCHMARK_ENABLED"] = old

    def test_forced_release_during_startup_exception_is_treated_as_stop(self):
        self._one_window_controller_state()
        main.scanner_manager = DummyManager()
        snapshot = {
            "session_id": "s1", "scan_owner": "general",
            "config": deepcopy(main.scan_state["config"]), "range_start_mhz": 50.0,
            "range_end_mhz": 56.0, "total_windows": 1,
            "specific_channel_targets": [], "controller_started_ns": main.perf_counter_ns(),
        }
        def stopped_startup(**_kwargs):
            main.stop_scan(main.StopScanRequest(scan_owner="general"))
            raise RuntimeError("worker startup was force-released")
        with patch.object(main, "scan_frequency_window", side_effect=stopped_startup):
            main._run_autonomous_single_sweep(snapshot, main.controller_stop_event)
        self.assertFalse(main.scan_state["running"])
        self.assertIsNone(main.scan_state["last_error"])
        self.assertEqual(len(main.scanner_manager.calls), 1)
        self.assertIsNone(main.controller_session_id)

    def test_disconnect_during_startup_exception_preserves_disconnect_state(self):
        self._one_window_controller_state()
        main.scanner_manager = DummyManager()
        main.usb_device_state.update({"status": "connected", "connected": True})
        snapshot = {
            "session_id": "s1", "scan_owner": "general",
            "config": deepcopy(main.scan_state["config"]), "range_start_mhz": 50.0,
            "range_end_mhz": 56.0, "total_windows": 1,
            "specific_channel_targets": [], "controller_started_ns": main.perf_counter_ns(),
        }
        def disconnected_startup(**_kwargs):
            main.update_usb_device_state({"status": "disconnected", "checked_at": "now"})
            raise RuntimeError("worker startup was force-released")
        with patch.object(main, "scan_frequency_window", side_effect=disconnected_startup):
            main._run_autonomous_single_sweep(snapshot, main.controller_stop_event)
        self.assertFalse(main.scan_state["running"])
        self.assertIn("connection was lost", main.scan_state["last_error"])
        self.assertIsNone(main.controller_session_id)

    def test_completed_cycle_rolls_without_releasing_worker(self):
        self._one_window_controller_state()
        main.scanner_manager = DummyManager()
        snapshot = {
            "session_id": "s1", "scan_owner": "general",
            "config": deepcopy(main.scan_state["config"]), "range_start_mhz": 50.0,
            "range_end_mhz": 56.0, "total_windows": 1,
            "specific_channel_targets": [], "controller_started_ns": main.perf_counter_ns(),
        }
        calls = 0
        def second_cycle_stops(**_kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                main.controller_stop_event.set()
            return self._window_result()
        with patch.object(main, "scan_frequency_window", side_effect=second_cycle_stops):
            main._run_autonomous_single_sweep(snapshot, main.controller_stop_event)
        self.assertEqual(calls, 2)
        self.assertTrue(main.scan_state["running"])
        self.assertFalse(main.scan_state["completed"])
        self.assertEqual(main.scan_state["completed_cycles"], 1)
        self.assertEqual(main.scan_state["cycle_index"], 2)
        self.assertEqual(main.scan_state["cycle_window_index"], 0)
        self.assertEqual(main.scanner_manager.calls, [])

    def test_rolling_detection_replacement_and_ordering(self):
        self._one_window_controller_state()
        old = self._window_result()
        old["detections"] = [
            {"frequency_mhz": 55.0, "power_db": 1.0},
            {"frequency_mhz": 51.0, "power_db": 1.0},
        ]
        new = self._window_result()
        new["detections"] = [{"frequency_mhz": 52.0, "power_db": 2.0}]
        main._commit_autonomous_window("s1", main.controller_stop_event, old, 50, 56, 1, 56, None)
        main._commit_autonomous_window("s1", main.controller_stop_event, new, 50, 56, 1, 56, None)
        self.assertEqual(len(main.scan_state["detections"]), 1)
        self.assertEqual(main.scan_state["detections"][0]["frequency_mhz"], 52.0)
        empty = self._window_result()
        main._commit_autonomous_window("s1", main.controller_stop_event, empty, 50, 56, 1, 56, None)
        self.assertEqual(main.scan_state["detections"], [])

    def test_preview_segment_replacement_keeps_one_segment_per_window(self):
        preview = main.create_empty_spectrum_preview()
        main.replace_spectrum_preview_window(
            preview, 1, {"frequency_mhz": [50.0], "power_db": [-20.0]}, 2
        )
        main.replace_spectrum_preview_window(
            preview, 1, {"frequency_mhz": [50.0], "power_db": [-30.0]}, 2
        )
        main.replace_spectrum_preview_window(
            preview, 2, {"frequency_mhz": [56.0], "power_db": [-40.0]}, 2
        )
        state = {"spectrum_preview": preview, "config": main.default_config}
        finalized = main.finalize_spectrum_preview(state)
        self.assertEqual(len(preview["segments"]), 2)
        self.assertEqual(finalized["frequency_mhz"], [50.0, 56.0])
        self.assertEqual(finalized["power_db"], [-30.0, -40.0])


if __name__ == "__main__":
    unittest.main()
