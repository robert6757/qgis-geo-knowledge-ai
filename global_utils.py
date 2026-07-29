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

import os
import requests

from qgis.core import QgsProject, Qgis, QgsMapLayer, QgsApplication

from .global_defs import AI_SERVER_DOMAIN


def upload_image_to_server(image_path, chat_id):
    """
    Upload an image file to the AI server and return the remote URL.

    Args:
        image_path: Local file path of the image (PNG) to upload.
        chat_id: The current chat session id used as a server-side grouping key.

    Returns:
        The remote image URL string returned by the server, or None if the
        upload failed for any reason.
    """
    try:
        upload_url = f"{AI_SERVER_DOMAIN}/ai/v1/attachment/image"
        image_name = os.path.basename(image_path)

        with open(image_path, 'rb') as f:
            image_data = f.read()

        params = {
            "chat_id": chat_id,
            "image_name": image_name
        }
        headers = {
            "Content-Type": "image/png"
        }
        response = requests.post(
            upload_url,
            params=params,
            data=image_data,
            headers=headers,
            timeout=10
        )

        if response.status_code == 200:
            return response.text.strip()
    except Exception as e:
        print(f"Failed to upload image: {str(e)}")
    return None


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

    # qgis version
    workspace_info["version"] = Qgis.version()

    # get working project
    project = QgsProject.instance()

    # CRS part
    project_crs = project.crs()
    workspace_info["CRSAuthId"] = project_crs.authid()

    # get map canvas parameters.
    map_canvas = iface.mapCanvas()
    canvas_extent = map_canvas.extent()
    workspace_info["MapCanvasExtent"] = [
        f"{canvas_extent.xMinimum():.6f}",
        f"{canvas_extent.yMinimum():.6f}",
        f"{canvas_extent.xMaximum():.6f}",
        f"{canvas_extent.yMaximum():.6f}"]

    # enumerate layers in project.
    layers_info = []
    layer_tree_root = project.layerTreeRoot()
    layers = project.mapLayers().values()
    for layer in layers:
        node = layer_tree_root.findLayer(layer.id())
        visible = node.isVisible() if node else False

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
            if provider:
                layer_info["raster_width"] = provider.xSize()
                layer_info["raster_height"] = provider.ySize()

                extent = provider.extent()
                layer_info["raster_extent"] = [
                    f"{extent.xMinimum():.6f}",
                    f"{extent.yMinimum():.6f}",
                    f"{extent.xMaximum():.6f}",
                    f"{extent.yMaximum():.6f}"
                ]

                if provider.xSize() > 0 and provider.ySize() > 0:
                    pixel_size_x = (extent.xMaximum() - extent.xMinimum()) / provider.xSize()
                    pixel_size_y = (extent.yMaximum() - extent.yMinimum()) / provider.ySize()
                    layer_info["pixel_size"] = [
                        f"{pixel_size_x:.6f}",
                        f"{pixel_size_y:.6f}"
                    ]

                layer_info["origin"] = [
                    f"{extent.xMinimum():.6f}",
                    f"{extent.yMaximum():.6f}"
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
                    if stats:
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