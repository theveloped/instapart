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
import glob
import json
import OCC
# import ConfigParser
from contextlib import contextmanager
import xml.etree.ElementTree as ET

def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)


# if sys.platform == 'win32':
#     casroot_path = resource_path('casroot')

#     if os.path.exists(casroot_path):
#         os.environ['CASROOT'] = casroot_path

import OCC
import math
# import numpy
import networkx as nx
from enum import Enum


from bounding_box import get_boundingbox_dimensions
from schemas import JobSchema, TreeSchema, ShapeSchema, SectionSchema, TemplateSchema
from cycad import Pattern, Entity
from utils import import_step, resource_path, is_dir, is_file, is_xml_file, is_step_file, are_files, are_step_files, are_xml_files

from auto    import main as auto_main
from analyse import main as analyse_main
from flatten import main as flatten_main
from explode import main as explode_main

from marshmallow import ValidationError

import logging
import logging.handlers
logger = logging.getLogger()

def configure_logger(level=logging.DEBUG):
    # CRITICAL 50
    # ERROR 40
    # WARNING 30
    # INFO 20
    # DEBUG 10
    # NOTSET 0

    if len(logger.handlers):
        logger.handlers = []

    if os.name == 'nt':
        # File logging location
        logging_dir = os.path.join(os.environ["APPDATA"], "SmartPart")
        logging_path = os.path.join(logging_dir, "instapart.log")
        if not os.path.exists(logging_dir):
            os.mkdir(logging_dir)

        # File logger
        handler = logging.handlers.RotatingFileHandler(logging_path, maxBytes=5*1024*1024)
        formatter = logging.Formatter("%(asctime)s %(levelname)-8s %(message)s")
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    # Stream logger
    handler = logging.StreamHandler()
    formatter = logging.Formatter("%(asctime)s %(levelname)-8s %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(level)


@contextmanager
def get_display(render):
    """Returns a display object for rendering

    Arguments:
    render: Bool (wether or not a try or dummy display shoul dbe returned)
    """

    if render:
        import OCC.Display.SimpleGui
        display, start_display, add_menu, add_function_to_menu = OCC.Display.SimpleGui.init_display("qt-pyqt5")
        display.EraseAll()

        yield display
        start_display()

    else:
        yield None


def parse_config_args(parser):
    """parses and sets up the command line argument system above
    with config file parsing."""

    early_parser = argparse.ArgumentParser(prog='InstaPart', add_help=False)
    early_parser.add_argument("command", nargs='?', help="command", default=None)
    early_parser.add_argument("-c", "--config", help="change default configuration location", default=resource_path("settings.json"))

    args, remainder_argv = early_parser.parse_known_args()

    config_file = is_file(args.config, allowed_extensions=["json"])
    with open(config_file, 'r') as json_file:
        config = json.load(json_file)

    parse_full = False
    defaults = config["default"]

    if args.command:
        parse_full = True
        defaults["command"] = args.command

    elif "command" in defaults:
        args.command = defaults["command"]

    else:
        parser.print_help()
        sys.exit(1)

    if args.command in config:
        section_defaults = config[args.command]
        defaults.update(section_defaults)

    for action in parser._actions:
        if action.dest == "command":

            action.default = defaults["command"]

            for command in action.choices:
                if command == defaults["command"]:

                    subparser = action.choices[command]

                    for sub_action in subparser._actions:
                        if sub_action.dest in defaults:
                            sub_action.default = defaults[sub_action.dest]

                            if sub_action.dest == "input":
                                sub_action.nargs = "*"

                            if sub_action.dest == "directory":
                                sub_action.nargs = "?"
                    break
            break

    if parse_full:
        args = parser.parse_args()
    else:
        args = subparser.parse_args()

    args.command = defaults["command"]
    return args


def parse_template():
    early_parser = argparse.ArgumentParser(prog='InstaPart', add_help=False)
    early_parser.add_argument("command", nargs='?', help="command", default=None)
    early_parser.add_argument("--template", help="change default template location", default=resource_path("template.json"))
    args, remainder_argv = early_parser.parse_known_args()

    template = None
    template_file = is_file(args.template, allowed_extensions=["json"], raise_exceptions=False)
    if template_file:
        with open(template_file, 'r', encoding='utf-8') as json_file:
            try:
                template = TemplateSchema().loads(json_file.read())
            except ValidationError as error:
                logger.warning("Failed to parse template: {}".format(error.messages))
                template = None

    return template


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(prog='InstaPart')
    subparsers = parser.add_subparsers(help='desired command to initiate', dest='command')

    # create the parser for the "auto" command
    parser_auto = subparsers.add_parser('auto', help='automatically analyse, explode and flatten input file')
    parser_auto.add_argument('input', type=are_step_files, nargs='+', help="input file [.stp, .step]")
    parser_auto.add_argument("-o", "--output", help="output directory", type=is_dir)
    parser_auto.add_argument("-n", "--nested", help="nested output directory", action='store_true')
    parser_auto.add_argument("-f", "--features", help="check parts for features (e.g. chamfers, embossings)", action='store_true')
    parser_auto.add_argument("-k", "--k_factor", help="k-factor to use duiring unfolding", type=float, default=0.5)
    parser_auto.add_argument("-m", "--material", help="material that will be used in export", type=str, default=None)
    parser_auto.add_argument("-t", "--text", help="text to add to the flat pattern", type=str, default=None)
    parser_auto.add_argument("-r", "--repair", help="allow repair if no valid solid is detected", action='store_true')
    parser_auto.add_argument('-v', '--verbose', help="verbose logging", action="store_const", dest="loglevel", const=logging.INFO, default=logging.WARNING)
    parser_auto.add_argument('-e', "--export", type=str, nargs='+', choices=["SVG", "PNG", "STP", "PDF", "XLS"], default=[], help="export types used for all shapes")

    parser_auto.add_argument("--filename_source", type=str, choices=["FILE", "PART"], default="PART", help="export types used for all shapes")
    parser_auto.add_argument("--filename_charset", type=str, default=None, help="export types used for all shapes")
    parser_auto.add_argument("--filename_min", type=int, default=None, help="limit the amount of bodies per part")
    parser_auto.add_argument("--filename_max", type=int, default=None, help="limit the amount of bodies per part")
    parser_auto.add_argument("--filename_trim", type=str, choices=["START", "END"], default="END", help="export types used for all shapes")
    parser_auto.add_argument("--filename_prefix", type=str, default=None, help="prefix to add to filename")
    parser_auto.add_argument("--filename_postfix", type=str, default=None, help="postfix to add to filename")

    parser_auto.add_argument("--nested_structure", type=str, choices=["FILE", "TYPE", "FILE/TYPE"], default="FILE", help="structure of the output directory")

    parser_auto.add_argument("--absolute_volume_threshold", help="Error threshold between the folded and unfolded shape volume in mm^3", type=float, default=5.0)
    parser_auto.add_argument("--relative_volume_threshold", help="Error threshold between the relative folded and unfolded shape", type=float, default=0.025)
    parser_auto.add_argument("-a", "--attributes", help="extract face colors, names and semantic PMI/GD&T from the STEP file", action='store_true')
    parser_auto.add_argument("-d", "--display", help="display user interface", action='store_true')
    # parser_auto.add_argument('-c', '--config', default="config.xml", help='file to read the default config from')

    # create the parser for the "convert" command
    # parser_convert = subparsers.add_parser('convert', help='currently not yet implemented')

    # create the parser for the "analyse" command
    # parser_analyse = subparsers.add_parser('analyse', help='analyse the content of a STEP file')
    # parser_analyse.add_argument('input', type=str, nargs='+', help="input file [.stp, .step]")
    # parser_analyse.add_argument("-o", "--output", help="output directory", type=is_dir)
    # parser_analyse.add_argument("-p", "--part", help="part index to analyse in case of an assembly", type=int, default=0)
    # parser_analyse.add_argument("-r", "--repair", help="allow repair if no valid solid is detected", action='store_true')
    # parser_analyse.add_argument("-d", "--display", help="display user interface", action='store_true')
    # parser_analyse.add_argument('-v', '--verbose', help="verbose logging", action="store_const", dest="loglevel", const=logging.INFO, default=logging.WARNING)

    # create the parser for the "explode" command
    parser_explode = subparsers.add_parser('explode', help='explode STEP assemblies into seperate files')
    parser_explode.add_argument('input', type=are_step_files, nargs='+', help="input file [.stp, .step]")
    parser_explode.add_argument("-o", "--output", help="output directory", type=is_dir)
    parser_explode.add_argument("-n", "--nested", help="nested output directory", action='store_true')
    parser_explode.add_argument("-b", "--bodies", help="explode parts with multiple bodies", action='store_true')
    parser_explode.add_argument("-l", "--limit", type=int, help="limit the amount of bodies per part", default=None)
    parser_explode.add_argument('-v', '--verbose', help="verbose logging", action="store_const", dest="loglevel", const=logging.INFO, default=logging.WARNING)

    parser_explode.add_argument("--filename_source", type=str, choices=["FILE", "PART"], default="PART", help="export types used for all shapes")
    parser_explode.add_argument("--filename_charset", type=str, default=None, help="export types used for all shapes")
    parser_explode.add_argument("--filename_min", type=int, default=None, help="limit the amount of bodies per part")
    parser_explode.add_argument("--filename_max", type=int, default=None, help="limit the amount of bodies per part")
    parser_explode.add_argument("--filename_trim", type=str, choices=["START", "END"], default="END", help="export types used for all shapes")
    parser_explode.add_argument("--filename_prefix", type=str, default=None, help="prefix to add to filename")
    parser_explode.add_argument("--filename_postfix", type=str, default=None, help="postfix to add to filename")
    # parser_explode.add_argument("-d", "--display", help="display user interface", action='store_true')

    # create the parser for the "flatten" command
    parser_flatten = subparsers.add_parser('flatten', help='flatten STEP files of sheet parts into a 2D representation')
    parser_flatten.add_argument('input', type=are_step_files, nargs='+', help="input file [.stp, .step]")
    parser_flatten.add_argument("-o", "--output", help="output directory", type=is_dir)
    parser_flatten.add_argument("-n", "--nested", help="nested output directory", action='store_true')
    parser_flatten.add_argument("-f", "--features", help="check parts for features (e.g. chamfers, embossings)", action='store_true')
    parser_flatten.add_argument("-k", "--k_factor", help="k-factor to use duiring unfolding", type=float, default=0.5)
    parser_flatten.add_argument("-m", "--material", help="material that will be used in exported", type=str, default=None)
    parser_flatten.add_argument("-r", "--repair", help="allow repair if no valid solid is detected", action='store_true')
    parser_flatten.add_argument('-v', '--verbose', help="verbose logging", action="store_const", dest="loglevel", const=logging.INFO, default=logging.WARNING)

    parser_flatten.add_argument("--absolute_volume_threshold", help="Error threshold between the folded and unfolded shape volume in mm^3", type=float, default=5.0)
    parser_flatten.add_argument("--relative_volume_threshold", help="Error threshold between the relative folded and unfolded shape", type=float, default=0.025)
    # parser_flatten.add_argument("-d", "--display", help="display user interface", action='store_true')

    args = parse_config_args(parser)
    configure_logger(level=args.loglevel)

    if not "display" in args:
        args.display = None

    # file_paths = []
    # if hasattr(args, "input"):
    #     for path in args.input:
    #         logger.info("Adding file to queue: {}".format(path))

    #         for file_path in glob.glob(path):
    #             if is_step_file(file_path):
    #                 file_paths.append(file_path)

    # args.input = file_paths

    file_paths = []
    if hasattr(args, "input"):
            for inputs in args.input:
                file_paths += inputs

    args.input = file_paths


    # handle auto of step files
    if args.command == "auto":
        logger.info("Starting: AUTO")

        export_names = {}
        for file_path in args.input:

            with get_display(args.display) as display:
                output_dir = args.output or os.path.dirname(file_path)

                # Nested file path per part
                if args.nested:

                    # File name and extension
                    file_name = os.path.basename(file_path)
                    file_name, extension = file_name.rsplit(".", 1)
                    file_name = file_name.strip()

                    # Nested output directory
                    output_dir = os.path.join(output_dir, file_name)
                    if not os.path.exists(output_dir):
                        os.mkdir(output_dir)
#
                logger.debug("Export: {}".format(args.export))
                export_svg = ("SVG" in args.export)
                export_png = ("PNG" in args.export)
                export_stp = ("STP" in args.export)
                export_pdf = ("PDF" in args.export)
                export_xls = ("XLS" in args.export)

                template = parse_template()
                logger.debug("Template: {}".format(template))

                logger.info("Auto processing {}".format(file_path))
                export_names = auto_main(file_path, output_dir, 
                            display=display, 
                            align=True, 
                            k_factor=args.k_factor, 
                            repair=args.repair, 
                            material=args.material, 
                            check_features=args.features, 
                            label_text=args.text, 
                            export_stp=export_stp, 
                            export_svg=export_svg, 
                            export_png=export_png, 
                            export_pdf=export_pdf,
                            export_xls=export_xls,
                            filename_source=args.filename_source,
                            filename_charset=args.filename_charset,
                            filename_min=args.filename_min,
                            filename_max=args.filename_max,
                            filename_trim=args.filename_trim,
                            filename_prefix=args.filename_prefix,
                            filename_postfix=args.filename_postfix,
                            export_names=export_names,
                            export_template=template,

                            absolute_volume_threshold=args.absolute_volume_threshold,
                            relative_volume_threshold=args.relative_volume_threshold,
                            extract_attributes=args.attributes
                        )

    # handle analysing of step files
    elif args.command == "analyse":
        logger.info("Starting: ANALYSING")

        for file_path in args.input:

            with get_display(args.display) as display:
                # output_dir = args.output or os.path.dirname(file_path)

                logger.info("Analysing {}".format(file_path))
                analyse_main(file_path, part_index=args.part, display=display)

    # handle exploding of step files
    elif args.command == "explode":
        logger.info("Starting: EXPLODE")

        export_names = {}
        for file_path in args.input:

            with get_display(args.display) as display:
                output_dir = args.output or os.path.dirname(file_path)

                # Nested file path per part
                if args.nested:

                    # File name and extension
                    file_name = os.path.basename(file_path)
                    file_name, extension = file_name.rsplit(".", 1)

                    # Nested output directory
                    output_dir = os.path.join(output_dir, file_name)
                    if not os.path.exists(output_dir):
                        os.mkdir(output_dir)


                logger.info("Exploding {} to {}".format(file_path, output_dir))
                export_names = explode_main(file_path, output_dir, extension="stp", explode_bodies=args.bodies, limit_bodies=args.limit, display=display,
                        filename_source=args.filename_source,
                        filename_charset=args.filename_charset,
                        filename_min=args.filename_min,
                        filename_max=args.filename_max,
                        filename_trim=args.filename_trim,
                        filename_prefix=args.filename_prefix,
                        filename_postfix=args.filename_postfix,
                        export_names=export_names
                    )

    # handle flattening of step files
    elif args.command == "flatten":
        logger.info("Starting: FLATTEN")

        for file_path in args.input:

            with get_display(args.display) as display:
                output_dir = args.output or os.path.dirname(file_path)

                # Nested file path per part
                if args.nested:

                    # File name and extension
                    file_name = os.path.basename(file_path)
                    file_name, extension = file_name.rsplit(".", 1)

                    # Nested output directory
                    output_dir = os.path.join(output_dir, file_name)
                    if not os.path.exists(output_dir):
                        os.mkdir(output_dir)

                logger.info("Flatten {} to {}".format(file_path, output_dir))
                flatten_main(file_path, output_dir, display=display, align=True, k_factor=args.k_factor, repair=args.repair, material=args.material, check_features=args.features,
                    absolute_volume_threshold=args.absolute_volume_threshold,
                    relative_volume_threshold=args.relative_volume_threshold)