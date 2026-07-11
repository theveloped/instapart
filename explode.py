# -*- coding: utf-8 -*-
from OCC.Core.TDocStd import TDocStd_Document
from OCC.Core.XCAFDoc import XCAFDoc_DocumentTool, XCAFDoc_ShapeTool
from OCC.Core.STEPCAFControl import STEPCAFControl_Reader
from OCC.Core.IFSelect import IFSelect_RetDone
from OCC.Core.TDF import TDF_LabelSequence, TDF_Label, TDF_Tool, TDF_AttributeIterator
from OCC.Core.TDataStd import TDataStd_Name
from OCC.Core.TCollection import TCollection_ExtendedString, TCollection_AsciiString
from OCC.Core.TopLoc import TopLoc_Location
from OCC.Core.BRepBuilderAPI import BRepBuilderAPI_Transform

import os
import sys
import json
import traceback

# export
from OCC.Core.STEPControl import STEPControl_Writer
from OCC.Core.Interface import Interface_Static
from OCC.Core.STEPControl import STEPControl_AsIs

from OCC.Core.TopoDS import TopoDS_Compound
from OCC.Core.BRep import BRep_Builder

import uuid

# utils
from utils import get_rondom_color, iterate_shape_parts, part_compound_shape, get_shape_solids, redirect_stdout, suppress_stdout_stderr, sanitize_filename, shape_hash
from naming import generate_name

import logging
logger = logging.getLogger()

class Part(object):

    def __init__(self, id=None, root=None, name=None, index=0, level=0, label=None, shape=None, shapes=[], solids=[], messages=[], location=None, reference=None, components=[]):
        self.id = id
        self.count = None
        self.root = root
        self.name = name
        self.index = index
        self.level = level
        self.label = label
        self.shape = shape
        self.shapes = shapes
        self.location = location
        self.reference = reference
        self.components = components

        self.solids = solids
        self.messages = messages

        if not id:
            # uuid similar to NDB datastore
            self.id = uuid.uuid4().int >> 75

    def __dict__(self):
        json_components = []
        for component in self.components:
            json_components.append(component.__dict__())

        json_solids = []
        for solid in self.solids:
            json_solids.append(solid.__dict__())

        return dict(name=self.name, count=self.count, components=json_components, location=str(self.location), level=self.level, shapes=json_solids, messages=self.messages, label=str(self.label), index=str(self.index))

    def __repr__(self):
        data = self.__dict__()

        return json.dumps(data, sort_keys=True, indent=2, separators=(',', ': '))


