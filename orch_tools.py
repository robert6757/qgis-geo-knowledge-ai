# -*- coding: utf-8 -*-
"""
/***************************************************************************
                                 Define Tools for Orchestration
  Define all tools in the subtask for orchestration.
                              -------------------
        begin                : 2026-04-16
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
import sys
import io
import os
import re
import json
import uuid
import requests
import zipfile
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse, parse_qs
from qgis.PyQt.QtCore import QObject, pyqtSignal, Qt, QCoreApplication, QVariant, QSize
from qgis.PyQt.QtGui import QColor
from qgis.core import (
    QgsProject,
    QgsVectorLayer,
    QgsRasterLayer,
    QgsMapLayer,
    QgsFeatureRequest,
    QgsApplication,
    QgsProcessingFeedback,
    QgsRectangle,
    QgsLayerTreeLayer,
    QgsSettings,
    QgsPrintLayout,
    QgsLayoutExporter,
    QgsLayoutItemMap,
    QgsLayoutPoint,
    QgsLayoutSize,
    QgsLayoutItemLabel,
    QgsLayoutItemLegend,
    QgsLayoutItemScaleBar,
    QgsLayoutItemPicture,
    QgsLayoutFrame,
    QgsLayoutItemAttributeTable,
    QgsUnitTypes,
)
from qgis import processing

from .code_exec_utils import get_code_execution_class
from .compat import *
from .orch_tools_osm import OverpassTool
from .orch_tools_qml import QmlStyleTool
from .orch_tools_stac import StacTool
from .global_defs import *
from .global_utils import get_qgis_proxies, get_auth_headers

SUPPORTED_TOOLS = ["qgis_add_vector_layer", "qgis_add_raster_layer", "qgis_get_layers", "qgis_zoom_to_layer",
                   "qgis_remove_layer", "qgis_query_features_from_vector_layer", "qgis_execute_code",
                   "qgis_execute_algorithm", "qgis_add_osm_layer", "qgis_add_google_layer",
                   "qgis_query_raster_values_by_bbox", "qgis_get_algorithm_help", "qgis_get_pyqgis_class_help",
                   "qgis_query_and_show_osm_objects", "qgis_search_and_show_place", "qgis_get_qml_template",
                   "qgis_reorder_layers", "qgis_capture_canvas_screenshot", "qgis_set_layers_visibility",
                   "qgis_configure_aws_credentials", "qgis_search_stac_items", "qgis_load_stac_asset_to_map",
                   "create_folder", "zip_files", "unzip_files", "qgis_list_layouts", "qgis_create_layout",
                   "qgis_capture_layout_screenshot", "qgis_remove_layout", "qgis_get_layout_info",
                   "qgis_export_layout", "qgis_add_layout_map", "qgis_add_layout_label", "qgis_add_layout_legend",
                   "qgis_add_layout_scalebar", "qgis_add_layout_picture", "qgis_add_layout_table", "qgis_move_layout_item"]

class OrchToolExecutor(QObject):
    """The tool executor uses a signal-slot mechanism to execute tools in the GUI thread."""

    execute_requested = pyqtSignal(str, dict)  # tool_name, arguments
    execution_completed = pyqtSignal(str)  # result
    execution_error = pyqtSignal(str)  # error message

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.overpass_tool = OverpassTool()
        self.qml_tool = QmlStyleTool()
        self.stac_tool = StacTool()
        self.execute_requested.connect(self._on_execute_requested, QueuedConnection)

    def _on_execute_requested(self, tool_name: str, arguments: dict):
        """Slot functions: Execute tools in the GUI thread."""
        try:
            result = self._execute_tool_impl(tool_name, arguments)
            self.execution_completed.emit(result)
        except Exception as e:
            self.execution_error.emit(str(e))

    def _execute_tool_impl(self, tool_name: str, arguments: dict) -> str:
        """
            Execute orchestration tool in GUI thread.

            Args:
                tool_name: tool name
                arguments: tool arguments

            Returns:
                execute tool result.
            """
        if tool_name == "qgis_add_vector_layer":
            # Add a vector layer to the project
            path = arguments.get("path", "")
            name = arguments.get("name", "")
            provider = arguments.get("provider", "ogr")
            # Specify the position to insert (e.g., -1 for the bottom, 0 for the top, 1 for the second position, and so on).
            position = arguments.get("position", 0)
            if not name:
                name = os.path.basename(path)

            # Create the layer
            layer = QgsVectorLayer(path, name, provider)

            if not layer.isValid():
                raise Exception(f"Layer is not valid: {path}")

            QgsProject.instance().addMapLayer(layer, False)

            # Add the layer to the specified position.
            root = QgsProject.instance().layerTreeRoot()
            root.insertLayer(position, layer)

            return json.dumps({
                "id": layer.id(),
                "name": layer.name(),
                "type": self._get_layer_type(layer),
                "feature_count": layer.featureCount()
            }, ensure_ascii=False)

        elif tool_name == "qgis_add_raster_layer":
            # Add a raster layer to the project
            path = arguments.get("path", "")
            name = arguments.get("name", "")
            provider = arguments.get("provider", "ogr")
            # Specify the position to insert (e.g., -1 for the bottom, 0 for the top, 1 for the second position, and so on).
            position = arguments.get("position", 0)
            if not name:
                name = os.path.basename(path)

            # Create the layer
            layer = QgsRasterLayer(path, name, provider)

            if not layer.isValid():
                raise Exception(f"Layer is not valid: {path}")

            # Add to project
            QgsProject.instance().addMapLayer(layer, False)

            # Add the layer to the specified position.
            root = QgsProject.instance().layerTreeRoot()
            root.insertLayer(position, layer)

            return json.dumps({
                "id": layer.id(),
                "name": layer.name(),
                "type": "raster",
                "width": layer.width(),
                "height": layer.height()
            }, ensure_ascii=False)

        elif tool_name == "qgis_get_layers":
            # Get all layers in the project
            project = QgsProject.instance()
            layers = []

            for layer_id, layer in project.mapLayers().items():
                layer_tree_node = project.layerTreeRoot().findLayer(layer_id)
                layer_info = {
                    "id": layer_id,
                    "name": layer.name(),
                    "type": self._get_layer_type(layer),
                    "visible": layer_tree_node.isVisible() if layer_tree_node is not None else False
                }

                # Add type-specific information
                if layer.type() == QgsMapLayer.LayerType.VectorLayer:
                    layer_info.update({
                        "feature_count": layer.featureCount(),
                        "geometry_type": layer.geometryType()
                    })
                elif layer.type() == QgsMapLayer.LayerType.RasterLayer:
                    layer_info.update({
                        "width": layer.width(),
                        "height": layer.height()
                    })

                layers.append(layer_info)

            return json.dumps(layers, ensure_ascii=False)

        elif tool_name == "qgis_zoom_to_layer":
            # Zoom to a layer's extent
            layer_id = arguments.get("layer_id", "")
            if not layer_id:
                raise Exception({"error_msg": "No layer id provided"})

            project = QgsProject.instance()

            if layer_id in project.mapLayers():
                layer = project.mapLayer(layer_id)
                self.iface.setActiveLayer(layer)
                self.iface.zoomToActiveLayer()
                return json.dumps({"zoomed_to": layer_id}, ensure_ascii=False)
            else:
                raise Exception({"error_msg": f"Layer {layer_id} is not found"})

        elif tool_name == "qgis_remove_layer":
            # Remove a layer from the project
            layer_id = arguments.get("layer_id", "")
            if not layer_id:
                raise Exception({"error_msg": "No layer id provided"})

            project = QgsProject.instance()

            if layer_id in project.mapLayers():
                project.removeMapLayer(layer_id)
                return json.dumps({"removed": layer_id}, ensure_ascii=False)
            else:
                raise Exception({"error_msg": f"Layer {layer_id} is not found"})

        elif tool_name == "qgis_query_features_from_vector_layer":
            # Use a query statement to query vector layer features.
            layer_id = arguments.get("layer_id", "")
            statement = arguments.get("statement", "")
            max_feature_count = arguments.get("max_feature_count", 5)
            if not layer_id:
                raise Exception({"error_msg": "No layer id provided"})

            project = QgsProject.instance()

            if layer_id in project.mapLayers():
                layer = project.mapLayer(layer_id)

                if layer.type() != QgsMapLayer.LayerType.VectorLayer:
                    raise Exception(f"Layer is not a vector layer: {layer_id}")

                features = []
                request = QgsFeatureRequest()
                if statement:
                    request.setFilterExpression(statement)
                # Must constrain the maximum number of features to return.
                request.setLimit(max_feature_count)
                for i, feature in enumerate(layer.getFeatures(request)):
                    # Extract attributes
                    attrs = {}
                    for field in layer.fields():
                        attrs[field.name()] = self._convert_qvariant(feature.attribute(field.name()))

                    # Extract geometry if available
                    geom = None
                    if feature.hasGeometry():
                        geom = {
                            "type": feature.geometry().type(),
                            "wkt": feature.geometry().asWkt(precision=4)
                        }

                    features.append({
                        "id": self._convert_qvariant(feature.id()),
                        "attributes": attrs,
                        "geometry": geom
                    })

                return json.dumps({
                    "layer_id": layer_id,
                    "layer_feature_count": layer.featureCount(),
                    "features": features,
                    "fields": [field.name() for field in layer.fields()]
                }, ensure_ascii=False)
            else:
                raise Exception({"error_msg": f"Layer {layer_id} is not found"})

        elif tool_name == "qgis_execute_code":
            # Execute PyQGIS code
            CodeExecution = get_code_execution_class()
            if CodeExecution is None:
                raise Exception({"error_msg": "Code execution module is not available"})

            code = arguments.get("code", "")

            # Replace any [AUTH_TOKEN:xxx] / [USER_PARAM:xxx] placeholders in the code
            # with locally saved values.
            code = self._resolve_placeholder(code)

            code_exec = CodeExecution(
                code=code,
                parent_widget=self,
                iface=self.iface
            )

            result_container = {"result": None, "error_msg": None}

            def on_finish(execution_result):
                result_container["result"] = execution_result
            def on_error(error_type, error_msg):
                result_container["error_type"] = error_type
                result_container["error_msg"] = error_msg

            code_exec.task_finished.connect(on_finish)
            code_exec.task_error.connect(on_error)

            code_exec.run()

            while result_container["result"] is None and result_container["error_msg"] is None:
                QCoreApplication.processEvents()

            if result_container["error_msg"] is not None:
                raise Exception({"error_msg": result_container["error_msg"]})

            return json.dumps({"result": result_container["result"]}, ensure_ascii=False)

        elif tool_name == "qgis_execute_algorithm":
            # Execution Algorithm Tools
            algo_id = arguments.get("algo_id", "")
            algo_parameters = arguments.get("algo_parameters", "{}")
            algo_parameters_obj = json.loads(algo_parameters)

            # Replace any [AUTH_TOKEN:xxx] / [USER_PARAM:xxx] placeholders in parameter
            # values with locally saved values.
            for key, value in list(algo_parameters_obj.items()):
                if not isinstance(value, str):
                    continue
                algo_parameters_obj[key] = self._resolve_placeholder(value)

            # use metadata of processing to find the real algorithm id.
            processing_metadata = QgsApplication.processingRegistry().algorithmById(algo_id)

            # try to find C++(native) and Python(qgis) processing.
            if processing_metadata is None and algo_id.startswith("native:"):
                _algo_id = algo_id.replace("native:", "qgis:")
                processing_metadata = QgsApplication.processingRegistry().algorithmById(_algo_id)
            if processing_metadata is None and algo_id.startswith("qgis:"):
                _algo_id = algo_id.replace("qgis:", "native:")
                processing_metadata = QgsApplication.processingRegistry().algorithmById(_algo_id)
            if processing_metadata is None and algo_id.startswith("saga:"):
                _algo_id = algo_id.replace("saga:", "sagang:")
                processing_metadata = QgsApplication.processingRegistry().algorithmById(_algo_id)

            # Fail to find any processing.
            if processing_metadata is None:
                raise Exception({"error_msg": f"Cannot find algorithm: {algo_id}"})

            feedback = QgsProcessingFeedback()
            result = processing.run(processing_metadata.id(), algo_parameters_obj, feedback=feedback)

            if not result:
                raise Exception({"error_msg": f"Failed to execute algorithm: {processing_metadata.id()}"})

            serializable_result = {}
            for key, value in result.items():
                if isinstance(value, QgsMapLayer):
                    # If the output is a layer object (e.g., a memory layer), extract the layer's basic properties.
                    serializable_result[key] = {
                        "layer_id": value.id(),
                        "name": value.name(),
                        "type": self._get_layer_type(value)
                    }
                    QgsProject.instance().addMapLayer(value, False)
                    QgsProject.instance().layerTreeRoot().insertLayer(0, value)
                else:
                    try:
                        json.dumps(value)
                        serializable_result[key] = value
                    except TypeError:
                        serializable_result[key] = str(value)

            return json.dumps({"result": serializable_result, "feedback": feedback.textLog()}, ensure_ascii=False)
        elif tool_name == "qgis_add_osm_layer":
            # Add OSM XYZ tile layer to project
            name = arguments.get("name", "OpenStreetMap")
            url = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"

            # QGIS XYZ Layer URI Format
            uri = f"type=xyz&url={url}&zmax=19&zmin=0"

            layer = QgsRasterLayer(uri, name, "wms")

            if not layer.isValid():
                raise Exception({"error_msg": f"Failed to create OSM layer"})

            QgsProject.instance().addMapLayer(layer, False)

            root = QgsProject.instance().layerTreeRoot()
            # add layer to the bottom
            root.insertLayer(-1, layer)

            return json.dumps({
                "status": "success",
                "message": "OpenStreetMap layer successfully loaded to map.",
                "layer_id": layer.id(),
                "layer_name": layer.name(),
                "layer_type": "raster"
            }, ensure_ascii=False)

        elif tool_name == "qgis_add_google_layer":
            layer_type = arguments.get("layer_type", "m")
            name = arguments.get("name", "")

            layer_type_names = {
                "m": "Roadmap",
                "t": "Topographic Map",
                "p": "Topographic Map with Labels",
                "s": "Satellite Map",
                "y": "Satellite Map with Labels",
                "h": "Only Labels",
            }
            if not name:
                name = layer_type_names.get(layer_type, f"Google ({layer_type})")

            tile_url = f"https://mt0.google.com/vt?lyrs%3D{layer_type}%26x%3D{{x}}%26y%3D{{y}}%26z%3D{{z}}"
            uri = f"type=xyz&url={tile_url}%26zmax%3D19%26zmin%3D0"

            layer = QgsRasterLayer(uri, name, "wms")

            if not layer.isValid():
                raise Exception({"error_msg": f"Failed to create Google layer with type: {layer_type}"})

            QgsProject.instance().addMapLayer(layer, False)

            root = QgsProject.instance().layerTreeRoot()
            # add layer to the bottom
            root.insertLayer(-1, layer)

            return json.dumps({
                "status": "success",
                "message": "Google layer successfully loaded to map.",
                "layer_id": layer.id(),
                "layer_name": layer.name(),
                "layer_type": "raster"
            }, ensure_ascii=False)

        elif tool_name == "qgis_get_algorithm_help":
            # Get help information for one or more processing algorithms in batch.
            alg_ids_json = arguments.get("alg_ids", [])
            alg_ids = alg_ids_json

            if not alg_ids:
                raise Exception({"error_msg": "No algorithm IDs provided"})

            help_results = {}
            for alg_id in alg_ids:
                old_stdout = sys.stdout
                sys.stdout = io.StringIO()
                try:
                    processing.algorithmHelp(alg_id)
                    help_results[alg_id] = sys.stdout.getvalue()
                finally:
                    sys.stdout = old_stdout
            return json.dumps(help_results, ensure_ascii=False)

        elif tool_name == "qgis_get_pyqgis_class_help":
            # Get help information for one or more PyQGIS classes in batch.
            class_names = arguments.get("class_names", [])
            if not class_names:
                raise Exception({"error_msg": "No PyQGIS class names provided"})

            import qgis.core, qgis.gui, qgis.analysis
            namespaces = [qgis.core, qgis.gui, qgis.analysis, sys.modules.get("__main__", {})]

            help_results = {}
            for class_name in class_names:
                cls_obj = None
                for ns in namespaces:
                    if hasattr(ns, class_name):
                        cls_obj = getattr(ns, class_name)
                        break
                
                if cls_obj is None:
                    help_results[class_name] = f"Class {class_name} not found in PyQGIS namespaces."
                    continue

                old_stdout = sys.stdout
                sys.stdout = io.StringIO()
                try:
                    help(cls_obj)
                    help_results[class_name] = sys.stdout.getvalue()
                finally:
                    sys.stdout = old_stdout
            return json.dumps(help_results, ensure_ascii=False)

        elif tool_name == "qgis_query_raster_values_by_bbox":
            # Query raster layer values by bounding box (minX, minY, maxX, maxY) and band number
            layer_id = arguments.get("layer_id", "")
            if not layer_id:
                raise Exception({"error_msg": "No layer id provided"})

            min_x = arguments.get("minX", None)
            min_y = arguments.get("minY", None)
            max_x = arguments.get("maxX", None)
            max_y = arguments.get("maxY", None)
            band = arguments.get("band", 1)

            if min_x is None or min_y is None or max_x is None or max_y is None:
                raise Exception({"error_msg": "No minX/minY/maxX/maxY coordinates provided"})

            project = QgsProject.instance()

            if layer_id not in project.mapLayers():
                raise Exception({"error_msg": f"Layer {layer_id} is not found"})

            layer = project.mapLayer(layer_id)

            if layer.type() != QgsMapLayer.LayerType.RasterLayer:
                raise Exception({"error_msg": f"Layer is not a raster layer: {layer_id}"})

            # Get the data provider
            provider = layer.dataProvider()
            if provider is None:
                raise Exception({"error_msg": "Failed to get data provider from raster layer"})

            # Calculate pixel coordinates from geographic coordinates
            pixel_size_x = layer.rasterUnitsPerPixelX()
            pixel_size_y = layer.rasterUnitsPerPixelY()
            extent = layer.extent()

            col_start = int((min_x - extent.xMinimum()) / pixel_size_x)
            col_end = int((max_x - extent.xMinimum()) / pixel_size_x)
            row_start = int((extent.yMaximum() - max_y) / pixel_size_y)
            row_end = int((extent.yMaximum() - min_y) / pixel_size_y)

            # Ensure col_start <= col_end and row_start <= row_end
            if col_start > col_end:
                col_start, col_end = col_end, col_start
            if row_start > row_end:
                row_start, row_end = row_end, row_start

            # Clamp to raster dimensions
            if col_start < 0:
                col_start = 0
            if row_start < 0:
                row_start = 0
            if col_end >= layer.width():
                col_end = layer.width() - 1
            if row_end >= layer.height():
                row_end = layer.height() - 1

            n_cols = col_end - col_start + 1
            n_rows = row_end - row_start + 1

            if n_cols <= 0 or n_rows <= 0:
                raise Exception({"error_msg": "Query extent is completely outside raster extent"})

            # Read block data using QgsRasterDataProvider.block()
            block = provider.block(int(band), layer.extent(), layer.width(), layer.height())

            if block is None or not block.isValid():
                raise Exception({"error_msg": "Failed to read raster block"})

            max_pixels = 10000
            total_pixels = n_cols * n_rows
            downsampled = False
            original_n_cols = n_cols
            original_n_rows = n_rows

            if total_pixels <= max_pixels:
                # Raw extraction - pixel count within limits
                values = []
                for row in range(row_start, row_end + 1):
                    row_values = []
                    for col in range(col_start, col_end + 1):
                        val = block.value(row, col)
                        if val is None:
                            row_values.append(None)
                        else:
                            row_values.append(float(val))
                    values.append(row_values)
            else:
                # Downsample to fit within max_pixels
                downsampled = True
                scale = (max_pixels / total_pixels) ** 0.5
                new_n_cols = max(1, int(n_cols * scale))
                new_n_rows = max(1, int(n_rows * scale))

                step_x = n_cols / new_n_cols
                step_y = n_rows / new_n_rows

                values = []
                for out_row in range(new_n_rows):
                    row_values = []
                    src_row_start = row_start + int(out_row * step_y)
                    src_row_end = row_start + int((out_row + 1) * step_y)
                    if src_row_end > row_end + 1:
                        src_row_end = row_end + 1
                    if src_row_start >= src_row_end:
                        src_row_start = src_row_end - 1

                    for out_col in range(new_n_cols):
                        src_col_start = col_start + int(out_col * step_x)
                        src_col_end = col_start + int((out_col + 1) * step_x)
                        if src_col_end > col_end + 1:
                            src_col_end = col_end + 1
                        if src_col_start >= src_col_end:
                            src_col_start = src_col_end - 1

                        # Block Averaging
                        total = 0.0
                        count = 0
                        for r in range(src_row_start, src_row_end):
                            for c in range(src_col_start, src_col_end):
                                val = block.value(r, c)
                                if val is not None:
                                    total += float(val)
                                    count += 1
                        if count > 0:
                            row_values.append(round(total / count, 6))
                        else:
                            row_values.append(None)
                    values.append(row_values)

                n_cols = new_n_cols
                n_rows = new_n_rows

            result = {
                "layer_id": layer_id,
                "extent": {
                    "minX": min_x,
                    "minY": min_y,
                    "maxX": max_x,
                    "maxY": max_y
                },
                "band": int(band),
                "pixel_range": {
                    "col_start": col_start,
                    "col_end": col_end,
                    "row_start": row_start,
                    "row_end": row_end
                },
                "n_cols": n_cols,
                "n_rows": n_rows,
                "values": values
            }

            if downsampled:
                result["downsampled"] = True
                result["original_n_cols"] = original_n_cols
                result["original_n_rows"] = original_n_rows

            return json.dumps(result, ensure_ascii=False)

        elif tool_name == "qgis_query_and_show_osm_objects":
            # Query OSM objects using Overpass API
            key = arguments.get("key", "")
            if not key:
                raise Exception({"error_msg": "OSM key is required"})
            
            value = arguments.get("value")
            area = arguments.get("area")
            osm_types = arguments.get("osm_types")
            if isinstance(osm_types, str):
                osm_types = json.loads(osm_types)
                
            around_distance = arguments.get("around_distance")
            bbox = arguments.get("bbox")
            base_url = arguments.get("base_url", 'https://overpass-api.de/api/')
            
            # Generate output file path with timestamp
            gSetting = QgsSettings()
            temp_dir = gSetting.value(TEMP_FOLDER_TAG, "")
            if not temp_dir:
                temp_dir = QStandardPaths.writableLocation(TempLocation)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = os.path.join(temp_dir, f"osm-query-{timestamp}.osm")
            
            try:
                self.overpass_tool.query_osm_objects(
                    key=key,
                    value=value,
                    area=area,
                    bbox=bbox,
                    osm_types=osm_types,
                    around_distance=around_distance,
                    output_path=output_path,
                    base_url=base_url
                )
                self.overpass_tool.load_osm_to_map(output_path, f"OSM_{key}_{value}")
            except Exception as e:
                raise Exception({"error_msg": str(e)})
            
            result = {"status": "success", "message": "OSM data successfully loaded to map."}
            return json.dumps(result, ensure_ascii=False)

        elif tool_name == "qgis_search_and_show_place":
            # Search for a place name using Nominatim and display results on the map.
            place_name = arguments.get("place_name", "")
            if not place_name:
                raise Exception({"error_msg": "place_name is required"})

            limit = arguments.get("limit", 5)
            layer_name = arguments.get("layer_name", "Place Search Results")
            base_url = arguments.get("base_url", 'https://nominatim.openstreetmap.org/search')

            # Generate output file path with timestamp
            gSetting = QgsSettings()
            temp_dir = gSetting.value(TEMP_FOLDER_TAG, "")
            if not temp_dir:
                temp_dir = QStandardPaths.writableLocation(TempLocation)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = os.path.join(temp_dir, f"place-search-{timestamp}.json")

            try:
                self.overpass_tool.search_place(
                    place_name=place_name,
                    output_path=output_path,
                    limit=limit,
                    base_url=base_url
                )
                self.overpass_tool.load_place_json_to_map(output_path, layer_name)
            except Exception as e:
                raise Exception({"error_msg": str(e)})

            # Count results for the response
            result_count = 0
            try:
                with open(output_path, 'r', encoding='utf8') as f:
                    place_data = json.load(f)
                    if isinstance(place_data, list):
                        result_count = len(place_data)
            except Exception:
                result_count = 0

            return json.dumps({
                "status": "success",
                "message": f"Place search results for '{place_name}' loaded to map.",
                "place_name": place_name,
                "result_count": result_count,
                "layer_name": layer_name
            }, ensure_ascii=False)

        elif tool_name == "qgis_get_qml_template":
            style_type = arguments.get("style_type")
            try:
                template = self.qml_tool.get_qml_template(style_type)
                result = {"status": "success", "template": template}
            except Exception as e:
                raise Exception({"error_msg": str(e)})
            return json.dumps(result, ensure_ascii=False)

        elif tool_name == "qgis_reorder_layers":
            # Reorder layers in the project's layer tree root.
            # layer_ids: list of layer ids in the desired top-to-bottom order.
            layer_ids = arguments.get("layer_ids", [])
            if not layer_ids:
                raise Exception({"error_msg": "No layer_ids provided"})

            project = QgsProject.instance()
            root = project.layerTreeRoot()

            # Collect nodes for the requested layer ids (only direct children of root).
            nodes_to_move = []
            skipped_ids = []
            for layer_id in layer_ids:
                node = root.findLayer(layer_id)
                if node is not None:
                    nodes_to_move.append((node, node.clone()))
                else:
                    skipped_ids.append(layer_id)

            if not nodes_to_move:
                raise Exception({"error_msg": f"None of the layer_ids were found: {layer_ids}"})

            # Insert clones at the top in reverse order so the final order matches layer_ids.
            for original_node, cloned_node in reversed(nodes_to_move):
                root.insertChildNode(0, cloned_node)

            # Remove original nodes after all clones are in place.
            for original_node, _ in nodes_to_move:
                root.removeChildNode(original_node)

            # Build the current top-to-bottom layer order.
            current_order = []
            for child in root.children():
                if isinstance(child, QgsLayerTreeLayer):
                    current_order.append(child.layerId())

            moved_count = len(nodes_to_move)
            message = f"Reordered {moved_count} layer(s)."
            if skipped_ids:
                message += f" Skipped layer ids: {skipped_ids}."

            return json.dumps({
                "status": "success",
                "message": message,
                "moved_count": moved_count,
                "skipped_ids": skipped_ids,
                "layer_order": current_order
                }, ensure_ascii=False)

        elif tool_name == "qgis_set_layers_visibility":
            # Control visibility of layers.
            # layer_ids: list of layer ids.
            # visible: boolean (True to show, False to hide).
            layer_ids = arguments.get("layer_ids", [])
            visible = arguments.get("visible")

            if not layer_ids:
                raise Exception({"error_msg": "No layer_ids provided"})
            if visible is None:
                raise Exception({"error_msg": "Visibility state (visible) not provided"})

            project = QgsProject.instance()
            root = project.layerTreeRoot()

            updated_count = 0
            skipped_ids = []

            for layer_id in layer_ids:
                node = root.findLayer(layer_id)
                if node is not None:
                    node.setItemVisibilityChecked(bool(visible))
                    updated_count += 1
                else:
                    skipped_ids.append(layer_id)

            if updated_count == 0:
                raise Exception({"error_msg": f"None of the layer_ids were found: {layer_ids}"})

            return json.dumps({
                "status": "success",
                "message": f"Updated visibility for {updated_count} layer(s).",
                "updated_count": updated_count,
                "skipped_ids": skipped_ids
            }, ensure_ascii=False)

        elif tool_name == "qgis_configure_aws_credentials":
            # Read AWS credentials from QgsSettings using token names that may
            # include [AUTH_TOKEN:xxx] placeholders, similar
            # to the substitution logic used in qgis_execute_algorithm.
            def _resolve_aws_token_name(token_name, gSetting):
                placeholder_pattern = re.compile(r"\[AUTH_TOKEN:(.*?)\]")
                resolved = token_name
                for param_name in placeholder_pattern.findall(token_name):
                    saved_value = gSetting.value(USER_PARAM_KEYS_TAG + f"/{param_name}", "")
                    if saved_value:
                        resolved = resolved.replace(f"[AUTH_TOKEN:{param_name}]", saved_value)
                return resolved

            gSetting = QgsSettings()
            access_key_id = gSetting.value(
                USER_PARAM_KEYS_TAG + f"/{_resolve_aws_token_name('aws_access_key_id', gSetting)}", "")
            secret_access_key = gSetting.value(
                USER_PARAM_KEYS_TAG + f"/{_resolve_aws_token_name('aws_secret_access_key', gSetting)}", "")
            session_token = gSetting.value(
                USER_PARAM_KEYS_TAG + f"/{_resolve_aws_token_name('aws_session_token', gSetting)}", "")

            if not access_key_id:
                raise Exception({"error_msg": "No access_key_id configured in settings"})
            if not secret_access_key:
                raise Exception({"error_msg": "No secret_access_key configured in settings"})

            self.stac_tool.configure_aws_credentials(
                access_key_id=access_key_id,
                secret_access_key=secret_access_key,
                session_token=session_token or None
            )

            return json.dumps({
                "status": "success",
                "message": "AWS credentials configured for GDAL /vsis3/ access."
            }, ensure_ascii=False)

        elif tool_name == "qgis_search_stac_items":
            collections = arguments.get("collections", [])
            if isinstance(collections, str):
                collections = json.loads(collections)
            bbox = arguments.get("bbox")
            if isinstance(bbox, str):
                bbox = json.loads(bbox)
            datetime_range = arguments.get("datetime_range")
            # Resolve any [USER_PARAM:xxx] / [AUTH_TOKEN:xxx] placeholders before
            # falling back to default values.
            if isinstance(datetime_range, str):
                datetime_range = self._resolve_placeholder(datetime_range)
            if not datetime_range:
                gSetting = QgsSettings()
                datetime_range = (
                    gSetting.value(USER_PARAM_KEYS_TAG + "/STAC_StartDate", "") + "/" +
                    gSetting.value(USER_PARAM_KEYS_TAG + "/STAC_EndDate", "")
                )
            query = arguments.get("query")
            if isinstance(query, str):
                query = json.loads(query)
            limit = arguments.get("limit", 5)
            base_url = arguments.get("base_url", 'https://planetarycomputer.microsoft.com/api/stac/v1')
            target_coverage = arguments.get("target_coverage", 0.95)
            # strategy: single_date, greedy
            strategy = arguments.get("strategy", "single_date")

            # Determine if the selected STAC catalog requires special asset signing.
            signing_provider = ''
            if "planetarycomputer.microsoft.com" in base_url:
                signing_provider = "planetary"

            stac_data = self.stac_tool.search_stac_items_with_coverage(
                collections=collections,
                bbox=bbox,
                datetime_range=datetime_range,
                query=query,
                base_url=base_url,
                target_coverage=target_coverage,
                strategy=strategy,
                max_items=limit
            )

            assets = self.stac_tool.list_stac_assets(stac_data)
            return json.dumps({
                "status": "success",
                "asset_count": len(assets),
                "assets": assets,
                "signing_provider": signing_provider
            }, ensure_ascii=False)

        elif tool_name == "qgis_load_stac_asset_to_map":
            href = arguments.get("href", "")
            if not href:
                raise Exception({"error_msg": "No href provided"})

            layer_name = arguments.get("layer_name", "STAC Asset")
            is_vector = arguments.get("is_vector", False)
            signing_provider = arguments.get("signing_provider", "")
            requester_pays = arguments.get("requester_pays", False)

            # Sign assets when the source catalog requires it.
            if signing_provider == "planetary":
                href = self.stac_tool.sign_planetary_computer_href(href)

            self.stac_tool.load_stac_asset_to_map(href, layer_name, is_vector, requester_pays)
            return json.dumps({
                "status": "success",
                "message": f"STAC asset loaded to map as layer '{layer_name}'."
            }, ensure_ascii=False)

        elif tool_name == "qgis_capture_canvas_screenshot":
            gSetting = QgsSettings()
            # Check if screen capture is allowed
            if gSetting.value(CAPTURE_SCREEN_TAG, 'false').lower() != "true":
                return json.dumps({
                    "status": "error",
                    "message": "Permission denied"
                }, ensure_ascii=False)

            try:
                # 1. save screenshot to temp dir.
                screenshot_path = os.path.join(
                    QStandardPaths.writableLocation(TempLocation),
                    f"qgis-canvas-screenshot-{uuid.uuid4().hex}.png"
                )
                pixmap = self.iface.mapCanvas().grab()
                pixmap.save(screenshot_path)

                screenshot_width = pixmap.width()
                screenshot_height = pixmap.height()

                # 2. upload to server
                upload_url = f"{AI_SERVER_DOMAIN}/ai/v1/attachment/image"
                image_name = os.path.basename(screenshot_path)

                with open(screenshot_path, 'rb') as f:
                    image_data = f.read()

                params = {
                    "image_name": image_name
                }
                headers = {
                    "Content-Type": "image/png"
                }
                headers.update(get_auth_headers())

                response = requests.post(
                    upload_url,
                    params=params,
                    data=image_data,
                    headers=headers,
                    proxies=get_qgis_proxies(),
                    timeout=10
                )

                if response.status_code != 200:
                    raise Exception({"error_msg": f"Failed to upload canvas screen: {image_name}"})

                response_text = response.text.strip()
                if not response_text:
                    raise Exception({"error_msg": f"Server did not return a valid image url: {response_text}"})

                image_url = response_text
            except Exception as e:
                raise Exception({"error_msg": f"Failed to capture canvas screen: {image_name}"})
            finally:
                if 'screenshot_path' in locals() and os.path.exists(screenshot_path):
                    os.remove(screenshot_path)

            return json.dumps({
                "status": "success",
                "image_url": image_url,
                "format": "png",
                "width": screenshot_width,
                "height": screenshot_height
            }, ensure_ascii=False)

        elif tool_name == "create_folder":
            # Create a directory (and parent directories if needed).
            path = arguments.get("path", "")
            if not path:
                raise Exception({"error_msg": "No path provided"})

            normalized_path = os.path.normpath(path)

            try:
                os.makedirs(normalized_path, exist_ok=True)
            except Exception as e:
                raise Exception({"error_msg": f"Failed to create folder {normalized_path}: {str(e)}"})

            return json.dumps({
                "status": "success",
                "path": normalized_path
            }, ensure_ascii=False)

        elif tool_name == "zip_files":
            # Create a zip archive from one or more files/folders.
            source_path = arguments.get("source_path", "")
            output_zip = arguments.get("output_zip", "")
            arcname_prefix = arguments.get("arcname_prefix", "")

            if not output_zip:
                raise Exception({"error_msg": "No output_zip provided"})
            if not source_path:
                raise Exception({"error_msg": "No source_path provided"})

            output_zip = os.path.normpath(output_zip)

            if isinstance(source_path, str):
                source_paths = [source_path]
            elif isinstance(source_path, list):
                source_paths = source_path
            else:
                raise Exception({"error_msg": "source_path must be a string or a list of strings"})

            parent_dir = os.path.dirname(output_zip)
            if parent_dir:
                os.makedirs(parent_dir, exist_ok=True)

            added_count = 0
            skipped_paths = []
            prefix = (arcname_prefix if arcname_prefix else "").replace('\\', '/').strip('/')

            with zipfile.ZipFile(output_zip, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for src in source_paths:
                    src = os.path.normpath(src)
                    if not os.path.exists(src):
                        skipped_paths.append(f"{src} (not found)")
                        continue

                    if os.path.isdir(src):
                        for root_dir, dirs, files in os.walk(src):
                            for file in files:
                                file_path = os.path.join(root_dir, file)
                                rel_path = os.path.relpath(file_path, src).replace('\\', '/')
                                arcname = f"{prefix}/{rel_path}" if prefix else rel_path
                                zipf.write(file_path, arcname)
                                added_count += 1
                    else:
                        rel_path = os.path.basename(src).replace('\\', '/')
                        arcname = f"{prefix}/{rel_path}" if prefix else rel_path
                        zipf.write(src, arcname)
                        added_count += 1

            return json.dumps({
                "status": "success",
                "output_zip": output_zip,
                "added_count": added_count,
                "skipped_paths": skipped_paths
            }, ensure_ascii=False)

        elif tool_name == "unzip_files":
            # Extract a zip archive to a directory.
            zip_path = arguments.get("zip_path", "")
            output_dir = arguments.get("output_dir", "")
            overwrite = arguments.get("overwrite", False)

            if not zip_path:
                raise Exception({"error_msg": "No zip_path provided"})

            zip_path = os.path.normpath(zip_path)
            if not os.path.exists(zip_path):
                raise Exception({"error_msg": f"Zip file not found: {zip_path}"})

            if not output_dir:
                output_dir = os.path.dirname(zip_path) or os.getcwd()
            output_dir = os.path.normpath(output_dir)
            os.makedirs(output_dir, exist_ok=True)

            extracted_count = 0
            output_dir_with_sep = os.path.normpath(output_dir) + os.sep

            with zipfile.ZipFile(zip_path, 'r') as zipf:
                for member in zipf.namelist():
                    target_path = os.path.normpath(os.path.join(output_dir, member))
                    if not target_path.startswith(output_dir_with_sep):
                        raise Exception({"error_msg": f"Unsafe zip entry detected: {member}"})

                    if not overwrite and os.path.exists(target_path):
                        continue

                    zipf.extract(member, output_dir)
                    extracted_count += 1

            return json.dumps({
                "status": "success",
                "output_dir": output_dir,
                "extracted_count": extracted_count
            }, ensure_ascii=False)

        elif tool_name == "qgis_list_layouts":
            manager = QgsProject.instance().layoutManager()
            layouts = []
            for layout in manager.layouts():
                layouts.append({
                    "name": layout.name(),
                    "page_count": layout.pageCollection().pageCount(),
                })
            return json.dumps({"layouts": layouts, "count": len(layouts)}, ensure_ascii=False)

        elif tool_name == "qgis_create_layout":
            name = arguments.get("name", "")
            if not name:
                raise Exception({"error_msg": "No layout name provided"})

            name = self._resolve_placeholder(name)

            project = QgsProject.instance()
            layout = QgsPrintLayout(project)
            layout.initializeDefaults()
            layout.setName(name)
            if not project.layoutManager().addLayout(layout):
                raise Exception({"error_msg": f"Could not add layout '{name}' (a layout with that name exists?)"})

            return json.dumps({"status": "success", "name": name}, ensure_ascii=False)

        elif tool_name == "qgis_capture_layout_screenshot":
            gSetting = QgsSettings()
            if gSetting.value(CAPTURE_SCREEN_TAG, 'false').lower() != "true":
                return json.dumps({
                    "status": "error",
                    "message": "Permission denied"
                }, ensure_ascii=False)

            screenshot_path = None
            image_name = ""
            try:
                # Parse parameters
                layout_name = arguments.get("layout_name")
                page_index = int(arguments.get("page_index", 0))
                dpi = float(arguments.get("dpi", 96))
                dpi = max(30, min(dpi, 150))  # Limit DPI to prevent images from becoming too large.

                # Find layout.
                layout = None
                if layout_name:
                    layout = QgsProject.instance().layoutManager().layoutByName(layout_name)
                    if layout is None:
                        raise Exception(f"Layout not found: {layout_name}")
                else:
                    # Prioritize the currently open layout designer
                    designers = self.iface.openLayoutDesigners()
                    if designers is not None and len(designers) > 0:
                        layout = designers[-1].layout()
                    else:
                        layouts = QgsProject.instance().layoutManager().printLayouts()
                        if not layouts:
                            raise Exception("No layout found in current project")
                        layout = layouts[0]

                page_count = layout.pageCollection().pageCount()
                if page_index < 0 or page_index >= page_count:
                    raise Exception(f"page_index out of range, layout has {page_count} page(s)")

                # Render as QImage and save to a temporary directory
                exporter = QgsLayoutExporter(layout)
                # QSize() indicates automatic calculation based on page size and DPI.
                image = exporter.renderPageToImage(page_index, QSize(), dpi)
                if image.isNull():
                    raise Exception("Failed to render layout page")

                screenshot_path = os.path.join(
                    QStandardPaths.writableLocation(TempLocation),
                    f"qgis-layout-screenshot-{uuid.uuid4().hex}.png"
                )
                if not image.save(screenshot_path, "PNG"):
                    raise Exception("Failed to save layout image")

                screenshot_width = image.width()
                screenshot_height = image.height()

                # upload to server
                upload_url = f"{AI_SERVER_DOMAIN}/ai/v1/attachment/image"
                image_name = os.path.basename(screenshot_path)

                with open(screenshot_path, 'rb') as f:
                    image_data = f.read()

                headers = {"Content-Type": "image/png"}
                headers.update(get_auth_headers())

                response = requests.post(
                    upload_url,
                    params={"image_name": image_name},
                    data=image_data,
                    headers=headers,
                    proxies=get_qgis_proxies(),
                    timeout=10
                )
                if response.status_code != 200:
                    raise Exception(f"Failed to upload layout screenshot: {image_name}")

                image_url = response.text.strip()
                if not image_url:
                    raise Exception("Server did not return a valid image url")

            except Exception as e:
                raise Exception({"error_msg": f"Failed to capture layout screenshot: {e}"})
            finally:
                if screenshot_path and os.path.exists(screenshot_path):
                    os.remove(screenshot_path)

            return json.dumps({
                "status": "success",
                "image_url": image_url,
                "format": "png",
                "layout_name": layout.name(),
                "page_index": page_index,
                "page_count": page_count,
                "width": screenshot_width,
                "height": screenshot_height
            }, ensure_ascii=False)

        elif tool_name == "qgis_remove_layout":
            layout_name = arguments.get("layout_name", "")
            layout = self._get_layout(layout_name)
            QgsProject.instance().layoutManager().removeLayout(layout)
            return json.dumps({"status": "success", "removed": layout_name}, ensure_ascii=False)

        elif tool_name == "qgis_get_layout_info":
            layout_name = arguments.get("layout_name", "")
            layout = self._get_layout(layout_name)

            items = []
            for item in layout.items():
                if not hasattr(item, "uuid"):
                    continue
                try:
                    pos = item.positionWithUnits()
                    size = item.sizeWithUnits()
                    x, y = pos.x(), pos.y()
                    w, h = size.width(), size.height()
                except Exception:
                    x = y = w = h = None
                items.append({
                    "id": item.id(),
                    "uuid": item.uuid(),
                    "type": type(item).__name__,
                    "x": x,
                    "y": y,
                    "width": w,
                    "height": h,
                })

            return json.dumps({
                "layout": layout_name,
                "items": items,
                "count": len(items),
                "page_count": layout.pageCollection().pageCount(),
            }, ensure_ascii=False)

        elif tool_name == "qgis_export_layout":
            layout_name = arguments.get("layout_name", "")
            path = arguments.get("path", "")
            fmt = arguments.get("format", "pdf")
            dpi = arguments.get("dpi", 300)

            if not layout_name:
                raise Exception({"error_msg": "No layout_name provided"})
            if not path:
                raise Exception({"error_msg": "No export path provided"})

            layout = self._get_layout(layout_name)
            path = self._resolve_placeholder(path)
            exporter = QgsLayoutExporter(layout)

            fmt_lower = fmt.lower()
            if fmt_lower == "pdf":
                settings = QgsLayoutExporter.PdfExportSettings()
                method = exporter.exportToPdf
            elif fmt_lower == "svg":
                settings = QgsLayoutExporter.SvgExportSettings()
                method = exporter.exportToSvg
            elif fmt_lower in ("png", "jpg", "jpeg", "tif", "tiff", "bmp"):
                settings = QgsLayoutExporter.ImageExportSettings()
                method = exporter.exportToImage
            else:
                raise Exception({"error_msg": f"Unsupported export format: {fmt}"})

            settings.dpi = dpi
            result = method(path, settings)
            if result != QgsLayoutExporter.ExportResult.Success:
                reason = exporter.errorMessage()
                detail = f": {reason}" if reason else ""
                raise Exception({"error_msg": f"Export failed with code: {result}{detail}"})

            return json.dumps({"status": "success", "path": path}, ensure_ascii=False)

        elif tool_name == "qgis_add_layout_map":
            layout_name = arguments.get("layout_name", "")
            x = arguments.get("x", 10)
            y = arguments.get("y", 10)
            width = arguments.get("width", 100)
            height = arguments.get("height", 80)

            layout = self._get_layout(layout_name)
            map_item = QgsLayoutItemMap(layout)
            map_item.attemptMove(QgsLayoutPoint(x, y))
            map_item.attemptResize(QgsLayoutSize(width, height))
            if self.iface is not None:
                map_item.zoomToExtent(self.iface.mapCanvas().extent())
            layout.addLayoutItem(map_item)
            return json.dumps({"status": "success", "uuid": map_item.uuid()}, ensure_ascii=False)

        elif tool_name == "qgis_add_layout_label":
            layout_name = arguments.get("layout_name", "")
            text = arguments.get("text", "")
            x = arguments.get("x", 10)
            y = arguments.get("y", 10)
            width = arguments.get("width", 100)
            height = arguments.get("height", 20)
            font_size = arguments.get("font_size", 12)
            color = arguments.get("color", "#000000")

            if not layout_name:
                raise Exception({"error_msg": "No layout_name provided"})

            layout = self._get_layout(layout_name)
            label = QgsLayoutItemLabel(layout)
            label.setText(self._resolve_placeholder(text))
            self._style_label(label, color, font_size)
            layout.addLayoutItem(label)
            label.attemptMove(QgsLayoutPoint(x, y))
            label.attemptResize(QgsLayoutSize(width, height))
            return json.dumps({"status": "success", "uuid": label.uuid()}, ensure_ascii=False)

        elif tool_name == "qgis_add_layout_legend":
            layout_name = arguments.get("layout_name", "")
            map_item_id = arguments.get("map_item_id", None)
            x = arguments.get("x", 10)
            y = arguments.get("y", 10)
            width = arguments.get("width", None)  # If not passed, it adapts to the content.
            height = arguments.get("height", None)
            title = arguments.get("title", "Legend")
            layer_ids = arguments.get("layer_ids") or []  # Specify by layer ID
            filter_by_map = bool(arguments.get("filter_by_map", False))  # Show only the legend for features visible within the map extent

            layout = self._get_layout(layout_name)
            if layout is None:
                return json.dumps({"status": "error", "message": f"Layout not found: {layout_name}"},
                                  ensure_ascii=False)

            project = QgsProject.instance()

            # Parse layers (preserve input order, remove duplicates)
            layers, missing = [], []
            seen = set()

            def _add_layer(lyr):
                if lyr.id() not in seen:
                    seen.add(lyr.id())
                    layers.append(lyr)

            for lid in layer_ids:
                lyr = project.mapLayer(lid)
                if lyr is not None and lyr.isValid():
                    _add_layer(lyr)
                else:
                    missing.append(lid)

            # The user explicitly specified layers, but none were found -> Throw an error to avoid generating an empty legend.
            if (layer_ids is not None and len(layer_ids) > 0) and (layers is None or len(layers) == 0):
                return json.dumps({
                    "status": "error",
                    "message": "None of the specified layers were found",
                    "missing_layers": missing
                }, ensure_ascii=False)

            # Create a legend
            legend = QgsLayoutItemLegend(layout)
            legend.setTitle(title)

            map_item = self._find_layout_map(layout, map_item_id)
            if map_item is not None:
                legend.setLinkedMap(map_item)
            elif map_item_id:
                # Explicitly notify if a specified map item is not found, rather than silently ignoring it.
                return json.dumps({"status": "error",
                                   "message": f"Map item not found: {map_item_id}"},
                                  ensure_ascii=False)

            # Specify Layers: Disable automatic updates and rebuild the layer tree.
            if layers:
                legend.setAutoUpdateModel(False)  # Must be closed first; otherwise, it will be covered by the project layer tree.
                root = legend.model().rootGroup()
                root.clear()
                for lyr in layers:
                    root.addLayer(lyr)

            if filter_by_map and map_item is not None:
                legend.setLegendFilterByMapEnabled(True)

            layout.addLayoutItem(legend)
            legend.attemptMove(QgsLayoutPoint(x, y, QgsUnitTypes.LayoutUnit.LayoutMillimeters))

            # Size: By default, the legend automatically adjusts its size based on content;
            # to manually specify width/height, you must first disable auto-scaling.
            if width is not None and height is not None:
                legend.setResizeToContents(False)
                legend.attemptResize(QgsLayoutSize(width, height, QgsUnitTypes.LayoutUnit.LayoutMillimeters))
            else:
                legend.adjustBoxSize()

            legend.refresh()

            return json.dumps({
                "status": "success",
                "uuid": legend.uuid(),
                "layers": [{"id": l.id(), "name": l.name()} for l in layers],
                "missing_layers": missing,
                "auto_update": not bool(layers)
            }, ensure_ascii=False)

        elif tool_name == "qgis_add_layout_scalebar":
            layout_name = arguments.get("layout_name", "")
            map_item_id = arguments.get("map_item_id", None)
            x = arguments.get("x", 10)
            y = arguments.get("y", 180)
            width = arguments.get("width", 80)
            height = arguments.get("height", 20)
            style = arguments.get("style", "Single Box")

            layout = self._get_layout(layout_name)
            bar = QgsLayoutItemScaleBar(layout)
            bar.setStyle(style)
            map_item = self._find_layout_map(layout, map_item_id)
            if map_item is not None:
                bar.setLinkedMap(map_item)
            bar.applyDefaultSize()
            layout.addLayoutItem(bar)
            bar.attemptMove(QgsLayoutPoint(x, y))
            bar.attemptResize(QgsLayoutSize(width, height))
            return json.dumps({"status": "success", "uuid": bar.uuid()}, ensure_ascii=False)

        elif tool_name == "qgis_add_layout_picture":
            layout_name = arguments.get("layout_name", "")
            path = arguments.get("path", "")
            x = arguments.get("x", 10)
            y = arguments.get("y", 10)
            width = arguments.get("width", 30)
            height = arguments.get("height", 30)

            if not path:
                raise Exception({"error_msg": "No picture path provided"})
            if not os.path.exists(path):
                raise Exception({"error_msg": f"Picture file not found: {path}"})

            layout = self._get_layout(layout_name)
            pic = QgsLayoutItemPicture(layout)
            pic.setPicturePath(path)
            layout.addLayoutItem(pic)
            pic.attemptMove(QgsLayoutPoint(x, y))
            pic.attemptResize(QgsLayoutSize(width, height))
            return json.dumps({"status": "success", "uuid": pic.uuid()}, ensure_ascii=False)

        elif tool_name == "qgis_add_layout_table":
            layout_name = arguments.get("layout_name", "")
            layer_id = arguments.get("layer_id", "")
            x = arguments.get("x", 10)
            y = arguments.get("y", 10)
            width = arguments.get("width", 180)
            height = arguments.get("height", 80)
            max_rows = arguments.get("max_rows", 20)

            layer = self._get_vector_layer(layer_id)
            layout = self._get_layout(layout_name)
            table = QgsLayoutItemAttributeTable.create(layout)
            table.setVectorLayer(layer)
            table.setMaximumNumberOfFeatures(int(max_rows))
            layout.addMultiFrame(table)
            frame = QgsLayoutFrame(layout, table)
            frame.attemptMove(QgsLayoutPoint(x, y))
            frame.attemptResize(QgsLayoutSize(width, height))
            table.addFrame(frame)
            return json.dumps({"status": "success", "uuid": frame.uuid()}, ensure_ascii=False)

        elif tool_name == "qgis_move_layout_item":
            layout_name = arguments.get("layout_name", "")
            item_id = arguments.get("item_id", "") # Supports UUID or the Item ID set in the designer.
            x = arguments.get("x", None)  # Absolute position (only one value may be passed)
            y = arguments.get("y", None)
            dx = arguments.get("dx", None)  # Relative offset (applies when x/y are not provided)
            dy = arguments.get("dy", None)
            page = arguments.get("page", None)  # Optional: Coordinates relative to the page number (0-indexed)
            unit_name = str(arguments.get("unit", "mm")).lower()

            unit_map = {
                "mm": QgsUnitTypes.LayoutUnit.LayoutMillimeters,
                "cm": QgsUnitTypes.LayoutUnit.LayoutCentimeters,
                "in": QgsUnitTypes.LayoutUnit.LayoutInches,
                "pt": QgsUnitTypes.LayoutUnit.LayoutPoints,
                "px": QgsUnitTypes.LayoutUnit.LayoutPixels,
            }
            unit = unit_map.get(unit_name)
            if unit is None:
                return json.dumps({"status": "error",
                                   "message": f"Unsupported unit: {unit_name}, use one of {list(unit_map.keys())}"},
                                  ensure_ascii=False)

            if all(v is None for v in (x, y, dx, dy)):
                return json.dumps({"status": "error",
                                   "message": "Provide x/y (absolute) or dx/dy (relative)"},
                                  ensure_ascii=False)

            layout = self._get_layout(layout_name)
            if layout is None:
                return json.dumps({"status": "error", "message": f"Layout not found: {layout_name}"},
                                  ensure_ascii=False)

            # 1. Find Item: first by UUID, then by ID
            item = layout.itemByUuid(item_id) if item_id else None
            if item is None and item_id:
                item = layout.itemById(item_id)
            if item is None:
                return json.dumps({"status": "error", "message": f"Layout item not found: {item_id}"},
                                  ensure_ascii=False)

            if item.isLocked():
                return json.dumps({"status": "error", "message": f"Layout item is locked: {item_id}"},
                                  ensure_ascii=False)

            # When specifying a page number, the coordinates are relative to the page;
            # both x and y must be provided to avoid confusion with current global coordinates.
            if page is not None:
                page = int(page)
                if page < 0 or page >= layout.pageCollection().pageCount():
                    return json.dumps({"status": "error",
                                       "message": f"page out of range, layout has {layout.pageCollection().pageCount()} page(s)"},
                                      ensure_ascii=False)
                if x is None or y is None:
                    return json.dumps({"status": "error",
                                       "message": "x and y are both required when page is specified"},
                                      ensure_ascii=False)

            # 2. Calculate target position: Convert to the target unit before processing.
            converter = layout.renderContext().measurementConverter()
            old_pos = converter.convert(item.positionWithUnits(), unit)

            def _resolve(abs_val, delta, current):
                if abs_val is not None:
                    return float(abs_val)
                if delta is not None:
                    return current + float(delta)
                return current

            new_x = _resolve(x, dx, old_pos.x())
            new_y = _resolve(y, dy, old_pos.y())

            # 3. Move
            if page is not None:
                item.attemptMove(QgsLayoutPoint(new_x, new_y, unit), True, False, page)
            else:
                item.attemptMove(QgsLayoutPoint(new_x, new_y, unit))
            item.refresh()

            final_pos = converter.convert(item.positionWithUnits(), unit)

            return json.dumps({
                "status": "success",
                "uuid": item.uuid(),
                "id": item.id(),
                "unit": unit_name,
                "old_position": {"x": round(old_pos.x(), 3), "y": round(old_pos.y(), 3)},
                "new_position": {"x": round(final_pos.x(), 3), "y": round(final_pos.y(), 3)},
                "page": item.page()
            }, ensure_ascii=False)

    def _resolve_placeholder(self, value: str) -> str:
        """Resolve any [USER_PARAM:xxx] / [AUTH_TOKEN:xxx] placeholders in a string using QgsSettings."""
        if not isinstance(value, str):
            return value
        gSetting = QgsSettings()
        placeholder_pattern = re.compile(r"\[(USER_PARAM|AUTH_TOKEN):(.*?)\]")
        for placeholder_type, param_name in placeholder_pattern.findall(value):
            saved_value = gSetting.value(USER_PARAM_KEYS_TAG + f"/{param_name}", "")
            if saved_value:
                value = value.replace(f"[{placeholder_type}:{param_name}]", saved_value)
        return value

    def _get_layout(self, layout_name):
        """Get a print layout by name or raise."""
        layout_name = self._resolve_placeholder(layout_name)
        layout = QgsProject.instance().layoutManager().layoutByName(layout_name)
        if layout is None:
            raise Exception({"error_msg": f"Layout not found: {layout_name}"})
        return layout

    def _find_layout_map(self, layout, map_item_id=None):
        """The map item with id/uuid *map_item_id*, else the first map item."""
        maps = [it for it in layout.items() if isinstance(it, QgsLayoutItemMap)]
        if map_item_id:
            for m in maps:
                if m.id() == map_item_id or m.uuid() == map_item_id:
                    return m
            raise Exception({"error_msg": f"Map item not found in layout: {map_item_id}"})
        return maps[0] if maps else None

    def _style_label(self, label, color, font_size):
        """Set a layout label's colour and size through the current API."""
        text_format = getattr(label, "textFormat", None)
        if text_format is not None and hasattr(label, "setTextFormat"):
            fmt = text_format()
            fmt.setColor(QColor(color))
            fmt.setSize(float(font_size))
            fmt.setSizeUnit(QgsUnitTypes.RenderUnit.RenderPoints)
            label.setTextFormat(fmt)
            return
        label.setFontColor(QColor(color))
        font = label.font()
        font.setPointSize(int(font_size))
        label.setFont(font)

    def _get_vector_layer(self, layer_id):
        """Get a vector layer by id or raise."""
        if layer_id is None or layer_id == "":
            raise Exception({"error_msg": "No layer id provided"})
        project = QgsProject.instance()
        if layer_id not in project.mapLayers():
            raise Exception({"error_msg": f"Layer {layer_id} is not found"})
        layer = project.mapLayer(layer_id)
        if layer.type() != QgsMapLayer.LayerType.VectorLayer:
            raise Exception({"error_msg": f"Layer is not a vector layer: {layer_id}"})
        return layer

    @staticmethod
    def _convert_qvariant(value):
        """Convert QVariant to JSON-serializable native Python types."""
        if isinstance(value, QVariant):
            if value.isNull():
                return None
            value = value.value()
        # Recursively process potentially nested QVariants.
        if isinstance(value, QVariant):
            return OrchToolExecutor._convert_qvariant(value)
        return value

    def _get_layer_type(self, layer):
        """Helper to get layer type as string"""
        if layer.type() == QgsMapLayer.LayerType.VectorLayer:
            return f"vector_{layer.geometryType()}"
        elif layer.type() == QgsMapLayer.LayerType.RasterLayer:
            return "raster"
        else:
            return str(layer.type())

    # def test_tool(self):
    #     tool_result = ""
    #     try:
    #         tool_result = self._execute_tool_impl(
    #             "qgis_search_and_show_place",
    #             {"place_name":"台北"}
    #         )
    #     except Exception as e:
    #         self.execution_error.emit(str(e))
    #     return tool_result
