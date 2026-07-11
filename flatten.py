#!/usr/bin/env python

# compatibility imports
from __future__ import print_function

# import sys,os
# app_module_path = 'app_module'
# if sys.platform == 'win32':
#     casroot_path = 'casroot'
#     if os.path.exists(casroot_path):
#         os.environ['CASROOT'] = casroot_path


import os
import sys
import math
# import numpy
import traceback
import networkx as nx
from enum import Enum

from OCC.Core.IFSelect import IFSelect_RetDone
from OCC.Core.ShapeFix import ShapeFix_Shape, ShapeFix_Wire, ShapeFix_Edge
from OCC.Core.ShapeAnalysis import ShapeAnalysis_WireOrder
from OCC.Core.GCPnts import GCPnts_AbscissaPoint
from OCC.Core.CPnts import CPnts_UniformDeflection
from OCC.Core.GeomAdaptor import GeomAdaptor_Curve
from OCC.Core.GeomProjLib import geomprojlib
from OCC.Core.BRep import BRep_Tool
from OCC.Core.GeomAbs import GeomAbs_G1
from OCC.Core.IFSelect import IFSelect_ItemsByEntity

from OCC.Core.Bnd import Bnd_Box
from OCC.Core.BRepBndLib import brepbndlib
from OCC.Core.BRepBuilderAPI import (BRepBuilderAPI_Transform,
                                BRepBuilderAPI_GTransform,
                                BRepBuilderAPI_MakeEdge,
                                BRepBuilderAPI_MakeWire,
                                BRepBuilderAPI_MakeFace,
                                BRepBuilderAPI_MakeVertex,
                                BRepBuilderAPI_Sewing,
                                BRepBuilderAPI_MakeSolid)

from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakePrism
from OCC.Core.STEPControl import STEPControl_Reader
from OCC.Core.TopAbs import (TopAbs_VERTEX, TopAbs_EDGE, TopAbs_FACE, TopAbs_WIRE,
                        TopAbs_SHELL, TopAbs_SOLID, TopAbs_COMPOUND, TopAbs_COMPSOLID)
from OCC.Core.TopoDS import topods
from OCC.Core.GProp import GProp_GProps
from OCC.Core.BRepGProp import brepgprop

from OCC.Core.gp import (gp_Trsf, gp_Ax1, gp_Pln,
                    gp_Ax3, gp_GTrsf, gp_Vec,
                    gp_Dir, gp_Pnt, gp_Origin,
                    gp_DZ, gp_Ax2d, gp_Pnt2d,
                    gp_Dir2d, gp_XY,
                    gp_Vec2d, gp_DX, gp_Lin,
                    gp_GTrsf2d, gp_Mat, gp_Trsf2d,
                    gp_Mat2d, gp_Ax2)

from OCC.Core.BRep import BRep_Tool
from OCC.Core.ShapeAnalysis import ShapeAnalysis_Surface, ShapeAnalysis_Curve,  ShapeAnalysis_Edge
from OCC.Core.GeomLProp import GeomLProp_SLProps

from OCC.Core.BRepAdaptor import BRepAdaptor_Curve
from OCC.Core.BRepLProp import BRepLProp_CLProps
from OCC.Core.GeomLib import GeomLib_IsPlanarSurface, geomlib

from OCC.Core.BRepTools import breptools
from OCC.Core.BRepAdaptor import BRepAdaptor_Surface

from OCC.Core.TopExp import TopExp_Explorer, topexp
from OCC.Core.Geom import Geom_Line
from OCC.Core.GeomAPI import GeomAPI_IntCS, GeomAPI_ProjectPointOnCurve
from OCC.Core.Geom2dAPI import Geom2dAPI_ProjectPointOnCurve

from OCC.Core.BRepAlgo import BRepAlgo_NormalProjection

from cycad import Pattern, Entity
from models import Loop, Shape, Feature
from bounding_box import get_boundingbox_dimensions

# utils
from utils import import_step, get_area, get_volume, get_shape_solids, redirect_stdout, suppress_stdout_stderr, shape_hash

import logging
logger = logging.getLogger()

#===========================================================================
# Global default settings
#===========================================================================
TOLLERANCE = 1e-6

#===========================================================================
# Helper functions from PythonOCC-Utils
#===========================================================================
def fix_shape(shp, tolerance=1e-3):
    fix = ShapeFix_Shape(shp)
    fix.SetFixFreeShellMode(True)
    sf = fix.FixShellTool()
    sf.SetFixOrientationMode(True)
    fix.LimitTolerance(tolerance)
    fix.Perform()
    return fix.Shape()

def fix_edge(edge):
    fix = ShapeFix_Edge()
    fix.FixAddCurve3d(edge)
    return edge


# def get_area(shape):
#     """
#     Compute area of face
#     """
#     props = GProp_GProps()
#     brepgprop.SurfaceProperties(shape, props)
#     return props.Mass()


# def get_volume(shape):
#     """
#     Compute volume of solid
#     """
#     props = GProp_GProps()
#     brepgprop.VolumeProperties(shape, props)
#     return props.Mass()


# def import_step(step_path):
#     """
#     Import step file
#     """
#     step_reader = STEPControl_Reader()
#     status = step_reader.ReadFile(step_path)

#     if status == IFSelect_RetDone:
#         fails_only = False
#         # step_reader.PrintCheckLoad(fails_only, IFSelect_ItemsByEntity)
#         # step_reader.PrintCheckTransfer(fails_only, IFSelect_ItemsByEntity)

#         if not step_reader.TransferRoot(1):
#             raise RuntimeError('Can not transfer root')
#         number_of_shapes = step_reader.NbShapes()
#         if number_of_shapes > 0:
#             return step_reader.Shape(1)
#         else:
#             raise RuntimeError('The input STEP file does not have shapes')
#     else:
#         raise RuntimeError('Can not read {0} file'.format(step_path))


def extrude_face(face, vector):
    """
    Extrude a face alomg vector
    """
    return BRepPrimAPI_MakePrism(face, vector).Shape()

def pcurve(edge, face):
    """
    computes the 2d parametric spline that lies on the surface of the face
    :return: Geom2d_Curve, u, v
    """
    crv, u, v = BRep_Tool.CurveOnSurface(edge, face)
    return crv, u, v


def mean(numbers):
    """
    Compute mean of a list
    """
    return float(sum(numbers)) / max(len(numbers), 1)


def domain(face):
    '''the u,v domain of the curve
    :return: UMin, UMax, VMin, VMax
    '''
    return breptools.UVBounds(face)


def mid_point(face):
    """
    :return: the parameter at the mid point of the face,
    and its corresponding gp_Pnt
    """
    u_min, u_max, v_min, v_max = domain(face)
    u_mid = (u_min + u_max) / 2.
    v_mid = (v_min + v_max) / 2.

    adaptor = BRepAdaptor_Surface(face)
    return adaptor.Value(u_mid, v_mid)


def wire_edge_pairs(wire, label=None):
    """
    :return: generator of ordered edges in a wire. edges are grouped
    in concecutive pairs and their respective wire_hash
    """
    if wire.Orientation() != 0:
        wire.Reverse()

    edge_explorer = TopExp_Explorer(wire, TopAbs_EDGE)

    first_edge = topods.Edge(edge_explorer.Current())
    prev_edge = first_edge
    edge_explorer.Next()

    while edge_explorer.More():
        current_edge = topods.Edge(edge_explorer.Current())

        yield (prev_edge, current_edge, label)
        prev_edge = current_edge
        edge_explorer.Next()

    # Return first edge
    yield (prev_edge, first_edge, label)


def face_edge_pairs(face_shape):
    """
    :return: generator of ordered edges belonging to wires
    of a face. edges are grouped in concecutive pairs and
    their respective wire_hash
    """
    outer_wire = breptools.OuterWire(face_shape)
    wire_explorer = TopExp_Explorer(face_shape, TopAbs_WIRE)

    # Return out wire
    wire_hash = shape_hash(outer_wire)
    for edge_pair in wire_edge_pairs(outer_wire, label=wire_hash):
        yield edge_pair

    # Return iner wires
    while wire_explorer.More():
        current_wire = topods.Wire(wire_explorer.Current())

        # If inner wire return
        if not current_wire.IsSame(outer_wire):
            wire_hash = shape_hash(current_wire)

            # Return all pairs
            for edge_pair in wire_edge_pairs(current_wire, label=wire_hash):
                yield edge_pair

        wire_explorer.Next()


def edge_end_vertices(edge_shape, ignore_orientation=False):
    """
    :return: first and last verticies of an edge
    """
    first_vertex = topexp.FirstVertex(edge_shape)
    last_vertex = topexp.LastVertex(edge_shape)

    if edge_shape.Orientation() != 0 and not ignore_orientation:
        first_vertex, last_vertex = last_vertex, first_vertex

    return first_vertex, last_vertex


def wire_edges(wire_shape, ignore_orientation=False):
    """
    :return: generator of ordered edges in a wire and if edge is first of a wire
    """
    # reversed_wire = False
    is_reversed = (wire_shape.Orientation() != 0)
    if is_reversed and not ignore_orientation:
        wire_shape.Reverse()
        reversed_wire = True

    is_first = True
    edge_explorer = TopExp_Explorer(wire_shape, TopAbs_EDGE)
    while edge_explorer.More():
        current_edge = topods.Edge(edge_explorer.Current())

        yield (current_edge, is_first, is_reversed)

        # if reversed_wire:
        #     current_edge.Reverse()
        #     yield (current_edge, is_first)
        # else:
        #     yield (current_edge, is_first)

        edge_explorer.Next()
        is_first = False


def face_edges(face_shape, ignore_orientation=False):
    """
    :return: generator of ordered edges in a face
    """
    wire_explorer = TopExp_Explorer(face_shape, TopAbs_WIRE)

    while wire_explorer.More():
        current_wire = topods.Wire(wire_explorer.Current())

        # Return all pairs
        for current_edge, is_first, is_reversed in wire_edges(current_wire, ignore_orientation=ignore_orientation):
            yield (current_edge, is_first, is_reversed)

        wire_explorer.Next()


def first_edge_point(edge):
    """
    :return: first vertex of an edge as gp_Pnt
    (ignoring edge orientation)
    """
    first_vertex = topexp.FirstVertex(edge)
    return BRep_Tool.Pnt(first_vertex)


def last_edge_point(edge):
    """
    :return: last vertex of an edge as gp_Pnt
    (ignoring edge orientation)
    """
    last_vertex = topexp.LastVertex(edge)
    return BRep_Tool.Pnt(last_vertex)


def face_surface_handle(face):
    """
    :return: surface handle belonging to a face
    """
    return BRep_Tool.Surface(face)


def face_surface(surface_handle):
    """
    :return: surface by surface handle
    """
    return surface_handle


def point_to_parameter(point, surface_handle, TOLLERANCE=TOLLERANCE):
    """
    :return: uv coordinates of a point with respect to the surface
    specified by it's surface handle
    """
    shape_analysis = ShapeAnalysis_Surface(surface_handle)
    uv = shape_analysis.ValueOfUV(point, TOLLERANCE)
    return uv.Coord()


def continuity_edge_face(edge, face_a, face_b):
    """
    :return: Continuity between two adjacent faces along a given edge
    """
    tool = BRep_Tool
    if tool.HasContinuity(edge, face_a, face_b):
        return True, 1

    else:
        return False, None


def calculating_normal_on_edge(face, edge):
    """
    :return: Normal vector on a face at the first point of the specified edge
    """
    first_point = first_edge_point(edge)
    surface_handle = face_surface_handle(face)
    uv_point = point_to_parameter(first_point, surface_handle)

    props = FaceProperties(surface_handle, uv_point)
    normal = props.normal()

    if face.Orientation() != 0:
        normal.Reverse()

    return normal


def calculating_normal_at_point(face, point):
    """
    :return: Normal vector on a face at a given point
    """
    surface_handle = face_surface_handle(face)
    uv_point = point_to_parameter(point, surface_handle)

    props = FaceProperties(surface_handle, uv_point)
    normal = props.normal()

    if face.Orientation() != 0:
        normal.Reverse()

    return normal


def face_normal(face):
    """
    :return: Normal vector of a planar face
    """
    surface_handle = face_surface_handle(face)
    props = FaceProperties(surface_handle)
    normal = props.normal()

    if face.Orientation() != 0:
        normal.Reverse()

    return normal


