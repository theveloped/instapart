import math

import numpy as np
import pytest

from pressbrake import machine as machine_mod
from pressbrake.machine import CatalogueError, load_dies, load_machine, load_punches
from pressbrake.model import polygon_area


def test_load_demo_machine():
    machine = load_machine()
    assert machine.x_length == pytest.approx(3100.0)
    assert polygon_area(machine.ram_profile) > 0
    assert polygon_area(machine.table_profile) > 0
    # ram bottom edge at local z=0, table top edge at local z=0
    assert np.min(machine.ram_profile[:, 1]) == pytest.approx(0.0)
    assert np.max(machine.table_profile[:, 1]) == pytest.approx(0.0)


def test_load_demo_punches():
    punches = load_punches()
    assert {"P.88.R08", "P.88.GN", "P.30.R08", "P.RAD10"} <= set(punches)
    straight = punches["P.88.R08"]
    assert straight.kind == "punch"
    assert straight.tip_angle == pytest.approx(math.radians(88))
    # origin at the tip
    assert np.min(straight.profile[:, 1]) == pytest.approx(0.0)
    assert straight.sections
    # the gooseneck relief window: mid-height material stops at y=-2 while
    # the straight blade spans the full +/-10
    gooseneck = punches["P.88.GN"]
    mid_band = gooseneck.profile[
        (gooseneck.profile[:, 1] > 28) & (gooseneck.profile[:, 1] < 96)]
    assert np.max(mid_band[:, 0]) == pytest.approx(-2.0)


def test_load_demo_dies():
    dies = load_dies()
    die = dies["D.V12.88"]
    assert die.kind == "die"
    assert die.v_width == pytest.approx(12.0)
    # V groove bottom (the profile point on the V centre line) depth matches
    # (v/2)/tan(v_angle/2)
    depth = (die.v_width / 2.0) / math.tan(die.v_angle / 2.0)
    center_points = die.profile[np.abs(die.profile[:, 0]) < 1e-9]
    assert np.max(center_points[:, 1]) == pytest.approx(-depth, abs=0.01)
    assert die.fits_thickness(1.5)
    assert not die.fits_thickness(3.0)


def test_transformed_profiles_thickness_shift():
    punches, dies = load_punches(), load_dies()
    thickness = 2.0
    punch_profile = punches["P.88.R08"].transformed_profile(thickness)
    die_profile = dies["D.V12.88"].transformed_profile(thickness)
    # punch tip on the sheet top (+t/2 at phi=0), die top on the sheet
    # bottom (-t/2)
    assert np.min(punch_profile[:, 1]) == pytest.approx(thickness / 2.0)
    assert np.max(die_profile[:, 1]) == pytest.approx(-thickness / 2.0)
    # at the final bend parameter the tip rides at the inner-corner height
    lifted = punches["P.88.R08"].transformed_profile(thickness, max_phi=math.pi / 2)
    assert np.min(lifted[:, 1]) == pytest.approx(
        (thickness / 2.0) / math.cos(math.pi / 4))


def test_machine_body_positioning():
    machine, punches, dies = load_machine(), load_punches(), load_dies()
    thickness = 2.0
    ram = machine.ram_transformed(punches["P.88.R08"], thickness)
    table = machine.table_transformed(dies["D.V12.88"], thickness)
    assert np.min(ram[:, 1]) == pytest.approx(thickness / 2.0 + 120.0)
    assert np.max(table[:, 1]) == pytest.approx(-thickness / 2.0 - 60.0)


def test_fits_angle():
    punches = load_punches()
    # an 88 deg punch can form up to 92 deg of fold (included angle >= 88)
    assert punches["P.88.R08"].fits_angle(math.radians(90))
    assert not punches["P.88.R08"].fits_angle(math.radians(120))
    assert punches["P.30.R08"].fits_angle(math.radians(120))


def test_invalid_profile_rejected(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "punches:\n"
        "  - id: BAD\n"
        "    tip_angle_deg: 88.0\n"
        "    height: 100.0\n"
        "    profile: [[0.0, 0.0], [10.0, 10.0], [-10.0, 10.0], [10.0, 0.1]]\n"
    )
    with pytest.raises(CatalogueError):
        load_punches(str(bad))


def test_schema_validation(tmp_path):
    bad = tmp_path / "bad_machine.yaml"
    bad.write_text("machine:\n  name: incomplete\n  x_length: -5\n")
    with pytest.raises(CatalogueError):
        machine_mod.load_machine(str(bad))
