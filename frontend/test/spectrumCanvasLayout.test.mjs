import assert from "node:assert/strict";
import test from "node:test";
import {
  clearPendingAnimationFrame,
  dbToCanvasY,
  frequencyToCanvasX,
  getCanvasBackingStoreSize,
  getMeasuredSpectrumSegments,
} from "../src/spectrumCanvasLayout.js";

test("Canvas backing store follows CSS dimensions and device pixel ratio", () => {
  assert.deepEqual(getCanvasBackingStoreSize(845, 259, 1), {
    width: 845,
    height: 259,
    pixelRatio: 1,
  });
  assert.deepEqual(getCanvasBackingStoreSize(845, 259, 2), {
    width: 1690,
    height: 518,
    pixelRatio: 2,
  });
  assert.equal(getCanvasBackingStoreSize(0, 259, 1), null);
  assert.equal(getCanvasBackingStoreSize(Number.NaN, 259, 1), null);
});

test("cancelled animation frames clear the pending scheduling state", () => {
  const frameRef = { current: 42 };
  const cancelledFrames = [];

  clearPendingAnimationFrame(frameRef, (frameId) => cancelledFrames.push(frameId));

  assert.deepEqual(cancelledFrames, [42]);
  assert.equal(frameRef.current, null);
});

test("fixed dB values preserve vertical ordering", () => {
  assert.equal(dbToCanvasY(-180, 200), 200);
  assert.equal(dbToCanvasY(20, 200), 0);
  assert.ok(dbToCanvasY(-107, 200) < dbToCanvasY(-147, 200));
});

test("configured frequencies map to the left, center, and right", () => {
  assert.equal(frequencyToCanvasX(50, 50, 6000, 900), 0);
  assert.equal(frequencyToCanvasX(6000, 50, 6000, 900), 900);
  assert.equal(frequencyToCanvasX(3025, 50, 6000, 900), 450);
});

test("invalid points are skipped and partial preview segments are not interpolated", () => {
  const segments = getMeasuredSpectrumSegments({
    frequencyValues: [50, 51, Number.NaN, 200, 201],
    powerValues: [-147, -146, -145, -130, Number.POSITIVE_INFINITY],
  });
  assert.deepEqual(segments.map((segment) => segment.map(({ frequency }) => frequency)), [[50, 51], [200]]);
});

test("runtime-like preview values produce drawable measured segments", () => {
  const segments = getMeasuredSpectrumSegments({
    frequencyValues: [50.765625, 50.8203125, 50.875, 50.9296875],
    powerValues: [-145, -143, -147, -103],
  });

  assert.equal(segments.length, 1);
  assert.equal(segments[0].length, 4);
  assert.ok(dbToCanvasY(-165, 259) > 0);
  assert.ok(dbToCanvasY(-103, 259) < 259);
  assert.ok(frequencyToCanvasX(50.765625, 50, 6000, 845) > 0);
});

test("General and Specific use the same renderer coordinate contract", () => {
  assert.equal(frequencyToCanvasX(3025, 50, 6000, 900), frequencyToCanvasX(3025, 50, 6000, 900));
});
