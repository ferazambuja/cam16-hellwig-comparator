/**
 * Dependency-free CAM16 and Hellwig--Fairchild 2022 forward models.
 *
 * This module is the browser-facing counterpart to cam16_compare.py. It keeps
 * the same equations, viewing-condition contract, correlate names, and hue
 * diagnostic, while deliberately omitting the Python command-line and CSV
 * surfaces.
 *
 * SPDX-License-Identifier: MIT
 */

export const BROWSER_API_VERSION = "cam16-browser-api-v1";
export const IMPLEMENTATION_VERSION = "1.2.1";
export const INTERPRETATION_LIMIT =
  "Model output only; not measurement or observer validation";
// Cross-runtime reporting boundary for cancellation-sensitive opponent
// responses. It is not an observer-derived or perceptual threshold.
export const OPPONENT_NOISE_RATIO = 1.0e-8;

const M16 = Object.freeze([
  Object.freeze([0.401288, 0.650173, -0.051461]),
  Object.freeze([-0.250268, 1.204414, 0.045854]),
  Object.freeze([-0.002079, 0.048952, 0.953127]),
]);

export class ModelDomainError extends RangeError {
  constructor(message) {
    super(message);
    this.name = "ModelDomainError";
  }
}

export class Surround {
  constructor(F, c, N_c, name = "custom") {
    this.F = F;
    this.c = c;
    this.N_c = N_c;
    this.name = name;
    Object.freeze(this);
  }
}

export const SURROUNDS = Object.freeze({
  average: new Surround(1.0, 0.69, 1.0, "average"),
  dim: new Surround(0.9, 0.59, 0.9, "dim"),
  dark: new Surround(0.8, 0.525, 0.8, "dark"),
});

function pythonFloatRepr(value) {
  if (Number.isInteger(value)) {
    return `${value}.0`;
  }
  return String(value).replace(/e([+-]?)(\d+)$/i, (_match, sign, digits) => {
    const resolvedSign = sign || "+";
    return `e${resolvedSign}${digits.padStart(2, "0")}`;
  });
}

function vectorRepr(vector) {
  return `(${vector.map(pythonFloatRepr).join(", ")})`;
}

function surroundRepr(surround) {
  return (
    `Surround(F=${pythonFloatRepr(surround.F)}, ` +
    `c=${pythonFloatRepr(surround.c)}, ` +
    `N_c=${pythonFloatRepr(surround.N_c)}, name='${surround.name}')`
  );
}

function vector(values, label) {
  if (!Array.isArray(values) || values.length !== 3) {
    throw new TypeError(`${label} must contain exactly three values`);
  }
  const result = values.map((value) => {
    if (typeof value !== "number") {
      throw new TypeError(`${label} must contain numbers`);
    }
    return value;
  });
  if (!result.every(Number.isFinite)) {
    throw new TypeError(
      `${label} must contain only finite values; got ${vectorRepr(result)}`,
    );
  }
  return result;
}

function requireFinite(values, label) {
  if (!values.every((value) => typeof value === "number" && Number.isFinite(value))) {
    throw new TypeError(`${label} must contain only finite numeric values`);
  }
}

function resolveSurround(surround) {
  if (typeof surround === "string") {
    const preset = SURROUNDS[surround];
    if (!preset) {
      throw new TypeError("surround must be 'average', 'dim', 'dark', or a Surround");
    }
    return preset;
  }
  if (
    surround === null ||
    typeof surround !== "object" ||
    !("F" in surround) ||
    !("c" in surround) ||
    !("N_c" in surround)
  ) {
    throw new TypeError("surround must be 'average', 'dim', 'dark', or a Surround");
  }
  return new Surround(
    surround.F,
    surround.c,
    surround.N_c,
    typeof surround.name === "string" ? surround.name : "custom",
  );
}

export function normalizeToDomain100({ XYZ, XYZ_w, Y_b }) {
  const stimulus = vector(XYZ, "XYZ");
  const white = vector(XYZ_w, "XYZ_w");
  requireFinite([Y_b], "Y_b");
  if (white[1] <= 0.0) {
    throw new RangeError(`XYZ_w must have positive Y; got ${pythonFloatRepr(white[1])}`);
  }
  if (Y_b <= 0.0) {
    throw new RangeError(`Y_b must be positive; got ${pythonFloatRepr(Y_b)}`);
  }
  const scale = 100.0 / white[1];
  return {
    XYZ: stimulus.map((value) => value * scale),
    XYZ_w: white.map((value) => value * scale),
    Y_b: Y_b * scale,
  };
}

