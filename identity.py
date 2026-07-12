"""Content-derived, persistent, deterministic entity identity.

Produces stable integer ids for solids (and fingerprints for the faces and
edges underneath) from rigid-motion-invariant geometry only: no filename,
path, run order, process state, or memory address enters the digest. The
same physical part therefore gets the same id regardless of which file it
came from, where it sits in an assembly, or when it was processed.

Scheme: quantized invariants are digested with sha1 and truncated to a
60-bit integer (ids stay ints for legacy JSON consumers). SCHEME_VERSION
is mixed into every digest so a future recipe change ("g2") cannot collide
with today's ids.

Known limitations (documented, accepted for v1):
- Mirror-image solids share an id: every ingredient (volume, area,
  principal moments, face fingerprints) is chirality-blind.
- Perfectly symmetric faces share a fingerprint; they are disambiguated by
  a deterministic duplicate rank in traversal order, which may permute
  across re-exports of the model. Such faces are geometrically
  indistinguishable, so any assignment is equally correct.
- A value sitting exactly on a quantization bucket boundary can flip the
  digest under float noise (~1e-9 relative observed; buckets are 1e-6
  relative, three orders of magnitude wider). This affects only the id,
  never geometry output. REL_TOL below is the single dial.

OCC imports are function-local so this module imports cleanly in
environments without pythonocc (the OCC-free CI unit job).
"""

import hashlib
import logging

logger = logging.getLogger()

SCHEME_VERSION = "g1"
REL_TOL = 1e-6      # relative quantization step vs. characteristic size
FLOOR = 1e-6        # absolute minimum step (mm-based units)


# ---------------------------------------------------------------------------
# Pure helpers (no OCC)
# ---------------------------------------------------------------------------

def step_for(scale, kind="length"):
    """Quantization step for a quantity of the given dimensionality.

    scale is the solid's characteristic size (mm); areas scale with its
    square and volumes with its cube so the relative resolution is uniform.
    """
    exponent = {"length": 1, "area": 2, "volume": 3}[kind]
    return max(REL_TOL * (scale ** exponent), FLOOR)


def quantize(value, step):
    """Map a float onto an integer bucket index of the given step."""
    if value is None:
        return None
    return int(round(value / step))


def stable_digest(*parts):
    """60-bit integer digest of the canonical repr of the given parts.

    Parts must be built from ints, strings, None, and (nested) tuples/lists
    of those — no raw floats (quantize first), so the repr is canonical.
    """
    payload = repr((SCHEME_VERSION,) + tuple(_canonical(p) for p in parts))
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()
    return int(digest[:15], 16)


def _canonical(part):
    if isinstance(part, (list, tuple)):
        return tuple(_canonical(p) for p in part)
    if isinstance(part, float):
        raise TypeError("raw float in digest input; quantize it first: %r" % part)
    return part


def assign_dup_ranks(fingerprints):
    """Disambiguate equal fingerprints with a deterministic duplicate rank.

    Returns [(fingerprint, rank), ...] preserving input (traversal) order:
    the n-th occurrence of an identical fingerprint gets rank n-1.
    """
    seen = {}
    ranked = []
    for fingerprint in fingerprints:
        rank = seen.get(fingerprint, 0)
        seen[fingerprint] = rank + 1
        ranked.append((fingerprint, rank))
    return ranked


# ---------------------------------------------------------------------------
# OCC-backed fingerprints (imports kept function-local)
# ---------------------------------------------------------------------------

def _gprops_surface(shape):
    from OCC.Core.GProp import GProp_GProps
    from OCC.Core.BRepGProp import brepgprop
    props = GProp_GProps()
    brepgprop.SurfaceProperties(shape, props)
    return props


def _gprops_volume(shape):
    from OCC.Core.GProp import GProp_GProps
    from OCC.Core.BRepGProp import brepgprop
    props = GProp_GProps()
    brepgprop.VolumeProperties(shape, props)
    return props


