#!/usr/bin/env python
# encoding: utf-8
# Copyright (C) 2012-2016 Space Science and Engineering Center (SSEC),
# University of Wisconsin-Madison.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# This file is part of the polar2grid software package. Polar2grid takes
# satellite observation data, remaps it, and writes it to a file format for
#     input into another program.
# Documentation: http://www.ssec.wisc.edu/software/polar2grid/
#
# Written by David Hoese    June 2016
# University of Wisconsin-Madison
# Space Science and Engineering Center
# 1225 West Dayton Street
# Madison, WI  53706
# david.hoese@ssec.wisc.edu
"""The SCMI AWIPS backend is used to create AWIPS compatible tiled NetCDF
files. The Advanced Weather Interactive Processing System (AWIPS) is a
program used by the United States National Weather Service (NWS) and others
to view
different forms of weather imagery. Sectorized Cloud and Moisture Imagery
(SCMI) is a netcdf format accepted by AWIPS to store one image broken up
in to one or more "tiles". Once AWIPS is configured for specific products
the SCMI NetCDF backend can be used to provide compatible products to the
system. The files created by this backend are compatible with AWIPS II (AWIPS I is no
longer supported).

The AWIPS NetCDF backend takes remapped binary image data and creates an
AWIPS-compatible NetCDF 4 file.
Both the AWIPS backend and the AWIPS client must be configured to handle certain
products over certain grids

 .. warning::

     The SCMI backend does not default to using any grid. Therefore, it is recommended to specify
     one or more grids for remapping by using the `-g` flag.

:author:       David Hoese (davidh)
:organization: Space Science and Engineering Center (SSEC)
:copyright:    Copyright (c) 2012-2016 University of Wisconsin SSEC. All rights reserved.
:date:         June 2016
:license:      GNU GPLv3

"""
__docformat__ = "restructuredtext en"

import sys
from datetime import datetime, timedelta
from netCDF4 import Dataset

import logging
import numpy as np
import os

from polar2grid.core.rescale import DEFAULT_RCONFIG
from polar2grid.core.dtype import DTYPE_UINT8
from polar2grid.core import roles
from .awips_config import AWIPS2ConfigReader, CONFIG_FILE as DEFAULT_AWIPS_CONFIG, NoSectionError

LOG = logging.getLogger(__name__)
# AWIPS 2 seems to not like data values under 0
AWIPS_USES_NEGATIVES = False
DEFAULT_OUTPUT_PATTERN = '{source_name}_AWIPS_{satellite}_{instrument}_{product_name}_{sector_id}_T{tile_number:03d}_{begin_time:%Y%m%d_%H%M}.nc'

SCMI_GLOBAL_ATT=dict(
    product_tile_height=None,  # 1100,
    # projection=None,
    # periodicity=10,
    # tile_center_longitude=None,  # 88.0022078322,
    # satellite_altitude=None,  # 35785.863,
    satellite_id=None,  # GOES-H8
    tile_column_offset=None,  # 2750,
    pixel_y_size=None,  # km
    # product_center_latitude=None,
    start_date_time=None,  # 2015181030000,  # %Y%j%H%M%S
    # product_columns=None,  # 11000,
    # title="Sectorized Cloud and Moisture Full Disk Imagery",
    # abi_mode=1,
    pixel_x_size=None,  # km
    # product_name=None,  # "HFD-010-B11-M1C01",
    # satellite_longitude=None,  # 140.7,
    # source_spatial_resolution=None,  # km
    # central_wavelength=None,  # 0.47063,
    number_product_tiles=None,  # 76,
    # bit_depth=None,
    # product_rows=None,  # 11000,
    # satellite_latitude=0.0,
    # ICD_version="SE-08_7034704_GS_AWIPS_Ext_ICD_RevB.3",
    # source_scene=None,  # FIXME: handle regionals
    production_location=None,  # "MSC",
    # tile_center_latitude=None,  # 62.41709885,
    Conventions="CF-1.7",
    # channel_id=None,  # 1,
    # product_center_longitude=None,  # 140.7,
    product_tile_width=None,  # 1375,
    # request_spatial_resolution=None,
    tile_row_offset=None,  # 0,
)


