import { useEffect, useMemo, useRef, useState } from "react";
import "./App.css";

const API_BASE_URL = "http://127.0.0.1:8000";

const SPECTRUM_REFRESH_MS = 250;

// Jumlah window history yang disimpan di frontend.
// Scan 50–6000 MHz dengan window 56 MHz butuh sekitar 107 window,
// jadi 160 masih cukup aman untuk satu sweep penuh.
const MAX_SPECTRUM_HISTORY_WINDOWS = 160;

const CHART_SVG_HEIGHT = 260;
const CHART_TICK_STEP_DB = 10;
const THRESHOLD_TARGET_TOP_RATIO = 1 / 3;

// Batas bawah display dibuat tetap agar skala tidak bergerak
// setiap spectrum baru diterima. Nilai spectrum di bawah -100 dB
// akan tetap terlihat pada baseline chart.
const CHART_REFERENCE_MIN_DB = -100;

// Warna marker pada grafik. Urutan warna sama dengan urutan Signal 01, 02, 03, dan seterusnya.
const DETECTION_MARKER_COLORS = [
  "#6dffba",
  "#ffd166",
  "#c792ff",
  "#ff8e8e",
  "#58c7ff",
  "#ff9f68",
];

// TEMPORARY DEBUG VISUAL.
// 0.05 MHz = 50 kHz. Matikan dengan mengubah true menjadi false.
const SHOW_MERGE_GAP_DEBUG = false;
const MERGE_GAP_DEBUG_MHZ = 0.05;

function clamp(value, minimum, maximum) {
  return Math.min(Math.max(value, minimum), maximum);
}

function roundDownToStep(value, step) {
  return Math.floor(value / step) * step;
}

function roundUpToStep(value, step) {
  return Math.ceil(value / step) * step;
}

function formatMHz(value) {
  if (value === null || value === undefined || value === "") {
    return "-";
  }

  if (!Number.isFinite(Number(value))) {
    return "-";
  }

  return `${Number(value).toFixed(6)} MHz`;
}

function formatDb(value) {
  if (!Number.isFinite(Number(value))) {
    return "-";
  }

  return `${Number(value).toFixed(2)} dB`;
}

function buildSpectrumSvgPath({
  frequencyValues,
  powerValues,
  start,
  end,
  chartScale,
}) {
  const pointCount = Math.min(
    frequencyValues.length,
    powerValues.length
  );

  if (
    pointCount === 0 ||
    !Number.isFinite(start) ||
    !Number.isFinite(end) ||
    end <= start
  ) {
    return {
      linePoints: "",
      areaPoints: "",
    };
  }

  const chartPoints = [];

  for (let index = 0; index < pointCount; index += 1) {
    const frequency = Number(frequencyValues[index]);
    const power = Number(powerValues[index]);

    if (!Number.isFinite(frequency) || !Number.isFinite(power)) {
      continue;
    }

    const normalizedX =
      ((frequency - start) / (end - start)) * 1000;

    const normalizedY =
      ((chartScale.maxDb - power) /
        (chartScale.maxDb - chartScale.minDb)) *
      CHART_SVG_HEIGHT;

    chartPoints.push({
      x: clamp(normalizedX, 0, 1000),
      y: clamp(normalizedY, 0, CHART_SVG_HEIGHT),
    });
  }

  if (chartPoints.length === 0) {
    return {
      linePoints: "",
      areaPoints: "",
    };
  }

  const linePoints = chartPoints
    .map((point) => `${point.x.toFixed(2)},${point.y.toFixed(2)}`)
    .join(" ");

  const firstPoint = chartPoints[0];
  const lastPoint = chartPoints[chartPoints.length - 1];

  return {
    linePoints,
    areaPoints: [
      `${firstPoint.x.toFixed(2)},${CHART_SVG_HEIGHT}`,
      linePoints,
      `${lastPoint.x.toFixed(2)},${CHART_SVG_HEIGHT}`,
    ].join(" "),
  };
}

function formatWindowMHz(start, end) {
  if (!Number.isFinite(Number(start)) || !Number.isFinite(Number(end))) {
    return "-";
  }

  return `${Number(start).toFixed(2)}–${Number(end).toFixed(2)} MHz`;
}

function buildLteDetail(candidate) {
  const direction = candidate.direction ?? "DL";

  if (direction === "TDD") {
    const earfcn = candidate.earfcn ?? candidate.earfcn_dl;

    return [
      earfcn === null || earfcn === undefined
        ? "EARFCN : -"
        : `EARFCN : [ ${earfcn} ]`,
    ];
  }

  const details = [];

  if (candidate.earfcn_dl !== null && candidate.earfcn_dl !== undefined) {
    details.push(`DL EARFCN : [ ${candidate.earfcn_dl} ]`);
  }

  if (candidate.earfcn_ul !== null && candidate.earfcn_ul !== undefined) {
    details.push(`UL EARFCN : [ ${candidate.earfcn_ul} ]`);
  }

  if (details.length === 0) {
    return ["EARFCN : -"];
  }

  return details;
}

