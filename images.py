# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import sys
import io as StringIO

from OCC.Core.gp import gp_Ax2, gp_Pnt, gp_Dir
from OCC.Core.BRepLib import breplib
from OCC.Core.HLRBRep import HLRBRep_Algo, HLRBRep_HLRToShape
from OCC.Core.HLRAlgo import HLRAlgo_Projector
from OCC.Core.GCPnts import GCPnts_QuasiUniformDeflection

from OCC.Core.Bnd import Bnd_Box
from OCC.Core.BRepBndLib import brepbndlib
from OCC.Core.TopAbs import TopAbs_SOLID, TopAbs_EDGE, TopAbs_FACE, TopAbs_WIRE
from OCC.Core.TopExp import TopExp_Explorer
from OCC.Core.TopoDS import topods
from OCC.Core.BRepAdaptor import BRepAdaptor_Curve


try:
    import xml.etree.cElementTree as ET
except ImportError:
    import xml.etree.ElementTree as ET

from PIL import Image, ImageDraw

TOLERANCE = 1e-6
DISCRETIZATION_TOLERANCE = 1e-1
DEFAULT_DIR = gp_Dir(-1.75, 1.1, 5)


def getPNG(shape, opts=None):
    """
        Export a shape to SVG
    """

    d = {'width': 400, 'height': 400, 'marginLeft': 5, 'marginTop': 5, 'orientation': (-1.75, 1.1, 5)}

    if opts:
        d.update(opts)

    width = float(d['width'])
    height = float(d['height'])
    marginLeft = float(d['marginLeft'])
    marginTop = float(d['marginTop'])
    direction = gp_Dir(d["orientation"][0], d["orientation"][1], d["orientation"][2])

    hlr = HLRBRep_Algo()
    hlr.Add(shape)

    projector = HLRAlgo_Projector(gp_Ax2(gp_Pnt(), direction))

    hlr.Projector(projector)
    hlr.Update()
    hlr.Hide()

    hlr_shapes = HLRBRep_HLRToShape(hlr)

    visible = []

    visible_sharp_edges = hlr_shapes.VCompound()
    if visible_sharp_edges:
        visible.append(visible_sharp_edges)

    visible_smooth_edges = hlr_shapes.Rg1LineVCompound()
    if visible_smooth_edges:
        visible.append(visible_smooth_edges)

    visible_contour_edges = hlr_shapes.OutLineVCompound()
    if visible_contour_edges:
        visible.append(visible_contour_edges)

    hidden = []

    hidden_sharp_edges = hlr_shapes.HCompound()
    if hidden_sharp_edges:
        hidden.append(hidden_sharp_edges)

    hidden_contour_edges = hlr_shapes.OutLineHCompound()
    if hidden_contour_edges:
        hidden.append(hidden_contour_edges)

    # Fix the underlying geometry - otherwise we will get segfaults
    for el in visible:
        breplib.BuildCurves3d(el, TOLERANCE)

    for el in hidden:
        breplib.BuildCurves3d(el, TOLERANCE)

    # get bounding box -- these are all in 2-d space
    bb = Bnd_Box()
    for path in visible:
        brepbndlib.Add(path, bb)

    for path in hidden:
        brepbndlib.Add(path, bb)

    xmin, ymin, zmin, xmax, ymax, zmax = bb.Get()
    bb_width = xmax - xmin
    bb_height = ymax - ymin
    bb_length = zmax - zmin

    # width pixels for x, height pixesl for y
    unitScale = min(width / bb_width * 0.98, height / bb_height * 0.98)
    marginLeft = (width / unitScale - bb_width) / 2
    marginTop = (height / unitScale - bb_height) / 2

    # Draw the lines
    drawing = getDrawing(visible, hidden, size=(width, height), origin=(xmin - marginLeft, ymin - marginTop), scale=unitScale)

    return drawing


def drawRectangle(draw, x, y, width, height, x_min, y_min, scale, outline=(0, 0, 0)):
    point_a = (x - x_min) * scale
    point_b = (y - y_min) * scale
    point_c = (x - x_min) * scale + width
    point_d = (y - y_min) * scale + height
    draw.rectangle([(point_a, point_b), (point_c, point_d)], fill=None, outline=outline)


