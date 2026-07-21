import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import "./App.css";
import SpecificChannelPage from "./SpecificChannelPage.jsx";

const API_BASE_URL = "http://127.0.0.1:8000";

const SPECTRUM_REFRESH_MS = 250;

// Saat Vite dan FastAPI dinyalakan hampir bersamaan, frontend dapat terbuka
// beberapa detik lebih dulu daripada backend. Scan history akan dicoba ulang
// otomatis agar user tidak perlu me-refresh halaman secara manual.
const INITIAL_HISTORY_RETRY_DELAYS_MS = [0, 1000, 2000, 4000, 8000];

// Tidak ada polling otomatis /api/device.
// USRP hanya diakses ketika user menjalankan scan agar CRUD tetap independen.

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
          ? "DL Pasangan : -"
          : `DL Pasangan : [ ${candidate.nr_arfcn_dl} ]`,
      ];
    }

    return [
      "FDD · Detected DL",
      candidate.nr_arfcn_dl === null || candidate.nr_arfcn_dl === undefined
        ? "DL ARFCN : -"
        : `DL ARFCN : [ ${candidate.nr_arfcn_dl} ]`,
      candidate.nr_arfcn_ul === null || candidate.nr_arfcn_ul === undefined
        ? "UL Pasangan : -"
        : `UL Pasangan : [ ${candidate.nr_arfcn_ul} ]`,
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


function normalizeDetailLines(detail) {
  if (Array.isArray(detail)) {
    return detail.filter(Boolean);
  }

  if (detail === null || detail === undefined || detail === "") {
    return [];
  }

  return [String(detail)];
}

function formatDetailValue(value) {
  if (value === null || value === undefined || value === "") {
    return "-";
  }

  return String(value);
}


function normalizeDetectedSide(side) {
  if (side === null || side === undefined || side === "") {
    return null;
  }

  const value = String(side).toUpperCase();

  if (value.includes("TDD")) {
    return "TDD";
  }

  if (value.includes("SDL")) {
    return "DL";
  }

  if (value.includes("SUL")) {
    return "UL";
  }

  if (value === "DL" || value === "DOWNLINK") {
    return "DL";
  }

  if (value === "UL" || value === "UPLINK") {
    return "UL";
  }

  return value;
}

function formatDetectedSide(side) {
  const normalized = normalizeDetectedSide(side);

  if (normalized === "DL") {
    return "DL / Downlink";
  }

  if (normalized === "UL") {
    return "UL / Uplink";
  }

  if (normalized === "TDD") {
    return "TDD / Shared DL-UL";
  }

  return normalized ?? "-";
}

function getLteDetectedSide(candidate) {
  const direction = normalizeDetectedSide(candidate.direction);
  const mode = normalizeDetectedSide(candidate.duplex_mode);

  if (direction) {
    return direction;
  }

  if (mode === "TDD") {
    return "TDD";
  }

  return "DL";
}

function getNrDetectedSide(candidate) {
  const direction = normalizeDetectedSide(candidate.direction);
  const mode = normalizeDetectedSide(candidate.mode);

  if (direction) {
    return direction;
  }

  if (mode === "TDD") {
    return "TDD";
  }

  if (mode === "SDL") {
    return "DL";
  }

  if (mode === "SUL") {
    return "UL";
  }

  return "DL";
}

function buildFrequencyRows(
  dlMhz,
  ulMhz,
  fallbackMhz = null,
  detectedSide = null
) {
  const side = normalizeDetectedSide(detectedSide);
  const rows = [];

  function sideSuffix(rowSide) {
    if (side === "TDD") {
      return " (TDD)";
    }

    if (side === rowSide) {
      return " (TERDETEKSI)";
    }

    if ((side === "DL" || side === "UL") && side !== rowSide) {
      return " (PASANGAN)";
    }

    return "";
  }

  if (dlMhz !== null && dlMhz !== undefined) {
    rows.push({ label: `FREQ DL${sideSuffix("DL")}`, value: formatMHz(dlMhz) });
  }

  if (ulMhz !== null && ulMhz !== undefined) {
    rows.push({ label: `FREQ UL${sideSuffix("UL")}`, value: formatMHz(ulMhz) });
  }

  if (rows.length === 0 && fallbackMhz !== null && fallbackMhz !== undefined) {
    rows.push({
      label: side === "TDD" ? "FREQ (TDD)" : "FREQ (TERDETEKSI)",
      value: formatMHz(fallbackMhz),
    });
  }

  return rows;
}

function buildLteChannelRows(candidate) {
  const detectedSide = getLteDetectedSide(candidate);

  if (detectedSide === "TDD") {
    return [
      {
        label: "EARFCN (TDD)",
        value: formatDetailValue(candidate.earfcn ?? candidate.earfcn_dl),
      },
    ];
  }

  const rows = [];

  if (candidate.earfcn_dl !== null && candidate.earfcn_dl !== undefined) {
    rows.push({
      label: detectedSide === "DL" ? "DL EARFCN (TERDETEKSI)" : "DL EARFCN (PASANGAN)",
      value: formatDetailValue(candidate.earfcn_dl),
    });
  }

  if (candidate.earfcn_ul !== null && candidate.earfcn_ul !== undefined) {
    rows.push({
      label: detectedSide === "UL" ? "UL EARFCN (TERDETEKSI)" : "UL EARFCN (PASANGAN)",
      value: formatDetailValue(candidate.earfcn_ul),
    });
  }

  if (rows.length === 0) {
    rows.push({ label: "EARFCN", value: formatDetailValue(candidate.earfcn) });
  }

  return rows;
}

function buildNrChannelRows(candidate) {
  const duplex = normalizeDetectedSide(candidate.mode ?? "NR");
  const detectedSide = getNrDetectedSide(candidate);

  if (duplex === "TDD" || detectedSide === "TDD") {
    return [
      {
        label: "NR-ARFCN (TDD)",
        value: formatDetailValue(
          candidate.nr_arfcn ?? candidate.nr_arfcn_dl ?? candidate.nr_arfcn_ul
        ),
      },
    ];
  }

  if (duplex === "SDL") {
    return [
      {
        label: "DL NR-ARFCN (TERDETEKSI)",
        value: formatDetailValue(candidate.nr_arfcn_dl),
      },
    ];
  }

  if (duplex === "SUL") {
    return [
      {
        label: "UL NR-ARFCN (TERDETEKSI)",
        value: formatDetailValue(candidate.nr_arfcn_ul),
      },
    ];
  }

  const rows = [];

  if (candidate.nr_arfcn_dl !== null && candidate.nr_arfcn_dl !== undefined) {
    rows.push({
      label: detectedSide === "DL" ? "DL NR-ARFCN (TERDETEKSI)" : "DL NR-ARFCN (PASANGAN)",
      value: formatDetailValue(candidate.nr_arfcn_dl),
    });
  }

  if (candidate.nr_arfcn_ul !== null && candidate.nr_arfcn_ul !== undefined) {
    rows.push({
      label: detectedSide === "UL" ? "UL NR-ARFCN (TERDETEKSI)" : "UL NR-ARFCN (PASANGAN)",
      value: formatDetailValue(candidate.nr_arfcn_ul),
    });
  }

  if (rows.length === 0) {
    rows.push({
      label: "NR-ARFCN",
      value: formatDetailValue(candidate.nr_arfcn),
    });
  }

  return rows;
}

function buildModeTitle(type, candidate = {}) {
  if (type === "gsm") {
    return "2G GSM";
  }

  if (type === "umts") {
    return "3G UMTS / WCDMA";
  }

  if (type === "lte") {
    const mode = candidate.duplex_mode ?? candidate.direction ?? "LTE";

    if (mode === "TDD" || candidate.direction === "TDD") {
      return "4G TDD-LTE";
    }

    if (mode === "FDD" || candidate.direction === "DL" || candidate.direction === "UL") {
      return "4G FDD-LTE";
    }

    return "4G LTE";
  }

  if (type === "nr") {
    const mode = candidate.mode ?? candidate.direction ?? "NR";

    if (mode === "TDD" || candidate.direction === "TDD") {
      return "5G NR TDD";
    }

    if (mode === "FDD" || candidate.direction === "DL" || candidate.direction === "UL") {
      return "5G NR FDD";
    }

    if (mode === "SDL") {
      return "5G NR SDL";
    }

    if (mode === "SUL") {
      return "5G NR SUL";
    }

    return "5G NR";
  }

  return "Unknown";
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
      modeTitle: buildModeTitle("gsm", gsmCandidate),
      bandTitle: gsmCandidate.band,
      detail:
        gsmCandidate.arfcn === "Dynamic"
          ? "ARFCN : Dynamic"
          : `ARFCN : [ ${gsmCandidate.arfcn} ]`,
      channelRows: [
        {
          label: "ARFCN",
          value: formatDetailValue(gsmCandidate.arfcn),
        },
      ],
      detectedSide: "DL",
      detectedSideLabel: formatDetectedSide("DL"),
      frequencyRows: buildFrequencyRows(
        gsmCandidate.freq_dl_mhz,
        gsmCandidate.freq_ul_mhz,
        detection.frequency_mhz,
        "DL"
      ),
      dlMhz: gsmCandidate.freq_dl_mhz,
      ulMhz: gsmCandidate.freq_ul_mhz,
    },
    ...umtsCandidates.map((candidate) => ({
      type: "umts",
      label: "3G",
      name: candidate.name ?? candidate.band ?? "UMTS Candidate",
      modeTitle: buildModeTitle("umts", candidate),
      bandTitle: candidate.name ?? candidate.band ?? "UMTS Candidate",
      detail:
        candidate.uarfcn_dl === null || candidate.uarfcn_dl === undefined
          ? "UARFCN : -"
          : `UARFCN : [ ${candidate.uarfcn_dl} ]`,
      channelRows: [
        { label: "UARFCN DL (TERDETEKSI)", value: formatDetailValue(candidate.uarfcn_dl) },
        { label: "UARFCN UL (PASANGAN)", value: formatDetailValue(candidate.uarfcn_ul) },
      ],
      detectedSide: "DL",
      detectedSideLabel: formatDetectedSide("DL"),
      frequencyRows: buildFrequencyRows(
        candidate.freq_dl_mhz,
        candidate.freq_ul_mhz,
        detection.frequency_mhz,
        "DL"
      ),
      dlMhz: candidate.freq_dl_mhz,
      ulMhz: candidate.freq_ul_mhz,
    })),
    ...lteCandidates.map((candidate) => ({
      type: "lte",
      label: "4G",
      name: candidate.name ?? candidate.band ?? "LTE Candidate",
      modeTitle: buildModeTitle("lte", candidate),
      bandTitle: candidate.band_code
        ? `${candidate.band_code} - ${candidate.name ?? candidate.band ?? "LTE"}`
        : candidate.name ?? candidate.band ?? "LTE Candidate",
      detail: buildLteDetail(candidate),
      channelRows: buildLteChannelRows(candidate),
      detectedSide: getLteDetectedSide(candidate),
      detectedSideLabel: formatDetectedSide(getLteDetectedSide(candidate)),
      frequencyRows: buildFrequencyRows(
        candidate.freq_dl_mhz,
        candidate.freq_ul_mhz,
        detection.frequency_mhz,
        getLteDetectedSide(candidate)
      ),
      dlMhz: candidate.freq_dl_mhz,
      ulMhz: candidate.freq_ul_mhz,
    })),
    ...nrCandidates.map((candidate) => ({
      type: "nr",
      label: "5G",
      name: candidate.name ?? candidate.band ?? "NR Candidate",
      modeTitle: buildModeTitle("nr", candidate),
      bandTitle: candidate.band_code
        ? `${candidate.band_code} - ${candidate.band_name ?? candidate.name ?? "NR"}`
        : candidate.name ?? candidate.band ?? "NR Candidate",
      detail: buildNrDetail(candidate),
      channelRows: buildNrChannelRows(candidate),
      detectedSide: getNrDetectedSide(candidate),
      detectedSideLabel: formatDetectedSide(getNrDetectedSide(candidate)),
      frequencyRows: buildFrequencyRows(
        candidate.freq_dl_mhz,
        candidate.freq_ul_mhz,
        detection.frequency_mhz,
        getNrDetectedSide(candidate)
      ),
      dlMhz: candidate.freq_dl_mhz,
      ulMhz: candidate.freq_ul_mhz,
    })),
  ].filter(Boolean);
}


