#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""A module-level docstring

Notice the comment above the docstring specifying the encoding.
Docstrings do appear in the bytecode, so you can access this through
the ``__doc__`` attribute. This is also what you'll see if you call
help() on a module or any other Python object.
"""

# compatibility imports
from __future__ import print_function

# general imports
import os
import sys

from random import randint
import math
import networkx as nx

# utils
from utils import import_step, mean
from flatten import AdjacencyGraph, FaceTypes, face_normal, mid_point, face_surface_handle, FaceProperties, get_solid_from_shape, get_largest_solid

# pythonOCC imports
from OCC.Core.gp import gp_Vec
from OCC.Core.BRepAdaptor import BRepAdaptor_Surface

# Assembly tools
from models import Shape, Section
from explode import TreeBuilder, count_parts

import logging
logger = logging.getLogger()


def get_rondom_color():
    """Return a random color string for rendering using pythonOCC"""

    colors = ['WHITE', 'BLUE', 'RED', 'GREEN', 'YELLOW', 'CYAN', 'BLACK', 'ORANGE']
    return colors[randint(0, 7)]


def grouped_graph(graph, base_hash, node_labels=None, node_groups=None):
    """Contract all C2-connected face groups of the C1 component around base.

    Rewritten from the legacy incremental merge, which was edge-order
    dependent (edges arrive in hash-ordered set order, and a C2 edge between
    two not-yet-seen nodes never merged), making tube classification
    nondeterministic per process. Computing connected components of the
    continuity==2 subgraph is order-independent and expresses the same
    intent: one node per multi-face bend / cylinder ring.
    """
    node_labels = node_labels if node_labels is not None else {}
    node_groups = node_groups if node_groups is not None else {}
    # face hashes are address-derived, so anything set-shaped iterates in a
    # process-random order; sort by the deterministic traversal index
    traversal_order = lambda node_hash: graph.C1_faces.nodes[node_hash]["order"]
    component = nx.node_connected_component(graph.C1_faces, base_hash)
    subgraph = graph.C1_faces.subgraph(component)

    c2_graph = nx.Graph()
    c2_graph.add_nodes_from(sorted(component, key=traversal_order))
    c2_graph.add_edges_from(
        (node_a, node_b)
        for node_a, node_b, continuity in subgraph.edges(data="continuity")
        if continuity == 2 and node_a != node_b
    )

    grouped = nx.Graph()
    for group in nx.connected_components(c2_graph):
        members = sorted(group, key=traversal_order)
        leader = base_hash if base_hash in group else members[0]
        grouped.add_node(leader, shapes=members)
        node_groups[leader] = members
        for member in members:
            node_labels[member] = leader

    for node_a, node_b in subgraph.edges():
        leader_a, leader_b = node_labels[node_a], node_labels[node_b]
        # intra-group C1 edges are group-internal, not cycles between groups
        if leader_a != leader_b:
            grouped.add_edge(leader_a, leader_b)

    return grouped, component



def cluster_directions(normals, n_clusters=4, tolerance_deg=2.0):
    """Group near-identical direction vectors; KMeans replacement.

    sklearn's KMeans crashes under pythonocc 7.9 on Windows (threadpoolctl
    fails introspecting OCCT's OpenMP runtime, WinError 0xc06d007f), and was
    overkill anyway: rectangular-tube face normals form exact clusters. Raises
    if the normals do not form exactly n_clusters groups, mirroring the old
    'Could not fit a rectangular section' failure mode.
    """
    cos_tol = math.cos(math.radians(tolerance_deg))
    centers = []   # list of [sum_x, sum_y, sum_z, count]
    labels = []
    for nx_, ny_, nz_ in normals:
        for index, center in enumerate(centers):
            cx, cy, cz, count = center
            norm = math.sqrt(cx * cx + cy * cy + cz * cz) or 1.0
            if (nx_ * cx + ny_ * cy + nz_ * cz) / norm >= cos_tol:
                center[0] += nx_
                center[1] += ny_
                center[2] += nz_
                center[3] += 1
                labels.append(index)
                break
        else:
            centers.append([nx_, ny_, nz_, 1])
            labels.append(len(centers) - 1)

    if len(centers) != n_clusters:
        raise Exception("Expected %d normal directions, found %d" % (n_clusters, len(centers)))

    directions = [[c[0] / c[3], c[1] / c[3], c[2] / c[3]] for c in centers]
    return labels, directions


def get_rectangular_parameters(aag, graph, x_axis=None):
    normals = []
    mid_points = []
    corner_radii = []
    # determinism: the "shapes" member lists come from grouped_graph, which
    # sorts them by traversal order, so normals order and thus the x_axis
    # choice (vectors[0]) are stable across runs
    for node_hash in graph.nodes():
        for shape_hash in graph.nodes[node_hash]["shapes"]:
            node = aag.C1_faces.nodes[shape_hash]

            if node["convexity"] == FaceTypes.PLANAR:
                face = node["shape"]
                normal = face_normal(face)
                normals.append([normal.Coord(1), normal.Coord(2), normal.Coord(3)])

                point = mid_point(face)
                point = gp_Vec(point.Coord(1), point.Coord(2), point.Coord(3))
                mid_points.append(point)

            else:
                corner_radii.append(abs(0.5 / node["curvature"]))

    # Cluster directions
    labels, directions = cluster_directions(normals, n_clusters=4)

    # Normailze vectors
    vectors = []
    for i in range(len(directions)):
        vectors.append(gp_Vec(directions[i][0], directions[i][1], directions[i][2]).Normalized())

    # Split into width and height values
    if not x_axis:
        x_axis = vectors[0]

    width_labels = []
    height_labels = []
    for i in range(len(directions)):
        if x_axis.IsParallel(vectors[i], math.pi/180):
            width_labels.append(i)

        else:
            if len(height_labels) == 0:
                y_axis = vectors[i]
                height_labels.append(i)

            elif y_axis.IsParallel(vectors[i], math.pi/180):
                height_labels.append(i)

            else:
                raise Exception('Could not fit a rectangular section')

    # Determine projected positions along directions
    positions = [[], [], [], []]
    for i in range(len(labels)):
        label = labels[i]

        if label in width_labels:
            position = mid_points[i].Dot(vectors[width_labels[0]])

        else:
            position = mid_points[i].Dot(vectors[height_labels[0]])

        positions[label].append(position)

    # Determine average values
    values = []
    for position in positions:
        values.append(mean(position))

    # Determine extrusion length
    min_extrusion = float("inf")
    max_extrusion = float("-inf")
    z_axis = vectors[width_labels[0]].Crossed(vectors[height_labels[0]])
    for node_hash in graph.nodes():
        for shape_hash in graph.nodes[node_hash]["shapes"]:
            node = aag.C1_faces.nodes[shape_hash]
            face = node["shape"]
            # BRepAdaptor_HSurface was removed in OCCT 7.6; the parameter
            # bounds live directly on the adaptor now
            adaptor = BRepAdaptor_Surface(face)

            points = []
            points.append(adaptor.Value(adaptor.FirstUParameter(), adaptor.FirstVParameter()))
            points.append(adaptor.Value(adaptor.LastUParameter(), adaptor.LastVParameter()))


            for point in points:
                position = gp_Vec(point.XYZ()).Dot(z_axis)

                if position < min_extrusion:
                    min_extrusion = position

                if position > max_extrusion:
                    max_extrusion = position

    extrusion_length = max_extrusion - min_extrusion
    logger.debug("EXTRUSION LENGTH: %0.2f" % (extrusion_length))

    # Compute actual values
    params = {}
    params["width"] = abs(values[width_labels[0]] - values[width_labels[1]])
    params["height"] = abs(values[height_labels[0]] - values[height_labels[1]])
    params["corner_radius"] = mean(corner_radii)
    params["x_axis"] = vectors[width_labels[0]]
    params["y_axis"] = vectors[height_labels[0]]
    params["z_axis"] = params["x_axis"].Crossed(params["y_axis"])
    params["length"] = extrusion_length

    return params


def analyse_shape(aag, display=None):
    # Get hash of the larges face
    section_data = Section()
    # quantized area + traversal-order tie-break: float noise between two
    # near-equal large faces must not flip the base-face choice across runs
    sorted_areas = sorted(aag.areas, key=lambda x: (-round(x[0], 6), aag.C1_faces.nodes[x[1]]["order"]))
    aag.node_labels = {}
    aag.node_groups = {}
    # base_hash = sorted_areas.pop(0)[1]
    base_hash = sorted_areas[0][1]
    base_node = aag.C1_faces.nodes[base_hash]

    # Get graph growing from base
    graph_a, component_a = grouped_graph(aag, base_hash, node_labels=aag.node_labels, node_groups=aag.node_groups)
    num_nodes_a = nx.number_of_nodes(graph_a)
    num_edges_a = nx.number_of_edges(graph_a)
    logger.debug("graph_a: %s nodes and %s edges" % (num_nodes_a, num_edges_a))

    # Find opposite face
    for area, other_base_hash in sorted_areas[1:]:

        if other_base_hash not in aag.node_labels:
            other_node = aag.C1_faces.nodes[other_base_hash]

            if base_node["convexity"].value == -other_node["convexity"].value:
                break

    # Get graph growing from base
    graph_b, component_b = grouped_graph(aag, other_base_hash, node_labels=aag.node_labels, node_groups=aag.node_groups)
    num_nodes_b = nx.number_of_nodes(graph_b)
    num_edges_b = nx.number_of_edges(graph_b)
    logger.debug("graph_b: %s nodes and %s edges" % (num_nodes_b, num_edges_b))

    # Check to determine if shape_data is valid
    # assert (num_nodes_a == num_nodes_b), "Nodes differ on sides"
    # assert (num_edges_a == num_edges_b), "Edges differ on sides"

    # Render initial results
    if display:
        for node_hash in graph_a.nodes():

            for shape_hash in graph_a.nodes[node_hash]["shapes"]:
                node = aag.C1_faces.nodes[shape_hash]

                if node["convexity"] == FaceTypes.PLANAR:
                    display.DisplayShape(node["shape"], update=True, color="blue")
                else:
                    display.DisplayShape(node["shape"], update=True, color="red")


        for node_hash in graph_b.nodes():

            for shape_hash in graph_b.nodes[node_hash]["shapes"]:
                node = aag.C1_faces.nodes[shape_hash]

                if node["convexity"] == FaceTypes.PLANAR:
                    display.DisplayShape(node["shape"], update=True, color="black")
                else:
                    display.DisplayShape(node["shape"], update=True, color="orange")


    # Define shape types
    if num_nodes_a == 1:
        for node_hash in graph_a.nodes():
            for shape_hash in graph_a.nodes[node_hash]["shapes"]:
                node = aag.C1_faces.nodes[shape_hash]
                break

        # Shape is a flat sheet
        if node["convexity"] == FaceTypes.PLANAR:

            for node_hash in graph_b.nodes():
                for shape_hash in graph_b.nodes[node_hash]["shapes"]:
                    node_b = aag.C1_faces.nodes[shape_hash]
                    break

            face_a = node["shape"]
            face_b = node_b["shape"]

            normal_a = face_normal(face_a)
            normal_b = face_normal(face_b)

            if normal_a.IsOpposite(normal_b, math.pi/180):
                logger.debug("[+] shape is a FLAT")
                # shape_data.type = Shape.ShapeTypes.SHEET
                return None

            else:
                logger.debug("[+] shape is a NOT SUPPORTED")
                # shape_data.type = Shape.ShapeTypes.OTHER
                return None

            # shape.type = Shape.ShapeTypes.FLAT

        # Shape is a round tube
        else:
            logger.debug("[+] shape is a ROUND TUBE")

            radii = []
            for node_hash in graph_a.nodes():
                for shape_hash in graph_a.nodes[node_hash]["shapes"]:
                    node = aag.C1_faces.nodes[shape_hash]
                    if node["curvature"]: #TODO: test of curvature is ever zero
                        radii.append(abs(0.5 / node["curvature"]))

            outside_radius = mean(radii)

            radii = []
            for node_hash in graph_b.nodes():
                for shape_hash in graph_b.nodes[node_hash]["shapes"]:
                    node = aag.C1_faces.nodes[shape_hash]
                    if node["curvature"]: #TODO: test of curvature is ever zero
                        radii.append(abs(0.5 / node["curvature"]))

            inside_radius = mean(radii)

            # graph_a describes the inside
            if node["convexity"] == FaceTypes.CONVEX:
                inside_radius, outside_radius = (outside_radius, inside_radius)

            # Determine extrusion length
            z_axis = None
            min_extrusion = float("inf")
            max_extrusion = float("-inf")
            for node_hash in graph_a.nodes():
                for shape_hash in graph_a.nodes[node_hash]["shapes"]:
                    node = aag.C1_faces.nodes[shape_hash]
                    face = node["shape"]
                    adaptor = BRepAdaptor_Surface(face)

                    if not z_axis:
                        surface_handle = face_surface_handle(face)
                        props = FaceProperties(surface_handle)
                        u_direction, v_direction = props.directions()
                        z_axis = gp_Vec(v_direction.XYZ())

                    points = []
                    points.append(adaptor.Value(adaptor.FirstUParameter(), adaptor.FirstVParameter()))
                    points.append(adaptor.Value(adaptor.LastUParameter(), adaptor.LastVParameter()))


                    for point in points:
                        position = gp_Vec(point.XYZ()).Dot(z_axis)

                        if position < min_extrusion:
                            min_extrusion = position

                        if position > max_extrusion:
                            max_extrusion = position

            logger.debug("Extrusion dir: {0}, {1}, {2}".format(z_axis.Coord(1), z_axis.Coord(2), z_axis.Coord(3)))

            extrusion_length = max_extrusion - min_extrusion
            logger.debug("EXTRUSION LENGTH: %0.2f" % (extrusion_length))

            section_data.type = Section.SectionTypes.ROUND
            section_data.inner_radius = min(inside_radius, outside_radius)
            section_data.outer_radius = max(inside_radius, outside_radius)
            section_data.thickness = section_data.outer_radius - section_data.inner_radius
            section_data.width = 2 * section_data.outer_radius
            section_data.height = 2 * section_data.outer_radius
            section_data.length = extrusion_length
            # shape_data.type = Shape.ShapeTypes.ROUND
            # shape_data.inside_radius = inside_radius
            # shape_data.outside_radius = outside_radius
            # shape_data.thickness = outside_radius - inside_radius
            return section_data

    else:
        # shape_data.type = "bent"

        # Shape is a bent sheet
        if num_nodes_a > num_edges_a:
            # shape_data.type = "bent"
            return None


        # Shape is a tube
        else:
            try:
                params_a = get_rectangular_parameters(aag, graph_a)
                params_b = get_rectangular_parameters(aag, graph_b, x_axis=params_a["x_axis"])

                logger.debug("[+] shape is a RECT TUBE")
                section_data.type = Section.SectionTypes.RECTANGULAR
                section_data.inner_radius = min(params_a["corner_radius"], params_b["corner_radius"])
                section_data.outer_radius = max(params_a["corner_radius"], params_b["corner_radius"])
                section_data.thickness = abs(params_a["width"] - params_b["width"]) / 2
                section_data.width = max(params_a["width"], params_b["width"])
                section_data.height = max(params_a["height"], params_b["height"])
                section_data.length = max(params_a["length"], params_b["length"])

                if abs(section_data.width - section_data.height) < 1e-3:
                    section_data.type = Section.SectionTypes.SQUARE

                return section_data

            except:
                logger.debug("[+] shape is a BENT")
                # shape_data.type = "bent"
                return None

    logger.debug("SHOULD NEVER BEEN REACHED. analyse_shape is leaking")



def main(step_path, part_index=None, display=None, repair=True):
    logger.debug("[+] analysing {0}".format(step_path))

    # Try sub shape
    shape = None
    builder = TreeBuilder(step_path)
    if part_index:
        shape = builder.find(part_index)

    # Try assembly
    else:
        tree = builder.compute(display=display)
        quantities = count_parts(tree)

        # Part is an assembly
        if len(quantities) > 1:
            logger.debug("[+] assembly")
            logger.debug(tree)
            logger.debug(quantities)
            return

    # Handle as a single shape
    if not shape:
        shape = import_step(step_path)

    if repair:
        shape = get_solid_from_shape(shape)

    else:
        shape = get_largest_solid(shape)

    # Render initial shape
    if display:
        display.EraseAll()
        display.DisplayShape(shape, update=True, color="white", transparency=0.8)

    aag = AdjacencyGraph(shape)
    aag.full()
    aag.smooth()

    # parameters = {}
    # parameters["area"] = graph.get_area()
    # parameters["volume"] = graph.get_volume()

    # parameters["width"] = graph.get_width()
    # parameters["height"] = graph.get_height()
    # parameters["length"] = graph.get_length()

    shape_properties = analyse_shape(aag, display=display)
    logger.debug(shape_properties)

    # if shape_properties["type"] in ["flat", "bent"]:
    #     parameters["type"] = "SHEET"

    #     if k_factor:
    #         logger.debug("[+] unfolding with k-factor: %s" % (k_factor))
    #         entities, thickness = raw_parse_unfolded_shape(shape, graph=graph, values=values, k_factor=k_factor)

    #     else:
    #         logger.debug("[+] unfolding with standard k-factor: 0.5")
    #         entities, thickness = raw_parse_unfolded_shape(shape, graph=graph, values=values)

    #     parameters["pattern"] = entities
    #     parameters["pattern"]["thickness"] = thickness

    # else:
    #     parameters["type"] = "TUBE"
    #     parameters["section"] = shape_properties

    # logger.debug("[+] done analysing: %s" % (parameters))

    # return jsonify(ShapeSchema().dump(parameters).data)




