# CAM16 and Hellwig–Fairchild 2022 comparator

[`cam16_compare.py`](cam16_compare.py) converts XYZ to six forward appearance
correlates under viewing conditions you declare. It reports standard CAM16,
the Hellwig–Fairchild 2022 proposal, or both side by side. The script needs
Python 3.10 or newer and only the Python standard library.

```sh
python3 cam16_compare.py \
  --xyz 19.01 20 21.78 \
  --white 95.05 100 108.88 \
  --la 318.31 --yb 20
```

On Windows, use `py -3 cam16_compare.py`, or `python cam16_compare.py` when
that is the installed command, and keep the remaining options the same. Run
`--help` for the complete interface and `--version` for the implementation
version.

For a browser or another JavaScript program, import the dependency-free
[`cam16_compare.mjs`](cam16_compare.mjs) module. It exposes the same forward
models and viewing-condition safeguards without the command-line and CSV
interfaces:

```js
import { compareModels } from "./cam16_compare.mjs";

const models = compareModels({
  XYZ: [19.01, 20, 21.78],
  XYZ_w: [95.047, 100, 108.883],
  L_A: 318.31,
  Y_b: 20,
  surround: "average",
});
```

The JavaScript API requires numeric values and never coerces strings. Its
`cam16-browser-api-v1` contract is intentionally smaller than the Python
tool's serialized CSV/JSON schema.

## Use it in your browser

