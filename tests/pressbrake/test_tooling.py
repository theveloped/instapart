import math
from dataclasses import dataclass, field

import pytest

from pressbrake import tooling
from pressbrake.intervals import IntervalSet
from pressbrake.machine import CatalogueSection, ToolProfile


def make_tool(lengths_counts, tool_id="T", kind="punch", mass=None):
    profile = [[0.0, 0.0], [5.0, 10.0], [5.0, 50.0], [-5.0, 50.0], [-5.0, 10.0]]
    tool = ToolProfile(
        id=tool_id, kind=kind, profile=profile, height=50.0,
        tip_angle=math.radians(88), mass_kg_per_m=mass,
        sections=[CatalogueSection(length, count)
                  for length, count in lengths_counts.items()],
    )
    return tool


def solve(tool, required, forbidden=(), domain=(-50.0, 200.0), machine_x=None):
    return tooling.solve_tool_placement(
        tool, IntervalSet(required), IntervalSet(forbidden), domain,
        machine_x_length=machine_x)


def test_exact_cover_single_section():
    placement = solve(make_tool({100.0: 1}), [(0, 100)])
    assert placement.feasible
    assert placement.section_count == 1
    assert placement.total_length == pytest.approx(100.0)
    assert len(placement.runs) == 1
    assert placement.runs[0].x_start == pytest.approx(0.0)
    assert placement.installed().contains(IntervalSet([(0, 100)]))


def test_min_count_beats_min_length():
    # span 35: 15+20 (2 sections, 35mm) beats 10+10+15 (3 sections)
    placement = solve(make_tool({10.0: 4, 15.0: 4, 20.0: 4}), [(0, 35)])
    assert placement.feasible
    assert placement.section_count == 2
    assert placement.total_length == pytest.approx(35.0)


def test_count_first_lexicographic():
    # span 50: one 50 beats two 25s even though lengths tie
    placement = solve(make_tool({50.0: 1, 25.0: 2}), [(0, 50)])
    assert placement.feasible
    assert placement.section_count == 1
    assert placement.runs[0].sections[0].length == pytest.approx(50.0)


def test_overshoot_when_room_infeasible_when_tight():
    # span 30 but only a 50mm section in stock
    roomy = solve(make_tool({50.0: 1}), [(0, 30)])
    assert roomy.feasible
    assert roomy.total_length == pytest.approx(50.0)
    # allowed region only 40 wide -> the 50 cannot fit
    tight = solve(make_tool({50.0: 1}), [(0, 30)],
                  forbidden=[(-100, -5), (35, 100)], domain=(-100, 100))
    assert not tight.feasible
    assert "no section combination" in tight.reason


def test_quantity_limits():
    placement = solve(make_tool({40.0: 1, 25.0: 2}), [(0, 80)])
    assert placement.feasible
    assert placement.section_count == 3
    assert placement.total_length == pytest.approx(90.0)

    placement = solve(make_tool({40.0: 2}), [(0, 80)])
    assert placement.feasible
    assert placement.section_count == 2
    assert placement.total_length == pytest.approx(80.0)

    # not enough stock at all
    placement = solve(make_tool({40.0: 1}), [(0, 80)])
    assert not placement.feasible


def test_forbidden_gap_splits_runs():
    tool = make_tool({40.0: 2, 100.0: 1})
    split = solve(tool, [(0, 40), (60, 100)], forbidden=[(45, 55)])
    assert split.feasible
    assert len(split.runs) == 2
    assert split.section_count == 2
    for run in split.runs:
        assert IntervalSet([(45, 55)]).intersect(
            IntervalSet([(run.x_start, run.x_end)])).is_empty()

    # without the forbidden gap one 100mm section covers both clusters
    merged = solve(tool, [(0, 40), (60, 100)])
    assert merged.feasible
    assert merged.section_count == 1
    assert merged.runs[0].length == pytest.approx(100.0)


