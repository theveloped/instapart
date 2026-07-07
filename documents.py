# -*- coding: utf-8 -*-

# import datetime
# import logging
import math
# import copy
import os

# from google.appengine.ext import ndb
# from google.appengine.api import app_identity
# from flask import request, abort, render_template


from svglib.svglib import SvgRenderer
# from lxml import etree
# import StringIO
# from io import BytesIO
# import ezdxf

from reportlab.platypus import SimpleDocTemplate
from reportlab.lib.enums import TA_JUSTIFY, TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import letter, A4, landscape
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, Spacer, Image, Table, TableStyle, Image, Frame, PageTemplate, Flowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm, cm
from reportlab.lib import colors, utils
from reportlab.graphics.shapes import Line
from reportlab.graphics import renderPDF
from reportlab.lib.colors import white, transparent, Color


# from pdfrw import PdfReader, PageMerge, PdfDict, PdfObject
# from pdfrw.buildxobj import pagexobj
# from pdfrw.toreportlab import makerl

# from .geometry import almostEqual, almostZero, Point, Path

# from dotmap import DotMap
# from functools import partial
# from app.modules.orders.models import Order
# from app.modules.parts.models import Part
# from app.modules.materials.models import Material


from jinja2 import Template, Environment, PackageLoader, select_autoescape
def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)

# env = Environment(
#     loader=PackageLoader('instapart', 'templates'),
#     autoescape=select_autoescape(['html', 'xml'])
# )



import sys
if sys.version_info.major == 2:
    import cStringIO as StringIO
else:
    import io as StringIO

from lxml import etree
from images import getSVG

# from weasyprint import HTML, CSS

import logging
logger = logging.getLogger()

import json
from xlwt import Workbook, XFStyle
from schemas import JobSchema, TreeSchema, ShapeSchema, SectionSchema, PatternSchema

def treeIterator(tree, ignore_duplicates=True):
    if tree.index == tree.reference or tree.reference == None or ignore_duplicates == False:

        for part in tree.solids:
            yield tree, part

        for component in tree.components:
            for component, part in treeIterator(component):
                yield component, part


def parseResource(resource, schema, columns):
    if resource and len(columns) > 0:
        resource_json = schema(only=columns).dumps(resource).data
        resource_parsed = json.loads(resource_json)

        result = []
        for column in columns:
            if column in resource_parsed:
                result.append(resource_parsed[column])

            else:
                return result.append(None)

        return result

    else:
        return [None] * len(columns)

def exportXLS(
        data, output_path, 
        component_columns=["name", "count"], 
        shape_columns=["type", "height", "length", "width", "area", "volume"],
        pattern_columns=["thickness", "width", "height", "bend_quantity", "bend_groups"],
        section_columns=["type", "length", "thickness", "width", "height", "inner_radius", "outer_radius"]
    ):

    str_format = XFStyle()
    str_format.num_format_str = '@'

    num_format = XFStyle()
    num_format.num_format_str = '0.0'


    wb = Workbook()
    ws = wb.add_sheet('tree')

    headers = []
    headers += component_columns
    headers += shape_columns

    for header in pattern_columns:
        header = "pattern {}".format(header) 
        headers.append(header)

    for header in section_columns:
        header = "section {}".format(header) 
        headers.append(header)

    column = 0
    for header in headers:
        ws.write(0, column, header)
        column += 1

    row = 1
    for component, shape in treeIterator(data):

        columns = []
        columns += parseResource(component, TreeSchema, component_columns)
        columns += parseResource(shape, ShapeSchema, shape_columns)
        columns += parseResource(shape.pattern, PatternSchema, pattern_columns)
        columns += parseResource(shape.section, SectionSchema, section_columns)

        column = 0
        for cell in columns:
            if cell:
                if isinstance(cell, float) or isinstance(cell, int):
                    ws.write(row, column, cell, num_format)

                else:
                    ws.write(row, column, cell, str_format)

            column += 1
        row += 1
    wb.save(output_path)



def exportPDF(pattern, shape, shape_data, output_path, file_name="", part_name=""):
    """
        accept a cadquery shape, and export it to the provided file
        TODO: should use file-like objects, not a fileName, and/or be able to return a string instead
        export a view of a part to svg
    """

    stream = getBendPDF(pattern, shape, shape_data, file_name=file_name, part_name=part_name)
    stream.seek(0)
    f = open(output_path, 'w')
    f.write(stream.read())
    f.close()


# def getImage(pattern, maxWidth=20*mm, maxHeight=20*mm, scale=None, dimensions=[], color="", add_text=False, approximate=False):
#     parser = etree.XMLParser(remove_comments=True, recover=True)

#     # Compute scale
#     if not scale:
#         scale = maxWidth / pattern.width

#         if (maxHeight / pattern.height) < scale:
#             scale = maxHeight / pattern.height

