#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Generate the AP242 semantic-PMI STEP fixture used by
tests/test_attributes.py.

Writes examples/pmi/pmi_box.step: a 20x30x40 box with one semantic linear
distance dimension (20.0 +0.1/-0.05) between face 1 and face 2 (1-based
TopExp.MapShapes(TopAbs_FACE) order).

Geometric tolerances and standalone datums cannot be authored with
pythonocc 7.9 (XCAFDoc_GeomTolerance is not wrapped, and the AP242 writer
drops datums that no tolerance references), so those extraction paths are
exercised with real CAD exports instead — e.g. the NIST FTC/CTC AP242 test
files (https://www.nist.gov/ctl/smart-connected-systems-division/nist-mbe-pmi-validation-and-conformance-testing-project).

Run from the repo root inside the instapart3 environment:
    python scripts/make_pmi_fixture.py
"""

import os
import sys

from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakeBox
from OCC.Core.IFSelect import IFSelect_RetDone
from OCC.Core.Interface import Interface_Static
from OCC.Core.STEPCAFControl import STEPCAFControl_Writer
from OCC.Core.TDF import TDF_LabelSequence
from OCC.Core.TDocStd import TDocStd_Document
from OCC.Core.TopAbs import TopAbs_FACE
from OCC.Core.TopExp import topexp
from OCC.Core.TopTools import TopTools_IndexedMapOfShape
from OCC.Core.XCAFDoc import XCAFDoc_DocumentTool, XCAFDoc_Dimension
from OCC.Core.XCAFDimTolObjects import (
    XCAFDimTolObjects_DimensionType_Location_LinearDistance,
)

VALUE = 20.0
UPPER = 0.1
LOWER = -0.05


def make_fixture(path):
    box = BRepPrimAPI_MakeBox(20.0, 30.0, 40.0).Shape()

    doc = TDocStd_Document("XmlXCAF")
    shape_tool = XCAFDoc_DocumentTool.ShapeTool(doc.Main())
    dimtol_tool = XCAFDoc_DocumentTool.DimTolTool(doc.Main())

    box_label = shape_tool.AddShape(box, False)

    face_map = TopTools_IndexedMapOfShape()
    topexp.MapShapes(box, TopAbs_FACE, face_map)
    face_1 = shape_tool.AddSubShape(box_label, face_map.FindKey(1))
    face_2 = shape_tool.AddSubShape(box_label, face_map.FindKey(2))

    dimension_label = dimtol_tool.AddDimension()
    # Set() returns the attribute the label already carries
    dimension = XCAFDoc_Dimension.Set(dimension_label)
    dimension_object = dimension.GetObject()
    dimension_object.SetType(XCAFDimTolObjects_DimensionType_Location_LinearDistance)
    dimension_object.SetValue(VALUE)
    dimension_object.SetUpperTolValue(UPPER)
    dimension_object.SetLowerTolValue(LOWER)
    dimension.SetObject(dimension_object)

    firsts = TDF_LabelSequence()
    firsts.Append(face_1)
    seconds = TDF_LabelSequence()
    seconds.Append(face_2)
    dimtol_tool.SetDimension(firsts, seconds, dimension_label)

    writer = STEPCAFControl_Writer()
    Interface_Static.SetCVal("write.step.schema", "AP242DIS")
    writer.SetDimTolMode(True)
    writer.Transfer(doc, 0)

    if writer.Write(path) != IFSelect_RetDone:
        raise RuntimeError("could not write %s" % path)

    print("written", path)


if __name__ == "__main__":
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out_dir = os.path.join(repo_root, "examples", "pmi")
    os.makedirs(out_dir, exist_ok=True)
    make_fixture(os.path.join(out_dir, "pmi_box.step"))
    sys.exit(0)
