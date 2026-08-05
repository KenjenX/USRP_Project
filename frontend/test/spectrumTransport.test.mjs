import assert from "node:assert/strict";
import test from "node:test";
import {
  createSpectrumStreamUrl,
  isCurrentSpectrumConnectionGeneration,
  shouldAcceptSpectrumSnapshot,
  shouldUseSpectrumRestFallback,
} from "../src/spectrumTransport.js";

const general = { id: "general-1", request: { scan_owner: "general", selected_machine_id: null } };
const specific = { id: "specific-1", request: { scan_owner: "specific", selected_machine_id: 7 } };
const snapshot = (overrides = {}) => ({
  protocol_version: 1,
  message_type: "spectrum_snapshot",
  session_id: "general-1",
  scan_owner: "general",
  selected_machine_id: null,
  spectrum_preview: { frequency_mhz: [50], power_db: [-145] },
  channel_measurements: [],
  ...overrides,
});

test("valid General and selected Specific snapshots are accepted", () => {
  assert.equal(shouldAcceptSpectrumSnapshot(snapshot(), general), true);
  assert.equal(shouldAcceptSpectrumSnapshot(snapshot({ session_id: "specific-1", scan_owner: "specific", selected_machine_id: 7 }), specific), true);
});

test("wrong session, owner, and machine snapshots are rejected", () => {
  assert.equal(shouldAcceptSpectrumSnapshot(snapshot({ session_id: "old" }), general), false);
  assert.equal(shouldAcceptSpectrumSnapshot(snapshot({ scan_owner: "specific" }), general), false);
  assert.equal(shouldAcceptSpectrumSnapshot(snapshot({ session_id: "specific-1", scan_owner: "specific", selected_machine_id: 8 }), specific), false);
});

test("stream URL uses WebSocket transport for the configured API base", () => {
  assert.equal(createSpectrumStreamUrl("http://127.0.0.1:8000"), "ws://127.0.0.1:8000/api/spectrum/stream");
});

test("obsolete connection generations and unhealthy sockets use the safe fallback", () => {
  assert.equal(isCurrentSpectrumConnectionGeneration(3, 3), true);
  assert.equal(isCurrentSpectrumConnectionGeneration(4, 3), false);
  assert.equal(shouldUseSpectrumRestFallback(true, true), false);
  assert.equal(shouldUseSpectrumRestFallback(true, false), true);
  assert.equal(shouldUseSpectrumRestFallback(false, true), true);
});