export function degreeOfAdaptation(
  L_A,
  surround = SURROUNDS.average,
  override = null,
) {
  const resolvedSurround = resolveSurround(surround);
  requireFinite([L_A, resolvedSurround.F], "adaptation inputs");
  if (L_A <= 0.0) {
    throw new RangeError(`L_A must be positive; got ${pythonFloatRepr(L_A)}`);
  }
  if (resolvedSurround.F <= 0.0) {
    throw new RangeError(
      `surround F must be positive; got ${pythonFloatRepr(resolvedSurround.F)}`,
    );
  }
  if (override !== null && override !== undefined) {
    requireFinite([override], "degree of adaptation");
    if (override < 0.0 || override > 1.0) {
      throw new RangeError(
        `degree of adaptation must lie in [0, 1]; got ${pythonFloatRepr(override)}`,
      );
    }
    return override;
  }
  const value =
    resolvedSurround.F *
    (1.0 - (1.0 / 3.6) * Math.exp((-L_A - 42.0) / 92.0));
  return Math.min(1.0, Math.max(0.0, value));
}

function validateInputs(XYZ, XYZ_w, L_A, Y_b, surround, allow_negative_xyz) {
  requireFinite(
    [L_A, Y_b, surround.F, surround.c, surround.N_c],
    "viewing-condition inputs",
  );
  if (XYZ_w.some((value) => value <= 0.0)) {
    throw new RangeError(
      `XYZ_w components must be positive; got ${vectorRepr(XYZ_w)}`,
    );
  }
  if (Math.abs(XYZ_w[1] - 100.0) > 1.0e-9) {
    throw new RangeError(
      "XYZ_w must use CAM16 Domain-100 (Y_w = 100); pass " +
        "normalize=true to scale the inputs explicitly. Got " +
        `Y_w=${pythonFloatRepr(XYZ_w[1])}`,
    );
  }
  if (L_A <= 0.0) {
    throw new RangeError(`L_A must be positive; got ${pythonFloatRepr(L_A)}`);
  }
  if (!(Y_b > 0.0 && Y_b <= XYZ_w[1])) {
    throw new RangeError(`Y_b must lie in (0, Y_w]; got ${pythonFloatRepr(Y_b)}`);
  }
  if (surround.F <= 0.0 || surround.c <= 0.0 || surround.N_c <= 0.0) {
    throw new RangeError(
      `surround parameters must be positive; got ${surroundRepr(surround)}`,
    );
  }
  if (!allow_negative_xyz && XYZ.some((value) => value < 0.0)) {
    throw new RangeError(
      "XYZ contains a negative component. This is refused by default because " +
        "difference/residual triples are not physical colours; pass " +
        "allow_negative_xyz=true only for deliberate numerical exploration. " +
        `Got ${vectorRepr(XYZ)}`,
    );
  }
  if (XYZ.every((value) => value === 0.0)) {
    throw new ModelDomainError(
      "all-zero XYZ has undefined chromatic correlates; no hue or " +
        "saturation is reported",
    );
  }
}

function transform(matrix, values) {
  return matrix.map((row) => {
    let total = 0.0;
    for (let index = 0; index < 3; index += 1) {
      total += row[index] * values[index];
    }
    return total;
  });
}

function postAdaptation(value, F_L) {
  const scaled = (F_L * Math.abs(value) / 100.0) ** 0.42;
  const magnitude = 400.0 * scaled / (scaled + 27.13);
  return (value < 0.0 || Object.is(value, -0.0) ? -magnitude : magnitude) + 0.1;
}

