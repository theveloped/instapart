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
import traceback
import datetime
from enum import Enum

# import math
# import networkx as nx
# from sklearn.cluster import KMeans

# utils
from utils import import_step, mean, get_shape_solids, get_volume, get_area, update_shape_parts, iterate_shape_parts, part_compound_shape, redirect_stdout, suppress_stdout_stderr
from flatten import FaceTypes, face_normal, mid_point, face_surface_handle, FaceProperties, get_solid_from_shape, get_largest_solid, referse_feature
from marshmallow import pprint

# pythonOCC imports
from OCC.gp import gp_Vec
from OCC.BRepAdaptor import BRepAdaptor_Surface, BRepAdaptor_HSurface

from OCC.TopoDS import TopoDS_Compound
from OCC.BRep import BRep_Builder

from OCC.Bnd import Bnd_Box
from OCC.BRepBndLib import brepbndlib_Add
from OCC.BRepBuilderAPI import BRepBuilderAPI_MakeFace

from OCC.gp import gp_Trsf, gp_Vec
from OCC.BRepBuilderAPI import BRepBuilderAPI_Transform

# Assembly tools
from explode import TreeBuilder, count_parts, write_step_file
from analyse import analyse_shape
from flatten import fix_shape, AdjacencyGraph
from cycad import Pattern, Entity
from models import Job, Shape
from schemas import JobSchema, TreeSchema, ShapeSchema, SectionSchema
from bounding_box import get_boundingbox_dimensions
from activate import check_license

import xml.etree.ElementTree as ET
from images import exportSVG, exportPNG
from documents import exportPDF, exportXLS

from naming import generate_name

import logging
logger = logging.getLogger()


# def exportShapeFiles(
#             export_stp=False,
#             export_svg=False,
#             export_png=False,
#             export_pdf=False,
#             export_xls=False,
#             display=None,
#             filename_source="PART",
#             filename_charset=None,
#             filename_min=None,
#             filename_max=None,
#             filename_trim="END",
#             filename_prefix=None,
#             filename_postfix=None,
#             export_names={},
#         ):

#     export_name = generate_name(input_file, part, export_names[output_dir],
#             source=filename_source,
#             charset=filename_charset,
#             min_length=filename_min,
#             max_length=filename_max,
#             trim_side=filename_trim,
#             prefix=filename_prefix,
#             postfix=filename_postfix
#         )

#     export_names[output_dir].append(export_name)

#     if export_svg:
#         output_file = "{}.svg".format(export_name)
#         output_path = os.path.join(output_dir, output_file)
#         solid_files.append({"path": output_path})
#         exportSVG(solid, output_path)

#     if export_png:
#         output_file = "{}.png".format(export_name)
#         output_path = os.path.join(output_dir, output_file)
#         solid_files.append({"path": output_path})
#         exportPNG(solid, output_path)

#     if export_stp:
#         output_file = "{}.stp".format(export_name)
#         output_path = os.path.join(output_dir, output_file)
#         solid_files.append({"path": output_path})
#         with suppress_stdout_stderr():
#             write_step_file(solid, output_path)

#     return export_names




