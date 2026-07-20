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
      ? ` Kandidat valid: ${detail.valid_candidate_keys.join(", ")}`
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

function SpecificChannelPage({ apiBaseUrl }) {
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

  const selectedMachine = useMemo(
    () =>
      machines.find(
        (machine) => machine.id === Number(selectedMachineId)
      ) ?? null,
    [machines, selectedMachineId]
  );

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
            getApiError(data, "Gagal memuat daftar Machine.")
          );
        }

        const nextMachines = Array.isArray(data) ? data : [];
        setMachines(nextMachines);

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
            getApiError(data, "Gagal memuat Channel Machine.")
          );
        }

        setChannels(Array.isArray(data) ? data : []);
      } finally {
        setLoadingChannels(false);
      }
    },
    [apiBaseUrl]
  );

  useEffect(() => {
    loadMachines().catch((error) => {
      setErrorMessage(error.message);
      setLoadingMachines(false);
    });
  }, [loadMachines]);

  useEffect(() => {
    loadChannels(selectedMachineId).catch((error) => {
      setErrorMessage(error.message);
      setLoadingChannels(false);
    });
  }, [loadChannels, selectedMachineId]);

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

  function resetMachineForm() {
    setMachineForm({
      name: "",
      description: "",
    });
    setEditingMachineId(null);
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
  }

  async function handleMachineSubmit(event) {
    event.preventDefault();
    clearMessages();

    const machineName = machineForm.name.trim();

    if (!machineName) {
      setErrorMessage("Nama Machine tidak boleh kosong.");
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
              ? "Gagal memperbarui Machine."
              : "Gagal membuat Machine."
          )
        );
      }

      resetMachineForm();
      await loadMachines({ preferredMachineId: data.id });
      setNoticeMessage(
        isEditing
          ? `Machine "${data.name}" berhasil diperbarui.`
          : `Machine "${data.name}" berhasil dibuat.`
      );
    } catch (error) {
      setErrorMessage(error.message);
    } finally {
      setBusyAction("");
    }
  }

  function startEditMachine(machine) {
    clearMessages();
    setEditingMachineId(machine.id);
    setMachineForm({
      name: machine.name ?? "",
      description: machine.description ?? "",
    });
  }

  async function handleDeleteMachine(machine) {
    const confirmed = window.confirm(
      `Hapus Machine "${machine.name}" beserta seluruh Channel di dalamnya?`
    );

    if (!confirmed) {
      return;
    }

    clearMessages();
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
          getApiError(data, "Gagal menghapus Machine.")
        );
      }

      if (editingMachineId === machine.id) {
        resetMachineForm();
      }

      if (selectedMachineId === machine.id) {
        resetChannelForm();
      }

      await loadMachines();
      setNoticeMessage(`Machine "${machine.name}" berhasil dihapus.`);
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
        `${currentTechnology.fcnLabel} harus berupa bilangan bulat minimal 0.`
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
          getApiError(data, "Gagal mencari kandidat Channel.")
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
          `Tidak ada kandidat untuk ${mode} dengan ${currentTechnology.fcnLabel} ${numericFcn}.`
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
          `Kandidat ${matchingCandidate.band} berhasil ditemukan untuk Channel yang diedit.`
        );
      } else if (candidates.length === 1) {
        setSelectedCandidateKey(candidates[0].candidate_key);
        setCandidateModalOpen(false);
        setNoticeMessage(
          `Satu kandidat ditemukan: ${candidates[0].band} · ${candidates[0].mode}.`
        );
      } else {
        setSelectedCandidateKey("");
        setCandidateModalOpen(true);
        setNoticeMessage(
          `${candidates.length} kandidat ditemukan. Pilih satu kandidat.`
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
      setErrorMessage("Pilih atau buat Machine terlebih dahulu.");
      return;
    }

    const numericFcn = Number(channelForm.input_fcn);

    if (!Number.isInteger(numericFcn) || numericFcn < 0) {
      setErrorMessage(
        `${currentTechnology.fcnLabel} harus berupa bilangan bulat minimal 0.`
      );
      return;
    }

    if (!selectedCandidateKey) {
      setErrorMessage(
        "Cari dan pilih kandidat Channel sebelum menyimpan."
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
              ? "Gagal memperbarui Channel."
              : "Gagal menyimpan Channel."
          )
        );
      }

      await loadChannels(selectedMachineId);
      resetChannelForm();
      setNoticeMessage(
        isEditing
          ? `${data.channel_number} berhasil diperbarui.`
          : `${data.channel_number} berhasil disimpan ke ${selectedMachine?.name ?? "Machine"}.`
      );
    } catch (error) {
      setErrorMessage(error.message);
    } finally {
      setBusyAction("");
    }
  }

  async function startEditChannel(channel) {
    clearMessages();
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

  async function handleDeleteChannel(channel) {
    const confirmed = window.confirm(
      `Hapus ${channel.channel_number} (${channel.band} · ${channel.mode})?`
    );

    if (!confirmed) {
      return;
    }

    clearMessages();
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
          getApiError(data, "Gagal menghapus Channel.")
        );
      }

      if (editingChannelId === channel.id) {
        resetChannelForm();
      }

      await loadChannels(selectedMachineId);
      setNoticeMessage(
        `${channel.channel_number} berhasil dihapus.`
      );
    } catch (error) {
      setErrorMessage(error.message);
    } finally {
      setBusyAction("");
    }
  }

  function chooseCandidate(candidate) {
    setSelectedCandidateKey(candidate.candidate_key);
    setCandidateModalOpen(false);
    setNoticeMessage(
      `${candidate.band} · ${candidate.mode} dipilih.`
    );
    setErrorMessage("");
  }

  return (
    <>
      <section className="specific-workspace">
        <header className="specific-workspace-header">
          <div>
            <p className="section-kicker">MACHINE CHANNEL CONFIGURATION</p>
            <h3>Specific Channel Manager</h3>
            <p>
              Buat Machine, masukkan Technology/Profile dan FCN, lalu
              pilih kandidat band sebelum Channel disimpan ke MySQL.
            </p>
          </div>

          <div className="specific-workspace-stats">
            <div>
              <span>Machines</span>
              <strong>{machines.length}</strong>
            </div>
            <div>
              <span>Selected channels</span>
              <strong>{channels.length}</strong>
            </div>
          </div>
        </header>

        {(noticeMessage || errorMessage) && (
          <div
            className={`specific-feedback ${
              errorMessage ? "error" : "success"
            }`}
          >
            {errorMessage || noticeMessage}
          </div>
        )}

        <div className="specific-layout">
          <aside className="specific-machine-panel">
            <div className="specific-panel-heading">
              <div>
                <p className="section-kicker">STEP 1</p>
                <h4>Machines</h4>
              </div>
              <span>{machines.length}</span>
            </div>

            <form
              className="specific-machine-form"
              onSubmit={handleMachineSubmit}
            >
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
                placeholder="Contoh: Machine-X"
              />

              <label htmlFor="specific-machine-description">
                Description
              </label>
              <textarea
                id="specific-machine-description"
                rows={3}
                value={machineForm.description}
                onChange={(event) =>
                  setMachineForm((previousForm) => ({
                    ...previousForm,
                    description: event.target.value,
                  }))
                }
                placeholder="Keterangan Machine"
              />

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

                {editingMachineId && (
                  <button
                    type="button"
                    className="specific-secondary-button"
                    onClick={resetMachineForm}
                  >
                    CANCEL
                  </button>
                )}
              </div>
            </form>

            <div className="specific-machine-list">
              {loadingMachines ? (
                <div className="specific-empty-state">
                  Memuat Machine...
                </div>
              ) : machines.length === 0 ? (
                <div className="specific-empty-state">
                  Belum ada Machine. Buat Machine pertama.
                </div>
              ) : (
                machines.map((machine) => (
                  <article
                    className={`specific-machine-card ${
                      selectedMachineId === machine.id ? "selected" : ""
                    }`}
                    key={machine.id}
                  >
                    <button
                      type="button"
                      className="specific-machine-select"
                      onClick={() => {
                        clearMessages();
                        setSelectedMachineId(machine.id);
                        resetChannelForm();
                      }}
                    >
                      <span className="specific-machine-icon">M</span>
                      <span>
                        <strong>{machine.name}</strong>
                        <small>
                          {machine.description || "Tanpa deskripsi"}
                        </small>
                      </span>
                    </button>

                    <div className="specific-card-actions">
                      <button
                        type="button"
                        onClick={() => startEditMachine(machine)}
                      >
                        EDIT
                      </button>
                      <button
                        type="button"
                        className="danger"
                        disabled={
                          busyAction === `delete-machine-${machine.id}`
                        }
                        onClick={() => handleDeleteMachine(machine)}
                      >
                        DELETE
                      </button>
                    </div>
                  </article>
                ))
              )}
            </div>
          </aside>

          <section className="specific-channel-panel">
            <div className="specific-panel-heading">
              <div>
                <p className="section-kicker">STEP 2</p>
                <h4>
                  {selectedMachine
                    ? `${selectedMachine.name} Channels`
                    : "Select a Machine"}
                </h4>
              </div>

              {selectedMachine && (
                <span>{channels.length}</span>
              )}
            </div>

            {!selectedMachine ? (
              <div className="specific-channel-empty">
                Pilih Machine di panel kiri atau buat Machine baru untuk
                mulai menambahkan Channel.
              </div>
            ) : (
              <>
                <form
                  id="specific-channel-form"
                  className="specific-channel-form"
                  onSubmit={handleChannelSubmit}
                >
                  {editingChannel && (
                    <div className="specific-editing-banner">
                      <div>
                        <span>EDIT MODE ACTIVE</span>
                        <strong>EDITING {editingChannel.channel_number}</strong>
                        <p>
                          Ubah Technology/Profile atau FCN, klik FIND CHANNEL,
                          pilih kandidat, lalu tekan UPDATE CHANNEL.
                        </p>
                      </div>

                      <small>
                        Data saat ini: {editingChannel.input_mode} · FCN{" "}
                        {editingChannel.input_fcn}
                      </small>
                    </div>
                  )}

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
                            ? `Mode edit ${editingChannel?.channel_number ?? "Channel"} tetap aktif. Klik FIND CHANNEL untuk mencari kandidat baru.`
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
                            ? `Mode edit ${editingChannel?.channel_number ?? "Channel"} tetap aktif. Klik FIND CHANNEL untuk memvalidasi FCN baru.`
                            : ""
                        );
                      }}
                      placeholder={`Masukkan ${currentTechnology.fcnLabel}`}
                    />
                  </div>

                  <div className="specific-channel-form-buttons">
                    <button
                      type="button"
                      className="specific-secondary-button find"
                      disabled={busyAction === "lookup"}
                      onClick={() => runChannelLookup()}
                    >
                      {busyAction === "lookup"
                        ? "SEARCHING..."
                        : "FIND CHANNEL"}
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

                    {editingChannelId && (
                      <button
                        type="button"
                        className="specific-secondary-button"
                        onClick={resetChannelForm}
                      >
                        CANCEL
                      </button>
                    )}
                  </div>
                </form>

                {selectedCandidate && (
                  <div className="specific-selected-candidate">
                    <div className="specific-selected-heading">
                      <div>
                        <p className="section-kicker">
                          SELECTED CANDIDATE
                        </p>
                        <h5>
                          {selectedCandidate.band} ·{" "}
                          {selectedCandidate.mode}
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

                <div className="specific-channel-list-heading">
                  <div>
                    <p className="section-kicker">SAVED CHANNELS</p>
                    <h5>Channel slots</h5>
                  </div>
                  <span>{channels.length}</span>
                </div>

                {loadingChannels ? (
                  <div className="specific-channel-empty">
                    Memuat Channel...
                  </div>
                ) : channels.length === 0 ? (
                  <div className="specific-channel-empty">
                    Machine ini belum mempunyai Channel.
                  </div>
                ) : (
                  <div className="specific-saved-channel-grid">
                    {channels.map((channel) => (
                      <article
                        className={`specific-saved-channel-card ${
                          editingChannelId === channel.id ? "editing" : ""
                        }`}
                        key={channel.id}
                      >
                        <header>
                          <div>
                            <span>{channel.channel_number}</span>
                            <strong>{channel.band}</strong>
                          </div>
                          <small>{channel.mode}</small>
                        </header>

                        <div className="specific-saved-channel-details">
                          <div>
                            <span>Technology/Profile</span>
                            <strong>{channel.input_mode}</strong>
                          </div>
                          <div>
                            <span>Input FCN</span>
                            <strong>{channel.input_fcn}</strong>
                          </div>
                          <div>
                            <span>DL frequency</span>
                            <strong>
                              {formatFrequency(channel.freq_dl_mhz)}
                            </strong>
                          </div>
                          <div>
                            <span>UL frequency</span>
                            <strong>
                              {formatFrequency(channel.freq_ul_mhz)}
                            </strong>
                          </div>
                          <div>
                            <span>DL FCN</span>
                            <strong>{formatFcn(channel.fcn_dl)}</strong>
                          </div>
                          <div>
                            <span>UL FCN</span>
                            <strong>{formatFcn(channel.fcn_ul)}</strong>
                          </div>
                        </div>

                        <footer>
                          <span>
                            Updated {formatDateTime(channel.updated_at)}
                          </span>

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
                              disabled={
                                busyAction ===
                                `delete-channel-${channel.id}`
                              }
                              onClick={() => handleDeleteChannel(channel)}
                            >
                              DELETE
                            </button>
                          </div>
                        </footer>
                      </article>
                    ))}
                  </div>
                )}
              </>
            )}
          </section>
        </div>
      </section>

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
            aria-label="Pilih kandidat Channel"
            onClick={(event) => event.stopPropagation()}
          >
            <header>
              <div>
                <p className="section-kicker">MULTIPLE CANDIDATES</p>
                <h4>Pilih kandidat Channel</h4>
                <span>
                  {channelForm.input_mode} · {currentTechnology.fcnLabel}{" "}
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