function sharedState(options) {
  let stimulus = vector(options.XYZ, "XYZ");
  let white = vector(options.XYZ_w, "XYZ_w");
  const L_A = options.L_A;
  let background = options.Y_b;
  const surround = resolveSurround(options.surround ?? SURROUNDS.average);
  const normalize = options.normalize ?? false;
  const allow_negative_xyz = options.allow_negative_xyz ?? false;

  if (typeof normalize !== "boolean" || typeof allow_negative_xyz !== "boolean") {
    throw new TypeError("normalize and allow_negative_xyz must be boolean");
  }
  requireFinite([L_A, background], "viewing-condition inputs");
  if (normalize) {
    ({ XYZ: stimulus, XYZ_w: white, Y_b: background } = normalizeToDomain100({
      XYZ: stimulus,
      XYZ_w: white,
      Y_b: background,
    }));
  }
  validateInputs(
    stimulus,
    white,
    L_A,
    background,
    surround,
    allow_negative_xyz,
  );

  const Y_w = white[1];
  const n = background / Y_w;
  if (!Number.isFinite(n) || n <= 0.0) {
    throw new ModelDomainError(
      "relative background Y_b/Y_w is outside the supported numerical " +
        `domain; got ${pythonFloatRepr(n)} from ` +
        `Y_b=${pythonFloatRepr(background)} and Y_w=${pythonFloatRepr(Y_w)}`,
    );
  }
  const z = 1.48 + Math.sqrt(n);
  const N_bb = 0.725 * (1.0 / n) ** 0.2;
  if (!Number.isFinite(N_bb)) {
    throw new ModelDomainError(
      "background induction factor is outside the supported numerical " +
        `domain for Y_b/Y_w=${pythonFloatRepr(n)}`,
    );
  }
  const k = 1.0 / (5.0 * L_A + 1.0);
  const F_L =
    0.2 * k ** 4 * (5.0 * L_A) +
    0.1 * (1.0 - k ** 4) ** 2 * (5.0 * L_A) ** (1.0 / 3.0);

  const RGB = transform(M16, stimulus);
  const RGB_w = transform(M16, white);
  if (RGB_w.some((value) => !Number.isFinite(value) || value <= 0.0)) {
    throw new ModelDomainError(
      "XYZ_w produces a non-positive CAT16 cone response; got " +
        vectorRepr(RGB_w),
    );
  }
  const D = degreeOfAdaptation(
    L_A,
    surround,
    options.degree_of_adaptation_override ?? null,
  );
  const D_RGB = RGB_w.map((value) => D * Y_w / value + 1.0 - D);
  const RGB_a = RGB.map((value, index) => postAdaptation(D_RGB[index] * value, F_L));
  const RGB_aw = RGB_w.map((value, index) =>
    postAdaptation(D_RGB[index] * value, F_L),
  );

  const a = RGB_a[0] - 12.0 * RGB_a[1] / 11.0 + RGB_a[2] / 11.0;
  const b = (RGB_a[0] + RGB_a[1] - 2.0 * RGB_a[2]) / 9.0;
  const h = ((Math.atan2(b, a) * 180.0 / Math.PI) % 360.0 + 360.0) % 360.0;
  const A = 2.0 * RGB_a[0] + RGB_a[1] + RGB_a[2] / 20.0 - 0.305;
  const A_w = 2.0 * RGB_aw[0] + RGB_aw[1] + RGB_aw[2] / 20.0 - 0.305;
  if (!Number.isFinite(A_w) || A_w <= 0.0) {
    throw new ModelDomainError(
      "XYZ_w produces a non-positive achromatic white response; got " +
        pythonFloatRepr(A_w),
    );
  }
  if (!Number.isFinite(A) || A <= 0.0) {
    throw new ModelDomainError(
      "lightness is undefined: the stimulus achromatic response is " +
        `${pythonFloatRepr(A)}, outside the supported real-valued domain`,
    );
  }
  return { a, b, h, A, A_w, RGB_a, F_L, n, z, N_bb, D, surround };
}

function checkedCorrelates(model, correlates) {
  const invalid = Object.entries(correlates).filter(([, value]) => !Number.isFinite(value));
  if (invalid.length > 0) {
    const rendered = invalid
      .map(([name, value]) => `'${name}': ${pythonFloatRepr(value)}`)
      .join(", ");
    throw new ModelDomainError(
      `${model} produced non-finite correlates {${rendered}}; the declared ` +
        "inputs are outside the supported numerical domain",
    );
  }
  return correlates;
}

