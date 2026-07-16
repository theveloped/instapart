# InstaPart

Reads STEP files, splits assemblies into parts, classifies parts as sheet
metal or tube, and unfolds sheet-metal parts into flat patterns (DXF/JSON/SVG)
using an attributed adjacency graph on top of pythonocc / OpenCASCADE.

Ported to **Python 3.11 + pythonocc-core 7.9** (July 2026). The legacy
Python 2.7 modules that were not ported (Cryptlex licensing, Windows service,
Bysoft BatchUnfold XML, PDF/XLS export via `documents.py`, the stale `aag.py`)
remain in the repo untouched for reference.

## Development environment

```
conda env create -f environment.yml
conda activate instapart3
```

## Usage

```
python instapart.py -h
python instapart.py auto .\examples\parts\SmartPart_01.stp -r -o .\temp
python instapart.py auto .\examples\assy\IEA-000204.stp -r -o .\temp
python instapart.py explode .\examples\assy\EMO-72-07-200.stp -o .\temp
```

Defaults (command, k-factor, export types, thresholds) come from
`settings.json`; CLI arguments override it.

## Benchmark & regression harness

The corpus under `examples/` (127 STEP files: single sheet parts, assemblies,
rolled parts, tubes, known-failing parts) is driven by the harness in
`benchmarks/`. Every file runs in its own subprocess (crash isolation +
per-file timeout) and is validated with physical invariants — most
importantly volume conservation: `|solid_volume − flat_area×thickness| ≤ 2.5%`
with the flat area recomputed independently from the exported DXF — plus
closed-contour/topology checks, DXF audits, bend sanity, filename-encoded
thickness ground truth (rolled parts), and comparison against the committed
golden outputs where they exist.

```
# fast pre-commit subset (~11 files, a slice of every category)
python -m benchmarks smoke

# full corpus; --jobs 1 for timing-quality runs
python -m benchmarks run --jobs 4

# diff the latest run against the blessed baseline (exit 1 on regression)
python -m benchmarks compare

# after intentional changes: freeze observed behavior into the manifest,
# review the git diff, then bless the run as the new baseline
python -m benchmarks freeze latest
python -m benchmarks bless latest

# harness self-tests (no OCC needed)
python -m pytest tests/test_metrics_unit.py
```

- `benchmarks/manifest.yaml` — the committed contract: category, expected
  outcome, frozen part/bend counts and message codes per input file.
- `benchmarks/history.csv` — one committed row per run: the
  performance-over-time record.
- `benchmarks/runs/<timestamp>_<sha>/report.md` — per-run report (failures
  with crash-stage attribution, per-stage timings, slowest files).

Notes for timing runs: use `--jobs 1`, and prefer a clone outside OneDrive —
sync I/O distorts wall times. Expect run-to-run float noise around 1e-13 on
areas (hash-ordered accumulation); structural metrics are deterministic.

## Error codes

See `ERRORS.md` (codes 000–009 embedded in the output JSON). Code 009 is
emitted for machined/CNC solids that fail sheet and tube classification: the
recognizer reports the recognized hole features (through/blind holes,
counterbores, countersinks) on an `OTHER`-typed shape.
