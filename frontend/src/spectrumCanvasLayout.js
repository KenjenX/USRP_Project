import { dbToChartPercent } from "./spectrumChartScale.js";

export function getCanvasBackingStoreSize(cssWidth, cssHeight, devicePixelRatio = 1) {
  const width = Number(cssWidth);
  const height = Number(cssHeight);
  if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) {
    return null;
  }

  const pixelRatio = Number(devicePixelRatio);
  const safePixelRatio = Number.isFinite(pixelRatio) && pixelRatio > 0 ? pixelRatio : 1;
  return {
    width: Math.round(width * safePixelRatio),
    height: Math.round(height * safePixelRatio),
    pixelRatio: safePixelRatio,
  };
}

export function clearPendingAnimationFrame(frameRef, cancelAnimationFrame) {
  if (frameRef.current !== null) cancelAnimationFrame(frameRef.current);
  frameRef.current = null;
}

export function frequencyToCanvasX(value, startFrequencyMHz, endFrequencyMHz, width) {
  const frequency = Number(value);
  const start = Number(startFrequencyMHz);
  const end = Number(endFrequencyMHz);

  if (!Number.isFinite(frequency) || !Number.isFinite(start) || !Number.isFinite(end) || end <= start) {
    return null;
  }

  return ((frequency - start) / (end - start)) * width;
}

export function dbToCanvasY(value, height) {
  return (dbToChartPercent(value) / 100) * height;
}

export function getMeasuredSpectrumSegments({ frequencyValues, powerValues }) {
  const pointCount = Math.min(
    Array.isArray(frequencyValues) ? frequencyValues.length : 0,
    Array.isArray(powerValues) ? powerValues.length : 0
  );
  const points = [];

  for (let index = 0; index < pointCount; index += 1) {
    const frequency = Number(frequencyValues[index]);
    const power = Number(powerValues[index]);
    if (Number.isFinite(frequency) && Number.isFinite(power)) {
      points.push({ frequency, power });
    }
  }

  points.sort((left, right) => left.frequency - right.frequency);
  if (points.length === 0) return [];

  const gaps = points.slice(1)
    .map((point, index) => point.frequency - points[index].frequency)
    .filter((gap) => gap > 0)
    .sort((left, right) => left - right);
  const medianGap = gaps.length > 0 ? gaps[Math.floor((gaps.length - 1) / 2)] : 0;
  const splitGap = medianGap > 0 ? medianGap * 4 : Infinity;
  const segments = [[points[0]]];

  for (let index = 1; index < points.length; index += 1) {
    const point = points[index];
    if (point.frequency - points[index - 1].frequency > splitGap) {
      segments.push([point]);
    } else {
      segments.at(-1).push(point);
    }
  }

  return segments;
}