#     if color:
#         svgString = getPatternSvg(pattern, scale=scale, dimensions=dimensions, add_text=add_text, contour_fill=color, hole_fill="white", approximate=approximate)
#     else:
#         svgString = getPatternSvg(pattern, scale=scale, dimensions=dimensions, add_text=add_text, approximate=approximate)

#     svg = etree.fromstring(svgString, parser=parser)

#     # Render svg to RLG
#     svgRenderer = SvgRenderer()
#     drawing = svgRenderer.render(svg)

#     return drawing


def getPatternSvg(pattern, scale=1.0, dimensions=[], add_text=True, contour_fill="", hole_fill=""):
    stroke_width = 1.0 / min(400.0 / pattern.width, 400.0 / pattern.height)

    template = Template(PART_PATTER_TEMPLATE)
    return template.render(
            pattern=pattern,
            stroke_width=stroke_width,
            scale=scale,
            dimensions=dimensions,
            contour_fill=contour_fill,
            hole_fill=hole_fill
        )


        # return render_template(resource_path("./templates/part_pattern.svg"), pattern=pattern, viewBox=viewBox, stroke_width=stroke_width, scale=scale, dimensions=dimensions, contour_fill=contour_fill, hole_fill=hole_fill)




def getBendPDF(pattern, shape, shape_data, pagesize=A4, file_name="", part_name=""):
    # Generate pdf
    outputStream = StringIO.StringIO()
    c = canvas.Canvas(outputStream, pagesize=pagesize)

    # Get Isometric image
    width, height = pagesize

    thumbnail_radius = max(width * .2, height * .2)
    options = {"width": thumbnail_radius, "height": thumbnail_radius}
    svgString = getSVG(shape, opts=options).encode('utf-8')
    svgRenderer = SvgRenderer("")
    parser = etree.XMLParser(remove_comments=True, recover=True)
    svg = etree.fromstring(svgString, parser=parser)
    drawing = svgRenderer.render(svg)
    drawing.drawOn(c, int(width - thumbnail_radius - 5*mm), int(height - thumbnail_radius - 5*mm))

    # Max width
    width *= 0.75
    height *= 0.75

    # Compute patter scale
    widthScale = width / pattern.width / mm
    heightScale = height / pattern.height / mm
    scale = min(widthScale, heightScale)

    if scale > 1:
        # logger.info("[+] scale > 1")

        scale = math.floor(scale)
        scaleString = "%d:1" % (scale)
        scale = scale * mm

    else:
        # logger.info("[+] scale < 1")
        scale = math.ceil(1 / scale)
        scaleString = "1:%d" % (scale)
        scale = 1 / scale
        scale = scale * mm

    # logger.info("[+] scale: " + str(scale))
    # logger.info("[+] string: " + scaleString)

    minimal = 0.0
    if pattern.thickness:
        minimal = pattern.thickness * 4 + 1

    dimensions = pattern.autoDimension(minimal=minimal, spacing=20.0/scale)
    # logger.info("[+] dimensions computed")


    svgString = getPatternSvg(pattern, scale=scale, dimensions=dimensions).encode('utf-8')
    parser = etree.XMLParser(remove_comments=True, recover=True)
    svg = etree.fromstring(svgString, parser=parser)
    drawing = svgRenderer.render(svg)


    # logging.info("[+] image made")
    x = int((pagesize[0] - pattern.width * scale) / 2)
    y = int((pagesize[1] - pattern.height * scale) / 2)
    drawing.drawOn(c, x, y)






    infoData = []
    infoData.append(["File name", file_name])
    infoData.append(["Part name", part_name])
    infoData.append(["Dimensions (3D)", "{:.2f} × {:.2f} × {:.2f}mm".format(shape_data.width, shape_data.height, shape_data.length)])
    infoData.append(["Dimensions (2D)", "{:.2f} × {:.2f} × {:.2f}mm".format(pattern.width, pattern.height, pattern.thickness)])
    # infoData.append([])
    # infoData[-1].append("{:.2f}x{:.2f}x{:.2f}mm".format(shape_data.width, shape_data.height, shape_data.length))
    # infoData[-1].append("{:.2f}x{:.2f}x{:.2f}mm".format(shape_data.width, shape_data.height, shape_data.length))
    # infoData[-1].append("{:.2f}x{:.2f}x{:.2f}mm".format(pattern.width, pattern.height, pattern.thickness))
    # infoData[-1].append("{}".format(len(pattern.bends)))
    # infoData[-1].append("{}".format(len(pattern.bends)))
    # infoData[-1].append("{}".format(len(pattern.bends)))

    infoTable = Table(infoData, colWidths=[(pagesize[0] - 10*mm)/5, (pagesize[0] - 10*mm)*4/5], style=[('FONT', (0, 0), (0, -1), 'Helvetica-Bold'), ('VALIGN', (-1, 0), (-1, -1), 'TOP')])

    table_width, table_height = infoTable.wrapOn(c, pagesize[0] - 10*mm, pagesize[1] - 10*mm)
    infoTable.drawOn(c, 5*mm, 5*mm)

    c.line(0, 10*mm + table_height, pagesize[0], 10*mm + table_height)

    # transparent = Color(1, 1, 1,alpha=0)
    # c.radialGradient(int(width - thumbnail_radius / 2), int(height - thumbnail_radius / 2), thumbnail_radius, (white, transparent), extend=False)

    c.save()
    return outputStream