class AttributeHelper(object):
    """
    helper object which wraps around a HimawariScene to provide SCMI attributes
    """
    tile_count = (0,0)  # ny, nx
    hsd = None
    offset = (0,0)  # ty, tx tile number
    tile_shape = (0,0)  # wy, wx height and width of tile in pixels
    scene_shape = (0,0)  # sy, sx height and width of scene in pixels

    def __init__(self, dataset, offset, tile_count, scene_shape):
        self.dataset = dataset
        self.offset = offset
        self.tile_count = tile_count
        self.scene_shape = scene_shape
        self.tile_shape = (int(scene_shape[0] / tile_count[0]), int(scene_shape[1] / tile_count[1]))

    def apply_attributes(self, nc, table, prefix=''):
        """
        apply fixed attributes, or look up attributes needed and apply them
        """
        for name, value in sorted(table.items()):
            if name in nc.ncattrs():
                LOG.debug('already have a value for %s' % name)
                continue
            if value is not None:
                setattr(nc, name, value)
            else:
                funcname = prefix+name  # _global_ + product_tile_height
                func = getattr(self, funcname, None)
                if func is not None:
                    value = func()
                    if value is not None:
                        setattr(nc, name, value)
                else:
                    LOG.info('no routine matching %s' % funcname)

    def _scene_time(self):
        return self.dataset["begin_time"] + timedelta(minutes=int(os.environ.get("DEBUG_TIME_SHIFT", 0)))

    def _tile_number(self):
        # e.g.
        # 001 002 003 004
        # 005 006 ...
        return self.offset[0] * self.tile_count[1] + self.offset[1] + 1

    def _product_name(self):
        return self.dataset["product_name"]

    def _global_product_tile_height(self):  # = None, # 1100,
        return self.tile_shape[0]

    def _global_product_tile_width(self):  # = None, # 1100,
        return self.tile_shape[1]

    def _global_number_product_tiles(self):
        return self.tile_count[0] * self.tile_count[1]

    def _global_satellite_id(self):
        return "{}-{}".format(self.dataset["satellite"].upper(), self.dataset["instrument"].upper())

    def _tile_center(self): # = None, # 88.0022078322,
        # calculate center longitude of tile
        # FIXME: resolve whether we need half-pixel offset
        row = self._global_tile_row_offset() + self.tile_shape[0]/2
        col = self._global_tile_column_offset() + self.tile_shape[1]/2
        return self.dataset["grid_definition"].get_lonlat(row, col)

    def _global_tile_center_longitude(self): # = None, # 88.0022078322,
        return np.float32(self._tile_center()[0])

    def _global_product_rows(self):
        return self.scene_shape[0]

    def _global_product_columns(self):
        return self.scene_shape[1]

    def _global_tile_row_offset(self):
        return self.offset[0] * self.tile_shape[0]

    def _global_tile_column_offset(self):
        return self.offset[1] * self.tile_shape[1]

    def _global_tile_center_latitude(self): # = None, # 88.0022078322,
        return np.float32(self._tile_center()[1])

    def _global_bit_depth(self):
        return self.dataset["bit_depth"]

    def _global_satellite_altitude(self):
        """ABI grid based satellite altitude used by L1b processing.

        Returns
        -------
        float or None
            Height of satellite in meters or None
        """
        return self.dataset["grid_definition"].proj4_dict.get("h")

    def _global_satellite_longitude(self): # = None, # 35785.863,
        proj4_dict = self.dataset["grid_definition"].proj4_dict
        if proj4_dict['proj'] == 'geos':
            return np.float32(proj4_dict["lon_0"])  # float32 needed?
        else:
            return None

    def _global_product_name(self):
        return self._product_name()

    def _global_channel_id(self):
        return self.dataset.get("channel_id", 0)

    def _global_pixel_x_size(self):
        return self.dataset["grid_definition"]["cell_width"] / 1000.

    _global_request_spatial_resolution = _global_source_spatial_resolution = _global_pixel_y_size = _global_pixel_x_size

    def _global_start_date_time(self):
        when = self._scene_time()
        return when.strftime('%Y-%m-%dT%H:%M:%S')

    def _global_product_center_longitude(self):
        grid_def = self.dataset["grid_definition"]
        return grid_def.lonlat_center[0]

    def _global_product_center_latitude(self):
        grid_def = self.dataset["grid_definition"]
        return grid_def.lonlat_center[1]

    def _global_production_location(self):
        org = os.environ.get('ORGANIZATION', None)
        if org is not None:
            return org
        else:
            LOG.warning('environment ORGANIZATION not set for .production_location attribute, using hostname')
            import socket
            return socket.gethostname()  # FUTURE: something more correct but this will do for now


