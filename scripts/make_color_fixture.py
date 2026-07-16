#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Generate the deterministic colored + named STEP fixture used by
tests/test_attributes.py.

Writes examples/colors/colored_box.step: a 20x30x40 box named "colored_box"
with face 1 colored red and named "LASER_FACE", and face 3 colored green
(face ids are 1-based TopExp.MapShapes(TopAbs_FACE) order).

Run from the repo root inside the instapart3 environment:
    python scripts/make_color_fixture.py
"""

import os
import sys

from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakeBox
from OCC.Core.IFSelect import IFSelect_RetDone
from OCC.Core.Interface import Interface_Static
from OCC.Core.Quantity import Quantity_Color, Quantity_TOC_RGB
from OCC.Core.STEPCAFControl import STEPCAFControl_Writer
from OCC.Core.TDataStd import TDataStd_Name
from OCC.Core.TDocStd import TDocStd_Document
from OCC.Core.TopAbs import TopAbs_FACE
from OCC.Core.TopExp import topexp
from OCC.Core.TopTools import TopTools_IndexedMapOfShape
from OCC.Core.XCAFDoc import XCAFDoc_DocumentTool, XCAFDoc_ColorSurf

RED = (1.0, 0.0, 0.0)
GREEN = (0.0, 1.0, 0.0)
FACE_NAME = "LASER_FACE"


def make_fixture(path):
    box = BRepPrimAPI_MakeBox(20.0, 30.0, 40.0).Shape()

    doc = TDocStd_Document("XmlXCAF")
    shape_tool = XCAFDoc_DocumentTool.ShapeTool(doc.Main())
    color_tool = XCAFDoc_DocumentTool.ColorTool(doc.Main())

    box_label = shape_tool.AddShape(box, False)
    TDataStd_Name.Set(box_label, "colored_box")

    face_map = TopTools_IndexedMapOfShape()
    topexp.MapShapes(box, TopAbs_FACE, face_map)

    label_1 = shape_tool.AddSubShape(box_label, face_map.FindKey(1))
    label_3 = shape_tool.AddSubShape(box_label, face_map.FindKey(3))
    TDataStd_Name.Set(label_1, FACE_NAME)
    color_tool.SetColor(label_1, Quantity_Color(*RED, Quantity_TOC_RGB), XCAFDoc_ColorSurf)
    color_tool.SetColor(label_3, Quantity_Color(*GREEN, Quantity_TOC_RGB), XCAFDoc_ColorSurf)

    writer = STEPCAFControl_Writer()
    Interface_Static.SetCVal("write.step.schema", "AP214IS")
    # Subshape names are not written by default
    Interface_Static.SetIVal("write.stepcaf.subshapes.name", 1)
    writer.Transfer(doc, 0)

    if writer.Write(path) != IFSelect_RetDone:
        raise RuntimeError("could not write %s" % path)

    print("written", path)


if __name__ == "__main__":
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out_dir = os.path.join(repo_root, "examples", "colors")
    os.makedirs(out_dir, exist_ok=True)
    make_fixture(os.path.join(out_dir, "colored_box.step"))
    sys.exit(0)
