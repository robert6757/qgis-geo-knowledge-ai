# -*- coding: utf-8 -*-
"""
/***************************************************************************
                             Global Utility Functions
                              -------------------
        begin                : 2026-07-27
        copyright            : (C) 2026 by phoenix-gis
        email                : phoenixgis@sina.com
        website              : phoenix-gis.cn
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""

import datetime as dt
import math
from urllib.parse import quote

from qgis.PyQt.QtNetwork import QNetworkProxy
from qgis.core import QgsProject, Qgis, QgsMapLayer, QgsApplication, QgsNetworkAccessManager, QgsSettings

from .global_defs import CLIENT_TOKEN_TAG


def get_auth_headers():
    """
    Return an Authorization header with the stored client token if available.

    Returns:
        A dict containing ``Authorization: bearer <token>`` when a token is
        configured; otherwise an empty dict.
    """
    token = QgsSettings().value(CLIENT_TOKEN_TAG, "")
    if token:
        return {"Authorization": f"bearer {token}"}
    return {}


def get_workspace_info(iface, include_processing_tools=True):
    """
    Collect current QGIS workspace information.
    
    Args:
        iface: The QGIS interface object.
        include_processing_tools: Whether to include the list of available processing tools.
        
    Returns:
        A dictionary containing workspace information.
    """
    workspace_info = {}

    # current system time
    workspace_info["ClientTime"] = dt.datetime.now().isoformat()

    # qgis version
    workspace_info["version"] = Qgis.version()

    # get working project
    project = QgsProject.instance()

    # CRS part
    project_crs = project.crs()
    workspace_info["CRSAuthId"] = project_crs.authid()

    def _format_extent(value, max_reasonable=1e15):
        """Return a formatted float if finite and within a sane coordinate range, otherwise None."""
        if not math.isfinite(value) or abs(value) >= max_reasonable:
            return None
        return f"{value:.6f}"

    # get map canvas parameters.
    map_canvas = iface.mapCanvas()
    canvas_extent = map_canvas.extent()
    workspace_info["MapCanvasExtent"] = [
        _format_extent(canvas_extent.xMinimum()),
        _format_extent(canvas_extent.yMinimum()),
        _format_extent(canvas_extent.xMaximum()),
        _format_extent(canvas_extent.yMaximum())
    ]

    # enumerate layers in project.
    layers_info = []
    layer_tree_root = project.layerTreeRoot()
    layers = project.mapLayers().values()
    for layer in layers:
        node = layer_tree_root.findLayer(layer.id())
        visible = node.isVisible() if node is not None else False

        layer_info = {}
        layer_info["name"] = f"{layer.name()}"
        layer_info["type"] = f"{layer.type().name}"
        layer_info["visible"] = visible

        crs = layer.crs()
        layer_info["CRSAuthId"] = f"{crs.authid()}"

        # get fields data in vector data.
        if layer.type() == QgsMapLayer.LayerType.VectorLayer:
            fields_info = []
            fields = layer.fields()
            for field in fields:
                field_info = {
                    "name": field.name(),
                    "type": field.typeName(),
                    "length": field.length(),
                    "precision": field.precision()
                }
                fields_info.append(field_info)
            layer_info["fields"] = fields_info

        # get bands data in raster data.
        elif layer.type() == QgsMapLayer.LayerType.RasterLayer:
            bands_info = []
            provider = layer.dataProvider()
            if provider is not None:
                layer_info["raster_width"] = provider.xSize()
                layer_info["raster_height"] = provider.ySize()

                extent = provider.extent()
                extent_valid = (
                    math.isfinite(extent.xMinimum()) and
                    math.isfinite(extent.yMinimum()) and
                    math.isfinite(extent.xMaximum()) and
                    math.isfinite(extent.yMaximum())
                )

                layer_info["raster_extent"] = [
                    _format_extent(extent.xMinimum()),
                    _format_extent(extent.yMinimum()),
                    _format_extent(extent.xMaximum()),
                    _format_extent(extent.yMaximum())
                ]

                if extent_valid and provider.xSize() > 0 and provider.ySize() > 0:
                    pixel_size_x = (extent.xMaximum() - extent.xMinimum()) / provider.xSize()
                    pixel_size_y = (extent.yMaximum() - extent.yMinimum()) / provider.ySize()
                    layer_info["pixel_size"] = [
                        f"{pixel_size_x:.6f}",
                        f"{pixel_size_y:.6f}"
                    ]

                layer_info["origin"] = [
                    _format_extent(extent.xMinimum()),
                    _format_extent(extent.yMaximum())
                ]

                band_count = provider.bandCount()
                for band in range(1, band_count + 1):
                    band_info = {
                        "band_number": band,
                        "band_name": f"Band {band}",
                        "data_type": provider.dataType(band),
                    }
                    color_interp = provider.colorInterpretation(band)
                    if hasattr(color_interp, 'name'):
                        band_info["color_interpretation"] = color_interp.name

                    customSampleSize = int(max(provider.xSize(), provider.ySize()) / 256)
                    stats = provider.bandStatistics(band, sampleSize=customSampleSize)
                    if stats is not None:
                        band_info["minimum"] = stats.minimumValue
                        band_info["maximum"] = stats.maximumValue
                        band_info["mean"] = stats.mean
                        band_info["std_dev"] = stats.stdDev

                    bands_info.append(band_info)

                layer_info["bands"] = bands_info

        layers_info.append(layer_info)
    workspace_info["Layers"] = layers_info

    # get Processing Tools
    if include_processing_tools:
        processing_tools = []
        registry = QgsApplication.processingRegistry()
        providers = registry.providers()
        for provider in providers:
            algorithm_ids = []
            for algorithm in provider.algorithms():
                algorithm_ids.append(algorithm.id())
            processing_tools.append({
                'name': provider.name(),
                'algorithms': algorithm_ids
            })
        workspace_info["ProcessingTools"] = processing_tools

    return workspace_info

def get_qgis_proxies():
    """
    Converts the proxy settings from QGIS network configuration into a `proxies` parameter for `requests`;returns `None` if no proxy is configured.
    """
    p = QgsNetworkAccessManager.instance().fallbackProxy()
    t = p.type()
    if t == QNetworkProxy.ProxyType.HttpProxy:
        scheme = "http"
    else:
        return None
    auth = f"{quote(p.user())}:{quote(p.password())}@" if p.user() else ""
    url = f"{scheme}://{auth}{p.hostName()}:{p.port()}"
    return {"http": url, "https": url}