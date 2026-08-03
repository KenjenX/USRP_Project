import assert from "node:assert/strict";
import test from "node:test";
import {
  CHART_MAX_DB,
  CHART_MIN_DB,
  FIXED_CHART_SCALE,
  createFixedChartDbTicks,
  dbToChartPercent,
} from "../src/spectrumChartScale.js";

test("fixed chart bounds map to the top and bottom", () => {
  assert.equal(CHART_MIN_DB, -180);
  assert.equal(CHART_MAX_DB, 20);
  assert.equal(dbToChartPercent(-180), 100);
  assert.equal(dbToChartPercent(20), 0);
});

test("reference-power and threshold values map inside the fixed chart", () => {
  assert.ok(dbToChartPercent(-100) > 0 && dbToChartPercent(-100) < 100);
  assert.ok(dbToChartPercent(-147) < 100);
  assert.ok(dbToChartPercent(-107) < dbToChartPercent(-147));
  assert.ok(dbToChartPercent(0) > 0 && dbToChartPercent(0) < 100);
  assert.ok(dbToChartPercent(-125) > 0 && dbToChartPercent(-125) < 100);
});

test("values outside the fixed chart clamp to visible edges", () => {
  assert.equal(dbToChartPercent(-181), 100);
  assert.equal(dbToChartPercent(21), 0);
});

test("General and Specific consume the same fixed range and ticks", () => {
  const generalScale = FIXED_CHART_SCALE;
  const specificScale = FIXED_CHART_SCALE;
  const ticks = createFixedChartDbTicks();

  assert.equal(generalScale, specificScale);
  assert.equal(ticks[0].value, 20);
  assert.equal(ticks.at(-1).value, -180);
  assert.ok(ticks.every(({ position }) => position >= 0 && position <= 100));
});
