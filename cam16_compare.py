#!/usr/bin/env python3
"""Convert XYZ to CAM16 and Hellwig--Fairchild 2022 correlates.

The module is both an importable, standard-library-only reference and a small
command-line tool.  It evaluates the forward appearance models for arbitrary
XYZ samples under caller-supplied viewing conditions; it does not infer those
conditions from a particular data source.

The Hellwig--Fairchild equations are a proposed 2022 revision, not a renamed
CAM16 or an adopted replacement.  Results from the two models are therefore
labelled separately.  This module intentionally does not map either result to
CAM16-UCS.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
import sys
import textwrap
from typing import IO, Sequence


Vector = tuple[float, float, float]

# CAT16 cone-response matrix from Li et al. (2017).
M16: tuple[Vector, Vector, Vector] = (
    (0.401288, 0.650173, -0.051461),
    (-0.250268, 1.204414, 0.045854),
    (-0.002079, 0.048952, 0.953127),
)

CORRELATES = ("J", "Q", "C", "M", "s", "h")

# Machine-readable output carries this warning so model calculations are not
# mistaken for instrument measurements or observer results.
INTERPRETATION_LIMIT = "Model output only; not measurement or observer validation"

# Stable identifiers for serialized output. Schema changes describe the shape
# of the record; implementation-version changes describe this tool's behavior.
SCHEMA = "cam16-hellwig-compare-v2"
IMPLEMENTATION_VERSION = "1.2.1"


class ModelDomainError(ValueError):
    """An input left the real-valued domain required by the model."""


#: Flags whose absence is the newcomer's first encounter with this tool.
_VIEWING_CONDITION_FLAGS = ("--white", "--la", "--yb")

_MISSING_CONDITION_GUIDANCE = """
These describe the viewing condition and have no safe default. A correlate
calculated under the wrong condition still looks entirely plausible, which is
why this tool will not guess one.

A worked starting point, a D65-like white viewed against a 20 percent
background:

  --white 95.05 100 108.88 --la 318.31 --yb 20

Run --help for what each one means and how to choose values for your own setup.
"""


class _ArgumentParser(argparse.ArgumentParser):
    """An argument parser whose refusals say where to go next.

    Declining to invent a viewing condition is the point of this tool, but the
    stock message reports only that three flags are missing. Someone who has
    not met an adapting-field luminance before has nowhere to go from there,
    and the epilog that would explain it is printed for ``--help`` and never
    for an error. The guidance is attached here so the first thing a new user
    sees leads somewhere, and only for that error, because a worked viewing
    condition is noise when the mistake was something else.
    """

    def error(self, message: str):  # type: ignore[override]
        self.print_usage(sys.stderr)
        sys.stderr.write(f"{self.prog}: error: {message}\n")
        required_prefix = "the following arguments are required:"
        missing = (
            {item.strip() for item in message[len(required_prefix) :].split(",")}
            if message.startswith(required_prefix)
            else set()
        )
        if missing.intersection(_VIEWING_CONDITION_FLAGS):
            sys.stderr.write(_MISSING_CONDITION_GUIDANCE)
        raise SystemExit(2)


@dataclass(frozen=True)
class Surround:
    """Surround induction factors used by CAM16 and the 2022 revision."""

    F: float
    c: float
    N_c: float
    name: str = "custom"


AVERAGE = Surround(F=1.0, c=0.69, N_c=1.0, name="average")
DIM = Surround(F=0.9, c=0.59, N_c=0.9, name="dim")
DARK = Surround(F=0.8, c=0.525, N_c=0.8, name="dark")
SURROUNDS = {item.name: item for item in (AVERAGE, DIM, DARK)}


def _vector(values: Sequence[float | str], label: str) -> Vector:
    """Parse and check a tristimulus triple, from numbers or CSV text."""

    if len(values) != 3:
        raise ValueError(f"{label} must contain exactly three values")
    first, second, third = (float(value) for value in values)
    vector = (first, second, third)
    if not all(math.isfinite(value) for value in vector):
        raise ValueError(f"{label} must contain only finite values; got {vector}")
    return vector


def _require_finite(values: Sequence[float], label: str) -> None:
    if not all(math.isfinite(value) for value in values):
        raise ValueError(f"{label} must contain only finite values; got {values}")


def normalize_to_domain100(
    XYZ: Sequence[float], XYZ_w: Sequence[float], Y_b: float
) -> tuple[Vector, Vector, float]:
    """Scale a stimulus, adopted white, and background together to ``Y_w=100``.

    This is useful when all three relative quantities arrive on an absolute or
    otherwise non-100 scale.  ``L_A`` is not part of this operation: adapting
    luminance remains an absolute value in cd/m2.
    """

    stimulus = _vector(XYZ, "XYZ")
    white = _vector(XYZ_w, "XYZ_w")
    background = float(Y_b)
    _require_finite((background,), "Y_b")
    if white[1] <= 0.0:
        raise ValueError(f"XYZ_w must have positive Y; got {white[1]}")
    if background <= 0.0:
        raise ValueError(f"Y_b must be positive; got {background}")
    scale = 100.0 / white[1]
    return (
        tuple(value * scale for value in stimulus),  # type: ignore[return-value]
        tuple(value * scale for value in white),  # type: ignore[return-value]
        background * scale,
    )


def degree_of_adaptation(
    L_A: float,
    surround: Surround = AVERAGE,
    override: float | None = None,
) -> float:
    """Return CAM16's clamped adaptation degree, or a declared override."""

    adapting_luminance = float(L_A)
    _require_finite((adapting_luminance, surround.F), "adaptation inputs")
    if adapting_luminance <= 0.0:
        raise ValueError(f"L_A must be positive; got {adapting_luminance}")
    if surround.F <= 0.0:
        raise ValueError(f"surround F must be positive; got {surround.F}")
    if override is not None:
        value = float(override)
        _require_finite((value,), "degree of adaptation")
        if not 0.0 <= value <= 1.0:
            raise ValueError(
                f"degree of adaptation must lie in [0, 1]; got {value}"
            )
        return value
    value = surround.F * (
        1.0 - (1.0 / 3.6) * math.exp((-adapting_luminance - 42.0) / 92.0)
    )
    return min(1.0, max(0.0, value))


