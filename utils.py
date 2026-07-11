#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""A module-level docstring

Notice the comment above the docstring specifying the encoding.
Docstrings do appear in the bytecode, so you can access this through
the ``__doc__`` attribute. This is also what you'll see if you call
help() on a module or any other Python object.
"""

# general imports
import os
import sys
import glob
import argparse
from contextlib import contextmanager
from random import randint

# pythonOCC imports
from OCC.Core.IFSelect import IFSelect_RetDone
from OCC.Core.STEPControl import STEPControl_Reader

from OCC.Core.BRepBuilderAPI import BRepBuilderAPI_Sewing, BRepBuilderAPI_MakeSolid
from OCC.Core.TopExp import TopExp_Explorer
from OCC.Core.TopoDS import topods
from OCC.Core.TopAbs import (TopAbs_VERTEX, TopAbs_EDGE, TopAbs_FACE, TopAbs_WIRE,
                             TopAbs_SHELL, TopAbs_SOLID, TopAbs_COMPOUND, TopAbs_COMPSOLID)
from OCC.Core.GProp import GProp_GProps
from OCC.Core.BRepGProp import brepgprop

from OCC.Core.TopoDS import TopoDS_Compound
from OCC.Core.BRep import BRep_Builder

import re
import logging
logger = logging.getLogger()

@contextmanager
def redirect_stdout(target):
    original = sys.stdout
    sys.stdout = target
    yield
    sys.stdout = original


def supress_stdout(func):
    def wrapper(*a, **ka):
        with open(os.devnull, 'w') as devnull:
            with redirect_stdout(devnull):
                func(*a, **ka)
    return wrapper

def sanitize_filename(filename):
   filename = re.sub(r'[^\w\-_\. ]', '_', filename)
   return filename

class suppress_stdout_stderr(object):
    '''
    A context manager for doing a "deep suppression" of stdout and stderr in
    Python, i.e. will suppress all print, even if the print originates in a
    compiled C/Fortran sub-function.
       This will not suppress raised exceptions, since exceptions are printed
    to stderr just before a script exits, and after the context manager has
    exited (at least, I think that is why it lets exceptions through).

    '''
    def __init__(self):
        # Open a pair of null files
        self.null_fds =  [os.open(os.devnull,os.O_RDWR) for x in range(2)]
        # Save the actual stdout (1) and stderr (2) file descriptors.
        self.save_fds = [os.dup(1), os.dup(2)]

    def __enter__(self):
        # Assign the null pointers to stdout and stderr.
        os.dup2(self.null_fds[0],1)
        os.dup2(self.null_fds[1],2)

    def __exit__(self, *_):
        # Re-assign the real stdout/stderr back to (1) and (2)
        os.dup2(self.save_fds[0],1)
        os.dup2(self.save_fds[1],2)
        # Close all file descriptors
        for fd in self.null_fds + self.save_fds:
            os.close(fd)


class StageTimer(object):
    """Accumulates wall time per pipeline stage.

    Used by the benchmark harness: auto.main takes an optional StageTimer so
    the production pipeline times itself and the harness never has to mirror
    the call sequence. If progress_path is given, the current stage name is
    flushed to that file on entry so a native crash can be attributed.
    """

    def __init__(self, progress_path=None):
        self.times = {}
        self.progress_path = progress_path

    @contextmanager
    def stage(self, name):
        from time import perf_counter
        if self.progress_path:
            try:
                with open(self.progress_path, "w") as fh:
                    fh.write('{"stage": "%s"}' % name)
                    fh.flush()
                    os.fsync(fh.fileno())
            except OSError:
                pass
        start = perf_counter()
        try:
            yield
        finally:
            self.times[name] = self.times.get(name, 0.0) + perf_counter() - start


@contextmanager
def _null_stage(name):
    yield


class NullTimer(object):
    """No-op StageTimer stand-in."""

    times = {}

    def stage(self, name):
        return _null_stage(name)


def shape_hash(shape):
    """Stable identity key for a TopoDS_Shape, replacing the removed
    shape.HashCode(upper) API (OCCT 7.8+). pythonocc wires __hash__ to
    std::hash<TopoDS_Shape>, which keys on TShape + Location and ignores
    orientation — the same identity semantics the AAG relied on.
    """
    return hash(shape)


def get_rondom_color():
    """Return a random color string for rendering using pythonOCC"""

    colors = ['WHITE', 'BLUE', 'RED', 'GREEN', 'YELLOW', 'CYAN', 'BLACK', 'ORANGE']
    return colors[randint(0, 7)]


def mean(numbers):
    return float(sum(numbers)) / max(len(numbers), 1)


def get_area(shape, TOLLERANCE=1e-5):
    """
    Compute area of face
    """

    try:
        props = GProp_GProps()
        brepgprop.SurfaceProperties(shape, props, TOLLERANCE)
        return props.Mass()

    except Exception:
        logger.warning("Area computation failed, returning 0", exc_info=True)
        return 0


def get_volume(shape, TOLLERANCE=1e-5):
    """
    Compute volume of solid
    """

    try:
        props = GProp_GProps()
        brepgprop.VolumeProperties(shape, props, TOLLERANCE)
        return props.Mass()

    except Exception:
        logger.warning("Volume computation failed, returning 0", exc_info=True)
        return 0


def import_step(step_path):
    """
    Import step file
    """
    step_reader = STEPControl_Reader()
    status = step_reader.ReadFile(step_path)

    if status == IFSelect_RetDone:
        # fails_only = False
        # step_reader.PrintCheckLoad(fails_only, IFSelect_ItemsByEntity)
        # step_reader.PrintCheckTransfer(fails_only, IFSelect_ItemsByEntity)

        if not step_reader.TransferRoot(1):
            raise RuntimeError('Can not transfer root')

        number_of_shapes = step_reader.NbShapes()
        if number_of_shapes >= 1:
            # return step_reader.Shape(1)
            return step_reader.OneShape()

        else:
            raise RuntimeError('The input STEP file does not have shapes')
    else:
        raise RuntimeError('Can not read {0} file'.format(step_path))


def stitch_shape_solids(shape):
    sewing = BRepBuilderAPI_Sewing()
    face_explorer = TopExp_Explorer(shape, TopAbs_FACE)

    contains_shapes = False
    while face_explorer.More():
        current_face = topods.Face(face_explorer.Current())
        sewing.Add(current_face)
        face_explorer.Next()
        contains_shapes = True

    # Skip if no shapes are added
    if contains_shapes:

        sewing.Perform()
        sewed_shape = sewing.SewedShape()

        if sewed_shape.ShapeType() == TopAbs_SHELL:
            shell = topods.Shell(sewed_shape)
            builder = BRepBuilderAPI_MakeSolid(shell)
            shape = builder.Shape()

            if shape.ShapeType() == TopAbs_SOLID:
                yield shape


def stitch_shell_solids(shape, sort=False):
    solids = []
    shell_explorer = TopExp_Explorer(shape, TopAbs_SHELL)
    while shell_explorer.More():
        current_shell = topods.Shell(shell_explorer.Current())

        for solid in stitch_shape_solids(current_shell):
            if sort:
                solids.append(solid)

            else:
                yield solid

        shell_explorer.Next()

    if sort:
        solids.sort(key=lambda x: get_volume(x), reverse=True)

        for solid in solids:
            yield solid


def iterate_solids(shape, sort=False):
    solids = []
    solid_explorer = TopExp_Explorer(shape, TopAbs_SOLID)
    while solid_explorer.More():
        solid = topods.Solid(solid_explorer.Current())

        if sort:
            solids.append(solid)

        else:
            yield solid

        solid_explorer.Next()

    if sort:
        solids.sort(key=lambda x: get_volume(x), reverse=True)

        for solid in solids:
            yield solid


def get_shape_solids(shape, sort=False, repair=False):
    solid = None
    shapeType = shape.ShapeType()

    if shapeType == TopAbs_SOLID:
        logger.info("Returning original shape as SOLID")
        yield shape

    elif shapeType == TopAbs_SHELL and repair:
        for solid in stitch_shape_solids(shape):
            logger.info("Stitched faces in SHELL to extract a valid SOLID")
            yield solid

    elif shapeType == TopAbs_COMPOUND:
        for solid in iterate_solids(shape, sort=sort):
            logger.info("Extracted SOLID from COMPOUND shape")
            yield solid

        if not solid and repair:
            logger.info("itterate shells")

            for solid in stitch_shell_solids(shape, sort=sort):
                logger.info("Stitched shell to extract SOLID")
                yield solid

            logger.info("itterate shapes general")
            if not solid:
                for solid in stitch_shape_solids(shape):
                    logger.info("Stitched faces to extract SOLID")
                    yield solid

            logger.info("done itterating")

    elif shapeType == TopAbs_COMPSOLID:
        for solid in iterate_solids(shape, sort=sort):
            logger.info("Extracted SOLID from COMPSOLID shape")
            yield solid

        if not solid and repair:
            for solid in stitch_shape_solids(shape):
                logger.info("Stitched faces to extract SOLID")
                yield solid

    else:
        logger.info("Unsupported shape. Can not extract a valid solid.")


def shapeTypeString(shape):
    st = shape.ShapeType()
    s = "Unknown"
    if st == TopAbs_VERTEX:
        s = "Vertex"
    if st == TopAbs_SOLID:
        s = "Solid"
    if st == TopAbs_EDGE:
        s = "Edge"
    if st == TopAbs_FACE:
        s = "Face"
    if st == TopAbs_SHELL:
        s = "Shell"
    if st == TopAbs_WIRE:
        s = "Wire"
    if st == TopAbs_COMPOUND:
        s = "Compound"
    if st == TopAbs_COMPSOLID:
        s = "Compsolid"
    return s


def update_shape_parts(part, updates):
    if part.is_assembly:
        for component in part.components:
            update_shape_parts(component, updates)

    elif len(part.shapes) > 0:
        if part.index in updates:
            for attribute in updates[part.index]:
                if hasattr(part, attribute):
                    setattr(part, attribute, updates[part.index][attribute])


def iterate_shape_parts(part):
    if part.is_assembly:
        for component in part.components:
            for component_part in iterate_shape_parts(component):
                yield component_part

    elif len(part.shapes) > 0:
        yield part

def part_compound_shape(part, force_compound=False):
    if not force_compound or len(part.shapes) == 1:
        return part.shapes[0]

    compound = TopoDS_Compound()
    builder = BRep_Builder()
    builder.MakeCompound(compound)

    for shape in part.shapes:
        builder.Add(compound, shape)

    return compound


def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)


def is_dir(dirname, raise_exceptions=True):
    """
    Checks if a path is an actual directory
    """
    if not os.path.isdir(dirname):
        if raise_exceptions:
            msg = "{0} is not a directory".format(dirname)
            raise argparse.ArgumentTypeError(msg)

        else:
            return None

    return os.path.abspath(os.path.realpath(os.path.expanduser(dirname)))


def is_file(filename, allowed_extensions=None, raise_exceptions=True):
    """
    Checks if a path is an actual file
    """
    if not os.path.isfile(filename):
        if raise_exceptions:
            msg = "{0} is not a file".format(filename)
            raise argparse.ArgumentTypeError(msg)

        else:
            return None

    if allowed_extensions:
        extension = filename.rsplit(".", 1)[-1]

        if not extension.lower() in allowed_extensions:
            if raise_exceptions:
                msg = "{0} is an unsupported file type".format(filename)
                raise argparse.ArgumentTypeError(msg)

            else:
                return None

    return os.path.abspath(os.path.realpath(os.path.expanduser(filename)))


def is_step_file(filename, raise_exceptions=True):
    """
    Checks if a path is an actual dxf file
    """

    return is_file(filename, allowed_extensions=["stp", "step"], raise_exceptions=raise_exceptions)


def is_xml_file(filename, raise_exceptions=True):
    """
    Checks if a path is an actual dxf file
    """

    return is_file(filename, allowed_extensions=["xml"], raise_exceptions=raise_exceptions)


def are_files(path, allowed_extensions=None, raise_exceptions=True):
    """
    Checks if a path all files described by path exist
    """

    file_paths = []
    glob_paths = glob.glob(path)
    if len(glob_paths) > 0:

        for file_path in glob_paths:
            file_path = is_file(file_path, allowed_extensions=allowed_extensions, raise_exceptions=raise_exceptions)
            file_paths.append(file_path)

    else:
        file_path = is_file(path, allowed_extensions=allowed_extensions, raise_exceptions=raise_exceptions)
        file_paths.append(file_path)

    return file_paths


def are_step_files(path, raise_exceptions=True):
    """
    Checks if a path is an actual dxf file
    """

    return are_files(path, allowed_extensions=["stp", "step"], raise_exceptions=raise_exceptions)


def are_xml_files(path, raise_exceptions=True):
    """
    Checks if a path is an actual dxf file
    """

    return are_files(path, allowed_extensions=["xml"], raise_exceptions=raise_exceptions)