function buildNrDetail(candidate) {
  const duplex = candidate.mode ?? "NR";
  const direction = candidate.direction ?? duplex;

  if (duplex === "TDD" || direction === "TDD") {
    const nrArfcn = candidate.nr_arfcn ?? candidate.nr_arfcn_dl;

    return [
      "TDD",
      nrArfcn === null || nrArfcn === undefined
        ? "ARFCN : -"
        : `ARFCN : [ ${nrArfcn} ]`,
    ];
  }

  if (duplex === "SDL" || direction === "SDL") {
    return [
      "SDL · DL Only",
      candidate.nr_arfcn_dl === null || candidate.nr_arfcn_dl === undefined
        ? "DL ARFCN : -"
        : `DL ARFCN : [ ${candidate.nr_arfcn_dl} ]`,
    ];
  }

  if (duplex === "SUL" || direction === "SUL") {
    return [
      "SUL · UL Only",
      candidate.nr_arfcn_ul === null || candidate.nr_arfcn_ul === undefined
        ? "UL ARFCN : -"
        : `UL ARFCN : [ ${candidate.nr_arfcn_ul} ]`,
    ];
  }

  if (duplex === "FDD") {
    if (direction === "UL") {
      return [
        "FDD · Detected UL",
        candidate.nr_arfcn_ul === null || candidate.nr_arfcn_ul === undefined
          ? "UL ARFCN : -"
          : `UL ARFCN : [ ${candidate.nr_arfcn_ul} ]`,
        candidate.nr_arfcn_dl === null || candidate.nr_arfcn_dl === undefined
          ? "DL Pair : -"
          : `DL Pair : [ ${candidate.nr_arfcn_dl} ]`,
      ];
    }

    return [
      "FDD · Detected DL",
      candidate.nr_arfcn_dl === null || candidate.nr_arfcn_dl === undefined
        ? "DL ARFCN : -"
        : `DL ARFCN : [ ${candidate.nr_arfcn_dl} ]`,
      candidate.nr_arfcn_ul === null || candidate.nr_arfcn_ul === undefined
        ? "UL Pair : -"
        : `UL Pair : [ ${candidate.nr_arfcn_ul} ]`,
    ];
  }

  const nrArfcn = candidate.nr_arfcn ?? candidate.nr_arfcn_dl ?? candidate.nr_arfcn_ul;

  return [
    duplex,
    nrArfcn === null || nrArfcn === undefined
      ? "ARFCN : -"
      : `ARFCN : [ ${nrArfcn} ]`,
  ].filter(Boolean);
}

function buildTechnologyCandidates(detection) {
  const gsmCandidate = detection.gsm;
  const umtsCandidates = Array.isArray(detection.umts)
    ? detection.umts
    : [];
  const lteCandidates = Array.isArray(detection.lte)
    ? detection.lte
    : [];
  const nrCandidates = Array.isArray(detection.nr)
    ? detection.nr
    : [];

  return [
    gsmCandidate && {
      type: "gsm",
      label: "2G",
      name: gsmCandidate.band,
      detail:
        gsmCandidate.arfcn === "Dynamic"
          ? "ARFCN : Dynamic"
          : `ARFCN : [ ${gsmCandidate.arfcn} ]`,
      dlMhz: gsmCandidate.freq_dl_mhz,
      ulMhz: gsmCandidate.freq_ul_mhz,
    },
    ...umtsCandidates.map((candidate) => ({
      type: "umts",
      label: "3G",
      name: candidate.name ?? candidate.band ?? "UMTS Candidate",
      detail:
        candidate.uarfcn_dl === null || candidate.uarfcn_dl === undefined
          ? "UARFCN : -"
          : `UARFCN : [ ${candidate.uarfcn_dl} ]`,
      dlMhz: candidate.freq_dl_mhz,
      ulMhz: candidate.freq_ul_mhz,
    })),
    ...lteCandidates.map((candidate) => ({
      type: "lte",
      label: "4G",
      name: candidate.name ?? candidate.band ?? "LTE Candidate",
      detail: buildLteDetail(candidate),
      dlMhz: candidate.freq_dl_mhz,
      ulMhz: candidate.freq_ul_mhz,
    })),
    ...nrCandidates.map((candidate) => ({
      type: "nr",
      label: "5G",
      name: candidate.name ?? candidate.band ?? "NR Candidate",
      detail: buildNrDetail(candidate),
      dlMhz: candidate.freq_dl_mhz,
      ulMhz: candidate.freq_ul_mhz,
    })),
  ].filter(Boolean);
}

function buildDetectionHistoryId(detection, fallbackIndex = 0) {
  const windowIndex = Number(detection.window_index ?? 0);
  const fftIndex = Number(detection.fft_index ?? fallbackIndex);
  const frequency = Number(detection.frequency_mhz);

  return [
    windowIndex,
    fftIndex,
    Number.isFinite(frequency) ? frequency.toFixed(6) : fallbackIndex,
  ].join("-");
}

function mergeDetectionHistory(previousHistory, incomingDetections) {
  const map = new Map();

  previousHistory.forEach((item) => {
    map.set(item.history_id, item);
  });

  incomingDetections.forEach((item) => {
    map.set(item.history_id, item);
  });

  return Array.from(map.values()).sort((a, b) => {
    const frequencyA = Number(a.frequency_mhz);
    const frequencyB = Number(b.frequency_mhz);

    if (!Number.isFinite(frequencyA) || !Number.isFinite(frequencyB)) {
      return 0;
    }

    return frequencyA - frequencyB;
  });
}

