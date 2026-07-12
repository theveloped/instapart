#!/usr/bin/env python

# compatibility imports
from __future__ import print_function

import json
import datetime
from enum import Enum


class Colors(Enum):
    WHITE = 7
    MAGENTA = 6
    BLUE = 5
    CYAN = 4
    GREEN = 3
    YELLOW = 2
    RED = 1
    BLACK = 0
    

class Loop(object):

    def __init__(self, wire=None, gap=None, short=None, is_closed=True, feature=None, is_single=False, TOLLERANCE=1e-6):
        self.wires = []
        self.gaps = []
        self.shorts = []
        self.feature = feature
        self.TOLLERANCE = TOLLERANCE

        self.is_single = is_single

        if wire:
            self.wires.append(wire)

        if gap:
            self.gaps.append(gap)

        if short:
            self.shorts.append(short)

    @property
    def short(self):
        gap_count = len(self.gaps)
        gap = self.gaps[-1].Reversed()

        if gap_count > 0:
            for i in range(gap_count - 1):
                gap = gap + self.gaps[i]

        return gap.Magnitude()

    @property
    def is_closed(self):
        # gap_count = len(self.gaps)
        # gap = self.gaps[0]

        # if gap_count > 0:
        #     for i in range(1, gap_count):
        #         gap = gap + self.gaps[i]

        return (self.short <= self.TOLLERANCE)


        # if (self.shorts[-1].Magnitude() <= self.TOLLERANCE)
        #     return True

        # else:
        #     gap = self.gaps[-1] - self.shorts[-1]

        #     # for short in self.shorts:
        #     #     gap = gap + short

        #     return (gap.Magnitude() <= self.TOLLERANCE)

    def add(self, wire=None, gap=None, feature=None):
        if wire:
            self.wires.append(wire)

        if gap:
            # if len(self.gaps) >= 1:
            #     gap = gap + self.gaps[-1]

            self.gaps.append(gap)

        if feature:
            self.feature = feature

    def __dict__(self):
        gaps = []
        for gap in self.gaps:
            gaps.append(gap.Magnitude())

        # shorts = []
        # for short in self.shorts:
        #     shorts.append(short.Magnitude())

        return dict(wires=str(self.wires), gaps=gaps, short=self.short, is_closed=self.is_closed, feature=str(self.feature), is_single=self.is_single)

    def __repr__(self):
        data = self.__dict__()
        return json.dumps(data, sort_keys=True, indent=2, separators=(',', ': '))


class Job(object):

    def __init__(self, input_path, output_dir, timestamp=None, TOLLERANCE=1e-6):
        self.input = input_path
        self.output = output_dir
        self.timestamp = timestamp or datetime.datetime.now()
        self.tree = None
        self.shapes = []
        self.messages = []

    def __repr__(self):
        data = self.__dict__()

        return json.dumps(data, sort_keys=True, indent=2, separators=(',', ': '))


class Shape(object):

    class ShapeTypes(Enum):
        TUBE = 2
        SHEET = 1
        OTHER = 0

    def __init__(self, shape_type=None):
        self.type = shape_type or Shape.ShapeTypes.OTHER

        # content-derived persistent id (identity.solid_content_id)
        self.id = None

        self.area = None
        self.volume = None

        self.width = None
        self.height = None
        self.length = None

        self.section = None
        self.pattern = None

        self.messages = []

    def __dict__(self):
        section = None
        if self.section:
            section = self.section.__dict__()

        return dict(type=self.type.name, area=self.area, volume=self.volume, width=self.width, height=self.height, length=self.length, section=section, messages=self.messages)

    def __repr__(self):
        data = self.__dict__()

        return json.dumps(data, sort_keys=True, indent=2, separators=(',', ': '))