PART_PATTER_TEMPLATE = u"""
<svg xmlns="http://www.w3.org/2000/svg" width="{{ pattern.width * scale }}" height="{{ pattern.height * scale }}">

  <g id="container" transform="scale({{ scale }}, -{{ scale }})translate({{ -pattern.origin.x }}, {{ -pattern.origin.y - pattern.height }})" style="fill: none; stroke: black; stroke-width: 0.25;" vector-effect="non-scaling-stroke">

    {% for entity in dimensions %}
    <g>
      {% if entity.kind == "leader" %}
        {% if entity.angle >= 2 %}
          <text text-anchor="middle" y="-0.5" transform="translate({{ entity.cx }}, {{ entity.cy }})rotate( {{ entity.angle * 180 / 3.14 - 180 }} )scale({{ 1 / scale }}, {{ -1 / scale }})" style="fill: black; stroke: none; font-size: 6">{{ -entity.dimension | round(2) }}</text>
        {% elif entity.angle <= -1 %}
          <text text-anchor="middle" y="-0.5" transform="translate({{ entity.cx }}, {{ entity.cy }})rotate( {{ entity.angle * 180 / 3.14 + 180 }} )scale({{ 1 / scale }}, {{ -1 / scale }})" style="fill: black; stroke: none; font-size: 6">{{ -entity.dimension | round(2) }}</text>
        {% else %}
          <text text-anchor="middle" y="-0.5" transform="translate({{ entity.cx }}, {{ entity.cy }})rotate( {{ entity.angle * 180 / 3.14 }} )scale({{ 1 / scale }}, {{ -1 / scale }})" style="fill: black; stroke: none; font-size: 6">{{ -entity.dimension | round(2) }}</text>
        {% endif %}

        <path fill="none" stroke="#777777" stroke-width="0.25" d="{{ entity.d }}" marker-end="url(#arrow)"></path>
      {% endif %}
    </g>
    {% endfor %}

    {% if pattern.contour %}
    <path class="contour" fill="{{ contour_fill }}" d="{{ pattern.contour.svgPath() }}"></path>
    {% endif %}

    {% for entity in pattern.holes %}
      <path class="hole" fill="{{ hole_fill }}" d="{{ entity.svgPath() }}"></path>
    {% endfor %}

    {% for entity in pattern.bends %}
        {% if entity.orientation >= 2 %}
          <text text-anchor="middle" y="-0.5" transform="translate({{ entity.middle.x }}, {{ entity.middle.y }})rotate( {{ entity.orientation * 180 / 3.14 - 180 }} )scale({{ 1 / scale }}, {{ -1 / scale }})" style="fill: black; stroke: none; font-size: 6">
            {% if entity.angle <= 0 %}
              DOWN {{ (entity.angle / 3.141592 * 180) | abs | round(1) }}° R{{ entity.inner_radius | round(2) }}
            {% else %}
              UP {{ (entity.angle / 3.141592 * 180) | abs | round(1) }}° R{{ entity.inner_radius | round(2) }}
            {% endif %}
          </text>
        {% elif entity.orientation <= -1 %}
          <text text-anchor="middle" y="-0.5" transform="translate({{ entity.middle.x }}, {{ entity.middle.y }})rotate( {{ entity.orientation * 180 / 3.14 + 180 }} )scale({{ 1 / scale }}, {{ -1 / scale }})" style="fill: black; stroke: none; font-size: 6">
            {% if entity.angle <= 0 %}
              DOWN {{ (entity.angle / 3.141592 * 180) | abs | round(1) }}° R{{ entity.inner_radius | round(2) }}
            {% else %}
              UP {{ (entity.angle / 3.141592 * 180) | abs | round(1) }}° R{{ entity.inner_radius | round(2) }}
            {% endif %}
          </text>
        {% else %}
          <text text-anchor="middle" y="-0.5" transform="translate({{ entity.middle.x }}, {{ entity.middle.y }})rotate( {{ entity.orientation * 180 / 3.14 }} )scale({{ 1 / scale }}, {{ -1 / scale }})" style="fill: black; stroke: none; font-size: 6">
            {% if entity.angle <= 0 %}
              DOWN {{ (entity.angle / 3.141592 * 180) | abs | round(1) }}° R{{ entity.inner_radius | round(2) }}
            {% else %}
              UP {{ (entity.angle / 3.141592 * 180) | abs | round(1) }}° R{{ entity.inner_radius | round(2) }}
            {% endif %}
          </text>
        {% endif %}

      <path class="other" d="{{ entity.svgPath() }}" style="stroke-dasharray: {{ stroke_width }} {{ stroke_width }};"></path>
    {% endfor %}

  </g>
</svg>
"""