def edge_tangent(edge, ignore_orientation=False):
    """
    :return: Tangent vector along an edge
    """
    edge_props = EdgeProperties(edge, use_first=(edge.Orientation != 0))
    tangent = edge_props.tangent()

    # Reverse if edge has reversed orientation
    if edge.Orientation() == 0 and not ignore_orientation:
        tangent.Reverse()

    return tangent


def bend_allowance(angle, inner_radius, thickness, k_factor):
    return angle * (inner_radius + thickness * k_factor)


def radius_allowance(angle, original_radius, new_radius):
    length = (new_radius - original_radius) / math.tan(angle / 2.)
    return 2 * length


#===========================================================================
# Helper class for edge properties
#===========================================================================
class EdgeProperties(object):
    def __init__(self, edge, use_first=True, TOLLERANCE=TOLLERANCE):
        curve_adaptor = BRepAdaptor_Curve(edge)
        self._props = BRepLProp_CLProps(curve_adaptor, 2, TOLLERANCE)

        if use_first:
            self._props.SetParameter(curve_adaptor.FirstParameter())
        else:
            self._props.SetParameter(curve_adaptor.LastParameter())

    def tangent(self):
        if self._props.IsTangentDefined():
            tangent_dir = gp_Dir()
            self._props.Tangent(tangent_dir)
            return gp_Vec(tangent_dir)
        else:
            raise ValueError('no tangent defined')


#===========================================================================
# Helper class for face properties
#===========================================================================
class FaceProperties(object):
    def __init__(self, surface_handle, uv_point=[-1, -1], TOLLERANCE=TOLLERANCE):
        if type(uv_point) == list:
            coord_a = uv_point[0]
            coord_b = uv_point[1]
        
        elif type(uv_point) == tuple:
            coord_a = uv_point[0]
            coord_b = uv_point[1]

        else:
            coord_a = uv_point.Coord(1)
            coord_b = uv_point.Coord(2)
            
        self._props = GeomLProp_SLProps(surface_handle, coord_a, coord_b, 2, TOLLERANCE)

    def directions(self):
        dU, dV = gp_Dir(), gp_Dir()
        if self._props.IsTangentUDefined() and self._props.IsTangentVDefined():
            self._props.TangentU(dU), self._props.TangentV(dV)

        return dU, dV

    def curvature(self):
        if self._props.IsCurvatureDefined():
            return self._props.MeanCurvature()

        else:
            raise ValueError('curvature is not defined at this u,v')

    def radii(self):
        dU = self._props.D2U().Magnitude()
        dV = self._props.D2V().Magnitude()

        return (dU, dV)

    def normal(self):
        if self._props.IsNormalDefined():
            normal_dir = self._props.Normal()
            return gp_Vec(normal_dir)
        else:
            raise ValueError('normal is not defined at this u,v')


#===========================================================================
# Enumerator to define face shape (currently all are cast to: CONVEX, CONCAVE or PLANAR)
#===========================================================================
class FaceTypes(Enum):
        CONVEX = -1
        PLANAR = 0
        CONCAVE = 1
        COMPLEX = 2


def is_planar(surface_handle, TOLLERANCE=TOLLERANCE):
    """
    :return: True if a given surface is planar
    """
    is_planar_surface = GeomLib_IsPlanarSurface(surface_handle, TOLLERANCE)
    return is_planar_surface.IsPlanar()


def face_convexity(face, TOLLERANCE=TOLLERANCE):
    """
    :return: face type and (mean) curvature are given for a given face

    TODO: face properties should be elaborated upon to properly handle
    non-uniform curvatures along a face
    """
    surface_handle = face_surface_handle(face)
    is_planar_surface = GeomLib_IsPlanarSurface(surface_handle, TOLLERANCE)

    if is_planar_surface.IsPlanar():
        return (FaceTypes.PLANAR, 0.0, [None, None], [None, None])

    props = FaceProperties(surface_handle)
    curvature = props.curvature()
    radii = props.radii()
    directions = props.directions()

    if abs(curvature) < TOLLERANCE:
        return (FaceTypes.PLANAR, 0.0, [None, None], [None, None])

    if abs(radii[0]) > TOLLERANCE and abs(radii[1]) > TOLLERANCE:
        return (FaceTypes.COMPLEX, curvature, radii, directions)

    # if face.Convex():
    if curvature > 0:
        if face.Orientation() != 0:
            return (FaceTypes.CONVEX, curvature, radii, directions)
        else:
            return (FaceTypes.CONCAVE, curvature, radii, directions)

    else:
        if face.Orientation() != 0:
            return (FaceTypes.CONCAVE, curvature, radii, directions)
        else:
            return (FaceTypes.CONVEX, curvature, radii, directions)


