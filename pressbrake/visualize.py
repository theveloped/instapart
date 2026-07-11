"""
Matplotlib debug visualisation: folded 3D states, machine-frame YZ
cross-sections and X-interval strip charts.

Import is kept lazy-friendly: matplotlib is only required when a plot
function is actually called (headless Agg backend by default).
"""

import numpy as np


def _pyplot():
    import matplotlib
    matplotlib.use("Agg", force=False)
    import matplotlib.pyplot as plt
    return plt


def plot_folded(graph, theta, active_bend=None, ax=None, title=None):
    """
    3D view of the part at hinge angles ``theta``.  Panels of the active
    bend's moving subtree are highlighted.
    """
    plt = _pyplot()
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection

    if ax is None:
        figure = plt.figure(figsize=(7, 6))
        ax = figure.add_subplot(111, projection="3d")

    moving_mask = 0
    if active_bend is not None:
        moving_mask = graph.bends[active_bend].moving_mask

    vertices = graph.panel_vertices(np.asarray(theta, dtype=float))
    all_points = np.vstack(vertices)
    for panel, verts in zip(graph.panels, vertices):
        moving = bool(moving_mask >> panel.id & 1)
        collection = Poly3DCollection(
            [verts],
            alpha=0.75,
            facecolor="#ff8c42" if moving else "#4a90d9",
            edgecolor="black",
            linewidth=0.8,
        )
        ax.add_collection3d(collection)

    _equalize_3d(ax, all_points)
    ax.set_xlabel("x [mm]")
    ax.set_ylabel("y [mm]")
    ax.set_zlabel("z [mm]")
    if title:
        ax.set_title(title)
    return ax


def plot_fold_sequence(graph, steps=6, path=None):
    """
    Grid of intermediate fold states from flat to fully folded.
    """
    plt = _pyplot()
    figure = plt.figure(figsize=(4 * steps, 4))
    targets = np.array([bend.angle_target for bend in graph.bends])
    for index, fraction in enumerate(np.linspace(0.0, 1.0, steps)):
        ax = figure.add_subplot(1, steps, index + 1, projection="3d")
        plot_folded(graph, targets * fraction, ax=ax,
                    title="{:.0f}%".format(100 * fraction))
    figure.tight_layout()
    if path:
        figure.savefig(path, dpi=110)
        plt.close(figure)
    return figure


def plot_machine_yz(machine=None, punch=None, die=None, slices=None, swept=None,
                    ax=None, title=None, path=None):
    """
    Machine-frame YZ cross-section: tool/machine profiles plus optional part
    slice segments/polygons at a chosen X.

    ``slices`` is a list of (N,2) YZ polygons (part material), ``swept`` an
    optional shapely geometry (rendered as its boundary).
    """
    plt = _pyplot()
    figure = None
    if ax is None:
        figure, ax = plt.subplots(figsize=(7, 7))

    def draw(polygon, color, label):
        polygon = np.asarray(polygon)
        closed = np.vstack([polygon, polygon[:1]])
        ax.fill(closed[:, 0], closed[:, 1], color=color, alpha=0.4, label=label)
        ax.plot(closed[:, 0], closed[:, 1], color=color, linewidth=1.0)

    if machine is not None:
        draw(machine.ram_profile, "#888888", "ram")
        draw(machine.table_profile, "#555555", "table")
    if punch is not None:
        draw(punch.transformed_profile(), "#c0392b", "punch " + punch.id)
    if die is not None:
        draw(die.transformed_profile(), "#27ae60", "die " + die.id)
    for polygon in slices or []:
        draw(polygon, "#2c3e50", None)
    if swept is not None:
        _draw_shapely_boundary(ax, swept, "#e67e22")

    ax.axhline(0.0, color="black", linewidth=0.5)
    ax.axvline(0.0, color="black", linewidth=0.5)
    ax.set_aspect("equal")
    ax.set_xlabel("y [mm]")
    ax.set_ylabel("z [mm]")
    ax.legend(loc="upper right", fontsize=8)
    if title:
        ax.set_title(title)
    if path and figure is not None:
        figure.savefig(path, dpi=110)
        plt.close(figure)
    return ax


def plot_envelope_strip(envelopes, x_range, path=None, title=None):
    """
    Strip chart of REQUIRED (green) / OPTIONAL (grey) / FORBIDDEN (red) X
    intervals, one row per envelope.  ``envelopes`` is a list of
    (label, CollisionEnvelope).
    """
    plt = _pyplot()
    figure, ax = plt.subplots(figsize=(10, 0.9 * max(len(envelopes), 2) + 1))

    for row, (label, envelope) in enumerate(envelopes):
        y = len(envelopes) - 1 - row
        ax.broken_barh(_spans(envelope.optional), (y + 0.15, 0.7),
                       facecolors="#d0d0d0")
        ax.broken_barh(_spans(envelope.required), (y + 0.15, 0.7),
                       facecolors="#2ecc71")
        ax.broken_barh(_spans(envelope.forbidden), (y + 0.15, 0.7),
                       facecolors="#e74c3c", alpha=0.85)
        marker = "ok" if envelope.feasible else "INFEASIBLE"
        ax.text(x_range[1] + 0.01 * (x_range[1] - x_range[0]), y + 0.5,
                "{} [{}]".format(label, marker), va="center", fontsize=8)

    ax.set_xlim(*x_range)
    ax.set_ylim(0, len(envelopes))
    ax.set_yticks([])
    ax.set_xlabel("machine X [mm]")
    if title:
        ax.set_title(title)
    figure.tight_layout()
    if path:
        figure.savefig(path, dpi=110, bbox_inches="tight")
        plt.close(figure)
    return figure


def _spans(interval_set):
    return [(start, end - start) for start, end in interval_set.to_pairs()]


def _draw_shapely_boundary(ax, geometry, color):
    from shapely.geometry import MultiPolygon, Polygon

    if isinstance(geometry, Polygon):
        polygons = [geometry]
    elif isinstance(geometry, MultiPolygon):
        polygons = list(geometry.geoms)
    else:
        polygons = [g for g in getattr(geometry, "geoms", []) if isinstance(g, Polygon)]
    for polygon in polygons:
        xy = np.asarray(polygon.exterior.coords)
        ax.plot(xy[:, 0], xy[:, 1], color=color, linewidth=1.2, linestyle="--")


def _equalize_3d(ax, points):
    center = (points.max(axis=0) + points.min(axis=0)) / 2.0
    radius = max(float(np.max(points.max(axis=0) - points.min(axis=0))) / 2.0, 1.0)
    ax.set_xlim(center[0] - radius, center[0] + radius)
    ax.set_ylim(center[1] - radius, center[1] + radius)
    ax.set_zlim(center[2] - radius, center[2] + radius)