class TreeBuilder(object):
    """ A class for analyzing the assembly structure of a STEP file"""

    def __init__(self, filename):
        self.filename = filename
        self.part_names = set()
        self.part_index = 0
        self.references = {}

        # Create the document (handles are transparent since pythonocc 7.x;
        # no XCAFApp application needed for reading). Pass a plain str: the
        # pythonocc 7.9 TCollection_ExtendedString overload hard-crashes here.
        # The document must stay referenced on self or the shape tool ends up
        # pointing into a freed document (empty GetFreeShapes).
        self.doc = TDocStd_Document("MDTV-CAF")
        doc = self.doc
        self.shape_tool = XCAFDoc_DocumentTool.ShapeTool(doc.Main())
        # self.color_tool = XCAFDoc_DocumentTool.ColorTool(doc.Main())
        # self.material_tool = XCAFDoc_DocumentTool.MaterialTool(doc.Main())

        with suppress_stdout_stderr():

            step_reader = STEPCAFControl_Reader()
            step_reader.SetColorMode(True)
            step_reader.SetLayerMode(True)
            step_reader.SetNameMode(True)
            step_reader.SetMatMode(True)

            status = step_reader.ReadFile(filename)
            if status == IFSelect_RetDone:
                step_reader.Transfer(doc)

            XCAFDoc_ShapeTool.SetAutoNaming(True)

    def get_label_name(self, lab):
        # pythonocc 7.x wraps the TDataStd_Name lookup as a label helper
        # (FindAttribute with an out-handle is not callable from Python here)
        name = lab.GetLabelName()
        if name:
            return sanitize_filename(name)

        return "No Name"

    def getComponents(self, parent, ignore_duplicates=False, display=None):
        components = []
        l_c = TDF_LabelSequence()
        self.shape_tool.GetComponents(parent.label, l_c)

        for i in range(l_c.Length()):
            label = l_c.Value(i + 1)

            if self.shape_tool.IsReference(label):
                label_reference = TDF_Label()
                self.shape_tool.GetReferredShape(label, label_reference)

                location = self.shape_tool.GetLocation(label)
                absolute_location = parent.location.Multiplied(location)

                component = self.getPart(label_reference, level=parent.level + 1, root=parent.root, location=absolute_location, ignore_duplicates=ignore_duplicates, display=display)
                if component:
                    components.append(component)

        return components

    def getShapes(self, part, display=None):
        shapes = []
        shape = self.shape_tool.GetShape(part.label)

        reference_hash = shape_hash(shape)
        if reference_hash not in self.references:
            self.references[reference_hash] = part.index

        part.reference = self.references[reference_hash]
        part.shape = shape

        # Transformation paramaters of shape
        transformation = part.location.Transformation()

        # Build transformed shape
        shape = BRepBuilderAPI_Transform(shape, transformation).Shape()
        shapes.append(shape)

        if display:
            color = get_rondom_color()
            display.DisplayColoredShape(shape, color, update=True)

        # SIMPLE SUB-SHAPES
        # l_subss = TDF_LabelSequence()
        # self.shape_tool.GetSubShapes(part.label, l_subss)

        # for i in range(l_subss.Length()):
        #     label = l_subss.Value(i + 1)

        #     shape = self.shape_tool.GetShape(label)
        #     shapes.append(shape)

        #     if display:
        #         display.DisplayColoredShape(shape, color)

        return shapes

    def getPart(self, label, level=0, root=None, location=TopLoc_Location(), ignore_duplicates=False, display=None):
        part = Part(label=label, level=level, root=root, index=self.part_index, location=location)

        # Fast shortcut for to ignore duplicates
        label_name = self.get_label_name(label)
        if ignore_duplicates and label_name in self.part_names:
            return None
        else:
            self.part_names.add(label_name)

        # if self.shape_tool.IsAssembly(label):
        #     print("%s[+] %s %s %s" % ("  " * level, label_name, self.part_index, label_name in self.part_names))
        # else:
        #     print("%s -  %s %s %s" % ("  " * max(0, level), label_name, self.part_index, label_name in self.part_names))

        self.part_index += 1

        part.is_assembly = self.shape_tool.IsAssembly(part.label)
        part.is_free = self.shape_tool.IsFree(part.label)
        part.is_shape = self.shape_tool.IsShape(part.label)
        part.is_compound = self.shape_tool.IsCompound(part.label)
        part.is_component = self.shape_tool.IsComponent(part.label)
        part.is_simple = self.shape_tool.IsSimpleShape(part.label)
        part.is_reference = self.shape_tool.IsReference(part.label)

        part.name = label_name
        part.count = max(1, self.shape_tool.GetUsers(part.label, TDF_LabelSequence()))

        if part.is_assembly:
            part.components = self.getComponents(part, ignore_duplicates=ignore_duplicates, display=display)

        elif part.is_simple:
            part.shapes = self.getShapes(part, display=display)

        else:
            # print("[!] neither shape nor assembly")
            return None

        return part


    def findPart(self, label, index):
        print("Looking for part %s current: %s" % (index, self.part_index))

        if str(self.part_index) == str(index):
            print(" - part found")
            return self.shape_tool.GetShape(label)

        self.part_index += 1
        if self.shape_tool.IsAssembly(label):
            l_c = TDF_LabelSequence()
            self.shape_tool.GetComponents(label, l_c)

            for i in range(l_c.Length()):
                print(" - checking component")
                label = l_c.Value(i + 1)

                if self.shape_tool.IsReference(label):
                    label_reference = TDF_Label()
                    self.shape_tool.GetReferredShape(label, label_reference)

                    shape = self.findPart(label_reference, index)
                    if shape:
                        return shape


    def compute(self, root=None, ignore_duplicates=False, display=None):
        labels = TDF_LabelSequence()
        self.shape_tool.GetFreeShapes(labels)

        # In rare cases muliple labels are present in root
        if labels.Length() > 1:
            logger.warning("multiple root labels detected in STEP file")
            self.tree = Part(name=root, root=root)
            self.tree.is_assembly = True
            self.tree.is_free = False
            self.tree.is_shape = False
            self.tree.is_compound = False
            self.tree.is_component = False
            self.tree.is_simple = False
            self.tree.is_reference = False
            self.tree.location = TopLoc_Location()
            self.tree.count = 1
            self.part_index += 1

            components =[]
            for i in range(1, labels.Length() + 1):
                component = self.getPart(labels.Value(i), root=root, level=1, ignore_duplicates=ignore_duplicates, display=display)
                components.append(component)
            self.tree.components = components

        # Simply use standard label
        else:
            self.tree = self.getPart(labels.Value(1), root=root, ignore_duplicates=ignore_duplicates, display=display)

        return self.tree

    def find(self, index):
        labels = TDF_LabelSequence()
        self.shape_tool.GetFreeShapes(labels)
        shape = self.findPart(labels.Value(1), index=index)
        return shape


