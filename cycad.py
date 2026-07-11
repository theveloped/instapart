#!/usr/bin/env python

# compatibility imports
from __future__ import print_function

import os
import math
import uuid
import copy
import networkx as nx
from enum import Enum

from OCC.Core.IFSelect import IFSelect_RetDone
from OCC.Core.ShapeFix import ShapeFix_Shape, ShapeFix_Wire
from OCC.Core.ShapeAnalysis import ShapeAnalysis_WireOrder
from OCC.Core.GCPnts import GCPnts_AbscissaPoint
from OCC.Core.CPnts import CPnts_UniformDeflection
from OCC.Core.GeomAdaptor import GeomAdaptor_Curve
from OCC.Core.GeomProjLib import geomprojlib
from OCC.Core.BRep import BRep_Tool
from OCC.Core.IFSelect import IFSelect_ItemsByEntity

from OCC.Core.Bnd import Bnd_Box
from OCC.Core.BRepBndLib import brepbndlib
from OCC.Core.BRepBuilderAPI import (
    BRepBuilderAPI_Transform,
    BRepBuilderAPI_GTransform,
    BRepBuilderAPI_MakeEdge,
    BRepBuilderAPI_MakeWire,
    BRepBuilderAPI_MakeFace,
    BRepBuilderAPI_MakeVertex,
    BRepBuilderAPI_Sewing,
    BRepBuilderAPI_MakeSolid,
)

from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakePrism
from OCC.Core.STEPControl import STEPControl_Reader
from OCC.Core.TopAbs import (
    TopAbs_VERTEX,
    TopAbs_EDGE,
    TopAbs_FACE,
    TopAbs_WIRE,
    TopAbs_SHELL,
    TopAbs_SOLID,
    TopAbs_COMPOUND,
    TopAbs_COMPSOLID,
)
from OCC.Core.TopoDS import (
    topods,
)
from OCC.Core.GProp import GProp_GProps
from OCC.Core.BRepGProp import brepgprop

from OCC.Core.gp import (
    gp_Trsf,
    gp_Ax1,
    gp_Pln,
    gp_Ax3,
    gp_GTrsf,
    gp_Vec,
    gp_Dir,
    gp_Pnt,
    gp_Origin,
    gp_DZ,
    gp_Ax2d,
    gp_Pnt2d,
    gp_Dir2d,
    gp_XY,
    gp_Vec2d,
    gp_DX,
    gp_Lin,
    gp_GTrsf2d,
    gp_Mat,
    gp_Trsf2d,
    gp_Mat2d,
)

from OCC.Core.BRep import BRep_Tool
from OCC.Core.ShapeAnalysis import ShapeAnalysis_Surface
from OCC.Core.GeomLProp import GeomLProp_SLProps

from OCC.Core.BRepAdaptor import BRepAdaptor_Curve
from OCC.Core.BRepLProp import BRepLProp_CLProps
from OCC.Core.GeomLib import GeomLib_IsPlanarSurface, geomlib

from OCC.Core.BRepTools import breptools
from OCC.Core.BRepAdaptor import BRepAdaptor_Surface

from OCC.Core.TopExp import TopExp_Explorer, topexp
from OCC.Core.Geom import Geom_Line
from OCC.Core.GeomAPI import GeomAPI_IntCS


from lxml import etree
import io as StringIO
import ezdxf
from ezdxf.enums import TextEntityAlignment

from models import Colors, Feature
from geometry import Point, Path, almostEqual, almostZero
from label import main as label_main

TOLLERANCE = 1e-6

import logging
logger = logging.getLogger()

# _geom_types_a = ['LINE', 'CIRCLE', 'ELLIPSE', 'HYPERBOLA', 'PARABOLA',
#                  'beziercurve', 'bsplinecurve', 'othercurve']

# _geom_types_b = [GeomAbs_Line, GeomAbs_Circle, GeomAbs_Ellipse,
#                  GeomAbs_Hyperbola, GeomAbs_Parabola, GeomAbs_BezierCurve,
#                 GeomAbs_BSplineCurve, GeomAbs_OtherCurve]

def polar_point(radius, angle):
    x = radius * math.cos(angle)
    y = radius * math.sin(angle)

    return Point(x, y)


def segment_to_point(segment, point):
    segVector = segment[1] - segment[0]
    distance = segVector.y * point.x - segVector.x * point.y + segment[1].x * segment[0].y - segment[0].x * segment[1].y
    distance = distance / segVector.distance()

    return distance


# Determines if two floats are approximately equal
def almostEqual(x, y, EPSILON=1e-9):
    return abs(x - y) < EPSILON


# Determines if two floats are approximately equal
def almostZero(x, EPSILON=1e-9):
    return abs(x) < EPSILON


# Determines if two floats are approximately equal
def equalPoint(pointA, pointB, EPSILON=1e-9):
  return almostEqual(pointA[0], pointB[0], EPSILON=EPSILON) and almostEqual(pointA[1], pointB[1], EPSILON=EPSILON)


class EdgeTypes(Enum):
    LINE = 0
    CIRCLE = 1
    ELLIPSE = 2
    HYPERBOLA = 3
    PARABOLA = 4
    BEZIERCURVE = 5
    BSPLINECURVE = 6
    OTHERCURVE = 7


