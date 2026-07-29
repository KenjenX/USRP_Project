export function createEmptyGeneralSpectrumPreview(sessionId = null) {
  return {
    sessionId,
    frequency_mhz: [],
    power_db: [],
  };
}

export function normalizeGeneralSpectrumPreview(preview) {
  if (!preview || typeof preview !== "object") {
    return null;
  }

  const frequencyValues = Array.isArray(preview.frequency_mhz)
    ? preview.frequency_mhz.map(Number)
    : [];
  const powerValues = Array.isArray(preview.power_db)
    ? preview.power_db.map(Number)
    : [];
  const pointCount = Math.min(frequencyValues.length, powerValues.length);
  const previewPoints = [];

  for (let index = 0; index < pointCount; index += 1) {
    const frequency = frequencyValues[index];
    const power = powerValues[index];
    if (Number.isFinite(frequency) && Number.isFinite(power)) {
      previewPoints.push({ frequency, power });
    }
  }

  if (previewPoints.length === 0) {
    return null;
  }

  previewPoints.sort((left, right) => left.frequency - right.frequency);
  const seenFrequencies = new Set();
  const frequency_mhz = [];
  const power_db = [];

  for (const point of previewPoints) {
    const key = point.frequency.toPrecision(12);
    if (!seenFrequencies.has(key)) {
      seenFrequencies.add(key);
      frequency_mhz.push(point.frequency);
      power_db.push(point.power);
    }
  }

  return {
    ...preview,
    frequency_mhz,
    power_db,
    point_count: frequency_mhz.length,
  };
}

export function replaceGeneralSpectrumPreview({
  activeSessionId,
  responseSessionId,
  preview,
}) {
  if (
    !activeSessionId ||
    !responseSessionId ||
    responseSessionId !== activeSessionId
  ) {
    return null;
  }

  const normalizedPreview = normalizeGeneralSpectrumPreview(preview);
  if (!normalizedPreview) {
    return null;
  }

  return {
    sessionId: responseSessionId,
    frequency_mhz: normalizedPreview.frequency_mhz,
    power_db: normalizedPreview.power_db,
  };
}