#===========================================================================
# Main class for generating and using the attributed adjacency graph of a shape
#===========================================================================
class AdjacencyGraph(object):

    class EdgeTypes(Enum):
        CONVEX = -1
        SMOOTH = 0
        CONCAVE = 1

    # class FaceTypes(Enum):
    #     CONVEX = -1
    #     PLANAR = 0
    #     CONCAVE = 1

    def __init__(self, shape, TOLLERANCE=1e-6):
        self.shape = shape
        self.TOLLERANCE = TOLLERANCE

        # Face graphs stored as networkX graphs
        # Graph nodes in the graph represent shape faces
        # Graph edges in the graph represent shape edges
        self.C0_faces = None # Nodes/Faces are connected if adjecent
        self.C1_faces = None # Nodes/Faces are connected only if continuity is higher than C0
        self.C2_faces = None # Nodes/Faces are connected only if continuity is higher than C1

        # Edge graphs stored as networkX graphs
        # Graph nodes in the graph represent shape vertices
        # Graph edges in the graph represent shape edges
        self.C0_edges = None
        self.C1_edges = None
        self.C2_edges = None

        self.areas = []


    # Angular tolerance for geometric tangency detection (radians, ~0.57deg)
    SMOOTH_ANGLE_TOLERANCE = 1e-2

    def edge_continuity(self, edge, node_a, node_b):
        """
        :return: return the degree of continuity of two nodes along an edge
        """
        # OCCT 7.x records continuity on edges where 6.9 stored nothing, so a
        # bare HasContinuity() now also fires for sharp (C0) edges. Check the
        # actual regularity level: smooth means G1 or better.
        tool = BRep_Tool
        smooth = False
        if tool.HasContinuity(edge, node_a["shape"], node_b["shape"]):
            smooth = tool.Continuity(edge, node_a["shape"], node_b["shape"]) >= GeomAbs_G1

        if not smooth:
            # Some exporters ship STEP files without any G1 regularity records
            # (and the 7.x reader then marks the edges C0), so trusting the
            # records alone drops genuinely tangent connections — verify
            # tangency geometrically by comparing outward normals on the edge.
            try:
                normal_a = calculating_normal_on_edge(node_a["shape"], edge)
                normal_b = calculating_normal_on_edge(node_b["shape"], edge)
                smooth = normal_a.Angle(normal_b) < self.SMOOTH_ANGLE_TOLERANCE
            except Exception:
                smooth = False

        if smooth:
            if abs(node_a["curvature"] - node_b["curvature"]) <= self.TOLLERANCE:
                if node_a["convexity"] == FaceTypes.COMPLEX or node_b["convexity"] == FaceTypes.COMPLEX:
                    return -2
                else:
                    return 2
            else:
                if node_a["convexity"] == FaceTypes.COMPLEX or node_b["convexity"] == FaceTypes.COMPLEX:
                    return -1
                else:
                    return 1

        else:
            return 0


    def full(self):
        """
        Compute the full adjacency graph with any continuity degree
        """
        if self.C0_faces:
            return self.C0_faces

        else:
            self.C0_faces = nx.Graph()
            self.C0_edges = nx.MultiGraph()
            self.build_graphs(self.C0_faces, self.C0_edges, min_continuity=0)


    def smooth(self):
        """
        Compute the adjacency graph with a C1/C2 continuity degree
        """
        if self.C1_faces:
            return self.C1_faces

        else:
            self.C1_faces = nx.Graph()
            self.C1_edges = nx.MultiGraph()
            self.build_graphs(self.C1_faces, self.C1_edges, min_continuity=1)


    def grouped(self):
        """
        Compute the adjacency graph with a C2 continuity degree
        """
        if self.C2_faces:
            return self.C2_faces

        else:
            self.C2_faces = nx.Graph()
            self.C2_edges = nx.MultiGraph()
            self.build_graphs(self.C2_faces, self.C2_edges, min_continuity=2)


    def build_graphs(self, graph_faces, graph_edges, min_continuity=0):
        """
        Compute the adjacency graph with given minimal continuity degree
        """
        self.areas = []
        edge_edges = []
        solid_explorer = TopExp_Explorer(self.shape, TopAbs_FACE)
        while solid_explorer.More():
            face = topods.Face(solid_explorer.Current())
            face_hash = shape_hash(face)
            solid_explorer.Next()

            # areas of faces
            face_area = abs(get_area(face))
            self.areas.append((face_area, face_hash))

            # add face + attributes to graph
            convexity, curvature, radii, directions = face_convexity(face)
            graph_faces.add_node(face_hash, shape=face, convexity=convexity, curvature=curvature, radii=radii, directions=directions, bend_radius=None, k_factor=None)
            face_node = graph_faces.nodes[face_hash]

            # Loop over all edges of current face
            for edge, is_first, is_reversed in face_edges(face, ignore_orientation=False):
                edge_hash = shape_hash(edge)

                first_vertex, last_vertex = edge_end_vertices(edge, ignore_orientation=False)
                first_hash = shape_hash(first_vertex)
                last_hash = shape_hash(last_vertex)

                # Add the first vertex to the edge graph
                if is_first and not graph_edges.has_node(first_hash):
                    graph_edges.add_node(first_hash, shape=first_vertex)

                # Add unique vertices to edge graph
                if not graph_edges.has_node(last_hash):
                    graph_edges.add_node(last_hash, shape=last_vertex)

                # Handle first face adjacent to edge
                if not graph_edges.has_edge(first_hash, last_hash, key=edge_hash):
                    graph_edges.add_edge(first_hash, last_hash, key=edge_hash, faces=[face], shape=edge, flattened=None)

                # Handle second face adjacent to edge
                else:
                    other_face = graph_edges[first_hash][last_hash][edge_hash]["faces"][0]
                    other_face_hash = shape_hash(other_face)
                    other_face_node = graph_faces.nodes[other_face_hash]
                    edge_continuity = self.edge_continuity(edge, face_node, other_face_node)

                    # Add face and loop data to edge adjecency graph
                    graph_edges[first_hash][last_hash][edge_hash]["faces"].append(face)
                    graph_edges[first_hash][last_hash][edge_hash]["continuity"] = edge_continuity

                    # Continue if continuity doesn't suffice
                    if abs(edge_continuity) < min_continuity:
                        continue

                    # Handle smooth faces
                    elif abs(edge_continuity) >= 1:
                        edge_convexity = self.EdgeTypes.SMOOTH
                        edge_angle = 0.0
                        # display.DisplayShape(edge, update=True, color="green")

                    # Handle non-smooth faces
                    else:
                        if is_reversed:
                            edge.Reverse()

                        normal_a = calculating_normal_on_edge(other_face, edge)
                        normal_b = calculating_normal_on_edge(face, edge)
                        tangent = edge_tangent(edge)

                        # if is_reversed:
                        #     tangent.Reverse()

                        # compute dihedral_angle
                        edge_angle = normal_b.AngleWithRef(normal_a, tangent)

                        # if is_reversed:
                        #     edge_angle *= -1

                        if edge_angle > 0.0:
                            edge_convexity = self.EdgeTypes.CONCAVE
                            # display.DisplayShape(edge, update=True, color="red")

                        else:
                            edge_convexity = self.EdgeTypes.CONVEX
                            # display.DisplayShape(edge, update=True, color="blue")

                    graph_faces.add_edge(other_face_hash, face_hash, angle=edge_angle, continuity=edge_continuity, convexity=edge_convexity, hash=edge_hash, shape=edge)
                    graph_edges[first_hash][last_hash][edge_hash]["angle"] = edge_angle
                    graph_edges[first_hash][last_hash][edge_hash]["convexity"] = edge_convexity


    def get_connected_subgraph(self, base_hash, ignore_complex=False, display=False):
        """
        :return: subgraph of the given graph composed of all nodes
        that are connected to the base node
        """
        component = nx.node_connected_component(self.C1_faces, base_hash)

        # Remove faces with complex convexity
        if ignore_complex:
            complex_hashes = []

            for node_hash in component:
                node = self.C1_faces.nodes[node_hash]

                if node["convexity"] == FaceTypes.COMPLEX:
                    logger.debug("removing %s becouse it is a complex face" % (node_hash))
                    complex_hashes.append(node_hash)

                    # if display:
                        # display.DisplayShape(node["shape"], update=True, color="red")

            for node_hash in complex_hashes:
                component.remove(node_hash)

            sub_graph = self.C1_faces.subgraph(component)
            component = nx.node_connected_component(sub_graph, base_hash)

        sub_graph = self.C1_faces.subgraph(component)

        if display:
            for node_hash in sub_graph.nodes():
                node = self.C1_faces.nodes[node_hash]

                # if node["convexity"] != FaceTypes.PLANAR:
                    # display.DisplayShape(node["shape"], update=True, color="green")
                # else:
                #     display.DisplayShape(node["shape"], update=True, color="red")

        return sub_graph


    def get_formed_components(self, base_hash, display=False):
        """
        :return: components of the given graph composed of all nodes
        that are are curved in 2 directions
        """
        component = nx.node_connected_component(self.C1_faces, base_hash)
        sub_graph = self.C1_faces.subgraph(component)

        if display:
            for node_hash in sub_graph.nodes():
                node = self.C1_faces.nodes[node_hash]

                if node["convexity"] != FaceTypes.PLANAR:
                    display.DisplayShape(node["shape"], update=True, color="green")
                else:
                    display.DisplayShape(node["shape"], update=True, color="red")

        return sub_graph


    # def extract_feature_wires(self, features, transformations=[], display=None, k_factor=0.5, TOLLERANCE=1e-3):
    #     """
    #     :return: create ordered wires of all connected edges by removing the seams.
    #     Tranformations can be passed and applied to edges before they are joined to
    #     a wire.
    #     """

    #     # Loop over all featuers
    #     for feature in features:
    #         logger.debug(feature)
    #         node = self.C0_faces.nodes[feature["base_a"]]
    #         node_scale = self.node_scale(node, thickness, k_factor=k_factor)

    #         for edge in feature["wire"].wire_edges(ignore_orientation=False):
    #             pass

        # for node_hash in graph.nodes():
        #         node = graph.nodes[node_hash]
        #         node_scale = self.node_scale(node, thickness, k_factor=k_factor)

        #         for edge in wire_edges

        #         # Loop over all edges, with internal wires grouped
        #         for edge, is_first, is_reversed in face_edges(node["shape"]):
        #             edge_hash = shape_hash(edge)

        #             if edge_hash in used_edge_hashes:
        #                 continue

        #             # Potential start edge
        #             first_vertex, start_vertex = edge_end_vertices(edge, ignore_orientation=True)
        #             first_vertex_hash = shape_hash(first_vertex)
        #             start_vertex_hash = shape_hash(start_vertex)

        #             # Wire is allready closed (circle, etc.)
        #             if first_vertex_hash == start_vertex_hash:
        #                 local_edge = self.transformed_edge(edge, node["shape"], surface_handle, scale=node_scale, transformations=transformations[node_hash])
        #                 wire_builder = BRepBuilderAPI_MakeWire()
        #                 wire_builder.Add(local_edge)
        #                 wire = wire_builder.Wire()
        #                 wires.append(wire)

        #                 loop = Loop(wire=wire, gap=gp_Vec(), feature=(edge_hash in featured_edges))
        #                 loops.append(loop)
        #                 continue


    def extract_wires(self, graph, surface_handle, thickness, transformations=[], featured_edges=[], features=[], display=None, k_factor=0.5, TOLLERANCE=1e-1):
        """
        :return: create ordered wires of all connected edges by removing the seams.
        Tranformations can be passed and applied to edges before they are joined to
        a wire.
        """

        loops = []
        wires = []
        open_wire_count = 0
        used_edge_hashes = set()

        # Loop over all nodes (faces) in the graph
        for node_hash in graph.nodes():
                node = graph.nodes[node_hash]
                node_scale = self.node_scale(node, thickness, k_factor=k_factor)

                # Loop over all edges, with internal wires grouped
                for edge, is_first, is_reversed in face_edges(node["shape"]):
                    edge_hash = shape_hash(edge)

                    if edge_hash in used_edge_hashes:
                        continue

                    # Potential start edge
                    first_vertex, start_vertex = edge_end_vertices(edge, ignore_orientation=True)
                    first_vertex_hash = shape_hash(first_vertex)
                    start_vertex_hash = shape_hash(start_vertex)

                    # Wire is allready closed (circle, etc.)
                    if first_vertex_hash == start_vertex_hash:
                        local_edge = self.transformed_edge(edge, node["shape"], surface_handle, scale=node_scale, transformations=transformations[node_hash])
                        wire_builder = BRepBuilderAPI_MakeWire()
                        wire_builder.Add(local_edge)
                        wire = wire_builder.Wire()
                        wires.append(wire)

                        # Start test of a closed wire is closed after unfolding
                        loop = Loop(wire=wire, gap=gp_Vec())
                        first_local_vertex, last_local_vertex = edge_end_vertices(local_edge, ignore_orientation=True)
                        first_local_point = BRep_Tool.Pnt(first_local_vertex)
                        last_local_point = BRep_Tool.Pnt(last_local_vertex)
                        local_gap = gp_Vec(first_local_point, last_local_point)
                        local_gap_distance = local_gap.Magnitude()

                        # logger.warning("local gap: {0}".format(local_gap_distance))
                        if local_gap_distance > TOLLERANCE:
                            logger.debug("single curve wire has local gap: {0}".format(local_gap_distance))
                            open_wire_count += 1
                        # End open wire test

                        if edge_hash in featured_edges:
                            for feature in features:
                                if edge_hash in feature.loop_a or edge_hash in feature.loop_b:
                                    loop.add(feature=feature)
                                    break

                        loops.append(loop)
                        continue

                    # Continue if wire needs to be closed manually
                    edge_node = self.C1_edges[first_vertex_hash][start_vertex_hash][edge_hash]

                    # Has two faces (not a seam) and is not smooth edge
                    if len(edge_node["faces"]) < 2 or edge_node["continuity"] > 0:
                        used_edge_hashes.add(edge_hash)
                        continue

                    # Has two faces (not a seam) and is not smooth edge
                    else:
                        wire_builder = BRepBuilderAPI_MakeWire()
                        local_start_vertex = self.transformed_vertex(start_vertex, node["shape"], surface_handle, scale=node_scale, transformations=transformations[node_hash])
                        local_start_point = BRep_Tool.Pnt(local_start_vertex)

                        wire_closed = False
                        current_loop = Loop()
                        current_hash = edge_hash
                        current_vertex_hash = start_vertex_hash
                        current_local_point = local_start_point
                        while not wire_closed:
                            is_found = False
                            connected_edges = self.C1_edges.neighbors(current_vertex_hash)

                            for connected_vertex_hash in connected_edges:
                                connected_vertex_node = self.C1_edges[current_vertex_hash][connected_vertex_hash]
                                current_vertex = self.C1_edges.nodes[current_vertex_hash]["shape"]

                                for connected_hash in connected_vertex_node:
                                    connected_node = connected_vertex_node[connected_hash]

                                    # Has two faces (not a seam)
                                    if len(connected_node["faces"]) < 2:
                                        used_edge_hashes.add(connected_hash)
                                        continue

                                    if connected_hash in featured_edges and not current_loop.feature:
                                        for feature in features:
                                            if connected_hash in feature.loop_a or connected_hash in feature.loop_b:
                                                current_loop.add(feature=feature)
                                                break

                                    face_hash_a = shape_hash(connected_node["faces"][0])
                                    face_hash_b = shape_hash(connected_node["faces"][1])

                                    is_connected_a = graph.has_node(face_hash_a)
                                    is_connected_b = graph.has_node(face_hash_b)
                                    is_used = connected_hash in used_edge_hashes
                                    is_start = current_vertex_hash == start_vertex_hash
                                    is_end = connected_vertex_hash == start_vertex_hash
                                    is_same = connected_hash == current_hash

                                    if not is_same:
                                        used_edge_hashes.add(connected_hash)

                                    if is_connected_a != is_connected_b and not is_used and not is_same:
                                        current_vertex_hash = connected_vertex_hash
                                        current_hash = connected_hash
                                        is_found = True

                                        current_edge = connected_node["shape"]
                                        if is_connected_a:
                                            face_node = self.C1_faces.nodes[face_hash_a]
                                            face_scale = self.node_scale(face_node, thickness, k_factor=k_factor)
                                            local_edge = self.transformed_edge(current_edge, connected_node["faces"][0], surface_handle, scale=face_scale, transformations=transformations[face_hash_a])

                                            # RESET LOCAL STARTPOINT IN CASE OF TUBES
                                            # if is_start:
                                            #     display.DisplayShape(local_start_point, update=True, color="red")

                                            #     local_start_vertex = self.transformed_vertex(start_vertex, connected_node["faces"][0], surface_handle, scale=face_scale, transformations=transformations[face_hash_a])
                                            #     local_start_point = BRep_Tool.Pnt(local_start_vertex)
                                            #     current_local_point = local_start_point

                                            #     display.DisplayShape(local_start_point, update=True, color="green")
                                        else:
                                            face_node = self.C1_faces.nodes[face_hash_b]
                                            face_scale = self.node_scale(face_node, thickness, k_factor=k_factor)
                                            local_edge = self.transformed_edge(current_edge, connected_node["faces"][1], surface_handle, scale=face_scale, transformations=transformations[face_hash_b])

                                            # RESET LOCAL STARTPOINT IN CASE OF TUBES
                                            # if is_start:
                                            #     display.DisplayShape(local_start_point, update=True, color="red")

                                            #     local_start_vertex = self.transformed_vertex(start_vertex, connected_node["faces"][1], surface_handle, scale=face_scale, transformations=transformations[face_hash_b])
                                            #     local_start_point = BRep_Tool.Pnt(local_start_vertex)
                                            #     current_local_point = local_start_point

                                            #     display.DisplayShape(local_start_point, update=True, color="green")

                                        first_vertex, last_vertex = edge_end_vertices(local_edge, ignore_orientation=False)
                                        first_local_point = BRep_Tool.Pnt(first_vertex)
                                        last_local_point = BRep_Tool.Pnt(last_vertex)

                                        current_gap = gp_Vec(current_local_point, first_local_point)
                                        gap_distance = current_gap.Magnitude()
                                        if gap_distance > current_local_point.Distance(last_local_point):
                                            current_gap = gp_Vec(current_local_point, last_local_point)
                                            gap_distance = current_gap.Magnitude()
                                            first_local_point, last_local_point = last_local_point, first_local_point
                                            local_edge.Reverse()

                                        # Get current wire
                                        if wire_builder.Error() != 1:
                                            current_wire = wire_builder.Wire()

                                        wire_builder.Add(local_edge)
                                        wire_error = wire_builder.Error()

                                        if wire_error > 0 and gap_distance <= TOLLERANCE:
                                            wire_builder = BRepBuilderAPI_MakeWire(current_wire)
                                            fixed_edge = BRepBuilderAPI_MakeEdge(current_local_point, first_local_point).Edge()
                                            wire_builder.Add(fixed_edge)
                                            wire_builder.Add(local_edge)
                                            logger.debug("forced to add filler wire to close wire: error {0}".format(gap_distance))
                                            current_gap = gp_Vec()

                                        elif wire_error > 0:
                                        # elif wire_error > 0 and not is_end:
                                            logger.debug("filler gap to large: error {0}".format(gap_distance))
                                            open_wire_count += 1

                                            # USE LAST_LOCAL POINT AS TUBE DISCONTINUITIES ARE NOT CLOSES
                                            first_local_point, last_local_point = last_local_point, first_local_point
                                            local_edge.Reverse()

                                            if display:
                                                display.DisplayShape(current_wire, update=True, color="blue")
                                                # display.DisplayShape(BRepBuilderAPI_MakeEdge(current_local_point, first_local_point).Edge(), update=True, color="red")
                                                # display.DisplayShape(BRepBuilderAPI_MakeEdge(local_start_point, current_local_point).Edge(), update=True, color="white")
                                            #     raw_input("next piece?")

                                            current_gap = gp_Vec(current_local_point, first_local_point)
                                            # current_short = gp_Vec(local_start_point, last_local_point)
                                            current_loop.add(wire=current_wire, gap=current_gap)
                                            wires.append(current_wire)

                                            wire_builder = BRepBuilderAPI_MakeWire()
                                            wire_builder.Add(local_edge)

                                            # TODO check if this solves issues
                                            current_wire = wire_builder.Wire()

                                        current_local_point = last_local_point

                                        if is_end:
                                            wire_closed = True

                                            current_gap = gp_Vec(local_start_point, current_local_point)
                                            current_loop.add(wire=current_wire, gap=current_gap)
                                            gap_distance = current_gap.Magnitude()

                                            # if gap_distance > TOLLERANCE:
                                                # logger.debug("still got local end gap: {}".format(gap_distance))


                                                # open_wire_count += 1

                                            # print(edge_hash)
                                            # if connected_hash in featured_edges:
                                            #     print("IN FEATURED EDGES END")

                                            #     for feature in features:
                                            #         if edge_hash in feature["loop_a"] or edge_hash in feature["loop_b"]:
                                            #             current_loop.add(feature=feature)
                                            #             break

                                            loops.append(current_loop)

                                            # if display:
                                                # display.DisplayShape(current_wire, update=True, color="orange")
                                                # display.DisplayShape(local_start_point, update=True, color="red")
                                                # display.DisplayShape(current_local_point, update=True, color="green")

                                            if display and current_gap.Magnitude() >= TOLLERANCE:
                                            #     # display.DisplayShape(current_wire, update=True, color="orange")
                                                display.DisplayShape(BRepBuilderAPI_MakeEdge(local_start_point, current_local_point).Edge(), update=True, color="white")
                                            #     raw_input("wire is done..")

                                            # raw_input("wire is done..")


                                            #     try:
                                            #         display.DisplayShape(BRepBuilderAPI_MakeEdge(local_start_point, last_local_point).Edge(), update=True, color="black")
                                            #     except:
                                            #         logger.debug("could not make wire..")

                                            wires.append(current_wire)
                                            wire_builder = BRepBuilderAPI_MakeWire()
                                            current_loop = Loop()

                                        break

                                # Continue to next vertex
                                if is_found:
                                    break

                            # Break if wire could not be closed (there is no next vertex that is feasabile)
                            if not is_found:
                                logger.debug("SHOULD NEVER HAPPEN")
                                break

        return wires, open_wire_count, loops


    def transformed_edge_origin(self, edge, face, surface_handle, reverse=False, normal=gp_DZ(), ignore_orientation=False, transformations=[], scale=None, direction=None):
        """
        :return: origin of edge after transformation to unfolding surface from originial face
        """
        # trasnform a single (the first) vertex of the edge
        first_test_vertex, last_test_vertex = edge_end_vertices(edge, ignore_orientation=False)
        local_test_vertex = self.transformed_vertex(first_test_vertex, face, surface_handle, transformations=transformations, scale=scale, direction=direction)
        first_test_point = BRep_Tool.Pnt(local_test_vertex)

        # Place p-curve of original edge on new surface (surface_handle) and apply transformations
        local_edge = self.transformed_edge(edge, face, surface_handle, transformations=transformations, scale=scale, direction=direction)

        # Compute first/last vertices of transformed edge
        first_vertex, last_vertex = edge_end_vertices(local_edge, ignore_orientation=False)
        first_point = BRep_Tool.Pnt(first_vertex)
        last_point = BRep_Tool.Pnt(last_vertex)

        # Reverse transformed edge so the first vertex agrees with the first vertex of the original shape
        # TODO: find a better way to guarantee correct orientation invariant to transformations
        if first_test_point.Distance(first_point) > first_test_point.Distance(last_point):
            local_edge.Reverse()
            first_point, last_point = last_point, first_point

        # Compute tangent along egde on laying on now surface
        tangent = edge_tangent(local_edge, ignore_orientation=True)
        if face.Orientation() != 0 and not ignore_orientation:
            normal.Reverse()

        # Reverse normal if base face we are unfolding to has a reversed orientation with regard to surface
        if reverse:
            normal.Reverse()

        # Return gp_Ax3 of edge describing the full orientation/postion of edge
        return gp_Ax3(first_point, gp_Dir(normal), gp_Dir(tangent))


    def transformed_edge(self, edge, face, surface_handle, transformations=[], scale=None, direction=None):
        """
        :return: return an edge after placing it's p-curve on a new surface and succesively
        applying the transformations
        """
        # Retrieve the pcurve on the cylindrical surface
        p_curve_handle, u, v = BRep_Tool.CurveOnSurface(edge, face)

        # non-uniform resizing (maintain currect surface area of unrolled face)
        if scale:
            # Get original end-points
            first_uv_point = p_curve_handle.Value(u)
            last_uv_point = p_curve_handle.Value(v)

            # Gtransform to allow non-uniform scaling
            transformation_2d = gp_GTrsf2d()
            transformation_2d.SetValue(1, 1, scale[0])
            transformation_2d.SetValue(2, 2, scale[1])
            p_curve_handle = geomlib.GTransform(p_curve_handle, transformation_2d)

            # Scale end-points manually for retrieving new bounding values
            first_uv_point.SetX(scale[0] * first_uv_point.X())
            first_uv_point.SetY(scale[1] * first_uv_point.Y())

            last_uv_point.SetX(scale[0] * last_uv_point.X())
            last_uv_point.SetY(scale[1] * last_uv_point.Y())

            # Projection of first point on curve
            projection = Geom2dAPI_ProjectPointOnCurve(first_uv_point, p_curve_handle)
            u = projection.LowerDistanceParameter()

            # Projection of second point on curve
            projection = Geom2dAPI_ProjectPointOnCurve(last_uv_point, p_curve_handle)
            v = projection.LowerDistanceParameter()

        edge = BRepBuilderAPI_MakeEdge(p_curve_handle, surface_handle, u, v).Edge()

        # Apply transformations on newly generated edge
        for transformation in transformations:
            edge = BRepBuilderAPI_Transform(edge, transformation).Shape()

        edge = topods.Edge(edge)
        edge = fix_edge(edge)

        return edge


    def transformed_vertex(self, vertex, face, surface_handle, transformations=[], scale=None, direction=False, TOLLERANCE=TOLLERANCE):
        """
        :return: return a vertex after placing on a new surface using the original uv coordinates and succesively
        applying the transformations
        """
        point = BRep_Tool.Pnt(vertex)
        shape_analysis = ShapeAnalysis_Surface(face_surface_handle(face))
        uv_point = shape_analysis.ValueOfUV(point, TOLLERANCE)

        if scale:
            uv_point.SetX(scale[0] * uv_point.X())
            uv_point.SetY(scale[1] * uv_point.Y())

        shape_analysis = ShapeAnalysis_Surface(surface_handle)
        point = shape_analysis.Value(uv_point)
        vertex = BRepBuilderAPI_MakeVertex(point).Vertex()

        for transformation in transformations:
            vertex = BRepBuilderAPI_Transform(vertex, transformation).Shape()

        return topods.Vertex(vertex)


    def plot_transformed_face(self, face, surface_handle, transformations=[], scale=None, direction=None, color="white"):
        """
        display face edges after transformation
        """
        for prev_edge, edge, edge_loop in face_edge_pairs(face):
            edge = self.transformed_edge(edge, face, surface_handle, scale=scale, direction=direction, transformations=transformations)
            display.DisplayShape(edge, update=True, color=color)


    def node_scale(self, node, thickness, k_factor=0.5):
        if node["convexity"] == FaceTypes.PLANAR:
            return None

        bend_face = node["shape"]
        face_domain = domain(bend_face)
        face_angle = abs(face_domain[0] - face_domain[1])
        face_radius = node["radii"][0]

        # New bend radius and angle
        face_radius = abs(1 / node["curvature"] / 2)
        if abs(node["radii"][0]) > abs(node["radii"][1]):
            face_angle = abs(face_domain[0] - face_domain[1])
        else:
            face_angle = abs(face_domain[2] - face_domain[3])

        if node["convexity"] != FaceTypes.CONCAVE:
            face_radius -= thickness
            face_angle *= -1

        bend_radius = node["bend_radius"] or face_radius
        k_factor = node["k_factor"] or k_factor

        # logger.info("bend radius: {:0.2f}".format(bend_radius))
        # logger.info("k_factor: {:0.2f}".format(k_factor))
        # logger.info("bend angle: {:0.2f}".format(face_angle))

        b_allowance = bend_allowance(face_angle, bend_radius, thickness, k_factor)
        r_allowance = radius_allowance(face_angle, face_radius, bend_radius)
        allowance = b_allowance  - r_allowance
        scale = allowance / face_angle

        # logger.info("b_allowance: {:0.2f}".format(b_allowance))
        # logger.info("r_allowance: {:0.2f}".format(r_allowance))
        # logger.info("total allowance: {:0.2f}".format(allowance))

        if abs(node["radii"][0]) > abs(node["radii"][1]):
            return (scale, 1.0)
        else:
            return (1.0, scale)


    def unfold_graph(self, graph, thickness, base_hash=None, align=False, display=False, k_factor=0.5):
        """
        Compute transformations to unfold a graph
        """
        node_transformations = {}
        node_flattened = {}

        # Use random hash if none is given
        if not base_hash:
            for base_hash in graph.nodes():
                break

        if not align:
            # Compute surface to unfold other faces to
            base_node = self.C1_faces.nodes[base_hash]
            base_face = base_node["shape"]
            base_surface_handle = face_surface_handle(base_face)
            base_props = FaceProperties(base_surface_handle)
            base_normal = base_props.normal()
            node_transformations[base_hash] = []
            base_reversed = False

        else:
            # Compute surface to unfold 2D plane
            base_node = self.C1_faces.nodes[base_hash]
            base_normal = gp_Vec(gp_DZ())
            base_plane = gp_Pln(gp_Origin(), gp_DZ())
            base_face = BRepBuilderAPI_MakeFace(base_plane).Face()
            base_surface_handle = face_surface_handle(base_face)
            node_transformations[base_hash] = []
            base_reversed = (base_node["shape"].Orientation() != 0)

            if base_reversed:
                transformation = gp_Trsf()
                transformation.SetTransformation(gp_Ax3(gp_Origin(), gp_DZ().Reversed(), gp_DX()))
                node_transformations[base_hash] = [transformation]

        # Plot the initial face in the 2D coordinate system
        if display:
            self.plot_transformed_face(base_node["shape"], base_surface_handle, transformations=node_transformations[base_hash], color="red")

        # Loop over all adjacent faces until all are covered
        for successors in nx.bfs_successors(graph, source=base_hash):

            predecessor_hash = successors[0]
            for successor_hash in successors[1]:

                # Get networkX nodes of the common edge
                edge_node = graph[predecessor_hash][successor_hash]
                edge_shape = edge_node["shape"]

                # Get networkX nodes of the faces
                predecessor_node = self.C1_faces.nodes[predecessor_hash]
                successor_node = self.C1_faces.nodes[successor_hash]

                # Scaling factors
                predecessor_scale = self.node_scale(predecessor_node, thickness, k_factor=k_factor)
                successor_scale = self.node_scale(successor_node, thickness, k_factor=k_factor)

                # Faces
                successor_face = successor_node["shape"]
                predecessor_face = predecessor_node["shape"]

                # Get compute axis of both faces to compute transformation
                predecessor_origin = self.transformed_edge_origin(edge_shape, predecessor_face, base_surface_handle, scale=predecessor_scale, normal=base_normal, reverse=(base_face.Orientation() != 0), ignore_orientation=True, transformations=node_transformations[predecessor_hash])
                successor_origin = self.transformed_edge_origin(edge_shape, successor_face, base_surface_handle, scale=successor_scale, normal=base_normal, reverse=(base_face.Orientation() != 0))

                # Initialize list of transformations
                node_transformations[successor_hash] = []

                transformation = gp_Trsf()
                transformation.SetTransformation(successor_origin)
                node_transformations[successor_hash].append(transformation)

                transformation = gp_Trsf()
                transformation.SetTransformation(predecessor_origin)
                transformation.Invert()
                node_transformations[successor_hash].append(transformation)

                # Plot the transformed successor face in the 2D coordinate system
                if display:
                    self.plot_transformed_face(successor_face, base_surface_handle, scale=successor_scale, transformations=node_transformations[successor_hash], color="orange")

        return base_surface_handle, node_transformations, base_reversed


    def node_center_line(self, node_hash, trim_line=True):
        node = self.C0_faces.nodes[node_hash]
        face = node["shape"]
        face_domain = domain(face)
        adaptor = BRepAdaptor_Surface(face)

        if abs(node["radii"][0]) > abs(node["radii"][1]):
            xMid = (face_domain[0] + face_domain[1]) / 2.
            start = adaptor.Value(xMid, face_domain[2])
            end = adaptor.Value(xMid, face_domain[3])

        else:
            yMid = (face_domain[2] + face_domain[3]) / 2.
            start = adaptor.Value(face_domain[0], yMid)
            end = adaptor.Value(face_domain[1], yMid)

        line = GC_MakeSegment(start, end)
        edge = BRepBuilderAPI_MakeEdge(line.Value()).Edge()

        if trim_line:
            minimum = float("inf")
            maximum = float("-inf")

            surface_handle = BRep_Tool.Surface(face)
            interference = boolean_common(edge, face)
            topo_explorer = TopExp_Explorer(interference, TopAbs_VERTEX)
            while topo_explorer.More():
                current_vertex = topods.Vertex(topo_explorer.Current())
                current_point = BRep_Tool.Pnt(current_vertex)

                current_values = list(point_to_parameter(current_point, surface_handle))
                if abs(node["radii"][0]) > abs(node["radii"][1]):
                    current_value = current_values[1]
                    # _, current_value = point_to_parameter(current_point, surface_handle).Coord()
                else:
                    current_value = current_values[0]
                    # current_value, _ = point_to_parameter(current_point, surface_handle).Coord()

                if current_value < minimum:
                    minimum = current_value
                    start = current_point

                elif current_value > maximum:
                    maximum = current_value
                    end = current_point

                topo_explorer.Next()

            line = GC_MakeSegment(start, end)
            edge = BRepBuilderAPI_MakeEdge(line.Value()).Edge()

        return edge


    def join_nodes(self, component):
        max_hash = None
        max_node = None
        max_face = None
        max_area = float("-inf")
        for node_hash in component:
            node = self.C0_faces.nodes[node_hash]
            node_face = node["shape"]
            face_area = abs(get_area(node_face))

            if face_area > max_area:
                max_area = face_area
                max_hash = node_hash
                max_node = node
                max_face = node_face

        max_domain = list(domain(max_face))
        surface_handle = face_surface_handle(max_face)
        for node_hash in component:
            if node_hash != max_hash:
                node = self.C0_faces.nodes[node_hash]
                node_face = node["shape"]
                face_domain = domain(node_face)
                adaptor = BRepAdaptor_Surface(node_face)


                start = adaptor.Value(face_domain[0], face_domain[2])
                end = adaptor.Value(face_domain[1], face_domain[3])

                uv_start = list(point_to_parameter(start, surface_handle))
                uv_end = list(point_to_parameter(end, surface_handle))

                # Fix overflow
                if abs(max_node["radii"][0]) > abs(max_node["radii"][1]):
                    if uv_start[0] > math.pi:
                        uv_start[0] -= 2 * math.pi

                    if uv_end[0] > math.pi:
                        uv_end[0] -= 2 * math.pi

                else:
                    if uv_start[1] > math.pi:
                        uv_start[1] -= 2 * math.pi

                    if uv_end[1] > math.pi:
                        uv_end[1] -= 2 * math.pi


                # Compute combined domain
                if max_domain[0] > max_domain[1]:
                    max_domain[0], max_domain[1] = max_domain[1], max_domain[0]

                if max_domain[2] > max_domain[3]:
                    max_domain[2], max_domain[3] = max_domain[3], max_domain[2]

                # u coords
                if uv_start[0] < max_domain[0]:
                    max_domain[0] = uv_start[0]

                elif uv_start[0] > max_domain[1]:
                    max_domain[1] = uv_start[0]

                if uv_end[0] < max_domain[0]:
                    max_domain[0] = uv_end[0]

                elif uv_end[0] > max_domain[1]:
                    max_domain[1] = uv_end[0]

                # v coords
                if uv_start[1] < max_domain[2]:
                    max_domain[2] = uv_start[1]

                elif uv_start[1] > max_domain[3]:
                    max_domain[3] = uv_start[1]

                if uv_end[1] < max_domain[2]:
                    max_domain[2] = uv_end[1]

                elif uv_end[1] > max_domain[3]:
                    max_domain[3] = uv_end[1]


        # Compute bend angle
        if abs(max_node["radii"][0]) > abs(max_node["radii"][1]):
            bend_angle = abs(max_domain[0] - max_domain[1])
            xMid = (max_domain[0] + max_domain[1]) / 2.
            start = adaptor.Value(xMid, max_domain[2])
            end = adaptor.Value(xMid, max_domain[3])

        else:
            bend_angle = abs(max_domain[2] - max_domain[3])
            yMid = (max_domain[2] + max_domain[3]) / 2.
            start = adaptor.Value(max_domain[0], yMid)
            end = adaptor.Value(max_domain[1], yMid)

        # logger.warning("total angle {}".format(bend_angle))

        line = GC_MakeSegment(start, end)
        edge = BRepBuilderAPI_MakeEdge(line.Value()).Edge()

        return (max_node, bend_angle, edge)

    def extract_bend(self, node, node_hash, surface_handle, thickness, transformations=[], reversed=False, display=None, k_factor=0.5, neighbors=None):
        bend_face = node["shape"]
        bend_scale = self.node_scale(node, thickness, k_factor=k_factor)
        bend_surface_handle = face_surface_handle(bend_face)
        bend_props = FaceProperties(bend_surface_handle)
        # center_line = face_center_line(bend_face)

        # if not multi_bend:
        center_line = self.node_center_line(node_hash)

        first_bend_vertex, last_bend_vertex = edge_end_vertices(center_line, ignore_orientation=False)
        first_bend_vertex = self.transformed_vertex(first_bend_vertex, bend_face, surface_handle, scale=bend_scale, transformations=transformations[node_hash])
        last_bend_vertex = self.transformed_vertex(last_bend_vertex, bend_face, surface_handle, scale=bend_scale, transformations=transformations[node_hash])


        first_point = BRep_Tool.Pnt(first_bend_vertex)
        last_point = BRep_Tool.Pnt(last_bend_vertex)

        # bend_radius = node["radii"][0]
        bend_domain = domain(bend_face)
        # bend_angle = abs(bend_domain[0] - bend_domain[1])

        # New bend radius
        bend_radius = abs(1 / node["curvature"] / 2)
        # New angle
        # if not multi_bend:
        if abs(node["radii"][0]) > abs(node["radii"][1]):
            bend_angle = abs(bend_domain[0] - bend_domain[1])
        else:
            bend_angle = abs(bend_domain[2] - bend_domain[3])

        if node["convexity"] != FaceTypes.CONCAVE:
            bend_radius -= thickness
            bend_angle *= -1

        # logger.warning("bend_angle {}".format(bend_angle))

        bend_k = (1 - bend_radius) / thickness
        bend_length = gp_Vec(first_point, last_point).Magnitude()

        bend = Entity(type=Entity.EntityTypes.LINE, inner_radius=bend_radius, k_factor=k_factor, angle=bend_angle, length=bend_length)
        bend.path.append([first_point.Coord(1), first_point.Coord(2)])
        bend.path.append([last_point.Coord(1), last_point.Coord(2)])

        return bend


    def extract_bends(self, graph, surface_handle, thickness, transformations=[], reversed=False, display=None, k_factor=0.5, combine_bends=True):
        """
        :return: create ordered wires of all connected edges by removing the seams.
        Tranformations can be passed and applied to edges before they are joined to
        a wire.
        """
        bends = []
        used_edge_hashes = set()

        # Loop over all nodes (faces) in the graph
        for node_hash in graph.nodes():

            if node_hash in used_edge_hashes:
                continue

            node = graph.nodes[node_hash]
            used_edge_hashes.add(node_hash)

            if node["convexity"] != FaceTypes.PLANAR:
                if node_hash in self.C2_faces and combine_bends:

                    component = nx.node_connected_component(self.C2_faces, node_hash)

                    # Get graph neighbors of the bend faces (hashes of the connected flanges)
                    neighbors = set()
                    for component_hash in component:
                        neighbors = neighbors.union(self.C1_faces.neighbors(component_hash))
                    for component_hash in component:
                        neighbors.discard(component_hash)
                    neighbors = frozenset(neighbors)

                    if len(component) > 1:
                        # logger.warning("Bend faces connected {}".format(len(component)))

                        sub_bends = []
                        total_angle = 0.0
                        for node_hash in component:

                            node = graph.nodes[node_hash]
                            used_edge_hashes.add(node_hash)

                            bend = self.extract_bend(node, node_hash, surface_handle, thickness, transformations=transformations, reversed=reversed, display=display, k_factor=k_factor)
                            sub_bends.append(bend)
                            total_angle += bend.angle

                        start_point = [0.0, 0.0]
                        end_point = [0.0, 0.0]
                        reference_point = gp_Vec2d(sub_bends[0].path[0][0], sub_bends[0].path[0][1])

                        for bend in sub_bends:
                            bend_point_a = gp_Vec2d(bend.path[0][0], bend.path[0][1])
                            bend_point_b = gp_Vec2d(bend.path[1][0], bend.path[1][1])

                            distance_a = (reference_point - bend_point_a).Magnitude()
                            distance_b = (reference_point - bend_point_b).Magnitude()

                            if distance_a > distance_b:
                                bend_point_a, bend_point_b = bend_point_b, bend_point_a

                            start_point[0] += (bend.angle / total_angle) * bend_point_a.Coord(1)
                            start_point[1] += (bend.angle / total_angle) * bend_point_a.Coord(2)
                            end_point[0] += (bend.angle / total_angle) * bend_point_b.Coord(1)
                            end_point[1] += (bend.angle / total_angle) * bend_point_b.Coord(2)

                        bend_length = math.sqrt(math.pow(start_point[0] - end_point[0], 2) + math.pow(start_point[1] - end_point[1], 2))

                        bend = Entity(type=Entity.EntityTypes.LINE, inner_radius=bend.inner_radius, k_factor=k_factor, angle=total_angle, length=bend_length)
                        bend.path.append(start_point)
                        bend.path.append(end_point)
                        bend.neighbors = neighbors
                        bends.append(bend)
                        continue

                bend = self.extract_bend(node, node_hash, surface_handle, thickness, transformations=transformations, reversed=reversed, display=display, k_factor=k_factor)
                bend.neighbors = neighbors
                bends.append(bend)

        common_id = 1
        common_bends = {}
        for bend in bends:

            # Add same common_id to bends with same neigbors
            if bend.neighbors in common_bends:
                bend.common_id = common_bends[bend.neighbors]
            else:
                common_bends[bend.neighbors] = common_id
                bend.common_id = common_id
                common_id += 1

            if display:
                bend_line = GC_MakeSegment(gp_Pnt(bend.path[0][0], bend.path[0][1], 0), gp_Pnt(bend.path[1][0], bend.path[1][1], 0))
                bend_edge = BRepBuilderAPI_MakeEdge(bend_line.Value()).Edge()

                if bend.angle > 0:
                    display.DisplayShape(bend_edge, update=True, color="orange")
                else:
                    display.DisplayShape(bend_edge, update=True, color="green")

        return bends


    def extract_all(self, graph, surface_handle, transformations=[]):
        """
        :return: create ordered wires of all connected edges by removing the seams.
        Tranformations can be passed and applied to edges before they are joined to
        a wire.
        """
        bends = []
        used_edge_hashes = set()

        # Loop over all nodes (faces) in the graph
        for node_hash in graph.nodes():
            node = graph.nodes[node_hash]

            # Loop over all edges, with internal wires grouped
            for edge, is_first, is_reversed in face_edges(node["shape"]):
                edge_hash = shape_hash(edge)

                if edge_hash in used_edge_hashes:
                    continue

                else:
                    used_edge_hashes.add(edge_hash)


    def get_sheet_base(self, min_thickness=1e-3, TOLLERANCE=1e-6, display=None):
        """
        Try to recognize faces that could belong to a sheet metal part and the
        distance between them indicating the thickness (uniform thickness expected)
        """
        thickness = float("inf")
        second_hash = None

        used_hashes = set()
        sorted_areas = sorted(self.areas, key=lambda x: x[0], reverse=True)

        # First side (largest face)
        first_area, first_hash = sorted_areas[0]
        first_node = self.C1_faces.nodes[first_hash]
        first_face = first_node["shape"]
        first_point = mid_point(first_face)
        first_normal = calculating_normal_at_point(first_face, first_point)

        if display:
            display.DisplayShape(first_face, update=True, color="red")

        # Find opposite face
        used_hashes.add(first_hash)
        for i in range(1, len(sorted_areas)):
            current_area, current_hash = sorted_areas[i]
            current_node = self.C1_faces.nodes[current_hash]

            if current_hash in used_hashes:
                continue

            used_hashes.add(current_hash)
            if first_node["convexity"].value == -current_node["convexity"].value:
                current_face = current_node["shape"]
                current_surface_handle = face_surface_handle(current_face)

                ray = Geom_Line(gp_Lin(first_point, gp_Dir(first_normal)))
                intersection = GeomAPI_IntCS(ray, current_surface_handle)

                if not intersection.IsDone() or intersection.NbPoints() == 0:
                    continue

                index = 1
                _, _, closest = intersection.Parameters(index)
                for i in range(1, intersection.NbPoints()):
                    u, v, w = intersection.Parameters(i + 1)

                    if w < 0 and abs(w) < abs(closest):
                        index = i + 1
                        closest = w

                u, v, w = intersection.Parameters(index)

                # New face is opposite of face not behind it
                if w >= 0:
                    continue

                shape_analysis = ShapeAnalysis_Surface(current_surface_handle)
                current_point = shape_analysis.Value(gp_Pnt2d(u, v))
                current_thickness = first_point.Distance(current_point)
                current_normal = calculating_normal_at_point(current_face, current_point)

                if (first_normal.IsOpposite(current_normal, 3.14 / 180)):

                    # TODO: testing
                    # Check if face has all concave edges
                    is_embossing = True
                    is_concave = 0
                    hash_a = current_hash
                    for hash_b in self.C0_faces[hash_a]:
                        edge = self.C0_faces[hash_a][hash_b]

                        if edge["convexity"].value == 1:
                            is_concave += 1

                        else:
                            is_concave -= 1

                        # Edge is concave
                        # if edge["convexity"].value != 1:
                        #     is_embossing = False
                        #     break

                    is_embossing = (is_concave >= 0)


                    # Find closest opposite value but not on the same plane
                    if current_thickness + TOLLERANCE < thickness and current_thickness >= min_thickness and not is_embossing:
                        logger.info("thickness is better: {}".format(current_thickness))
                        thickness = current_thickness
                        second_hash = current_hash

        if thickness == float("inf"):
            thickness = 0.0

        elif display:
            second_node = self.C1_faces.nodes[second_hash]
            second_face = second_node["shape"]
            display.DisplayShape(second_face, update=True, color="green")

        logger.info("Detected thickness: %0.2f" % (thickness))
        return first_hash, second_hash, thickness


    def get_chamfered_edges(self, graph):
        feature_graph = self.C0_faces.copy()

        boundary_edges = nx.edge_boundary(feature_graph, graph.nodes())
        for node_a, node_b in boundary_edges:
            edge = self.C0_faces[node_a][node_b]

            if abs(abs(edge["angle"]) - math.pi / 2) < (math.pi / 180):
                logger.debug("SQUARE", edge)
                display.DisplayShape(edge["shape"], update=True, color="green")

                # if node_a in self.node_labels.keys():
                #     display.DisplayShape(feature_graph.nodes[node_b]["shape"], update=True, color="red")
                # else:
                #     display.DisplayShape(feature_graph.nodes[node_a]["shape"], update=True, color="red")

            elif abs(abs(edge["angle"]) - math.pi / 4) < (math.pi / 180):
                logger.debug("FORTYFIVE", edge)
                display.DisplayShape(edge["shape"], update=True, color="blue")

                # if node_a in self.node_labels.keys():
                #     display.DisplayShape(feature_graph.nodes[node_b]["shape"], update=True, color="blue")
                # else:
                #     display.DisplayShape(feature_graph.nodes[node_a]["shape"], update=True, color="blue")

            else:
                logger.debug("OTHER", edge)
                display.DisplayShape(edge["shape"], update=True, color="red")

        # feature_graph.remove_nodes_from(self.node_labels.keys())


    def analyze_feature(self, component, nodes_a, nodes_b):
        loop_a = {"concave": False, "convex": True, "fillet": False, "chamfer": False}
        loop_b = {"concave": False, "convex": True, "fillet": False, "chamfer": False}

        # feature = {"top": False, "bottom": False, "chamfer": False, "fillet": False, }


        boundary_edges = nx.edge_boundary(self.C0_faces, component)
        for face_a, face_b in boundary_edges:
            edge = self.C0_faces[face_a][face_b]

            if face_a in nodes_a or face_b in nodes_a:

                if edge["convexity"].value == 1:
                    loop_a["concave"] = True
                    loop_a["convex"] = False

                elif edge["convexity"].value == 0:
                    if face_a in nodes_a:
                        face_node = self.C0_faces.nodes[face_a]
                        face_node["convexity"]

                    else:
                        pass


    def get_feature_extrema(self, base_hash, component):
        base_node = self.C0_faces.nodes[base_hash]
        base_face = base_node["shape"]
        base_point = mid_point(base_face)
        base_normal = calculating_normal_at_point(base_face, base_point)

        minimum = float("inf")
        maximum = float("-inf")
        minimum = 0.0
        maximum = 0.0

        # surface_handle = face_surface_handle(base_face)
        # ray = Geom_Line(gp_Lin(base_point, gp_Dir(base_normal)))

        # Find opposite face
        for node_hash in component:
            face_node = self.C0_faces.nodes[node_hash]
            face = face_node["shape"]

            for edge, is_first, is_reversed in face_edges(face):
                # first_vertex, last_vertex = edge_end_vertices(edge, ignore_orientation=True)

                point = first_edge_point(edge)
                distance_vec = gp_Vec(base_point, point)
                distance = distance_vec.Dot(base_normal) / base_normal.Magnitude()

                if distance < minimum:
                    minimum = distance

                if distance > maximum:
                    maximum = distance

        if minimum == float("inf"):
            minimum = 0.0

        if maximum == float("-inf"):
            maximum = 0.0

        return (minimum, maximum)


    def get_feature_loop(self, edges, side_component):
        convex_count = 0
        concave_count = 0
        smooth_count = 0
        square_count = 0

        loop_hashes = []
        base_hashes = []

        feature_base_a = None
        feature_base_b = None

        for hash_a, hash_b in edges:

            # Edge connects to top
            if hash_a in side_component or hash_b in side_component:
                edge = self.C0_faces[hash_a][hash_b]
                loop_hashes.append(edge["hash"])

                if edge["convexity"] == self.EdgeTypes.CONVEX:
                    convex_count += 1

                    if abs(abs(edge["angle"]) - math.pi / 2) <= (math.pi / 180):
                        square_count += 1

                elif edge["convexity"] == self.EdgeTypes.CONCAVE:
                    concave_count += 1

                else:
                    smooth_count += 1

                # Hash_a is a non feature face
                if hash_a in side_component:
                    if hash_a not in base_hashes:
                        base_hashes.append(hash_a)

                # Hash_b is a non feature face
                else:
                    if hash_b not in base_hashes:
                        base_hashes.append(hash_b)

        return (convex_count, concave_count, smooth_count, square_count, base_hashes, loop_hashes)





    def get_feature_groups(self, component):
        group_graph = self.C2_faces.subgraph(component)
        group_components = nx.connected_components(group_graph)
        return list(group_components)


    def get_edges_wire(self, edges):
        wire_start = None
        wire_end = None
        wire_builder = BRepBuilderAPI_MakeWire()

        for edge in edges:
            first_vertex, last_vertex = edge_end_vertices(edge, ignore_orientation=False)
            first_point = BRep_Tool.Pnt(first_vertex)
            last_point = BRep_Tool.Pnt(last_vertex)

            if wire_start and wire_end:
                if wire_end.Distance(first_point) > wire_end.Distance(last_point):

                    first_point, last_point = last_point, first_point
                    edge.Reverse()

            else:
                wire_start = first_point

            wire_end = last_point
            wire_builder.Add(edge)

        if wire_builder.Error() == 0:
            return wire_builder.Wire()

        else:
            return None


    def project_features(self, features, surface_handle, unfold_a=True, transformations=[], display=None):
        logger.info("Extracting extra feature geometry")

        for feature in features:
            if feature.type == Feature.FeatureTypes.COUNTERSINK:
                self.project_feature(feature, surface_handle, unfold_a=unfold_a, transformations=transformations, display=display)

        return features


    def project_feature(self, feature, surface_handle, unfold_a=True, transformations=[], display=None):
        if unfold_a:
            base_hash = feature.base_a[0]

        else:
            base_hash = feature.base_b[0]

        # Retrieve the face the feature is cut into
        base_node = self.C0_faces.nodes[base_hash]
        base_face = base_node["shape"]

        # Project edges to the original face
        projector = BRepAlgo_NormalProjection(base_face)
        projector.Compute3d(True)

        # # Make a graph of the different continuous groups
        # graph = nx.MultiGraph()
        # for i in range(len(feature.groups)):
        #     graph.add_node(i)

        # # Extract edges not connected to a side or seams within a group
        # edges = []
        # feature_graph = self.C0_faces.subgraph(feature.component)
        # for edge in feature_graph.edges(data=True):

        #     group_a = None
        #     group_b = None
        #     for i in range(len(feature.groups)):
        #         if edge[0] in feature.groups[i] and edge[1] in feature.groups[i]:
        #             continue

        #         elif edge[0] in feature.groups[i]:
        #             group_a = i

        #         elif edge[1] in feature.groups[i]:
        #             group_b = i
                
        #     if group_a != None and group_b != None:
        #         graph.add_edge(group_a, group_b, shape=edge[2]["shape"])
        #         projector.Add(edge[2]["shape"])


        # Loop over all edges (C0_faces.edges does not accout for two shapes linked by two different edges)
        options = {}
        for feature_hash in feature.component:
            feature_face = self.C0_faces.nodes[feature_hash]["shape"]
            face_hash = shape_hash(feature_face)

            # Determine group the face is in
            for i in range(len(feature.groups)):
                if face_hash in feature.groups[i]:
                    group = i
                    break

            edge_explorer = TopExp_Explorer(feature_face, TopAbs_EDGE)
            while edge_explorer.More():
                edge = topods.Edge(edge_explorer.Current())
                edge_hash = shape_hash(edge)

                if edge_hash in options:

                    # Edge covers two different groups
                    if group != options[edge_hash]:
                        projector.Add(edge)

                    # Edge connects two faces in the same group
                    else:
                        del options[edge_hash]

                else:
                    options[edge_hash] = group

                edge_explorer.Next()