class SCMI_writer(object):
    """
    Write a basic NetCDF4 file with header data mapped to global attributes, and BT/ALB/RAD variables
    FUTURE: optionally add time dimension (CF)
    FUTURE: optionally add zenith and azimuth angles

    """
    _nc = None
    _shape = None
    _offset = None  # offset within source file
    _kind = None  # 'albedo', 'brightness_temp'
    _band = None
    # _include_geo = False
    _include_fgf = True
    _fill_value = 0
    row_dim_name, col_dim_name = 'y', 'x'
    y_var_name, x_var_name = 'y', 'x'
    image_var_name = 'data'
    # lat_var_name = 'latitude'
    # lon_var_name = 'longitude'
    # line_time_var_name = 'line_time_offset'
    # lat = None
    # lon = None
    fgf_y = None
    fgf_x = None
    # line_time = None
    projection = None

    def __init__(self, filename, offset, shape, include_fgf=True, helper=None, compress=False):
        self._nc = Dataset(filename, 'w')
        self._shape = shape
        self._offset = offset
        # self._include_geo = include_geo
        self._include_fgf = include_fgf
        self._compress = compress
        self.helper = helper

    def create_dimensions(self):
        # Create Dimensions
        lines, columns = self._shape
        _nc = self._nc
        _nc.createDimension(self.row_dim_name, lines)
        _nc.createDimension(self.col_dim_name, columns)

    def create_variables(self, fill_value, scale_factor=None, add_offset=None):
        # geo_coords = "%s %s" % (self.lat_var_name, self.lon_var_name)
        fgf_coords = "%s %s" % (self.y_var_name, self.x_var_name)

        self.image_data = self._nc.createVariable(self.image_var_name, 'u2', dimensions=(self.row_dim_name, self.col_dim_name), fill_value=fill_value, zlib=self._compress)
        self.image_data.coordinates = fgf_coords
        self.apply_data_attributes(scale_factor, add_offset)

        if self._include_fgf:
            self.fgf_y = self._nc.createVariable(self.y_var_name, 'i2', dimensions=(self.row_dim_name,), zlib=self._compress)
            self.fgf_x = self._nc.createVariable(self.x_var_name, 'i2', dimensions=(self.col_dim_name,), zlib=self._compress)

            # FUTURE: include compatibility 'y' and 'x', though there's a nonlinear transformation from CGMS to GOES y/x angles.
            # This requires that the scale_factor and add_offset are 1.0 and 0.0 respectively,
            # which violates some uses that use the line/column unscaled form expected by some applications.

        # if self._include_geo:
        #     self.lat = self._nc.createVariable(self.lat_var_name, 'f4', dimensions=(self.row_dim_name, self.col_dim_name), fill_value=self.fmissing, zlib=self._compress)
        #     self.lat.units = 'degrees_north'
        #     self.lon = self._nc.createVariable(self.lon_var_name, 'f4', dimensions=(self.row_dim_name, self.col_dim_name), fill_value=self.fmissing, zlib=self._compress)
        #     self.lon.units = 'degrees_east'
        # self.line_time = None # self._nc.createVariable(self.line_time_var_name, 'f8', dimensions=(self.row_dim_name,))
        # self.line_time.units = 'seconds POSIX'
        # self.line_time.long_name = "POSIX epoch seconds elapsed since base_time for image line"

    def apply_data_attributes(self, bitdepth, scale_factor=None, add_offset=None):
        # NOTE: grid_mapping is set by `set_projection_attrs`
        self.image_data.scale_factor = np.float32(scale_factor)
        self.image_data.add_offset = np.float32(add_offset)
        self.image_data.units = self.helper.dataset.get('units', '1')
        # FIXME: does this need to be increased/decreased by 1 to leave room for the fill value?
        file_bitdepth = self.image_data.dtype.itemsize * 8
        is_unsigned = self.image_data.dtype.kind == 'u'
        if not AWIPS_USES_NEGATIVES and not is_unsigned:
            file_bitdepth -= 1
            is_unsigned = True

        if bitdepth >= file_bitdepth:
            bitdepth = file_bitdepth
            num_fills = 1
        else:
            bitdepth = bitdepth
            num_fills = 0
        if not is_unsigned:
            # signed data type
            self.image_data.valid_min = -2**(bitdepth - 1)
            # 1 less for data type (65535), another 1 less for fill value (fill value = max file value)
            self.image_data.valid_max = 2**(bitdepth - 1) - 1 - num_fills
        else:
            # unsigned data type
            self.image_data.valid_min = 0
            self.image_data.valid_max = 2**bitdepth - 1 - num_fills

        if "standard_name" in self.helper.dataset:
            self.image_data.standard_name = self.helper.dataset["standard_name"]
        elif self.helper.dataset["data_kind"] in ["reflectance", "albedo"]:
            self.image_data.standard_name = "toa_bidirectional_reflectance"
        else:
            self.image_data.standard_name = self.helper.dataset["data_kind"]

    # def set_geo(self, lat, lon):
    #     if self.lat is not None:
    #         self.lat[:,:] = np.ma.fix_invalid(lat, fill_value=self.missing)
    #     if self.lon is not None:
    #         self.lon[:,:] = np.ma.fix_invalid(lon, fill_value=self.missing)

    def set_fgf(self, x, mx, bx, y, my, by, units='meters', downsample_factor=1):
        # assign values before scale factors to avoid implicit scale reversal
        LOG.debug('y variable shape is {}'.format(self.fgf_y.shape))
        self.fgf_y.scale_factor = np.float64(my * float(downsample_factor))
        self.fgf_y.add_offset = np.float64(by)
        self.fgf_y.units = units
        self.fgf_y.standard_name = "projection_y_coordinate"
        # self.fgf_y.long_name = "CGMS N/S fixed grid viewing angle (not interchangeable with GOES y)"
        self.fgf_y[:] = y

        self.fgf_x.scale_factor = np.float64(mx * float(downsample_factor))
        self.fgf_x.add_offset = np.float64(bx)
        self.fgf_x.units = units
        self.fgf_x.standard_name = "projection_x_coordinate"
        # self.fgf_x.long_name = "CGMS E/W fixed grid viewing angle (not interchangeable with GOES x)"
        self.fgf_x[:] = x

    def set_image_data(self, data, fill_value):
        LOG.info('writing image data')
        # note: autoscaling will be applied to make int16
        assert(hasattr(data, 'mask'))
        self.image_data[:, :] = np.require(data.filled(fill_value), dtype=np.float32)

    def set_projection_attrs(self, grid_def):
        """
        assign projection attributes per GRB standard
        """
        proj4_info = grid_def.proj4_dict
        if proj4_info["proj"] == "geos":
            p = self.projection = self._nc.createVariable("fixedgrid_projection", 'i4')
            self.image_data.grid_mapping = "fixedgrid_projection"
            p.short_name = grid_def["grid_name"]
            p.grid_mapping_name = "geostationary"
            # p.long_name = "Himawari Imagery Projection"
            p.sweep_angle_axis = proj4_info.get("sweep", "x")
            # Projection.units = "radians"
            # calculate invflat 'f' such that rpol = req - req/invflat
            a = proj4_info["a"]
            b = proj4_info["b"]
            h = proj4_info["h"]
            lon_0 = proj4_info["lon_0"]

            p.semi_major = a * 1e3  # 6378.137f ;
            p.semi_minor = b * 1e3  # convert to meters
            p.perspective_point_height = h
            p.latitude_of_projection_origin = np.float32(0.0)
            p.longitude_of_projection_origin = np.float32(lon_0)  # is the float32 needed?

            # if "f" in proj4_info:
            #     f = proj4_info['f']
            # elif a != b:
            #     f = 1.0 / (1.0 - b/a)
            # else:
            #     raise ValueError("Only ellipsoid 'geos' projections are supported")
            # Projection.inverse_flattening = np.float32(f) # 298.2572f ;

            # Set globals based on projection
            # self._nc.projection = "Fixed_Grid"
        elif proj4_info["proj"] == "lcc":
            p = self.projection = self._nc.createVariable("lambert_projection", 'i4')
            self.image_data.grid_mapping = "lambert_projection"
            p.short_name = grid_def["grid_name"]
            p.grid_mapping_name = "lambert_conformal_conic"
            if proj4_info["lat_0"] != proj4_info["lat_1"]:
                raise NotImplementedError("Unsure how to handle two standard parallels for LCC projection")
            p.standard_parallel = proj4_info["lat_0"]  # How do we specify two standard parallels?
            p.longitude_of_central_meridian = proj4_info["lon_0"]
            p.latitude_of_projection_origion = proj4_info["lat_0"]  # XXX: lat_1?
            p.false_easting = proj4_info.get("x", 0.0)
            p.false_northing = proj4_info.get("y", 0.0)
            p.semi_major = proj4_info["a"]
            p.semi_minor = proj4_info["b"]

            # Set globals based on projection
            # self._nc.projection = "Lambert Conformal"

        # self._nc.grid_name = grid_def["grid_name"]

    def set_global_attrs(self, meta, nav, dataset_name, sector_id):
        # self._nc.central_wavelength = self.helper.dataset["wavelength"]
        self._nc.creator = "UW SSEC - CSPP Polar2Grid"
        self._nc.creation_time = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S')
        self._nc.dataset_name = dataset_name
        self._nc.sector_id = sector_id
        self.helper.apply_attributes(self._nc, SCMI_GLOBAL_ATT, '_global_')

    def close(self):
        self._nc.sync()
        self._nc.close()
        self._nc = None


