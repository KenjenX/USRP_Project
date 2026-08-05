import { useEffect, useRef } from "react";
import {
  createSpectrumStreamUrl,
  isCurrentSpectrumConnectionGeneration,
  shouldAcceptSpectrumSnapshot,
} from "./spectrumTransport.js";

const RECONNECT_DELAYS_MS = [250, 500, 1000, 2000, 4000];

function logStreamDiagnostic(event, generation, detail = "") {
  if (import.meta.env.DEV) {
    console.debug(`[spectrum-stream] ${event} generation=${generation}`, detail);
  }
}

export default function useSpectrumStream({ enabled, apiBaseUrl, activeScanMetaRef, onSnapshot, onHealthChange, onRejected }) {
  const callbackRef = useRef({ onSnapshot, onHealthChange, onRejected });
  callbackRef.current = { onSnapshot, onHealthChange, onRejected };
  const generationRef = useRef(0);

  useEffect(() => {
    if (!enabled) {
      callbackRef.current.onHealthChange(false);
      return undefined;
    }

    const generation = generationRef.current + 1;
    generationRef.current = generation;
    let socket = null;
    let reconnectTimer = null;
    let attempt = 0;
    let disposed = false;

    const isCurrent = () => !disposed && isCurrentSpectrumConnectionGeneration(
      generationRef.current,
      generation
    );
    const connect = () => {
      if (!isCurrent()) return;
      socket = new WebSocket(createSpectrumStreamUrl(apiBaseUrl));
      socket.onopen = () => {
        if (!isCurrent()) return;
        attempt = 0;
        logStreamDiagnostic("open", generation);
        callbackRef.current.onHealthChange(true);
      };
      socket.onmessage = (event) => {
        if (!isCurrent()) return;
        try {
          const snapshot = JSON.parse(event.data);
          logStreamDiagnostic("message", generation, snapshot.session_id ?? "no-session");
          if (shouldAcceptSpectrumSnapshot(snapshot, activeScanMetaRef.current)) {
            callbackRef.current.onSnapshot(snapshot);
          } else {
            callbackRef.current.onRejected();
          }
        } catch {
          callbackRef.current.onRejected();
        }
      };
      socket.onerror = () => {
        logStreamDiagnostic("error", generation);
        socket?.close();
      };
      socket.onclose = (event) => {
        if (!isCurrent()) return;
        logStreamDiagnostic("close", generation, `${event.code} ${event.reason || ""}`.trim());
        callbackRef.current.onHealthChange(false);
        const delay = RECONNECT_DELAYS_MS[Math.min(attempt, RECONNECT_DELAYS_MS.length - 1)];
        attempt += 1;
        reconnectTimer = window.setTimeout(connect, delay);
      };
    };

    connect();
    return () => {
      disposed = true;
      generationRef.current += 1;
      window.clearTimeout(reconnectTimer);
      if (socket) socket.close();
    };
  }, [activeScanMetaRef, apiBaseUrl, enabled]);
}