def write_step_file(a_shape, filename, application_protocol="AP203"):
    """ exports a shape to a STEP file
    a_shape: the topods_shape to export (a compound, a solid etc.)
    filename: the filename
    application protocol: "AP203" or "AP214"
    """
    # a few checks
    if a_shape.IsNull():
        raise AssertionError("Shape %s is null." % a_shape)

    if application_protocol not in ["AP203", "AP214IS"]:
        raise AssertionError("application_protocol must be either AP203 or AP214IS. You passed %s." % application_protocol)

    if os.path.isfile(filename):
        logger.warning("{} file already exists and will be replaced".format(filename))

    # creates and initialise the step exporter
    step_writer = STEPControl_Writer()
    Interface_Static.SetCVal("write.step.schema", application_protocol)

    # transfer shapes and write file
    step_writer.Transfer(a_shape, STEPControl_AsIs)
    status = step_writer.Write(filename)

    if not status == IFSelect_RetDone:
        raise AssertionError("Error while writing shape to STEP file.")

    if not os.path.isfile(filename):
        raise AssertionError("File %s was not saved to filesystem." % filename)


def export_part(part, output_dir, quantities={}):
    if part.is_assembly:
        for component in part.components:
            export_part(component, output_dir, quantities=quantities)

    elif len(part.shapes) > 0:
        compound = TopoDS_Compound()
        builder = BRep_Builder()
        builder.MakeCompound(compound)

        for shape in part.shapes:
            builder.Add(compound, shape)

        write_step_file(compound, os.path.join(output_dir, part.name + "_x" + str(quantities[part.name]) + ".stp"))


def export_tree(part, output_dir):
    if part.is_assembly:
        for component in part.components:
            export_tree(component, output_dir)

    elif len(part.shapes) > 0:
        if part.index == part.reference:
            file_name = str(part.root) + "_" + str(part.reference) + ".stp"
            file_path = os.path.join(output_dir, file_name)

            print("FILEPATH: " + file_path)

            # if not os.path.isfile(file_path):
            write_step_file(part.shape, file_path)

    # elif len(part.shapes) > 0:
    #     compound = TopoDS_Compound()
    #     builder = BRep_Builder()
    #     builder.MakeCompound(compound)

    #     for shape in part.shapes:
    #         builder.Add(compound, shape)

    #     write_step_file(compound, os.path.join(output_dir, part.id + ".stp"))


def count_parts(part, quantities={}):
    if part.is_assembly:
        for component in part.components:
            quantities = count_parts(component, quantities=quantities)

    elif len(part.shapes) > 0:
        if part.name in quantities:
            quantities[part.name] += 1

        else:
            quantities[part.name] = 1

    return quantities


