# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

import os
import sys
import ntpath
# import PyQt5
import OCC
from glob import glob
from cryptlex.lexactivator import LexActivator, LexStatusCodes, PermissionFlags, LexActivatorException
from cryptlex.lexactivator.lexactivator_native import get_library_path
# import distutils.util


version = 1.2
DIR_PATH = os.getcwd()
COMPILING_PLATFORM = os.name

PATH_EXE = [os.path.join(DIR_PATH, 'instapart.py')]

if COMPILING_PLATFORM == 'nt':
    platform = 'win'
    STRIP = False

    BINARIES = [
      ( 'LexActivator.dll', '.' ),
      ( 'Bystronic.Bysoft.BatchUnfold.exe', '.' )
    ]

    for binary in glob('*.pyd'):
      BINARIES.append((binary, '.'))

    DATAS = []

    HIDDENIMPORTS = [
      'win32serviceutil',
      'servicemanager',
      'win32service',
      'win32event',
      'win32api',
      'win32con',
      'win32event',
      'win32evtlogutil',
      'psutil',
    ]

elif sys.platform.startswith("linux"):
    platform = 'linux'
    STRIP = False

    BINARIES = [( get_library_path(), '.' )]
    for binary in glob('*.so'):
        BINARIES.append((binary, '.'))

    DATAS = []
    HIDDENIMPORTS = ['PIL._imaging']

elif COMPILING_PLATFORM == 'linux-x86_64':
    platform = 'nix64'
    STRIP = True

    DATAS = []
    HIDDENIMPORTS = []

else:
    platform = 'mac'
    STRIP = True

    BINARIES = [( 'libLexActivator.dylib', '.' )]
    for binary in glob('*.so'):
      BINARIES.append((binary, '.'))

    DATAS = []
    HIDDENIMPORTS = ['_sysconfigdata']

DATAS = DATAS + [
                ( os.path.join("templates", "AC1015.dxf"), os.path.join("ezdxf", "templates") ),
                ( 'product_v38505766-362d-47bf-a0a1-02c677e7124c.dat', '.' ),
                ( 'settings.json', '.'),
                ( 'icon.ico', '.')
              ]

HIDDENIMPORTS = HIDDENIMPORTS + [
#  'PyQt5',
#  'PyQt5.QtCore',
#  'PyQt5.QtGui',
#  'PyQt5.QtOpenGL',
#  'PyQt5.QtWidgets',
#  'PyQt5.sip',

  'xlwt',

  'PIL.Image',
  'PIL.ImageDraw',

  'jinja2',
  'svglib.svglib',

  'watchdog.events',
  'watchdog.observers',

  'cython',
  'sklearn',
  'sklearn.neighbors.typedefs',
  'sklearn.neighbors.quad_tree',
  'sklearn.tree._utils',
  'sklearn.utils.sparsetools',

  'pyclipper',
  'marshmallow',
  'cryptlex.lexactivator',

  'OCC.BRepAlgo',
  'OCC.BRepLib',
  'OCC.HLRBRep',
  'OCC.HLRAlgo',

  'OCC.TDocStd',
  'OCC.XCAFApp',
  'OCC.XCAFDoc',
  'OCC.STEPCAFControl',
  'OCC.TDF',
  'OCC.TDataStd',
  'OCC.TCollection',
  'OCC.TopLoc',
  'OCC.Interface',
  'OCC.GeomAbs',
  'OCC.ShapeUpgrade',


  'OCC.IFSelect',
  'OCC.ShapeFix',
  'OCC.ShapeAnalysis',
  'OCC.GCPnts',
  'OCC.CPnts',
  'OCC.GeomAdaptor',
  'OCC.GeomProjLib',
  'OCC.BRep',
  'OCC.Bnd',
  'OCC.BRepBndLib',
  'OCC.BRepBuilderAPI',
  'OCC.BRepPrimAPI',
  'OCC.STEPControl',
  'OCC.TopAbs',
  'OCC.TopoDS',
  'OCC.GProp',
  'OCC.BRepGProp',
  'OCC.gp',
  'OCC.GeomLProp',
  'OCC.BRepAdaptor',
  'OCC.BRepLProp',
  'OCC.GeomLib',
  'OCC.BRepTools',
  'OCC.TopExp',
  'OCC.Geom',
  'OCC.GeomAPI',
  'OCC.Geom2dAPI',
  'OCC.GC',
  'OCC.TopAbs',
  'OCC.BRepAlgoAPI',

  'ezdxf']


a = Analysis(['instapart.py'],
             pathex=PATH_EXE,
             binaries=BINARIES,
             datas=DATAS,
             hiddenimports=HIDDENIMPORTS,
             hookspath=[],
             runtime_hooks=[],
             excludes=[
              'OCC.Display',
              'matplotlib',
              'PyQt5'
             ],
             win_no_prefer_redirects=False,
             win_private_assemblies=False,
             cipher=block_cipher,
             noarchive=False)

pyz = PYZ(a.pure, a.zipped_data,
             cipher=block_cipher)

exe = EXE(pyz,
          a.scripts,
          [],
          exclude_binaries=True,
          name='instapart',
          debug=False,
          bootloader_ignore_signals=False,
          strip=STRIP,
          upx=True,
          console=True,
          icon='icon.ico' )

coll = COLLECT(exe,
               a.binaries,
               a.zipfiles,
               a.datas,
               strip=STRIP,
               upx=True,
               upx_exclude=[],
               name='instapart-{}-{}'.format(version, platform))

if platform == 'mac':
    print("doing bundle ")
    app = BUNDLE(coll,
                 name='instapart.app',
                 icon='icon.ico',
                 bundle_identifier=None)
