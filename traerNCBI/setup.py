#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
setup.py — Compilador automático con Pybind11 y soporte para OpenMP o MSVC.
"""

from setuptools import setup, Extension
import pybind11, sys, os

# Detecta MSVC (Visual Studio)
is_msvc = 'MSC' in sys.version

extra_compile_args = []
extra_link_args = []

if is_msvc:
    print("🟦 Detectado compilador MSVC (Visual Studio)")
    extra_compile_args = ['/O2', '/std:c++17', '/EHsc']
else:
    print("🟩 Detectado GCC/Clang")
    extra_compile_args = ['-O3', '-std=c++17', '-fopenmp']
    extra_link_args = ['-fopenmp']

setup(
    name='fastmetrics',
    version='1.0.1',
    ext_modules=[
        Extension(
            'fastmetrics',
            sources=['fastmetrics.cpp'],
            include_dirs=[pybind11.get_include()],
            language='c++',
            extra_compile_args=extra_compile_args,
            extra_link_args=extra_link_args,
        )
    ],
)