# <<<<<<< HEAD
# =======
#                 elif edge[1] in feature.groups[i]:
#                     group_b = i

#             if group_a != None and group_b != None:
#                 graph.add_edge(group_a, group_b, shape=edge[2]["shape"])
#                 projector.Add(edge[2]["shape"])
# >>>>>>> 6f775880ebbd14b9b51c0eff08b58db68080bcc7


        # Perform projection
        projector.Build()
        projected_edges = projector.Projection()

        edges = []
        edge_explorer = TopExp_Explorer(projected_edges, TopAbs_EDGE)
        while edge_explorer.More():
            edge = topods.Edge(edge_explorer.Current())

            if surface_handle and base_hash in transformations:
                local_edge = self.transformed_edge(edge, base_face, surface_handle, transformations=transformations[base_hash])
                edges.append(local_edge)

            edge_explorer.Next()

        wire = self.get_edges_wire(edges)

        try:
            wire = fix_shape(wire)
        except:
            logging.warning("could not close feature wire")
            pass

        if wire:
            feature.projections = [wire]

        return feature


    def project_feature_old(self, base_hash, component, display=None):
        from OCC.Core.HLRBRep import HLRBRep_Algo, HLRBRep_HLRToShape
        from OCC.Core.HLRAlgo import HLRAlgo_Projector
        from OCC.Core.GCPnts import GCPnts_QuasiUniformDeflection

        # Preprocessing base
        base_node = self.C0_faces.nodes[base_hash]
        base_face = base_node["shape"]
        base_point = mid_point(base_face)
        base_normal = calculating_normal_at_point(base_face, base_point)

        # Stitch feature
        sewing = BRepBuilderAPI_Sewing()
        for feature_hash in component:
            feature_face = self.C0_faces.nodes[feature_hash]["shape"]
            sewing.Add(feature_face)
        sewing.Perform()
        shape = sewing.SewedShape()

        # logger.debug("SHAPE: ")
        # logger.debug(shape)

        if display:
            display.DisplayShape(shape, update=True, color="green")

        hlr = HLRBRep_Algo()
        hlr.Add(shape)

        projector = HLRAlgo_Projector(gp_Ax2(base_point, gp_Dir(base_normal)))

        hlr.Projector(projector)
        hlr.Update()
        hlr.Hide()

        hlr_shapes = HLRBRep_HLRToShape(hlr)

        visible = []

        visible_sharp_edges = hlr_shapes.VCompound()
        if visible_sharp_edges:
            visible.append(visible_sharp_edges)

        # visible_smooth_edges = hlr_shapes.Rg1LineVCompound()
        # if visible_smooth_edges:
        #     visible.append(visible_smooth_edges)

        visible_contour_edges = hlr_shapes.OutLineVCompound()
        if visible_contour_edges:
            visible.append(visible_contour_edges)

        if display:
            for edge in visible:
                display.DisplayShape(edge, update=True, color="orange")



        # logger.debug(len(visible))


    def get_connecting_features(self, graph_a, graph_b, thickness, display=None, max_groups=None, max_faces=None, ignore_complex=True, surface_handle=None, transformations=[], TOLLERANCE=1e-6):
        features_graph = self.C0_faces.copy()

        nodes_a = graph_a.nodes()
        nodes_b = graph_b.nodes()

        features_graph.remove_nodes_from(nodes_a)
        features_graph.remove_nodes_from(nodes_b)

        # All connected components not on one of the two graphs in argument
        featured_edges = set()
        feature_components = nx.connected_components(features_graph)

        index = 0
        features = []
        for feature_component in feature_components:
            # logger.info("__________________________")
            # logger.info("[+] checking feature {0}".format(index))
            # logger.info(" - {0} faces".format(len(feature_component)))

            # limit feature extraction by number of faces
            if max_faces == None or len(feature_component) <= max_faces:
                groups = self.get_feature_groups(feature_component)
                group_count = len(groups)
                # logger.info(" - {0} groups".format(group_count))

                # limit feature extraction by number of groups
                if max_groups == None or group_count <= max_groups:

                    boundary_edges_a = nx.edge_boundary(self.C0_faces, feature_component)
                    convex_a, concave_a, smooth_a, square_count_a, base_hashes_a, loop_hashes_a = self.get_feature_loop(boundary_edges_a, nodes_a)

                    boundary_edges_b = nx.edge_boundary(self.C0_faces, feature_component)
                    convex_b, concave_b, smooth_b, square_count_b, base_hashes_b, loop_hashes_b = self.get_feature_loop(boundary_edges_b, nodes_b)

                    # logger.info(" - {0}, {1}, {2}, {3}".format(convex_a, concave_a, smooth_a, square_count_a))
                    # logger.info(" - {0}, {1}, {2}, {3}".format(convex_b, concave_b, smooth_b, square_count_b))

                    # Skip feature if it crosses multiple faces on one of the sides
                    if ignore_complex:
                        if len(base_hashes_a) > 1 or len(base_hashes_b) > 1:
                            continue

                    extrusion = None
                    embossing = None
                    chamfer = None
                    chamfer_a = False
                    chamfer_b = False

                    # single sided feature on top
                    if convex_b + concave_b + smooth_b == 0:
                        extrusion_mimumum, extrusion_maximum = self.get_feature_extrema(base_hashes_a[0], feature_component)
                        # logger.info(" -> min: {:0.2f}, max: {:0.2f}".format(extrusion_mimumum, extrusion_maximum))

                        # Extrusion on top
                        if extrusion_maximum >= TOLLERANCE:
                            extrusion = extrusion_maximum
                            logger.debug("Extrusion top {:0.2f}mm".format(extrusion))

                        # Embossing on top
                        elif extrusion_mimumum <= -TOLLERANCE:
                            embossing = -extrusion_mimumum
                            logger.debug("Embossing top {:0.2f}mm".format(embossing))


                    # single sided feature on bottom
                    elif convex_a + concave_a + smooth_a == 0:
                        extrusion_mimumum, extrusion_maximum = self.get_feature_extrema(base_hashes_b[0], feature_component)
                        # logger.info(" -> min: {:0.2f}, max: {:0.2f}".format(extrusion_mimumum, extrusion_maximum))

                        # Extrusion on bottom
                        if extrusion_maximum >= TOLLERANCE:
                            extrusion = -extrusion_maximum
                            logger.debug("Extrusion bottom {:0.2f}mm".format(extrusion))

                        # Embossing on bottom
                        elif extrusion_mimumum <= -TOLLERANCE:
                            embossing = extrusion_mimumum
                            logger.debug("Embossing bottom {:0.2f}mm".format(embossing))


                    # double sided feature on top
                    elif concave_a + smooth_a > 0:
                        extrusion_mimumum, extrusion_maximum = self.get_feature_extrema(base_hashes_a[0], feature_component)
                        # logger.info(" -> min: {:0.2f}, max: {:0.2f}".format(extrusion_mimumum, extrusion_maximum))

                        # Out top surface
                        if extrusion_maximum >= TOLLERANCE:
                            extrusion = extrusion_maximum
                            logger.debug("Extrusion top {:0.2f}mm".format(extrusion))

                        # Extrusion under bottom surface
                        elif extrusion_mimumum + thickness <= -TOLLERANCE:
                            extrusion = extrusion_mimumum + thickness
                            logger.debug("Extrusion bottom {:0.2f}mm".format(extrusion))

                        else:
                            embossing = 0.0
                            extrusion = 0.0
                            logger.info("Flush feature {:0.2f}mm".format(extrusion))


                    # double sided feature on bottom
                    elif concave_b + smooth_b > 0:
                        extrusion_mimumum, extrusion_maximum = self.get_feature_extrema(base_hashes_b[0], feature_component)
                        # logger.info(" -> min: {:0.2f}, max: {:0.2f}".format(extrusion_mimumum, extrusion_maximum))

                        # Out bottom surface
                        if extrusion_maximum >= TOLLERANCE:
                            extrusion = -extrusion_maximum
                            logger.debug("Extrusion bottom {:0.2f}mm".format(extrusion))

                        # Extrusion over top surface
                        elif extrusion_mimumum + thickness <= -TOLLERANCE:
                            extrusion = -extrusion_mimumum + thickness
                            logger.debug("Extrusion top {:0.2f}mm".format(extrusion))

                        else:
                            embossing = 0.0
                            extrusion = 0.0
                            logger.debug("Flush feature {:0.2f}mm".format(extrusion))

                    # through hole with possible chamfers
                    elif group_count >= 2:
                        # logger.info(" -> maybe an chamfer")

                        if convex_a != square_count_a or convex_b != square_count_b:
                            logger.debug("Chamfer feature")
                            # logger.info(" - {0}, {1}, {2}, {3}".format(convex_a, concave_a, smooth_a, square_count_a))
                            # logger.info(" - {0}, {1}, {2}, {3}".format(convex_b, concave_b, smooth_b, square_count_b))
                            chamfer_a = convex_a != square_count_a
                            chamfer_b = convex_b != square_count_b

                            chamfers = []
                            if convex_a != square_count_a:
                                for group in groups:
                                    chamfer_mimumum, _ = self.get_feature_extrema(base_hashes_a[0], group)
                                    chamfers.append(chamfer_mimumum)

                                chamfer_a = max(chamfers)

                            chamfers = []
                            if convex_b != square_count_b:
                                for group in groups:
                                    chamfer_mimumum, _ = self.get_feature_extrema(base_hashes_b[0], group)
                                    chamfers.append(chamfer_mimumum)

                                chamfer_b = max(chamfers)

                    if extrusion != None or embossing != None or chamfer_a or chamfer_b:
                        # feature = {
                        #     "loop_a": loop_hashes_a,
                        #     "loop_b": loop_hashes_b,
                        #     "extrusion": extrusion,
                        #     "embossing": embossing,
                        #     "chamfer": embossing,
                        #     "chamfer_a": chamfer_a,
                        #     "chamfer_b": chamfer_b,
                        #     "wires": []
                        # }
                        feature = Feature(component=feature_component, groups=groups, base_a=base_hashes_a, base_b=base_hashes_b, loop_a=loop_hashes_a, loop_b=loop_hashes_b, extrusion=extrusion, embossing=embossing, chamfer_a=chamfer_a, chamfer_b=chamfer_b, wires=[])
                        features.append(feature)
                        featured_edges = featured_edges.union(loop_hashes_a)
                        featured_edges = featured_edges.union(loop_hashes_b)


                    if extrusion != None:
                        for node_hash in feature_component:
                            face_node = self.C0_faces.nodes[node_hash]

                            if display:
                                display.DisplayShape(face_node["shape"], update=True, color="orange")

                    if embossing != None:
                        for node_hash in feature_component:
                            face_node = self.C0_faces.nodes[node_hash]

                            if display:
                                display.DisplayShape(face_node["shape"], update=True, color="red")

                    if chamfer_a or chamfer_b:
                        for node_hash in feature_component:
                            face_node = self.C0_faces.nodes[node_hash]

                            # if display:
                            #     display.DisplayShape(face_node["shape"], update=True, color="blue")

            index += 1

        return features, featured_edges