class Backend(roles.BackendRole):
    def __init__(self, backend_configs=None, rescale_configs=None,
                 compress=False, fix_awips=False, **kwargs):
        backend_configs = backend_configs or [DEFAULT_AWIPS_CONFIG]
        rescale_configs = rescale_configs or [DEFAULT_RCONFIG]
        self.awips_config_reader = AWIPS2ConfigReader(*backend_configs)
        self.compress = compress
        self.fix_awips = fix_awips
        # self.rescaler = Rescaler(*rescale_configs, **kwargs)
        super(Backend, self).__init__(**kwargs)

    @property
    def known_grids(self):
        return None

    def _calc_factor_offset(self, data=None, dtype=np.int16, bitdepth=None, min=None, max=None, num_fills=1):
        if num_fills > 1:
            raise NotImplementedError("More than one fill value is not implemented yet")

        dtype = np.dtype(dtype)
        file_bitdepth = dtype.itemsize * 8
        is_unsigned = dtype.kind == 'u'
        if not AWIPS_USES_NEGATIVES and not is_unsigned:
            file_bitdepth -= 1
            is_unsigned = True

        if bitdepth is None:
            bitdepth = file_bitdepth
        if bitdepth >= file_bitdepth:
            bitdepth = file_bitdepth
        else:
            # don't take away from the data bitdepth if there is room in
            # file data type to allow for extra fill values
            num_fills = 0
        if min is None:
            min = data.min()
        if max is None:
            max = data.max()
        mx = float(max - min) / (2**bitdepth - 1 - num_fills)
        bx = min
        if not is_unsigned:
            bx += 2**(bitdepth - 1) * mx
            # max value
            fills = [2**(file_bitdepth - 1) - 1]
        else:
            # max value
            fills = [2**file_bitdepth - 1]
        return fills, mx, bx

    def create_output_from_product(self, gridded_product, sector_id=None,
                                   output_pattern=None,
                                   tile_count=(1, 1), tile_size=None,
                                   tile_offset=(0, 0),
                                   **kwargs):
        data_type = DTYPE_UINT8
        fill_value = np.nan
        grid_def = gridded_product["grid_definition"]

        try:
            awips_info = self.awips_config_reader.get_product_info(gridded_product)
        except NoSectionError as e:
            LOG.error("Could not get information on product from backend configuration file")
            # NoSectionError is not a "StandardError" so it won't be caught normally
            raise RuntimeError(e.message)

        # TODO: Remove unnecessary file attributes
        # TODO: Add configuration to define physical element based on product name
        # TODO: Add command line flag for region/sector id

        # Create the netcdf file
        created_files = []
        try:
            LOG.debug("Scaling %s data to fit in netcdf file...", gridded_product["product_name"])
            # data = self.rescaler.rescale_product(gridded_product, data_type,
            #                                      inc_by_one=inc_by_one, fill_value=fill_value)
            data = gridded_product.get_data_array()
            mask = gridded_product.get_data_mask()
            data = np.ma.masked_array(data, mask=mask)

            LOG.info("Writing product %s to AWIPS NetCDF file", gridded_product["product_name"])
            if tile_size is not None:
                tile_shape = (int(min(tile_size[0], data.shape[0])), int(min(tile_size[1], data.shape[1])))
                tile_count = (int(np.ceil(data.shape[0] / tile_shape[0])), int(np.ceil(data.shape[1] / tile_shape[1])))
            else:
                tile_shape = (int(data.shape[0] / tile_count[0]), int(data.shape[1] / tile_count[1]))
            tmp_tile = np.ma.zeros(tile_shape, dtype=np.float32)
            tmp_tile.set_fill_value(fill_value)

            # Get X/Y
            # Since our tiles may go over the edge of the original "grid" we
            # need to make sure we calculate X/Y to the edge of all of the tiles
            imaginary_data_size = (tile_shape[0] * tile_count[0], tile_shape[1] * tile_count[1])
            imaginary_grid_def = gridded_product["grid_definition"].copy()
            imaginary_grid_def["height"] = imaginary_data_size[0]
            imaginary_grid_def["width"] = imaginary_data_size[1]
            proj4_info = grid_def.proj4_dict
            if proj4_info["proj"] == "geos":
                xy_units = "microradian"
                micro_factor = 1e6
            else:
                xy_units = "meters"
                micro_factor = 1

            x, y = imaginary_grid_def.get_xy_arrays()
            x = x[0].squeeze()  # all rows should have the same coordinates
            y = y[:, 0].squeeze()  # all columns should have the same coordinates
            # scale the X and Y arrays to fit in the file for 16-bit integers
            # mx, bx = self._calc_factor_offset(x, bitdepth=13, dtype=np.uint16)
            # AWIPS is dumb and requires the integer values to be 0, 1, 2, 3, 4
            if x.shape[0] > 2**(16-2):
                # awips uses 0, 1, 2, 3 so we can't use the negative end of the variable space
                raise ValueError("X variable too large for AWIPS-version of 16-bit integer space")
            bx = x.min()
            mx = gridded_product['grid_definition']['cell_width']
            bx *= micro_factor
            mx *= micro_factor
            # my, by = self._calc_factor_offset(y, bitdepth=13, dtype=np.uint16)
            if y.shape[0] > 2**(16-2):
                # awips uses 0, 1, 2, 3 so we can't use the negative end of the variable space
                raise ValueError("Y variable too large for AWIPS-version of 16-bit integer space")
            by = y.min()
            my = gridded_product['grid_definition']['cell_height']
            by *= micro_factor
            my *= micro_factor

            bit_depth = gridded_product.get("bit_depth", 16)
            valid_min = gridded_product.get('valid_min')
            if valid_min is None:
                valid_min = np.nanmin(data)
            valid_max = gridded_product.get('valid_max')
            if valid_max is None:
                valid_max = np.nanmax(data)
            gridded_product["valid_min"] = valid_min
            gridded_product["valid_max"] = valid_max
            fills, factor, offset = self._calc_factor_offset(bitdepth=bit_depth, min=valid_min, max=valid_max, dtype=np.uint16)

            for ty in range(tile_count[0]):
                for tx in range(tile_count[1]):
                    # store tile data to an intermediate array
                    tmp_tile[:] = fill_value
                    tile_number = ty * tile_count[1] + tx + 1
                    tmp_tile[:] = data[ty * tile_shape[0]: (ty + 1) * tile_shape[0], tx * tile_shape[1]: (tx + 1) * tile_shape[1]]

                    if tmp_tile.mask.all():
                        LOG.info("Tile %d contains all masked data, skipping...", tile_number)
                        continue
                    tmp_x = x[tx * tile_shape[1]: (tx + 1) * tile_shape[1]]
                    tmp_y = y[ty * tile_shape[0]: (ty + 1) * tile_shape[0]]

                    attr_helper = AttributeHelper(gridded_product, (ty + tile_offset[0], tx + tile_offset[1]), tile_count, data.shape)
                    tile_number = attr_helper._tile_number()
                    # output_filename = attr_helper._filename(environment='O', data_type='R')
                    if "{" in output_pattern:
                        # format the filename
                        of_kwargs = gridded_product.copy(as_dict=True)
                        of_kwargs["data_type"] = data_type
                        of_kwargs["begin_time"] += timedelta(minutes=int(os.environ.get("DEBUG_TIME_SHIFT", 0)))
                        output_filename = self.create_output_filename(output_pattern,
                                                                      grid_name=grid_def["grid_name"],
                                                                      rows=grid_def["height"],
                                                                      columns=grid_def["width"],
                                                                      source_name=awips_info.get('source_name'),
                                                                      sector_id=sector_id,
                                                                      tile_number=tile_number,
                                                                      **of_kwargs)
                    else:
                        output_filename = output_pattern
                    if os.path.isfile(output_filename):
                        if not self.overwrite_existing:
                            LOG.error("AWIPS file already exists: %s", output_filename)
                            raise RuntimeError("AWIPS file already exists: %s" % (output_filename,))
                        else:
                            LOG.warning("AWIPS file already exists, will overwrite: %s", output_filename)
                    created_files.append(output_filename)

                    LOG.info("Writing tile %d to %s", tile_number, output_filename)

                    nc = SCMI_writer(output_filename, (ty + tile_offset[0], tx + tile_offset[1]), tile_shape,
                                     helper=attr_helper, compress=self.compress)
                    LOG.debug("Creating dimensions...")
                    nc.create_dimensions()
                    LOG.debug("Creating variables...")
                    nc.create_variables(factor, offset, fills[0])
                    LOG.debug("Creating global attributes...")
                    nc.set_global_attrs(None, None, "AWIPS_" + gridded_product['product_name'], sector_id)
                    LOG.debug("Creating projection attributes...")
                    nc.set_projection_attrs(gridded_product["grid_definition"])
                    LOG.debug("Writing image data...")
                    nc.set_image_data(tmp_tile, fills[0])
                    LOG.debug("Writing X/Y navigation data...")
                    nc.set_fgf(tmp_x, mx, bx, tmp_y, my, by, units=xy_units)
                    nc.close()

                    if self.fix_awips:
                        # hack to get files created by new NetCDF library
                        # versions to be read by AWIPS buggy java version
                        # of NetCDF
                        LOG.info("Modifying SCMI NetCDF file to work with AWIPS")
                        import h5py
                        h = h5py.File(output_filename, 'a')
                        if '_NCProperties' in h.attrs:
                            del h.attrs['_NCProperties']
                        h.close()
        except StandardError:
            last_fn = created_files[-1] if created_files else "N/A"
            LOG.error("Error while filling in NC file with data: %s", last_fn)
            for fn in created_files:
                if not self.keep_intermediate and os.path.isfile(fn):
                    os.remove(fn)
            raise

        return created_files[-1]


