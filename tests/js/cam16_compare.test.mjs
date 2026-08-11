import assert from "node:assert/strict";
import test from "node:test";

import {
  BROWSER_API_VERSION,
  IMPLEMENTATION_VERSION,
  INTERPRETATION_LIMIT,
  ModelDomainError,
  OPPONENT_NOISE_RATIO,
  SURROUNDS,
  compareModels,
  compareModelsWithDiagnostics,
  degreeOfAdaptation,
  normalizeToDomain100,
} from "../../cam16_compare.mjs";

const DEFAULT_CASE = Object.freeze({
  XYZ: [19.01, 20.0, 21.78],
  XYZ_w: [95.047, 100.0, 108.883],
  L_A: 318.31,
  Y_b: 20.0,
});

function close(actual, expected, tolerance = 1.0e-12) {
  assert.ok(
    Math.abs(actual - expected) <= tolerance * Math.max(1.0, Math.abs(expected)),
    `${actual} differs from ${expected}`,
  );
}

test("exports an explicit browser contract without claiming the CLI schema", () => {
  assert.equal(BROWSER_API_VERSION, "cam16-browser-api-v1");
  assert.equal(IMPLEMENTATION_VERSION, "1.2.1");
  assert.equal(
    INTERPRETATION_LIMIT,
    "Model output only; not measurement or observer validation",
  );
  assert.equal(OPPONENT_NOISE_RATIO, 1.0e-8);
  assert.deepEqual(Object.keys(SURROUNDS), ["average", "dim", "dark"]);
  assert.ok(Object.isFrozen(SURROUNDS));
});

test("matches the published CAM16 worked example and both reference outputs", () => {
  const { models, hue_diagnostics } = compareModelsWithDiagnostics(DEFAULT_CASE);
  close(models.cam16.J, 41.73134111868119);
  close(models.cam16.Q, 195.37201860293985);
  close(models.cam16.C, 0.09587245821175222);
  close(models.cam16.M, 0.09965801217069391);
  close(models.cam16.s, 2.2585251356165843);
  close(models.cam16.h, 218.97548554129165);
  close(models.hellwig2022.J, 41.73134111868119);
  close(models.hellwig2022.Q, 55.85250025870248);
  close(models.hellwig2022.C, 0.02338948054640507);
  close(models.hellwig2022.M, 0.03085687241778727);
  close(models.hellwig2022.s, 0.055247074481646695);
  close(models.hellwig2022.h, 218.97548554129165);
  assert.equal(hue_diagnostics.hue_resolved, true);
});

test("selects either model without renaming correlates", () => {
  const cam16 = compareModels({ ...DEFAULT_CASE, model: "cam16" });
  assert.deepEqual(Object.keys(cam16), ["cam16"]);
  assert.deepEqual(Object.keys(cam16.cam16), ["J", "Q", "C", "M", "s", "h"]);

  const hellwig = compareModels({ ...DEFAULT_CASE, model: "hellwig2022" });
  assert.deepEqual(Object.keys(hellwig), ["hellwig2022"]);
});

test("normalization is explicit and preserves the declared adapting luminance", () => {
  const normalized = normalizeToDomain100({
    XYZ: [9.505, 10.0, 10.8883],
    XYZ_w: [47.5235, 50.0, 54.4415],
    Y_b: 10.0,
  });
  assert.deepEqual(normalized, {
    XYZ: [19.01, 20.0, 21.7766],
    XYZ_w: [95.047, 100.0, 108.883],
    Y_b: 20.0,
  });
  const implicit = compareModels({
    XYZ: [9.505, 10.0, 10.89],
    XYZ_w: [47.5235, 50.0, 54.4415],
    L_A: DEFAULT_CASE.L_A,
    Y_b: 10.0,
    normalize: true,
  });
  const explicit = compareModels({
    XYZ: [19.01, 20.0, 21.78],
    XYZ_w: [95.047, 100.0, 108.883],
    L_A: DEFAULT_CASE.L_A,
    Y_b: 20.0,
  });
  close(implicit.cam16.J, explicit.cam16.J);
  close(implicit.hellwig2022.Q, explicit.hellwig2022.Q);
});