def stitch_shape(shape):
    sewing = BRepBuilderAPI_Sewing()
    face_explorer = TopExp_Explorer(shape, TopAbs_FACE)

    while face_explorer.More():
        current_face = topods.Face(face_explorer.Current())
        sewing.Add(current_face)
        face_explorer.Next()

    sewing.Perform()
    sewed_shape = sewing.SewedShape()

    if sewed_shape.ShapeType() != TopAbs_SHELL:
        return None

    shell = topods.Shell(sewed_shape)
    builder = BRepBuilderAPI_MakeSolid(shell)
    shape = builder.Shape()

    if shape.ShapeType() == TopAbs_SOLID:
        return shape

    else:
        return None


def get_largest_solid(shape):
    solid = None
    max_volume = 0
    solid_explorer = TopExp_Explorer(shape, TopAbs_SOLID)
    while solid_explorer.More():
        current_solid = topods.Solid(solid_explorer.Current())
        current_volume = get_volume(current_solid)

        if current_volume > max_volume:
            max_volume = current_volume
            solid = current_solid

        solid_explorer.Next()

    return solid


def stitch_shell(shape):
    solid = None
    max_volume = 0
    shell_explorer = TopExp_Explorer(shape, TopAbs_SHELL)
    while shell_explorer.More():
        current_shell = topods.Shell(shell_explorer.Current())
        solid = stitch_shape(current_shell)
        shell_explorer.Next()

        if solid:
            break

    return solid


