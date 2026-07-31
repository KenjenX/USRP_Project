"""No-hardware checks for the C++ reference fast-acquisition contract."""

import types
import unittest
from unittest.mock import patch

import numpy as np

from backend import main
from backend import scanner_worker


class ReferencePlanTests(unittest.TestCase):
    def test_golden_vectors(self):
        rate, centers = main.build_reference_hop_plan(50, 106)
        self.assertEqual(rate, 20.0)
        self.assertEqual(centers, (60.0, 80.0, 100.0))
        rate, centers = main.build_reference_hop_plan(50, 6000)
        self.assertEqual(rate, 56.0)
        self.assertEqual(len(centers), 107)
        self.assertEqual((centers[0], centers[-1]), (78.0, 6014.0))
        self.assertEqual(main.build_reference_hop_plan(50, 150), (56.0, (78.0, 134.0)))
        self.assertEqual(main.build_reference_hop_plan(100, 110), (20.0, (105.0,)))

    def test_invalid_and_immutable_repeat_plan(self):
        for invalid in ((100, 100), (float("nan"), 110), (100, float("inf"))):
            with self.assertRaises(ValueError):
                main.build_reference_hop_plan(*invalid)
        first = main.build_reference_hop_plan(50, 6000)
        self.assertEqual(first, main.build_reference_hop_plan(50, 6000))
        self.assertIsInstance(first[1], tuple)

    def test_final_capture_is_cropped_to_requested_output_range(self):
        class FakeManager:
            def acquire_samples(self, **_kwargs):
                return np.ones(8, dtype=np.complex64)

        original_manager = main.scanner_manager
        main.scanner_manager = FakeManager()
        try:
            result = main.scan_frequency_window(
                window_start_mhz=5986.0,
                window_end_mhz=6000.0,
                acquisition_center_mhz=6014.0,
                acquisition_sample_rate_mhz=56.0,
                threshold_db=999.0,
                window_index=107,
            )
        finally:
            main.scanner_manager = original_manager
        self.assertTrue(all(5986.0 <= value <= 6000.0 for value in result["spectrum"]["frequency_mhz"]))
        self.assertTrue(all(5986.0 <= item["frequency_mhz"] <= 6000.0 for item in result["detections"]))


class _FakeMetadata:
    def __init__(self):
        self.error_code = "none"
        self.message = "no error"

    def strerror(self):
        return self.message


class _FakeStreamArgs:
    def __init__(self, cpu, wire):
        self.cpu = cpu
        self.wire = wire
        self.channels = []


class _FakeCommand:
    def __init__(self, mode):
        self.mode = mode
        self.num_samps = 0
        self.stream_now = False


class _FakeStreamer:
    def __init__(self):
        self.commands = []
        self.buffers = []
        self.next_count = None
        self.next_error = "none"
        self.timeouts = []

    def issue_stream_cmd(self, command):
        self.commands.append(command)

    def recv(self, buffer, metadata, timeout):
        if buffer.ndim != 2 or buffer.shape[0] != 1:
            raise AssertionError("UHD RX buffer must have shape (1, N)")
        self.buffers.append(buffer)
        self.timeouts.append(timeout)
        buffer[0, :] = np.arange(buffer.shape[1], dtype=np.float32) + 1j
        metadata.error_code = self.next_error
        metadata.message = "simulated metadata failure"
        return buffer.shape[1] if self.next_count is None else self.next_count


class _FakeUsrp:
    def __init__(self):
        self.calls = []
        self.streamers = []

    def set_master_clock_rate(self, value): self.calls.append(("clock", value))
    def set_rx_rate(self, value, channel): self.calls.append(("rate", value, channel))
    def set_rx_gain(self, value, channel): self.calls.append(("gain", value, channel))
    def set_rx_antenna(self, value, channel): self.calls.append(("antenna", value, channel))
    def set_rx_freq(self, value, channel): self.calls.append(("freq", value, channel))
    def get_rx_stream(self, args):
        self.calls.append(("stream", args.cpu, args.wire, args.channels))
        streamer = _FakeStreamer()
        self.streamers.append(streamer)
        return streamer