def add_backend_argument_groups(parser):
    group = parser.add_argument_group(title="Backend Initialization")
    group.add_argument("--backend-configs", nargs="*", dest="backend_configs",
                       help="alternative backend configuration files")
    group.add_argument("--compress", action="store_true",
                       help="zlib compress each netcdf file")
    group.add_argument("--fix-awips", action="store_true",
                       help="modify NetCDF output to work with the old/broken AWIPS NetCDF library")
    group = parser.add_argument_group(title="Backend Output Creation")
    # group.add_argument("--ncml-template",
    #                    help="alternative AWIPS ncml template file from what is configured")
    group.add_argument("--tiles", dest="tile_count", nargs=2, type=int, default=[1, 1],
                       help="Number of tiles to produce in Y (rows) and X (cols) direction respectively")
    group.add_argument("--tile-size", dest="tile_size", nargs=2, type=int, default=None,
                       help="Specify how many pixels are in each tile (overrides '--tiles')")
    group.add_argument('--tile-offset', nargs=2, default=(0, 0),
                       help="Start counting tiles from this offset ('row_offset col_offset')")
    group.add_argument("--output-pattern", default=DEFAULT_OUTPUT_PATTERN,
                       help="output filenaming pattern")
    group.add_argument("--source-name", default='SSEC',
                       help="specify processing source name used in attributes and filename (default 'SSEC')")
    group.add_argument("--sector-id", required=True,
                       help="specify name for sector/region used in attributes and filename (example 'LCC')")
    return ["Backend Initialization", "Backend Output Creation"]