def get_solid_from_shape(shape):
    shapeType = shape.ShapeType()

    if shapeType == TopAbs_SOLID:
        logger.info("Returning original shape as SOLID")
        return shape

    elif shapeType == TopAbs_SHELL:
        logger.info("Stitching faces in SHELL to extract a valid SOLID")
        return stitch_shape(shape)

    elif shapeType == TopAbs_COMPOUND:
        logger.info("Trying to extract largest SOLID from COMPOUND shape")
        solid = get_largest_solid(shape)

        if not solid:
            logger.info("Reverting to stitching shells to extract SOLID")
            solid = stitch_shell(shape)

            if not solid:
                logger.info("Reverting to stitching faces to extract SOLID")
                solid = stitch_shape(shape)

        return solid

    elif shapeType == TopAbs_COMPSOLID:
        logger.info("Trying to extract largest SOLID from COMPSOLID shape")
        solid = get_largest_solid(shape)

        if not solid:
            logger.info("Reverting to stitching faces to extract SOLID")
            solid = stitch_shape(shape)

        return solid

    else:
        logger.info("Unsupported shape. Can not extract a valid solid.")
        return None


def shapeTypeString(shape):
    st = shape.ShapeType()
    s = "Unknown"
    if st == TopAbs_VERTEX:
        s = "Vertex"
    if st == TopAbs_SOLID:
        s = "Solid"
    if st == TopAbs_EDGE:
        s = "Edge"
    if st == TopAbs_FACE:
        s = "Face"
    if st == TopAbs_SHELL:
        s = "Shell"
    if st == TopAbs_WIRE:
        s = "Wire"
    if st == TopAbs_COMPOUND:
        s = "Compound"
    if st == TopAbs_COMPSOLID:
        s = "Compsolid"
    return s


