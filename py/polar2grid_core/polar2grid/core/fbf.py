#!/usr/bin/env python
# encoding: utf-8
""" Flat binary file utilities

:author:       David Hoese (davidh)
:contact:      david.hoese@ssec.wisc.edu
:organization: Space Science and Engineering Center (SSEC)
:copyright:    Copyright (c) 2012 University of Wisconsin SSEC. All rights reserved.
:date:         Dec 2012
:license:      GNU GPLv3
"""
__docformat__ = "restructuredtext en"

from .constants import *

import numpy

import os
import logging
from glob import glob

log = logging.getLogger(__name__)

FBF_FLOAT32   = "real4"
FBF_FLOAT64   = "real8"
FBF_INT8      = "int1"
FBF_INT16     = "int2"
FBF_INT32     = "int4"
FBF_INT64     = "int8"
FBF_UINT8     = "uint1"
FBF_UINT16    = "uint2"
FBF_UINT32    = "uint4"
FBF_UINT64    = "uint8"

str_to_dtype = {
        FBF_FLOAT32   : numpy.float32,
        FBF_FLOAT64   : numpy.float64,
        FBF_INT8      : numpy.int8,
        FBF_INT16     : numpy.int16,
        FBF_INT32     : numpy.int32,
        FBF_INT64     : numpy.int64,
        FBF_UINT8     : numpy.uint8,
        FBF_UINT16    : numpy.uint16,
        FBF_UINT32    : numpy.uint32,
        FBF_UINT64    : numpy.uint64
        }

# Map polar2grid data type to FBF data type
dtype2fbf = {
        DTYPE_FLOAT32 : FBF_FLOAT32,
        DTYPE_FLOAT64 : FBF_FLOAT64,
        DTYPE_INT8    : FBF_INT8,
        DTYPE_INT16   : FBF_INT16,
        DTYPE_INT32   : FBF_INT32,
        DTYPE_INT64   : FBF_INT64,
        DTYPE_UINT8   : FBF_UINT8,
        DTYPE_UINT16  : FBF_UINT16,
        DTYPE_UINT32  : FBF_UINT32,
        DTYPE_UINT64  : FBF_UINT64
        }

def data_type_to_fbf_type(data_type):
    if data_type not in dtype2fbf:
        msg = "Can not convert data type '%s' to FBF data type" % (data_type,)
        log.error(msg)
        raise ValueError(msg)

    return dtype2fbf[data_type]

def check_stem(stem_name):
    """Helper function to tell a user if a stem name will conflict with
    another file in the current working directory.
    """
    log.debug("Checking stem '%s'" % (stem_name,))
    if len(glob(stem_name + ".*")) != 0:
        msg = "Flat binary file with stem '%s' already exists, please remove and try again" % (stem_name,)
        log.error(msg)
        raise ValueError(msg)

class Workspace(object):
    """Wrapper object around ``numpy.fromfile()`` method to treat a directory as a
    workspace of flat binary files.

    :attention: Replaces rayg's ``keoni.fbf.Workspace``
    """
    def __init__(self, dir='.'):
        self._dir=dir

    def _parse_attr_name(self, name):
        """Take a FBF formatted filename and parse out the binary data
        details such as number of rows/cols and data type.

        :Parameters:
            name : str
                Flat binary formatted name (ex. image_I01.real4.6400.10167).
        """
        fullpath = os.path.abspath(name)
        filename = os.path.split(fullpath)[1]
        parts = filename.split(".")
        if len(parts) != 4 and len(parts) != 5:
            log.error("Found filename %s with incorrect format, need 4 or 5 parts" % filename)
            raise ValueError("Found filename %s with incorrect format, need 4 or 5parts" % filename)

        attr_name = parts[0]
        type = parts[1]
        shape = parts[2:][::-1] # Flip shape order, fbf is minor to major, numpy is major to minor
        if type not in str_to_dtype:
            log.error("Don't know how to interpret data type %s from %s" % (type,filename))
            raise ValueError("Don't know how to interpret data type %s from %s" % (type,filename))
        dtype = str_to_dtype[type]

        try:
            shape = tuple(list( int(x) for x in shape ))
        except ValueError:
            log.error("Shape must be integers not (%r)" % (shape,))
            raise ValueError("Shape must be integers not (%r)" % (shape,))

        return attr_name,dtype,shape

    def __getattr__(self, name, mode='r'):
        g = glob( os.path.join(self._dir,name+'.*') )
        if len(g)==1:
            attr_name,dtype,shape = self._parse_attr_name(g[0])
            mmap_arr = numpy.memmap(g[0], dtype=dtype, mode=mode, shape=shape)
            setattr(self,name,mmap_arr)
            return mmap_arr
        elif len(g) > 1:
            raise AttributeError("Found too many instances for %s in workspace" % name)
        else:
            raise AttributeError("%s not in workspace" % name)
        
    def var(self,name):
        return getattr(self, name)
    
    def vars(self):
        for path in os.listdir(self._dir):
            try:
                fullpath = os.path.join(self._dir, path)
                stemname,_,_ = self._parse_attr_name(fullpath)
                yield stemname, self.__getattr__(stemname)
            except:
                pass
            
    def variables(self):
        return dict(self.vars())

    def __getitem__(self,name):
        return getattr(self,name)

