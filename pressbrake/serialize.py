"""
JSON serialization of kinematic graphs and envelope reports, mirroring the
marshmallow-based contract style of the repository's schemas.py.
"""

from marshmallow import Schema, fields


class IntervalSetField(fields.Field):
    """
    An IntervalSet as a list of [start, end] pairs.
    """

    def _serialize(self, value, attr, obj, **kwargs):
        if value is None:
            return []
        return [[start, end] for start, end in value.to_pairs()]


class PanelSchema(Schema):
    id = fields.Integer()
    outline = fields.Method("outline_points")
    holes = fields.Method("hole_points")

    def outline_points(self, panel):
        return [[float(x), float(y)] for x, y in panel.outline]

    def hole_points(self, panel):
        return [[[float(x), float(y)] for x, y in hole] for hole in panel.holes]


class BendSchema(Schema):
    id = fields.Integer()
    axis_point = fields.Method("point")
    axis_dir = fields.Method("direction")
    angle_target = fields.Float()
    angle_overbend = fields.Float()
    angle_relaxed = fields.Float()
    inner_radius = fields.Float()
    k_factor = fields.Float()
    length = fields.Float()
    parent_panel = fields.Integer()
    child_panel = fields.Integer()
    moving_mask = fields.Integer()
    sister_group = fields.Integer()

    def point(self, bend):
        return [float(bend.axis_point[0]), float(bend.axis_point[1])]

    def direction(self, bend):
        return [float(bend.axis_dir[0]), float(bend.axis_dir[1])]


class KinematicGraphSchema(Schema):
    source = fields.String()
    thickness = fields.Float()
    z_offset = fields.Float()
    base_panel = fields.Integer()
    panels = fields.List(fields.Nested(PanelSchema))
    bends = fields.List(fields.Nested(BendSchema))


class EnvelopeSchema(Schema):
    punch = fields.String(attribute="punch_id")
    die = fields.String(attribute="die_id")
    feasible = fields.Boolean()
    margin = fields.Float()
    x_range = fields.Method("range_pair")
    required = IntervalSetField()
    forbidden_punch = IntervalSetField()
    forbidden_die = IntervalSetField()
    forbidden_machine = IntervalSetField()

    def range_pair(self, envelope):
        return [float(envelope.x_range[0]), float(envelope.x_range[1])]


class ActionResultSchema(Schema):
    bend_ids = fields.List(fields.Integer())
    sister_group = fields.Integer()
    rotation = fields.Integer()
    flip = fields.Boolean()
    feasible = fields.Boolean()
    envelopes = fields.List(fields.Nested(EnvelopeSchema))
    best = fields.Nested(EnvelopeSchema, allow_none=True)
    collision_summary = fields.String(allow_none=True)


class ReportSchema(Schema):
    source = fields.String()
    machine = fields.String(allow_none=True)
    feasible = fields.Boolean()
    graph = fields.Nested(KinematicGraphSchema)
    actions = fields.List(fields.Nested(ActionResultSchema))


def dump_report(report):
    return ReportSchema().dump(report)


def dump_graph(graph):
    return KinematicGraphSchema().dump(graph)