def drawPathPNG(draw, path, x_min, y_min, scale, fill=(192, 193, 194), outline=(0, 0, 0)):

    cs = StringIO.StringIO()

    curve = BRepAdaptor_Curve(path)
    start = curve.FirstParameter()
    end = curve.LastParameter()

    points = GCPnts_QuasiUniformDeflection(curve,
                                           DISCRETIZATION_TOLERANCE,
                                           start,
                                           end)

    polyline = []
    if points.IsDone():
        point_it = (points.Value(i + 1) for i in range(points.NbPoints()))

        for p in point_it:
            x = (p.X() - x_min) * scale
            y = (p.Y() - y_min) * scale
            polyline.append((x, y))

    draw.line(polyline, fill=outline)


def getDrawing(visibleShapes, hiddenShapes, size=None, origin=None, scale=None, mode="RGBA", visible=(0, 0, 0), hidden=(192, 193, 194)):
    width = int(size[0])
    height = int(size[1])

    if mode == "RGBA":
        blank_color = (255, 255, 255, 1)
        img = Image.new('RGBA', (width, height), blank_color)

    elif mode == "RGB":
        blank_color = (255, 255, 255, 1)
        img = Image.new('RGB', (width, height), blank_color)

    elif mode == "1":
        blank_color = (0)
        img = Image.new('1', (width, height), blank_color)

    draw = ImageDraw.Draw(img)

    i = 0
    for s in hiddenShapes:
        for e in getEdges(s):
            drawPathPNG(draw, e, origin[0], origin[1], scale, fill=None, outline=hidden)

    for s in visibleShapes:
        for e in getEdges(s):
            drawPathPNG(draw, e, origin[0], origin[1], scale, fill=None, outline=visible)

    return img


def makeSVGedge(e):
    """

    """

    cs = StringIO.StringIO()

    curve = BRepAdaptor_Curve(e)
    # curve = e._geomAdaptor()  # adapt the edge into curve
    start = curve.FirstParameter()
    end = curve.LastParameter()

    points = GCPnts_QuasiUniformDeflection(curve,
                                           DISCRETIZATION_TOLERANCE,
                                           start,
                                           end)

    if points.IsDone():
        point_it = (points.Value(i + 1) for i in
                    range(points.NbPoints()))

        p = next(point_it)
        cs.write('M{},{} '.format(p.X(), p.Y()))

        for p in point_it:
            cs.write('L{},{} '.format(p.X(), p.Y()))

    return cs.getvalue()


def getPathsSVG(visibleShapes, hiddenShapes):
    """

    """

    hiddenPaths = []
    visiblePaths = []

    i = 0
    for s in visibleShapes:
        for e in getEdges(s):
            visiblePaths.append(makeSVGedge(e))

    for s in hiddenShapes:
        for e in getEdges(s):
            hiddenPaths.append(makeSVGedge(e))

    return (hiddenPaths, visiblePaths)


def getEdges(shape):
    edges = []
    edge_explorer = TopExp_Explorer(shape, TopAbs_EDGE)
    while edge_explorer.More():
        current_edge = topods.Edge(edge_explorer.Current())
        yield current_edge
        edge_explorer.Next()


