import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import "./App.css";
import SpecificChannelPage from "./SpecificChannelPage.jsx";
import SpectrumCanvas from "./SpectrumCanvas.jsx";
import useSpectrumStream from "./useSpectrumStream.js";
import { shouldUseSpectrumRestFallback } from "./spectrumTransport.js";
import {
  createEmptySpectrumPreview,
  replaceSpectrumPreview,
} from "./generalSpectrumPreview.js";
import { createFixedChartDbTicks, dbToChartPercent } from "./spectrumChartScale.js";
import navGeneralIcon from "./assets/nav-general.png";
import navSpecificIcon from "./assets/nav-specific.png";
import signalIcon from "./assets/signal-icon.png";

const API_BASE_URL = "";

const SPECTRUM_REFRESH_MS = 250;
const ENABLE_SPECTRUM_WEBSOCKET = true;
const DEVICE_STATUS_REFRESH_MS = 5000;
const INITIAL_STATUS_RETRY_DELAYS_MS = [0, 1000, 2000, 4000, 8000];

// Saat Vite dan FastAPI dinyalakan hampir bersamaan, frontend dapat terbuka
// Status SDR dibaca dari cache detector USB/PnP pasif. Endpoint ini tidak
// menjalankan UHD dan tetap aman ketika USRP tidak terhubung atau sedang scan.

// Warna marker pada grafik. Urutan warna sama dengan urutan Signal 01, 02, 03, dan seterusnya.
const DETECTION_MARKER_COLORS = [
  "#6dffba",
  "#ffd166",
  "#c792ff",
  "#ff8e8e",
  "#58c7ff",
  "#ff9f68",
];