# Get the center line of a face (e.g. bend line of a bend face)
# -> Edge
from OCC.Core.GC import GC_MakeSegment
from OCC.Core.TopAbs import TopAbs_VERTEX
from OCC.Core.ShapeAnalysis import ShapeAnalysis_Surface
def face_center_line(face, trim_line=True):
    face_domain = domain(face)
    adaptor = BRepAdaptor_Surface(face)

    xMid = (face_domain[0] + face_domain[1]) / 2.
    start = adaptor.Value(xMid, face_domain[2])
    end = adaptor.Value(xMid, face_domain[3])

    line = GC_MakeSegment(start, end)
    edge = BRepBuilderAPI_MakeEdge(line.Value()).Edge()

    if trim_line:
        yMin = float("inf")
        yMax = float("-inf")

        surface_handle = BRep_Tool.Surface(face)
        interference = boolean_common(edge, face)
        topo_explorer = TopExp_Explorer(interference, TopAbs_VERTEX)
        while topo_explorer.More():
            current_vertex = topods.Vertex(topo_explorer.Current())
            current_point = BRep_Tool.Pnt(current_vertex)

            _, yCurrent = point_to_parameter(current_point, surface_handle)
            if yCurrent < yMin:
                yMin = yCurrent
                start = current_point

            elif yCurrent > yMax:
                yMax = yCurrent
                end = current_point

            topo_explorer.Next()

        line = GC_MakeSegment(start, end)
        edge = BRepBuilderAPI_MakeEdge(line.Value()).Edge()

    return edge