def main():
    from polar2grid.core.script_utils import create_basic_parser, create_exc_handler, setup_logging
    from polar2grid.core.containers import GriddedScene, GriddedProduct
    parser = create_basic_parser(description="Create SCMI AWIPS compatible NetCDF files")
    subgroup_titles = add_backend_argument_groups(parser)
    parser.add_argument("--scene", required=True, help="JSON SwathScene filename to be remapped")
    parser.add_argument("-p", "--products", nargs="*", default=None,
                        help="Specify only certain products from the provided scene")
    global_keywords = ("keep_intermediate", "overwrite_existing", "exit_on_error")
    args = parser.parse_args(subgroup_titles=subgroup_titles, global_keywords=global_keywords)

    # Logs are renamed once data the provided start date is known
    levels = [logging.ERROR, logging.WARN, logging.INFO, logging.DEBUG]
    setup_logging(console_level=levels[min(3, args.verbosity)], log_filename=args.log_fn)
    sys.excepthook = create_exc_handler(LOG.name)

    LOG.info("Loading scene or product...")
    gridded_scene = GriddedScene.load(args.scene)
    if args.products and isinstance(gridded_scene, GriddedScene):
        for k in gridded_scene.keys():
            if k not in args.products:
                del gridded_scene[k]

    LOG.info("Initializing backend...")
    backend = Backend(**args.subgroup_args["Backend Initialization"])
    if isinstance(gridded_scene, GriddedScene):
        backend.create_output_from_scene(gridded_scene, **args.subgroup_args["Backend Output Creation"])
    elif isinstance(gridded_scene, GriddedProduct):
        backend.create_output_from_product(gridded_scene, **args.subgroup_args["Backend Output Creation"])
    else:
        raise ValueError("Unknown Polar2Grid object provided")

if __name__ == '__main__':
    sys.exit(main())