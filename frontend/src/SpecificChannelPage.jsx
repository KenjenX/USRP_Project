import { useCallback, useEffect, useMemo, useState } from "react";
import "./SpecificChannelPage.css";

const TECHNOLOGY_OPTIONS = [
  {
    value: "2G E-GSM 900",
    label: "2G E-GSM 900",
    fcnLabel: "ARFCN",
  },
  {
    value: "2G DCS 1800",
    label: "2G DCS 1800",
    fcnLabel: "ARFCN",
  },
  {
    value: "3G UMTS",
    label: "3G UMTS",
    fcnLabel: "UARFCN",
  },
  {
    value: "4G LTE",
    label: "4G LTE",
    fcnLabel: "EARFCN",
  },
  {
    value: "5G NR",
    label: "5G NR",
    fcnLabel: "NR-ARFCN",
  },
];

// Frontend-only channel monitoring status. The backend can later become
// the authoritative source without changing the card UI contract.
const CHANNEL_MATCH_TOLERANCE_MHZ = 0.05;

function toFiniteNumber(value) {
  if (value === null || value === undefined || value === "") {
    return null;
  }

  const numberValue = Number(value);
  return Number.isFinite(numberValue) ? numberValue : null;
}

function getChannelTargetFrequencies(channel) {
  const targets = [];
  const dlFrequency = toFiniteNumber(channel?.freq_dl_mhz);
  const ulFrequency = toFiniteNumber(channel?.freq_ul_mhz);

  if (dlFrequency !== null) {
    targets.push({ side: "DL", frequencyMhz: dlFrequency });
  }

  if (
    ulFrequency !== null &&
    !targets.some(
      (target) =>
        Math.abs(target.frequencyMhz - ulFrequency) < 0.000001
    )
  ) {
    targets.push({ side: "UL", frequencyMhz: ulFrequency });
  }

  return targets;
}

function buildChannelScanResult({
  channel,
  scanConfig,
  scanDetections,
  channelMeasurements,
  sweepInfo,
}) {
  const targets = getChannelTargetFrequencies(channel);
  const scanStart = toFiniteNumber(scanConfig?.start_frequency_mhz);
  const scanEnd = toFiniteNumber(scanConfig?.end_frequency_mhz);
  const thresholdDb = toFiniteNumber(scanConfig?.threshold_db);

  if (
    targets.length === 0 ||
    scanStart === null ||
    scanEnd === null ||
    scanEnd <= scanStart
  ) {
    return {
      key: "not-scanned",
      label: "NOT SCANNED",
      detail: "Target frequency is unavailable",
      matchedFrequencyMhz: null,
      powerDb: null,
      side: null,
    };
  }

  const inRangeTargets = targets.filter(
    (target) =>
      target.frequencyMhz >= scanStart - CHANNEL_MATCH_TOLERANCE_MHZ &&
      target.frequencyMhz <= scanEnd + CHANNEL_MATCH_TOLERANCE_MHZ
  );

  if (inRangeTargets.length === 0) {
    return {
      key: "not-scanned",
      label: "NOT SCANNED",
      detail: "Channel frequency is outside the scan range",
      matchedFrequencyMhz: null,
      powerDb: null,
      side: null,
    };
  }

  const matchingMeasurements = (
    Array.isArray(channelMeasurements) ? channelMeasurements : []
  )
    .filter(
      (measurement) =>
        Number(measurement?.channel_id) === Number(channel?.id) &&
        toFiniteNumber(measurement?.power_db) !== null
    )
    .map((measurement) => ({
      side: measurement.side ?? null,
      targetFrequencyMhz: toFiniteNumber(
        measurement.target_frequency_mhz
      ),
      matchedFrequencyMhz: toFiniteNumber(
        measurement.measured_frequency_mhz
      ),
      powerDb: toFiniteNumber(measurement.power_db),
      aboveThreshold:
        typeof measurement.above_threshold === "boolean"
          ? measurement.above_threshold
          : toFiniteNumber(measurement.power_db) >= (thresholdDb ?? 0),
    }))
    .filter(
      (measurement) =>
        measurement.powerDb !== null &&
        inRangeTargets.some(
          (target) =>
            target.side === measurement.side ||
            Math.abs(
              target.frequencyMhz -
                (measurement.targetFrequencyMhz ??
                  measurement.matchedFrequencyMhz ??
                  target.frequencyMhz)
            ) <= CHANNEL_MATCH_TOLERANCE_MHZ
        )
    );

  if (matchingMeasurements.length > 0) {
    const strongestMeasurement = matchingMeasurements.reduce(
      (strongest, measurement) =>
        !strongest || measurement.powerDb > strongest.powerDb
          ? measurement
          : strongest,
      null
    );

    const isAboveThreshold = matchingMeasurements.some(
      (measurement) => measurement.aboveThreshold
    );

    const allInRangeTargetsMeasured = inRangeTargets.every(
      (target) =>
        matchingMeasurements.some(
          (measurement) =>
            target.side === measurement.side ||
            Math.abs(
              target.frequencyMhz -
                (measurement.targetFrequencyMhz ??
                  measurement.matchedFrequencyMhz ??
                  target.frequencyMhz)
            ) <= CHANNEL_MATCH_TOLERANCE_MHZ
        )
    );

    if (isAboveThreshold) {
      return {
        key: "on",
        label: "ON",
        detail: `${strongestMeasurement.side ?? "Channel"} is above ${
          thresholdDb ?? 0
        } dB`,
        side: strongestMeasurement.side,
        targetFrequencyMhz: strongestMeasurement.targetFrequencyMhz,
        matchedFrequencyMhz: strongestMeasurement.matchedFrequencyMhz,
        powerDb: strongestMeasurement.powerDb,
      };
    }

    if (!allInRangeTargetsMeasured) {
      return {
        key: "not-scanned",
        label: "NOT SCANNED",
        detail: "Waiting for the sweep to measure the remaining Channel targets",
        side: strongestMeasurement.side,
        targetFrequencyMhz: strongestMeasurement.targetFrequencyMhz,
        matchedFrequencyMhz: strongestMeasurement.matchedFrequencyMhz,
        powerDb: strongestMeasurement.powerDb,
      };
    }

    return {
      key: "off",
      label: "OFF",
      detail: `${strongestMeasurement.side ?? "Channel"} is below ${
        thresholdDb ?? 0
      } dB`,
      side: strongestMeasurement.side,
      targetFrequencyMhz: strongestMeasurement.targetFrequencyMhz,
      matchedFrequencyMhz: strongestMeasurement.matchedFrequencyMhz,
      powerDb: strongestMeasurement.powerDb,
    };
  }

  // Fallback kompatibilitas untuk response backend lama yang belum memiliki
  // channel_measurements dan hanya mengirim detection di atas threshold.
  let strongestMatch = null;

  (Array.isArray(scanDetections) ? scanDetections : []).forEach(
    (detection) => {
      const detectedFrequency = toFiniteNumber(detection?.frequency_mhz);
      const detectedPower = toFiniteNumber(detection?.power_db);

      if (detectedFrequency === null || detectedPower === null) {
        return;
      }

      inRangeTargets.forEach((target) => {
        const difference = Math.abs(
          detectedFrequency - target.frequencyMhz
        );

        if (difference > CHANNEL_MATCH_TOLERANCE_MHZ) {
          return;
        }

        if (
          !strongestMatch ||
          detectedPower > strongestMatch.powerDb
        ) {
          strongestMatch = {
            side: target.side,
            targetFrequencyMhz: target.frequencyMhz,
            matchedFrequencyMhz: detectedFrequency,
            powerDb: detectedPower,
          };
        }
      });
    }
  );

  if (strongestMatch) {
    return {
      key: "on",
      label: "ON",
      detail: `${strongestMatch.side} is above ${
        thresholdDb ?? 0
      } dB`,
      ...strongestMatch,
    };
  }

  const scannedWindows = toFiniteNumber(sweepInfo?.scanned_windows) ?? 0;
  const progressPercent = toFiniteNumber(sweepInfo?.progress_percent) ?? 0;
  const lastWindowEnd = toFiniteNumber(
    sweepInfo?.last_window_end_mhz
  );
  const sweepCompleted =
    Boolean(sweepInfo?.completed) || progressPercent >= 100;

  if (scannedWindows <= 0 && !sweepCompleted) {
    return {
      key: "not-scanned",
      label: "NOT SCANNED",
      detail: "No scan results yet",
      matchedFrequencyMhz: null,
      powerDb: null,
      side: null,
    };
  }

  const allTargetsCovered = sweepCompleted || (
    lastWindowEnd !== null &&
    inRangeTargets.every(
      (target) =>
        target.frequencyMhz <=
        lastWindowEnd + CHANNEL_MATCH_TOLERANCE_MHZ
    )
  );

  if (allTargetsCovered) {
    return {
      key: "off",
      label: "OFF",
      detail: "No power exceeded the threshold",
      matchedFrequencyMhz: null,
      powerDb: null,
      side: null,
    };
  }

  return {
    key: "not-scanned",
    label: "NOT SCANNED",
    detail: "Waiting for the sweep to reach the Channel frequency",
    matchedFrequencyMhz: null,
    powerDb: null,
    side: null,
  };
}

