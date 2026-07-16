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
from OCC.Core.XCAFDoc import (
    XCAFDoc_ColorSurf, XCAFDoc_ColorGen, XCAFDoc_DocumentTool,
    XCAFDoc_Dimension, XCAFDoc_Datum, XCAFDoc_DimTolTool,
)
from OCC.Core import XCAFDimTolObjects
from OCC.Core.XCAFDimTolObjects import (
    XCAFDimTolObjects_Tool,
    XCAFDimTolObjects_GeomToleranceObjectSequence,
    XCAFDimTolObjects_DatumObjectSequence,
    XCAFDimTolObjects_DataMapOfToleranceDatum,
)

from models import FaceAttributes, Dimension, GeomTolerance, Datum, PmiData

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


def _enum_names(prefix):
    """{int value: readable name} for one XCAFDimTolObjects enum family."""
    names = {}
    for name in dir(XCAFDimTolObjects):
        if name.startswith(prefix):
            names[int(getattr(XCAFDimTolObjects, name))] = name[len(prefix):]
    return names


_DIMENSION_TYPES = _enum_names("XCAFDimTolObjects_DimensionType_")
_TOLERANCE_TYPES = _enum_names("XCAFDimTolObjects_GeomToleranceType_")
_TOLERANCE_VALUE_TYPES = _enum_names("XCAFDimTolObjects_GeomToleranceTypeValue_")


def _resolve_references(shape_tool, parts_by_label_entry, ref_labels):
    """Resolve PMI reference labels to (part, face_ids, edge_ids).

    Reference labels are XCAF subshape labels (children of the owning shape
    label) or the shape label itself. Faces/edges resolve to their stable
    1-based ids via the hash indexes built by TreeBuilder.mapSubShapes.
    """
    from utils import shape_hash

    part = None
    face_ids = []
    edge_ids = []

    for i in range(1, ref_labels.Length() + 1):
        ref_label = ref_labels.Value(i)

        owner = parts_by_label_entry.get(label_entry(ref_label))
        if owner is None:
            owner = parts_by_label_entry.get(label_entry(ref_label.Father()))
        if owner is None:
            continue

        part = part or owner

        shape = shape_tool.GetShape(ref_label)
        if shape is None or shape.IsNull():
            continue

        if shape.ShapeType() == TopAbs_FACE and owner.face_id_by_source_hash:
            face_id = owner.face_id_by_source_hash.get(shape_hash(shape))
            if face_id:
                face_ids.append(face_id)

        elif shape.ShapeType() == TopAbs_EDGE and owner.edge_id_by_source_hash:
            edge_id = owner.edge_id_by_source_hash.get(shape_hash(shape))
            if edge_id:
                edge_ids.append(edge_id)

    return part, face_ids, edge_ids


def _tag_faces(part, face_ids, pmi_id):
    """Record the PMI entity id on the FaceAttributes of the faces it
    annotates (creating entries for faces that had no color/name)."""
    if part.face_attributes is None:
        part.face_attributes = {}

    for face_id in face_ids:
        if face_id not in part.face_attributes:
            part.face_attributes[face_id] = FaceAttributes(face_id=face_id)
        part.face_attributes[face_id].pmi_refs.append(pmi_id)


def _part_pmi(part):
    if part.pmi is None:
        part.pmi = PmiData()
    return part.pmi


