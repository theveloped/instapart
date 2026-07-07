import setuptools

from distutils.core import setup
from distutils.extension import Extension

from Cython.Distutils import build_ext

ext_modules = [
        Extension("aag",  ["aag.py"]),
        Extension("activate",  ["activate.py"]),
        Extension("analyse",  ["analyse.py"]),
        Extension("auto",  ["auto.py"]),
        Extension("cycad",  ["cycad.py"]),
        Extension("explode",  ["explode.py"]),
        Extension("flatten",  ["flatten.py"]),
        Extension("geometry",  ["geometry.py"]),
        Extension("label",  ["label.py"]),
        Extension("utils",  ["utils.py"]),
        Extension("models",  ["models.py"]),
        Extension("schemas",  ["schemas.py"]),
        Extension("service",  ["service.py"]),
        Extension("observe",  ["observe.py"]),
        Extension("images",  ["images.py"]),
        Extension("naming",  ["naming.py"]),
        Extension("documents",  ["documents.py"])
    ]

setup(
    name = 'My Program Name',
    cmdclass = {'build_ext': build_ext},
    ext_modules = ext_modules
)