def _gprops_linear(shape):
    from OCC.Core.GProp import GProp_GProps
    from OCC.Core.BRepGProp import brepgprop
    props = GProp_GProps()
    brepgprop.LinearProperties(shape, props)
    return props


def solid_centroid(solid):
    """Center of mass of the solid as a gp_Pnt."""
    return _gprops_volume(solid).CentreOfMass()


def face_fingerprint(face, centroid, scale):
    """Rigid-motion-invariant fingerprint tuple for one face.

    (surface type name, quantized area, quantized centroid distance to the
    solid centroid, quantized principal radii for non-planar faces)
    """
    from OCC.Core.BRepAdaptor import BRepAdaptor_Surface

    surface_type = BRepAdaptor_Surface(face).GetType()
    props = _gprops_surface(face)
    area = abs(props.Mass())
    distance = props.CentreOfMass().Distance(centroid)

    radii = None
    try:
        adaptor = BRepAdaptor_Surface(face)
        # cylinders/spheres/tori expose a defining radius; quantize it so
        # equal-radius bends fingerprint identically
        if adaptor.GetType() == 1:      # GeomAbs_Cylinder
            radii = quantize(adaptor.Cylinder().Radius(), step_for(scale))
        elif adaptor.GetType() == 4:    # GeomAbs_Sphere
            radii = quantize(adaptor.Sphere().Radius(), step_for(scale))
        elif adaptor.GetType() == 5:    # GeomAbs_Torus
            torus = adaptor.Torus()
            radii = (quantize(torus.MajorRadius(), step_for(scale)),
                     quantize(torus.MinorRadius(), step_for(scale)))
    except Exception:
        radii = None

    return (int(surface_type),
            quantize(area, step_for(scale, "area")),
            quantize(distance, step_for(scale)),
            radii)


def edge_fingerprint(edge, centroid, scale):
    """Rigid-motion-invariant fingerprint tuple for one edge.

    (curve type, quantized length, quantized centroid distance to the solid
    centroid)
    """
    from OCC.Core.BRepAdaptor import BRepAdaptor_Curve

    curve_type = BRepAdaptor_Curve(edge).GetType()
    props = _gprops_linear(edge)
    length = abs(props.Mass())
    distance = props.CentreOfMass().Distance(centroid)

    return (int(curve_type),
            quantize(length, step_for(scale)),
            quantize(distance, step_for(scale)))


def solid_content_id(solid):
    """Persistent content-derived id for a solid, or None on failure.

    Ingredients (all rigid-motion invariant): quantized volume, total
    surface area, sorted principal moments of inertia, face and edge
    counts, and the sorted multiset of face fingerprints.
    """
    try:
        from OCC.Core.TopExp import TopExp_Explorer
        from OCC.Core.TopAbs import TopAbs_FACE, TopAbs_EDGE
        from OCC.Core.TopoDS import topods

        volume_props = _gprops_volume(solid)
        volume = abs(volume_props.Mass())
        centroid = volume_props.CentreOfMass()
        scale = max(abs(volume) ** (1.0 / 3.0), 1.0)

        area = abs(_gprops_surface(solid).Mass())
        moments = sorted(volume_props.PrincipalProperties().Moments())

        fingerprints = []
        explorer = TopExp_Explorer(solid, TopAbs_FACE)
        while explorer.More():
            fingerprints.append(face_fingerprint(topods.Face(explorer.Current()), centroid, scale))
            explorer.Next()

        edge_count = 0
        explorer = TopExp_Explorer(solid, TopAbs_EDGE)
        while explorer.More():
            edge_count += 1
            explorer.Next()

        # moments scale as length^5: quantize against volume^(5/3)
        moment_step = max(REL_TOL * (scale ** 5), FLOOR)

        return stable_digest(
            quantize(volume, step_for(scale, "volume")),
            quantize(area, step_for(scale, "area")),
            tuple(quantize(m, moment_step) for m in moments),
            len(fingerprints),
            edge_count,
            tuple(sorted(fingerprints, key=lambda f: repr(f))),
        )

    except Exception:
        logger.warning("Content id computation failed", exc_info=True)
        return None