[Open the interactive calculator](https://ferazambuja.github.io/imaging/cam16-hellwig-comparator/)
to enter one XYZ stimulus and its viewing conditions without installing
anything. It runs the tested JavaScript module locally in the page. Use the
Python script when you need CSV batches, machine-readable output, or a file you
can keep with an analysis.

## Installing

Nothing to install. Copy the Python script or the JavaScript module appropriate
to your use. The Python path needs Python 3.10 or newer; the browser module has
no packages, build step, or network dependency.

## Platform status

The test suite has been executed locally on macOS with Python 3.10, 3.13, and
3.14. CI has also passed on Windows with Python 3.13, as well as Ubuntu and
macOS. The runtime uses only the Python standard library. The workflow executes
every fenced shell example in this README with the selected interpreter.

## Why you can trust the numbers

The included tests use two independent numerical anchors:

- [the dependency-free suite](tests/test_cam16_compare.py) reproduces the
  published CAM16 and Hellwig worked examples and tests the structural
  relations that distinguish the models; and
- [`test_cam16_colour_differential.py`](tests/test_cam16_colour_differential.py)
  runs this module against `colour-science` 0.4.7, an independently maintained
  implementation of both models, over 1,728 combinations of stimuli, whites,
  adapting luminances, backgrounds, surrounds, and adaptation modes.

That differential skips when `colour-science` is absent, so the tool keeps its
no-dependency property. The dedicated CI job is configured to install the
package and run the comparison. Hue is compared circularly, and only for
samples whose hue is resolved: see
[Near-neutral samples and hue](#near-neutral-samples-and-hue) for why some
near-zero opponent directions are not numerically reportable. Lightness and
brightness still compare directly for those samples; chroma, colorfulness,
and saturation must stay within explicit near-zero bounds because their raw
residues are not meaningful cross-implementation targets.

```text
   label        model        J        Q          C         M          s        h
--------  -----------  -------  -------  ---------  --------  ---------  -------
sample-1        cam16  41.7312  195.372   0.103356  0.107437    2.34502  217.068
sample-1  hellwig2022  41.7312  55.8523  0.0257636  0.033989  0.0608551  217.068

6 significant digits shown; CSV and JSON retain full precision

viewing conditions
  XYZ_w                 95.05, 100, 108.88
  L_A                   318.31 cd/m2
  Y_b                   20
  surround              average (F=1, c=0.69, N_c=1)
  degree of adaptation  0.9944687801 (computed)
input handling
  Domain-100 normalized false
  signed XYZ allowed    false
implementation: cam16_compare.py 1.2.1
interpretation limit: Model output only; not measurement or observer validation
```

## What the correlates mean

| Correlate | Name | Interpretation |
|---|---|---|
| `J` | lightness | Relative appearance against the adopted white; the white is 100 |
| `Q` | brightness | Perceived amount of light, dependent on the viewing conditions |
| `C` | chroma | Colorfulness judged relative to a similarly illuminated white |
| `M` | colorfulness | Perceived chromatic strength |
| `s` | saturation | Colorfulness relative to the sample's own brightness |
| `h` | hue angle | Hue direction in degrees from 0 to 360 |

`J` and `h` are shared between the two formulations. The proposal redefines
`Q`, `C`, `M`, and `s`, so a difference between rows is a formulation
comparison—not an error, a color difference, or proof that one model is more
accurate.

An exact black is outside this tool's supported chromatic domain and is
refused; do not read the lightness description above as permission to supply
`XYZ = 0, 0, 0`.

## What you must supply

The tool refuses to invent a viewing condition. A correlate calculated under
the wrong condition still looks numerically plausible, so these inputs remain
explicit.

| Input | Flag | How to choose it |
|---|---|---|
| Stimulus | `--xyz` or `--input-csv` | The sample XYZ, on the same scale as the adopted white |
| Adopted white | `--white` | The white to which the observer is adapted, measured on the sample's scale |
| Adapting luminance | `--la` | Absolute adapting-field luminance `L_A` in cd/m²; it is not the sample's `Y` |
| Background | `--yb` | Relative background luminance `Y_b`, on the white's Y scale |
| Surround | `--surround` | A model induction preset: `average`, `dim`, or `dark` |
| Adaptation degree | `--degree-of-adaptation` | Normally omit it and let the model compute `D`; override only deliberately |

The examples use `Y_b = 20`; that is an example condition, not a hidden tool
default. One white, background, surround, and adaptation degree apply to every
sample in a CSV batch. Use a separate run for each viewing condition.

## Three common input scales

Already on CAM16 Domain-100, where adopted-white `Y = 100`:

```sh
python3 cam16_compare.py \
  --xyz 19.01 20 21.78 \
  --white 95.05 100 108.88 \
  --la 318.31 --yb 20
```

Relative 0-to-1 data, where adopted-white `Y = 1`:

```sh
python3 cam16_compare.py \
  --xyz 0.1901 0.2 0.2178 \
  --white 0.9505 1 1.0888 \
  --la 318.31 --yb 0.2 --normalize-domain100
```

Absolute XYZ, here with adopted-white `Y = 1000 cd/m²`:

```sh
python3 cam16_compare.py \
  --xyz 190.1 200 217.8 \
  --white 950.5 1000 1088.8 \
  --la 318.31 --yb 200 --normalize-domain100
```

These three examples evaluate the same relative stimulus under the same
adapting luminance. `--normalize-domain100` scales the stimulus, white, and
`Y_b` together. It never scales `L_A`: relative tristimulus values and absolute
adapting luminance are separate model inputs.

## Batch input

CSV input requires `X,Y,Z` columns and may include `label`. Column names are
case-insensitive, lines beginning with `#` before the header are skipped as an
export preamble, and `-` reads standard input. After the header, `#` is ordinary
CSV data, so labels such as `#neutral` are preserved.

[`examples/samples.csv`](examples/samples.csv) is a runnable batch:

```csv
label,X,Y,Z
standard-example,19.01,20.00,21.78
amber,45.00,36.00,12.00
blue,20.00,30.00,60.00
equal-tristimulus,33.00,33.00,33.00
```

```sh
python3 cam16_compare.py --input-csv examples/samples.csv \
  --white 95.047 100 108.883 --la 20 --yb 20
```

The last row is achromatic only under an equal-energy white. Run the same file
against `--white 100 100 100` to watch the tool decline to report a hue angle
it cannot resolve:

```sh
python3 cam16_compare.py --input-csv examples/samples.csv \
  --white 100 100 100 --la 20 --yb 20
```

Add `--format csv` to either command to get the full-precision export instead
of the readable table.

The current input contract is comma-delimited. Tab- and semicolon-delimited
exports, column remapping, and per-row viewing conditions are not supported;
convert those files explicitly before running the tool.

## Output formats

| Format | Best for | Shape |
|---|---|---|
| `table` (default) | Reading in a terminal | Up to six significant digits with conditions below |
| `json` | Machine-readable data | Full-precision, nested records by sample and model |
| `csv` | Spreadsheets and data exchange | Full-precision, deliberately wide row per model |

The CSV is wide on purpose. Every row repeats the inputs, evaluated values,
viewing conditions, input-handling choices, tool version, and interpretation
limit. You can therefore understand and recalculate one row without the
original command line or the rest of the file.

Use `--output PATH` to write any format to a file instead of standard output.

## Near-neutral samples and hue

An achromatic stimulus has no hue. A near-neutral stimulus can also have an
opponent direction too small for finite-precision arithmetic to reproduce
reliably. Converting either case with `atan2` would produce a precise-looking
angle whose last digits—or its entire direction—can depend on the runtime.

The readable table therefore displays `h` as `n/a` and its near-zero `C`, `M`,
and `s` as `~0`, followed by a warning. CSV records `hue_resolved` and the
opponent magnitude on every model row. JSON stores the shared
`hue_diagnostics` once per sample. Both machine-readable formats retain the raw
numeric correlates for detailed analysis.

The diagnostic compares the opponent magnitude with the adapted-response
scale. Version 1.2.1 uses a ratio of `1e-8`. A white under materially
incomplete adaptation remains resolved; the rule is numerical, not a blanket
assumption that `XYZ == XYZ_w` has no hue.

This is a reporting boundary, not a perceptual threshold or a promise that
every raw floating-point result has the same last digits in every runtime.
The 1,728-case broad grid stays well clear of the boundary and uses a strict
`1e-11` relative comparison. Separate regression inputs from `1.2e-8` to
`5e-6` exercise the boundary itself: Python and JavaScript must make the same
resolution decision and display the same six significant digits there, under
looser raw-value tolerances that reflect the cancellation-sensitive arithmetic.

For library callers, `compare_models_with_diagnostics()` returns the model
results and the shared hue diagnostic together. `compare_models()` preserves
the simpler correlates-only API.

## Library use

With the repository directory on `PYTHONPATH`, or with `cam16_compare.py`
beside your own script:

```python
from cam16_compare import AVERAGE, compare_models

result = compare_models(
    XYZ=(19.01, 20.00, 21.78),
    XYZ_w=(95.05, 100.00, 108.88),
    L_A=318.31,
    Y_b=20.0,
    surround=AVERAGE,
)
```

## Learn about the models

For the background behind the equations and a visual comparison of their
outputs:

- [the CAM16 equation audit](https://github.com/ferazambuja/imaging-color-measurement/blob/main/reports/cam16-equation-audit.md),
  which reproduces the deterministic consequences of the proposed revision and
  keeps the paper's unfavorable colorfulness result visible.
- [the portfolio comparison](https://ferazambuja.github.io/imaging/#cam16-hellwig-comparator),
  which explains the two formulations in plain language, generates one compact
  example with this tool, and links the result to the equation study.

## Licence and sources

MIT — see [LICENSE](LICENSE). You may copy `cam16_compare.py` into your own
project; keep the notice with it.

[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) lists the equation sources,
the published examples used by the tests, and the optional development
dependency. Nothing is vendored, and the tool imports only the Python standard
library.
