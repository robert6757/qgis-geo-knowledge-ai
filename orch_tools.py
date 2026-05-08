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
import os
import json
from urllib.parse import quote
from qgis.PyQt.QtCore import QObject, pyqtSignal, Qt, QCoreApplication
from qgis.core import QgsProject, QgsVectorLayer, QgsRasterLayer, QgsMapLayer, QgsFeatureRequest, QgsApplication, QgsProcessingFeedback
from qgis import processing

from .code_execution import CodeExecution

SUPPORTED_TOOLS = ["qgis_add_vector_layer", "qgis_add_raster_layer", "qgis_get_layers", "qgis_zoom_to_layer",
                   "qgis_remove_layer", "qgis_query_features_from_vector_layer", "qgis_execute_code",
                   "qgis_execute_algorithm", "qgis_add_osm_layer", "qgis_add_google_layer"]

class OrchToolExecutor(QObject):
    """The tool executor uses a signal-slot mechanism to execute tools in the GUI thread."""

    execute_requested = pyqtSignal(str, dict)  # tool_name, arguments
    execution_completed = pyqtSignal(str)  # result
    execution_error = pyqtSignal(str)  # error message

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.execute_requested.connect(self._on_execute_requested, Qt.QueuedConnection)

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
            if not name:
                name = os.path.basename(path)

            # Create the layer
            layer = QgsVectorLayer(path, name, provider)

            if not layer.isValid():
                raise Exception(f"Layer is not valid: {path}")

            # Add to project
            QgsProject.instance().addMapLayer(layer)

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
            if not name:
                name = os.path.basename(path)

            # Create the layer
            layer = QgsRasterLayer(path, name, provider)

            if not layer.isValid():
                raise Exception(f"Layer is not valid: {path}")

            # Add to project
            QgsProject.instance().addMapLayer(layer)

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
                layer_info = {
                    "id": layer_id,
                    "name": layer.name(),
                    "type": self._get_layer_type(layer),
                    "visible": project.layerTreeRoot().findLayer(layer_id).isVisible()
                }

                # Add type-specific information
                if layer.type() == QgsMapLayer.VectorLayer:
                    layer_info.update({
                        "feature_count": layer.featureCount(),
                        "geometry_type": layer.geometryType()
                    })
                elif layer.type() == QgsMapLayer.RasterLayer:
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
            if not layer_id:
                raise Exception({"error_msg": "No layer id provided"})

            project = QgsProject.instance()

            if layer_id in project.mapLayers():
                layer = project.mapLayer(layer_id)

                if layer.type() != QgsMapLayer.VectorLayer:
                    raise Exception(f"Layer is not a vector layer: {layer_id}")

                features = []
                request = QgsFeatureRequest()
                if statement:
                    request.setFilterExpression(statement)
                for i, feature in enumerate(layer.getFeatures(request)):
                    # Extract attributes
                    attrs = {}
                    for field in layer.fields():
                        attrs[field.name()] = feature.attribute(field.name())

                    # Extract geometry if available
                    geom = None
                    if feature.hasGeometry():
                        geom = {
                            "type": feature.geometry().type(),
                            "wkt": feature.geometry().asWkt(precision=4)
                        }

                    features.append({
                        "id": feature.id(),
                        "attributes": attrs,
                        "geometry": geom
                    })

                return json.dumps({
                    "layer_id": layer_id,
                    "feature_count": layer.featureCount(),
                    "features": features,
                    "fields": [field.name() for field in layer.fields()]
                }, ensure_ascii=False)
            else:
                raise Exception({"error_msg": f"Layer {layer_id} is not found"})

        elif tool_name == "qgis_execute_code":
            # Execute PyQGIS code
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

            return json.dumps({"result": result, "feedback": feedback.textLog()}, ensure_ascii=False)
        elif tool_name == "qgis_add_osm_layer":
            # Add OSM XYZ tile layer to project
            name = arguments.get("name", "OpenStreetMap")
            url = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"

            # QGIS XYZ Layer URI Format
            uri = f"type=xyz&url={url}&zmax=19&zmin=0"

            layer = QgsRasterLayer(uri, name, "wms")

            if not layer.isValid():
                raise Exception({"error_msg": f"Failed to create OSM layer"})

            QgsProject.instance().addMapLayer(layer)

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

            QgsProject.instance().addMapLayer(layer)

            return json.dumps({
                "layer_id": layer.id(),
                "layer_name": layer.name(),
                "layer_type": "raster",
                "layer_width": layer.width(),
                "layer_height": layer.height()
            }, ensure_ascii=False)

        else:
            raise Exception({"error_msg": f"Unknown tool: {tool_name}"})

    def _get_layer_type(self, layer):
        """Helper to get layer type as string"""
        if layer.type() == QgsMapLayer.VectorLayer:
            return f"vector_{layer.geometryType()}"
        elif layer.type() == QgsMapLayer.RasterLayer:
            return "raster"
        else:
            return str(layer.type())

    # def test_tool(self):
    #     tool_result = ""
    #     try:
    #         tool_result = self._execute_tool_impl(
    #             "qgis_execute_algorithm",
    #             {"algo_id": "gdal:contour","algo_parameters": '{"INPUT":"D:/output/1.tif","BAND":1,"INTERVAL":500,"FIELD_NAME":"ELEV","CREATE_3D":false,"IGNORE_NODATA":false,"NODATA":null,"OFFSET":0,"EXTRA":"","OUTPUT":"TEMPORARY_OUTPUT"}'})
    #     except Exception as e:
    #         self.execution_error.emit(str(e))
    #     return tool_result
