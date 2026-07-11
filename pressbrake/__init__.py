"""
Press-brake bend simulation and tooling planning on top of the instapart unfolder.

The package represents a sheet-metal part as a kinematic graph of rigid flat
panels connected by revolute bend hinges (see ``pressbrake.model``).  All
planning-loop geometry is pure numpy/shapely; OpenCASCADE is only touched in
``pressbrake.extract`` (harvesting the graph from the unfolder's
``AdjacencyGraph``) and in optional visualisation branches.

Machine frame convention (used throughout):
    X: along the bend axis / machine width, x in [0, machine.x_length]
    Y: horizontal, positive toward the operator
    Z: up; the active bend line lies at Y=0, Z=0 (die top plane), the punch
       travels in -Z.

Units are millimetres and radians everywhere.

Roadmap beyond this package version (phases 4-8 of the design):
    P4: analytic arc-vs-edge first-contact sweeps inside ``envelope.swept_region``
    P5: 1D segmented tooling placement solver over IntervalSets
    P6: bend-sequence search memoised on FoldState.done_mask with lexicographic
        objectives (setup changes > unique setups > section count > length > mass)
    P7: operation phases (backgauge, handling, tonnage, die-penetration descent)
    P8: exact BREP verification of winning plans via stored face hashes
"""

from pressbrake.model import (
    Panel,
    Bend,
    KinematicGraph,
    FoldState,
    BendAction,
)
from pressbrake.intervals import IntervalSet

__all__ = [
    "Panel",
    "Bend",
    "KinematicGraph",
    "FoldState",
    "BendAction",
    "IntervalSet",
]
