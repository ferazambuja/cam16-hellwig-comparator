# Third-party notices

This repository has no third-party code dependencies. `cam16_compare.py`
imports only the Python standard library, and nothing here is vendored.

One optional development dependency exists. `tests/test_cam16_colour_differential.py`
imports [Colour](https://www.colour-science.org/) when it is installed, to
compare this implementation against an independently maintained one. The test
skips when Colour is absent, so installing it is never required to run the
tool or its main test suite. Colour is published under the BSD 3-Clause
licence and is not redistributed here.

## Published numerical examples

The test suite retains two published examples as fixed anchors:

- the standard CAM16 worked example associated with Changjun Li et al.,
  "Comprehensive color solutions: CAM16, CAT16, and CAM16-UCS,"
  *Color Research & Application* 42(6), 2017,
  <https://doi.org/10.1002/col.22131>; and
- the Hellwig 2022 example documented by the Colour project,
  <https://github.com/colour-science/colour/blob/v0.4.7/colour/appearance/hellwig2022.py>.

## Models implemented

The equations are published science, implemented here from their sources:

- Changjun Li et al., "Comprehensive color solutions: CAM16, CAT16, and
  CAM16-UCS," *Color Research & Application* 42(6), 2017,
  <https://doi.org/10.1002/col.22131>.
- Luke Hellwig and Mark D. Fairchild, "Brightness, Lightness, Colorfulness,
  and Chroma in CIECAM02 and CAM16," *Color Research & Application* 47, 2022,
  <https://doi.org/10.1002/col.22792>.

The Hellwig--Fairchild equations are a proposed revision. They are not an
adopted replacement for CAM16, and this tool reports them as a separate,
labelled model rather than folding them into it.

Product and standard names remain the property of their respective owners.
