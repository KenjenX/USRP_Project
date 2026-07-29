import assert from "node:assert/strict";
import test from "node:test";
import {
  createEmptyGeneralSpectrumPreview,
  normalizeGeneralSpectrumPreview,
  replaceGeneralSpectrumPreview,
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
    graph = replaceGeneralSpectrumPreview({
      activeSessionId: "session-1",
      responseSessionId: "session-1",
      preview: snapshot.preview,
    });
  }

  assert.deepEqual(graph.frequency_mhz, [50, 106, 162, 218, 274]);
  assert.equal(graph.frequency_mhz.length, 5);
});

test("duplicate polling and duplicate preview frequencies do not duplicate graph points", () => {
  const preview = {
    frequency_mhz: [106, 50, 106, 162],
    power_db: [-71, -70, -71, -72],
  };
  const first = replaceGeneralSpectrumPreview({
    activeSessionId: "session-1", responseSessionId: "session-1", preview,
  });
  const repeat = replaceGeneralSpectrumPreview({
    activeSessionId: "session-1", responseSessionId: "session-1", preview,
  });

  assert.deepEqual(first, repeat);
  assert.deepEqual(first.frequency_mhz, [50, 106, 162]);
});

test("a new or stale session cannot populate the active session graph", () => {
  const newSession = createEmptyGeneralSpectrumPreview("session-2");
  assert.deepEqual(newSession.frequency_mhz, []);
  assert.deepEqual(newSession.power_db, []);

  assert.equal(replaceGeneralSpectrumPreview({
    activeSessionId: "session-2",
    responseSessionId: "session-1",
    preview: fiveWindowPreview,
  }), null);
});

test("the final completed response and a single-window preview remain drawable", () => {
  const completed = replaceGeneralSpectrumPreview({
    activeSessionId: "single-window",
    responseSessionId: "single-window",
    preview: { frequency_mhz: [50, 106], power_db: [-80, -75] },
  });

  assert.deepEqual(completed.frequency_mhz, [50, 106]);
  assert.equal(normalizeGeneralSpectrumPreview(completed).point_count, 2);
});

test("a rolling cycle replaces the same-session preview without clearing the graph", () => {
  const cycleOne = replaceGeneralSpectrumPreview({
    activeSessionId: "rolling", responseSessionId: "rolling",
    preview: { frequency_mhz: [50, 106], power_db: [-80, -70] },
  });
  const cycleTwo = replaceGeneralSpectrumPreview({
    activeSessionId: "rolling", responseSessionId: "rolling",
    preview: { frequency_mhz: [50, 106], power_db: [-75, -65] },
  });

  assert.equal(cycleOne.frequency_mhz.length, 2);
  assert.deepEqual(cycleTwo.power_db, [-75, -65]);
});