def getSVG(shape, opts=None):
    """
        Export a shape to SVG
    """

    d = {'width': 400, 'height': 400, 'marginLeft': 5, 'marginTop': 5, 'orientation': (-1.75, 1.1, 5)}

    if opts:
        d.update(opts)

    width = float(d['width'])
    height = float(d['height'])
    marginLeft = float(d['marginLeft'])
    marginTop = float(d['marginTop'])
    direction = gp_Dir(d["orientation"][0], d["orientation"][1], d["orientation"][2])

    hlr = HLRBRep_Algo()
    hlr.Add(shape)

    projector = HLRAlgo_Projector(gp_Ax2(gp_Pnt(), direction))

    hlr.Projector(projector)
    hlr.Update()
    hlr.Hide()

    hlr_shapes = HLRBRep_HLRToShape(hlr)

    visible = []

    visible_sharp_edges = hlr_shapes.VCompound()
    if visible_sharp_edges:
        visible.append(visible_sharp_edges)

    visible_smooth_edges = hlr_shapes.Rg1LineVCompound()
    if visible_smooth_edges:
        visible.append(visible_smooth_edges)

    visible_contour_edges = hlr_shapes.OutLineVCompound()
    if visible_contour_edges:
        visible.append(visible_contour_edges)

    hidden = []

    hidden_sharp_edges = hlr_shapes.HCompound()
    if hidden_sharp_edges:
        hidden.append(hidden_sharp_edges)

    hidden_contour_edges = hlr_shapes.OutLineHCompound()
    if hidden_contour_edges:
        hidden.append(hidden_contour_edges)

    # Fix the underlying geometry - otherwise we will get segfaults
    for el in visible:
        breplib.BuildCurves3d(el, TOLERANCE)

    for el in hidden:
        breplib.BuildCurves3d(el, TOLERANCE)

    (hiddenPaths, visiblePaths) = getPathsSVG(visible,
                                           hidden)

    # get bounding box -- these are all in 2-d space
    bb = Bnd_Box()
    for path in visible:
        brepbndlib.Add(path, bb)

    for path in hidden:
        brepbndlib.Add(path, bb)

    xmin, ymin, zmin, xmax, ymax, zmax = bb.Get()
    bb_width = xmax - xmin
    bb_height = ymax - ymin
    bb_length = zmax - zmin

    # width pixels for x, height pixesl for y
    unitScale = min(width / bb_width * 0.98, height / bb_height * 0.98)
    marginLeft = (width - bb_width * unitScale) / 2
    marginTop = (height - bb_height * unitScale) / 2

    # compute amount to translate-- move the top left into view
    (xTranslate, yTranslate) = ((0 - xmin) + marginLeft /
                                unitScale, (0 - ymax) - marginTop / unitScale)

    # compute paths
    hiddenContent = ""
    for p in hiddenPaths:
        hiddenContent += PATHTEMPLATE % p

    visibleContent = ""
    for p in visiblePaths:
        visibleContent += PATHTEMPLATE % p

    svg = SVG_TEMPLATE % (
        {
            "unitScale": str(unitScale),
            "strokeWidth": str(1.0 / unitScale),
            "hiddenContent":  hiddenContent,
            "visibleContent": visibleContent,
            "xTranslate": str(xTranslate),
            "yTranslate": str(yTranslate),
            "width": str(width),
            "height": str(height),
        }
    )

    return svg


def exportSVG(shape, fileName):
    """
        accept a cadquery shape, and export it to the provided file
        TODO: should use file-like objects, not a fileName, and/or be able to return a string instead
        export a view of a part to svg
    """

    svg = getSVG(shape)
    f = open(fileName, 'w', encoding='utf-8')
    f.write(svg)
    f.close()


def exportPNG(shape, fileName):
    """
        accept a cadquery shape, and export it to the provided file
        TODO: should use file-like objects, not a fileName, and/or be able to return a string instead
        export a view of a part to svg
    """

    img = getPNG(shape)
    img = img.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    img.save(fileName, "png", optimize=True, quality=70)


SVG_TEMPLATE = """<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<svg xmlns="http://www.w3.org/2000/svg"
   width="%(width)s"
   height="%(height)s">

    <g transform="scale(%(unitScale)s, -%(unitScale)s)   translate(%(xTranslate)s,%(yTranslate)s)" stroke-width="%(strokeWidth)s"  fill="none">
       <!-- hidden lines -->
       <g  stroke="rgb(160, 160, 160)" fill="none" stroke-dasharray="%(strokeWidth)s,%(strokeWidth)s" >
%(hiddenContent)s
       </g>

       <!-- solid lines -->
       <g  stroke="rgb(0, 0, 0)" fill="none">
%(visibleContent)s
       </g>
    </g>
</svg>
"""

PATHTEMPLATE = "\t\t\t<path d=\"%s\" />\n"