const HISTORY_TECHNOLOGY_GROUPS = [
  { key: "gsm", label: "2G" },
  { key: "umts", label: "3G" },
  { key: "lte", label: "4G" },
  { key: "nr", label: "5G" },
];

function TechnologyBandCard({ candidate }) {
  return (
    <span
      className={`figma-band-card ${candidate.type}`}
      title={`${candidate.modeTitle} · ${candidate.bandTitle ?? candidate.name}`}
    >
      <span className="figma-band-icon" aria-hidden="true">
        ◉
      </span>

      <span className="figma-band-text">
        <strong>{candidate.modeTitle}</strong>
        <small>{candidate.bandTitle ?? candidate.name}</small>
      </span>
    </span>
  );
}

function getDetectionDlUlSummary(technologyCandidates, detection) {
  const candidate =
    technologyCandidates.find(
      (item) => item.dlMhz !== null && item.dlMhz !== undefined &&
        item.ulMhz !== null && item.ulMhz !== undefined
    ) ??
    technologyCandidates.find(
      (item) => item.dlMhz !== null || item.ulMhz !== null || item.detectedSide === "TDD"
    ) ??
    null;

  if (!candidate) {
    return {
      dl: "-",
      ul: "-",
    };
  }

  const detectedFrequency = detection.frequency_mhz;
  const isTdd = candidate.detectedSide === "TDD";

  return {
    dl:
      candidate.dlMhz !== null && candidate.dlMhz !== undefined
        ? formatMHz(candidate.dlMhz)
        : isTdd
          ? formatMHz(detectedFrequency)
          : "-",
    ul:
      candidate.ulMhz !== null && candidate.ulMhz !== undefined
        ? formatMHz(candidate.ulMhz)
        : isTdd
          ? formatMHz(detectedFrequency)
          : "-",
  };
}