function buildUnavailableChannelScanResult(detail) {
  return {
    key: "not-scanned",
    label: "NOT SCANNED",
    detail,
    matchedFrequencyMhz: null,
    powerDb: null,
    side: null,
  };
}


function formatScanPower(value) {
  const numberValue = toFiniteNumber(value);
  return numberValue === null ? "-" : `${numberValue.toFixed(2)} dB`;
}

function formatFrequency(value) {
  if (value === null || value === undefined || value === "") {
    return "-";
  }

  const numericValue = Number(value);

  if (!Number.isFinite(numericValue)) {
    return "-";
  }

  const formatted = numericValue
    .toFixed(6)
    .replace(/\.?0+$/, "");

  return `${formatted} MHz`;
}

function formatFcn(value) {
  if (value === null || value === undefined || value === "") {
    return "-";
  }

  return String(value);
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
  });
}

function getApiError(data, fallbackMessage) {
  const detail = data?.detail;

  if (typeof detail === "string") {
    return detail;
  }

  if (detail && typeof detail === "object" && !Array.isArray(detail)) {
    const validKeys = Array.isArray(detail.valid_candidate_keys)
      ? ` Valid candidates: ${detail.valid_candidate_keys.join(", ")}`
      : "";

    return `${detail.message ?? fallbackMessage}${validKeys}`;
  }

  if (Array.isArray(detail)) {
    const validationMessages = detail
      .map((item) => item?.msg)
      .filter(Boolean);

    if (validationMessages.length > 0) {
      return validationMessages.join(" ");
    }
  }

  return fallbackMessage;
}

function candidateMatchesChannel(candidate, channel) {
  return (
    candidate.band === channel.band &&
    candidate.mode === channel.mode &&
    candidate.fcn_dl === channel.fcn_dl &&
    candidate.fcn_ul === channel.fcn_ul
  );
}

function CandidateSummary({ candidate, compact = false }) {
  if (!candidate) {
    return null;
  }

  return (
    <article
      className={`specific-candidate-card ${
        candidate.monitorable ? "" : "not-monitorable"
      } ${compact ? "compact" : ""}`}
    >
      <header className="specific-candidate-header">
        <div>
          <span>{candidate.technology}</span>
          <strong>
            {candidate.band} · {candidate.mode}
          </strong>
        </div>

        <span
          className={`specific-monitorable-badge ${
            candidate.monitorable ? "ready" : "blocked"
          }`}
        >
          {candidate.monitorable ? "MONITORABLE" : "OUT OF RANGE"}
        </span>
      </header>

      <div className="specific-candidate-grid">
        <div>
          <span>Band name</span>
          <strong>{candidate.band_name ?? "-"}</strong>
        </div>

        <div>
          <span>Direction</span>
          <strong>{candidate.direction ?? "-"}</strong>
        </div>

        <div>
          <span>DL frequency</span>
          <strong>{formatFrequency(candidate.freq_dl_mhz)}</strong>
        </div>

        <div>
          <span>UL frequency</span>
          <strong>{formatFrequency(candidate.freq_ul_mhz)}</strong>
        </div>

        <div>
          <span>DL {candidate.fcn_type}</span>
          <strong>{formatFcn(candidate.fcn_dl)}</strong>
        </div>

        <div>
          <span>UL {candidate.fcn_type}</span>
          <strong>{formatFcn(candidate.fcn_ul)}</strong>
        </div>
      </div>
    </article>
  );
}

