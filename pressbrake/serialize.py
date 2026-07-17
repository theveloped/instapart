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


class PlacedSectionSchema(Schema):
    length = fields.Float()
    x_start = fields.Float()
    x_end = fields.Float()
    horn = fields.String(allow_none=True)


class ToolRunSchema(Schema):
    x_start = fields.Float()
    x_end = fields.Float()
    length = fields.Float()
    sections = fields.List(fields.Nested(PlacedSectionSchema))


class ToolPlacementSchema(Schema):
    tool = fields.String(attribute="tool_id")
    kind = fields.String()
    feasible = fields.Boolean()
    reason = fields.String()
    section_count = fields.Integer()
    total_length = fields.Float()
    total_mass = fields.Float()
    runs = fields.List(fields.Nested(ToolRunSchema))


class SetupPlanSchema(Schema):
    punch_id = fields.String()
    die_id = fields.String()
    step_indices = fields.List(fields.Integer())
    feasible = fields.Boolean()
    reason = fields.String()
    punch = fields.Nested(ToolPlacementSchema, attribute="punch_placement",
                          allow_none=True)
    die = fields.Nested(ToolPlacementSchema, attribute="die_placement",
                        allow_none=True)


class ProcessStepSchema(Schema):
    bend_ids = fields.List(fields.Integer())
    sister_group = fields.Integer()
    rotation = fields.Method("action_rotation")
    flip = fields.Method("action_flip")

    def action_rotation(self, step):
        return step.action.rotation

    def action_flip(self, step):
        return bool(step.action.flip)


class ProcessPlanSchema(Schema):
    feasible = fields.Boolean()
    objective = fields.Method("objective_list")
    steps = fields.List(fields.Nested(ProcessStepSchema))
    setups = fields.List(fields.Nested(SetupPlanSchema))

    def objective_list(self, plan):
        return list(plan.objective)


class SearchReportSchema(Schema):
    source = fields.String()
    machine = fields.String(allow_none=True)
    feasible = fields.Boolean()
    exhaustive = fields.Boolean()
    stats = fields.Dict()
    graph = fields.Nested(KinematicGraphSchema)
    plans = fields.List(fields.Nested(ProcessPlanSchema))


def dump_report(report):
    return ReportSchema().dump(report)


def dump_graph(graph):
    return KinematicGraphSchema().dump(graph)


def dump_search_report(result, graph, machine_name=None):
    return SearchReportSchema().dump({
        "source": graph.source,
        "machine": machine_name,
        "feasible": result.feasible,
        "exhaustive": result.exhaustive,
        "stats": result.stats,
        "graph": graph,
        "plans": result.plans,
    })
