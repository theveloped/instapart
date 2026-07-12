"""Filename independence of persistent content ids (needs OCC).

The same geometry processed under two different filenames must yield the
same shape ids: nothing about the input path may leak into identity.
"""

import json
import shutil
from pathlib import Path

import pytest

pytestmark = pytest.mark.smoke

REPO_ROOT = Path(__file__).resolve().parent.parent
INPUT_STEP = REPO_ROOT / "examples/parts/SmartPart_01.stp"


def _shape_ids(json_path):
    with open(json_path, encoding="utf-8") as fh:
        job = json.load(fh)
    ids = []

    def walk(node):
        if not isinstance(node, dict):
            return
        for shape in node.get("shapes") or []:
            ids.append(shape.get("id"))
        for comp in node.get("components") or []:
            walk(comp)

    walk(job.get("tree") or {})
    return ids


def _run_auto(step_path, outdir):
    from auto import main as auto_main
    outdir.mkdir(parents=True, exist_ok=True)
    auto_main(str(step_path), str(outdir), repair=True, export_stp=False)
    json_path = outdir / (step_path.stem + ".json")
    assert json_path.is_file(), "no output JSON for %s" % step_path
    return json_path


def test_shape_ids_independent_of_filename(tmp_path):
    original = tmp_path / "in_a" / INPUT_STEP.name
    renamed = tmp_path / "in_b" / "renamed_xyz_123.stp"
    original.parent.mkdir()
    renamed.parent.mkdir()
    shutil.copy2(INPUT_STEP, original)
    shutil.copy2(INPUT_STEP, renamed)

    ids_a = _shape_ids(_run_auto(original, tmp_path / "out_a"))
    ids_b = _shape_ids(_run_auto(renamed, tmp_path / "out_b"))

    assert ids_a, "no shapes extracted"
    assert all(i is not None for i in ids_a), "shape without content id: %s" % ids_a
    # same geometry, different filename and directory -> identical ids
    # (this also proves same-process determinism: two full pipeline runs)
    assert ids_a == ids_b
