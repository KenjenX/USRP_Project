import { useEffect, useMemo, useState } from "react";
import "./App.css";

const API_BASE_URL = "http://127.0.0.1:8000";

const CHART_MIN_DB = -80;
const CHART_MAX_DB = 10;

function clamp(value, minimum, maximum) {
  return Math.min(Math.max(value, minimum), maximum);
}

function formatMHz(value) {
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

  // Ambil data spectrum baru setiap 500 ms saat scan berjalan.
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
        timeoutId = window.setTimeout(pollSpectrum, 50);
      }
    }

    pollSpectrum();

    return () => {
      cancelled = true;
      window.clearTimeout(timeoutId);
    };
  }, [isScanning]);

  // Buat angka sumbu X berdasarkan konfigurasi scan asli.
  const frequencyTicks = useMemo(() => {
    const start = Number(scanConfig.start_frequency_mhz);
    const end = Number(scanConfig.end_frequency_mhz);

    return Array.from({ length: 5 }, (_, index) => {
      const value = start + ((end - start) / 4) * index;
      return `${Number(value.toFixed(2))} MHz`;
    });
  }, [scanConfig]);

  // Ubah power_db dari backend menjadi titik SVG.
  const spectrumPoints = useMemo(() => {
    const powerValues = spectrum.power_db;

    if (!powerValues || powerValues.length === 0) {
      return "";
    }

    return powerValues
      .map((powerValue, index) => {
        const x =
          powerValues.length === 1
            ? 0
            : (index / (powerValues.length - 1)) * 1000;

        const normalizedY =
          ((CHART_MAX_DB - Number(powerValue)) /
            (CHART_MAX_DB - CHART_MIN_DB)) *
          260;

        const y = clamp(normalizedY, 0, 260);

        return `${x.toFixed(2)},${y.toFixed(2)}`;
      })
      .join(" ");
  }, [spectrum]);

  // Posisi garis threshold pada grafik.
  const thresholdTop = useMemo(() => {
    const value = Number(scanConfig.threshold_db);

    const position =
      ((CHART_MAX_DB - value) / (CHART_MAX_DB - CHART_MIN_DB)) * 100;

    return clamp(position, 0, 100);
  }, [scanConfig]);

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
      setIsScanning(true);
      setStatusMessage("Scan USRP dimulai. Menunggu data spectrum...");
    } catch (error) {
      setErrorMessage(error.message);
      setStatusMessage("Scan belum dimulai.");
    } finally {
      setIsBusy(false);
    }
  }

  const detectedCount = peak?.above_threshold ? 1 : 0;

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
            className={activeTab === "specific" ? "tab active-tab" : "tab"}
            onClick={() => setActiveTab("specific")}
          >
            Specific
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
                </div>
              </div>

              <div className="spectrum-chart">
                <div className="chart-y-label top">{CHART_MAX_DB} dB</div>
                <div className="chart-y-label middle">
                  {(CHART_MAX_DB + CHART_MIN_DB) / 2} dB
                </div>
                <div className="chart-y-label bottom">{CHART_MIN_DB} dB</div>

                <div className="grid-line grid-1" />
                <div className="grid-line grid-2" />
                <div className="grid-line grid-3" />
                <div className="grid-line grid-4" />

                <div
                  className="threshold-visual"
                  style={{ top: `${thresholdTop}%` }}
                />

                {spectrumPoints ? (
                  <svg
                    className="spectrum-svg"
                    viewBox="0 0 1000 260"
                    preserveAspectRatio="none"
                    aria-label="USRP realtime spectrum"
                  >
                    <polyline
                      points={spectrumPoints}
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="3"
                    />
                  </svg>
                ) : (
                  <div className="chart-placeholder">
                    {isScanning
                      ? "Menerima IQ sample dari USRP..."
                      : "Tekan START SCAN untuk melihat spectrum."}
                  </div>
                )}

                <div className="chart-x-axis">
                  {frequencyTicks.map((frequency) => (
                    <span key={frequency}>{frequency}</span>
                  ))}
                </div>
              </div>
            </section>

            <section className="detected-section">
              <div className="panel-heading">
                <div>
                  <p className="section-kicker">SCAN RESULT</p>
                  <h3>Frequency Detected</h3>
                </div>

                <div className="detected-count">
                  <strong>{detectedCount}</strong>
                  <span>Peak Above Threshold</span>
                </div>
              </div>

              {peak ? (
                <div className="frequency-grid">
                  <article className="frequency-card">
                    <div className="card-top">
                      <span className="technology-tag">LIVE PEAK SIGNAL</span>

                      <span
                        className={
                          peak.above_threshold
                            ? "result-status detected"
                            : "result-status candidate"
                        }
                      >
                        {peak.above_threshold ? "WARNING" : "NORMAL"}
                      </span>
                    </div>

                    <h4>USRP B210 · RX2</h4>

                    <div className="frequency-detail">
                      <span>PEAK FREQUENCY</span>
                      <strong>{formatMHz(peak.frequency_mhz)}</strong>
                    </div>

                    <div className="frequency-detail">
                      <span>PEAK POWER</span>
                      <strong>{formatDb(peak.power_db)}</strong>
                    </div>

                    <div className="frequency-detail">
                      <span>THRESHOLD</span>
                      <strong>{scanConfig.threshold_db} dB</strong>
                    </div>
                  </article>
                </div>
              ) : (
                <div className="empty-state">
                  Belum ada peak dari USRP. Jalankan scan terlebih dahulu.
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