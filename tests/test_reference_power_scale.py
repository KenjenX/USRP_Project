"""Offline formula and integration tests for the C++ reference power scale."""

import os
import unittest
from unittest.mock import patch

import numpy as np

from backend import main


class ReferencePowerFormulaTests(unittest.TestCase):
    def test_norm_and_scalar_formula_match_reference_expression(self):
        for size in (1, 8, 1024):
            self.assertEqual(main.reference_power_norm(size), 1.0 / (size * size))
        raw_power = np.array([0.0, 1.0, 12.5, 1e8])
        actual = main.reference_display_power_from_raw(raw_power, 8)
        expected = (10 * np.log10(raw_power / 64 + 1e-15) - 76) * 0.846 + 5
        np.testing.assert_allclose(actual, expected)
        self.assertTrue(np.all(np.isfinite(actual)))
        self.assertAlmostEqual(actual[0], (10 * np.log10(1e-15) - 76) * .846 + 5)

    def test_invalid_sizes_negative_raw_and_round_trip(self):
        for size in (0, -1):
            with self.assertRaises(ValueError):
                main.reference_power_norm(size)
        with self.assertRaises(ValueError):
            main.reference_display_power_from_raw([-1.0], 8)
        for threshold in (-120, -100, -80, -60, -40, 0):
            raw = main.reference_threshold_to_raw_power(threshold, 1024)
            actual = float(main.reference_display_power_from_raw(raw, 1024))
            # The forward transform adds 1e-15, while the inverse does not
            # remove it. Tiny low-threshold differences are expected, but this
            # absolute tolerance remains far too small to hide formula errors.
            self.assertLessEqual(abs(actual - threshold), 1e-6)
        for value in (float("nan"), float("inf"), -float("inf")):
            with self.assertRaises(ValueError):
                main.reference_threshold_to_raw_power(value, 8)

    def test_raw_comparison_is_strict(self):
        threshold = -80.0
        raw = main.reference_threshold_to_raw_power(threshold, 16)
        frequencies = np.array([1.0, 2.0])
        displays = main.reference_display_power_from_raw(
            np.array([raw, raw * (1.0 + 1e-8)]), 16
        )
        detections = main.build_detections_from_threshold_points(
            frequency_axis_mhz=frequencies, power_db=displays,
            threshold_db=threshold, window_start_mhz=1, window_end_mhz=2,
            window_index=1, raw_power=np.array([raw, raw * (1.0 + 1e-8)]),
            raw_threshold=raw,
        )
        self.assertEqual([item["fft_index"] for item in detections], [1])


class ReferenceHannTests(unittest.TestCase):
    def test_symmetric_reference_hann_is_bounded_and_cached(self):
        with main._hann_window_cache_lock:
            main._hann_window_cache.clear()
        first = main.get_reference_hann_window(8)
        second = main.get_reference_hann_window(8)
        expected = .5 * (1 - np.cos(2 * np.pi * np.arange(8) / 7))
        self.assertIs(first, second)
        self.assertEqual(len(first), 8)
        self.assertEqual(first[0], 0.0)
        self.assertEqual(first[-1], 0.0)
        np.testing.assert_allclose(first, expected)
        third = main.get_reference_hann_window(16)
        self.assertIsNot(first, third)
        self.assertEqual(len(third), 16)
        for size in range(2, 16):
            main.get_reference_hann_window(size)
        self.assertLessEqual(len(main._hann_window_cache), main._HANN_WINDOW_CACHE_MAX_ENTRIES)


class ReferencePipelineTests(unittest.TestCase):
    def setUp(self):
        self.original_manager = main.scanner_manager

    def tearDown(self):
        main.scanner_manager = self.original_manager

    def _scan(self, enabled):
        count = 16
        # A bin-centred tone produces a clear raw-power peak without hardware.
        samples = np.exp(2j * np.pi * 3 * np.arange(count) / count).astype(np.complex64)

        class FakeManager:
            def acquire_samples(self, **_kwargs):
                return samples

        main.scanner_manager = FakeManager()
        with patch.dict(os.environ, {"USRP_REFERENCE_POWER_SCALE_ENABLED": enabled}):
            return main.scan_frequency_window(
                window_start_mhz=50, window_end_mhz=66, threshold_db=-80,
                window_index=1, channel_targets=[{
                    "channel_id": 1, "channel_number": "x", "side": "DL",
                    "target_frequency_mhz": 53.0,
                }], metrics={},
            )

    def test_reference_pipeline_keeps_arrays_aligned_and_uses_display_power(self):
        result = self._scan("on")
        frequency = result["spectrum"]["frequency_mhz"]
        power = result["spectrum"]["power_db"]
        self.assertEqual(len(frequency), len(power))
        self.assertEqual(frequency, sorted(frequency))
        self.assertTrue(all(50 <= value <= 66 for value in frequency))
        peak_index = int(np.argmax(power))
        self.assertEqual(result["peak"]["frequency_mhz"], frequency[peak_index])
        self.assertEqual(result["peak"]["power_db"], power[peak_index])
        self.assertEqual(result["channel_measurements"][0]["power_db"], power[3])
        samples = np.exp(2j * np.pi * 3 * np.arange(16) / 16).astype(np.complex64)
        raw = np.fft.fftshift(np.fft.fft(samples * np.hanning(16)))
        raw = raw.real * raw.real + raw.imag * raw.imag
        raw_threshold = main.reference_threshold_to_raw_power(-80, 16)
        expected_indexes = np.where(raw > raw_threshold)[0].tolist()
        self.assertEqual(
            [item["fft_index"] for item in result["detections"]], expected_indexes
        )
        for item in result["detections"]:
            self.assertEqual(item["power_db"], power[item["fft_index"]])
        self.assertGreater(max(power) - min(power), 1.0)  # no per-window max normalization

    def test_legacy_flag_preserves_prior_formula(self):
        result = self._scan("off")
        samples = np.exp(2j * np.pi * 3 * np.arange(16) / 16).astype(np.complex64)
        expected = 20 * np.log10(np.abs(np.fft.fftshift(np.fft.fft(samples * np.hanning(16)))) + 1e-12)
        np.testing.assert_allclose(result["spectrum"]["power_db"], expected)

    def test_flag_spellings_and_invalid_value(self):
        for value in ("1", "true", "yes", "on", "TRUE"):
            self.assertTrue(main._parse_reference_power_scale_enabled(value))
        for value in ("0", "false", "no", "off", "FALSE"):
            self.assertFalse(main._parse_reference_power_scale_enabled(value))
        with self.assertRaisesRegex(RuntimeError, "USRP_REFERENCE_POWER_SCALE_ENABLED"):
            main._parse_reference_power_scale_enabled("maybe")


if __name__ == "__main__":
    unittest.main()