# Boolean intersect (common area) of two shapes
from OCC.Core.BRepAlgoAPI import BRepAlgoAPI_Common
def boolean_common(shape, other_shape):
    common = BRepAlgoAPI_Common(shape, other_shape)
    # common.SetFuzzyValue(1e-3)

    return common.Shape()


def referse_feature(feature):
    if feature["extrusion"]:
        feature["extrusion"] *= -1

    if feature["embossing"]:
        feature["embossing"] *= -1

    if feature["chamfer"]:
        feature["chamfer"] *= -1



    return {
        "loop_a": feature["loop_b"],
        "loop_b": feature["loop_a"],
        "extrusion": feature["extrusion"],
        "embossing": feature["embossing"],
        "chamfer": feature["chamfer"],
        "chamfer_a": feature["chamfer_b"],
        "chamfer_b": feature["chamfer_a"],
        "wires": feature["wires"]
    }

#===========================================================================
# Test function for use with CLI
#===========================================================================
def main(
        step_path,
        output_dir,
        align=True,
        k_factor=0.5,
        repair=True,
        display=None,
        material=None,
        check_features=False,
        combine_bends=True,
        bysoft_autopart=False,
        label_text=None,
        label_height=20.0,

        absolute_volume_threshold=5.0,
        relative_volume_threshold=0.025,
    ):

    # Import step file

    try:
        # with open(os.devnull, 'w') as devnull:
        #     with redirect_stdout(devnull):

        with suppress_stdout_stderr():
                shape = import_step(step_path)

    except Exception:
        logger.error("Could not read file and/or assembly structure")
        # traceback.print_exc()
        sys.exit(1)

    solid = None
    for solid in get_shape_solids(shape, sort=True, repair=repair):
        break

    if not solid:
        logger.error("Could not extract a valid solid for unfolding")
        sys.exit(1)

    try:
        aag = AdjacencyGraph(solid)
        aag.full()
        aag.smooth()
        aag.grouped()

    except Exception:
        logger.error("Could not compute shape topology")
        # traceback.print_exc()
        sys.exit(1)

    try:
        shape_data = Shape()
        shape_data.volume = get_volume(solid)
        shape_data.area = sum([areas[0] for areas in aag.areas])
        shape_data.width, shape_data.height, shape_data.length = get_boundingbox_dimensions(solid, use_mesh=False)

        min_thickness = 2 * shape_data.volume / shape_data.area
        first_hash, second_hash, thickness = aag.get_sheet_base(min_thickness=min_thickness, display=display)

        if not thickness:
            logger.warning("Could not detect shape thickness and/or base flange")
            sys.exit(1)

        # Get first side graph
        graph_a = aag.get_connected_subgraph(first_hash, ignore_complex=True, display=display)

        # Get features
        unfold_a = True
        features = []
        featured_edges = []
        if check_features:
            graph_b = aag.get_connected_subgraph(second_hash, ignore_complex=True, display=display)
            features, featured_edges = aag.get_connecting_features(graph_a, graph_b, thickness, display=display)

            features_a = 0
            features_b = 0
            for feature in features:
                if feature.top:
                    features_a += 1

                if feature.bottom:
                    features_b += 1

            if features_a > 0 and features_b > 0:
                logger.warning("Features detected on both sides of part. Only one side visible in 2D.")

            if features_b > features_a:
                logger.info("Unfolding second side of shape, because it contains more features")
                unfold_a = False

        # compute transformations to unfold graph
        if unfold_a:
            surface_handle, transformations, base_reversed = aag.unfold_graph(graph_a, thickness, base_hash=first_hash, align=align, display=None, k_factor=k_factor)
            wires, open_wire_count, loops = aag.extract_wires(graph_a, surface_handle, thickness, transformations=transformations, k_factor=k_factor, features=features, featured_edges=featured_edges, display=display)
            bends = aag.extract_bends(graph_a, surface_handle, thickness, transformations=transformations, reversed=base_reversed, display=display, k_factor=k_factor, combine_bends=combine_bends)
            shape_data.bends = bends

        else:
            for feature in features:
                feature.reverse()

            surface_handle, transformations, base_reversed = aag.unfold_graph(graph_b, thickness, base_hash=second_hash, align=align, display=None, k_factor=k_factor)
            wires, open_wire_count, loops = aag.extract_wires(graph_b, surface_handle, thickness, transformations=transformations, k_factor=k_factor, features=features, featured_edges=featured_edges, display=display)
            bends = aag.extract_bends(graph_b, surface_handle, thickness, transformations=transformations, reversed=base_reversed, display=display, k_factor=k_factor, combine_bends=combine_bends)
            shape_data.bends = bends


        # part is a bent or flat part
        if open_wire_count != 0:
            logger.warning("Part can not be interpreted as a sheet metal part")
            sys.exit(1)

        # Analyse result
        max_size = 0
        max_index = 0
        bbox = Bnd_Box()
        for i in range(len(loops)):
            brepbndlib.Add(loops[i].wires[0], bbox)
            bb_xmin, bb_ymin, _, bb_xmax, bb_ymax, _ = bbox.Get()
            wire_size = (bb_xmax - bb_xmin) * (bb_ymax - bb_ymin)

            if wire_size > max_size:
                max_size = wire_size
                max_index = i

        # Generate single unfolded face based on wires
        # max_loop = loops.pop(max_index)
        make_face = BRepBuilderAPI_MakeFace(loops[max_index].wires[0])
        for i in range(len(loops)):
            if i == max_index:
                if display:
                    display.DisplayShape(loops[i].wires[0], update=True, color="red", transparency=0.5)

            elif loops[i].feature:
                if display:
                    display.DisplayShape(loops[i].wires[0], update=True, color="green", transparency=0.5)

            elif i != max_index:
                make_face.Add(loops[i].wires[0])

                if display:
                    display.DisplayShape(loops[i].wires[0], update=True, color="blue", transparency=0.5)

        face = make_face.Face()
        face = fix_shape(face)
        face_area = get_area(face)
        face_volume = face_area * thickness
        volume_error = shape_data.volume - face_volume

        logger.info("Volume difference: {:0.2f} ({:0.2f}%)".format(volume_error, volume_error / shape_data.volume * 100))

        if relative_volume_threshold:
            if abs((volume_error) / shape_data.volume) > relative_volume_threshold:
                logger.error("Volume error to large after unfolding")
                sys.exit(1)

        if absolute_volume_threshold:
            if abs(volume_error) > absolute_volume_threshold:
                logger.warning("Volume difference after flattening {:0.2f}mm^3 should be checked".format(volume_error))

        logger.info("Sheet metal part (with {} bends)".format(len(bends)))

        file_name = os.path.basename(step_path)
        file_name, extension = file_name.rsplit(".", 1)
        output_file = "{}.dxf".format(file_name)
        output_path = os.path.join(output_dir, output_file)

        pattern = Pattern(thickness=thickness, wires=wires, bends=bends, loops=loops, material=material)
        pattern.parse_wires()

        if label_text:
            pattern.place_label(text=label_text, font_height=label_height, gravity_angle=4.7)

        if bysoft_autopart:
            pattern.save(output_path, add_text=False, dxf_type="DESIGNER")

        else:
            pattern.save(output_path, add_text=False, dxf_type="CYCAD")


    except Exception:
        logger.error("Shape could not be processed")
        # traceback.print_exc()
        sys.exit(1)



#===========================================================================
# CLI for testing
#===========================================================================
def is_dir(dirname):
    """
    Checks if a path is an actual directory
    """
    if not os.path.isdir(dirname):
        msg = "{0} is not a directory".format(dirname)
        raise argparse.ArgumentTypeError(msg)
    else:
        return os.path.abspath(os.path.realpath(os.path.expanduser(dirname)))


def is_file(filename):
    """
    Checks if a path is an actual file
    """
    if not os.path.isfile(filename):
        msg = "{0} is not a file".format(filename)
        raise argparse.ArgumentTypeError(msg)
    else:
        return os.path.abspath(os.path.realpath(os.path.expanduser(filename)))


display, start_display, add_menu, add_function_to_menu = (None, None, None, None)
if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("-f", "--file", help="input file [.stp, .step]", type=is_file)
    parser.add_argument("-d", "--directory", help="input directory", type=is_dir)
    parser.add_argument("-a", "--align", help="align output to 2D plane", action='store_true')
    parser.add_argument("-r", "--display", help="display graphical interface", action='store_true')
    parser.add_argument("-p", "--profile", help="generate call graph for optimization", action='store_true')
    parser.add_argument("-o", "--output", help="the output file to be generated", action='store_true')
    parser.add_argument("-k", "--k_factor", help="k-factor to use with all bends and their drawn inner radius", type=float, default=0.5)
    args = parser.parse_args()

    # Add single file path
    file_paths = []
    if args.file:
        file_paths.append(args.file)

    # Add files from directory
    if args.directory:
        for file_name in os.listdir(args.directory):
            if file_name.lower().endswith((".stp", ".step")):
                file_path = os.path.join(args.directory, file_name)
                file_paths.append(file_path)

    # Exit if no input is found
    if len(file_paths) == 0:
        parser.print_help()

    # Prepare GUI in case of displaying
    if args.display:
        import OCC.Display.SimpleGui

        for file_path in file_paths:
            display, start_display, add_menu, add_function_to_menu = OCC.Display.SimpleGui.init_display("qt-pyqt5")
            main(file_path, align=args.align, display=True, output=args.output, k_factor=args.k_factor)
            start_display()

    # Loop over files and prolfile
    elif args.profile:
        from pycallgraph import PyCallGraph
        from pycallgraph.output import GraphvizOutput
        with PyCallGraph(output=GraphvizOutput()):

            for file_path in file_paths:
                main(file_path, align=args.align, display=False, output=args.output, k_factor=args.k_factor)

    # Loop over files without prolfiling
    else:
        for file_path in file_paths:
            main(file_path, align=args.align, display=False, output=args.output, k_factor=args.k_factor)
