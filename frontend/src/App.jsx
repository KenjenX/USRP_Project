import { useEffect, useMemo, useState } from "react";
import "./App.css";

const API_BASE_URL = "http://127.0.0.1:8000";

const SPECTRUM_REFRESH_MS = 250;

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

function App() {
  const [activeTab, setActiveTab] = useState("general");

  // Nilai input yang diketik pada web.
  const [threshold, setThreshold] = useState("0");
  const [startFrequency, setStartFrequency] = useState("99");
  const [endFrequency, setEndFrequency] = useState("101");

  // Konfigurasi yang sudah benar-benar dikirim ke backend.
  const [scanConfig, setScanConfig] = useState({
    threshold_db: 0,
    start_frequency_mhz: 99,
    end_frequency_mhz: 101,
    center_frequency_mhz: 100,
    sample_rate_mhz: 2,
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

        setSpectrum(data.spectrum);
        setPeak(data.peak);
        setDetections(
          Array.isArray(data.detections) ? data.detections : []
        );
        setDebugClusters(
          data.debug_clusters ?? {
            merge_gap_mhz: 0.05,
            raw_clusters: [],
            merged_clusters: [],
          }
        );
        setScanConfig(data.config);
        setErrorMessage("");

        if (!data.running) {
          setIsScanning(false);
          setStatusMessage("Scan dihentikan.");
          return;
        }

        setStatusMessage(
          `Spectrum diperbarui: ${data.timestamp || "realtime"}`
        );
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
  // Posisi X memakai frekuensi asli, bukan nomor/index data display.
  const spectrumChart = useMemo(() => {
    const frequencyValues = spectrum.frequency_mhz ?? [];
    const powerValues = spectrum.power_db ?? [];
    const start = Number(scanConfig.start_frequency_mhz);
    const end = Number(scanConfig.end_frequency_mhz);

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
  }, [chartScale, scanConfig, spectrum]);

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

  const detectedCount = detections.length;

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

        {/* <nav className="tabs">
          <button
            type="button"
            className={activeTab === "general" ? "tab active-tab" : "tab"}
            onClick={() => setActiveTab("general")}
          >
            General
          </button>

          <button
            type="button"
            className={activeTab === "specific" ? "tab active-tab" : "tab"}
            onClick={() => setActiveTab("specific")}
          >
            Specific
          </button>
        </nav> */}

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
                    Detected Peak
                  </span>

                  <span>
                    <i className="legend-merged-cluster" />
                    Cluster
                  </span>

                  {SHOW_MERGE_GAP_DEBUG && (
                    <span>
                      <i className="legend-merge-gap" />
                      50 kHz Debug
                    </span>
                  )}
                </div>
              </div>

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

                  {spectrumChart.linePoints ? (
                    <>
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
                  <p className="section-kicker">SCAN RESULT</p>
                  <h3>Frequency Classification</h3>
                </div>

                <div className="detected-count">
                  <strong>{detectedCount}</strong>
                  <span>
                    {detectedCount === 1
                      ? "SIGNAL ABOVE THRESHOLD"
                      : "SIGNALS ABOVE THRESHOLD"}
                  </span>
                </div>
              </div>

              {!peak ? (
                <div className="empty-state">
                  {isScanning
                    ? "Menerima data spectrum dari USRP..."
                    : "Belum ada peak dari USRP. Jalankan scan terlebih dahulu."}
                </div>
              ) : detections.length === 0 ? (
                <div className="empty-state">
                  Tidak ada sinyal yang menyentuh atau melewati threshold.
                </div>
              ) : (
                <div className="classification-grid">
                  {detections.map((detection, index) => {
                    const gsmCandidate = detection.gsm;
                    const umtsCandidates = Array.isArray(detection.umts)
                      ? detection.umts
                      : [];

                    // Nanti LTE dan NR dapat ditambahkan ke array
                    // ini dengan format data card yang sama.
                    const technologyCandidates = [
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
                        profiles: gsmCandidate.possible_profiles ?? [],
                      },
                      ...umtsCandidates.map((candidate) => ({
                        type: "umts",
                        label: "3G",
                        // Tampilkan nama asli dari tabel Sqimway,
                        // contoh: "900 GSM", bukan "UMTS Band 8".
                        name:
                          candidate.name ??
                          candidate.band ??
                          "UMTS Candidate",
                        detail:
                          candidate.uarfcn_dl === null ||
                          candidate.uarfcn_dl === undefined
                            ? "UARFCN : -"
                            : `UARFCN : [ ${candidate.uarfcn_dl} ]`,
                        dlMhz: candidate.freq_dl_mhz,
                        ulMhz: candidate.freq_ul_mhz,
                        profiles: [candidate.band_code].filter(Boolean),
                      })),
                    ].filter(Boolean);

                    const primaryCandidate =
                      technologyCandidates[0] ?? null;

                    const signalColor =
                      DETECTION_MARKER_COLORS[
                        index % DETECTION_MARKER_COLORS.length
                      ];

                    return (
                      <article
                        className="signal-detection-card"
                        key={`${detection.frequency_mhz}-${index}`}
                        style={{ "--signal-color": signalColor }}
                      >
                        <header className="signal-detection-header">
                          <div>
                            <p className="signal-detection-label">
                              SIGNAL {String(index + 1).padStart(2, "0")} ·
                              DETECTED ABOVE THRESHOLD
                            </p>

                            <h4>
                              {formatMHz(detection.frequency_mhz)}
                            </h4>
                          </div>

                          <span className="signal-detection-power">
                            {formatDb(detection.power_db)}
                          </span>
                        </header>

                        {primaryCandidate && (
                          <div className="signal-frequency-pair">
                            <span>
                              DL: {formatMHz(primaryCandidate.dlMhz)}
                            </span>

                            <span>
                              UL: {formatMHz(primaryCandidate.ulMhz)}
                            </span>
                          </div>
                        )}

                        <p className="technology-candidate-title">
                          TECHNOLOGY CANDIDATES
                        </p>

                        {technologyCandidates.length > 0 ? (
                          <div className="technology-candidate-grid">
                            {technologyCandidates.map((candidate) => (
                              <article
                                className={`technology-mini-card ${candidate.type}`}
                                key={`${candidate.type}-${candidate.name}`}
                              >
                                <div className="technology-mini-header">
                                  <span className="technology-mini-icon">
                                    {candidate.label}
                                  </span>

                                  <div className="technology-mini-info">
                                    <strong>{candidate.name}</strong>
                                    <span>{candidate.detail}</span>
                                  </div>
                                </div>
                              </article>
                            ))}
                          </div>
                        ) : (
                          <div className="no-technology-match">
                            No 2G/3G candidate match for this signal.
                          </div>
                        )}
                      </article>
                    );
                  })}
                </div>
              )}

              <p className="live-message">{statusMessage}</p>

              {errorMessage && (
                <p className="error-message">{errorMessage}</p>
              )}
            </section>
          </>
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