def _validate_inputs(
    XYZ: Vector,
    XYZ_w: Vector,
    L_A: float,
    Y_b: float,
    surround: Surround,
    allow_negative_xyz: bool,
) -> None:
    _require_finite(
        (L_A, Y_b, surround.F, surround.c, surround.N_c),
        "viewing-condition inputs",
    )
    if any(value <= 0.0 for value in XYZ_w):
        raise ValueError(f"XYZ_w components must be positive; got {XYZ_w}")
    if not math.isclose(XYZ_w[1], 100.0, rel_tol=0.0, abs_tol=1e-9):
        raise ValueError(
            "XYZ_w must use CAM16 Domain-100 (Y_w = 100); pass "
            "normalize=True or --normalize-domain100 to scale the inputs "
            f"explicitly. Got Y_w={XYZ_w[1]}"
        )
    if L_A <= 0.0:
        raise ValueError(f"L_A must be positive; got {L_A}")
    if not 0.0 < Y_b <= XYZ_w[1]:
        raise ValueError(f"Y_b must lie in (0, Y_w]; got {Y_b}")
    if surround.F <= 0.0 or surround.c <= 0.0 or surround.N_c <= 0.0:
        raise ValueError(f"surround parameters must be positive; got {surround}")
    if not allow_negative_xyz and any(value < 0.0 for value in XYZ):
        raise ValueError(
            "XYZ contains a negative component. This is refused by default "
            "because difference/residual triples are not physical colours; "
            "pass allow_negative_xyz=True or --allow-negative-xyz only for "
            f"deliberate numerical exploration. Got {XYZ}"
        )
    if all(value == 0.0 for value in XYZ):
        raise ModelDomainError(
            "all-zero XYZ has undefined chromatic correlates; no hue or "
            "saturation is reported"
        )


def _transform(matrix: tuple[Vector, Vector, Vector], vector: Vector) -> Vector:
    return tuple(
        sum(matrix[row][column] * vector[column] for column in range(3))
        for row in range(3)
    )  # type: ignore[return-value]


def _post_adaptation(value: float, F_L: float) -> float:
    scaled = (F_L * abs(value) / 100.0) ** 0.42
    return math.copysign(400.0 * scaled / (scaled + 27.13), value) + 0.1


@dataclass(frozen=True)
class _SharedState:
    a: float
    b: float
    h: float
    A: float
    A_w: float
    RGB_a: Vector
    F_L: float
    n: float
    z: float
    N_bb: float
    D: float


