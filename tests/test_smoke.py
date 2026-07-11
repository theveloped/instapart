"""Pytest wrapper for the smoke subset: pytest tests -m smoke.

Each test runs one manifest smoke entry through the subprocess-isolated
worker and asserts the invariant verdict. Requires the instapart3 env (OCC).
"""

import pytest

from benchmarks import manifest as manifest_mod

pytestmark = pytest.mark.smoke


def _smoke_entries():
    try:
        manifest = manifest_mod.load()
    except FileNotFoundError:
        return []
    return [e for e in manifest["files"] if e.get("smoke")]


@pytest.fixture(scope="session")
def smoke_run(tmp_path_factory):
    """One shared run over all smoke files (subprocess isolation per file)."""
    from benchmarks import runner
    entries = _smoke_entries()
    if not entries:
        pytest.skip("no manifest")
    run_dir, meta, results = runner.execute(entries, jobs=2, label="_pytest-smoke")
    return {r["path"]: r for r in results}


def _smoke_params():
    entries = _smoke_entries()
    if not entries:
        # Surface a missing manifest as a visible skip instead of an empty
        # parametrize list, which would silently collect zero tests.
        return [pytest.param(None, id="manifest-missing",
                             marks=pytest.mark.skip(reason="no smoke entries (benchmarks/manifest.yaml missing?)"))]
    return [pytest.param(e, id=e["path"]) for e in entries]


@pytest.mark.parametrize("entry", _smoke_params())
def test_smoke_file(entry, smoke_run):
    record = smoke_run.get(entry["path"])
    assert record is not None, "no result for %s" % entry["path"]
    if entry.get("expected") == "known_failure":
        assert record["status"] in ("known_failure", "pass", "warn")
    else:
        failing = [c for c in record.get("checks") or [] if c["status"] == "fail"]
        assert record["status"] in ("pass", "warn"), (
            "status=%s failing_checks=%s error=%s"
            % (record["status"],
               [(c["name"], c.get("detail")) for c in failing],
               (record.get("error") or "")[-300:]))