function SpecificSpectrumPanel({
  scanConfig,
  isScanning,
  scanOwner,
  scannerLocked,
  selectedMachineName,
  scanSelectedMachineName,
  scanMatchesSelectedMachine,
  spectrumChart,
  spectrumHistoryCharts,
  frequencyTicks,
  chartDbTicks,
  thresholdTop,
}) {
  const ownScanRunning =
    isScanning &&
    scanOwner === "specific" &&
    scanMatchesSelectedMachine;
  const specificScanForOtherMachine = Boolean(
    scanOwner === "specific" &&
    scanSelectedMachineName &&
    !scanMatchesSelectedMachine
  );
  const hasSpectrum = Boolean(
    !scannerLocked &&
    scanMatchesSelectedMachine &&
    (spectrumChart?.linePoints || spectrumHistoryCharts?.length)
  );

  return (
    <section className="specific-spectrum-panel">
      <div className="specific-spectrum-titlebar status-only">
        <div className="specific-spectrum-status">
          <i
            className={
              ownScanRunning
                ? "running"
                : scannerLocked
                  ? "locked"
                  : "standby"
            }
          />
          {scannerLocked
            ? isScanning
              ? "GENERAL SCAN ACTIVE"
              : "GENERAL RESULT ISOLATED"
            : ownScanRunning
              ? `SCANNING ${selectedMachineName ?? "MACHINE"}`
              : specificScanForOtherMachine
                ? isScanning
                  ? "OTHER MACHINE SCAN ACTIVE"
                  : "MACHINE NOT SCANNED"
                : "STANDBY"}
        </div>
      </div>

      <div className="spectrum-chart specific-spectrum-chart">
        <div className="chart-y-axis" aria-hidden="true">
          {(chartDbTicks ?? []).map(({ value, position, isThreshold }) => (
            <span
              key={`specific-y-${value}`}
              className={isThreshold ? "threshold-y-tick" : ""}
              style={{ top: `${position}%` }}
            >
              {value} dB
            </span>
          ))}
        </div>

        <div className="chart-plot">
          {(chartDbTicks ?? []).map(({ value, position }) => (
            <div
              key={`specific-horizontal-${value}`}
              className="chart-h-grid-line"
              style={{ top: `${position}%` }}
            />
          ))}

          {(frequencyTicks ?? []).map(({ label, position }) => (
            <div
              key={`specific-vertical-${label}-${position}`}
              className="chart-v-grid-line"
              style={{ left: `${position}%` }}
            />
          ))}

          <div
            className="threshold-visual"
            style={{ top: `${thresholdTop ?? 0}%` }}
          >
            <span>Threshold {scanConfig?.threshold_db ?? 0} dB</span>
          </div>

          {hasSpectrum ? (
            <>
              {(spectrumHistoryCharts ?? []).length > 1 && (
                <svg
                  className="spectrum-history-svg"
                  viewBox="0 0 1000 260"
                  preserveAspectRatio="none"
                  aria-label="Specific sweep spectrum history"
                >
                  {spectrumHistoryCharts.slice(0, -1).map((segment) => (
                    <polyline
                      key={segment.id}
                      points={segment.linePoints}
                      className="spectrum-history-line"
                      fill="none"
                      vectorEffect="non-scaling-stroke"
                    />
                  ))}
                </svg>
              )}

              <svg
                className="spectrum-svg"
                viewBox="0 0 1000 260"
                preserveAspectRatio="none"
                aria-label="Specific realtime spectrum"
              >
                <polygon
                  points={spectrumChart?.areaPoints ?? ""}
                  className="spectrum-area"
                />
                <polyline
                  points={spectrumChart?.linePoints ?? ""}
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.25"
                  vectorEffect="non-scaling-stroke"
                />
              </svg>
            </>
          ) : (
            <div className="chart-placeholder">
              {scannerLocked
                ? isScanning
                  ? "The scanner is in use by the General Scan."
                  : "General Scan results are not used for Channel status."
                : specificScanForOtherMachine
                  ? `Specific Scan results belong to ${scanSelectedMachineName}, not ${
                      selectedMachineName ?? "this Machine"
                    }.`
                  : ownScanRunning
                    ? `Receiving spectrum data for ${selectedMachineName ?? "the selected Machine"}...`
                    : "Open a Machine, then select START SPECIFIC SCAN."}
            </div>
          )}
        </div>

        <div className="chart-x-axis" aria-hidden="true">
          {(frequencyTicks ?? []).map(({ label, position }, index) => (
            <span
              key={`specific-x-${label}-${position}`}
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
  );
}

function SpecificChannelPage({
  apiBaseUrl,
  scanConfig,
  isScanning,
  scanOwner,
  scanMode,
  scanSelectedMachineId,
  scanSelectedMachineName,
  scannerLocked,
  spectrumChart,
  spectrumHistoryCharts,
  frequencyTicks,
  chartDbTicks,
  thresholdTop,
  scanDetections,
  channelMeasurements,
  sweepInfo,
  onSelectedMachineChange,
}) {
  const [machines, setMachines] = useState([]);
  const [selectedMachineId, setSelectedMachineId] = useState(null);
  const [channels, setChannels] = useState([]);

  const [machineForm, setMachineForm] = useState({
    name: "",
    description: "",
  });
  const [editingMachineId, setEditingMachineId] = useState(null);

  const [channelForm, setChannelForm] = useState({
    input_mode: TECHNOLOGY_OPTIONS[0].value,
    input_fcn: "",
  });
  const [editingChannelId, setEditingChannelId] = useState(null);

  const [lookupCandidates, setLookupCandidates] = useState([]);
  const [selectedCandidateKey, setSelectedCandidateKey] = useState("");
  const [candidateModalOpen, setCandidateModalOpen] = useState(false);

  const [loadingMachines, setLoadingMachines] = useState(true);
  const [loadingChannels, setLoadingChannels] = useState(false);
  const [busyAction, setBusyAction] = useState("");
  const [noticeMessage, setNoticeMessage] = useState("");
  const [errorMessage, setErrorMessage] = useState("");
  const [deleteDialog, setDeleteDialog] = useState(null);

  const [workspaceView, setWorkspaceView] = useState("machines");
  const [machineEditorOpen, setMachineEditorOpen] = useState(false);
  const [channelEditorOpen, setChannelEditorOpen] = useState(false);
  const [machineSearch, setMachineSearch] = useState("");
  const [channelSearch, setChannelSearch] = useState("");
  const [machineChannelCounts, setMachineChannelCounts] = useState({});

  const selectedMachine = useMemo(
    () =>
      machines.find(
        (machine) => machine.id === Number(selectedMachineId)
      ) ?? null,
    [machines, selectedMachineId]
  );

  const machineWorkspaceActive = Boolean(
    workspaceView === "channels" && selectedMachineId !== null
  );

  const scanMatchesSelectedMachine = Boolean(
    machineWorkspaceActive &&
    scanOwner === "specific" &&
    scanSelectedMachineId !== null &&
    Number(selectedMachineId) === Number(scanSelectedMachineId)
  );

  const specificScanForOtherMachine = Boolean(
    machineWorkspaceActive &&
    scanOwner === "specific" &&
    scanSelectedMachineId !== null &&
    !scanMatchesSelectedMachine
  );

  const unavailableScanDetail = specificScanForOtherMachine
    ? `The latest Specific Scan belongs to ${
        scanSelectedMachineName ?? `Machine #${scanSelectedMachineId}`
      }`
    : "-";

  const editingChannel = useMemo(
    () =>
      channels.find(
        (channel) => channel.id === Number(editingChannelId)
      ) ?? null,
    [channels, editingChannelId]
  );

  const selectedCandidate = useMemo(
    () =>
      lookupCandidates.find(
        (candidate) => candidate.candidate_key === selectedCandidateKey
      ) ?? null,
    [lookupCandidates, selectedCandidateKey]
  );

  const currentTechnology = useMemo(
    () =>
      TECHNOLOGY_OPTIONS.find(
        (option) => option.value === channelForm.input_mode
      ) ?? TECHNOLOGY_OPTIONS[0],
    [channelForm.input_mode]
  );

  const filteredMachines = useMemo(() => {
    const query = machineSearch.trim().toLowerCase();

    if (!query) {
      return machines;
    }

    return machines.filter((machine) =>
      [machine.name, machine.description, machine.id]
        .filter((value) => value !== null && value !== undefined)
        .some((value) => String(value).toLowerCase().includes(query))
    );
  }, [machineSearch, machines]);

  const filteredChannels = useMemo(() => {
    const query = channelSearch.trim().toLowerCase();

    if (!query) {
      return channels;
    }

    return channels.filter((channel) =>
      [
        channel.channel_number,
        channel.band,
        channel.mode,
        channel.input_mode,
        channel.input_fcn,
        channel.fcn_dl,
        channel.fcn_ul,
      ]
        .filter((value) => value !== null && value !== undefined)
        .some((value) => String(value).toLowerCase().includes(query))
    );
  }, [channelSearch, channels]);

  const channelScanResults = useMemo(() => {
    const results = new Map();

    channels.forEach((channel) => {
      results.set(
        channel.id,
        scanMatchesSelectedMachine
          ? buildChannelScanResult({
              channel,
              scanConfig,
              scanDetections,
              channelMeasurements,
              sweepInfo,
            })
          : buildUnavailableChannelScanResult(unavailableScanDetail)
      );
    });

    return results;
  }, [
    channels,
    scanConfig,
    scanDetections,
    channelMeasurements,
    scanMatchesSelectedMachine,
    sweepInfo,
    unavailableScanDetail,
  ]);

  const channelStatusCounts = useMemo(() => {
    const counts = { on: 0, off: 0, "not-scanned": 0 };

    channelScanResults.forEach((result) => {
      if (Object.hasOwn(counts, result.key)) {
        counts[result.key] += 1;
      }
    });

    return counts;
  }, [channelScanResults]);

  const clearMessages = useCallback(() => {
    setNoticeMessage("");
    setErrorMessage("");
  }, []);

  const loadMachines = useCallback(
    async ({ preferredMachineId = null } = {}) => {
      setLoadingMachines(true);

      try {
        const response = await fetch(`${apiBaseUrl}/api/machines`);
        const data = await response.json();

        if (!response.ok) {
          throw new Error(
            getApiError(data, "Failed to load the Machine list.")
          );
        }

        const nextMachines = Array.isArray(data) ? data : [];
        setMachines(nextMachines);

        const channelCountEntries = await Promise.all(
          nextMachines.map(async (machine) => {
            try {
              const channelResponse = await fetch(
                `${apiBaseUrl}/api/machines/${machine.id}/channels`
              );
              const channelData = await channelResponse.json();

              return [
                machine.id,
                channelResponse.ok && Array.isArray(channelData)
                  ? channelData.length
                  : 0,
              ];
            } catch {
              return [machine.id, 0];
            }
          })
        );

        setMachineChannelCounts(Object.fromEntries(channelCountEntries));

        setSelectedMachineId((previousMachineId) => {
          const preferredExists = nextMachines.some(
            (machine) => machine.id === Number(preferredMachineId)
          );

          if (preferredMachineId !== null && preferredExists) {
            return Number(preferredMachineId);
          }

          const previousExists = nextMachines.some(
            (machine) => machine.id === Number(previousMachineId)
          );

          if (previousMachineId !== null && previousExists) {
            return Number(previousMachineId);
          }

          return nextMachines[0]?.id ?? null;
        });
      } finally {
        setLoadingMachines(false);
      }
    },
    [apiBaseUrl]
  );

  const loadChannels = useCallback(
    async (machineId) => {
      if (!machineId) {
        setChannels([]);
        return;
      }

      setLoadingChannels(true);

      try {
        const response = await fetch(
          `${apiBaseUrl}/api/machines/${machineId}/channels`
        );
        const data = await response.json();

        if (!response.ok) {
          throw new Error(
            getApiError(data, "Failed to load Machine Channels.")
          );
        }

        const nextChannels = Array.isArray(data) ? data : [];
        setChannels(nextChannels);
        setMachineChannelCounts((previousCounts) => ({
          ...previousCounts,
          [machineId]: nextChannels.length,
        }));
      } finally {
        setLoadingChannels(false);
      }
    },
    [apiBaseUrl]
  );

  useEffect(() => {
    loadMachines().catch(() => {
      setLoadingMachines(false);
    });
  }, [loadMachines]);

  useEffect(() => {
    loadChannels(selectedMachineId).catch(() => {
      setLoadingChannels(false);
    });
  }, [loadChannels, selectedMachineId]);

  useEffect(() => {
    onSelectedMachineChange?.(
      workspaceView === "channels" && selectedMachine
        ? { id: selectedMachine.id, name: selectedMachine.name }
        : null
    );
  }, [
    onSelectedMachineChange,
    selectedMachine,
    workspaceView,
  ]);

  useEffect(() => {
    function handleEscape(event) {
      if (event.key === "Escape") {
        setCandidateModalOpen(false);
      }
    }

    if (candidateModalOpen) {
      window.addEventListener("keydown", handleEscape);
    }

    return () => window.removeEventListener("keydown", handleEscape);
  }, [candidateModalOpen]);

  useEffect(() => {
    function handleDeleteDialogEscape(event) {
      if (event.key === "Escape" && !busyAction.startsWith("delete-")) {
        setDeleteDialog(null);
      }
    }

    if (deleteDialog) {
      window.addEventListener("keydown", handleDeleteDialogEscape);
    }

    return () =>
      window.removeEventListener("keydown", handleDeleteDialogEscape);
  }, [busyAction, deleteDialog]);

  function resetMachineForm() {
    setMachineForm({
      name: "",
      description: "",
    });
    setEditingMachineId(null);
    setMachineEditorOpen(false);
  }

  function resetChannelForm() {
    setChannelForm((previousForm) => ({
      input_mode: previousForm.input_mode,
      input_fcn: "",
    }));
    setEditingChannelId(null);
    setLookupCandidates([]);
    setSelectedCandidateKey("");
    setCandidateModalOpen(false);
    setChannelEditorOpen(false);
  }

  async function handleMachineSubmit(event) {
    event.preventDefault();
    clearMessages();

    const machineName = machineForm.name.trim();

    if (!machineName) {
      setErrorMessage("Machine name is required.");
      return;
    }

    const isEditing = editingMachineId !== null;
    setBusyAction(isEditing ? "update-machine" : "create-machine");

    try {
      const response = await fetch(
        isEditing
          ? `${apiBaseUrl}/api/machines/${editingMachineId}`
          : `${apiBaseUrl}/api/machines`,
        {
          method: isEditing ? "PUT" : "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            name: machineName,
            description: machineForm.description.trim() || null,
          }),
        }
      );

      const data = await response.json();

      if (!response.ok) {
        throw new Error(
          getApiError(
            data,
            isEditing
              ? "Failed to update the Machine."
              : "Failed to create the Machine."
          )
        );
      }

      resetMachineForm();
      await loadMachines({ preferredMachineId: data.id });
      setNoticeMessage(
        isEditing
          ? `Machine "${data.name}" updated.`
          : `Machine "${data.name}" created.`
      );
    } catch (error) {
      setErrorMessage(error.message);
    } finally {
      setBusyAction("");
    }
  }

  function startEditMachine(machine) {
    clearMessages();
    setWorkspaceView("machines");
    setMachineEditorOpen(true);
    setEditingMachineId(machine.id);
    setMachineForm({
      name: machine.name ?? "",
      description: machine.description ?? "",
    });
  }

  function handleDeleteMachine(machine) {
    clearMessages();
    setDeleteDialog({
      type: "machine",
      item: machine,
    });
  }

  async function confirmDeleteMachine(machine) {
    setBusyAction(`delete-machine-${machine.id}`);

    try {
      const response = await fetch(
        `${apiBaseUrl}/api/machines/${machine.id}`,
        {
          method: "DELETE",
        }
      );
      const data = await response.json();

      if (!response.ok) {
        throw new Error(
          getApiError(data, "Failed to delete the Machine.")
        );
      }

      if (editingMachineId === machine.id) {
        resetMachineForm();
      }

      if (selectedMachineId === machine.id) {
        resetChannelForm();
        setWorkspaceView("machines");
      }

      await loadMachines();
      setNoticeMessage(`Machine "${machine.name}" deleted.`);
    } catch (error) {
      setErrorMessage(error.message);
    } finally {
      setBusyAction("");
    }
  }

  async function runChannelLookup({
    mode = channelForm.input_mode,
    fcn = channelForm.input_fcn,
    preferredChannel = null,
  } = {}) {
    clearMessages();

    const numericFcn = Number(fcn);

    if (!Number.isInteger(numericFcn) || numericFcn < 0) {
      setErrorMessage(
        `${currentTechnology.fcnLabel} must be a non-negative integer.`
      );
      return [];
    }

    setBusyAction("lookup");

    try {
      const query = new URLSearchParams({
        input_mode: mode,
        fcn: String(numericFcn),
      });

      const response = await fetch(
        `${apiBaseUrl}/api/channel-lookup?${query.toString()}`
      );
      const data = await response.json();

      if (!response.ok) {
        throw new Error(
          getApiError(data, "Failed to find Channel candidates.")
        );
      }

      const candidates = Array.isArray(data.candidates)
        ? data.candidates
        : [];

      setLookupCandidates(candidates);

      if (candidates.length === 0) {
        setSelectedCandidateKey("");
        setCandidateModalOpen(false);
        setErrorMessage(
          `No candidates found for ${mode} with ${currentTechnology.fcnLabel} ${numericFcn}.`
        );
        return [];
      }

      const matchingCandidate = preferredChannel
        ? candidates.find((candidate) =>
            candidateMatchesChannel(candidate, preferredChannel)
          )
        : null;

      if (matchingCandidate) {
        setSelectedCandidateKey(matchingCandidate.candidate_key);
        setCandidateModalOpen(false);
        setNoticeMessage(
          `Candidate ${matchingCandidate.band} found for the Channel being edited.`
        );
      } else if (candidates.length === 1) {
        setSelectedCandidateKey(candidates[0].candidate_key);
        setCandidateModalOpen(false);
        setNoticeMessage(
          `One candidate found: ${candidates[0].band} · ${candidates[0].mode}.`
        );
      } else {
        setSelectedCandidateKey("");
        setCandidateModalOpen(true);
        setNoticeMessage(
          `${candidates.length} candidates found. Select one candidate.`
        );
      }

      return candidates;
    } catch (error) {
      setLookupCandidates([]);
      setSelectedCandidateKey("");
      setCandidateModalOpen(false);
      setErrorMessage(error.message);
      return [];
    } finally {
      setBusyAction("");
    }
  }

  async function handleChannelSubmit(event) {
    event.preventDefault();
    clearMessages();

    if (!selectedMachineId) {
      setErrorMessage("Select or create a Machine first.");
      return;
    }

    const numericFcn = Number(channelForm.input_fcn);

    if (!Number.isInteger(numericFcn) || numericFcn < 0) {
      setErrorMessage(
        `${currentTechnology.fcnLabel} must be a non-negative integer.`
      );
      return;
    }

    if (!selectedCandidateKey) {
      setErrorMessage(
        "Find and select a Channel candidate before saving."
      );
      return;
    }

    const isEditing = editingChannelId !== null;
    setBusyAction(isEditing ? "update-channel" : "create-channel");

    try {
      const response = await fetch(
        isEditing
          ? `${apiBaseUrl}/api/channels/${editingChannelId}`
          : `${apiBaseUrl}/api/machines/${selectedMachineId}/channels`,
        {
          method: isEditing ? "PUT" : "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            input_mode: channelForm.input_mode,
            input_fcn: numericFcn,
            candidate_key: selectedCandidateKey,
          }),
        }
      );

      const data = await response.json();

      if (!response.ok) {
        throw new Error(
          getApiError(
            data,
            isEditing
              ? "Failed to update the Channel."
              : "Failed to save the Channel."
          )
        );
      }

      await loadChannels(selectedMachineId);
      resetChannelForm();
      setNoticeMessage(
        isEditing
          ? `${data.channel_number} updated.`
          : `${data.channel_number} saved to ${selectedMachine?.name ?? "Machine"}.`
      );
    } catch (error) {
      setErrorMessage(error.message);
    } finally {
      setBusyAction("");
    }
  }

  async function startEditChannel(channel) {
    clearMessages();
    setWorkspaceView("channels");
    setChannelEditorOpen(true);
    setEditingChannelId(channel.id);
    setChannelForm({
      input_mode: channel.input_mode,
      input_fcn: String(channel.input_fcn),
    });
    setLookupCandidates([]);
    setSelectedCandidateKey("");

    await runChannelLookup({
      mode: channel.input_mode,
      fcn: channel.input_fcn,
      preferredChannel: channel,
    });

    window.requestAnimationFrame(() => {
      document
        .getElementById("specific-channel-form")
        ?.scrollIntoView({
          behavior: "smooth",
          block: "start",
        });
    });
  }

  function handleDeleteChannel(channel) {
    clearMessages();
    setDeleteDialog({
      type: "channel",
      item: channel,
    });
  }

  async function confirmDeleteChannel(channel) {
    setBusyAction(`delete-channel-${channel.id}`);

    try {
      const response = await fetch(
        `${apiBaseUrl}/api/channels/${channel.id}`,
        {
          method: "DELETE",
        }
      );
      const data = await response.json();

      if (!response.ok) {
        throw new Error(
          getApiError(data, "Failed to delete the Channel.")
        );
      }

      if (editingChannelId === channel.id) {
        resetChannelForm();
      }

      await loadChannels(selectedMachineId);
      setNoticeMessage(
        `${channel.channel_number} deleted.`
      );
    } catch (error) {
      setErrorMessage(error.message);
    } finally {
      setBusyAction("");
    }
  }

  async function confirmSpecificDelete() {
    if (!deleteDialog?.item) {
      return;
    }

    const currentDialog = deleteDialog;

    if (currentDialog.type === "machine") {
      await confirmDeleteMachine(currentDialog.item);
    } else {
      await confirmDeleteChannel(currentDialog.item);
    }

    setDeleteDialog(null);
  }

  function chooseCandidate(candidate) {
    setSelectedCandidateKey(candidate.candidate_key);
    setCandidateModalOpen(false);
    setNoticeMessage(
      `${candidate.band} · ${candidate.mode} selected.`
    );
    setErrorMessage("");
  }

  function openCreateMachine() {
    clearMessages();
    setEditingMachineId(null);
    setMachineForm({ name: "", description: "" });
    setMachineEditorOpen(true);
    setWorkspaceView("machines");
  }

  function openCreateChannel() {
    clearMessages();
    setEditingChannelId(null);
    setChannelForm((previousForm) => ({
      input_mode: previousForm.input_mode,
      input_fcn: "",
    }));
    setLookupCandidates([]);
    setSelectedCandidateKey("");
    setCandidateModalOpen(false);
    setChannelEditorOpen(true);
  }

  function selectMachine(machine) {
    clearMessages();

    if (
      isScanning &&
      scanOwner === "specific" &&
      scanSelectedMachineId !== null &&
      Number(machine.id) !== Number(scanSelectedMachineId)
    ) {
      setErrorMessage(
        `Stop the Specific Scan for ${
          scanSelectedMachineName ?? `Machine #${scanSelectedMachineId}`
        } before selecting another Machine.`
      );
      return;
    }

    setSelectedMachineId(machine.id);
    resetChannelForm();
    setWorkspaceView("channels");
  }

  return (
    <>
      <section className="specific-workspace specific-figma-workspace">
        <SpecificSpectrumPanel
          scanConfig={scanConfig}
          isScanning={isScanning}
          scanOwner={scanOwner}
          scannerLocked={scannerLocked}
          selectedMachineName={
            machineWorkspaceActive ? selectedMachine?.name ?? null : null
          }
          scanSelectedMachineName={scanSelectedMachineName}
          scanMatchesSelectedMachine={scanMatchesSelectedMachine}
          spectrumChart={spectrumChart}
          spectrumHistoryCharts={spectrumHistoryCharts}
          frequencyTicks={frequencyTicks}
          chartDbTicks={chartDbTicks}
          thresholdTop={thresholdTop}
        />

        {specificScanForOtherMachine && (
          <div className="specific-machine-scan-notice">
            <strong>SPECIFIC SCAN IS TIED TO ONE MACHINE</strong>
            <span>
              The active results are from {
                scanSelectedMachineName ?? `Machine #${scanSelectedMachineId}`
              }. Channels on {selectedMachine?.name ?? "this Machine"} remain
              NOT SCANNED.
            </span>
          </div>
        )}

        {scannerLocked && (
          <div className="specific-scan-isolation-notice">
            <strong>
              {isScanning
                ? "GENERAL SCAN IS RUNNING"
                : "GENERAL SCAN RESULTS ARE ISOLATED"}
            </strong>
            <span>
              Channel ON/OFF status is updated only by Specific Scan.
              {scanMode ? ` Active mode: ${scanMode.replaceAll("_", " ")}.` : ""}
            </span>
          </div>
        )}

        {(noticeMessage || errorMessage) && (
          <div
            className={`specific-feedback ${
              errorMessage ? "error" : "success"
            }`}
          >
            {errorMessage || noticeMessage}
          </div>
        )}

        {workspaceView === "machines" ? (
          <section className="specific-figma-content machine-view">
            <div className="specific-figma-toolbar">
              <div className="specific-toolbar-count">
                <strong>{machines.length}</strong>
                <span>{machines.length === 1 ? "Machine" : "Machines"}</span>
              </div>

              <button
                type="button"
                className="specific-toolbar-button primary"
                onClick={openCreateMachine}
              >
                ＋ ADD MACHINE
              </button>

              <label className="specific-search-box">
                <span>⌕</span>
                <input
                  type="search"
                  value={machineSearch}
                  onChange={(event) => setMachineSearch(event.target.value)}
                  placeholder="Search machine"
                />
              </label>
            </div>

            {machineEditorOpen && (
              <form
                className="specific-editor-panel machine-editor"
                onSubmit={handleMachineSubmit}
              >
                <div className="specific-editor-heading">
                  <div>
                    <span>{editingMachineId ? "EDIT MACHINE" : "NEW MACHINE"}</span>
                    <strong>
                      {editingMachineId
                        ? "Update machine information"
                        : "Create a new machine"}
                    </strong>
                  </div>

                  <button
                    type="button"
                    className="specific-editor-close"
                    onClick={resetMachineForm}
                    aria-label="Close machine editor"
                  >
                    ×
                  </button>
                </div>

                <div className="specific-editor-fields machine-fields">
                  <div className="specific-field">
                    <label htmlFor="specific-machine-name">Machine name</label>
                    <input
                      id="specific-machine-name"
                      type="text"
                      maxLength={100}
                      value={machineForm.name}
                      onChange={(event) =>
                        setMachineForm((previousForm) => ({
                          ...previousForm,
                          name: event.target.value,
                        }))
                      }
                      placeholder="Example: Machine-X"
                    />
                  </div>

                  <div className="specific-field">
                    <label htmlFor="specific-machine-description">Description</label>
                    <input
                      id="specific-machine-description"
                      type="text"
                      value={machineForm.description}
                      onChange={(event) =>
                        setMachineForm((previousForm) => ({
                          ...previousForm,
                          description: event.target.value,
                        }))
                      }
                      placeholder="Machine description"
                    />
                  </div>
                </div>

                <div className="specific-form-actions">
                  <button
                    type="submit"
                    className="specific-primary-button"
                    disabled={
                      busyAction === "create-machine" ||
                      busyAction === "update-machine"
                    }
                  >
                    {busyAction === "create-machine" ||
                    busyAction === "update-machine"
                      ? "PROCESSING..."
                      : editingMachineId
                        ? "UPDATE MACHINE"
                        : "CREATE MACHINE"}
                  </button>

                  <button
                    type="button"
                    className="specific-secondary-button"
                    onClick={resetMachineForm}
                  >
                    CANCEL
                  </button>
                </div>
              </form>
            )}

            <div className="specific-machine-table-shell">
              <div className="specific-machine-table-head">
                <span>No</span>
                <span>Machine</span>
                <span>Description</span>
                <span>Channel</span>
                <span>Action</span>
              </div>

              <div className="specific-machine-table-body">
                {loadingMachines ? (
                  <div className="specific-table-empty">Loading Machines...</div>
                ) : filteredMachines.length === 0 ? (
                  <div className="specific-table-empty">
                    {machines.length === 0
                      ? "No Machines yet. Select ADD MACHINE to create the first Machine."
                      : "No Machines found."}
                  </div>
                ) : (
                  filteredMachines.map((machine, index) => (
                    <article
                      className={`specific-machine-table-row ${
                        selectedMachineId === machine.id ? "selected" : ""
                      }`}
                      key={machine.id}
                    >
                      <span className="machine-row-number">{index + 1}</span>

                      <span className="machine-row-name">
                        <i>M</i>
                        <strong>{machine.name}</strong>
                      </span>

                      <span className="machine-row-description">
                        {machine.description || "Tanpa deskripsi"}
                      </span>

                      <strong className="machine-row-count">
                        {machineChannelCounts[machine.id] ?? 0}
                      </strong>

                      <span className="machine-row-actions">
                        <button
                          type="button"
                          className="select"
                          disabled={
                            isScanning &&
                            scanOwner === "specific" &&
                            scanSelectedMachineId !== null &&
                            Number(machine.id) !== Number(scanSelectedMachineId)
                          }
                          onClick={() => selectMachine(machine)}
                        >
                          SELECT
                        </button>
                        <button
                          type="button"
                          onClick={() => startEditMachine(machine)}
                        >
                          EDIT
                        </button>
                        <button
                          type="button"
                          className="danger"
                          disabled={busyAction === `delete-machine-${machine.id}`}
                          onClick={() => handleDeleteMachine(machine)}
                        >
                          DELETE
                        </button>
                      </span>
                    </article>
                  ))
                )}
              </div>
            </div>
          </section>
        ) : (
          <section className="specific-figma-content channel-view">
            <div className="specific-figma-toolbar channel-toolbar">
              <button
                type="button"
                className="specific-toolbar-button back"
                onClick={() => {
                  resetChannelForm();
                  setWorkspaceView("machines");
                }}
              >
                ← BACK
              </button>

              <div className="specific-selected-machine-chip">
                <strong>{selectedMachine?.name ?? "Machine"}</strong>
              </div>

              <button
                type="button"
                className="specific-toolbar-button primary"
                onClick={openCreateChannel}
              >
                ＋ ADD CHANNEL
              </button>

              <label className="specific-search-box">
                <span>⌕</span>
                <input
                  type="search"
                  value={channelSearch}
                  onChange={(event) => setChannelSearch(event.target.value)}
                  placeholder="Search channel"
                />
              </label>

            </div>

            {!selectedMachine ? (
              <div className="specific-channel-empty">
                Machine not found. Return to the Machine list and select one again.
              </div>
            ) : (
              <>
                {channelEditorOpen && (
                  <form
                    id="specific-channel-form"
                    className="specific-editor-panel specific-channel-form"
                    onSubmit={handleChannelSubmit}
                  >
                    <div className="specific-editor-heading">
                      <div>
                        <span>
                          {editingChannelId ? "EDIT CHANNEL" : "NEW CHANNEL"}
                        </span>
                        <strong>
                          {editingChannelId
                            ? `Editing ${editingChannel?.channel_number ?? "Channel"}`
                            : `Add channel to ${selectedMachine.name}`}
                        </strong>
                      </div>

                      <button
                        type="button"
                        className="specific-editor-close"
                        onClick={resetChannelForm}
                        aria-label="Close channel editor"
                      >
                        ×
                      </button>
                    </div>

                    {editingChannel && (
                      <div className="specific-editing-banner">
                        <div>
                          <span>EDIT MODE ACTIVE</span>
                          <strong>EDITING {editingChannel.channel_number}</strong>
                          <p>
                            Change the Technology/Profile or FCN, select FIND CHANNEL,
                            choose a candidate, then select UPDATE CHANNEL.
                          </p>
                        </div>
                        <small>
                          Current values: {editingChannel.input_mode} · FCN {" "}
                          {editingChannel.input_fcn}
                        </small>
                      </div>
                    )}

                    <div className="specific-editor-fields channel-fields">
                      <div className="specific-field">
                        <label htmlFor="specific-input-mode">
                          Technology/Profile
                        </label>
                        <select
                          id="specific-input-mode"
                          value={channelForm.input_mode}
                          onChange={(event) => {
                            const nextMode = event.target.value;
                            setChannelForm((previousForm) => ({
                              ...previousForm,
                              input_mode: nextMode,
                            }));
                            setLookupCandidates([]);
                            setSelectedCandidateKey("");
                            setCandidateModalOpen(false);
                            setErrorMessage("");
                            setNoticeMessage(
                              editingChannelId !== null
                                ? `Edit mode for ${editingChannel?.channel_number ?? "Channel"} remains active. Select FIND CHANNEL to find a new candidate.`
                                : ""
                            );
                          }}
                        >
                          {TECHNOLOGY_OPTIONS.map((option) => (
                            <option value={option.value} key={option.value}>
                              {option.label}
                            </option>
                          ))}
                        </select>
                      </div>

                      <div className="specific-field">
                        <label htmlFor="specific-input-fcn">
                          {currentTechnology.fcnLabel}
                        </label>
                        <input
                          id="specific-input-fcn"
                          type="number"
                          min="0"
                          step="1"
                          value={channelForm.input_fcn}
                          onChange={(event) => {
                            setChannelForm((previousForm) => ({
                              ...previousForm,
                              input_fcn: event.target.value,
                            }));
                            setLookupCandidates([]);
                            setSelectedCandidateKey("");
                            setCandidateModalOpen(false);
                            setErrorMessage("");
                            setNoticeMessage(
                              editingChannelId !== null
                                ? `Edit mode for ${editingChannel?.channel_number ?? "Channel"} remains active. Select FIND CHANNEL to validate the new FCN.`
                                : ""
                            );
                          }}
                          placeholder={`Enter ${currentTechnology.fcnLabel}`}
                        />
                      </div>
                    </div>

                    <div className="specific-channel-form-buttons">
                      <button
                        type="button"
                        className="specific-secondary-button find"
                        disabled={busyAction === "lookup"}
                        onClick={() => runChannelLookup()}
                      >
                        {busyAction === "lookup" ? "SEARCHING..." : "FIND CHANNEL"}
                      </button>

                      <button
                        type="submit"
                        className="specific-primary-button"
                        disabled={
                          !selectedCandidateKey ||
                          busyAction === "create-channel" ||
                          busyAction === "update-channel"
                        }
                      >
                        {busyAction === "update-channel"
                          ? "UPDATING..."
                          : busyAction === "create-channel"
                            ? "SAVING..."
                            : editingChannelId
                              ? "UPDATE CHANNEL"
                              : "SAVE CHANNEL"}
                      </button>

                      <button
                        type="button"
                        className="specific-secondary-button"
                        onClick={resetChannelForm}
                      >
                        CANCEL
                      </button>
                    </div>
                  </form>
                )}

                {selectedCandidate && channelEditorOpen && (
                  <div className="specific-selected-candidate">
                    <div className="specific-selected-heading">
                      <div>
                        <p className="section-kicker">SELECTED CANDIDATE</p>
                        <h5>
                          {selectedCandidate.band} · {selectedCandidate.mode}
                        </h5>
                      </div>

                      {lookupCandidates.length > 1 && (
                        <button
                          type="button"
                          className="specific-secondary-button"
                          onClick={() => setCandidateModalOpen(true)}
                        >
                          CHANGE
                        </button>
                      )}
                    </div>
                    <CandidateSummary candidate={selectedCandidate} />
                  </div>
                )}

                <div className="specific-channel-monitor-summary">
                  <div>
                    <span className="monitor-summary-label">CHANNEL STATUS</span>
                    <small>
                      {scanMatchesSelectedMachine
                        ? `Specific Scan results for ${selectedMachine?.name ?? "this Machine"}`
                        : unavailableScanDetail}
                    </small>
                  </div>

                  <div className="monitor-summary-counts">
                    <span className="on">
                      ON <strong>{channelStatusCounts.on}</strong>
                    </span>
                    <span className="off">
                      OFF <strong>{channelStatusCounts.off}</strong>
                    </span>
                    <span className="not-scanned">
                      NOT SCANNED {" "}
                      <strong>{channelStatusCounts["not-scanned"]}</strong>
                    </span>
                  </div>
                </div>

                {loadingChannels ? (
                  <div className="specific-channel-empty">Loading Channels...</div>
                ) : filteredChannels.length === 0 ? (
                  <div className="specific-channel-empty">
                    {channels.length === 0
                      ? "This Machine has no Channels yet. Select ADD CHANNEL to add the first Channel."
                      : "No Channels match the search or filter."}
                  </div>
                ) : (
                  <div className="specific-saved-channel-grid figma-channel-grid">
                    {filteredChannels.map((channel) => {
                      const scanResult =
                        channelScanResults.get(channel.id) ??
                        buildUnavailableChannelScanResult(
                          unavailableScanDetail
                        );

                      return (
                      <article
                        className={`specific-saved-channel-card figma-channel-card status-${scanResult.key} ${
                          editingChannelId === channel.id ? "editing" : ""
                        }`}
                        key={channel.id}
                      >
                        <header>
                          <div className="figma-channel-identity">
                            <span className="figma-channel-radio">◉</span>
                            <span>
                              <strong>{channel.channel_number}</strong>
                              <small>FCN {formatFcn(channel.input_fcn)}</small>
                            </span>
                          </div>

                          <span
                            className={`figma-channel-state ${scanResult.key}`}
                            title={scanResult.detail}
                          >
                            {scanResult.label}
                          </span>
                        </header>

                        <div className="figma-channel-title">
                          <strong>{channel.band}</strong>
                          <span>{channel.mode}</span>
                        </div>

                        <div className="specific-saved-channel-details">
                          <div>
                            <span>Technology/Profile</span>
                            <strong>{channel.input_mode}</strong>
                          </div>
                          <div>
                            <span>Input FCN</span>
                            <strong>{formatFcn(channel.input_fcn)}</strong>
                          </div>
                          <div>
                            <span>DL frequency</span>
                            <strong>{formatFrequency(channel.freq_dl_mhz)}</strong>
                          </div>
                          <div>
                            <span>UL frequency</span>
                            <strong>{formatFrequency(channel.freq_ul_mhz)}</strong>
                          </div>
                          <div>
                            <span>DL FCN</span>
                            <strong>{formatFcn(channel.fcn_dl)}</strong>
                          </div>
                          <div>
                            <span>UL FCN</span>
                            <strong>{formatFcn(channel.fcn_ul)}</strong>
                          </div>
                          <div className="channel-scan-detail">
                            <span>Power (dB)</span>
                            <strong className={scanResult.key}>
                              {formatScanPower(scanResult.powerDb)}
                            </strong>
                          </div>
                          <div className="channel-scan-detail">
                            <span>Scan Result</span>
                            <strong className={scanResult.key}>
                              {scanResult.detail}
                            </strong>
                          </div>
                        </div>

                        <footer>
                          <span>Updated {formatDateTime(channel.updated_at)}</span>
                          <div className="specific-card-actions">
                            <button
                              type="button"
                              onClick={() => startEditChannel(channel)}
                            >
                              EDIT
                            </button>
                            <button
                              type="button"
                              className="danger"
                              disabled={busyAction === `delete-channel-${channel.id}`}
                              onClick={() => handleDeleteChannel(channel)}
                            >
                              DELETE
                            </button>
                          </div>
                        </footer>
                      </article>
                      );
                    })}
                  </div>
                )}
              </>
            )}
          </section>
        )}
      </section>

      {deleteDialog && (
        <div
          className="specific-delete-backdrop"
          role="presentation"
          onClick={() => {
            if (!busyAction.startsWith("delete-")) {
              setDeleteDialog(null);
            }
          }}
        >
          <section
            className="specific-delete-modal"
            role="dialog"
            aria-modal="true"
            aria-label={
              deleteDialog.type === "machine"
                ? "Confirm Machine deletion"
                : "Confirm Channel deletion"
            }
            onClick={(event) => event.stopPropagation()}
          >
            <div className="specific-delete-icon" aria-hidden="true">
              !
            </div>

            <div className="specific-delete-content">
              <p className="section-kicker">DELETE CONFIRMATION</p>

              <h3>
                {deleteDialog.type === "machine"
                  ? `Delete Machine "${deleteDialog.item.name}"?`
                  : `Delete ${deleteDialog.item.channel_number}?`}
              </h3>

              <p>
                {deleteDialog.type === "machine"
                  ? "All Channels stored in this Machine will also be permanently deleted."
                  : `${deleteDialog.item.band} · ${deleteDialog.item.mode} will be permanently deleted from this Machine.`}
              </p>
            </div>

            <div className="specific-delete-actions">
              <button
                type="button"
                className="specific-delete-cancel"
                disabled={busyAction.startsWith("delete-")}
                onClick={() => setDeleteDialog(null)}
              >
                CANCEL
              </button>

              <button
                type="button"
                className="specific-delete-confirm"
                disabled={busyAction.startsWith("delete-")}
                onClick={confirmSpecificDelete}
              >
                {busyAction.startsWith("delete-")
                  ? "DELETING..."
                  : "DELETE"}
              </button>
            </div>
          </section>
        </div>
      )}

      {candidateModalOpen && (
        <div
          className="specific-candidate-backdrop"
          role="presentation"
          onClick={() => setCandidateModalOpen(false)}
        >
          <section
            className="specific-candidate-modal"
            role="dialog"
            aria-modal="true"
            aria-label="Select Channel candidate"
            onClick={(event) => event.stopPropagation()}
          >
            <header>
              <div>
                <p className="section-kicker">MULTIPLE CANDIDATES</p>
                <h4>Select a Channel candidate</h4>
                <span>
                  {channelForm.input_mode} · {currentTechnology.fcnLabel} {" "}
                  {channelForm.input_fcn}
                </span>
              </div>

              <button
                type="button"
                className="specific-modal-close"
                onClick={() => setCandidateModalOpen(false)}
                aria-label="Close candidate modal"
              >
                ×
              </button>
            </header>

            <div className="specific-candidate-modal-list">
              {lookupCandidates.map((candidate) => (
                <div
                  className={`specific-candidate-option ${
                    selectedCandidateKey === candidate.candidate_key
                      ? "selected"
                      : ""
                  }`}
                  key={candidate.candidate_key}
                >
                  <CandidateSummary candidate={candidate} compact />

                  <button
                    type="button"
                    className="specific-primary-button"
                    disabled={!candidate.monitorable}
                    onClick={() => chooseCandidate(candidate)}
                  >
                    {candidate.monitorable
                      ? "SELECT CANDIDATE"
                      : "OUT OF RANGE"}
                  </button>
                </div>
              ))}
            </div>
          </section>
        </div>
      )}
    </>
  );

}

export default SpecificChannelPage;