def _shared_state(
    XYZ: Sequence[float],
    XYZ_w: Sequence[float],
    L_A: float,
    Y_b: float,
    surround: Surround,
    degree_of_adaptation_override: float | None,
    allow_negative_xyz: bool,
    normalize: bool,
) -> tuple[_SharedState, Vector, Vector, float]:
    stimulus = _vector(XYZ, "XYZ")
    white = _vector(XYZ_w, "XYZ_w")
    adapting_luminance = float(L_A)
    background = float(Y_b)
    if normalize:
        stimulus, white, background = normalize_to_domain100(
            stimulus, white, background
        )
    _validate_inputs(
        stimulus,
        white,
        adapting_luminance,
        background,
        surround,
        allow_negative_xyz,
    )

    Y_w = white[1]
    n = background / Y_w
    if not math.isfinite(n) or n <= 0.0:
        raise ModelDomainError(
            "relative background Y_b/Y_w is outside the supported numerical "
            f"domain; got {n} from Y_b={background} and Y_w={Y_w}"
        )
    z = 1.48 + math.sqrt(n)
    N_bb = 0.725 * (1.0 / n) ** 0.2
    if not math.isfinite(N_bb):
        raise ModelDomainError(
            "background induction factor is outside the supported numerical "
            f"domain for Y_b/Y_w={n}"
        )
    k = 1.0 / (5.0 * adapting_luminance + 1.0)
    F_L = (
        0.2 * k**4 * (5.0 * adapting_luminance)
        + 0.1
        * (1.0 - k**4) ** 2
        * (5.0 * adapting_luminance) ** (1.0 / 3.0)
    )

    RGB = _transform(M16, stimulus)
    RGB_w = _transform(M16, white)
    if any(not math.isfinite(value) or value <= 0.0 for value in RGB_w):
        raise ModelDomainError(
            "XYZ_w produces a non-positive CAT16 cone response; got "
            f"{RGB_w}"
        )
    D = degree_of_adaptation(
        adapting_luminance, surround, degree_of_adaptation_override
    )
    D_RGB = tuple(D * Y_w / value + 1.0 - D for value in RGB_w)
    adapt = [
        (
            _post_adaptation(D_RGB[index] * RGB[index], F_L),
            _post_adaptation(D_RGB[index] * RGB_w[index], F_L),
        )
        for index in range(3)
    ]
    RGB_a: Vector = (adapt[0][0], adapt[1][0], adapt[2][0])
    RGB_aw: Vector = (adapt[0][1], adapt[1][1], adapt[2][1])

    a = RGB_a[0] - 12.0 * RGB_a[1] / 11.0 + RGB_a[2] / 11.0
    b = (RGB_a[0] + RGB_a[1] - 2.0 * RGB_a[2]) / 9.0
    h = math.degrees(math.atan2(b, a)) % 360.0
    A = 2.0 * RGB_a[0] + RGB_a[1] + RGB_a[2] / 20.0 - 0.305
    A_w = 2.0 * RGB_aw[0] + RGB_aw[1] + RGB_aw[2] / 20.0 - 0.305
    if not math.isfinite(A_w) or A_w <= 0.0:
        raise ModelDomainError(
            "XYZ_w produces a non-positive achromatic white response; got "
            f"{A_w}"
        )
    if not math.isfinite(A) or A <= 0.0:
        raise ModelDomainError(
            "lightness is undefined: the stimulus achromatic response is "
            f"{A}, outside the supported real-valued domain"
        )
    return (
        _SharedState(a, b, h, A, A_w, RGB_a, F_L, n, z, N_bb, D),
        stimulus,
        white,
        background,
    )


def _cam16_from_state(state: _SharedState, surround: Surround) -> dict[str, float]:
    A = state.A * state.N_bb
    A_w = state.A_w * state.N_bb
    J = 100.0 * (A / A_w) ** (surround.c * state.z)
    Q = (
        (4.0 / surround.c)
        * math.sqrt(J / 100.0)
        * (A_w + 4.0)
        * state.F_L**0.25
    )
    chroma_denominator = (
        state.RGB_a[0] + state.RGB_a[1] + 21.0 * state.RGB_a[2] / 20.0
    )
    if not math.isfinite(chroma_denominator) or chroma_denominator <= 0.0:
        raise ModelDomainError(
            "CAM16 chroma is undefined: the adapted-response denominator is "
            f"{chroma_denominator}, outside the supported real-valued domain"
        )
    h_rad = math.radians(state.h)
    e_t = 0.25 * (math.cos(h_rad + 2.0) + 3.8)
    N_cb = state.N_bb
    t = (
        50000.0
        / 13.0
        * surround.N_c
        * N_cb
        * e_t
        * math.hypot(state.a, state.b)
        / chroma_denominator
    )
    C = (
        t**0.9
        * math.sqrt(J / 100.0)
        * (1.64 - 0.29**state.n) ** 0.73
    )
    M = C * state.F_L**0.25
    s = 100.0 * math.sqrt(M / Q)
    return _checked_correlates(
        "CAM16", {"J": J, "Q": Q, "C": C, "M": M, "s": s, "h": state.h}
    )


def _hellwig2022_from_state(
    state: _SharedState, surround: Surround
) -> dict[str, float]:
    J = 100.0 * (state.A / state.A_w) ** (surround.c * state.z)
    Q = (2.0 / surround.c) * (J / 100.0) * state.A_w
    h_rad = math.radians(state.h)
    e_t = (
        -0.0582 * math.cos(h_rad)
        - 0.0258 * math.cos(2.0 * h_rad)
        - 0.1347 * math.cos(3.0 * h_rad)
        + 0.0289 * math.cos(4.0 * h_rad)
        - 0.1475 * math.sin(h_rad)
        - 0.0308 * math.sin(2.0 * h_rad)
        + 0.0385 * math.sin(3.0 * h_rad)
        + 0.0096 * math.sin(4.0 * h_rad)
        + 1.0
    )
    M = 43.0 * surround.N_c * e_t * math.hypot(state.a, state.b)
    C = 35.0 * M / state.A_w
    s = 100.0 * M / Q
    return _checked_correlates(
        "Hellwig--Fairchild 2022",
        {"J": J, "Q": Q, "C": C, "M": M, "s": s, "h": state.h},
    )


def _checked_correlates(
    model: str, correlates: dict[str, float]
) -> dict[str, float]:
    """Refuse numerical overflow instead of serializing NaN or infinity."""

    invalid = {
        name: value
        for name, value in correlates.items()
        if not math.isfinite(value)
    }
    if invalid:
        raise ModelDomainError(
            f"{model} produced non-finite correlates {invalid}; the declared "
            "inputs are outside the supported numerical domain"
        )
    return correlates


