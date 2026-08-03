export const CHART_MIN_DB = -180;
export const CHART_MAX_DB = 20;

export const FIXED_CHART_SCALE = Object.freeze({
  minDb: CHART_MIN_DB,
  maxDb: CHART_MAX_DB,
});

function clamp(value, minimum, maximum) {
  return Math.min(Math.max(value, minimum), maximum);
}

export function dbToChartPercent(value) {
  const db = Number(value);
  const safeDb = Number.isFinite(db) ? db : CHART_MAX_DB;

  return clamp(
    ((CHART_MAX_DB - safeDb) / (CHART_MAX_DB - CHART_MIN_DB)) * 100,
    0,
    100
  );
}

export function createFixedChartDbTicks() {
  return Array.from({ length: 11 }, (_, index) => {
    const value = CHART_MAX_DB - index * 20;

    return {
      value,
      position: dbToChartPercent(value),
      isThreshold: false,
    };
  });
}