function formatDateTime(value) {
  if (!value) {
    return "-";
  }

  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return String(value);
  }

  return date.toLocaleString("id-ID", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function App() {
  const [activeTab, setActiveTab] = useState("general");

  // Nilai input yang diketik pada web.
  const [threshold, setThreshold] = useState("0");
  const [startFrequency, setStartFrequency] = useState("50");
  const [endFrequency, setEndFrequency] = useState("6000");

  // Konfigurasi yang sudah benar-benar dikirim ke backend.
  const [scanConfig, setScanConfig] = useState({
    threshold_db: 0,
    start_frequency_mhz: 50,
    end_frequency_mhz: 6000,
    center_frequency_mhz: 3025,
    sample_rate_mhz: 5950,
  });

  const [isScanning, setIsScanning] = useState(false);
  const [isBusy, setIsBusy] = useState(false);

  const [device, setDevice] = useState({
    status: "checking",
    device: "USRP B210",
    antenna: "RX2",
  });

  const [spectrum, setSpectrum] = useState({
    frequency_mhz: [],
    power_db: [],
  });

  // Opsi 2: history spektrum dari window sweep yang sudah discan.
  // Data ini membuat window 56 MHz yang bergerak meninggalkan trail di chart.
  const [spectrumHistory, setSpectrumHistory] = useState([]);
  const [sweepInfo, setSweepInfo] = useState(null);
  const [totalDetectionCount, setTotalDetectionCount] = useState(0);

  // Single scan session history:
  // semua titik di atas threshold pada satu sweep disimpan di sini,
  // lalu setelah sweep selesai dibuat menjadi satu folder/session.
  const [currentScanHistory, setCurrentScanHistory] = useState([]);
  const [scanSessions, setScanSessions] = useState([]);
  const [selectedSessionId, setSelectedSessionId] = useState(null);

  const currentScanHistoryRef = useRef([]);
  const activeScanMetaRef = useRef(null);
  const scanSessionSavedRef = useRef(false);

  const [peak, setPeak] = useState(null);
  const [detections, setDetections] = useState([]);
  const [debugClusters, setDebugClusters] = useState({
    merge_gap_mhz: 0.05,
    raw_clusters: [],
    merged_clusters: [],
  });
  const [statusMessage, setStatusMessage] = useState(
    "Masukkan konfigurasi lalu tekan START SCAN."
  );
  const [errorMessage, setErrorMessage] = useState("");

  // Cek apakah backend bisa mendeteksi USRP.
  useEffect(() => {
    async function checkDevice() {
      try {
        const response = await fetch(`${API_BASE_URL}/api/device`);
        const data = await response.json();

        if (!response.ok) {
          throw new Error(data.detail || "USRP tidak dapat diakses.");
        }

        setDevice(data);
      } catch (error) {
        setDevice({
          status: "offline",
          device: "USRP B210",
          antenna: "RX2",
        });

        setErrorMessage(`Device error: ${error.message}`);
      }
    }

    checkDevice();
  }, []);

  // Ambil data spectrum baru setiap 250 ms saat scan berjalan.
  useEffect(() => {
    if (!isScanning) {
      return undefined;
    }

    let cancelled = false;
    let timeoutId;

    async function pollSpectrum() {
      try {
        const response = await fetch(`${API_BASE_URL}/api/spectrum`);
        const data = await response.json();

        if (!response.ok) {
          throw new Error(data.detail || "Gagal mengambil spectrum.");
        }

        if (cancelled) {
          return;
        }

        const spectrumData = data.spectrum ?? {
          frequency_mhz: [],
          power_db: [],
        };
        const currentWindow = data.current_window ?? null;
        const sweep = data.sweep ?? null;
        const frequencyValues = spectrumData.frequency_mhz ?? [];
        const powerValues = spectrumData.power_db ?? [];
        const timestamp = data.timestamp ?? new Date().toISOString();
        const windowDetections = Array.isArray(data.detections)
          ? data.detections
          : [];
        const windowIndex = Number(
          currentWindow?.window_index ?? sweep?.scanned_windows ?? 0
        );

        setSpectrum(spectrumData);
        setPeak(data.peak);
        setDetections(windowDetections);
        setDebugClusters(
          data.debug_clusters ?? {
            merge_gap_mhz: 0.05,
            raw_clusters: [],
            merged_clusters: [],
          }
        );
        setScanConfig(data.config);
        setSweepInfo(sweep);
        setTotalDetectionCount(
          Number.isFinite(Number(data.detection_count))
            ? Number(data.detection_count)
            : windowDetections.length
        );

        if (windowDetections.length > 0) {
          const normalizedDetections = windowDetections.map(
            (detection, detectionIndex) => ({
              ...detection,
              history_id: buildDetectionHistoryId(
                detection,
                detectionIndex
              ),
              captured_at: timestamp,
              window_label: currentWindow
                ? formatWindowMHz(
                    currentWindow.start_frequency_mhz,
                    currentWindow.end_frequency_mhz
                  )
                : "-",
            })
          );

          const nextScanHistory = mergeDetectionHistory(
            currentScanHistoryRef.current,
            normalizedDetections
          );

          currentScanHistoryRef.current = nextScanHistory;
          setCurrentScanHistory(nextScanHistory);
        }

        if (
          currentWindow &&
          frequencyValues.length > 0 &&
          powerValues.length > 0
        ) {
          const segmentId = [
            windowIndex,
            currentWindow.start_frequency_mhz,
            currentWindow.end_frequency_mhz,
          ].join("-");

          const historySegment = {
            id: segmentId,
            windowIndex,
            startFrequencyMhz: Number(currentWindow.start_frequency_mhz),
            endFrequencyMhz: Number(currentWindow.end_frequency_mhz),
            timestamp,
            frequency_mhz: frequencyValues,
            power_db: powerValues,
          };

          setSpectrumHistory((previousHistory) => {
            const withoutDuplicate = previousHistory.filter(
              (segment) => segment.id !== segmentId
            );

            const nextHistory = [
              ...withoutDuplicate,
              historySegment,
            ].sort((a, b) => a.windowIndex - b.windowIndex);

            if (nextHistory.length > MAX_SPECTRUM_HISTORY_WINDOWS) {
              return nextHistory.slice(
                nextHistory.length - MAX_SPECTRUM_HISTORY_WINDOWS
              );
            }

            return nextHistory;
          });
        }

        setErrorMessage("");

        if (!data.running) {
          setIsScanning(false);

          if (data.completed && !scanSessionSavedRef.current) {
            const historyForSession = currentScanHistoryRef.current;
            const sessionId =
              activeScanMetaRef.current?.id ?? `scan-${Date.now()}`;
            const completedAt = timestamp;

            const session = {
              id: sessionId,
              startedAt:
                activeScanMetaRef.current?.startedAt ?? completedAt,
              completedAt,
              config: data.config,
              sweep,
              peak: data.peak,
              detections: historyForSession,
              detectionCount: historyForSession.length,
            };

            setSelectedSessionId(session.id);
            setScanSessions((previousSessions) => {
              const sessionWithTitle = {
                ...session,
                title: `Scan #${String(
                  previousSessions.length + 1
                ).padStart(3, "0")}`,
              };

              return [sessionWithTitle, ...previousSessions];
            });

            scanSessionSavedRef.current = true;
          }

          setStatusMessage(
            data.completed
              ? `Sweep selesai. Hasil scan disimpan ke Scan History. Total titik di atas threshold: ${
                  currentScanHistoryRef.current.length
                }.`
              : "Scan dihentikan."
          );
          return;
        }

        if (currentWindow && sweep) {
          setStatusMessage(
            `Scanning ${formatWindowMHz(
              currentWindow.start_frequency_mhz,
              currentWindow.end_frequency_mhz
            )} · Window ${sweep.scanned_windows}/${sweep.total_windows} · ${
              sweep.progress_percent
            }%`
          );
        } else {
          setStatusMessage(
            `Spectrum diperbarui: ${data.timestamp || "realtime"}`
          );
        }
      } catch (error) {
        if (!cancelled) {
          setErrorMessage(`Spectrum error: ${error.message}`);
          setIsScanning(false);
        }

        return;
      }

      if (!cancelled) {
        timeoutId = window.setTimeout(pollSpectrum, SPECTRUM_REFRESH_MS);
      }
    }

    pollSpectrum();

    return () => {
      cancelled = true;
      window.clearTimeout(timeoutId);
    };
  }, [isScanning]);

  // Buat label sumbu X berdasarkan konfigurasi scan asli.
  // Sepuluh interval memberi label setiap 0.2 MHz saat lebar scan 2 MHz.
  const frequencyTicks = useMemo(() => {
    const start = Number(scanConfig.start_frequency_mhz);
    const end = Number(scanConfig.end_frequency_mhz);
    const tickCount = 10;

    if (
      !Number.isFinite(start) ||
      !Number.isFinite(end) ||
      start >= end
    ) {
      return [];
    }

    return Array.from({ length: tickCount + 1 }, (_, index) => {
      const value = start + ((end - start) / tickCount) * index;

      return {
        label: Number(value.toFixed(2)).toString(),
        position: (index / tickCount) * 100,
      };
    });
  }, [scanConfig]);

  // Skala Y hanya dihitung ulang saat threshold scan berubah.
  // Spectrum baru setiap 500 ms tidak boleh mengubah skala.
  // Dengan batas bawah tetap -100 dB, threshold berada tepat
  // sekitar 1/3 dari atas chart.
  const chartScale = useMemo(() => {
    const thresholdValue = Number(scanConfig.threshold_db);
    const safeThreshold = Number.isFinite(thresholdValue)
      ? thresholdValue
      : 0;

    const minDb = CHART_REFERENCE_MIN_DB;
    const maxDb =
      (safeThreshold - THRESHOLD_TARGET_TOP_RATIO * minDb) /
      (1 - THRESHOLD_TARGET_TOP_RATIO);

    return { minDb, maxDb };
  }, [scanConfig.threshold_db]);

  // Label sumbu Y mengikuti skala threshold yang stabil.
  const chartDbTicks = useMemo(() => {
    const thresholdValue = Number(scanConfig.threshold_db);
    const safeThreshold = Number.isFinite(thresholdValue)
      ? thresholdValue
      : 0;

    const firstTick = Math.ceil(chartScale.minDb / 50) * 50;
    const lastTick = Math.floor(chartScale.maxDb / 50) * 50;

    const values = [];

    for (let value = lastTick; value >= firstTick; value -= 50) {
      values.push(value);
    }

    const thresholdAlreadyExists = values.some(
      (value) => Math.abs(value - safeThreshold) < 0.001
    );

    if (
      !thresholdAlreadyExists &&
      safeThreshold >= chartScale.minDb &&
      safeThreshold <= chartScale.maxDb
    ) {
      values.push(safeThreshold);
    }

    return values
      .sort((a, b) => b - a)
      .map((value) => ({
        value: Number(value.toFixed(1)),
        position:
          ((chartScale.maxDb - value) /
            (chartScale.maxDb - chartScale.minDb)) *
          100,
        isThreshold: Math.abs(value - safeThreshold) < 0.001,
      }));
  }, [chartScale, scanConfig.threshold_db]);

  // Ubah pasangan frequency_mhz + power_db dari backend menjadi titik SVG.
  // Posisi X memakai frekuensi asli pada full range scan, bukan nomor/index data.
  const spectrumChart = useMemo(() => {
    const start = Number(scanConfig.start_frequency_mhz);
    const end = Number(scanConfig.end_frequency_mhz);

    return buildSpectrumSvgPath({
      frequencyValues: spectrum.frequency_mhz ?? [],
      powerValues: spectrum.power_db ?? [],
      start,
      end,
      chartScale,
    });
  }, [chartScale, scanConfig, spectrum]);

  // Opsi 2: ubah seluruh history window sweep menjadi polyline SVG.
  // Segment lama akan digambar lebih redup, sedangkan window aktif tetap memakai
  // spectrumChart utama yang lebih terang.
  const spectrumHistoryCharts = useMemo(() => {
    const start = Number(scanConfig.start_frequency_mhz);
    const end = Number(scanConfig.end_frequency_mhz);

    if (
      !Array.isArray(spectrumHistory) ||
      spectrumHistory.length === 0 ||
      !Number.isFinite(start) ||
      !Number.isFinite(end) ||
      end <= start
    ) {
      return [];
    }

    return spectrumHistory
      .map((segment) => {
        const path = buildSpectrumSvgPath({
          frequencyValues: segment.frequency_mhz ?? [],
          powerValues: segment.power_db ?? [],
          start,
          end,
          chartScale,
        });

        if (!path.linePoints) {
          return null;
        }

        return {
          ...segment,
          ...path,
        };
      })
      .filter(Boolean);
  }, [chartScale, scanConfig, spectrumHistory]);


  // Posisi garis threshold pada grafik.
  const thresholdTop = useMemo(() => {
    const value = Number(scanConfig.threshold_db);

    const position =
      ((chartScale.maxDb - value) /
        (chartScale.maxDb - chartScale.minDb)) *
      100;

    return clamp(position, 0, 100);
  }, [chartScale, scanConfig.threshold_db]);

  // Satu marker dibuat untuk setiap detection akhir dari backend.
  // Marker ini menunjukkan peak yang dipakai untuk klasifikasi band,
  // bukan seluruh titik FFT yang berada di atas threshold.
  const detectionMarkers = useMemo(() => {
    const start = Number(scanConfig.start_frequency_mhz);
    const end = Number(scanConfig.end_frequency_mhz);

    if (
      !Number.isFinite(start) ||
      !Number.isFinite(end) ||
      end <= start
    ) {
      return [];
    }

    return detections
      .map((detection, index) => {
        const frequency = Number(detection.frequency_mhz);
        const power = Number(detection.power_db);

        if (!Number.isFinite(frequency) || !Number.isFinite(power)) {
          return null;
        }

        const horizontalPosition =
          ((frequency - start) / (end - start)) * 100;

        // Jangan tampilkan marker bila frequency berada di luar range scan.
        if (horizontalPosition < 0 || horizontalPosition > 100) {
          return null;
        }

        const verticalPosition =
          ((chartScale.maxDb - power) /
            (chartScale.maxDb - chartScale.minDb)) *
          100;

        return {
          id: `${frequency}-${index}`,
          label: String(index + 1).padStart(2, "0"),
          x: clamp(horizontalPosition, 0, 100),
          y: clamp(verticalPosition, 0, 100),
          color:
            DETECTION_MARKER_COLORS[
              index % DETECTION_MARKER_COLORS.length
            ],
          alignRight: horizontalPosition > 86,
        };
      })
      .filter(Boolean);
  }, [chartScale, detections, scanConfig]);

  // TEMPORARY DEBUG VISUAL.
  // Menampilkan area cluster akhir aktual dari backend.
  // Area ini menunjukkan bagian threshold yang sudah digabung
  // dan menghasilkan satu detection/card.
  const clusterAreas = useMemo(() => {
    const start = Number(scanConfig.start_frequency_mhz);
    const end = Number(scanConfig.end_frequency_mhz);
    const scanWidthMhz = end - start;

    if (
      !Number.isFinite(scanWidthMhz) ||
      scanWidthMhz <= 0 ||
      !Array.isArray(debugClusters.merged_clusters)
    ) {
      return [];
    }

    return debugClusters.merged_clusters
      .map((cluster, index) => {
        const clusterStart = Number(cluster.start_mhz);
        const clusterEnd = Number(cluster.end_mhz);

        if (
          !Number.isFinite(clusterStart) ||
          !Number.isFinite(clusterEnd)
        ) {
          return null;
        }

        const left =
          ((clusterStart - start) / scanWidthMhz) * 100;

        const right =
          ((clusterEnd - start) / scanWidthMhz) * 100;

        const width = Math.max(right - left, 0.35);

        return {
          id: `cluster-${cluster.id ?? index}`,
          label: `C${index + 1}`,
          left: clamp(left, 0, 100),
          width: clamp(width, 0.35, 100),
          color:
            DETECTION_MARKER_COLORS[
              index % DETECTION_MARKER_COLORS.length
            ],
          widthKHz: Number(cluster.width_khz),
        };
      })
      .filter(Boolean);
  }, [debugClusters, scanConfig]);

  // TEMPORARY DEBUG VISUAL.
  // Menampilkan lebar 50 kHz pada grafik agar mudah melihat
  // seberapa dekat dua cluster sebelum digabung.
  const mergeGapDebugRulers = useMemo(() => {
    const start = Number(scanConfig.start_frequency_mhz);
    const end = Number(scanConfig.end_frequency_mhz);
    const scanWidthMhz = end - start;

    if (
      !SHOW_MERGE_GAP_DEBUG ||
      !Number.isFinite(scanWidthMhz) ||
      scanWidthMhz <= 0
    ) {
      return [];
    }

    const widthPercent =
      (MERGE_GAP_DEBUG_MHZ / scanWidthMhz) * 100;

    return detectionMarkers.map((marker, index) => {
      const useLeftSide = marker.x + widthPercent > 100;
      const left = useLeftSide
        ? marker.x - widthPercent
        : marker.x;

      return {
        id: `merge-gap-${marker.id}`,
        left: clamp(left, 0, 100),
        width: clamp(widthPercent, 0, 100),
        color: marker.color,
        rowOffsetPx: 10 + (index % 4) * 15,
        direction: useLeftSide ? "left" : "right",
      };
    });
  }, [detectionMarkers, scanConfig]);

  async function handleScan() {
    setErrorMessage("");
    setIsBusy(true);

    try {
      // Jika sedang scan, tombol menjadi Stop Scan.
      if (isScanning) {
        const response = await fetch(`${API_BASE_URL}/api/scan/stop`, {
          method: "POST",
        });

        const data = await response.json();

        if (!response.ok) {
          throw new Error(data.detail || "Gagal menghentikan scan.");
        }

        setIsScanning(false);
        setStatusMessage("Scan USRP dihentikan.");
        return;
      }

      const requestBody = {
        threshold_db: Number(threshold),
        start_frequency_mhz: Number(startFrequency),
        end_frequency_mhz: Number(endFrequency),
      };

      if (
        !Number.isFinite(requestBody.threshold_db) ||
        !Number.isFinite(requestBody.start_frequency_mhz) ||
        !Number.isFinite(requestBody.end_frequency_mhz)
      ) {
        throw new Error("Semua konfigurasi harus berupa angka.");
      }

      const response = await fetch(`${API_BASE_URL}/api/scan/start`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(requestBody),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "Gagal memulai scan.");
      }

      setScanConfig(data.config);
      setSpectrum({
        frequency_mhz: [],
        power_db: [],
      });
      setSpectrumHistory([]);
      setCurrentScanHistory([]);
      currentScanHistoryRef.current = [];
      activeScanMetaRef.current = {
        id: `scan-${Date.now()}`,
        startedAt: new Date().toISOString(),
        request: requestBody,
      };
      scanSessionSavedRef.current = false;
      setSweepInfo(data.sweep ?? null);
      setTotalDetectionCount(0);
      setPeak(null);
      setDetections([]);
      setDebugClusters({
        merge_gap_mhz: 0.05,
        raw_clusters: [],
        merged_clusters: [],
      });
      setIsScanning(true);
      setStatusMessage("Scan USRP dimulai. Menunggu data spectrum...");
    } catch (error) {
      setErrorMessage(error.message);
      setStatusMessage("Scan belum dimulai.");
    } finally {
      setIsBusy(false);
    }
  }

  const currentScanHistorySorted = useMemo(
    () => [...currentScanHistory].sort(
      (a, b) => Number(a.frequency_mhz) - Number(b.frequency_mhz)
    ),
    [currentScanHistory]
  );

  const selectedScanSession = useMemo(() => {
    if (scanSessions.length === 0) {
      return null;
    }

    return (
      scanSessions.find((session) => session.id === selectedSessionId) ??
      scanSessions[0]
    );
  }, [scanSessions, selectedSessionId]);

  const detectedCount = currentScanHistorySorted.length;

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">◢</span>

          <div>
            <p className="brand-small">USRP B210</p>
            <h1>TOOLS SCANNER</h1>
          </div>
        </div>

        <div className="sidebar-divider" />

        <section className="settings-section">
          <h2>SCAN SETTINGS</h2>

          <label htmlFor="threshold">Threshold</label>
          <div className="input-unit">
            <input
              id="threshold"
              type="number"
              value={threshold}
              onChange={(event) => setThreshold(event.target.value)}
            />
            <span>dB</span>
          </div>

          <label htmlFor="start-frequency">Start Frequency</label>
          <div className="input-unit">
            <input
              id="start-frequency"
              type="number"
              value={startFrequency}
              onChange={(event) => setStartFrequency(event.target.value)}
            />
            <span>MHz</span>
          </div>

          <label htmlFor="end-frequency">End Frequency</label>
          <div className="input-unit">
            <input
              id="end-frequency"
              type="number"
              value={endFrequency}
              onChange={(event) => setEndFrequency(event.target.value)}
            />
            <span>MHz</span>
          </div>

          <button
            type="button"
            className={`scan-button ${isScanning ? "scan-active" : ""}`}
            onClick={handleScan}
            disabled={isBusy}
          >
            <span className="scan-icon">{isScanning ? "■" : "▶"}</span>
            {isBusy
              ? "PROCESSING..."
              : isScanning
                ? "STOP SCAN"
                : "START SCAN"}
          </button>
        </section>

        <section className="sidebar-status">
          <p>SCAN STATUS</p>

          <strong className={isScanning ? "status-running" : "status-idle"}>
            {isScanning ? "RUNNING" : "STANDBY"}
          </strong>

          <span>
            Range: {scanConfig.start_frequency_mhz}–
            {scanConfig.end_frequency_mhz} MHz
          </span>

          {sweepInfo && (
            <span className="sidebar-sweep-detail">
              Sweep: {sweepInfo.scanned_windows}/{sweepInfo.total_windows} ·{" "}
              {sweepInfo.progress_percent}%
            </span>
          )}
        </section>
        <section className="sidebar-live-peak">
        <div className="sidebar-peak-heading">
          <span>LIVE PEAK SIGNAL</span>

          {peak && (
            <span
              className={
                peak.above_threshold
                  ? "sidebar-peak-state warning"
                  : "sidebar-peak-state normal"
              }
            >
              {peak.above_threshold ? "WARNING" : "NORMAL"}
            </span>
          )}
        </div>

        {peak ? (
          <>
            <h3>USRP B210 · RX2</h3>

            <div className="sidebar-peak-detail">
              <span>PEAK FREQUENCY</span>
              <strong>{formatMHz(peak.frequency_mhz)}</strong>
            </div>

            <div className="sidebar-peak-detail">
              <span>PEAK POWER</span>
              <strong>{formatDb(peak.power_db)}</strong>
            </div>

            <div className="sidebar-peak-detail">
              <span>THRESHOLD</span>
              <strong>{scanConfig.threshold_db} dB</strong>
            </div>
          </>
        ) : (
          <p className="sidebar-empty-peak">
            Belum ada peak signal.
          </p>
        )}
      </section>

      <p className="sidebar-live-message">{statusMessage}</p>

      {errorMessage && (
        <p className="sidebar-error-message">{errorMessage}</p>
      )}
      </aside>

      <section className="dashboard">
        <header className="topbar">
          <div>
            <p className="eyebrow">REALTIME SPECTRUM MONITORING</p>
            <h2>Frequency Scanner Dashboard</h2>
          </div>

          <div className="connection-status">
            <span
              className={
                device.status === "ready"
                  ? "status-dot"
                  : "status-dot status-dot-offline"
              }
            />

            {device.status === "ready"
              ? `${device.device} · ${device.antenna}`
              : "USRP Checking"}
          </div>
        </header>

        <nav className="tabs">
          <button
            type="button"
            className={activeTab === "general" ? "tab active-tab" : "tab"}
            onClick={() => setActiveTab("general")}
          >
            General
          </button>

          <button
            type="button"
            className={activeTab === "history" ? "tab active-tab" : "tab"}
            onClick={() => setActiveTab("history")}
          >
            Scan History
            <span className="tab-badge">{scanSessions.length}</span>
          </button>
        </nav>

        {activeTab === "general" ? (
          <>
            <section className="spectrum-panel">
              <div className="panel-heading">
                <div>
                  <p className="section-kicker">LIVE VIEW</p>
                  <h3>Realtime Spectrum</h3>
                </div>

                <div className="legend">
                  <span>
                    <i className="legend-line spectrum-line" />
                    Spectrum
                  </span>

                  <span>
                    <i className="legend-line threshold-line" />
                    Threshold {scanConfig.threshold_db} dB
                  </span>

                  <span>
                    <i className="legend-detection-marker" />
                    Threshold Point
                  </span>

                  <span>
                    <i className="legend-line history-line" />
                    Spectrum History
                  </span>

                  {SHOW_MERGE_GAP_DEBUG && (
                    <span>
                      <i className="legend-merge-gap" />
                      50 kHz Debug
                    </span>
                  )}
                </div>
              </div>

              {sweepInfo && (
                <div className="sweep-progress-card">
                  <span>
                    Sweep window: {sweepInfo.scanned_windows}/
                    {sweepInfo.total_windows}
                  </span>
                  <span>Progress: {sweepInfo.progress_percent}%</span>
                  {sweepInfo.last_window_start_mhz !== null &&
                    sweepInfo.last_window_end_mhz !== null && (
                      <span>
                        Last:{" "}
                        {formatWindowMHz(
                          sweepInfo.last_window_start_mhz,
                          sweepInfo.last_window_end_mhz
                        )}
                      </span>
                    )}
                </div>
              )}

              <div className="spectrum-chart">
                <div className="chart-y-axis" aria-hidden="true">
                {chartDbTicks.map(({ value, position, isThreshold }) => (
                  <span
                    key={value}
                    className={isThreshold ? "threshold-y-tick" : ""}
                    style={{ top: `${position}%` }}
                  >
                    {value} dB
                  </span>
                ))}
                </div>

                <div className="chart-plot">
                  {chartDbTicks.map(({ value, position }) => (
                    <div
                      key={`horizontal-grid-${value}`}
                      className="chart-h-grid-line"
                      style={{ top: `${position}%` }}
                    />
                  ))}

                  {frequencyTicks.map(({ label, position }) => (
                    <div
                      key={`vertical-grid-${label}-${position}`}
                      className="chart-v-grid-line"
                      style={{ left: `${position}%` }}
                    />
                  ))}

                  <div
                    className="threshold-visual"
                    style={{ top: `${thresholdTop}%` }}
                  >
                    <span>Threshold {scanConfig.threshold_db} dB</span>
                  </div>

                  {spectrumChart.linePoints || spectrumHistoryCharts.length > 0 ? (
                    <>
                  {spectrumHistoryCharts.length > 1 && (
                    <svg
                      className="spectrum-history-svg"
                      viewBox={`0 0 1000 ${CHART_SVG_HEIGHT}`}
                      preserveAspectRatio="none"
                      aria-label="USRP sweep spectrum history"
                    >
                      {spectrumHistoryCharts.slice(0, -1).map((segment) => (
                        <polyline
                          key={segment.id}
                          points={segment.linePoints}
                          className="spectrum-history-line"
                          fill="none"
                          vectorEffect="non-scaling-stroke"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          shapeRendering="geometricPrecision"
                        />
                      ))}
                    </svg>
                  )}

                      <svg
                        className="spectrum-svg"
                        viewBox={`0 0 1000 ${CHART_SVG_HEIGHT}`}
                        preserveAspectRatio="none"
                        aria-label="USRP realtime spectrum"
                      >
                        <polygon
                          points={spectrumChart.areaPoints}
                          className="spectrum-area"
                        />

                        <polyline
                          points={spectrumChart.linePoints}
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="1.35"
                          vectorEffect="non-scaling-stroke"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          shapeRendering="geometricPrecision"
                        />
                      </svg>

                      {clusterAreas.map((cluster) => (
                        <div
                          className="cluster-area"
                          key={cluster.id}
                          style={{
                            left: `${cluster.left}%`,
                            width: `${cluster.width}%`,
                            "--cluster-color": cluster.color,
                          }}
                        >
                          <span>
                            {cluster.label}
                            {Number.isFinite(cluster.widthKHz)
                              ? ` · ${cluster.widthKHz.toFixed(1)} kHz`
                              : ""}
                          </span>
                        </div>
                      ))}

                      {detectionMarkers.map((marker) => (
                        <div
                          className={`spectrum-detection-marker ${
                            marker.alignRight ? "marker-align-right" : ""
                          }`}
                          key={marker.id}
                          style={{
                            left: `${marker.x}%`,
                            "--marker-color": marker.color,
                          }}
                        >
                          <span className="spectrum-detection-guide" />

                          <span
                            className="spectrum-detection-dot"
                            style={{ top: `${marker.y}%` }}
                          />

                          <span
                            className="spectrum-detection-label"
                            style={{ top: `${marker.y}%` }}
                          >
                            {marker.label}
                          </span>
                        </div>
                      ))}

                      {mergeGapDebugRulers.map((ruler) => (
                        <div
                          className={`merge-gap-debug-ruler ${ruler.direction}`}
                          key={ruler.id}
                          style={{
                            left: `${ruler.left}%`,
                            width: `${ruler.width}%`,
                            bottom: `${ruler.rowOffsetPx}px`,
                            "--marker-color": ruler.color,
                          }}
                        >
                          <span>50 kHz</span>
                        </div>
                      ))}
                    </>
                  ) : (
                    <div className="chart-placeholder">
                      {isScanning
                        ? "Menerima IQ sample dari USRP..."
                        : "Tekan START SCAN untuk melihat spectrum."}
                    </div>
                  )}
                </div>

                <div className="chart-x-axis" aria-hidden="true">
                  {frequencyTicks.map(({ label, position }, index) => (
                    <span
                      key={`${label}-${position}`}
                      className={
                        index === 0
                          ? "first-x-label"
                          : index === frequencyTicks.length - 1
                            ? "last-x-label"
                            : ""
                      }
                      style={{ left: `${position}%` }}
                    >
                      {label}
                    </span>
                  ))}

                  <small className="chart-x-unit">MHz</small>
                </div>
              </div>
            </section>

            <section className="detected-section classification-section">
              <div className="panel-heading">
                <div>
                  <p className="section-kicker">CURRENT SCAN</p>
                  <h3>Current Scan History</h3>
                </div>

                <div className="detected-count">
                  <strong>{detectedCount}</strong>
                  <span>
                    {detectedCount === 1
                      ? "POINT ABOVE THRESHOLD"
                      : "POINTS ABOVE THRESHOLD"}
                  </span>
                </div>
              </div>

              <div className="scan-history-toolbar">
                <span>Sorted by frequency: 50 MHz → 6000 MHz</span>
                <span>
                  Backend total: {totalDetectionCount} threshold point
                  {totalDetectionCount === 1 ? "" : "s"}
                </span>
                {sweepInfo && (
                  <span>
                    Window {sweepInfo.scanned_windows}/{sweepInfo.total_windows}
                  </span>
                )}
              </div>

              {currentScanHistorySorted.length === 0 ? (
                <div className="empty-state">
                  {isScanning
                    ? "Belum ada titik yang melewati threshold pada scan ini."
                    : "Belum ada history scan. Tekan START SCAN untuk memulai single sweep."}
                </div>
              ) : (
                <div className="scan-history-table">
                  <div className="scan-history-head">
                    <span>#</span>
                    <span>Frequency</span>
                    <span>Power</span>
                    <span>Window</span>
                    <span>Technology candidates</span>
                  </div>

                  <div className="scan-history-list">
                    {currentScanHistorySorted.map((detection, index) => {
                      const technologyCandidates = buildTechnologyCandidates(detection);

                      return (
                        <article
                          className="scan-history-row"
                          key={detection.history_id ?? `${detection.frequency_mhz}-${index}`}
                        >
                          <span className="scan-history-index">
                            {String(index + 1).padStart(3, "0")}
                          </span>

                          <strong>{formatMHz(detection.frequency_mhz)}</strong>

                          <span className="history-power">
                            {formatDb(detection.power_db)}
                          </span>

                          <span className="history-window">
                            {detection.window_label ??
                              formatWindowMHz(
                                detection.window_start_mhz,
                                detection.window_end_mhz
                              )}
                          </span>

                          <div className="history-candidate-chips">
                            {technologyCandidates.length > 0 ? (
                              technologyCandidates.map((candidate, candidateIndex) => (
                                <span
                                  className={`history-chip ${candidate.type}`}
                                  key={`${candidate.type}-${candidate.name}-${candidateIndex}`}
                                >
                                  <b>{candidate.label}</b> {candidate.name}
                                </span>
                              ))
                            ) : (
                              <span className="history-chip unknown">
                                No candidate
                              </span>
                            )}
                          </div>
                        </article>
                      );
                    })}
                  </div>
                </div>
              )}

              <p className="live-message">{statusMessage}</p>

              {errorMessage && (
                <p className="error-message">{errorMessage}</p>
              )}
            </section>
          </>
        ) : activeTab === "history" ? (
          <section className="detected-section scan-session-section">
            <div className="panel-heading">
              <div>
                <p className="section-kicker">SESSION STORAGE</p>
                <h3>Scan History Folder</h3>
              </div>

              <div className="detected-count">
                <strong>{scanSessions.length}</strong>
                <span>{scanSessions.length === 1 ? "SCAN SESSION" : "SCAN SESSIONS"}</span>
              </div>
            </div>

            {scanSessions.length === 0 ? (
              <div className="empty-state">
                Belum ada folder scan. Jalankan satu sweep sampai selesai,
                lalu hasilnya otomatis masuk ke halaman ini.
              </div>
            ) : (
              <div className="session-history-layout">
                <div className="session-folder-list">
                  {scanSessions.map((session) => (
                    <button
                      type="button"
                      className={`session-folder-card ${
                        selectedScanSession?.id === session.id ? "selected" : ""
                      }`}
                      key={session.id}
                      onClick={() => setSelectedSessionId(session.id)}
                    >
                      <span className="folder-icon">▰</span>
                      <span>
                        <strong>{session.title}</strong>
                        <small>
                          {session.config.start_frequency_mhz}–
                          {session.config.end_frequency_mhz} MHz · {session.detectionCount} points
                        </small>
                      </span>
                    </button>
                  ))}
                </div>

                <div className="session-detail-panel">
                  {selectedScanSession && (
                    <>
                      <div className="session-summary-grid">
                        <div>
                          <span>Range</span>
                          <strong>
                            {selectedScanSession.config.start_frequency_mhz}–
                            {selectedScanSession.config.end_frequency_mhz} MHz
                          </strong>
                        </div>
                        <div>
                          <span>Threshold</span>
                          <strong>{selectedScanSession.config.threshold_db} dB</strong>
                        </div>
                        <div>
                          <span>Total points</span>
                          <strong>{selectedScanSession.detectionCount}</strong>
                        </div>
                        <div>
                          <span>Completed</span>
                          <strong>{formatDateTime(selectedScanSession.completedAt)}</strong>
                        </div>
                      </div>

                      <div className="scan-history-table session-table">
                        <div className="scan-history-head">
                          <span>#</span>
                          <span>Frequency</span>
                          <span>Power</span>
                          <span>Window</span>
                          <span>Technology candidates</span>
                        </div>

                        <div className="scan-history-list">
                          {selectedScanSession.detections.map((detection, index) => {
                            const technologyCandidates = buildTechnologyCandidates(detection);

                            return (
                              <article
                                className="scan-history-row"
                                key={detection.history_id ?? `${detection.frequency_mhz}-${index}`}
                              >
                                <span className="scan-history-index">
                                  {String(index + 1).padStart(3, "0")}
                                </span>

                                <strong>{formatMHz(detection.frequency_mhz)}</strong>

                                <span className="history-power">
                                  {formatDb(detection.power_db)}
                                </span>

                                <span className="history-window">
                                  {detection.window_label ??
                                    formatWindowMHz(
                                      detection.window_start_mhz,
                                      detection.window_end_mhz
                                    )}
                                </span>

                                <div className="history-candidate-chips">
                                  {technologyCandidates.length > 0 ? (
                                    technologyCandidates.map((candidate, candidateIndex) => (
                                      <span
                                        className={`history-chip ${candidate.type}`}
                                        key={`${candidate.type}-${candidate.name}-${candidateIndex}`}
                                      >
                                        <b>{candidate.label}</b> {candidate.name}
                                      </span>
                                    ))
                                  ) : (
                                    <span className="history-chip unknown">
                                      No candidate
                                    </span>
                                  )}
                                </div>
                              </article>
                            );
                          })}
                        </div>
                      </div>
                    </>
                  )}
                </div>
              </div>
            )}
          </section>
        ) : (
          <section className="specific-panel">
            <p className="section-kicker">COMING SOON</p>
            <h3>Specific Channel Scanner</h3>
            <p>
              Halaman Specific akan dibuat setelah spectrum USRP stabil tampil
              di halaman General.
            </p>
          </section>
        )}
      </section>
    </main>
  );
}

export default App;