#: Below this fraction of the adapted-response scale, the opponent direction is
#: too ill-conditioned to report as a reliable hue. This is a cross-runtime
#: reporting boundary, not an observer-derived or perceptual threshold.
#:
#: `a` and `b` are formed by near-total cancellation among three nearly equal
#: adapted responses. Exact cancellation leaves ratios below 4.2e-16. A white
#: under adaptation so close to complete that its ratio is about 1.0e-12 has a
#: mathematically non-zero direction, but that direction changes by 0.003
#: degrees between supported runtimes while its chroma is about 1e-8. A 1e-8
#: cutoff declines that unstable case. Constructed inputs immediately above the
#: cutoff retain matching six-significant-digit output across Python and
#: JavaScript, although their raw values do not meet the broad grid's stricter
#: 1e-11 relative tolerance.
#:
#: The failure this prevents is concrete: two correct implementations of these
#: equations can return very different angles when the opponent magnitude is
#: dominated by cancellation. A reader would otherwise see a precise-looking
#: angle whose last digits depend on the runtime.
OPPONENT_NOISE_RATIO = 1.0e-8


def _hue_diagnostics(state: _SharedState) -> dict[str, float | bool]:
    """Whether this stimulus's hue angle is chroma or rounding residue.

    Both formulations share `a` and `b`, so this is a property of the stimulus
    and viewing condition rather than of either model.
    """

    magnitude = math.hypot(state.a, state.b)
    scale = max(abs(value) for value in state.RGB_a)
    ratio = magnitude / scale if scale > 0.0 else 0.0
    return {
        "opponent_magnitude": magnitude,
        "opponent_magnitude_ratio": ratio,
        "hue_resolved": ratio > OPPONENT_NOISE_RATIO,
    }


def compare_models(
    XYZ: Sequence[float],
    XYZ_w: Sequence[float],
    L_A: float,
    Y_b: float,
    surround: Surround = AVERAGE,
    *,
    model: str = "both",
    normalize: bool = False,
    degree_of_adaptation_override: float | None = None,
    allow_negative_xyz: bool = False,
) -> dict[str, dict[str, float]]:
    """Return one or both labelled forward-model results.

    ``XYZ`` and ``XYZ_w`` use CAM16 Domain-100 unless ``normalize=True``.  With
    normalization enabled, ``XYZ``, ``XYZ_w``, and ``Y_b`` are scaled together;
    ``L_A`` remains the declared adapting-field luminance in cd/m2.

    ``h`` is returned for every accepted stimulus, including achromatic ones
    where it is not meaningful. Use :func:`compare_models_with_diagnostics` to
    learn whether it was resolved.
    """

    return compare_models_with_diagnostics(
        XYZ,
        XYZ_w,
        L_A,
        Y_b,
        surround,
        model=model,
        normalize=normalize,
        degree_of_adaptation_override=degree_of_adaptation_override,
        allow_negative_xyz=allow_negative_xyz,
    )[0]


def compare_models_with_diagnostics(
    XYZ: Sequence[float],
    XYZ_w: Sequence[float],
    L_A: float,
    Y_b: float,
    surround: Surround = AVERAGE,
    *,
    model: str = "both",
    normalize: bool = False,
    degree_of_adaptation_override: float | None = None,
    allow_negative_xyz: bool = False,
) -> tuple[dict[str, dict[str, float]], dict[str, float | bool]]:
    """Return the model results and the shared opponent-vector diagnostics."""

    if model not in {"cam16", "hellwig2022", "both"}:
        raise ValueError("model must be 'cam16', 'hellwig2022', or 'both'")
    try:
        state, _, _, _ = _shared_state(
            XYZ,
            XYZ_w,
            L_A,
            Y_b,
            surround,
            degree_of_adaptation_override,
            allow_negative_xyz,
            normalize,
        )
        result: dict[str, dict[str, float]] = {}
        if model in {"cam16", "both"}:
            result["cam16"] = _cam16_from_state(state, surround)
        if model in {"hellwig2022", "both"}:
            result["hellwig2022"] = _hellwig2022_from_state(state, surround)
        return result, _hue_diagnostics(state)
    except (OverflowError, ZeroDivisionError) as error:
        raise ModelDomainError(
            "model evaluation overflowed or divided by zero; the declared "
            "inputs are outside the supported numerical domain"
        ) from error


def cam16_forward(
    XYZ: Sequence[float],
    XYZ_w: Sequence[float],
    L_A: float,
    Y_b: float,
    surround: Surround = AVERAGE,
    *,
    normalize: bool = False,
    degree_of_adaptation_override: float | None = None,
    allow_negative_xyz: bool = False,
) -> dict[str, float]:
    """Return standard CAM16 ``J, Q, C, M, s, h`` for one XYZ stimulus."""

    return compare_models(
        XYZ,
        XYZ_w,
        L_A,
        Y_b,
        surround,
        model="cam16",
        normalize=normalize,
        degree_of_adaptation_override=degree_of_adaptation_override,
        allow_negative_xyz=allow_negative_xyz,
    )["cam16"]