class Entity(object):
    class EntityTypes(Enum):
        LINE = 0
        CIRCLE = 1
        POLYLINE = 2
        PATH = 3

    class FeatureTypes(Enum):
        OTHER = 0
        EMBOSSING = 1
        EXTRUSION = 2
        CHAMFER = 3
        COUNTERSINK = 4

    def __init__(self, path=None, type=None, radius=None, centroid=None, inner_radius=None, k_factor=None, angle=None, length=None, TOLLERANCE=TOLLERANCE):
        self.path = path
        if not path:
            self.path = Path()

        self.type = type
        self.radius = radius
        self.centroid = centroid

        self.approximation = None

        self.inner_radius = inner_radius
        self.k_factor = k_factor
        self.angle = angle
        self.length = length

        self.feature_type = None
        self.feature_value = None

        self.TOLLERANCE = TOLLERANCE

    def __getitem__(self,index):
        return self.path[index]

    def __setitem__(self,index,value):
        self.path[index] = value

    def __len__(self):
        return len(self.path)


    @property
    def middle(self):
        x = (self[0].x + self[1].x) / 2
        y = (self[0].y + self[1].y) / 2

        return Point(x, y)

    @property
    def orientation(self):
        x = self[0].x - self[1].x
        y = self[0].y - self[1].y

        angle = math.atan2(y, x)

        return angle



    # def is_closed(self):
    #     return equalPoint(self.path[0], self.path[-1], TOLLERANCE=self.TOLLERANCE)

    def compute_area(self, TOLLERANCE=0.1, signed=False):
        area = 0.0
        approximation = self.approximate()

        for i in range(len(approximation)):
            area += approximation[i].determinant(approximation[i + 1])

        if signed:
            return area / 2

        else:
            return abs(area / 2)


    def compute_length(self, TOLLERANCE=0.1):
        length = 0.0
        approximation = self.approximate(TOLLERANCE=TOLLERANCE)

        if self.path.isClosed():
            for i in range(len(approximation)):
                length += (approximation[i + 1] - approximation[i]).distance(squared=False)

        else:
            for i in range(len(approximation) - 1):
                length += (approximation[i + 1] - approximation[i]).distance(squared=False)

        return length


    def approximate(self, TOLLERANCE=0.1):
        # return self for linear types
        if self.type in [Entity.EntityTypes.LINE, Entity.EntityTypes.POLYLINE]:
          return self.path

        # compute approximation
        elif not self.approximation:

          # Handle circle
          if self.type == Entity.EntityTypes.CIRCLE:

            tolRadius = min(TOLLERANCE / self.radius, 1)
            maxAngle = 2 * math.acos(1 - tolRadius)
            angle = 2 * math.pi

            nParts = int(math.ceil(angle / maxAngle))
            nParts = min(nParts, 4)
            dAngle = angle / nParts

            self.approximation = Path()
            for i in range(nParts):
              point = [self.centroid[0] + self.radius * math.cos(i * dAngle)]
              point.append(self.centroid[1] + self.radius * math.sin(i * dAngle))

              self.approximation.append(point)
            self.approximation.append(self.approximation[0])


          # Parse bulges
          elif self.type == Entity.EntityTypes.PATH:
            # print "APPROXIMATION length:", len(self)

            prevPoint = self.path[0]
            self.approximation = Path()
            self.approximation.append(prevPoint)

            for i in range(1, len(self.path)):
              point = self.path[i]

              if prevPoint.bulge:
                bulge = prevPoint.bulge

                # vertex parameters
                vertex = (point - prevPoint)
                length = vertex.distance()
                vertexAngle = math.atan2(vertex.y, vertex.x)

                # compute center and radius of bulge
                sagitta = length / 2 * abs(bulge)
                radius = (math.pow(length / 2, 2) + math.pow(sagitta, 2)) / (2 * sagitta)
                angle = 4.0 * math.atan(bulge)

                if bulge < 0:
                  center = point + polar_point(radius, vertexAngle - math.pi / 2 + math.atan(bulge) * 2)
                  bulgeSign = -1
                else:
                  center = point - polar_point(radius, vertexAngle - math.pi / 2 + math.atan(bulge) * 2)
                  bulgeSign = 1

                interPoint = prevPoint - center
                start = math.atan2(interPoint.y, interPoint.x)

                # approximation
                tolRadius = min(TOLLERANCE / radius, 1)
                maxAngle = 2 * math.acos(1 - TOLLERANCE/radius)
                nParts = int(math.ceil(abs(angle / maxAngle)))
                dAngle = angle / nParts

                # print "APPROXIMATION:", nParts

                # self.approximation.append(center)
                for i in range(1, nParts):
                  approxPoint = [center[0] + radius * math.cos(i * dAngle + start)]
                  approxPoint.append(center[1] + radius * math.sin(i * dAngle + start))
                  self.approximation.append(approxPoint)

              self.approximation.append(point)
              prevPoint = point

        # Return approximation fresh or old
        return self.approximation


    def svgPath(self):
        # ["POINT", "CIRCLE", "LINE", "ARC", "SPLINE", "POLYLINE"]
        prevPoint = self[0]
        d = "M %f %f " % (prevPoint.x, prevPoint.y)

        for i in range(1, len(self)):
            point = self[i]
            length = (point - prevPoint).distance()

            # Parse a bulge
            if prevPoint.bulge and length >= self.TOLLERANCE:
                bulge = prevPoint.bulge

                # logging.info("[+] length: " + str(length))
                sagitta = length / 2 * bulge
                radius = (math.pow(length / 2, 2) + math.pow(sagitta, 2)) / (2 * sagitta)

                largeArcSweep = (abs(bulge) > 1)
                sweepFlag = (bulge >= 0)

                d += "A %f %f 0 %d %d %f %f" % (radius, radius, int(largeArcSweep), int(sweepFlag), point.x, point.y)

            # Draw straight line
            else:
                d += "L %f %f" % (point.x, point.y)

            prevPoint = point

        # Close if closed
        if self.path.isClosed():
            d += "Z"

        return d


