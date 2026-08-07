export function shouldAcceptSpectrumSnapshot(snapshot, activeScanMeta) {
  if (!snapshot || snapshot.protocol_version !== 1 || snapshot.message_type !== "spectrum_snapshot") {
    return false;
  }

  const activeSessionId = activeScanMeta?.id;
  const request = activeScanMeta?.request ?? {};
  if (!activeSessionId || snapshot.session_id !== activeSessionId) return false;
  if (request.scan_owner && snapshot.scan_owner !== request.scan_owner) return false;

  if (request.scan_owner === "specific" && request.selected_machine_id !== null && request.selected_machine_id !== undefined) {
    return Number(snapshot.selected_machine_id) === Number(request.selected_machine_id);
  }

  return true;
}

export function createSpectrumStreamUrl(apiBaseUrl) {
  const browserOrigin = typeof window === "undefined" ? null : window.location.origin;
  const url = new URL(apiBaseUrl || browserOrigin);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.pathname = "/api/spectrum/stream";
  url.search = "";
  return url.toString();
}

export function shouldUseSpectrumRestFallback(webSocketEnabled, webSocketHealthy) {
  return !webSocketEnabled || !webSocketHealthy;
}

export function isCurrentSpectrumConnectionGeneration(currentGeneration, callbackGeneration) {
  return currentGeneration === callbackGeneration;
}