function DetectionHistoryCard({ detection, index, sourceLabel, onOpen }) {
  const technologyCandidates = buildTechnologyCandidates(detection);
  const dlUlSummary = getDetectionDlUlSummary(technologyCandidates, detection);

  function openDetail() {
    onOpen({
      detection,
      displayIndex: index + 1,
      sourceLabel,
    });
  }

  return (
    <article
      className="figma-signal-card clickable"
      key={detection.history_id ?? `${detection.frequency_mhz}-${index}`}
      role="button"
      tabIndex={0}
      onClick={openDetail}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          openDetail();
        }
      }}
    >
      <div className="figma-signal-topline">
        <span className="figma-signal-number">
          POINT {String(index + 1).padStart(3, "0")}
        </span>
      </div>

      <div className="figma-signal-main-info">
        <div>
          <span>Detected Frequency</span>
          <strong>{formatMHz(detection.frequency_mhz)}</strong>
        </div>

        <div>
          <span>Power dB</span>
          <strong>{formatDb(detection.power_db)}</strong>
        </div>

        <div>
          <span>DL</span>
          <strong>{dlUlSummary.dl}</strong>
        </div>

        <div>
          <span>UL</span>
          <strong>{dlUlSummary.ul}</strong>
        </div>
      </div>

      {technologyCandidates.length === 0 ? (
        <div className="figma-band-empty">No 2G/3G/4G/5G candidate</div>
      ) : (
        <div className="figma-band-grid">
          {technologyCandidates.map((candidate, candidateIndex) => (
            <TechnologyBandCard
              candidate={candidate}
              key={`${candidate.type}-${candidate.name}-${candidateIndex}`}
            />
          ))}
        </div>
      )}
    </article>
  );
}

