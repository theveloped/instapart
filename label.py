#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""A module-level docstring

Notice the comment above the docstring specifying the encoding.
Docstrings do appear in the bytecode, so you can access this through
the ``__doc__`` attribute. This is also what you'll see if you call
help() on a module or any other Python object.
"""

# compatibility imports
from __future__ import print_function

# general imports
import os
import sys
import json
import pyclipper
from geometry import Point, Path, almostEqual, almostZero

INFINATE = 2**31
TOLLERANCE = 1e-6
CONVERSION = int(1 / TOLLERANCE)

import logging
logger = logging.getLogger()


def main(pattern, text=None, font_height=10.0, font_ratio=0.6):
    logger.info("Labeling pattern with: {0}".format(text))

    font_width = len(text) * font_ratio * font_height
    # Compute text bounding box
    text = ((-font_width/2, -font_height/2),
            (font_width/2, -font_height/2),
            (font_width/2, font_height/2),
            (-font_width/2, font_height/2))

    text = pyclipper.scale_to_clipper(text, scale=CONVERSION)

    # Convert contour to clipper path
    contour = []
    for point in pattern.contour.approximate():
        contour.append((point[0], point[1]))

    # contour.append((pattern.contour.path[0][0], pattern.contour.path[0][1]))
    contour = pyclipper.scale_to_clipper(contour, scale=CONVERSION)

    # Compute minkowski differnece
    inner_fit_polygon = pyclipper.MinkowskiDiff(text, contour)
    if len(inner_fit_polygon) == 0:
        return None

    # Compute initial solution space
    pc = pyclipper.Pyclipper()
    pc.AddPath(contour, pyclipper.PT_SUBJECT, True)
    pc.AddPaths(inner_fit_polygon, pyclipper.PT_CLIP, True)
    inner_fit_polygon = pc.Execute(pyclipper.CT_INTERSECTION, pyclipper.PFT_EVENODD, pyclipper.PFT_POSITIVE)

    # Remove contour itself from solution space. Could be multiple polygons.
    for i in range(len(inner_fit_polygon) - 1, -1, -1):
        for point in inner_fit_polygon[i]:
            if point in contour:
                inner_fit_polygon.pop(i)
                break

    if len(inner_fit_polygon) <= 0:
        return None

    # Remove holes from solution
    hole_paths = []
    pc = pyclipper.Pyclipper()
    pc.AddPaths(inner_fit_polygon, pyclipper.PT_SUBJECT, True)
    for hole in pattern.holes:

        hole_path = []
        hole_approximation = hole.approximate()
        for point in hole_approximation:
            hole_path.append((point[0], point[1]))

        # Check text bb fits fully over feature (solves error in minkowski diff)
        min_point = hole_approximation.min()
        max_point = hole_approximation.max()
        width = max_point.x - min_point.x
        height = max_point.y - min_point.y

        hole_path = pyclipper.scale_to_clipper(hole_path, scale=CONVERSION)
        hole_paths.append(hole_path)

        hole_fit_polygon = pyclipper.MinkowskiDiff(text, hole_path)

        if width <= font_width and height <= font_height:
            pc.AddPath(hole_fit_polygon.pop(0), pyclipper.PT_CLIP, True)

        else:
            pc.AddPaths(hole_fit_polygon, pyclipper.PT_CLIP, True)

    inner_fit_polygon = pc.Execute(pyclipper.CT_DIFFERENCE, pyclipper.PFT_EVENODD, pyclipper.PFT_POSITIVE)
    if len(inner_fit_polygon) == 0:
        return None

    # Remove bends from solution
    pc = pyclipper.Pyclipper()
    pc.AddPaths(inner_fit_polygon, pyclipper.PT_SUBJECT, True)
    for bend in pattern.bends:
        bend_path = []

        for point in bend.approximate():
            bend_path.append((point[0], point[1]))

        bend_path = pyclipper.scale_to_clipper(bend_path, scale=CONVERSION)
        bend_fit_polygon = pyclipper.MinkowskiDiff(text, bend_path)

        if len(bend_fit_polygon) > 0:
            pc.AddPaths(bend_fit_polygon, pyclipper.PT_CLIP, True)

    inner_fit_polygon = pc.Execute(pyclipper.CT_DIFFERENCE, pyclipper.PFT_EVENODD, pyclipper.PFT_POSITIVE)
    if len(inner_fit_polygon) == 0:
        return None

    # Remove solution space inside holes
    pc = pyclipper.Pyclipper()
    pc.AddPath(contour, pyclipper.PT_SUBJECT, True)

    if len(hole_paths) > 0:
        pc.AddPaths(hole_paths, pyclipper.PT_SUBJECT, True)

    if len(inner_fit_polygon) > 0:
        pc.AddPaths(inner_fit_polygon, pyclipper.PT_CLIP, True)

    inner_fit_polygon = pc.Execute(pyclipper.CT_INTERSECTION, pyclipper.PFT_EVENODD, pyclipper.PFT_POSITIVE)
    if len(inner_fit_polygon) == 0:
        return None

    # Convert result to python
    paths = []
    for path in inner_fit_polygon:
        nfp = Path(pyclipper.scale_from_clipper(path, scale=CONVERSION))
        nfp.append(nfp[0])
        paths.append(nfp)

    return paths