test("supports a declared adaptation override", () => {
  assert.equal(degreeOfAdaptation(20.0, "average", 1.0), 1.0);
  assert.notEqual(
    compareModels({ ...DEFAULT_CASE, degree_of_adaptation_override: 1.0 }).cam16.C,
    compareModels(DEFAULT_CASE).cam16.C,
  );
});

test("marks cancellation residue as an unresolved hue", () => {
  const result = compareModelsWithDiagnostics({
    XYZ: [33.0, 33.0, 33.0],
    XYZ_w: [100.0, 100.0, 100.0],
    L_A: 20.0,
    Y_b: 20.0,
  });
  assert.equal(result.hue_diagnostics.hue_resolved, false);
  assert.ok(result.hue_diagnostics.opponent_magnitude_ratio < OPPONENT_NOISE_RATIO);
});

test("does not overstate hue precision near complete adaptation", () => {
  const nearComplete = compareModelsWithDiagnostics({
    XYZ: [95.047, 100.0, 108.883],
    XYZ_w: [95.047, 100.0, 108.883],
    L_A: 2000.0,
    Y_b: 20.0,
  });
  assert.equal(nearComplete.hue_diagnostics.hue_resolved, false);
  assert.ok(nearComplete.hue_diagnostics.opponent_magnitude_ratio > 1.0e-13);

  const incomplete = compareModelsWithDiagnostics({
    XYZ: [95.047, 100.0, 108.883],
    XYZ_w: [95.047, 100.0, 108.883],
    L_A: 318.31,
    Y_b: 20.0,
  });
  assert.equal(incomplete.hue_diagnostics.hue_resolved, true);
});

test("refuses missing conditions, unsafe negatives, and undefined black", () => {
  assert.throws(() => compareModels({ XYZ: [1, 2, 3] }), /missing required option/);
  assert.throws(
    () => compareModels({ ...DEFAULT_CASE, XYZ: [1, -2, 3] }),
    /negative component/,
  );
  assert.throws(
    () => compareModels({ ...DEFAULT_CASE, XYZ: [0, 0, 0] }),
    (error) =>
      error instanceof ModelDomainError &&
      error.message ===
        "all-zero XYZ has undefined chromatic correlates; no hue or saturation is reported",
  );
});

test("refuses coercion, non-finite values, and undeclared model names", () => {
  assert.throws(
    () => compareModels({ ...DEFAULT_CASE, XYZ: ["19.01", 20, 21.78] }),
    /must contain numbers/,
  );
  assert.throws(
    () => compareModels({ ...DEFAULT_CASE, L_A: Number.POSITIVE_INFINITY }),
    /finite numeric values/,
  );
  assert.throws(
    () => compareModels({ ...DEFAULT_CASE, model: "cam16ucs" }),
    /model must be/,
  );
});

test("extreme finite inputs either produce finite correlates or a bounded refusal", () => {
  const stimulusScales = [1.0e-300, 1.0e-100, 1.0, 1.0e100, 1.0e300];
  const adaptingLuminances = [1.0e-300, 1.0e-100, 1.0, 20.0, 1.0e100, 1.0e300];
  const backgrounds = [5.0e-324, 1.0e-320, 1.0e-100, 20.0, 100.0];
  let evaluated = 0;
  let refused = 0;

  for (const scale of stimulusScales) {
    for (const L_A of adaptingLuminances) {
      for (const Y_b of backgrounds) {
        for (const surround of Object.keys(SURROUNDS)) {
          const options = {
            XYZ: [0.1901 * scale, 0.2 * scale, 0.2178 * scale],
            XYZ_w: [95.047, 100.0, 108.883],
            L_A,
            Y_b,
            surround,
          };
          try {
            const models = compareModels(options);
            for (const correlates of Object.values(models)) {
              assert.ok(Object.values(correlates).every(Number.isFinite));
            }
            evaluated += 1;
          } catch (error) {
            assert.ok(
              error instanceof ModelDomainError || error instanceof RangeError,
              `unexpected ${error?.name}: ${error?.message}`,
            );
            refused += 1;
          }
        }
      }
    }
  }
  assert.equal(evaluated + refused, 450);
  assert.ok(evaluated > 0);
  assert.ok(refused > 0);
});
