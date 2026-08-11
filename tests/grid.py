"""Shared numerical grid for independent and cross-language differentials."""

from __future__ import annotations

import itertools
from typing import Iterator


WHITES = (
    (95.047, 100.0, 108.883),
    (96.422, 100.0, 82.521),
    (100.0, 100.0, 100.0),
)
# A stimulus equal to the adopted white is the first thing a reader tries, and
# it is not the same thing as an achromatic stimulus. Under incomplete
# adaptation the model can give it a genuine hue -- about 64 degrees under
# Illuminant A, because a partly adapted observer does not see the adopted
# white as neutral. Under near-complete adaptation the same input shrinks to an
# opponent direction that finite precision cannot reproduce reliably. Both
# behaviours are reachable from the calculator and neither was covered.
ADOPTED_WHITE = "adopted-white"

STIMULI = (
    (19.01, 20.0, 21.78),
    (45.0, 36.0, 12.0),
    (12.0, 10.0, 8.0),
    (30.0, 40.0, 55.0),
    (0.5, 0.2, 0.8),
    (90.0, 95.0, 100.0),
    (33.0, 33.0, 33.0),
    ADOPTED_WHITE,
)
ADAPTING_LUMINANCES = (4.0, 20.0, 318.31, 2000.0)
BACKGROUNDS = (5.0, 20.0, 100.0)
SURROUNDS = (
    ("average", (1.0, 0.69, 1.0)),
    ("dim", (0.9, 0.59, 0.9)),
    ("dark", (0.8, 0.525, 0.8)),
)
DISCOUNT_ILLUMINANT = (False, True)


def reference_cases() -> Iterator[
    tuple[dict[str, object], tuple[float, float, float], bool]
]:
    """Yield cases plus the independent-library surround/adaptation inputs."""

    grid = itertools.product(
        WHITES,
        STIMULI,
        ADAPTING_LUMINANCES,
        BACKGROUNDS,
        SURROUNDS,
        DISCOUNT_ILLUMINANT,
    )
    for white, stimulus, L_A, Y_b, (surround, factors), discount in grid:
        if stimulus is ADOPTED_WHITE:
            stimulus = white
        yield (
            {
                "XYZ": stimulus,
                "XYZ_w": white,
                "L_A": L_A,
                "Y_b": Y_b,
                "surround": surround,
                "degree_of_adaptation_override": 1.0 if discount else None,
            },
            factors,
            discount,
        )


def cases() -> Iterator[dict[str, object]]:
    """Yield every declared viewing-condition case."""

    for case, _, _ in reference_cases():
        yield case


CASE_COUNT = (
    len(WHITES)
    * len(STIMULI)
    * len(ADAPTING_LUMINANCES)
    * len(BACKGROUNDS)
    * len(SURROUNDS)
    * len(DISCOUNT_ILLUMINANT)
)


# The broad grid above deliberately keeps clear of the hue-resolution cutoff so
# last-bit rounding cannot flip the public resolved/unresolved decision. These
# additional fixtures exercise the separate question of agreement immediately
# above that boundary.
#
# These stimuli fill that band. Each is the D65 white with a single offset on
# X, bisected under near-complete adaptation (L_A = 2000, where the white's own
# residual chroma is 1e-12) until the opponent ratio hits the stated target.
# The recorded offsets are regression fixtures constructed by that bisection;
# they are not recomputed or adjusted to make a future implementation pass.
BOUNDARY_WHITE = (95.047, 100.0, 108.883)
BOUNDARY_L_A = 2000.0
BOUNDARY_Y_B = 20.0
BOUNDARY_OFFSETS = (
    (4.438e-06, 1.2e-08),
    (1.849e-05, 5.0e-08),
    (1.849e-04, 5.0e-07),
    (1.849e-03, 5.0e-06),
)


def boundary_cases() -> Iterator[tuple[dict[str, object], float]]:
    """Yield cases just above the hue-resolution cutoff, with their targets."""

    for offset, target_ratio in BOUNDARY_OFFSETS:
        yield (
            {
                "XYZ": (
                    BOUNDARY_WHITE[0] + offset,
                    BOUNDARY_WHITE[1],
                    BOUNDARY_WHITE[2],
                ),
                "XYZ_w": BOUNDARY_WHITE,
                "L_A": BOUNDARY_L_A,
                "Y_b": BOUNDARY_Y_B,
                "surround": "average",
                "degree_of_adaptation_override": None,
            },
            target_ratio,
        )