function cam16FromState(state) {
  const A = state.A * state.N_bb;
  const A_w = state.A_w * state.N_bb;
  const J = 100.0 * (A / A_w) ** (state.surround.c * state.z);
  const Q =
    (4.0 / state.surround.c) *
    Math.sqrt(J / 100.0) *
    (A_w + 4.0) *
    state.F_L ** 0.25;
  const chromaDenominator =
    state.RGB_a[0] + state.RGB_a[1] + 21.0 * state.RGB_a[2] / 20.0;
  if (!Number.isFinite(chromaDenominator) || chromaDenominator <= 0.0) {
    throw new ModelDomainError(
      "CAM16 chroma is undefined: the adapted-response denominator is " +
        `${pythonFloatRepr(chromaDenominator)}, outside the supported real-valued domain`,
    );
  }
  const hRad = state.h * Math.PI / 180.0;
  const e_t = 0.25 * (Math.cos(hRad + 2.0) + 3.8);
  const t =
    50000.0 / 13.0 *
    state.surround.N_c *
    state.N_bb *
    e_t *
    Math.hypot(state.a, state.b) /
    chromaDenominator;
  const C =
    t ** 0.9 *
    Math.sqrt(J / 100.0) *
    (1.64 - 0.29 ** state.n) ** 0.73;
  const M = C * state.F_L ** 0.25;
  const s = 100.0 * Math.sqrt(M / Q);
  return checkedCorrelates("CAM16", { J, Q, C, M, s, h: state.h });
}

function hellwig2022FromState(state) {
  const J = 100.0 * (state.A / state.A_w) ** (state.surround.c * state.z);
  const Q = (2.0 / state.surround.c) * (J / 100.0) * state.A_w;
  const hRad = state.h * Math.PI / 180.0;
  const e_t =
    -0.0582 * Math.cos(hRad) -
    0.0258 * Math.cos(2.0 * hRad) -
    0.1347 * Math.cos(3.0 * hRad) +
    0.0289 * Math.cos(4.0 * hRad) -
    0.1475 * Math.sin(hRad) -
    0.0308 * Math.sin(2.0 * hRad) +
    0.0385 * Math.sin(3.0 * hRad) +
    0.0096 * Math.sin(4.0 * hRad) +
    1.0;
  const M = 43.0 * state.surround.N_c * e_t * Math.hypot(state.a, state.b);
  const C = 35.0 * M / state.A_w;
  const s = 100.0 * M / Q;
  return checkedCorrelates("Hellwig--Fairchild 2022", {
    J,
    Q,
    C,
    M,
    s,
    h: state.h,
  });
}

function hueDiagnostics(state) {
  const magnitude = Math.hypot(state.a, state.b);
  const scale = Math.max(...state.RGB_a.map(Math.abs));
  const ratio = scale > 0.0 ? magnitude / scale : 0.0;
  return {
    opponent_magnitude: magnitude,
    opponent_magnitude_ratio: ratio,
    hue_resolved: ratio > OPPONENT_NOISE_RATIO,
  };
}

function validateOptions(options) {
  if (options === null || typeof options !== "object" || Array.isArray(options)) {
    throw new TypeError("compareModels expects an options object");
  }
  for (const required of ["XYZ", "XYZ_w", "L_A", "Y_b"]) {
    if (!(required in options)) {
      throw new TypeError(`missing required option: ${required}`);
    }
  }
}

export function compareModelsWithDiagnostics(options) {
  validateOptions(options);
  const model = options.model ?? "both";
  if (!new Set(["cam16", "hellwig2022", "both"]).has(model)) {
    throw new TypeError("model must be 'cam16', 'hellwig2022', or 'both'");
  }
  const state = sharedState(options);
  const models = {};
  if (model === "cam16" || model === "both") {
    models.cam16 = cam16FromState(state);
  }
  if (model === "hellwig2022" || model === "both") {
    models.hellwig2022 = hellwig2022FromState(state);
  }
  return { models, hue_diagnostics: hueDiagnostics(state) };
}

export function compareModels(options) {
  return compareModelsWithDiagnostics(options).models;
}