def hellwig2022_forward(
    XYZ: Sequence[float],
    XYZ_w: Sequence[float],
    L_A: float,
    Y_b: float,
    surround: Surround = AVERAGE,
    *,
    normalize: bool = False,
    degree_of_adaptation_override: float | None = None,
    allow_negative_xyz: bool = False,
) -> dict[str, float]:
    """Return Hellwig--Fairchild 2022 ``J, Q, C, M, s, h`` correlates."""

    return compare_models(
        XYZ,
        XYZ_w,
        L_A,
        Y_b,
        surround,
        model="hellwig2022",
        normalize=normalize,
        degree_of_adaptation_override=degree_of_adaptation_override,
        allow_negative_xyz=allow_negative_xyz,
    )["hellwig2022"]


@dataclass(frozen=True)
class Sample:
    label: str
    XYZ: Vector


@dataclass(frozen=True)
class _OutputContext:
    """Resolved conditions plus the supplied values needed to recalculate them."""

    XYZ_w_as_supplied: Vector
    XYZ_w: Vector
    L_A_cd_m2: float
    Y_b_as_supplied: float
    Y_b: float
    surround: Surround
    degree_of_adaptation: float
    degree_of_adaptation_source: str
    domain100_normalized: bool
    allow_negative_xyz: bool

    def as_document(self) -> dict[str, object]:
        return {
            "XYZ_w_as_supplied": self.XYZ_w_as_supplied,
            "XYZ_w": self.XYZ_w,
            "L_A_cd_m2": self.L_A_cd_m2,
            "Y_b_as_supplied": self.Y_b_as_supplied,
            "Y_b": self.Y_b,
            "surround": asdict(self.surround),
            "degree_of_adaptation": self.degree_of_adaptation,
            "degree_of_adaptation_source": self.degree_of_adaptation_source,
            "domain100_normalized": self.domain100_normalized,
            "allow_negative_xyz": self.allow_negative_xyz,
        }


def _read_csv(handle: IO[str]) -> list[Sample]:
    """Read X, Y, Z, and optional label columns from a delimited export.

    Instrument and toolbox exports commonly carry a commented metadata
    preamble above the header, so lines whose first non-space character is
    ``#`` are dropped only until the header is found. After the header, ``#``
    belongs to the CSV data: a label such as ``#neutral`` must not make a valid
    sample disappear. Original file line numbers are retained through the
    preamble filter, because an error that names a line the reader cannot find
    in the file is worse than no line number at all.
    """

    numbered: list[tuple[int, str]] = []
    header_found = False
    for number, line in enumerate(handle, start=1):
        if number == 1:
            # Files opened by the CLI use utf-8-sig, but stdin does not pass
            # through that decoder. Accept a BOM there as well.
            line = line.lstrip("\ufeff")
        if not header_found:
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            header_found = True
        numbered.append((number, line))
    reader = csv.DictReader(line for _, line in numbered)
    if reader.fieldnames is None:
        raise ValueError("input CSV has no header")
    normalized = [name.strip().lower() for name in reader.fieldnames]
    if len(normalized) != len(set(normalized)):
        raise ValueError("input CSV has duplicate column names after case folding")
    field_map = dict(zip(normalized, reader.fieldnames))
    missing = [name for name in ("x", "y", "z") if name not in field_map]
    if missing:
        raise ValueError(
            "input CSV requires X,Y,Z columns (case-insensitive); missing "
            + ",".join(missing)
        )
    samples: list[Sample] = []
    for row in reader:
        line_number = numbered[reader.line_num - 1][0]
        if None in row:
            raise ValueError(
                f"invalid CSV row {line_number}: more fields than the header"
            )
        try:
            XYZ = _vector(
                tuple(row[field_map[name]] for name in ("x", "y", "z")),
                f"CSV row {line_number} XYZ",
            )
        except (TypeError, ValueError) as error:
            raise ValueError(f"invalid CSV row {line_number}: {error}") from error
        label_key = field_map.get("label")
        label = row[label_key].strip() if label_key and row[label_key] else ""
        samples.append(Sample(label or f"sample-{len(samples) + 1}", XYZ))
    if not samples:
        raise ValueError("input CSV contains no data rows")
    return samples


def _surround_from_args(args: argparse.Namespace) -> Surround:
    custom = (args.surround_f, args.surround_c, args.surround_nc)
    if any(value is not None for value in custom):
        if not all(value is not None for value in custom):
            raise ValueError(
                "--surround-f, --surround-c, and --surround-nc must be supplied together"
            )
        if args.surround is not None:
            # Two viewing conditions were supplied and only one can be used.
            # Preferring either silently is the failure this tool exists to
            # prevent, so it refuses instead of choosing.
            raise ValueError(
                f"--surround {args.surround} conflicts with an explicit "
                "--surround-f/--surround-c/--surround-nc triple; supply one "
                "surround, not two"
            )
        return Surround(*custom, name="custom")
    return SURROUNDS[args.surround or "average"]


