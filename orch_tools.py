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
import json
from qgis.PyQt.QtCore import QObject, pyqtSignal, Qt, QCoreApplication, QVariant, QStandardPaths
from qgis.core import QgsProject, QgsVectorLayer, QgsRasterLayer, QgsMapLayer, QgsFeatureRequest, QgsApplication, QgsProcessingFeedback, QgsRectangle
from qgis import processing

from .code_exec_utils import get_code_execution_class
from .compat import *
from .orch_tools_osm import OverpassTool
from .orch_tools_qml import QmlStyleTool

SUPPORTED_TOOLS = ["qgis_add_vector_layer", "qgis_add_raster_layer", "qgis_get_layers", "qgis_zoom_to_layer",
                   "qgis_remove_layer", "qgis_query_features_from_vector_layer", "qgis_execute_code",
                   "qgis_execute_algorithm", "qgis_add_osm_layer", "qgis_add_google_layer",
                   "qgis_query_raster_values_by_bbox", "qgis_get_algorithm_help", "qgis_get_pyqgis_class_help",
                   "qgis_query_and_show_osm_objects", "qgis_get_qml_template"]

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
                    "visible": layer_tree_node.isVisible() if layer_tree_node else False
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
            max_feature_count = arguments.get("max_feature_count", 0)
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
                if max_feature_count > 0:
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

            # use metadata of processing to find the real algorithm id.
            processing_metadata = QgsApplication.processingRegistry().algorithmById(algo_id)

            # try to find C++(native) and Python(qgis) processing.
            if not processing_metadata and algo_id.startswith("native:"):
                _algo_id = algo_id.replace("native:", "qgis:")
                processing_metadata = QgsApplication.processingRegistry().algorithmById(_algo_id)
            if not processing_metadata and algo_id.startswith("qgis:"):
                _algo_id = algo_id.replace("qgis:", "native:")
                processing_metadata = QgsApplication.processingRegistry().algorithmById(_algo_id)
            if not processing_metadata and algo_id.startswith("saga:"):
                _algo_id = algo_id.replace("saga:", "sagang:")
                processing_metadata = QgsApplication.processingRegistry().algorithmById(_algo_id)

            # Fail to find any processing.
            if not processing_metadata:
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
                "layer_id": layer.id(),
                "layer_name": layer.name(),
                "layer_type": "raster",
                "layer_width": layer.width(),
                "layer_height": layer.height()
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
                "layer_id": layer.id(),
                "layer_name": layer.name(),
                "layer_type": "raster",
                "layer_width": layer.width(),
                "layer_height": layer.height()
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
            
            # Generate output file path
            temp_dir = QStandardPaths.writableLocation(TempLocation)
            output_path = os.path.join(temp_dir, "qgis-geo-knowledge-ai-osm-query.json")
            
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
                self.overpass_tool.load_osm_json_to_map(output_path, f"OSM_{key}_{value}")
            except Exception as e:
                raise Exception({"error_msg": str(e)})
            
            result = {"status": "success", "message": "OSM data successfully loaded to map."}
            return json.dumps(result, ensure_ascii=False)

        elif tool_name == "qgis_get_qml_template":
            style_type = arguments.get("style_type")
            try:
                template = self.qml_tool.get_qml_template(style_type)
                result = {"status": "success", "template": template}
            except Exception as e:
                raise Exception({"error_msg": str(e)})
            return json.dumps(result, ensure_ascii=False)

        else:
            raise Exception({"error_msg": f"Unknown tool: {tool_name}"})

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
    #             "qgis_get_pyqgis_class_help",
    #             {"class_names": ['QgsGraduatedSymbolRenderer']})
    #     except Exception as e:
    #         self.execution_error.emit(str(e))
    #     return tool_result