class Pattern(object):
    def __init__(self, thickness, wires=[], bends=[], loops=[], material=None, quantity=None, date=None, TOLLERANCE=TOLLERANCE):
        self.wires = wires
        self.loops = loops
        self.bends = bends
        self.thickness = thickness
        self.material = material
        self.quantity = quantity
        self.date = date
        self.TOLLERANCE = TOLLERANCE

        self.origin = None
        self.width = None
        self.height = None

        self.contour = None
        self.holes = None
        self.other = None

        self.inner_fit_polygon = None
        self.label = {}

        # label["position"] = None
        # self.label["start"] = None
        # self.label["end"] = None
        # self.label["text"] = None

    def add_wire(self, wire):
        self.wires.append(wire)

    def add_bend(self, bend):
        self.bends.append(bend)

    def contour_index(self):
        max_size = 0
        max_index = 0
        bbox = Bnd_Box()

        # for i in range(len(self.wires)-1, -1, -1):
        for i in range(len(self.loops)):
            brepbndlib.Add(self.loops[i].wires[0], bbox)

            bb_xmin, bb_ymin, _, bb_xmax, bb_ymax, _ = bbox.Get()
            wire_size = (bb_xmax - bb_xmin) * (bb_ymax - bb_ymin)

            if wire_size > max_size:
                max_size = wire_size
                max_index = i

            # logger.debug("WIRE %s IS: %s" % (i, wire_size))
            # logger.debug("WIRE TYPE %s" % (self.wires[i].ShapeType()))

        xmin, ymin, zmin, xmax, ymax, zmax = bbox.Get()

        self.origin = Point(min(xmin, xmax), min(ymin, ymax))
        self.width = abs(xmax - xmin)
        self.height = abs(ymax - ymin)

        return max_index

    def parse_wires(self):
        contour_index = self.contour_index()
        contour_wire = self.loops[contour_index].wires[0]

        self.contour = self.parse_wire(contour_wire)
        self.holes = []

        for i in range(len(self.loops)):

            if i != contour_index:
                loop = self.loops[i]
                wire = loop.wires[0]
                entity = self.parse_wire(wire)

                if loop.feature:

                    if loop.feature.projections:
                        projection = self.parse_wire(loop.feature.projections[0])
                        self.holes.append(projection)

                    if loop.feature.extrusion:
                        entity.feature_type = Entity.FeatureTypes.EXTRUSION
                        entity.feature_value = loop.feature.extrusion

                    elif loop.feature.embossing:
                        entity.feature_type = Entity.FeatureTypes.EMBOSSING
                        entity.feature_value = loop.feature.embossing

                    elif loop.feature.chamfer_a or loop.feature.chamfer_b:
                        if entity.type == Entity.EntityTypes.CIRCLE:

                            entity.feature_type = Entity.FeatureTypes.COUNTERSINK
                            entity.feature_value = min(loop.feature.chamfer_a, loop.feature.chamfer_b)

                        else:
                            entity.feature_type = Entity.FeatureTypes.CHAMFER
                            entity.feature_value = min(loop.feature.chamfer_a, loop.feature.chamfer_b)

                self.holes.append(entity)

        # TODO: Check orientations of wires for bulges
        # if wire.Orientation() != 0:
        #         wire.Reverse()
        pass

    def parse_loops(self):
        # contour_index = self.contour_index()
        # contour_wire = self.loops[contour_index].wires[0]

        # self.contour = self.parse_wire(contour_wire)
        self.holes = []

        for i in range(len(self.loops)):
            loop = self.loops[i]

            entities = []
            for j in  range(len(loop.wires)):
                wire = loop.wires[j]
                entity = self.parse_wire(wire)

                if loop.feature:

                    if loop.feature.extrusion:
                        entity.feature_type = Entity.FeatureTypes.EXTRUSION
                        entity.feature_value = loop.feature.extrusion

                    elif loop.feature.embossing:
                        entity.feature_type = Entity.FeatureTypes.EMBOSSING
                        entity.feature_value = loop.feature.embossing

                    elif loop.feature.chamfer_a or loop.feature.chamfer_b:
                        if entity.type == Entity.EntityTypes.CIRCLE:
                            entity.feature_type = Entity.FeatureTypes.COUNTERSINK
                            entity.feature_value = min(loop.feature.chamfer_a, loop.feature.chamfer_b)
                            # entity.feature_value = loop.feature["embossing"]

                        else:
                            entity.feature_type = Entity.FeatureTypes.CHAMFER
                            entity.feature_value = min(loop.feature.chamfer_a, loop.feature.chamfer_b)
                            # entity.feature_value = loop.feature["embossing"]

                entities.append(entity)

            # print(entities)

            entity = entities.pop(0)
            entity.area = entity.compute_area()
            entity.boundary = entity.compute_length()

            # print("area: {:0.2f}, length: {:0.2f}".format(entity.area, entity.boundary))
            for other in entities:
                entity.area += other.compute_area()
                entity.boundary += other.compute_length()

                # print("area: {:0.2f}, length: {:0.2f}".format(entity.area, entity.boundary))

            self.holes.append(entity)

    def fix_continuity(self, edge, continuity=1):
        from OCC.Core.GeomAbs import GeomAbs_C1, GeomAbs_C2, GeomAbs_C3
        from OCC.Core.ShapeUpgrade import ShapeUpgrade_ShapeDivideContinuity

        su = ShapeUpgrade_ShapeDivideContinuity(edge)
        su.SetBoundaryCriterion(eval("GeomAbs_C" + str(continuity)))
        su.Perform()
        return su.Result()

    def approximate_edge(self, edge):
        points = []
        shape = self.fix_continuity(edge, 2)

        edge_explorer = TopExp_Explorer(shape, TopAbs_EDGE)
        while edge_explorer.More():
            sub_edge = topods.Edge(edge_explorer.Current())
            edge_explorer.Next()

            curveAdaptor = BRepAdaptor_Curve(sub_edge)
            sub_points = CPnts_UniformDeflection(curveAdaptor, 0.001, 0.0001, True)

            if sub_points.IsAllDone():
                while sub_points.More():
                    point = sub_points.Point()
                    points.append([point.Coord(1), point.Coord(2)])
                    sub_points.Next()

        return points

    def parse_wire(self, wire):
        init = True
        totalAngle = 0
        entity = Entity()

        edge_explorer = TopExp_Explorer(wire, TopAbs_EDGE)
        while edge_explorer.More():
            edge = topods.Edge(edge_explorer.Current())
            edge_explorer.Next()

            adaptor = BRepAdaptor_Curve(edge)
            _lbound = adaptor.FirstParameter()
            _ubound = adaptor.LastParameter()


            edge_type = EdgeTypes(adaptor.Curve().GetType())

            curve_handle = BRep_Tool.Curve(edge)[0]
            curve = curve_handle

            # Line, Circle, Ellipse, Hyperbola, Parabola,
            # BezierCurve, BSplineCurve, OtherCurve
            if edge_type == EdgeTypes.LINE:
                logger.debug("[+] parse LINE: %s" % (edge_type.name))
                startPoint = gp_Pnt()
                endPoint = gp_Pnt()

                # _lbound, _ubound = edge.domain()
                curve.D0(_lbound, startPoint)
                curve.D0(_ubound, endPoint)

                if edge.Orientation() != 0:
                    startPoint, endPoint = endPoint, startPoint

                if init:
                    entity.path.append([startPoint.Coord(1), startPoint.Coord(2)])
                    entity.type = Entity.EntityTypes.LINE #TODO: used to be POLYLINE

                else:
                    entity.type = Entity.EntityTypes.POLYLINE #TODO: used to be PATH

                entity.path.append([endPoint.Coord(1), endPoint.Coord(2)])


            elif edge_type == EdgeTypes.CIRCLE:
                logger.debug("[+] parse CIRCLE: %s" % (edge_type.name))

                circle = adaptor.Circle()
                centerPoint = circle.Location()
                circleRadius = circle.Radius()
                circleLength = GCPnts_AbscissaPoint.Length(adaptor)
                circleAngle = circleLength / circleRadius

                # logger.debug(" - R=%0.2f, 0=%0.2f, A=%0.2f" % (circleRadius, circleLength, circleAngle))

                # Check if entity could still be circle
                if init:
                    entity.type = Entity.EntityTypes.CIRCLE
                    totalAngle += circleAngle
                    entity.radius = circleRadius

                elif (entity.type == Entity.EntityTypes.CIRCLE) and entity.radius:
                    if almostZero(entity.radius - circleRadius, EPSILON=1e-3):
                        totalAngle += circleAngle
                        entity.radius = circleRadius

                    else:
                        entity.type = Entity.EntityTypes.PATH

                else:
                    entity.type = Entity.EntityTypes.PATH
                    entity.radius = None
                    entity.centroid = None

                startPoint = gp_Pnt()
                endPoint = gp_Pnt()
                midPoint = gp_Pnt()

                # _lbound, _ubound = edge.domain()
                curve.D0(_lbound, startPoint)
                curve.D0(_ubound, endPoint)
                curve.D0((_lbound + _ubound) / 2.0, midPoint)

                if edge.Orientation() != 0:
                    startPoint, endPoint = endPoint, startPoint

                if init:
                    entity.path.append([startPoint.Coord(1), startPoint.Coord(2)])

                entity.path.append([endPoint.Coord(1), endPoint.Coord(2)])

                origin = Point(entity.path[-2])
                segment = Point(entity.path[-1]) - origin
                centroid = Point(centerPoint.Coord(1), centerPoint.Coord(2)) - origin
                middle = Point(midPoint.Coord(1), midPoint.Coord(2))

                if not (almostZero(segment.distance(), EPSILON=1e-3)
                    or almostZero(centroid.distance(), EPSILON=1e-3)):

                    bulge = math.tan(circleAngle / 4.0)
                    if (middle - origin).isLeftOf(segment):
                        bulge *= -1

                    entity.path[-2].bulge = bulge


            else:
                logger.debug("[+] parse OTHER: %s" % (edge_type.name))
                points = self.approximate_edge(edge)

                if edge.Orientation() != 0:
                    points = list(reversed(points))

                if init:
                    entity.type == Entity.EntityTypes.POLYLINE
                else:
                    points.pop(0)

                for point in points:
                    entity.path.append(point)

                if not entity.type == Entity.EntityTypes.POLYLINE:
                    entity.type = Entity.EntityTypes.PATH

            init = False

        if (entity.type == Entity.EntityTypes.CIRCLE) and almostZero(totalAngle - 2 * math.pi, EPSILON=1e-3):
            entity.path = Path()
            entity.path.append(
                [centerPoint.Coord(1) + circleRadius, centerPoint.Coord(2)]
            )
            entity.path[-1].bulge = 1.0
            entity.path.append(
                [centerPoint.Coord(1) - circleRadius, centerPoint.Coord(2)]
            )
            entity.path[-1].bulge = 1.0
            entity.centroid = [centerPoint.Coord(1), centerPoint.Coord(2)]
            entity.radius = circleRadius

            # print(totalAngle)

        else:
            # print(totalAngle)
            entity.type = Entity.EntityTypes.PATH

        # Force closed contour
        entity.path.append([entity.path[0].x, entity.path[0].y])

        return entity


    def export_cycad(self, material=None, thickness=None, add_text=True, description=None, messages=[]):
        logger.debug("Exporting CYCAD")

        # template_path = os.getcwd()
        # template_path = os.path.join(template_path, "templates")
        # ezdxf.options.template_dir = template_path

        dwg = ezdxf.new("AC1015", setup=True)

        dwg.layers.add("DESCRIPTION", color=1, linetype="Continuous")
        dwg.layers.add("BENDS", color=2, linetype="DASHED")
        dwg.layers.add("OUTLINE", color=3, linetype="Continuous")
        dwg.layers.add("ENGRAVING", color=4, linetype="Continuous")

        msp = dwg.modelspace()
        layers = {
            "description": "DESCRIPTION",
            "contour": "OUTLINE",
            "hole": "OUTLINE",
            "bend": "BENDS",
            "engraving": "ENGRAVING"
        }

        yText = self.origin.y + self.height

        # if description:
        #     yText += 1.5
        #     msp.add_text("DESCRIPTION = %s" % (description)).set_placement(
        #         (self.origin.x, yText), align=TextEntityAlignment.BOTTOM_LEFT
        #     ).set_dxf_attrib("layer", "DESCRIPTION")

        if self.quantity:
            yText += 1.5
            msp.add_text("USERINFO3 = x%i" % (self.quantity)).set_placement(
                (self.origin.x, yText), align=TextEntityAlignment.BOTTOM_LEFT
            ).set_dxf_attrib("layer", "DESCRIPTION")

        if self.date:
            yText += 1.5
            msp.add_text("USERINFO2 = %s" % (self.date)).set_placement(
                (self.origin.x, yText), align=TextEntityAlignment.BOTTOM_LEFT
            ).set_dxf_attrib("layer", "DESCRIPTION")

        if "text" in self.label:
            yText += 1.5
            msp.add_text("USERINFO1 = %s" % (self.label["text"])).set_placement(
                (self.origin.x, yText), align=TextEntityAlignment.BOTTOM_LEFT
            ).set_dxf_attrib("layer", "DESCRIPTION")

        if self.thickness:
            yText += 1.5
            msp.add_text("THICK = %0.2f" % (self.thickness)).set_placement(
                (self.origin.x, yText), align=TextEntityAlignment.BOTTOM_LEFT
            ).set_dxf_attrib("layer", "DESCRIPTION")

        if self.material:
            yText += 1.5
            msp.add_text("MATERIAL = %s" % (self.material)).set_placement(
                (self.origin.x, yText), align=TextEntityAlignment.BOTTOM_LEFT
            ).set_dxf_attrib("layer", "DESCRIPTION")

        yText += 1.5
        msp.add_text("CYCAD:ENGRAVING").set_placement(
            (self.origin.x, yText), align=TextEntityAlignment.BOTTOM_LEFT
        ).set_dxf_attrib("layer", "ENGRAVING")

        yText += 1.5
        msp.add_text("CYCAD:OUTLINE").set_placement(
            (self.origin.x, yText), align=TextEntityAlignment.BOTTOM_LEFT
        ).set_dxf_attrib("layer", "OUTLINE")

        yText += 1.5
        msp.add_text("CYCAD:BENDS").set_placement(
            (self.origin.x, yText), align=TextEntityAlignment.BOTTOM_LEFT
        ).set_dxf_attrib("layer", "BENDS")

        self.draw_entity(msp, self.contour, layers["contour"])

        for entity in self.holes:
            if entity.feature_type == Entity.FeatureTypes.COUNTERSINK:
                self.draw_entity(msp, entity, layers["engraving"])

            if entity.feature_type == Entity.FeatureTypes.CHAMFER:
                self.draw_entity(msp, entity, layers["engraving"])

            if entity.feature_type == Entity.FeatureTypes.EXTRUSION:
                self.draw_entity(msp, entity, layers["engraving"])

            if entity.feature_type == Entity.FeatureTypes.EMBOSSING:
                self.draw_entity(msp, entity, layers["engraving"])

            if not entity.feature_type:
                self.draw_entity(msp, entity, layers["hole"])

        for entity in self.bends:
            self.draw_bend(msp, entity, layers["bend"])

        if "position" in self.label:
            text = msp.add_text(self.label["text"], dxfattribs={
                 'height': self.label["height"]}
                )

            text.set_placement(self.label["start"], self.label["end"], align=TextEntityAlignment.FIT)
            text.set_dxf_attrib("layer", layers["description"])

        # logger.warning("inner_fit_polygon: {}".format(self.inner_fit_polygon != None))
        # logger.warning("label_position: {}".format(label["position"] != None))
        # if self.inner_fit_polygon:
        #     for entity in self.inner_fit_polygon:
        #         logger.info("DRAWING inner_fit_polygon")
        #         element = self.draw_entity(msp, entity, layers["description"])

        outputStream = StringIO.StringIO()
        dwg.write(outputStream)

        return outputStream


    def export_dxf(self, template, material=None, thickness=None, add_text=True, description=None, messages=[]):
        logger.debug("Exporting DXF (template)")

        dwg = ezdxf.new("AC1015", setup=True)

        layers = {}
        for layer in template["layers"]:
            layer_color = Colors[layer["color"].upper()]
            layer_linetype = None

            for linetype in ezdxf.tools.standards.linetypes():
                if linetype[0].upper() == layer["linetype"].upper():
                    layer_linetype = linetype[0]
                    break

            if layer_color and layer_linetype:
                dwg.layers.add(layer["name"], color=layer_color.value, linetype=layer_linetype)

                for entity in layer["entities"]:
                    layers[entity.upper()] = layer["name"] 

        msp = dwg.modelspace()




        # Add data
        yText = self.origin.y + self.height
        if self.quantity and "QUANTITY" in layers:
            yText += 1.5
            msp.add_text("QUANTITY = %i" % (self.quantity)).set_placement(
                (self.origin.x, yText), align=TextEntityAlignment.BOTTOM_LEFT
            ).set_dxf_attrib("layer", layers["QUANTITY"])

        if self.thickness and "THICKNESS" in layers:
            yText += 1.5
            msp.add_text("THICKNESS = %0.2f" % (self.thickness)).set_placement(
                (self.origin.x, yText), align=TextEntityAlignment.BOTTOM_LEFT
            ).set_dxf_attrib("layer", layers["THICKNESS"])

        if self.material and "MATERIAL" in layers:
            yText += 1.5
            msp.add_text("MATERIAL = %s" % (self.material)).set_placement(
                (self.origin.x, yText), align=TextEntityAlignment.BOTTOM_LEFT
            ).set_dxf_attrib("layer", layers["MATERIAL"])


        # if "position" in self.label:
        #     text = msp.add_text(self.label["text"], dxfattribs={
        #          'height': self.label["height"]}
        #         )

        #     text.set_placement(self.label["start"], self.label["end"], align=TextEntityAlignment.FIT)
        #     text.set_dxf_attrib("layer", layers["CONTOUR"])
        #     # text.set_placement(self.label["start"], align=TextEntityAlignment.BOTTOM_LEFT)
        #     # text.set_dxf_attrib("layer", layers["CONTOUR"])

        # else:
        #     text = msp.add_text(self.label["text"], dxfattribs={
        #          'height': self.label["height"]}
        #         )

        #     text.set_placement(self.origin, align=TextEntityAlignment.BOTTOM_LEFT)
        #     text.set_dxf_attrib("layer", layers["CONTOUR"])


        if "CONTOUR" in layers:
            self.draw_entity(msp, self.contour, layers["CONTOUR"])

        for entity in self.holes:

            if entity.feature_type == Entity.FeatureTypes.COUNTERSINK and  "COUNTERSINK" in layers:
                self.draw_entity(msp, entity, layers["COUNTERSINK"])

            if entity.feature_type == Entity.FeatureTypes.CHAMFER and "CHAMFER" in layers:
                self.draw_entity(msp, entity, layers["CHAMFER"])

            if entity.feature_type == Entity.FeatureTypes.EXTRUSION and "EXTRUSION" in layers:
                self.draw_entity(msp, entity, layers["EXTRUSION"])

            if entity.feature_type == Entity.FeatureTypes.EMBOSSING and "EMBOSSING" in layers:
                self.draw_entity(msp, entity, layers["EMBOSSING"])

            if not entity.feature_type and "HOLE" in layers:
                self.draw_entity(msp, entity, layers["HOLE"])

        if "BEND" in layers:
            for entity in self.bends:
                self.draw_bend(msp, entity, layers["BEND"], add_text=False)

        if "position" in self.label and "LABEL" in layers:
            text = msp.add_text(self.label["text"], dxfattribs={
                 'height': self.label["height"]}
                )

            text.set_placement(self.label["start"], self.label["end"], align=TextEntityAlignment.FIT)
            text.set_dxf_attrib("layer", layers["LABEL"])

        # logger.warning("inner_fit_polygon: {}".format(self.inner_fit_polygon != None))
        # logger.warning("label_position: {}".format(label["position"] != None))
        # if self.inner_fit_polygon:
        #     for entity in self.inner_fit_polygon:
        #         logger.info("DRAWING inner_fit_polygon")
        #         element = self.draw_entity(msp, entity, layers["description"])

        outputStream = StringIO.StringIO()
        dwg.write(outputStream)

        return outputStream


    def export_designer(self, application_name="BYSOFT7_DESIGNER", guid=None, measurementSystem="Metric", material=None, thickness=None, add_text=True, description=None, messages=[]):
        logger.debug("Exporting Designer DXF")
        dwg = ezdxf.new("AC1015", setup=True)
        dwg.appids.add(application_name)

        dwg.layers.add("DESCRIPTION", color=1, linetype="Continuous")
        dwg.layers.add("BENDLINES", color=2, linetype="DASHED")
        dwg.layers.add("EXTRUSIONS", color=3, linetype="Continuous")
        dwg.layers.add("GEOMETRY", color=4, linetype="Continuous")

        msp = dwg.modelspace()
        layers = {
            "text": "DESCRIPTION",
            "contour": "GEOMETRY",
            "hole": "GEOMETRY",
            "extrusion": "EXTRUSIONS",
            "bend": "BENDLINES",
        }

        # Text
        if add_text:
            yText = self.origin.y + self.height

            info_index = 0
            for message in messages:
                yText += 1.5
                info_index += 1
                text = msp.add_text("Info{} = {}".format(info_index, message["description"])).set_placement(
                    (self.origin.x, yText), align=TextEntityAlignment.BOTTOM_LEFT
                )
                text.set_dxf_attrib("layer", layers["text"])
                # text.set_dxf_attrib("style", "STANDARD")

            if description:
                yText += 1.5
                text = msp.add_text("Description = {}".format(description)).set_placement(
                    (self.origin.x, yText), align=TextEntityAlignment.BOTTOM_LEFT
                )
                text.set_dxf_attrib("layer", layers["text"])
                # text.set_dxf_attrib("style", "STANDARD")


        # Contour
        contour_element = self.draw_entity(msp, self.contour, layers["contour"])

        # Determine full extended data
        XDATA = []

        if len(self.bends) == 0:
            XDATA.append((1000, 'FlatPartInfo'))
        else:
            XDATA.append((1000, 'BendPartInfo'))

        XDATA.append((1002, '{'))

        if not guid:
            guid = uuid.uuid4()
            # guid = "1ea66f28-7015-468a-aa18-36ad21a9b99a"

        XDATA.append((1000, 'Guid={0}'.format(guid)))

        if measurementSystem:
            XDATA.append((1000, 'MeasurementSystem={0}'.format(measurementSystem)))

        if material:
            XDATA.append((1000, 'Material={0}'.format(material)))

        if thickness:
            XDATA.append((1000, 'Thickness={0:.2f}'.format(thickness)))

        XDATA.append((1002, '}'))
        contour_element.set_xdata(application_name, XDATA)

        # logger.debug(XDATA)

        for entity in self.holes:
            if entity.feature_type:
                hole_element = self.draw_entity(msp, entity, layers["extrusion"])

                if entity.feature_type == Entity.FeatureTypes.EXTRUSION:
                    extrusion = entity.feature_value

                else:
                    extrusion = 0.0

                XDATA = [
                    (1000, 'ExtrusionInfo'),
                    (1002, '{'),
                    (1000, 'ZHeight={:0.2f}'.format(extrusion)),
                    (1002, '}')
                ]
                hole_element.set_xdata(application_name, XDATA)
                # logger.debug(XDATA)

            else:
                hole_element = self.draw_entity(msp, entity, layers["hole"])

        # bend_id = 1
        for entity in self.bends:
            bend_element = self.draw_bend(msp, entity, layers["bend"], add_text=False)

            bend_angle = 180.0 * entity.angle / math.pi
            bend_allowance = abs(entity.angle) * (entity.inner_radius + thickness * entity.k_factor)
            bend_deduction = 2 * (entity.inner_radius + thickness) * math.tan(abs(entity.angle) / 2) - bend_allowance

            XDATA = [
                (1000, 'BendLineInfo'),
                (1002, '{'),
                (1000, 'BendId={0}'.format(entity.common_id)),
                (1000, 'BendAngle={:0.2f}'.format(bend_angle)),
                (1000, 'BendRadius={:0.2f}'.format(entity.inner_radius)),
                (1000, 'BendDeduction={:0.2f}'.format(bend_deduction)),
                (1002, '}')
            ]
            bend_element.set_xdata(application_name, XDATA)
            # logger.debug(XDATA)

        if len(self.bends) > 0:
            if len(self.bends) > entity.common_id:
                logger.warning("bends detected with common bend id")

            # bend_id += 1

        # if self.inner_fit_polygon:
        #     for entity in self.inner_fit_polygon:
        #         element = self.draw_entity(msp, entity, layers["text"])

        # paths = pack(self, offset=0.1)
        # for path in paths:
        #     entity = Entity(path=path, type=Entity.EntityTypes.POLYLINE)
        #     element = self.draw_entity(msp, entity, layers["text"])

        if "position" in self.label:
            text = msp.add_text(self.label["text"], dxfattribs={
                 'height': self.label["height"]}
                )

            text.set_placement(self.label["start"], self.label["end"], align=TextEntityAlignment.FIT)
            text.set_dxf_attrib("layer", layers["text"])

        outputStream = StringIO.StringIO()
        dwg.write(outputStream)

        return outputStream


    def save(self, file_path, dxf_type="DESIGNER", description=None, messages=[], add_text=True, template=None):
        if dxf_type == "DESIGNER":
            logger.debug("Saving DESIGNER DXF")
            stream = self.export_designer(thickness=self.thickness, material=self.material, description=description, messages=messages, add_text=add_text)

        elif dxf_type == "TEMPLATE" and template:
            logger.debug("Saving DXF")
            stream = self.export_dxf(template, thickness=self.thickness, material=self.material, description=description, messages=messages)

        elif dxf_type == "CYCAD":
            logger.debug("Saving CYCAD DXF")
            stream = self.export_cycad(thickness=self.thickness, material=self.material, description=description, messages=messages, add_text=add_text)

        else:
            raise ValueError("unknown dxf_type %r (expected DESIGNER, TEMPLATE with a template, or CYCAD)" % dxf_type)

        with open(file_path, "w", encoding="utf-8") as output_file:
            output_file.write(stream.getvalue())

        stream.close()

        return


    def draw_bend(self, msp, entity, layer, add_text=True):
        element = msp.add_line(
                (entity.path[0][0], entity.path[0][1]),
                (entity.path[1][0], entity.path[1][1]),
                dxfattribs={"layer": layer})

        if add_text:
            angle_degrees = 180.0 * entity.angle / math.pi
            bendText = "%0.2f/R=%0.2f/K=%0.2f" % (angle_degrees, entity.inner_radius, entity.k_factor)

            msp.add_text(bendText).set_placement(
                (
                    (entity.path[0][0] + entity.path[1][0]) / 2.0,
                    (entity.path[0][1] + entity.path[1][1]) / 2.0,
                ),  align=TextEntityAlignment.BOTTOM_LEFT,
            ).set_dxf_attrib("layer", layer)

        return element



    def draw_entity(self, msp, entity, layer):
        if entity.type == Entity.EntityTypes.LINE:
            element = msp.add_line(
                (entity[0][0], entity[0][1]),
                (entity[1][0], entity[1][1]),
                dxfattribs={"layer": layer},
            )

        elif entity.type == Entity.EntityTypes.CIRCLE:
            element = msp.add_circle(
                (entity.centroid[0], entity.centroid[1]),
                entity.radius,
                dxfattribs={"layer": layer},
            )

        else:
            lwPoints = []
            for point in entity.path:

                if point.bulge:
                    lwPoint = (point[0], point[1], 0, 0, point.bulge)

                else:
                    lwPoint = (point[0], point[1], 0, 0, 0)

                lwPoints.append(lwPoint)

            if entity.path.isClosed():
                element = msp.add_lwpolyline(lwPoints[:-1], dxfattribs={"layer": layer})
                element.closed = True

            else:
                element = msp.add_lwpolyline(lwPoints, dxfattribs={"layer": layer})

        return element


    def place_label(self, text, font_height=10.0, gravity_angle=4.7, font_ratio=0.84):
        paths = label_main(self, text=text, font_height=font_height, font_ratio=font_ratio)

        if paths:
            best_distance = -float("inf")
            best_placement = paths[0][0]
            gravity_vec = polar_point(1.0, gravity_angle)
            self.inner_fit_polygon = []
            for path in paths:
                entity = Entity(path=path, type=Entity.EntityTypes.POLYLINE)
                self.inner_fit_polygon.append(entity)

                for point in path:
                    distance = gravity_vec.dot(point)

                    if distance >= best_distance:
                        best_distance = distance
                        best_placement = point


            font_width = len(text) * font_ratio * font_height

            self.label["height"] = font_height
            self.label["width"] = font_width
            self.label["position"] = Point(best_placement.x, best_placement.y)
            self.label["start"] = Point(best_placement.x - font_width / 2, best_placement.y)
            self.label["end"] = Point(best_placement.x + font_width / 2, best_placement.y)

        self.label["text"] = text



    def autoDimension(self, spacing=20.0, alpha=1e2, minimal=0.0, EPSILON=1e-6):
        # logging.info("[+] computing the bend dimensions")

        bends = copy.copy(self.bends)
        dimensions = []
        approximation = self.contour.approximate()

        # logging.info("[+] Force CCW of approximation")
        if self.contour.compute_area(signed=True) < 0:
            # logging.info("[+] REVERSING CONTOUR")
            approximation.reverse()

        while len(bends) > 0:
            bend = bends.pop(0)
            bendVector = bend[1] - bend[0]
            bendMid = bend[0] + bendVector / 2

            bendDir = bendVector / bendVector.distance()

            # logging.info("[+] direction: " + str(bendDir))

            points = [(bend[0] + bend[1]) / 2]
            lengths = {}
            distances = {}
            segments = {}
            for i in range(len(approximation)):
                segment = [approximation[i], approximation[i + 1]]
                segVector = segment[1] - segment[0]
                segLength = segVector.distance()
                if segLength == 0:
                    continue

                segDir = segVector / segLength
                product = bendDir.x * segDir.x + bendDir.y * segDir.y

                # Bend is parallel to this segment
                if almostEqual(abs(product), 1, EPSILON=EPSILON):
                    segMid = segment[0] + segVector / 2

                    distance = segment_to_point(segment, bendMid)

                    lengths[segMid] = segLength

                    if abs(distance) < minimal:
                        lengths[segMid] *= 1/alpha

                    if distance > 0:
                        distance *= alpha

                    distances[segMid] = abs(distance)
                    segments[segMid] = segment

                    # logging.info("[+] parallel at " + str(distance) + ", length: " + str(segLength) + ", dir: " + str(segDir) + str(segment[0]) + str(segment[1]))

            if len(distances) == 0:
                # logging.info("[+] No parallel lines detected")

                minPoint = None
                maxPoint = None

                minDistance = float("inf")
                maxDistance = float("-inf")

                for contourPoint in approximation:
                    distance = segment_to_point(bend, contourPoint)

                    if distance < minDistance:
                        minDistance = distance
                        minPoint = contourPoint

                    elif distance > maxDistance:
                        maxDistance = distance
                        maxPoint = contourPoint

                lengths = {minPoint: 1., maxPoint: 1.}
                distances = {minPoint: abs(minDistance), maxPoint: abs(maxDistance)}
                segments = {minPoint: [minPoint], maxPoint: [maxPoint]}


            # Add additional bends in line
            for j in reversed(range(len(bends))):
                otherBend = bends[j]
                otherVector = otherBend[1] - otherBend[0]
                otherDir = otherVector / otherVector.distance()

                otherProduct = bendDir.x * otherDir.x + bendDir.y * otherDir.y

                # Other bends are also parallel, handle as single set of ordinate dimensions
                if almostEqual(abs(otherProduct), 1, EPSILON=EPSILON):
                    otherBend = bends.pop(j)
                    otherMid = otherBend[0] + otherVector / 2
                    points.append(otherMid)

                    for midPoint in distances:
                        if len(segments[midPoint]) == 1:
                            distance = segment_to_point(otherBend, segments[midPoint][0])

                            if abs(distance) < minimal:
                                lengths[midPoint] *= 1/alpha

                        else:
                            distance = segment_to_point(segments[midPoint], otherMid)

                            if abs(distance) < minimal:
                                lengths[midPoint] *= 1/alpha

                            if distance > 0:
                                distance *= alpha

                        distances[midPoint] += abs(distance)


            best = float("inf")
            for midPoint in distances:
                fitness = distances[midPoint] / lengths[midPoint]
                # fitness = distances[midPoint]

                if fitness < best:
                    best = fitness
                    origin = midPoint


            # Determin total dimension for reverse order
            minDistance = float("inf")
            maxDistance = float("-inf")
            originSegment = [origin, origin + bendDir]
            for midPoint in distances:
                distance = segment_to_point(originSegment, midPoint)

                if distance > maxDistance:
                    maxDistance = distance
                    maxPoint = midPoint

                if distance < minDistance:
                    minDistance = distance
                    minPoint = midPoint

            points.append(maxPoint)
            points.append(minPoint)


            direction = bendDir
            perpendicular = Point([direction.y, -direction.x])


            # Compute minimal offset in direction, ovoid dimensions through part
            minOffset = float("inf")
            maxOffset = -minOffset
            minOffsetSum = 0.0
            maxOffsetSum = 0.0
            for point in approximation:
                point = point - origin
                offset = point.x * direction.x + point.y * direction.y

                # Compute offsets with respect to bends
                offsetSum = offset
                for midPoint in points:
                    midVector = point - midPoint
                    bendOffset = midVector.x * direction.x + midVector.y * direction.y
                    offsetSum += bendOffset

                if offset < minOffset and offset <= 0:
                    minOffset = offset
                    minOffsetSum = offsetSum

                elif offset > maxOffset and offset >= 0:
                    maxOffset = offset
                    maxOffsetSum = offsetSum

            # if abs(minOffset) < abs(maxOffset):
            if minOffsetSum < maxOffsetSum:
                offset = minOffset - spacing
            else:
                offset = maxOffset + spacing

            # offset += spacing
            offsetVector = direction * offset
            angle = math.atan2(offsetVector.y, offsetVector.x)

            # logging.info("[+] reference offset " + str(offset))
            # logging.info("[+] reference at " + str(origin))
            # logging.info("[+] reference distance " + str(distances[origin]))

            dimension = {}
            dimension["d"] = "M %f %f " % (origin.x, origin.y)
            dimension["d"] += "L %f %f" % (origin.x + offsetVector.x, origin.y + offsetVector.y)
            dimension["cx"], dimension["cy"] = (origin.x + offsetVector.x, origin.y + offsetVector.y)
            dimension["dimension"] = -0.0
            dimension["angle"] = angle
            dimension["kind"] = "leader"
            dimensions.append(dimension)

            positives = []
            negatives = []
            for point in points:
                pointVector = point - origin
                distance = pointVector.x * perpendicular[0] + pointVector.y * perpendicular[1]

                if abs(distance) < EPSILON:
                    continue
                if distance > 0:
                    positives.append(distance)
                else:
                    negatives.append(distance)

                leader = Path()
                leader.append(point)
                leader.append(origin + offsetVector + distance * perpendicular)

                dimension = {}
                dimension["d"] = "M %f %f " % (leader[0].x, leader[0].y)
                dimension["d"] += "L %f %f" % (leader[1].x, leader[1].y)
                dimension["cx"], dimension["cy"] = (leader[1].x, leader[1].y)
                dimension["dimension"] = distance
                dimension["angle"] = angle
                dimension["kind"] = "leader"
                dimensions.append(dimension)

                # logging.info("[+] dimensions: " + str((point - origin).distance()))

            if len(positives) > 0:
                start = origin + offsetVector

                dimension = {}
                dimension["d"] = "M %f %f " % (start.x, start.y)
                dimension["cx"], dimension["cy"] = (start.x, start.y)
                dimension["kind"] = "arrow"
                positives.sort()
                for distance in positives:
                    dimension["d"] += "L %f %f " % (start.x + distance * perpendicular.x, start.y + distance * perpendicular.y)
                dimensions.append(dimension)

            if len(negatives) > 0:
                start = origin + offsetVector

                dimension = {}
                dimension["d"] = "M %f %f " % (start.x, start.y)
                dimension["cx"], dimension["cy"] = (start.x, start.y)
                dimension["kind"] = "arrow"
                negatives.sort(reverse=True)
                for distance in negatives:
                    dimension["d"] += "L %f %f " % (start.x + distance * perpendicular.x, start.y + distance * perpendicular.y)
                dimensions.append(dimension)

        # logging.info("[+] dimensions: " + str(dimensions))
        return dimensions