# def main(step_path, part_index=None, display=None, repair=True):
# def main(step_path, align=False, output=False, k_factor=0.5, repair=True, display=None, material=None, check_features=False):
def main(file_path, output_dir,
        repair=True,
        max_solids=None,
        align=True,
        k_factor=0.5,
        material=None,
        date=None,
        check_features=False,
        bysoft_autopart=False,
        label_text=None,
        label_height=20.0,
        combine_bends=True,
        export_stp=False,
        export_svg=False,
        export_png=False,
        export_pdf=False,
        export_xls=False,
        display=None,
        filename_source="PART",
        filename_charset=None,
        filename_min=None,
        filename_max=None,
        filename_trim="END",
        filename_prefix=None,
        filename_postfix=None,
        export_names={},
        export_template=None,

        absolute_volume_threshold=5.0,
        relative_volume_threshold=0.025,
    ):

    check_license(meter_attribute="auto")
    job_data = Job(file_path, output_dir)
    input_file = os.path.basename(file_path)
    input_file = input_file.rsplit(".", 1)[0]

    if output_dir not in export_names:
        export_names[output_dir] = [input_file]

    try:
        with suppress_stdout_stderr():
            builder = TreeBuilder(file_path)
            job_data.tree = builder.compute(ignore_duplicates=False, root=input_file, display=display)

    except Exception:
        logger.error("Could not read file and/or assembly structure")
        traceback.print_exc()

        message = {
            "code": "000",
            "description": "Could not read file and/or assembly structure",
            "value": None
        }

        job_data.messages.append(message)

        output_file = "{}.json".format(input_file)
        with open(os.path.join(output_dir, output_file), 'w') as json_file:
            job_json = JobSchema().dumps(job_data).data
            job_parsed = json.loads(job_json)
            json.dump(job_parsed, json_file, indent=2, sort_keys=True)

        return export_names

    part_updates = {}
    for part in iterate_shape_parts(job_data.tree):

        if part.index != part.reference:
            continue

        logger.info("Processing {0}x, {1}".format(part.count, part.name))

        part_solids = []
        part_messages = []

        solid = None
        solid_index = 0

        shape = part_compound_shape(part)
        logger.info("COMPOUND FOUND {0}x, {1}".format(part.count, part.name))

        for solid in get_shape_solids(shape, sort=True, repair=repair):
            solid_index += 1
            solid_files= []
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

            if export_svg:
                output_file = "{}.svg".format(export_name)
                output_path = os.path.join(output_dir, output_file)
                solid_files.append({"path": output_path})
                exportSVG(solid, output_path)

            if export_png:
                output_file = "{}.png".format(export_name)
                output_path = os.path.join(output_dir, output_file)
                solid_files.append({"path": output_path})
                exportPNG(solid, output_path)

            if export_stp:
                output_file = "{}.stp".format(export_name)
                output_path = os.path.join(output_dir, output_file)
                solid_files.append({"path": output_path})
                with suppress_stdout_stderr():
                    write_step_file(solid, output_path)

            if display:
                display.EraseAll()
                display.DisplayShape(solid, update=True, color="white", transparency=0.8)

            try:
                aag = AdjacencyGraph(solid)
                aag.full()
                aag.smooth()
                aag.grouped()

            except Exception:
                traceback.print_exc()
                logger.warning("Could not compute shape topology")

                shape_data = Shape()
                message = {
                    "code": "001",
                    "description": "Could not compute shape topology",
                    "value": None
                }
                shape_data.messages.append(message)
                shape_data.files = solid_files
                part_solids.append(shape_data)
                # raw_input("continue?")
                continue

            try:
                # Tube parts
                shape_data = Shape()
                section_data = analyse_shape(aag, display=None)

                # section_json = SectionSchema().dump(section_data).data
                # pprint(section_json)

                # Bend parts
                shape_data.volume = get_volume(solid)
                shape_data.area = sum([areas[0] for areas in aag.areas])
                shape_data.width, shape_data.height, shape_data.length = get_boundingbox_dimensions(solid, use_mesh=False)

                min_thickness = 2 * shape_data.volume / shape_data.area
                first_hash, second_hash, thickness = aag.get_sheet_base(min_thickness=min_thickness, display=display)
                if not thickness:
                    logger.warning("Could not detect shape thickness and/or base flange")

                    message = {
                        "code": "002",
                        "description": "Could not detect shape thickness and/or base flange",
                        "value": None
                    }
                    shape_data.messages.append(message)
                    shape_data.files = solid_files
                    part_solids.append(shape_data)
                    # raw_input("continue?")
                    continue

                graph_a = aag.get_connected_subgraph(first_hash, ignore_complex=True, display=display)

                # Get features
                unfold_a = True
                features = []
                featured_edges = []
                if check_features:
                    graph_b = aag.get_connected_subgraph(second_hash, ignore_complex=True, display=display)
                    features, featured_edges = aag.get_connecting_features(graph_a, graph_b, thickness, display=display)
                    shape_data.features = features

                    features_a = 0
                    features_b = 0
                    for feature in features:
                        if feature.top:
                            features_a += 1

                        if feature.bottom:
                            features_b += 1

                        # logger.info("FEATURE: {}".format(feature))

                    if features_a > 0 and features_b > 0:
                        logger.warning("Features detected on both sides of part. Only one side visible in 2D.")

                        message = {
                            "code": "008",
                            "description": "Features detected on both sides of part. Only one side visible in 2D.",
                            "value": None
                        }
                        shape_data.messages.append(message)

                    if features_b > features_a:
                        logger.info("Unfolding second side of shape")
                        unfold_a = False

                # compute transformations to unfold graph
                if unfold_a:
                    surface_handle, transformations, base_reversed = aag.unfold_graph(graph_a, thickness, base_hash=first_hash, align=align, display=None, k_factor=k_factor)
                    features = aag.project_features(features, surface_handle, unfold_a=unfold_a, transformations=transformations, display=display)
                    wires, open_wire_count, loops = aag.extract_wires(graph_a, surface_handle, thickness, transformations=transformations, k_factor=k_factor, features=features, featured_edges=featured_edges, display=display)
                    bends = aag.extract_bends(graph_a, surface_handle, thickness, transformations=transformations, reversed=base_reversed, display=display, k_factor=k_factor, combine_bends=combine_bends)
                    shape_data.bends = bends

                else:
                    for feature in features:
                        feature.reverse()

                    surface_handle, transformations, base_reversed = aag.unfold_graph(graph_b, thickness, base_hash=second_hash, align=align, display=None, k_factor=k_factor)
                    features = aag.project_features(features, surface_handle, unfold_a=unfold_a, transformations=transformations, display=display)
                    wires, open_wire_count, loops = aag.extract_wires(graph_b, surface_handle, thickness, transformations=transformations, k_factor=k_factor, features=features, featured_edges=featured_edges, display=display)
                    bends = aag.extract_bends(graph_b, surface_handle, thickness, transformations=transformations, reversed=base_reversed, display=display, k_factor=k_factor, combine_bends=combine_bends)
                    shape_data.bends = bends


                # features, featured_edges = aag.get_connecting_features(graph_a, graph_b, thickness, surface_handle=surface_handle, transformations=transformations, display=display)

                # for loop in loops:
                #     print(loop)

                #     translation = None
                #     wire_count = len(loop.wires)
                #     for i in range(wire_count):
                #         wire = loop.wires[i]

                #         if i >= 1:
                #             if translation:
                #                 translation = translation + loop.gaps[i]
                #             else:
                #                 translation = loop.gaps[i]

                #             # translation = loop.gaps[i]
                #             transformation = gp_Trsf()
                #             transformation.SetTranslation(loop.gaps[i - 1].Reversed())
                #             wire = BRepBuilderAPI_Transform(wire, transformation).Shape()

                #         if display:
                #             if loop.is_closed:
                #                 display.DisplayShape(wire, update=True, color="orange")
                #             else:
                #                 display.DisplayShape(wire, update=True, color="blue")

                #         if i >= 2:
                #             display.DisplayShape(wire, update=True, color="black")

                # raw_input("continue?")
                # continue

                # logger.warning("OPEN WIRE COUNT: {}".format(open_wire_count))

                # part is a bent or flat part
                if open_wire_count == 0:

                    # Analyse result
                    max_size = 0
                    max_index = 0
                    bbox = Bnd_Box()
                    for i in range(len(loops)):
                        brepbndlib_Add(loops[i].wires[0], bbox)
                        bb_xmin, bb_ymin, _, bb_xmax, bb_ymax, _ = bbox.Get()
                        wire_size = (bb_xmax - bb_xmin) * (bb_ymax - bb_ymin)

                        if wire_size > max_size:
                            max_size = wire_size
                            max_index = i

                    # Generate single unfolded face based on wires
                    # max_loop = loops.pop(max_index)
                    make_face = BRepBuilderAPI_MakeFace(loops[max_index].wires[0])
                    for i in range(len(loops)):
                        if i == max_index:
                            if display:
                                display.DisplayShape(loops[i].wires[0], update=True, color="red", transparency=0.5)

                        elif loops[i].feature:
                            if display:
                                display.DisplayShape(loops[i].wires[0], update=True, color="green", transparency=0.5)

                                if loops[i].feature.projections:
                                    display.DisplayShape(loops[i].feature.projections[0], update=True, color="orange", transparency=0.5)

                        elif i != max_index:
                            make_face.Add(loops[i].wires[0])

                            if display:
                                display.DisplayShape(loops[i].wires[0], update=True, color="blue", transparency=0.5)

                    face = make_face.Face()
                    face = fix_shape(face)
                    face_area = get_area(face)
                    face_volume = face_area * thickness
                    volume_error = shape_data.volume - face_volume

                    if display:
                        display.DisplayShape(face, update=True, color="red", transparency=0.5)

                    # logger.info("Thickness: {:0.2f}, Area: {:0.2f})".format(thickness, face_area))

                    logger.info("Volume difference: {:0.2f} ({:0.2f}%)".format(volume_error, volume_error / shape_data.volume * 100))

                    relative_threshold_triggered = False
                    if relative_volume_threshold:
                        relative_threshold_triggered = (abs((volume_error) / shape_data.volume) > relative_volume_threshold)

                    if not relative_threshold_triggered:
                        if output_dir:
                            output_file = "{}.dxf".format(export_name)
                            output_path = os.path.join(output_dir, output_file)

                        if len(bends) == 0:
                            logger.info("Shape is flat")

                        else:
                            logger.info("Shape is bent")

                        if absolute_volume_threshold:
                            if abs(volume_error) > absolute_volume_threshold:
                                logger.warning("Volume difference after flattening {:0.2f}mm^3 should be checked".format(volume_error))

                                message = {
                                    "code": "003",
                                    "description": "Volume difference after flattening {:0.2f}mm^3".format(volume_error),
                                    "value": volume_error
                                }
                                shape_data.messages.append(message)

                        description = "{}x, {:0.2f}mm, {}, {}, {}".format(part.count, thickness, file_path, part.name, solid_index)
                        pattern = Pattern(thickness=thickness, wires=wires, bends=bends, loops=loops, material=material, quantity=part.count, date=date)
                        pattern.origin = [bb_xmin, bb_ymin]
                        pattern.width = bb_xmax - bb_xmin
                        pattern.height = bb_ymax - bb_ymin
                        pattern.parse_wires()

                        if label_text:
                            pattern.place_label(text=label_text, font_height=label_height, gravity_angle=4.7)

                        if bysoft_autopart:
                            pattern.save(output_path, description=description, messages=shape_data.messages, add_text=False, dxf_type="DESIGNER")

                        elif export_template:
                            pattern.save(output_path, description=description, messages=shape_data.messages, add_text=False, dxf_type="TEMPLATE", template=export_template)

                        else:
                            pattern.save(output_path, description=description, messages=shape_data.messages, add_text=False, dxf_type="CYCAD")

                        solid_files.append({"path": output_path})


                        if export_pdf:
                            output_file = "{}.pdf".format(export_name)
                            output_path = os.path.join(output_dir, output_file)
                            solid_files.append({"path": output_path})
                            exportPDF(pattern, shape, shape_data, output_path, file_name=input_file, part_name=part.name)

                        shape_data.type = Shape.ShapeTypes.SHEET
                        shape_data.pattern = pattern
                        shape_data.files = solid_files
                        part_solids.append(shape_data)


                        # Export BYSOFT XML
                        if bysoft_autopart:
                            xml_data = ET.Element('BatchUnfoldInfo')
                            xml_input_file = ET.SubElement(xml_data, 'InputFile')
                            xml_status = ET.SubElement(xml_data, 'Status')
                            xml_count = ET.SubElement(xml_data, 'Count')
                            xml_material = ET.SubElement(xml_data, 'Material')
                            xml_measurement_system = ET.SubElement(xml_data, 'MeasurementSystem')
                            xml_thickness = ET.SubElement(xml_data, 'Thickness')
                            xml_messages = ET.SubElement(xml_data, 'Messages')

                            # if len(shape_data.messages) > 0:
                            #     xml_status.text = "Warnings"
                            # else:
                            #     xml_status.text = "Succeeded"

                            xml_input_file.text = file_path
                            xml_status.text = "Succeeded"
                            xml_count.text = str(part.count) or 1
                            xml_material.text = material or ""
                            xml_measurement_system.text = "Metric"
                            xml_thickness.text = "{:0.2f}".format(thickness)

                            for message in shape_data.messages:
                                xml_message = ET.SubElement(xml_messages, 'string')
                                xml_message.text = message["description"]

                            output_file = "{}.info".format(export_name)
                            output_path = os.path.join(output_dir, output_file)
                            solid_files.append({"path": output_path})

                            with open(output_path, 'w') as xml_file:
                                xml_file.write(ET.tostring(xml_data))

                        continue

                    # Fallback on TUBES
                    elif section_data:
                        logger.info("Shape is tubular")

                        if not export_stp:
                            output_file = "{}.stp".format(export_name)
                            output_path = os.path.join(output_dir, output_file)
                            solid_files.append({"path": output_path})

                        shape_data.type = Shape.ShapeTypes.TUBE
                        shape_data.section = section_data
                        shape_data.files = solid_files
                        part_solids.append(shape_data)

                        if not export_stp:
                            with suppress_stdout_stderr():
                                write_step_file(solid, output_path)

                        continue

                    else:
                        logger.error("Could not flatten shape")

                        message = {
                            "code": "004",
                            "description": "Could not flatten shape",
                            "value": None
                        }
                        shape_data.messages.append(message)
                        part_solids.append(shape_data)
                        continue

                # Part is a tube part
                elif section_data:
                    logger.info("Shape is tubular")

                    # Tube pattern: TODO test if split wires are correctly measured
                    pattern = Pattern(thickness=thickness, wires=wires, bends=[], loops=loops)
                    pattern.parse_loops()
                    shape_data.pattern = pattern

                    logger.info("Shape pattern computed")

                    if not export_stp:
                        output_file = "{}.stp".format(export_name)
                        output_path = os.path.join(output_dir, output_file)
                        solid_files.append({"path": output_path})

                    shape_data.type = Shape.ShapeTypes.TUBE
                    shape_data.section = section_data
                    shape_data.files = solid_files
                    part_solids.append(shape_data)

                    if not export_stp:
                        with suppress_stdout_stderr():
                            write_step_file(solid, output_path)

                    continue


                # Part is a tube part
                else:
                    logger.error("Shape type is not recognized")

                    message = {
                        "code": "005",
                        "description": "Shape type is not recognized",
                        "value": None
                    }
                    shape_data.messages.append(message)
                    shape_data.files = solid_files
                    part_solids.append(shape_data)
                    continue



            except Exception:
                traceback.print_exc()
                logger.error("Shape could not be processed")

                message = {
                    "code": "006",
                    "description": "Shape could not be processed",
                    "value": None
                }
                shape_data.messages.append(message)
                shape_data.files = solid_files
                part_solids.append(shape_data)
                continue

        if not solid:
            logger.error("No valid solids could be extracted from part")

            message = {
                "code": "007",
                "description": "No valid solids could be extracted from part",
                "value": None
            }
            part_messages.append(message)

        # Update tree
        part_updates[part.index] = {
            "solids": part_solids,
            "messages": part_messages
        }

    update_shape_parts(job_data.tree, part_updates)

    sys.setrecursionlimit(250000)
    if export_xls:
        output_file = "{}.xls".format(input_file)
        output_path = os.path.join(output_dir, output_file)
        exportXLS(job_data.tree, output_path)

    output_file = "{}.json".format(input_file)
    output_path = os.path.join(output_dir, output_file)
    with open(output_path, 'w') as json_file:
        job_json = JobSchema().dumps(job_data).data
        job_parsed = json.loads(job_json)
        json.dump(job_parsed, json_file, indent=2, sort_keys=True)

    return export_names