def main(file_path, output_dir, extension="stp", explode_bodies=False, limit_bodies=None, display=None,
            filename_source="PART",
            filename_charset=None,
            filename_min=None,
            filename_max=None,
            filename_trim="END",
            filename_prefix=None,
            filename_postfix=None,
            export_names={}
        ):
    input_file = os.path.basename(file_path)
    input_file = input_file.rsplit(".", 1)[0]
    if output_dir not in export_names:
        export_names[output_dir] = [input_file]

    try:
        with suppress_stdout_stderr():
            builder = TreeBuilder(file_path)
            tree = builder.compute(ignore_duplicates=False, root=input_file, display=display)

    except Exception:
        logger.error("Could not read file and/or assembly structure")
        # traceback.print_exc()
        return export_names


    quantities = count_parts(tree, quantities={})
    for part in iterate_shape_parts(tree):
        solid_index = 0
        part.count = quantities[part.name]
        shape = part_compound_shape(part)

        if part.index != part.reference:
            continue

        logger.info("PART FOUND {0}x, {1}".format(part.count, part.name))

        if explode_bodies:
            for solid in get_shape_solids(shape, sort=True):
                solid_index += 1

                logger.info("SOLID FOUND {0}x, {1}_{2}".format(part.count, part.name, solid_index))

                original_name, export_name = generate_name(input_file, part, export_names[output_dir],
                        source=filename_source,
                        charset=filename_charset,
                        min_length=filename_min,
                        max_length=filename_max,
                        trim_side=filename_trim,
                        prefix=filename_prefix,
                        postfix=filename_postfix
                    )
                export_names[output_dir].append(original_name)

                output_file = "{}.{}".format(export_name, extension)
                output_path = os.path.join(output_dir, output_file)

                with suppress_stdout_stderr():
                        write_step_file(solid, output_path)

                if limit_bodies != None:
                    if solid_index >= limit_bodies:
                        break

        else:
            original_name, export_name = generate_name(input_file, part, export_names[output_dir],
                    source=filename_source,
                    charset=filename_charset,
                    min_length=filename_min,
                    max_length=filename_max,
                    trim_side=filename_trim,
                    prefix=filename_prefix,
                    postfix=filename_postfix
                )
            export_names[output_dir].append(original_name)

            output_file = "{}.{}".format(export_name, extension)
            output_path = os.path.join(output_dir, output_file)

            # file_name = "{}_x{}.{}".format(part.name, part.count, extension)

            # with open(os.devnull, 'w') as devnull:
            #     with redirect_stdout(devnull):
            with suppress_stdout_stderr():
                write_step_file(shape, output_path)

    return export_names
    # export_part(tree, output_dir, quantities=quantities)


# Entry point for console script
display, start_display, add_menu, add_function_to_menu = (None, None, None, None)
def is_dir(dirname):
    """Checks if a path is an actual directory"""
    if not os.path.isdir(dirname):
        msg = "{0} is not a directory".format(dirname)
        raise argparse.ArgumentTypeError(msg)
    else:
        return os.path.abspath(os.path.realpath(os.path.expanduser(dirname)))

def is_file(filename):
    """Checks if a path is an actual directory"""
    if not os.path.isfile(filename):
        msg = "{0} is not a file".format(filename)
        raise argparse.ArgumentTypeError(msg)
    else:
        return os.path.abspath(os.path.realpath(os.path.expanduser(filename)))

if __name__ == '__main__':
    import argparse
    import OCC.Display.SimpleGui

    parser = argparse.ArgumentParser()
    parser.add_argument("input", help="input file [.stp, .step]", type=is_file)
    parser.add_argument("-o", "--output", help="output directory", type=is_dir)
    parser.add_argument("-d", "--display", action='store_true')
    args = parser.parse_args()

    # display, start_display, add_menu, add_function_to_menu = OCC.Display.SimpleGui.init_display("qt-pyqt5")

    if not args.input:
        parser.print_help()
        sys.exit()

    if not args.output:
        args.output = args.input.rsplit(".", 1)[0]

        if not os.path.exists(args.output):
            os.makedirs(args.output)

    main(args.input, args.output, display=args.display)

    if args.display:
        start_display()