function clamp(value, minimum, maximum) {
  return Math.min(Math.max(value, minimum), maximum);
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
          ? "Paired DL: -"
          : `Paired DL: [ ${candidate.nr_arfcn_dl} ]`,
      ];
    }

    return [
      "FDD · Detected DL",
      candidate.nr_arfcn_dl === null || candidate.nr_arfcn_dl === undefined
        ? "DL ARFCN : -"
        : `DL ARFCN : [ ${candidate.nr_arfcn_dl} ]`,
      candidate.nr_arfcn_ul === null || candidate.nr_arfcn_ul === undefined
        ? "Paired UL: -"
        : `Paired UL: [ ${candidate.nr_arfcn_ul} ]`,
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
      return " (DETECTED)";
    }

    if ((side === "DL" || side === "UL") && side !== rowSide) {
      return " (PAIRED)";
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
      label: side === "TDD" ? "FREQ (TDD)" : "DETECTED FREQUENCY",
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
      label: detectedSide === "DL" ? "DL EARFCN (DETECTED)" : "DL EARFCN (PAIRED)",
      value: formatDetailValue(candidate.earfcn_dl),
    });
  }

  if (candidate.earfcn_ul !== null && candidate.earfcn_ul !== undefined) {
    rows.push({
      label: detectedSide === "UL" ? "UL EARFCN (DETECTED)" : "UL EARFCN (PAIRED)",
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
        label: "DL NR-ARFCN (DETECTED)",
        value: formatDetailValue(candidate.nr_arfcn_dl),
      },
    ];
  }

  if (duplex === "SUL") {
    return [
      {
        label: "UL NR-ARFCN (DETECTED)",
        value: formatDetailValue(candidate.nr_arfcn_ul),
      },
    ];
  }

  const rows = [];

  if (candidate.nr_arfcn_dl !== null && candidate.nr_arfcn_dl !== undefined) {
    rows.push({
      label: detectedSide === "DL" ? "DL NR-ARFCN (DETECTED)" : "DL NR-ARFCN (PAIRED)",
      value: formatDetailValue(candidate.nr_arfcn_dl),
    });
  }

  if (candidate.nr_arfcn_ul !== null && candidate.nr_arfcn_ul !== undefined) {
    rows.push({
      label: detectedSide === "UL" ? "UL NR-ARFCN (DETECTED)" : "UL NR-ARFCN (PAIRED)",
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
    return "3G UMTS";
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
        { label: "DL UARFCN (DETECTED)", value: formatDetailValue(candidate.uarfcn_dl) },
        { label: "UL UARFCN (PAIRED)", value: formatDetailValue(candidate.uarfcn_ul) },
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


function TechnologyBandCard({ candidate }) {
  return (
    <span
      className={`figma-band-card ${candidate.type}`}
      title={`${candidate.modeTitle} · ${candidate.bandTitle ?? candidate.name}`}
    >
      <span className="figma-band-icon" aria-hidden="true">
        <img src={signalIcon} alt="" aria-hidden="true" />
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
          <span>Power (dB)</span>
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

function normalizeDetection(detection, index = 0) {
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
    title: "3G UMTS",
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

        <p className="signal-detail-section-title">Match Details</p>

        {technologyGroups.length === 0 ? (
          <div className="signal-detail-empty">
            No matching technology found.
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


function ScanModeIsolationPanel({ owner, isRunning }) {
  const ownerLabel = owner === "specific" ? "Specific" : "General";
  const targetLabel = owner === "specific" ? "General" : "Specific";

  return (
    <section className="scan-mode-isolation-panel">
      <div className={`scan-mode-isolation-icon ${isRunning ? "running" : "saved"}`}>
        {isRunning ? "●" : "■"}
      </div>

      <p className="section-kicker">SEPARATE SCAN MODE</p>
      <h3>
        {isRunning
          ? `${ownerLabel} Scan is running`
          : `The latest result is from the ${ownerLabel} Scan`}
      </h3>
      <p>
        ${ownerLabel} Scan data is not shown on the {targetLabel} page.
        {isRunning
          ? ` Return to the ${ownerLabel} page to stop the scan.`
          : ` Run a ${targetLabel} Scan to create results for this page.`}
      </p>
    </section>
  );
}

function ToastViewport({ toasts, onDismiss }) {
  return (
    <div className="toast-viewport" aria-live="polite" aria-atomic="true">
      {toasts.map((toast) => (
        <div className={`toast toast-${toast.type}`} key={toast.id} role="status">
          <span>{toast.message}</span>
          <button
            type="button"
            onClick={() => onDismiss(toast.id)}
            aria-label="Dismiss notification"
          >
            ×
          </button>
        </div>
      ))}
    </div>
  );
}

function App({ isLoggingOut = false, onLogout }) {
  const [activeTab, setActiveTab] = useState(() => {
    const savedTab = window.sessionStorage.getItem("usrp-active-tab");

    return ["general", "specific"].includes(savedTab)
      ? savedTab
      : "general";
  });

  useEffect(() => {
    window.sessionStorage.setItem("usrp-active-tab", activeTab);
  }, [activeTab]);

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
  const [scanOwner, setScanOwner] = useState(null);
  const [scanMode, setScanMode] = useState(null);
  const [scanSelectedMachineId, setScanSelectedMachineId] = useState(null);
  const [scanSelectedMachineName, setScanSelectedMachineName] = useState(null);
  const [selectedSpecificMachineId, setSelectedSpecificMachineId] = useState(null);
  const [selectedSpecificMachineName, setSelectedSpecificMachineName] = useState(null);

  // Both owners use this bounded backend preview for the full-range graph.
  const [spectrumPreview, setSpectrumPreview] = useState(
    createEmptySpectrumPreview()
  );

  const [sweepInfo, setSweepInfo] = useState(null);
  // All threshold-exceeding points from the active rolling scan are retained
  // here for the current General or Specific view.
  const [currentScanHistory, setCurrentScanHistory] = useState([]);
  const [selectedDetectionDetail, setSelectedDetectionDetail] = useState(null);

  const currentScanHistoryRef = useRef([]);
  const activeScanMetaRef = useRef(null);
  const lastSnapshotKeyRef = useRef(null);
  const [spectrumStreamHealthy, setSpectrumStreamHealthy] = useState(false);

  const [detections, setDetections] = useState([]);
  const [channelMeasurements, setChannelMeasurements] = useState([]);
  const [statusMessage, setStatusMessage] = useState(
    "Enter a configuration, then select START SCAN."
  );
  const [errorMessage, setErrorMessage] = useState("");
  const [deviceStatus, setDeviceStatus] = useState({
    connected: null,
    status: "unknown",
    device: "USRP B210",
    serial: null,
    detector: null,
    friendly_name: null,
    detail: "Waiting for USB detection...",
    checked_at: null,
    scanner_busy: false,
  });
  const [toasts, setToasts] = useState([]);
  const toastIdRef = useRef(0);
  const toastTimersRef = useRef(new Map());
  const recentToastKeysRef = useRef(new Map());
  const deviceConnectionRef = useRef(null);
  const deviceStatusResolvedRef = useRef(false);
  const deviceDisconnectDuringScanRef = useRef(false);
  const isScanningRef = useRef(isScanning);
  const scanCompletionToastRef = useRef(false);
  const manualStopRequestedRef = useRef(false);

  const dismissToast = useCallback((toastId) => {
    const timerId = toastTimersRef.current.get(toastId);
    if (timerId) {
      window.clearTimeout(timerId);
      toastTimersRef.current.delete(toastId);
    }

    setToasts((previousToasts) =>
      previousToasts.filter((toast) => toast.id !== toastId)
    );
  }, []);

  const notify = useCallback(
    (message, type = "info", key = message) => {
      const duration = type === "error" || type === "warning" ? 6000 : 4000;
      const now = Date.now();
      const duplicateKey = `${type}:${key}`;
      const lastShownAt = recentToastKeysRef.current.get(duplicateKey);

      if (lastShownAt && now - lastShownAt < duration) {
        return;
      }

      recentToastKeysRef.current.set(duplicateKey, now);
      const toastId = ++toastIdRef.current;

      setToasts((previousToasts) => {
        const nextToasts = [
          ...previousToasts,
          { id: toastId, message, type },
        ];
        const removedToasts = nextToasts.slice(0, -3);

        removedToasts.forEach((toast) => {
          const timerId = toastTimersRef.current.get(toast.id);
          if (timerId) {
            window.clearTimeout(timerId);
            toastTimersRef.current.delete(toast.id);
          }
        });

        return nextToasts.slice(-3);
      });

      const timerId = window.setTimeout(() => dismissToast(toastId), duration);
      toastTimersRef.current.set(toastId, timerId);
    },
    [dismissToast]
  );

  useEffect(() => {
    isScanningRef.current = isScanning;
  }, [isScanning]);

  useEffect(() => () => {
    toastTimersRef.current.forEach((timerId) => window.clearTimeout(timerId));
    toastTimersRef.current.clear();
  }, []);

  const loadDeviceStatus = useCallback(async () => {
    try {
      const response = await fetch(
        `${API_BASE_URL}/api/device/status`,
        { cache: "no-store" }
      );
      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "Failed to read SDR status.");
      }

      const connected =
          data.connected === true
            ? true
            : data.connected === false
              ? false
              : null;

      if (connected !== null) {
        const previousConnection = deviceConnectionRef.current;

        if (!deviceStatusResolvedRef.current) {
          notify(
            connected ? "Device connected." : "Device is not connected.",
            connected ? "success" : "warning",
            "device-initial-state"
          );
          deviceStatusResolvedRef.current = true;
        } else if (previousConnection !== connected) {
          if (connected) {
            deviceDisconnectDuringScanRef.current = false;
            notify("Device connected.", "success", "device-connected");
          } else {
            const disconnectedDuringScan = isScanningRef.current;
            deviceDisconnectDuringScanRef.current = disconnectedDuringScan;
            notify(
              disconnectedDuringScan
                ? "Device disconnected during scan. Reconnect the device."
                : "Device disconnected.",
              "warning",
              "device-disconnected"
            );
          }
        }

        deviceConnectionRef.current = connected;
      }

      setDeviceStatus({
        connected,
        status: data.status ?? "unknown",
        device: data.device ?? "USRP B210",
        serial: data.serial ?? null,
        detector: data.detector ?? null,
        friendly_name: data.friendly_name ?? null,
        detail: data.detail ?? null,
        checked_at: data.checked_at ?? null,
        scanner_busy: Boolean(data.scanner_busy),
        scan_owner: data.scan_owner ?? null,
      });
    } catch {
      // Detector tidak boleh mengubah error global aplikasi. CRUD dan halaman
      // lain tetap berjalan ketika backend detector belum tersedia.
      setDeviceStatus((previousStatus) => ({
        ...previousStatus,
        connected: null,
        status: "unknown",
        detail: "USB status is unavailable from the backend.",
        checked_at: null,
      }));
    }
  }, [notify]);

  const notifyScanFailure = useCallback(
    (error) => {
      const detail = error instanceof Error ? error.message : String(error ?? "");
      const deviceUnavailable = /device|usrp|sdr|disconnect|not connected|unavailable/i.test(
        detail
      );

      if (deviceUnavailable && deviceDisconnectDuringScanRef.current) {
        return;
      }

      notify(
        deviceUnavailable
          ? "Scan failed. Reconnect the device."
          : "Scan failed.",
        "error",
        "scan-failed"
      );
    },
    [notify]
  );

  const applyBackendScanState = useCallback(
    (data, { showResumeMessage = false } = {}) => {
      const running = Boolean(data?.running);
      const owner = data?.scan_owner ?? null;
      const mode = data?.scan_mode ?? null;
      const machineId = data?.selected_machine_id ?? null;
      const machineName = data?.selected_machine_name ?? null;

      setIsScanning(running);
      setScanOwner(owner);
      setScanMode(mode);
      setScanSelectedMachineId(machineId);
      setScanSelectedMachineName(machineName);

      if (data?.config && typeof data.config === "object") {
        setScanConfig(data.config);
      }

      if (data?.sweep && typeof data.sweep === "object") {
        setSweepInfo({
          ...data.sweep,
          cycle_index: data.cycle_index,
          completed_cycles: data.completed_cycles,
          cycle_window_index: data.cycle_window_index,
          cycle_total_windows: data.cycle_total_windows,
          cycle_progress_percent: data.cycle_progress_percent,
          completed: Boolean(data.completed),
        });
      }

      if (Array.isArray(data?.channel_measurements)) {
        setChannelMeasurements(data.channel_measurements);
      }

      if (running) {
        activeScanMetaRef.current = {
          id: data?.session_id ?? `scan-${Date.now()}`,
          startedAt: data?.started_at ?? new Date().toISOString(),
          request: {
            scan_owner: owner,
            selected_machine_id: machineId,
          },
          selectedMachineName: machineName,
        };
        if (showResumeMessage) {
          const ownerLabel = owner === "specific" ? "Specific" : "General";
          const machineLabel =
            owner === "specific" && machineName ? ` — ${machineName}` : "";

          setStatusMessage(
            `${ownerLabel} Scan${machineLabel} is still running. Status restored from the backend.`
          );
        }
      } else if (showResumeMessage && data?.last_error) {
        setStatusMessage("The scan stopped because of a backend error.");
      }

      return {
        running,
        owner,
        mode,
        machineId,
        machineName,
      };
    },
    []
  );

  const syncScanStateFromBackend = useCallback(
    async ({ showResumeMessage = false, restoreResults = true } = {}) => {
      const statusResponse = await fetch(`${API_BASE_URL}/api/status`);
      const statusData = await statusResponse.json();

      if (!statusResponse.ok) {
        throw new Error(
          statusData.detail || "Failed to synchronize scan status."
        );
      }

      const synchronizedState = applyBackendScanState(statusData, {
        showResumeMessage,
      });

      if (synchronizedState.running && restoreResults) {
        const resultsResponse = await fetch(
          `${API_BASE_URL}/api/scan/results`
        );
        const resultsData = await resultsResponse.json();

        if (resultsResponse.ok) {
          const restoredDetections = Array.isArray(resultsData.detections)
            ? resultsData.detections.map((detection, index) =>
                normalizeDetection(detection, index)
              )
            : [];

          currentScanHistoryRef.current = restoredDetections;
          setCurrentScanHistory(restoredDetections);
          setDetections(
            Array.isArray(resultsData.last_window_detections)
              ? resultsData.last_window_detections
              : []
          );
          setChannelMeasurements(
            Array.isArray(resultsData.channel_measurements)
              ? resultsData.channel_measurements
              : []
          );
        }
      }

      return statusData;
    },
    [applyBackendScanState]
  );

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
    loadDeviceStatus();

    const intervalId = window.setInterval(
      loadDeviceStatus,
      DEVICE_STATUS_REFRESH_MS
    );

    function handleDeviceStatusFocus() {
      loadDeviceStatus();
    }

    window.addEventListener("focus", handleDeviceStatusFocus);

    return () => {
      window.clearInterval(intervalId);
      window.removeEventListener("focus", handleDeviceStatusFocus);
    };
  }, [loadDeviceStatus]);

  useEffect(() => {
    let cancelled = false;
    let retryTimerId;
    let attemptIndex = 0;

    async function synchronizeWithRetry({ showResumeMessage = false } = {}) {
      try {
        await syncScanStateFromBackend({
          showResumeMessage,
          restoreResults: true,
        });
      } catch {
        if (cancelled) {
          return;
        }

        attemptIndex += 1;

        if (attemptIndex < INITIAL_STATUS_RETRY_DELAYS_MS.length) {
          retryTimerId = window.setTimeout(
            () => synchronizeWithRetry({ showResumeMessage }),
            INITIAL_STATUS_RETRY_DELAYS_MS[attemptIndex]
          );
        }
      }
    }

    function handleWindowFocus() {
      attemptIndex = 0;
      synchronizeWithRetry({ showResumeMessage: true });
    }

    function handleVisibilityChange() {
      if (document.visibilityState === "visible") {
        handleWindowFocus();
      }
    }

    synchronizeWithRetry({ showResumeMessage: true });
    window.addEventListener("focus", handleWindowFocus);
    document.addEventListener("visibilitychange", handleVisibilityChange);

    return () => {
      cancelled = true;
      window.clearTimeout(retryTimerId);
      window.removeEventListener("focus", handleWindowFocus);
      document.removeEventListener(
        "visibilitychange",
        handleVisibilityChange
      );
    };
  }, [syncScanStateFromBackend]);

  const applySpectrumSnapshot = useCallback(async (data) => {
    const responseSessionId = data?.session_id ?? null;
    const activeScan = activeScanMetaRef.current;
    const activeSessionId = activeScan?.id ?? null;
    const expectedOwner = activeScan?.request?.scan_owner ?? null;
    const expectedMachineId = activeScan?.request?.selected_machine_id;

    if (
      !responseSessionId ||
      !activeSessionId ||
      responseSessionId !== activeSessionId ||
      (expectedOwner && data.scan_owner !== expectedOwner) ||
      (expectedOwner === "specific" && expectedMachineId !== null && expectedMachineId !== undefined &&
        Number(data.selected_machine_id) !== Number(expectedMachineId))
    ) {
      return { accepted: false, running: Boolean(data?.running) };
    }

    const currentWindow = data.current_window ?? null;
    const sweep = data.sweep ?? null;
    const timestamp = data.timestamp ?? new Date().toISOString();
    const snapshotKey = [
      responseSessionId,
      timestamp,
      data.cycle_index,
      currentWindow?.window_index,
      data.spectrum_preview?.point_count,
      data.running,
      data.last_error,
    ].join("|");
    if (lastSnapshotKeyRef.current === snapshotKey) {
      return { accepted: true, running: Boolean(data.running), duplicate: true };
    }
    lastSnapshotKeyRef.current = snapshotKey;

    const rollingDetections = Array.isArray(data.detections) ? data.detections : [];
    const windowDetections = Array.isArray(data.last_window_detections)
      ? data.last_window_detections
      : [];
    const nextPreview = replaceSpectrumPreview({
      activeSessionId,
      responseSessionId,
      preview: data.spectrum_preview,
    });
    if (nextPreview) setSpectrumPreview({ ...nextPreview });
    setScanOwner(data.scan_owner ?? null);
    setScanMode(data.scan_mode ?? null);
    setScanSelectedMachineId(data.selected_machine_id ?? null);
    setScanSelectedMachineName(data.selected_machine_name ?? null);
    setDetections(windowDetections);
    setChannelMeasurements(Array.isArray(data.channel_measurements) ? data.channel_measurements : []);
    if (data.config) setScanConfig(data.config);
    setSweepInfo({
      ...sweep,
      cycle_index: data.cycle_index,
      completed_cycles: data.completed_cycles,
      cycle_window_index: data.cycle_window_index,
      cycle_total_windows: data.cycle_total_windows,
      cycle_progress_percent: data.cycle_progress_percent,
    });
    const normalizedDetections = rollingDetections.map((detection, detectionIndex) => ({
      ...detection,
      history_id: buildDetectionHistoryId(detection, detectionIndex),
      captured_at: timestamp,
      window_label: formatWindowMHz(detection.window_start_mhz, detection.window_end_mhz),
    }));
    currentScanHistoryRef.current = normalizedDetections;
    setCurrentScanHistory(normalizedDetections);
    setErrorMessage("");

    if (!data.running) {
      setIsScanning(false);
      setStatusMessage(data.completed ? "Scan completed." : "Scan stopped.");
      if (data.completed && !scanCompletionToastRef.current) {
        scanCompletionToastRef.current = true;
        notify("Scan completed.", "success", "scan-completed");
      } else if (!data.completed && data.last_error && !manualStopRequestedRef.current) {
        notifyScanFailure(new Error(data.last_error));
      }
      return { accepted: true, running: false };
    }

    if (currentWindow && sweep) {
      setStatusMessage(
        `Scanning ${formatWindowMHz(currentWindow.start_frequency_mhz, currentWindow.end_frequency_mhz)} Â· Window ${sweep.scanned_windows}/${sweep.total_windows} Â· ${sweep.progress_percent}%`
      );
    } else {
      setStatusMessage(`Spectrum updated: ${data.timestamp || "real time"}`);
    }
    return { accepted: true, running: true };
  }, [notify, notifyScanFailure]);

  useSpectrumStream({
    enabled: ENABLE_SPECTRUM_WEBSOCKET && isScanning,
    apiBaseUrl: API_BASE_URL,
    activeScanMetaRef,
    onSnapshot: applySpectrumSnapshot,
    onHealthChange: setSpectrumStreamHealthy,
    onRejected: () => {},
  });

  // REST remains the Stage 1 fallback while the WebSocket is unavailable.
  useEffect(() => {
    if (!isScanning || !shouldUseSpectrumRestFallback(
      ENABLE_SPECTRUM_WEBSOCKET,
      spectrumStreamHealthy
    )) {
      return undefined;
    }

    let cancelled = false;
    let timeoutId;

    async function pollSpectrum() {
      try {
        const response = await fetch(`${API_BASE_URL}/api/spectrum`);
        const data = await response.json();

        if (!response.ok) {
          throw new Error(data.detail || "Failed to retrieve spectrum data.");
        }

        if (cancelled) {
          return;
        }

        const applied = await applySpectrumSnapshot(data);
        if (!applied.accepted || !applied.running) {
          return;
        }
        if (!cancelled) {
          timeoutId = window.setTimeout(pollSpectrum, SPECTRUM_REFRESH_MS);
        }
        return;

      } catch (error) {
        if (cancelled) {
          return;
        }

        try {
          const synchronizedStatus = await syncScanStateFromBackend({
            showResumeMessage: false,
            restoreResults: true,
          });

          if (cancelled) {
            return;
          }

          if (synchronizedStatus.running) {
            setErrorMessage(
              `Spectrum data could not be loaded: ${error.message}. Retrying...`
            );
            timeoutId = window.setTimeout(pollSpectrum, 1000);
            return;
          }

          setErrorMessage(`Spectrum error: ${error.message}`);
          setIsScanning(false);
          if (!manualStopRequestedRef.current) {
            notifyScanFailure(error);
          }
          return;
        } catch (statusError) {
          setErrorMessage(
            `Spectrum error: ${error.message}. Backend status could not be checked: ${statusError.message}`
          );
          setIsScanning(false);
          if (!manualStopRequestedRef.current) {
            notifyScanFailure(error);
          }
          return;
        }
      }

    }

    pollSpectrum();

    return () => {
      cancelled = true;
      window.clearTimeout(timeoutId);
    };
  }, [
    applySpectrumSnapshot,
    isScanning,
    notify,
    notifyScanFailure,
    spectrumStreamHealthy,
    syncScanStateFromBackend,
  ]);

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

  // The fixed reference-power range remains stable across polling updates.
  const chartDbTicks = useMemo(createFixedChartDbTicks, []);

  // Both full-range graphs use the session-validated backend preview.
  const spectrumChart = useMemo(() => {
    return {
      frequencyValues: spectrumPreview.frequency_mhz,
      powerValues: spectrumPreview.power_db,
    };
  }, [spectrumPreview]);


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

        const verticalPosition = dbToChartPercent(power);

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
  }, [detections, scanConfig]);

  async function handleScan() {
    const requestedOwner =
      activeTab === "specific"
        ? "specific"
        : activeTab === "general"
          ? "general"
          : null;

    if (!requestedOwner) {
      setErrorMessage(
        "A scan can only be started from the General or Specific page."
      );
      return;
    }

    if (
      isScanning &&
      scanOwner &&
      scanOwner !== requestedOwner
    ) {
      setErrorMessage(
        `The scanner is in use by the ${
          scanOwner === "general" ? "General" : "Specific"
        } Scan. Return to that page to stop it.`
      );
      return;
    }

    if (
      requestedOwner === "specific" &&
      !selectedSpecificMachineId &&
      !isScanning
    ) {
      setErrorMessage(
        "Select a Machine on the Specific page before starting a Specific Scan."
      );
      return;
    }

    setErrorMessage("");
    setIsBusy(true);

    try {
      if (isScanning) {
        manualStopRequestedRef.current = true;
        const response = await fetch(`${API_BASE_URL}/api/scan/stop`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            scan_owner: requestedOwner,
          }),
        });

        const data = await response.json();

        if (!response.ok) {
          if (response.status === 409) {
            await syncScanStateFromBackend({
              showResumeMessage: true,
              restoreResults: true,
            });
            setErrorMessage(
              data.detail || "Scanner ownership status has been synchronized."
            );
            return;
          }

          throw new Error(data.detail || "Failed to stop the scan.");
        }

        setIsScanning(false);
        setScanOwner(data.scan_owner ?? scanOwner);
        setScanMode(data.scan_mode ?? scanMode);
        setScanSelectedMachineId(
          data.selected_machine_id ?? scanSelectedMachineId
        );
        setScanSelectedMachineName(
          data.selected_machine_name ?? scanSelectedMachineName
        );
        setStatusMessage(
          `${requestedOwner === "general" ? "General" : "Specific"} Scan stopped.`
        );
        notify("Scan stopped.", "info", "scan-stopped");
        return;
      }

      const requestBody = {
        threshold_db: Number(threshold),
        start_frequency_mhz: Number(startFrequency),
        end_frequency_mhz: Number(endFrequency),
        scan_owner: requestedOwner,
        selected_machine_id:
          requestedOwner === "specific"
            ? Number(selectedSpecificMachineId)
            : null,
      };

      if (
        !Number.isFinite(requestBody.threshold_db) ||
        !Number.isFinite(requestBody.start_frequency_mhz) ||
        !Number.isFinite(requestBody.end_frequency_mhz)
      ) {
        throw new Error("All configuration values must be numbers.");
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
        if (response.status === 409) {
          await syncScanStateFromBackend({
            showResumeMessage: true,
            restoreResults: true,
          });
          setErrorMessage(
            data.detail || "The scanner is in use by an active scan."
          );
          return;
        }

        throw new Error(data.detail || "Failed to start the scan.");
      }

      setScanOwner(data.scan_owner ?? requestedOwner);
      setScanMode(data.scan_mode ?? "range_sweep");
      setScanSelectedMachineId(data.selected_machine_id ?? null);
      setScanSelectedMachineName(data.selected_machine_name ?? null);
      setScanConfig(data.config);
      setSpectrumPreview(
        createEmptySpectrumPreview(data.session_id ?? null)
      );
      setCurrentScanHistory([]);
      currentScanHistoryRef.current = [];
      activeScanMetaRef.current = {
        id: data.session_id ?? `scan-${Date.now()}`,
        startedAt: new Date().toISOString(),
        request: requestBody,
        selectedMachineName:
          requestedOwner === "specific"
            ? data.selected_machine_name ?? selectedSpecificMachineName
            : null,
      };
      scanCompletionToastRef.current = false;
      manualStopRequestedRef.current = false;
      deviceDisconnectDuringScanRef.current = false;
      setSweepInfo(data.sweep ? {
        ...data.sweep,
        cycle_index: data.cycle_index,
        completed_cycles: data.completed_cycles,
        cycle_window_index: data.cycle_window_index,
        cycle_total_windows: data.cycle_total_windows,
        cycle_progress_percent: data.cycle_progress_percent,
      } : null);
      setDetections([]);
      setChannelMeasurements([]);
      setIsScanning(true);
      setStatusMessage(
        requestedOwner === "specific"
          ? `Specific Scan for ${
              data.selected_machine_name ?? selectedSpecificMachineName ?? "the selected Machine"
            } started. Waiting for spectrum data...`
          : "General Scan started. Waiting for spectrum data..."
      );
      notify("Scan started.", "success", "scan-started");
    } catch (error) {
      setErrorMessage(error.message);
      setStatusMessage("Scan has not started.");
      manualStopRequestedRef.current = false;
      if (error.message !== "All configuration values must be numbers.") {
        notifyScanFailure(error);
      }
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

  const detectedCount = currentScanHistorySorted.length;

  const isSweepCompleted =
    !isScanning &&
    Boolean(sweepInfo) &&
    Number(sweepInfo?.progress_percent ?? 0) >= 100;
  const hasMeaningfulSweepInfo = Boolean(
    sweepInfo &&
      (Number(sweepInfo.scanned_windows ?? 0) > 0 ||
        Number(sweepInfo.progress_percent ?? 0) > 0 ||
        Number(sweepInfo.completed_cycles ?? 0) > 0)
  );

  const sidebarScanStatus = errorMessage
    ? "FAILED"
    : isScanning
      ? "SCANNING"
      : isSweepCompleted
        ? "COMPLETED"
        : "READY";

  const sidebarScanStatusClass = errorMessage
    ? "status-failed"
    : isScanning
      ? "status-running"
      : isSweepCompleted
        ? "status-completed"
        : "status-idle";

  const currentPageScanOwner =
    activeTab === "general"
      ? "general"
      : activeTab === "specific"
        ? "specific"
        : null;
  const scannerOwnedByOtherPage = Boolean(
    isScanning &&
    currentPageScanOwner &&
    scanOwner &&
    scanOwner !== currentPageScanOwner
  );
  const scanOwnerLabel =
    scanOwner === "specific"
      ? "Specific"
      : scanOwner === "general"
        ? "General"
        : null;
  const deviceBadgeLabel = "SDR 1";
  const deviceBadgeStatus =
    deviceStatus.scanner_busy
      ? "SCANNING"
      : deviceStatus.connected === true
        ? "CONNECTED"
        : deviceStatus.connected === false
          ? "DISCONNECTED"
          : "RECONNECTING";
  const deviceBadgeState = deviceBadgeStatus.toLowerCase();
  const deviceBadgeStatusLabel =
    `${deviceBadgeStatus.slice(0, 1)}${deviceBadgeStatus.slice(1).toLowerCase()}`;
  const deviceBadgeCompactStatusLabel =
    deviceBadgeStatus === "CONNECTED"
      ? "ON"
      : deviceBadgeStatus === "SCANNING"
        ? "SCAN"
        : deviceBadgeStatus === "DISCONNECTED"
          ? "OFF"
          : "WAIT";

  return (
    <main className={`app-shell active-${activeTab}`}>
      <header className="app-header">
        <div className="app-header-brand">
          <strong>TOOLS SCANNER</strong>
        </div>

        <nav className="tabs app-tabs" aria-label="Main navigation">
          <button
            type="button"
            className={activeTab === "general" ? "tab active-tab" : "tab"}
            onClick={() => setActiveTab("general")}
          >
            <img className="top-tab-icon" src={navGeneralIcon} alt="" />
            General
          </button>

          <button
            type="button"
            className={activeTab === "specific" ? "tab active-tab" : "tab"}
            onClick={() => setActiveTab("specific")}
          >
            <img className="top-tab-icon" src={navSpecificIcon} alt="" />
            Specific
          </button>
        </nav>

        <div className="app-header-actions">
          <div
            className={`sdr-badge sdr-${deviceBadgeState}`}
            title={deviceBadgeStatusLabel}
            aria-label={`${deviceBadgeLabel} — ${deviceBadgeStatusLabel}`}
            aria-live="polite"
          >
            <strong className="sdr-badge-label">{deviceBadgeLabel}</strong>
            <span className="sdr-badge-status" aria-hidden="true">
              {deviceBadgeCompactStatusLabel}
            </span>
          </div>

          <button
            type="button"
            className="logout-button"
            onClick={onLogout}
            disabled={isLoggingOut}
            aria-label="Log out"
            title="Log out"
          >
            <span className="logout-button-label">
              {isLoggingOut ? "WAIT" : "LOGOUT"}
            </span>
            <span className="logout-button-icon" aria-hidden="true">↪</span>
          </button>
        </div>
      </header>

      <div className="scanner-shell">
        <div className="scanner-grid">
          <aside className="sidebar">
        <div className="sidebar-nav-card selected">
          <span>
            {activeTab === "specific"
              ? <img className="sidebar-nav-icon" src={navSpecificIcon} alt="" />
              : <img className="sidebar-nav-icon" src={navGeneralIcon} alt="" />}
          </span>
          <strong>
            {activeTab === "specific"
              ? "Specific"
              : "General"}
          </strong>
        </div>

        <section className="settings-section">
          <h2>Scan Settings</h2>

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
            className={`scan-button ${
              isScanning && !scannerOwnedByOtherPage ? "scan-active" : ""
            } ${scannerOwnedByOtherPage ? "scan-locked" : ""}`}
            onClick={handleScan}
            disabled={
              isBusy ||
              scannerOwnedByOtherPage
            }
          >
            <span className="scan-icon">
              {scannerOwnedByOtherPage
                ? "⌁"
                : isScanning
                  ? "■"
                  : "▶"}
            </span>
            {isBusy
              ? "PROCESSING..."
              : scannerOwnedByOtherPage
                  ? `${scanOwnerLabel?.toUpperCase()} SCAN ACTIVE`
                  : isScanning
                    ? `STOP ${currentPageScanOwner?.toUpperCase()} SCAN`
                    : `START ${currentPageScanOwner?.toUpperCase()} SCAN`}
          </button>
        </section>

        <section className="sidebar-detected-counter">
          <h2>Detected Frequencies</h2>
          <strong>{detectedCount}</strong>
          <span>
            {detectedCount === 1 ? "threshold point" : "threshold points"}
          </span>
        </section>

        <section className="sidebar-status">
          <p>SCAN STATUS</p>

          <strong className={sidebarScanStatusClass}>
            {sidebarScanStatus}
          </strong>

          <span>
            Range: {scanConfig.start_frequency_mhz}–
            {scanConfig.end_frequency_mhz} MHz
          </span>

          {isScanning && sweepInfo && (
            <span className="sidebar-sweep-detail">
              Progress: {sweepInfo.scanned_windows}/
              {sweepInfo.total_windows} · {sweepInfo.progress_percent}%
            </span>
          )}

          {isSweepCompleted && !errorMessage && (
            <span className="sidebar-scan-saved">Scan completed.</span>
          )}
        </section>

        {errorMessage && (
          <p className="sidebar-error-message">{errorMessage}</p>
        )}
          </aside>

          <section className="dashboard">
        {activeTab === "general" ? (
          scanOwner === "specific" ? (
            <ScanModeIsolationPanel
              owner="specific"
              isRunning={isScanning}
            />
          ) : (
            <>
            <section className="spectrum-panel general-spectrum-panel">
              <div className="spectrum-panel-header">
                <h3 className="spectrum-panel-title">Realtime Spectrum</h3>
                <div
                  className={`spectrum-panel-status ${
                    isScanning ? "is-scanning" : ""
                  }`}
                >
                  {isScanning && <i aria-hidden="true" />}
                  {isScanning ? "SCANNING" : "READY"}
                </div>
              </div>

              {hasMeaningfulSweepInfo && (
                <div className="sweep-progress-card general-spectrum-sweep">
                  <span>
                    Sweep window: {sweepInfo.scanned_windows}/
                    {sweepInfo.total_windows}
                  </span>
                  <span>Progress: {sweepInfo.progress_percent}%</span>
                  {Number(sweepInfo.completed_cycles ?? 0) > 0 && (
                    <span>Completed cycles: {sweepInfo.completed_cycles}</span>
                  )}
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

                  {spectrumPreview.frequency_mhz.length > 0 ? (
                    <>
                      <SpectrumCanvas
                        frequencyValues={spectrumPreview.frequency_mhz}
                        powerValues={spectrumPreview.power_db}
                        startFrequencyMHz={scanConfig.start_frequency_mhz}
                        endFrequencyMHz={scanConfig.end_frequency_mhz}
                        thresholdDb={scanConfig.threshold_db}
                      />

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
                    </>
                  ) : (
                    <div className="chart-placeholder">
                      {isScanning
                        ? "Receiving signal data..."
                        : "Select START SCAN to view the spectrum."}
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
                  <h3>Detected Frequencies</h3>
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
              </div>

              {currentScanHistorySorted.length === 0 ? (
                <div className="empty-state">
                  {isScanning
                    ? "No signals above threshold yet."
                    : "Start a scan to see results."}
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
          )
        ) : (
          <SpecificChannelPage
            apiBaseUrl={API_BASE_URL}
            scanConfig={scanConfig}
            isScanning={isScanning}
            scanOwner={scanOwner}
            scanSelectedMachineId={scanSelectedMachineId}
            scanSelectedMachineName={scanSelectedMachineName}
            scannerLocked={scanOwner === "general"}
            spectrumChart={
              scanOwner === "specific"
                ? spectrumChart
                : { linePoints: "", areaPoints: "" }
            }
            frequencyTicks={frequencyTicks}
            chartDbTicks={chartDbTicks}
            scanDetections={
              scanOwner === "specific" ? currentScanHistorySorted : []
            }
            channelMeasurements={
              scanOwner === "specific" ? channelMeasurements : []
            }
            sweepInfo={scanOwner === "specific" ? sweepInfo : null}
            onSelectedMachineChange={(machine) => {
              setSelectedSpecificMachineId(machine?.id ?? null);
              setSelectedSpecificMachineName(machine?.name ?? null);
            }}
            onNotify={notify}
          />
        )}
          </section>
        </div>
      </div>

      <SignalDetailModal
        detail={selectedDetectionDetail}
        onClose={() => setSelectedDetectionDetail(null)}
      />

      <ToastViewport toasts={toasts} onDismiss={dismissToast} />
    </main>
  );
}

export default App;