class Section(object):

    class SectionTypes(Enum):
        RECTANGULAR = 3
        SQUARE = 2
        ROUND = 1
        OTHER = 0

    def __init__(self, section_type=None):
        self.type = section_type or Section.SectionTypes.OTHER

        self.width = None
        self.height = None
        self.length = None

        self.thickness = None
        self.inner_radius = None
        self.outer_radius = None

    @property
    def description(self):
        if self.type == Section.SectionTypes.ROUND:
            return "ROUND_{:0.2f}x{:0.2f}_{:0.2f}mm".format(self.width, self.thickness, self.length)

        elif self.type == Section.SectionTypes.SQUARE:
            return "SQUARE_{:0.2f}x{:0.2f}x{:0.2f}R{:0.2f}_{:0.2f}mm".format(self.width, self.height, self.thickness, self.outer_radius, self.length)

        elif self.type == Section.SectionTypes.RECTANGULAR:
            return "RECTANGULAR_{:0.2f}x{:0.2f}x{:0.2f}R{:0.2f}_{:0.2f}mm".format(self.width, self.height, self.thickness, self.outer_radius, self.length)

        else:
            return "UNKNOWN"

    def __dict__(self):
        return dict(type=self.type.name, width=self.width, height=self.height, length=self.length, thickness=self.thickness, inner_radius=self.inner_radius, outer_radius=self.outer_radius)

    def __repr__(self):
        data = self.__dict__()

        return json.dumps(data, sort_keys=True, indent=2, separators=(',', ': '))


class Feature(object):

    class FeatureTypes(Enum):
        COUNTERSINK = 3
        EXTRUSION = 2
        EMBOSSING = 1
        OTHER = 0

    def __init__(self, feature_type=None, component=None, groups=None, base_a=None, base_b=None, loop_a=None, loop_b=None, extrusion=None, embossing=None, chamfer_a=False, chamfer_b=False, wires=None):
        # self.type = feature_type or Section.Feature.FeatureTypes.OTHER

        self.loop_a = loop_a if loop_a is not None else []
        self.loop_b = loop_b if loop_b is not None else []
        self.extrusion = extrusion
        self.embossing = embossing
        self.chamfer_a = chamfer_a
        self.chamfer_b = chamfer_b
        self.wires = wires if wires is not None else []

        self.component = component if component is not None else []
        self.groups = groups if groups is not None else []
        self.base_a = base_a if base_a is not None else []
        self.base_b = base_b if base_b is not None else []

        self.projections = None


    def reverse(self):
        if self.extrusion:
            self.extrusion *= -1

        if self.embossing:
            self.embossing *= -1


    @property
    def type(self):
        if self.embossing:
            return Feature.FeatureTypes.EMBOSSING

        elif self.extrusion:
            return Feature.FeatureTypes.EXTRUSION

        elif self.chamfer_a or self.chamfer_b:
            return Feature.FeatureTypes.COUNTERSINK

        else:
            return Feature.FeatureTypes.OTHER


    @property
    def top(self):
        if self.type == Feature.FeatureTypes.EMBOSSING:
            return self.embossing >= 0

        elif self.type == Feature.FeatureTypes.EXTRUSION:
            return self.extrusion >= 0

        else:
            return self.chamfer_a


    @property
    def bottom(self):
        if self.type == Feature.FeatureTypes.EMBOSSING:
            return self.embossing < 0

        elif self.type == Feature.FeatureTypes.EXTRUSION:
            return self.extrusion < 0

        else:
            return self.chamfer_b


    @property
    def value(self):
        if self.type == Feature.FeatureTypes.EMBOSSING:
            return abs(self.embossing)

        elif self.type == Feature.FeatureTypes.EXTRUSION:
            return abs(self.extrusion)

        else:
            return None


    def __dict__(self):
        return dict(type=self.type.name, top=self.top, bottom=self.bottom, value=self.value)


    def __repr__(self):
        data = self.__dict__()
        return json.dumps(data, sort_keys=True, indent=2, separators=(',', ': '))