def _flatten(
    supplied_samples: Sequence[Sample],
    evaluated_samples: Sequence[Sample],
    results: Sequence[dict[str, dict[str, float]]],
    diagnostics: Sequence[dict[str, float | bool]],
    context: _OutputContext,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for supplied, sample, model_results, diagnostic in zip(
        supplied_samples, evaluated_samples, results, diagnostics
    ):
        for model_name, correlates in model_results.items():
            rows.append(
                {
                    "label": sample.label,
                    "model": model_name,
                    "X_as_supplied": supplied.XYZ[0],
                    "Y_as_supplied": supplied.XYZ[1],
                    "Z_as_supplied": supplied.XYZ[2],
                    "X": sample.XYZ[0],
                    "Y": sample.XYZ[1],
                    "Z": sample.XYZ[2],
                    **correlates,
                    "hue_resolved": diagnostic["hue_resolved"],
                    "opponent_magnitude": diagnostic["opponent_magnitude"],
                    "X_w_as_supplied": context.XYZ_w_as_supplied[0],
                    "Y_w_as_supplied": context.XYZ_w_as_supplied[1],
                    "Z_w_as_supplied": context.XYZ_w_as_supplied[2],
                    "X_w": context.XYZ_w[0],
                    "Y_w": context.XYZ_w[1],
                    "Z_w": context.XYZ_w[2],
                    "L_A_cd_m2": context.L_A_cd_m2,
                    "Y_b_as_supplied": context.Y_b_as_supplied,
                    "Y_b": context.Y_b,
                    "surround": context.surround.name,
                    "surround_F": context.surround.F,
                    "surround_c": context.surround.c,
                    "surround_N_c": context.surround.N_c,
                    "degree_of_adaptation": context.degree_of_adaptation,
                    "degree_of_adaptation_source": (
                        context.degree_of_adaptation_source
                    ),
                    "domain100_normalized": context.domain100_normalized,
                    "allow_negative_xyz": context.allow_negative_xyz,
                    "schema": SCHEMA,
                    "implementation_version": IMPLEMENTATION_VERSION,
                    "interpretation_limit": INTERPRETATION_LIMIT,
                }
            )
    return rows


def _format_table(
    rows: Sequence[dict[str, object]], context: _OutputContext
) -> str:
    def display_label(value: object) -> str:
        """Escape terminal controls while preserving readable Unicode labels."""

        escapes = {
            "\\": "\\\\",
            "\b": "\\b",
            "\t": "\\t",
            "\n": "\\n",
            "\f": "\\f",
            "\r": "\\r",
        }
        rendered_label: list[str] = []
        for character in str(value):
            if character in escapes:
                rendered_label.append(escapes[character])
            elif character.isprintable():
                rendered_label.append(character)
            else:
                codepoint = ord(character)
                if codepoint <= 0xFF:
                    rendered_label.append(f"\\x{codepoint:02x}")
                elif codepoint <= 0xFFFF:
                    rendered_label.append(f"\\u{codepoint:04x}")
                else:
                    rendered_label.append(f"\\U{codepoint:08x}")
        return "".join(rendered_label)

    columns = ("label", "model", "J", "Q", "C", "M", "s", "h")
    rendered: list[dict[str, str]] = []
    for row in rows:
        rendered.append(
            {
                key: (
                    display_label(row[key])
                    if key == "label"
                    else str(row[key])
                    if key == "model"
                    else "n/a"
                    if key == "h" and not row["hue_resolved"]
                    else "~0"
                    if key in {"C", "M", "s"} and not row["hue_resolved"]
                    else f"{row[key]:.6g}"
                )
                for key in columns
            }
        )
    widths = {
        key: max(len(key), *(len(row[key]) for row in rendered)) for key in columns
    }
    lines = ["  ".join(key.rjust(widths[key]) for key in columns)]
    lines.append("  ".join("-" * widths[key] for key in columns))
    lines.extend(
        "  ".join(row[key].rjust(widths[key]) for key in columns)
        for row in rendered
    )
    lines.append("")
    lines.append("6 significant digits shown; CSV and JSON retain full precision")
    lines.append("")

    def field(name: str, value: str) -> str:
        return f"  {name:<22}{value}"

    lines.append("viewing conditions")
    lines.append(
        field("XYZ_w", ", ".join(f"{value:.10g}" for value in context.XYZ_w))
    )
    lines.append(field("L_A", f"{context.L_A_cd_m2:.10g} cd/m2"))
    lines.append(field("Y_b", f"{context.Y_b:.10g}"))
    lines.append(
        field(
            "surround",
            f"{context.surround.name} (F={context.surround.F:.10g}, "
            f"c={context.surround.c:.10g}, N_c={context.surround.N_c:.10g})",
        )
    )
    lines.append(
        field(
            "degree of adaptation",
            f"{context.degree_of_adaptation:.10g} "
            f"({context.degree_of_adaptation_source})",
        )
    )
    if context.domain100_normalized:
        lines.append("as supplied, before Domain-100 normalization")
        lines.append(
            field(
                "XYZ_w",
                ", ".join(
                    f"{value:.10g}" for value in context.XYZ_w_as_supplied
                ),
            )
        )
        lines.append(field("Y_b", f"{context.Y_b_as_supplied:.10g}"))
    lines.append("input handling")
    lines.append(
        field(
            "Domain-100 normalized",
            str(context.domain100_normalized).lower(),
        )
    )
    lines.append(
        field("signed XYZ allowed", str(context.allow_negative_xyz).lower())
    )
    unresolved = sorted(
        {display_label(row["label"]) for row in rows if not row["hue_resolved"]}
    )
    if unresolved:
        # Printing ten digits of an angle that is entirely rounding residue is
        # the failure this line exists to stop. J, Q, and the near-zero chroma
        # remain valid for these samples.
        warning = (
            "hue not resolved for: "
            + ", ".join(unresolved)
            + ". The opponent direction is too close to floating-point "
            "cancellation to report reliably; table h is n/a and C, M, and s "
            "are ~0. CSV and JSON retain the numeric values."
        )
        # The point of this line is to name the samples, so the names have to
        # survive it. Default wrapping splits on hyphens and inside long words,
        # which turns "grey-patch-04" into two fragments that no longer match a
        # search of the output. A label longer than the width overruns instead,
        # which is the caller's own choice of label.
        lines.extend(
            textwrap.wrap(
                warning,
                width=80,
                subsequent_indent="  ",
                break_on_hyphens=False,
                break_long_words=False,
            )
        )
    lines.append(f"implementation: cam16_compare.py {IMPLEMENTATION_VERSION}")
    lines.append(f"interpretation limit: {INTERPRETATION_LIMIT}")
    return "\n".join(lines) + "\n"


def _format_csv(rows: Sequence[dict[str, object]]) -> str:
    from io import StringIO

    output = StringIO()
    # Conditions and safeguards repeat on every row because a row is commonly
    # detached from its file. Keeping both input and evaluated scales makes a
    # normalized batch recalculable without the original command line.
    columns = (
        "label",
        "model",
        "X_as_supplied",
        "Y_as_supplied",
        "Z_as_supplied",
        "X",
        "Y",
        "Z",
        *CORRELATES,
        "hue_resolved",
        "opponent_magnitude",
        "X_w_as_supplied",
        "Y_w_as_supplied",
        "Z_w_as_supplied",
        "X_w",
        "Y_w",
        "Z_w",
        "L_A_cd_m2",
        "Y_b_as_supplied",
        "Y_b",
        "surround",
        "surround_F",
        "surround_c",
        "surround_N_c",
        "degree_of_adaptation",
        "degree_of_adaptation_source",
        "domain100_normalized",
        "allow_negative_xyz",
        "schema",
        "implementation_version",
        "interpretation_limit",
    )
    text_columns = {
        "label",
        "model",
        "surround",
        "degree_of_adaptation_source",
        "schema",
        "implementation_version",
        "interpretation_limit",
    }
    boolean_columns = {
        "hue_resolved",
        "domain100_normalized",
        "allow_negative_xyz",
    }
    writer = csv.DictWriter(output, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                key: (
                    row[key]
                    if key in text_columns
                    else str(row[key]).lower()
                    if key in boolean_columns
                    # `repr(float)` is the shortest decimal that round-trips
                    # to the same binary value. A fixed 15-digit format loses
                    # information while making the CSV look more precise than
                    # it is, and its last digit varies across Python/libm
                    # versions for otherwise equivalent calculations.
                    else repr(float(row[key]))
                )
                for key in columns
            }
        )
    return output.getvalue()