def extract_pmi(doc, shape_tool, parts_by_label_entry):
    """Extract semantic PMI (dimensions, geometric tolerances, datums) from
    the XCAF document and attach it to the parts whose faces it annotates.

    pythonocc 7.9 caveats shape this code:
    - label.FindAttribute(guid, attr) is not callable, but Attribute.Set(label)
      returns the existing attribute for labels that already carry it — used
      for XCAFDoc_Dimension and XCAFDoc_Datum.
    - XCAFDoc_GeomTolerance is not wrapped at all; tolerance semantics come
      from XCAFDimTolObjects_Tool.GetGeomTolerances, whose sequence follows
      GetGeomToleranceLabels order (it iterates the same labels internally),
      so objects pair with labels index-wise.
    """
    dimtol_tool = XCAFDoc_DocumentTool.DimTolTool(doc.Main())
    pmi_id = 0

    # ── dimensions ───────────────────────────────────────────────────────
    dim_labels = TDF_LabelSequence()
    dimtol_tool.GetDimensionLabels(dim_labels)

    for i in range(1, dim_labels.Length() + 1):
        label = dim_labels.Value(i)
        try:
            dimension_object = XCAFDoc_Dimension.Set(label).GetObject()
        except Exception:
            logger.warning("could not read dimension object %s", i)
            continue

        pmi_id += 1
        dimension = Dimension(id=pmi_id,
                              dimension_type=_DIMENSION_TYPES.get(int(dimension_object.GetType())),
                              value=dimension_object.GetValue())

        if dimension_object.IsDimWithPlusMinusTolerance():
            dimension.upper_tolerance = dimension_object.GetUpperTolValue()
            dimension.lower_tolerance = dimension_object.GetLowerTolValue()

        elif dimension_object.IsDimWithRange():
            dimension.upper_tolerance = dimension_object.GetUpperBound() - dimension.value
            dimension.lower_tolerance = dimension_object.GetLowerBound() - dimension.value

        first, second = TDF_LabelSequence(), TDF_LabelSequence()
        dimtol_tool.GetRefShapeLabel(label, first, second)

        part, face_ids, edge_ids = _resolve_references(shape_tool, parts_by_label_entry, first)
        second_part, second_face_ids, _ = _resolve_references(shape_tool, parts_by_label_entry, second)
        part = part or second_part

        dimension.face_ids = face_ids
        dimension.secondary_face_ids = second_face_ids
        dimension.edge_ids = edge_ids

        if part:
            dimension.part_index = part.reference
            _part_pmi(part).dimensions.append(dimension)
            _tag_faces(part, face_ids, pmi_id)
            if second_part:
                _tag_faces(second_part, second_face_ids, pmi_id)

    # ── geometric tolerances ─────────────────────────────────────────────
    tolerance_labels = TDF_LabelSequence()
    dimtol_tool.GetGeomToleranceLabels(tolerance_labels)

    tolerance_objects = XCAFDimTolObjects_GeomToleranceObjectSequence()
    if tolerance_labels.Length():
        try:
            XCAFDimTolObjects_Tool(doc).GetGeomTolerances(
                tolerance_objects,
                XCAFDimTolObjects_DatumObjectSequence(),
                XCAFDimTolObjects_DataMapOfToleranceDatum())
        except Exception:
            logger.exception("could not read geometric tolerance objects")

    for i in range(1, tolerance_labels.Length() + 1):
        label = tolerance_labels.Value(i)

        pmi_id += 1
        tolerance = GeomTolerance(id=pmi_id)

        if i <= tolerance_objects.Length():
            tolerance_object = tolerance_objects.Value(i)
            tolerance.type = _TOLERANCE_TYPES.get(int(tolerance_object.GetType()))
            tolerance.value = tolerance_object.GetValue()
            tolerance.type_of_value = _TOLERANCE_VALUE_TYPES.get(int(tolerance_object.GetTypeOfValue()))

        datum_labels = TDF_LabelSequence()
        dimtol_tool.GetDatumWithObjectOfTolerLabels(label, datum_labels)
        for j in range(1, datum_labels.Length() + 1):
            try:
                datum_object = XCAFDoc_Datum.Set(datum_labels.Value(j)).GetObject()
                name = datum_object.GetName()
                if name is not None:
                    tolerance.datum_names.append(name.ToCString())
            except Exception:
                logger.warning("could not read datum of tolerance %s", i)

        first, second = TDF_LabelSequence(), TDF_LabelSequence()
        dimtol_tool.GetRefShapeLabel(label, first, second)
        part, face_ids, edge_ids = _resolve_references(shape_tool, parts_by_label_entry, first)

        tolerance.face_ids = face_ids
        tolerance.edge_ids = edge_ids

        if part:
            tolerance.part_index = part.reference
            _part_pmi(part).tolerances.append(tolerance)
            _tag_faces(part, face_ids, pmi_id)

    # ── datums ───────────────────────────────────────────────────────────
    datum_labels = TDF_LabelSequence()
    dimtol_tool.GetDatumLabels(datum_labels)

    for i in range(1, datum_labels.Length() + 1):
        label = datum_labels.Value(i)
        try:
            datum_object = XCAFDoc_Datum.Set(label).GetObject()
        except Exception:
            logger.warning("could not read datum object %s", i)
            continue

        pmi_id += 1
        name = datum_object.GetName()
        datum = Datum(id=pmi_id, name=name.ToCString() if name is not None else None)

        first, second = TDF_LabelSequence(), TDF_LabelSequence()
        dimtol_tool.GetRefShapeLabel(label, first, second)
        part, face_ids, edge_ids = _resolve_references(shape_tool, parts_by_label_entry, first)

        datum.face_ids = face_ids
        datum.edge_ids = edge_ids

        if part:
            datum.part_index = part.reference
            _part_pmi(part).datums.append(datum)
            _tag_faces(part, face_ids, pmi_id)


def filter_pmi_for_solid(part_pmi, matched_faces):
    """PmiData restricted to entities annotating any of the given faces
    (FaceAttributes list of one solid). Entities without any resolved face
    reference are kept as well — they belong to the part but cannot be
    narrowed to a single solid."""
    if part_pmi is None:
        return None

    matched_ids = {attributes.face_id for attributes in matched_faces}

    def keep(entity):
        referenced = set(entity.face_ids)
        referenced.update(getattr(entity, "secondary_face_ids", []))
        return not referenced or bool(referenced & matched_ids)

    pmi = PmiData()
    pmi.dimensions = [d for d in part_pmi.dimensions if keep(d)]
    pmi.tolerances = [t for t in part_pmi.tolerances if keep(t)]
    pmi.datums = [d for d in part_pmi.datums if keep(d)]

    return pmi if pmi else None