function DetectionCardGrid({ detections, sourceLabel, onOpen }) {
  return (
    <div className="figma-signal-card-grid">
      {detections.map((detection, index) => (
        <DetectionHistoryCard
          detection={detection}
          index={index}
          key={detection.history_id ?? `${detection.frequency_mhz}-${index}`}
          sourceLabel={sourceLabel}
          onOpen={onOpen}
        />
      ))}
    </div>
  );
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



function normalizePersistentDetection(detection, index = 0) {
  return {
    ...detection,
    history_id:
      detection.history_id ?? buildDetectionHistoryId(detection, index),
    window_label:
      detection.window_label ??
      formatWindowMHz(
        detection.window_start_mhz,
        detection.window_end_mhz
      ),
  };
}

function normalizeSpectrumPreview(preview) {
  if (!preview || typeof preview !== "object") {
    return null;
  }

  const frequencyValues = Array.isArray(preview.frequency_mhz)
    ? preview.frequency_mhz.map(Number)
    : [];
  const powerValues = Array.isArray(preview.power_db)
    ? preview.power_db.map(Number)
    : [];
  const pointCount = Math.min(frequencyValues.length, powerValues.length);

  if (pointCount === 0) {
    return null;
  }

  const normalizedFrequency = [];
  const normalizedPower = [];

  for (let index = 0; index < pointCount; index += 1) {
    const frequency = frequencyValues[index];
    const power = powerValues[index];

    if (!Number.isFinite(frequency) || !Number.isFinite(power)) {
      continue;
    }

    normalizedFrequency.push(frequency);
    normalizedPower.push(power);
  }

  if (normalizedFrequency.length === 0) {
    return null;
  }

  return {
    ...preview,
    frequency_mhz: normalizedFrequency,
    power_db: normalizedPower,
    point_count: normalizedFrequency.length,
  };
}


function normalizePersistentScanSession(session, index = 0) {
  const detections = Array.isArray(session.detections)
    ? session.detections.map((detection, detectionIndex) =>
        normalizePersistentDetection(detection, detectionIndex)
      )
    : [];

  const id =
    session.id ??
    session.session_id ??
    `scan-history-${index}`;

  const completedAt =
    session.completedAt ??
    session.completed_at ??
    session.updated_at ??
    session.started_at ??
    null;

  return {
    ...session,
    id,
    title:
      session.title ??
      `Scan #${String(index + 1).padStart(3, "0")}`,
    startedAt:
      session.startedAt ??
      session.started_at ??
      completedAt,
    completedAt,
    config: session.config ?? {},
    sweep: session.sweep ?? {},
    peak: session.peak ?? null,
    spectrumPreview: normalizeSpectrumPreview(
      session.spectrumPreview ?? session.spectrum_preview
    ),
    detections,
    detectionCount:
      Number.isFinite(Number(session.detectionCount))
        ? Number(session.detectionCount)
        : Number.isFinite(Number(session.detection_count))
          ? Number(session.detection_count)
          : detections.length,
  };
}



function HistoricalSpectrumPanel({ session }) {
  const preview = session?.spectrumPreview ?? null;
  const config = session?.config ?? {};
  const thresholdValue = Number(
    preview?.threshold_db ?? config.threshold_db ?? 0
  );
  const start = Number(
    preview?.start_frequency_mhz ?? config.start_frequency_mhz
  );
  const end = Number(
    preview?.end_frequency_mhz ?? config.end_frequency_mhz
  );

  const chartScale = useMemo(() => {
    const safeThreshold = Number.isFinite(thresholdValue)
      ? thresholdValue
      : 0;
    const minDb = CHART_REFERENCE_MIN_DB;
    const maxDb =
      (safeThreshold - THRESHOLD_TARGET_TOP_RATIO * minDb) /
      (1 - THRESHOLD_TARGET_TOP_RATIO);

    return { minDb, maxDb };
  }, [thresholdValue]);

  const chartPath = useMemo(() => {
    if (!preview) {
      return { linePoints: "", areaPoints: "" };
    }

    return buildSpectrumSvgPath({
      frequencyValues: preview.frequency_mhz ?? [],
      powerValues: preview.power_db ?? [],
      start,
      end,
      chartScale,
    });
  }, [preview, start, end, chartScale]);

  const frequencyTicks = useMemo(() => {
    if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) {
      return [];
    }

    const tickCount = 10;

    return Array.from({ length: tickCount + 1 }, (_, index) => {
      const value = start + ((end - start) / tickCount) * index;

      return {
        label: Number(value.toFixed(2)).toString(),
        position: (index / tickCount) * 100,
      };
    });
  }, [start, end]);

  const chartDbTicks = useMemo(() => {
    const safeThreshold = Number.isFinite(thresholdValue)
      ? thresholdValue
      : 0;
    const values = [-100, -50, safeThreshold]
      .filter(
        (value, index, source) =>
          value >= chartScale.minDb &&
          value <= chartScale.maxDb &&
          source.findIndex((item) => Math.abs(item - value) < 0.001) === index
      )
      .sort((a, b) => b - a);

    return values.map((value) => ({
      value,
      position:
        ((chartScale.maxDb - value) /
          (chartScale.maxDb - chartScale.minDb)) *
        100,
      isThreshold: Math.abs(value - safeThreshold) < 0.001,
    }));
  }, [chartScale, thresholdValue]);

  const thresholdTop = useMemo(() => {
    const value = Number.isFinite(thresholdValue) ? thresholdValue : 0;

    return clamp(
      ((chartScale.maxDb - value) /
        (chartScale.maxDb - chartScale.minDb)) *
        100,
      0,
      100
    );
  }, [chartScale, thresholdValue]);

  return (
    <section className="history-spectrum-preview">
      <div className="history-spectrum-heading">
        <div>
          <p className="section-kicker">SAVED SPECTRUM</p>
          <h4>Historical Spectrum Preview</h4>
        </div>

        {preview && (
          <div className="history-spectrum-meta">
            <span>{preview.point_count ?? preview.frequency_mhz.length} preview points</span>
            <span>{preview.source_point_count ?? "-"} source FFT points</span>
          </div>
        )}
      </div>

      {!preview || !chartPath.linePoints ? (
        <div className="history-spectrum-unavailable">
          Spectrum preview tidak tersedia untuk session lama. Jalankan scan baru
          setelah update backend untuk menyimpan visual grafik.
        </div>
      ) : (
        <div className="spectrum-chart history-spectrum-chart">
          <div className="chart-y-axis" aria-hidden="true">
            {chartDbTicks.map(({ value, position, isThreshold }) => (
              <span
                key={`history-y-${value}`}
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
                key={`history-horizontal-${value}`}
                className="chart-h-grid-line"
                style={{ top: `${position}%` }}
              />
            ))}

            {frequencyTicks.map(({ label, position }) => (
              <div
                key={`history-vertical-${label}-${position}`}
                className="chart-v-grid-line"
                style={{ left: `${position}%` }}
              />
            ))}

            <div
              className="threshold-visual"
              style={{ top: `${thresholdTop}%` }}
            >
              <span>Threshold {Number.isFinite(thresholdValue) ? thresholdValue : 0} dB</span>
            </div>

            <svg
              className="spectrum-svg"
              viewBox={`0 0 1000 ${CHART_SVG_HEIGHT}`}
              preserveAspectRatio="none"
              aria-label="Historical spectrum preview"
            >
              <polygon
                points={chartPath.areaPoints}
                className="spectrum-area"
              />

              <polyline
                points={chartPath.linePoints}
                fill="none"
                stroke="currentColor"
                strokeWidth="1.25"
                vectorEffect="non-scaling-stroke"
                strokeLinecap="round"
                strokeLinejoin="round"
                shapeRendering="geometricPrecision"
              />
            </svg>
          </div>

          <div className="chart-x-axis" aria-hidden="true">
            {frequencyTicks.map(({ label, position }, index) => (
              <span
                key={`history-x-${label}-${position}`}
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
      )}
    </section>
  );
}


const TECHNOLOGY_DETAIL_GROUPS = [
  {
    key: "gsm",
    label: "2G",
    title: "2G GSM",
    className: "gsm",
  },
  {
    key: "umts",
    label: "3G",
    title: "3G UMTS / WCDMA",
    className: "umts",
  },
  {
    key: "lte",
    label: "4G",
    title: "4G LTE",
    className: "lte",
  },
  {
    key: "nr",
    label: "5G",
    title: "5G NR",
    className: "nr",
  },
];

function buildTechnologyCandidateGroups(technologyCandidates) {
  return TECHNOLOGY_DETAIL_GROUPS.map((group) => ({
    ...group,
    candidates: technologyCandidates.filter(
      (candidate) => candidate.type === group.key
    ),
  })).filter((group) => group.candidates.length > 0);
}

function SignalDetailModal({ detail, onClose }) {
  const hasDetection = Boolean(detail?.detection);
  const detection = detail?.detection ?? {};
  const displayIndex = detail?.displayIndex ?? 0;
  const sourceLabel = detail?.sourceLabel ?? "SCAN POINT";
  const technologyCandidates = hasDetection
    ? buildTechnologyCandidates(detection)
    : [];
  const technologyGroups = buildTechnologyCandidateGroups(technologyCandidates);
  const detailKey = hasDetection
    ? `${detection.window_index ?? ""}-${detection.fft_index ?? ""}-${detection.frequency_mhz ?? ""}`
    : "empty";

  const [openTechnologyGroups, setOpenTechnologyGroups] = useState({});

  useEffect(() => {
    setOpenTechnologyGroups({});
  }, [detailKey]);

  function toggleTechnologyGroup(groupKey) {
    setOpenTechnologyGroups((previousState) => ({
      ...previousState,
      [groupKey]: !previousState[groupKey],
    }));
  }

  const candidateSummary = TECHNOLOGY_DETAIL_GROUPS.map((group) => ({
    ...group,
    count: technologyCandidates.filter(
      (candidate) => candidate.type === group.key
    ).length,
  }));

  if (!hasDetection) {
    return null;
  }

  return (
    <div
      className="signal-detail-backdrop"
      role="presentation"
      onClick={onClose}
    >
      <section
        className="signal-detail-modal"
        role="dialog"
        aria-modal="true"
        aria-label="Signal detail"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="signal-detail-header">
          <div>
            <p className="signal-detail-kicker">
              {sourceLabel ?? "SCAN POINT"}
            </p>
            <h3>POINT - {String(displayIndex).padStart(3, "0")}</h3>
          </div>

          <button
            type="button"
            className="signal-detail-close"
            onClick={onClose}
            aria-label="Close signal detail"
          >
            ×
          </button>
        </header>

        <div className="signal-detail-status-row">
          <span className="signal-detail-status active">ABOVE THRESHOLD</span>
        </div>

        <div className="signal-detail-summary-grid">
          <div className="signal-detail-summary-card wide">
            <span>Detected Frequency</span>
            <strong>{formatMHz(detection.frequency_mhz)}</strong>
          </div>

          <div className="signal-detail-summary-card">
            <span>Power</span>
            <strong>{formatDb(detection.power_db)}</strong>
          </div>

          <div className="signal-detail-summary-card">
            <span>Threshold</span>
            <strong>{formatDb(detection.threshold_db)}</strong>
          </div>

        </div>

        <p className="signal-detail-section-title">Technology Candidate Summary</p>

        <div className="signal-detail-candidate-summary-grid">
          {candidateSummary.map((group) => (
            <div
              className={`signal-detail-candidate-summary-card ${group.className}`}
              key={group.key}
            >
              <span>{group.label}</span>
              <strong>{group.count}</strong>
              <small>{group.count === 1 ? "candidate" : "candidates"}</small>
            </div>
          ))}
        </div>

        <p className="signal-detail-section-title">Technology Candidate Details</p>

        {technologyGroups.length === 0 ? (
          <div className="signal-detail-empty">
            No 2G/3G/4G/5G candidate match for this signal.
          </div>
        ) : (
          <div className="signal-detail-accordion-list">
            {technologyGroups.map((group) => {
              const isOpen = Boolean(openTechnologyGroups[group.key]);

              return (
                <section
                  className={`signal-detail-technology-group ${group.className} ${
                    isOpen ? "open" : ""
                  }`}
                  key={group.key}
                >
                  <button
                    type="button"
                    className="signal-detail-technology-toggle"
                    onClick={() => toggleTechnologyGroup(group.key)}
                    aria-expanded={isOpen}
                  >
                    <span className="technology-toggle-left">
                      <i>{group.label}</i>
                      <strong>{group.title}</strong>
                    </span>

                    <span className="technology-toggle-right">
                      {group.candidates.length} {group.candidates.length === 1 ? "candidate" : "candidates"}
                      <b>{isOpen ? "▾" : "▸"}</b>
                    </span>
                  </button>

                  {isOpen && (
                    <div className="signal-detail-candidate-list compact">
                      {group.candidates.map((candidate, index) => (
                        <article
                          className={`signal-detail-candidate-card ${candidate.type}`}
                          key={`${candidate.type}-${candidate.name}-${index}`}
                        >
                          <div className="candidate-detail-header compact">
                            <span>{candidate.label}</span>
                            <strong>{candidate.modeTitle}</strong>
                          </div>

                          <div className="candidate-detail-main-grid">
                            <div>
                              <span>Band</span>
                              <strong>{candidate.bandTitle ?? candidate.name}</strong>
                            </div>

                            <div className="candidate-detected-side">
                              <span>Detected Side</span>
                              <strong>{candidate.detectedSideLabel ?? "-"}</strong>
                            </div>

                            {(candidate.channelRows ?? []).map((row) => (
                              <div key={`${candidate.type}-${row.label}-${row.value}`}>
                                <span>{row.label}</span>
                                <strong>{row.value}</strong>
                              </div>
                            ))}
                          </div>

                          <div className="candidate-detail-section-label">
                            Frequency Details
                          </div>

                          <div className="candidate-frequency-grid">
                            {(candidate.frequencyRows ?? []).length > 0 ? (
                              candidate.frequencyRows.map((row) => (
                                <div key={`${candidate.type}-${row.label}-${row.value}`}>
                                  <span>{row.label}</span>
                                  <strong>{row.value}</strong>
                                </div>
                              ))
                            ) : (
                              <div>
                                <span>FREQ</span>
                                <strong>{formatMHz(detection.frequency_mhz)}</strong>
                              </div>
                            )}
                          </div>
                        </article>
                      ))}
                    </div>
                  )}
                </section>
              );
            })}
          </div>
        )}

        <footer className="signal-detail-footer">
          <button type="button" onClick={onClose}>Close</button>
        </footer>
      </section>
    </div>
  );
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
  const [selectedDetectionDetail, setSelectedDetectionDetail] = useState(null);

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

  const loadPersistentScanSessions = useCallback(
    async ({ selectLatest = false } = {}) => {
      const response = await fetch(`${API_BASE_URL}/api/scan/history`);
      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "Gagal memuat scan history.");
      }

      const sessions = Array.isArray(data.sessions)
        ? data.sessions.map((session, index) =>
            normalizePersistentScanSession(session, index)
          )
        : [];

      setScanSessions(sessions);

      setSelectedSessionId((previousSelectedId) => {
        if (selectLatest) {
          return sessions[0]?.id ?? null;
        }

        const previousStillExists = sessions.some(
          (session) => session.id === previousSelectedId
        );

        if (previousSelectedId && previousStillExists) {
          return previousSelectedId;
        }

        return sessions[0]?.id ?? null;
      });

      return sessions;
    },
    []
  );

  async function handleDeleteScanSession(sessionId, sessionTitle) {
    if (!sessionId) {
      return;
    }

    const confirmed = window.confirm(
      `Hapus scan history "${sessionTitle ?? sessionId}"? File JSON di backend akan dihapus permanen.`
    );

    if (!confirmed) {
      return;
    }

    try {
      setErrorMessage("");

      const response = await fetch(
        `${API_BASE_URL}/api/scan/history/${encodeURIComponent(sessionId)}`,
        { method: "DELETE" }
      );
      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "Gagal menghapus scan history.");
      }

      setSelectedDetectionDetail(null);
      await loadPersistentScanSessions();
      setStatusMessage(`Scan history berhasil dihapus: ${sessionTitle ?? sessionId}.`);
    } catch (error) {
      setErrorMessage(`Delete history error: ${error.message}`);
    }
  }

  async function handleDeleteAllScanSessions() {
    if (scanSessions.length === 0) {
      return;
    }

    const confirmed = window.confirm(
      `Hapus semua scan history (${scanSessions.length} session)? Semua file JSON di backend akan dihapus permanen.`
    );

    if (!confirmed) {
      return;
    }

    try {
      setErrorMessage("");

      const response = await fetch(`${API_BASE_URL}/api/scan/history`, {
        method: "DELETE",
      });
      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "Gagal menghapus semua scan history.");
      }

      setSelectedDetectionDetail(null);
      setScanSessions([]);
      setSelectedSessionId(null);
      setStatusMessage(`Semua scan history berhasil dihapus. Total file: ${data.deleted_count ?? 0}.`);
    } catch (error) {
      setErrorMessage(`Delete all history error: ${error.message}`);
    }
  }

  useEffect(() => {
    if (!selectedDetectionDetail) {
      return undefined;
    }

    function handleKeyDown(event) {
      if (event.key === "Escape") {
        setSelectedDetectionDetail(null);
      }
    }

    window.addEventListener("keydown", handleKeyDown);

    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [selectedDetectionDetail]);

  useEffect(() => {
    let cancelled = false;
    let retryTimerId;
    let attemptIndex = 0;

    async function loadHistoryWithRetry() {
      try {
        await loadPersistentScanSessions();

        if (!cancelled) {
          setErrorMessage((previousMessage) =>
            previousMessage.startsWith("Scan history error:")
              ? ""
              : previousMessage
          );
        }
      } catch (error) {
        if (cancelled) {
          return;
        }

        attemptIndex += 1;

        if (attemptIndex < INITIAL_HISTORY_RETRY_DELAYS_MS.length) {
          retryTimerId = window.setTimeout(
            loadHistoryWithRetry,
            INITIAL_HISTORY_RETRY_DELAYS_MS[attemptIndex]
          );
          return;
        }

        setErrorMessage(`Scan history error: ${error.message}`);
      }
    }

    loadHistoryWithRetry();

    return () => {
      cancelled = true;
      window.clearTimeout(retryTimerId);
    };
  }, [loadPersistentScanSessions]);

  // Muat ulang setiap kali tab Scan History dibuka. Ini memastikan session
  // yang tersimpan di backend selalu muncul tanpa refresh browser.
  useEffect(() => {
    if (activeTab !== "history") {
      return undefined;
    }

    let cancelled = false;

    loadPersistentScanSessions()
      .then(() => {
        if (!cancelled) {
          setErrorMessage((previousMessage) =>
            previousMessage.startsWith("Scan history error:")
              ? ""
              : previousMessage
          );
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setErrorMessage(`Scan history error: ${error.message}`);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [activeTab, loadPersistentScanSessions]);

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
            try {
              await loadPersistentScanSessions({ selectLatest: true });
            } catch (historyError) {
              const historyForSession = currentScanHistoryRef.current;
              const sessionId =
                data.session_id ??
                activeScanMetaRef.current?.id ??
                `scan-${Date.now()}`;
              const completedAt = data.completed_at ?? timestamp;

              const fallbackSession = {
                id: sessionId,
                title: `Scan ${formatDateTime(completedAt)}`,
                startedAt:
                  activeScanMetaRef.current?.startedAt ?? completedAt,
                completedAt,
                config: data.config,
                sweep,
                peak: data.peak,
                detections: historyForSession,
                detectionCount: historyForSession.length,
              };

              setSelectedSessionId(fallbackSession.id);
              setScanSessions((previousSessions) => [
                fallbackSession,
                ...previousSessions.filter(
                  (session) => session.id !== fallbackSession.id
                ),
              ]);

              setErrorMessage(
                `Scan history error: ${historyError.message}`
              );
            }

            scanSessionSavedRef.current = true;
          }

          setStatusMessage(
            data.completed
              ? `Sweep selesai. Hasil scan disimpan ke JSON Scan History. Total titik di atas threshold: ${
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
  }, [isScanning, loadPersistentScanSessions]);

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
    <main className={`app-shell active-${activeTab}`}>
      <header className="app-header">
        <div className="app-header-brand">
          <span className="app-header-brand-mark">◈</span>
          <strong>TOOLS SCANNER</strong>
        </div>

        <nav className="tabs app-tabs" aria-label="Main navigation">
          <button
            type="button"
            className={activeTab === "general" ? "tab active-tab" : "tab"}
            onClick={() => setActiveTab("general")}
          >
            <span className="top-tab-icon">◈</span>
            General
          </button>

          <button
            type="button"
            className={activeTab === "history" ? "tab active-tab" : "tab"}
            onClick={() => setActiveTab("history")}
          >
            <span className="top-tab-icon">▰</span>
            Scan History
            <span className="tab-badge">{scanSessions.length}</span>
          </button>

          <button
            type="button"
            className={activeTab === "specific" ? "tab active-tab" : "tab"}
            onClick={() => setActiveTab("specific")}
          >
            <span className="top-tab-icon">◎</span>
            Specific
          </button>
        </nav>

        <div className="sdr-badge">SDR 1</div>
      </header>

      <aside className="sidebar">
        <div className="sidebar-nav-card selected">
          <span>
            {activeTab === "specific"
              ? "◎"
              : activeTab === "history"
                ? "▰"
                : "◈"}
          </span>
          <strong>
            {activeTab === "specific"
              ? "Specific"
              : activeTab === "history"
                ? "Scan History"
                : "General"}
          </strong>
        </div>

        <section className="settings-section">
          <h2>Setting Threshold</h2>

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

        <section className="sidebar-detected-counter">
          <h2>Frequency Detected</h2>
          <strong>{detectedCount}</strong>
          <span>
            {detectedCount === 1 ? "threshold point" : "threshold points"}
          </span>
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
        {activeTab === "general" ? (
          <>
            <section className="spectrum-panel general-spectrum-panel">
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

            <section className="detected-section classification-section general-detected-panel">
              <div className="panel-heading">
                <div>
                  <p className="section-kicker">DETECTED SIGNALS</p>
                  <h3>Frequency Detection</h3>
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
                <DetectionCardGrid
                  detections={currentScanHistorySorted}
                  sourceLabel="CURRENT SCAN DETAIL"
                  onOpen={setSelectedDetectionDetail}
                />
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
                <p className="section-kicker">JSON SESSION STORAGE</p>
                <h3>Scan History Folder</h3>
              </div>

              <div className="detected-count">
                <strong>{scanSessions.length}</strong>
                <span>{scanSessions.length === 1 ? "SCAN SESSION" : "SCAN SESSIONS"}</span>
              </div>
            </div>

            {scanSessions.length > 0 && (
              <div className="scan-history-action-bar">
                <span>History tersimpan di backend/scan_history sebagai file JSON.</span>
                <button
                  type="button"
                  className="history-delete-all-button"
                  onClick={handleDeleteAllScanSessions}
                >
                  DELETE ALL HISTORY
                </button>
              </div>
            )}

            {scanSessions.length === 0 ? (
              <div className="empty-state">
                Belum ada folder scan tersimpan. Jalankan satu sweep sampai selesai,
                lalu hasilnya otomatis disimpan ke JSON dan muncul di halaman ini.
              </div>
            ) : (
              <div className="session-history-layout">
                <div className="session-folder-list">
                  {scanSessions.map((session) => (
                    <article
                      className={`session-folder-card ${
                        selectedScanSession?.id === session.id ? "selected" : ""
                      }`}
                      key={session.id}
                      role="button"
                      tabIndex={0}
                      onClick={() => setSelectedSessionId(session.id)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter" || event.key === " ") {
                          event.preventDefault();
                          setSelectedSessionId(session.id);
                        }
                      }}
                    >
                      <div className="session-folder-main">
                        <span className="folder-icon">▰</span>
                        <span>
                          <strong>{session.title}</strong>
                          <small>
                            {session.config.start_frequency_mhz}–
                            {session.config.end_frequency_mhz} MHz · {session.detectionCount} points
                          </small>
                        </span>
                      </div>

                      <button
                        type="button"
                        className="session-delete-button"
                        onClick={(event) => {
                          event.stopPropagation();
                          handleDeleteScanSession(session.id, session.title);
                        }}
                      >
                        DELETE
                      </button>
                    </article>
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

                      <HistoricalSpectrumPanel session={selectedScanSession} />

                      <div className="session-card-history-panel">
                        <div className="session-detection-heading">
                          <div>
                            <p className="section-kicker">DETECTED SIGNALS</p>
                            <h4>Saved Frequency Detection</h4>
                          </div>
                          <span>{selectedScanSession.detectionCount} points</span>
                        </div>

                        <DetectionCardGrid
                          detections={selectedScanSession.detections}
                          sourceLabel={selectedScanSession?.title ?? "SCAN HISTORY DETAIL"}
                          onOpen={setSelectedDetectionDetail}
                        />
                      </div>
                    </>
                  )}
                </div>
              </div>
            )}
          </section>
        ) : (
          <SpecificChannelPage
            apiBaseUrl={API_BASE_URL}
            scanConfig={scanConfig}
            isScanning={isScanning}
            spectrumChart={spectrumChart}
            spectrumHistoryCharts={spectrumHistoryCharts}
            frequencyTicks={frequencyTicks}
            chartDbTicks={chartDbTicks}
            thresholdTop={thresholdTop}
            scanDetections={currentScanHistorySorted}
            sweepInfo={sweepInfo}
          />
        )}
      </section>

      <SignalDetailModal
        detail={selectedDetectionDetail}
        onClose={() => setSelectedDetectionDetail(null)}
      />
    </main>
  );
}

export default App;