# -*- coding: utf-8 -*-
"""XCAF attribute extraction: face colors, face/shape names and semantic PMI.

All lookups run against the prototype shapes stored in the XCAF document
(the labels the STEP reader populated). Faces are addressed by their 1-based
index in TopExp.MapShapes(shape, TopAbs_FACE) order, which is stable across
BRepBuilderAPI_Transform — TreeBuilder uses the same order to bridge these
attributes onto the transformed shapes the rest of the pipeline works with.
"""

from OCC.Core.Quantity import Quantity_Color
from OCC.Core.TCollection import TCollection_AsciiString
from OCC.Core.TDF import TDF_LabelSequence, TDF_Tool
from OCC.Core.TopAbs import TopAbs_FACE, TopAbs_EDGE
from OCC.Core.XCAFDoc import XCAFDoc_ColorSurf, XCAFDoc_ColorGen

from models import FaceAttributes

import logging
logger = logging.getLogger()


def label_entry(label):
    """Tag entry string of a TDF label (e.g. "0:1:1:2"), usable as dict key.
    TDF_Tool.Entry only fills an out-parameter in pythonocc 7.9."""
    entry = TCollection_AsciiString()
    TDF_Tool.Entry(label, entry)
    return entry.ToCString()


def _shape_color(color_tool, shape):
    """Surface color of a shape, falling back to its generic color.

    Lookup goes through the TopoDS_Shape overload of GetColor (which resolves
    the shape's label internally): the TDF_Label overloads are not callable in
    the pythonocc 7.9 bindings (SWIG rejects the label dispatch).
    """
    color = Quantity_Color()
    if color_tool.GetColor(shape, XCAFDoc_ColorSurf, color):
        return (color.Red(), color.Green(), color.Blue())

    if color_tool.GetColor(shape, XCAFDoc_ColorGen, color):
        return (color.Red(), color.Green(), color.Blue())

    return None


def extract_face_attributes(shape_tool, color_tool, label, face_map):
    """Collect per-face colors and names for one shape label.

    Only explicit face-level data creates an entry; the part-level color is
    returned separately so callers can store it once on the part instead of
    repeating it across every face.

    :param label: XCAF prototype shape label of the part
    :param face_map: TopTools_IndexedMapOfShape of the prototype shape's faces
    :return: (part_color, {face_id: FaceAttributes}) — part_color may be None,
             the dict holds only faces that carry data
    """
    attributes = {}

    def get(face_id):
        if face_id not in attributes:
            attributes[face_id] = FaceAttributes(face_id=face_id)
        return attributes[face_id]

    part_color = _shape_color(color_tool, shape_tool.GetShape(label))

    for face_id in range(1, face_map.Size() + 1):
        face_color = _shape_color(color_tool, face_map.FindKey(face_id))

        if face_color is not None:
            face = get(face_id)
            face.color = face_color

    # Names ride on subshape labels (only present when the STEP file names
    # individual faces and read.stepcaf.subshapes.name is enabled). Most
    # exporters fill the ADVANCED_FACE name with the placeholder 'NONE';
    # only user-assigned names are worth keeping.
    sub_labels = TDF_LabelSequence()
    shape_tool.GetSubShapes(label, sub_labels)

    for i in range(1, sub_labels.Length() + 1):
        sub_label = sub_labels.Value(i)
        # Face names are user data (e.g. "polish this"); do not sanitize.
        name = sub_label.GetLabelName()
        if not name or name == "NONE":
            continue

        sub_shape = shape_tool.GetShape(sub_label)
        if sub_shape is None or sub_shape.IsNull():
            continue

        if sub_shape.ShapeType() != TopAbs_FACE:
            continue

        face_id = face_map.FindIndex(sub_shape)
        if face_id > 0:
            get(face_id).name = name

    return part_color, attributes