class ExplicitStreamerTests(unittest.TestCase):
    def setUp(self):
        self.fake_uhd = types.SimpleNamespace(
            usrp=types.SimpleNamespace(StreamArgs=_FakeStreamArgs),
            types=types.SimpleNamespace(
                RXMetadata=_FakeMetadata,
                RXMetadataErrorCode=types.SimpleNamespace(none="none"),
                StreamCMD=_FakeCommand,
                StreamMode=types.SimpleNamespace(num_done="num_done"),
            ),
        )
        self.usrp = _FakeUsrp()
        self.config = {"channel": 1, "gain_db": 35, "rx_antenna": "RX2"}

    def test_reuses_streamer_buffer_and_exact_reference_command(self):
        with patch.object(scanner_worker, "uhd", self.fake_uhd), patch.object(scanner_worker, "sleep") as sleep:
            acquirer = scanner_worker._PersistentRxAcquirer(self.usrp, self.config)
            first = acquirer.acquire(num_samps=8, center_frequency_hz=60e6, sample_rate_hz=20e6)
            second = acquirer.acquire(num_samps=8, center_frequency_hz=80e6, sample_rate_hz=20e6)
        self.assertEqual(len(self.usrp.streamers), 1)
        self.assertIn(("stream", "fc32", "sc16", [1]), self.usrp.calls)
        self.assertEqual([call[0] for call in self.usrp.calls].count("rate"), 1)
        self.assertEqual([call[0] for call in self.usrp.calls].count("gain"), 1)
        self.assertEqual([call[0] for call in self.usrp.calls].count("antenna"), 1)
        self.assertEqual([call[0] for call in self.usrp.calls].count("freq"), 2)
        self.assertEqual(sleep.call_count, 2)
        sleep.assert_any_call(0.002)
        streamer = self.usrp.streamers[0]
        self.assertEqual(len(streamer.commands), 2)
        self.assertTrue(all(command.num_samps == 8 and command.stream_now for command in streamer.commands))
        self.assertTrue(all(command.mode == "num_done" for command in streamer.commands))
        self.assertFalse(hasattr(self.fake_uhd.types.StreamMode, "num_samps_and_done"))
        self.assertEqual(streamer.timeouts, [0.1, 0.1])
        self.assertIs(streamer.buffers[0], streamer.buffers[1])
        self.assertEqual(streamer.buffers[0].shape, (1, 8))
        self.assertEqual(first.shape, (8,))
        self.assertEqual(first.dtype, np.complex64)
        self.assertIsNot(first, streamer.buffers[0])
        self.assertIsNot(second, streamer.buffers[0])
        self.assertFalse(np.shares_memory(first, streamer.buffers[0]))
        self.assertFalse(np.shares_memory(second, streamer.buffers[0]))

    def test_failures_do_not_return_stale_data_and_rate_change_recreates(self):
        with patch.object(scanner_worker, "uhd", self.fake_uhd), patch.object(scanner_worker, "sleep"):
            acquirer = scanner_worker._PersistentRxAcquirer(self.usrp, self.config)
            acquirer.acquire(num_samps=4, center_frequency_hz=60e6, sample_rate_hz=20e6)
            self.usrp.streamers[0].next_count = 3
            with self.assertRaisesRegex(scanner_worker.UhdAcquisitionError, "short receive"):
                acquirer.acquire(num_samps=4, center_frequency_hz=80e6, sample_rate_hz=20e6)
            self.usrp.streamers[0].next_count = None
            self.usrp.streamers[0].next_error = "overflow"
            with self.assertRaisesRegex(
                scanner_worker.UhdAcquisitionError,
                "metadata error code=overflow; message=simulated metadata failure; received=4; expected=4; backend=explicit_streamer",
            ):
                acquirer.acquire(num_samps=4, center_frequency_hz=100e6, sample_rate_hz=20e6)
            acquirer.acquire(num_samps=4, center_frequency_hz=150e6, sample_rate_hz=56e6)
            self.assertEqual(len(self.usrp.streamers), 2)
            acquirer.clear()
            self.assertIsNone(acquirer._streamer)
            self.assertIsNone(acquirer._buffer)

    def test_metadata_diagnostic_handles_property_and_failing_callable(self):
        with patch.object(scanner_worker, "uhd", self.fake_uhd):
            property_metadata = types.SimpleNamespace(
                error_code="overflow", strerror="property diagnostic"
            )
            result = scanner_worker._PersistentRxAcquirer._metadata_error(
                property_metadata, received=1, expected=4, backend="explicit_streamer"
            )
            self.assertIn("property diagnostic", result)

            def broken_strerror():
                raise RuntimeError("boom")

            broken_metadata = types.SimpleNamespace(
                error_code="overflow", strerror=broken_strerror
            )
            result = scanner_worker._PersistentRxAcquirer._metadata_error(
                broken_metadata, received=1, expected=4, backend="explicit_streamer"
            )
            self.assertIn("strerror() failed: RuntimeError: boom", result)

    def test_flag_parser(self):
        self.assertTrue(scanner_worker._parse_explicit_streamer_enabled(None))
        self.assertTrue(scanner_worker._parse_explicit_streamer_enabled("YES"))
        self.assertFalse(scanner_worker._parse_explicit_streamer_enabled("off"))
        with self.assertRaises(RuntimeError):
            scanner_worker._parse_explicit_streamer_enabled("sometimes")

    def test_legacy_flag_contract(self):
        self.assertEqual(
            scanner_worker._acquisition_backend_name(False),
            "legacy_recv_num_samps",
        )
        self.assertEqual(
            scanner_worker._acquisition_backend_name(True),
            "explicit_streamer",
        )


class InstalledUhdCompatibilityTests(unittest.TestCase):
    def test_required_uhd_410_types_exist_without_device_creation(self):
        # Importing the package and inspecting these symbols must not create a
        # MultiUSRP or trigger device discovery.
        import uhd

        self.assertTrue(hasattr(uhd.types.StreamMode, "num_done"))
        self.assertTrue(hasattr(uhd.usrp, "StreamArgs"))
        self.assertTrue(hasattr(uhd.types, "RXMetadata"))
        self.assertTrue(hasattr(uhd.types, "StreamCMD"))


if __name__ == "__main__":
    unittest.main()
