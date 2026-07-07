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
from sklearn.cluster import KMeans

# utils
from utils import import_step, mean
from flatten import AdjacencyGraph, FaceTypes, face_normal, mid_point, face_surface_handle, FaceProperties, get_solid_from_shape, get_largest_solid

# pythonOCC imports
from OCC.gp import gp_Vec
from OCC.BRepAdaptor import BRepAdaptor_Surface, BRepAdaptor_HSurface

# Assembly tools
from models import Shape, Section
from explode import TreeBuilder, count_parts

import logging
logger = logging.getLogger()


def get_rondom_color():
    """Return a random color string for rendering using pythonOCC"""

    colors = ['WHITE', 'BLUE', 'RED', 'GREEN', 'YELLOW', 'CYAN', 'BLACK', 'ORANGE']
    return colors[randint(0, 7)]


def grouped_graph(graph, base_hash, node_labels={}, node_groups={}):
    component = nx.node_connected_component(graph.C1_faces, base_hash)
    grouped_graph = nx.Graph()

    grouped_graph.add_node(base_hash, shapes=[base_hash])
    node_labels[base_hash] = base_hash
    node_groups[base_hash] = [base_hash]

    for node_a, node_b, continuity in graph.C1_faces.edges(nbunch=component, data="continuity"):

        # Avoid error if contracting node with itself (round tube with one face)
        if node_a == node_b:
            continue

        elif node_a in node_labels and node_b in node_labels:
            if continuity == 2:
                node_groups[node_labels[node_a]] += node_groups[node_labels[node_b]]
                grouped_graph.node[node_labels[node_a]]["shapes"] += grouped_graph.node[node_labels[node_b]]["shapes"]
                grouped_graph = nx.contracted_nodes(grouped_graph, node_labels[node_a], node_labels[node_b], self_loops=False)

                for old_nodes in node_groups[node_labels[node_b]]:
                    node_labels[old_nodes] = node_labels[node_a]

            grouped_graph.add_edge(node_labels[node_a], node_labels[node_b])
            continue

        elif node_a in node_labels or node_b in node_labels:
            if continuity == 2:
                if node_a in node_labels:
                    node_labels[node_b] = node_labels[node_a]
                    node_groups[node_labels[node_b]].append(node_b)
                    grouped_graph.node[node_labels[node_b]]["shapes"].append(node_b)
                else:
                    node_labels[node_a] = node_labels[node_b]
                    node_groups[node_labels[node_a]].append(node_a)
                    grouped_graph.node[node_labels[node_a]]["shapes"].append(node_a)
                continue

        if node_a not in node_labels:
            node_labels[node_a] = node_a
            node_groups[node_a] = [node_a]
            grouped_graph.add_node(node_a, shapes=[node_a])

        if node_b not in node_labels:
            node_labels[node_b] = node_b
            node_groups[node_b] = [node_b]
            grouped_graph.add_node(node_b, shapes=[node_b])

        grouped_graph.add_edge(node_labels[node_a], node_labels[node_b])

    return grouped_graph, component



def get_rectangular_parameters(aag, graph, x_axis=None):
    normals = []
    mid_points = []
    corner_radii = []
    for node_hash in graph.nodes():
        for shape_hash in graph.node[node_hash]["shapes"]:
            node = aag.C1_faces.node[shape_hash]

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
    kmeans = KMeans(n_clusters=4)
    labels = kmeans.fit_predict(normals)
    directions = kmeans.cluster_centers_

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
        for shape_hash in graph.node[node_hash]["shapes"]:
            node = aag.C1_faces.node[shape_hash]
            face = node["shape"]
            adaptor = BRepAdaptor_Surface(face)
            adaptor_handle = BRepAdaptor_HSurface(adaptor)

            points = []
            points.append(adaptor.Value(adaptor_handle.FirstUParameter(), adaptor_handle.FirstVParameter()))
            points.append(adaptor.Value(adaptor_handle.LastUParameter(), adaptor_handle.LastVParameter()))


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
    sorted_areas = sorted(aag.areas, key=lambda x: x[0], reverse=True)
    aag.node_labels = {}
    aag.node_groups = {}
    # base_hash = sorted_areas.pop(0)[1]
    base_hash = sorted_areas[0][1]
    base_node = aag.C1_faces.node[base_hash]

    # Get graph growing from base
    graph_a, component_a = grouped_graph(aag, base_hash, node_labels=aag.node_labels, node_groups=aag.node_groups)
    num_nodes_a = nx.number_of_nodes(graph_a)
    num_edges_a = nx.number_of_edges(graph_a)
    logger.debug("graph_a: %s nodes and %s edges" % (num_nodes_a, num_edges_a))

    # Find opposite face
    for area, other_base_hash in sorted_areas[1:]:

        if other_base_hash not in aag.node_labels:
            other_node = aag.C1_faces.node[other_base_hash]

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

            for shape_hash in graph_a.node[node_hash]["shapes"]:
                node = aag.C1_faces.node[shape_hash]

                if node["convexity"] == FaceTypes.PLANAR:
                    display.DisplayShape(node["shape"], update=True, color="blue")
                else:
                    display.DisplayShape(node["shape"], update=True, color="red")


        for node_hash in graph_b.nodes():

            for shape_hash in graph_b.node[node_hash]["shapes"]:
                node = aag.C1_faces.node[shape_hash]

                if node["convexity"] == FaceTypes.PLANAR:
                    display.DisplayShape(node["shape"], update=True, color="black")
                else:
                    display.DisplayShape(node["shape"], update=True, color="orange")


    # Define shape types
    if num_nodes_a == 1:
        for node_hash in graph_a.nodes():
            for shape_hash in graph_a.node[node_hash]["shapes"]:
                node = aag.C1_faces.node[shape_hash]
                break

        # Shape is a flat sheet
        if node["convexity"] == FaceTypes.PLANAR:

            for node_hash in graph_b.nodes():
                for shape_hash in graph_b.node[node_hash]["shapes"]:
                    node_b = aag.C1_faces.node[shape_hash]
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
                for shape_hash in graph_a.node[node_hash]["shapes"]:
                    node = aag.C1_faces.node[shape_hash]
                    if node["curvature"]: #TODO: test of curvature is ever zero
                        radii.append(abs(0.5 / node["curvature"]))

            outside_radius = mean(radii)

            radii = []
            for node_hash in graph_b.nodes():
                for shape_hash in graph_b.node[node_hash]["shapes"]:
                    node = aag.C1_faces.node[shape_hash]
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
                for shape_hash in graph_a.node[node_hash]["shapes"]:
                    node = aag.C1_faces.node[shape_hash]
                    face = node["shape"]
                    adaptor = BRepAdaptor_Surface(face)
                    adaptor_handle = BRepAdaptor_HSurface(adaptor)

                    if not z_axis:
                        surface_handle = face_surface_handle(face)
                        props = FaceProperties(surface_handle)
                        u_direction, v_direction = props.directions()
                        z_axis = gp_Vec(v_direction.XYZ())

                    points = []
                    points.append(adaptor.Value(adaptor_handle.FirstUParameter(), adaptor_handle.FirstVParameter()))
                    points.append(adaptor.Value(adaptor_handle.LastUParameter(), adaptor_handle.LastVParameter()))


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




