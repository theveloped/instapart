#!/usr/bin/env python

# compatibility imports
from __future__ import print_function

import datetime
from marshmallow import Schema, fields, pprint
from OCC.gp import gp_Pnt, gp_Dir, gp_Vec



class LayerSchema(Schema):
    name = fields.Str()
    color = fields.Str()
    linetype = fields.Str()
    text = fields.Str()
    entities = fields.List(fields.Str())


class TemplateSchema(Schema):
    layers = fields.Nested(LayerSchema, many=True)


class KeyField(fields.Int):
    def __init__(self, *args, **kwargs):
        super(KeyField, self).__init__(format="uuid", *args, **kwargs)

    def _serialize(self, value, attr, obj):

        if value:
            return value

        else:
            return None


class DateTimeField(fields.DateTime):
    def __init__(self, *args, **kwargs):
        super(DateTimeField, self).__init__(*args, **kwargs)

    def _serialize(self, value, attr, obj):
        if not value:
            value = datetime.datetime.now()

        return super(DateTimeField, self)._serialize(value, attr, obj)


class EnumField(fields.String):
    def _serialize(self, value, attr, obj):
        if value != None:
            return value.name

        else:
            return None


class PointField(fields.List):
    def __init__(self, *args, **kwargs):
        super(PointField, self).__init__(fields.Float(), *args, **kwargs)

    def _serialize(self, value, attr, obj):
        if value != None:
            if value.bulge:
                return [value.x, value.y, value.bulge]

            else:
                return [value.x, value.y]

        else:
            return None


class BaseSchema(Schema):
    id = KeyField(attribute="id")

    class Meta:
        ordered = True


class EntitySchema(BaseSchema):
    # path = fields.List(fields.List(fields.Float()))
    # path = fields.Nested(PointField, many=True)
    area = fields.Float()
    boundary = fields.Float()

    path = fields.List(PointField())

    type = EnumField()
    kind = fields.Str()
    radius = fields.Float()
    centroid = fields.List(fields.Float())

    
    # bend = fields.Float()
    # inner_radius = fields.Float()

    # embossing = fields.Float()
    # extrusion = fields.Float()


class BendSchema(BaseSchema):
    common_id = fields.Int(dump_to="group")
    angle = fields.Float()
    length = fields.Float()
    inner_radius = fields.Float(dump_to="radius")


class FeatureSchema(BaseSchema):
    type = EnumField()
    top = fields.Bool()
    bottom = fields.Bool()
    value = fields.Float()


class LabelSchema(BaseSchema):
    text = fields.String()
    width = fields.Float()
    height = fields.Float()
    position = PointField()


class PatternSchema(BaseSchema):
    thickness = fields.Float()
    contour = fields.Nested(EntitySchema)
    holes = fields.Nested(EntitySchema, many=True)
    bends = fields.Nested(EntitySchema, many=True)
    other = fields.Nested(EntitySchema, many=True)
    
    origin = PointField()
    width = fields.Float()
    height = fields.Float()

    label = fields.Nested(LabelSchema)

    bend_quantity = fields.Method("get_bend_quantity")
    bend_groups = fields.Method("get_bend_groups")

    def get_bend_quantity(self, pattern):
        return len(pattern.bends) or 0

    def get_bend_groups(self, pattern):
        groups = 0
        for bend in pattern.bends:
            if bend.common_id > groups:
                groups = bend.common_id

        return groups
        

class SectionSchema(BaseSchema):
    type = EnumField()
    width = fields.Float()
    height = fields.Float()
    length = fields.Float()
    thickness = fields.Float()
    inner_radius = fields.Float()
    outer_radius = fields.Float()


class MessageSchema(BaseSchema):
    code = fields.Int()
    description = fields.Str()
    value = fields.Float()


class FileSchema(BaseSchema):
    path = fields.Str()


class ShapeSchema(BaseSchema):
    type = EnumField()

    area = fields.Float()
    volume = fields.Float()

    width = fields.Float()
    height = fields.Float()
    length = fields.Float()

    bends = fields.Nested(BendSchema, many=True)
    section = fields.Nested(SectionSchema)
    pattern = fields.Nested(PatternSchema)
    features = fields.Nested(FeatureSchema, many=True)

    messages = fields.Nested("MessageSchema", many=True)
    files = fields.Nested("FileSchema", many=True)


class TreeSchema(BaseSchema):
    id = KeyField(attribute="id")
    root = fields.String()
    name = fields.String()
    level = fields.Int()
    index = fields.Int()
    count = fields.Int()

    reference = fields.Int()
    components = fields.Nested("TreeSchema", many=True)

    is_assembly = fields.Bool()
    is_free = fields.Bool()
    is_shape = fields.Bool()
    is_compound = fields.Bool()
    is_component = fields.Bool()
    is_simple = fields.Bool()
    is_reference = fields.Bool()

    translation = fields.Method("get_translation")
    orientation = fields.Method("get_orientation")

    shapes = fields.Nested("ShapeSchema", many=True, attribute="solids")
    messages = fields.Nested("MessageSchema", many=True)

    def get_translation(self, tree):
        translation = tree.location.Transformation().TranslationPart()
        return translation.Coord(1), translation.Coord(1), translation.Coord(1)

    def get_orientation(self, tree):
        # v = gp_Vec()
        # angle = 0.0
        # tree.location.Transformation().GetRotation().GetVectorAndAngle(v, angle)
        # return (v.X(), v.Y(), v.Z(), angle)  # angles

        v = gp_Vec()
        angle = tree.location.Transformation().GetRotation().GetVectorAndAngle(v)
        return (v.X(), v.Y(), v.Z(), angle)  # angles


class JobSchema(BaseSchema):
    file = fields.Str()
    timestamp = DateTimeField()

    tree = fields.Nested("TreeSchema")
    messages = fields.Nested("MessageSchema", many=True)