def test_required_meets_forbidden_rejected():
    placement = solve(make_tool({100.0: 1}), [(0, 100)], forbidden=[(40, 50)])
    assert not placement.feasible
    assert "forbidden" in placement.reason


def test_machine_width_post_check():
    tool = make_tool({100.0: 2})
    placement = solve(tool, [(0, 90), (1900, 1990)], domain=(-100, 2100),
                      machine_x=1000.0)
    assert not placement.feasible
    assert "wider than the machine" in placement.reason


def test_mass_proxy_and_objective():
    with_mass = solve(make_tool({50.0: 1}, mass=10.0), [(0, 50)])
    assert with_mass.total_mass == pytest.approx(0.5)   # 10 kg/m * 50 mm
    without_mass = solve(make_tool({50.0: 1}), [(0, 50)])
    assert without_mass.total_mass == pytest.approx(50.0)  # length proxy
    assert with_mass.objective[0] == without_mass.objective[0] == 1


def test_empty_required_trivially_feasible():
    placement = solve(make_tool({50.0: 1}), [])
    assert placement.feasible
    assert placement.section_count == 0


# --- solve_setup -------------------------------------------------------------


@dataclass
class FakeEnvelope:
    required: IntervalSet
    forbidden_punch: IntervalSet = field(default_factory=IntervalSet)
    forbidden_die: IntervalSet = field(default_factory=IntervalSet)
    forbidden_machine: IntervalSet = field(default_factory=IntervalSet)
    x_range: tuple = (0.0, 100.0)


def test_solve_setup_compatible_union():
    punch = make_tool({100.0: 1, 40.0: 2}, tool_id="P", kind="punch")
    die = make_tool({100.0: 1, 40.0: 2}, tool_id="D", kind="die")
    envelopes = [
        FakeEnvelope(required=IntervalSet([(0, 40)])),
        FakeEnvelope(required=IntervalSet([(60, 100)])),
    ]
    setup = tooling.solve_setup(envelopes, punch, die)
    assert setup.feasible
    assert setup.punch_placement.section_count == 1   # one 100 covers both
    assert setup.die_placement.section_count == 1
    assert setup.objective[0] == 2


def test_solve_setup_conflicting_union(monkeypatch):
    punch = make_tool({100.0: 1}, tool_id="P")
    die = make_tool({100.0: 1}, tool_id="D", kind="die")
    envelopes = [
        FakeEnvelope(required=IntervalSet([(0, 100)])),
        FakeEnvelope(required=IntervalSet([(150, 200)]),
                     forbidden_punch=IntervalSet([(20, 80)]),
                     x_range=(0.0, 250.0)),
    ]
    calls = []
    monkeypatch.setattr(tooling, "solve_tool_placement",
                        lambda *a, **k: calls.append(1))
    setup = tooling.solve_setup(envelopes, punch, die)
    assert not setup.feasible
    assert "union required meets union forbidden" in setup.reason
    # the fast test must trip before any placement work
    assert not calls


def test_solve_setup_machine_interference():
    punch = make_tool({100.0: 1}, tool_id="P")
    die = make_tool({100.0: 1}, tool_id="D", kind="die")
    envelopes = [FakeEnvelope(required=IntervalSet([(0, 100)]),
                              forbidden_machine=IntervalSet([(10, 20)]))]
    setup = tooling.solve_setup(envelopes, punch, die)
    assert not setup.feasible
    assert "machine" in setup.reason


def test_setup_signature_distinguishes_layouts():
    punch = make_tool({50.0: 2}, tool_id="P")
    die = make_tool({50.0: 2}, tool_id="D", kind="die")
    setup_a = tooling.solve_setup(
        [FakeEnvelope(required=IntervalSet([(0, 50)]))], punch, die)
    setup_b = tooling.solve_setup(
        [FakeEnvelope(required=IntervalSet([(0, 100)]))], punch, die)
    assert setup_a.feasible and setup_b.feasible
    assert setup_a.signature != setup_b.signature