def _parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(
        # Fixed rather than taken from sys.argv[0]. The version string and the
        # `implementation:` line exist to identify what produced a result, so
        # they must not change when the file is vendored under another name,
        # invoked through a wrapper, or imported and called directly.
        prog="cam16_compare.py",
        description=(
            "Convert XYZ to standard CAM16 and/or Hellwig-Fairchild 2022\n"
            "forward appearance correlates."
        ),
        epilog=(
            "example:\n"
            "  python3 cam16_compare.py --xyz 19.01 20 21.78 \\\n"
            "      --white 95.05 100 108.88 --la 318.31 --yb 20\n"
            "\n"
            "One adopted white, background, surround, and adaptation degree\n"
            "apply to every sample in a CSV batch. Run the tool again for a\n"
            "different viewing condition."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {IMPLEMENTATION_VERSION}",
        help="show the implementation version and exit",
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--xyz",
        nargs=3,
        type=float,
        metavar=("X", "Y", "Z"),
        help=(
            "one stimulus as three tristimulus values on the adopted-white "
            "scale"
        ),
    )
    source.add_argument(
        "--input-csv",
        metavar="PATH",
        help=(
            "comma-delimited CSV with X,Y,Z and optional label columns; use "
            "- for standard input"
        ),
    )
    parser.add_argument(
        "--white",
        nargs=3,
        type=float,
        required=True,
        metavar=("XW", "YW", "ZW"),
        help=(
            "adopted white on the stimulus scale; Y must be 100 unless "
            "normalization is enabled"
        ),
    )
    parser.add_argument(
        "--la",
        type=float,
        required=True,
        help="adapting luminance L_A in cd/m2",
    )
    parser.add_argument(
        "--yb",
        type=float,
        required=True,
        help="background Y_b on the same relative-Y scale as the white",
    )
    # No default, so that a named surround supplied alongside a custom triple
    # is distinguishable from the unstated case. "average" is applied in
    # :func:`_surround_from_args`.
    parser.add_argument(
        "--surround",
        choices=tuple(SURROUNDS),
        default=None,
        help="named surround (default: average)",
    )
    parser.add_argument("--surround-f", type=float, help="custom surround F")
    parser.add_argument("--surround-c", type=float, help="custom surround c")
    parser.add_argument("--surround-nc", type=float, help="custom surround N_c")
    parser.add_argument(
        "--degree-of-adaptation",
        type=float,
        metavar="D",
        help="override computed adaptation degree with an explicit value in [0,1]",
    )
    parser.add_argument(
        "--normalize-domain100",
        action="store_true",
        help="scale XYZ, white, and Y_b together so adopted-white Y is 100",
    )
    parser.add_argument(
        "--allow-negative-xyz",
        action="store_true",
        help="allow deliberate numerical exploration of signed XYZ triples",
    )
    parser.add_argument(
        "--model",
        choices=("cam16", "hellwig2022", "both"),
        default="both",
        help="which formulation to report (default: both)",
    )
    parser.add_argument(
        "--format",
        choices=("table", "csv", "json"),
        default="table",
        help=(
            "table for reading, JSON for machine-readable data, or a wide "
            "row-per-model CSV (default: table)"
        ),
    )
    parser.add_argument(
        "--output",
        metavar="PATH",
        help="write output to a file instead of standard output",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        # Argument-shape errors are worth a usage block; a bad value on line
        # 300 of an export is not, and printing one buries the line number.
        surround = _surround_from_args(args)
    except ValueError as error:
        parser.error(str(error))
    try:
        if args.xyz is not None:
            samples = [Sample("sample-1", _vector(args.xyz, "XYZ"))]
        elif args.input_csv == "-":
            samples = _read_csv(sys.stdin)
        else:
            with Path(args.input_csv).open(encoding="utf-8-sig", newline="") as handle:
                samples = _read_csv(handle)

        white = _vector(args.white, "XYZ_w")
        background = args.yb
        evaluated_samples = samples
        evaluated_white = white
        evaluated_background = background
        if args.normalize_domain100:
            evaluated_samples = []
            for sample in samples:
                XYZ, normalized_white, normalized_background = normalize_to_domain100(
                    sample.XYZ, white, background
                )
                evaluated_samples.append(Sample(sample.label, XYZ))
                evaluated_white = normalized_white
                evaluated_background = normalized_background
        D = degree_of_adaptation(args.la, surround, args.degree_of_adaptation)
        context = _OutputContext(
            XYZ_w_as_supplied=white,
            XYZ_w=evaluated_white,
            L_A_cd_m2=args.la,
            Y_b_as_supplied=background,
            Y_b=evaluated_background,
            surround=surround,
            degree_of_adaptation=D,
            degree_of_adaptation_source=(
                "override" if args.degree_of_adaptation is not None else "computed"
            ),
            domain100_normalized=args.normalize_domain100,
            allow_negative_xyz=args.allow_negative_xyz,
        )
        evaluated = [
            compare_models_with_diagnostics(
                sample.XYZ,
                evaluated_white,
                args.la,
                evaluated_background,
                surround,
                model=args.model,
                degree_of_adaptation_override=args.degree_of_adaptation,
                allow_negative_xyz=args.allow_negative_xyz,
            )
            for sample in evaluated_samples
        ]
        results = [models for models, _ in evaluated]
        diagnostics = [diagnostic for _, diagnostic in evaluated]
        flat = _flatten(samples, evaluated_samples, results, diagnostics, context)
        if args.format == "table":
            payload = _format_table(flat, context)
        elif args.format == "csv":
            payload = _format_csv(flat)
        else:
            document = {
                "schema": SCHEMA,
                "implementation_version": IMPLEMENTATION_VERSION,
                "viewing_conditions": context.as_document(),
                "interpretation_limit": INTERPRETATION_LIMIT,
                "results": [
                    {
                        "label": sample.label,
                        "XYZ": sample.XYZ,
                        # Normalization rewrites the stimulus before the model
                        # sees it. Retaining what was supplied keeps the record
                        # readable back to the measurement it came from.
                        "XYZ_as_supplied": supplied.XYZ,
                        # Shared by both models: h comes from the same a and b.
                        "hue_diagnostics": diagnostic,
                        "models": result,
                    }
                    for supplied, sample, result, diagnostic in zip(
                        samples, evaluated_samples, results, diagnostics
                    )
                ],
            }
            payload = (
                json.dumps(document, indent=2, sort_keys=True, allow_nan=False)
                + "\n"
            )

        if args.output:
            Path(args.output).write_text(payload, encoding="utf-8")
        else:
            sys.stdout.write(payload)
        return 0
    except (OSError, ValueError, csv.Error) as error:
        print(f"{parser.prog}: error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
