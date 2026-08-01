import assert from "node:assert/strict";
import test from "node:test";
import {
  createEmptySpectrumPreview,
  normalizeSpectrumPreview,
  replaceSpectrumPreview,
} from "../src/generalSpectrumPreview.js";

const fiveWindowPreview = {
  // Represents backend preview entries for windows 1 through 5, while the
  // frontend happens to poll only after windows 1, 3, and 5.
  frequency_mhz: [50, 106, 162, 218, 274],
  power_db: [-70, -71, -72, -73, -74],
};

test("cumulative preview covers all committed windows despite skipped latest snapshots", () => {
  const snapshots = [
    { windowIndex: 1, preview: { frequency_mhz: [50], power_db: [-70] } },
    { windowIndex: 3, preview: { frequency_mhz: [50, 106, 162], power_db: [-70, -71, -72] } },
    { windowIndex: 5, preview: fiveWindowPreview },
  ];
  let graph = null;

  for (const snapshot of snapshots) {
    graph = replaceSpectrumPreview({
      activeSessionId: "session-1",
      responseSessionId: "session-1",
      preview: snapshot.preview,
    });
  }

  assert.deepEqual(graph.frequency_mhz, [50, 106, 162, 218, 274]);
  assert.equal(graph.frequency_mhz.length, 5);
});

test("General and Specific accept the same valid session preview", () => {
  for (const owner of ["general", "specific"]) {
    const preview = replaceSpectrumPreview({
      activeSessionId: `${owner}-session`,
      responseSessionId: `${owner}-session`,
      preview: { frequency_mhz: [50, 106], power_db: [-80, -75] },
    });
    assert.deepEqual(preview.frequency_mhz, [50, 106]);
  }
});

test("duplicate polling and duplicate preview frequencies do not duplicate graph points", () => {
  const preview = {
    frequency_mhz: [106, 50, 106, 162],
    power_db: [-71, -70, -71, -72],
  };
  const first = replaceSpectrumPreview({
    activeSessionId: "session-1", responseSessionId: "session-1", preview,
  });
  const repeat = replaceSpectrumPreview({
    activeSessionId: "session-1", responseSessionId: "session-1", preview,
  });

  assert.deepEqual(first, repeat);
  assert.deepEqual(first.frequency_mhz, [50, 106, 162]);
});

test("a new or stale session cannot populate the active session graph", () => {
  const newSession = createEmptySpectrumPreview("session-2");
  assert.deepEqual(newSession.frequency_mhz, []);
  assert.deepEqual(newSession.power_db, []);

  assert.equal(replaceSpectrumPreview({
    activeSessionId: "session-2",
    responseSessionId: "session-1",
    preview: fiveWindowPreview,
  }), null);
});

test("starting either owner with a new session clears the previous preview", () => {
  for (const sessionId of ["specific-next", "general-next"]) {
    const fresh = createEmptySpectrumPreview(sessionId);
    assert.equal(fresh.sessionId, sessionId);
    assert.deepEqual(fresh.frequency_mhz, []);
    assert.deepEqual(fresh.power_db, []);
  }
});

test("empty and partial previews stay truthful", () => {
  assert.equal(replaceSpectrumPreview({
    activeSessionId: "first-cycle",
    responseSessionId: "first-cycle",
    preview: { frequency_mhz: [], power_db: [] },
  }), null);

  const partial = replaceSpectrumPreview({
    activeSessionId: "first-cycle",
    responseSessionId: "first-cycle",
    preview: { frequency_mhz: [50, 106], power_db: [-80, -75] },
  });
  assert.deepEqual(partial.frequency_mhz, [50, 106]);
  assert.equal(partial.frequency_mhz.length, 2);
});

test("preview normalization sorts finite pairs without fabricating points", () => {
  const normalized = normalizeSpectrumPreview({
    frequency_mhz: [162, NaN, 50, 106, Infinity],
    power_db: [-72, -73, -70, -71, -74],
  });
  assert.deepEqual(normalized.frequency_mhz, [50, 106, 162]);
  assert.deepEqual(normalized.power_db, [-70, -71, -72]);
});

test("the final completed response and a single-window preview remain drawable", () => {
  const completed = replaceSpectrumPreview({
    activeSessionId: "single-window",
    responseSessionId: "single-window",
    preview: { frequency_mhz: [50, 106], power_db: [-80, -75] },
  });

  assert.deepEqual(completed.frequency_mhz, [50, 106]);
  assert.equal(normalizeSpectrumPreview(completed).point_count, 2);
});

test("a rolling cycle replaces the same-session preview without clearing the graph", () => {
  const cycleOne = replaceSpectrumPreview({
    activeSessionId: "rolling", responseSessionId: "rolling",
    preview: { frequency_mhz: [50, 106], power_db: [-80, -70] },
  });
  const cycleTwo = replaceSpectrumPreview({
    activeSessionId: "rolling", responseSessionId: "rolling",
    preview: { frequency_mhz: [50, 106], power_db: [-75, -65] },
  });

  assert.equal(cycleOne.frequency_mhz.length, 2);
  assert.deepEqual(cycleTwo.power_db, [-75, -65]);
});
