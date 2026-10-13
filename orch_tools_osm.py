# -*- coding: utf-8 -*-
"""
/***************************************************************************
                                 Define Tools for OSM Queries
  Define all tools related to OpenStreetMap queries for orchestration.
                              -------------------
        begin                : 2026-07-14
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
import re
import json
import time
import shutil
from typing import List, Optional
from qgis.PyQt.QtCore import QByteArray, QEventLoop, QUrl, QUrlQuery, QVariant
from qgis.core import (
    Qgis, QgsFileDownloader, QgsVectorLayer, QgsField,
    QgsFeature, QgsGeometry, QgsPoint, QgsPointXY, QgsProject, QgsFeatureRequest,
    QgsVectorFileWriter
)


class OverpassTool:
    """
    Provides a high-level interface to query OpenStreetMap data via Overpass API.
    Implemented as a standalone tool using PyQGIS standard libraries.

    Workflow (same strategy as the QuickOSM plugin):
      1. Overpass returns OSM XML, with all member ways/nodes of the matched objects
         included (``(._;>;); out body;``).
      2. The XML (.osm) file is opened through GDAL's OSM driver, which assembles
         member ways into rings according to their roles and exposes the results as
         the layers ``points``, ``lines``, ``multilinestrings`` and ``multipolygons``.
    """

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------
    def query_osm_objects(
            self,
            key: str,
            value: Optional[str] = None,
            area: Optional[str] = None,
            bbox: Optional[List[float]] = None,
            osm_types: Optional[List[str]] = None,
            around_distance: Optional[int] = None,
            output_path: str = "",
            base_url: str = 'https://overpass-api.de/api/'
    ):
        """
        Query OSM objects based on key/value and location. The result is saved as
        OSM XML (use a '.osm' file extension for output_path).

        :param key: OSM key to filter by.
        :param value: OSM value to filter by (optional).
        :param area: Place name for the query (optional).
        :param bbox: Bounding box for the query [xmin, ymin, xmax, ymax] (optional).
        :param osm_types: List of OSM types ('node', 'way', 'relation'). Defaults to all.
        :param around_distance: Distance in meters for 'around' queries (optional).
        :param output_path: Path to save the query results (OSM XML, '.osm').
        :param base_url: Base URL of the Overpass API.
        """
        try:
            if not output_path:
                raise ValueError("output_path must not be empty.")

            # 1. Generate the OQL Query
            oql = self._generate_oql(key, value, area, bbox, osm_types, around_distance)

            # 2. Construct the URL
            # Ensure base_url ends with / and append 'interpreter'
            endpoint = base_url.rstrip('/') + '/interpreter'
            url = QUrl(endpoint)

            url_query = QUrlQuery()
            url_query.addQueryItem('info', 'LLM_OverpassTool')
            url.setQuery(url_query)

            # Make sure a stale result of a previous run can never be mistaken for a new one
            out_dir = os.path.dirname(output_path)
            if out_dir:
                os.makedirs(out_dir, exist_ok=True)
            if os.path.exists(output_path):
                os.remove(output_path)

            # 3. Execute request using QgsFileDownloader (POST)
            downloader = QgsFileDownloader(
                url,
                output_path,
                delayStart=True,
                httpMethod=Qgis.HttpMethod.Post,
                data=QByteArray(f"data={oql}".encode('utf-8'))
            )

            loop = QEventLoop()
            downloader.downloadExited.connect(loop.quit)
            downloader.startDownload()
            loop.exec()

            # 4. Validate the result
            if not os.path.exists(output_path):
                raise FileNotFoundError("Query result file not found. This might be because the Overpass API timed out or the query is too large. Please try again or consider adjusting parameters such as osm_types or the search area.")
            self._validate_osm_xml(output_path)

        except Exception as e:
            raise e

    @staticmethod
    def _esc(text) -> str:
        """Escape a string for use inside a double-quoted Overpass QL literal."""
        return str(text).replace('\\', '\\\\').replace('"', '\\"')

    def _generate_oql(self, key: str, value: Optional[str], area: Optional[str],
                       bbox: Optional[List[float]], osm_types: Optional[List[str]],
                       around_distance: Optional[int]) -> str:
        """Internal helper to generate a simple Overpass QL string."""

        # Header: XML output (read by GDAL's OSM driver) and timeout
        query = '[out:xml][timeout:60];\n'

        # Handle Area
        area_id = None
        if area:
            # Simple name-based area query: find the area by name and assign to variable .a
            query += f'area["name"="{self._esc(area)}"] -> .a;\n'
            area_id = '.a'

        # Determine types to query
        types = osm_types if osm_types else ['node', 'way', 'relation']

        # Build the filters
        # Filter: [key="value"] or just [key]
        filter_str = f'["{self._esc(key)}"="{self._esc(value)}"]' if value else f'["{self._esc(key)}"]'

        # Combine types into a union
        query += '(\n'
        for t in types:
            # Filter and spatial constraint
            spatial = ''
            if bbox:
                # bbox format: [xmin, ymin, xmax, ymax]
                # Overpass API format: (south, west, north, east) -> (ymin, xmin, ymax, xmax)
                spatial = f'({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]})'
            elif around_distance and area_id:
                spatial = f'(around:{around_distance}, {area_id})'
            elif area_id:
                spatial = f'(area{area_id})'

            query += f'  {t}{filter_str}{spatial};\n'
        query += ');\n'

        # Recurse down so that all member ways and their nodes are returned too.
        # GDAL needs them to assemble relation geometries (rings of boundary relations).
        # A single, type-sorted output (nodes -> ways -> relations) is required by GDAL.
        query += '(._;>;);\n'
        query += 'out body;'

        return query

    def _validate_osm_xml(self, path: str):
        """Raise if the downloaded file is empty, an HTML error page, or an Overpass runtime error."""
        size = os.path.getsize(path)
        if size == 0:
            raise RuntimeError("The downloaded OSM data is empty.")

        with open(path, 'rb') as f:
            head = f.read(4096).decode('utf8', errors='ignore').lower()
            f.seek(max(0, size - 4096))
            tail = f.read().decode('utf8', errors='ignore')

        if '<html' in head or '<!doctype html' in head:
            raise RuntimeError("The downloaded OSM data contains an HTML error page (the Overpass server may be busy or rejected the query).")
        if '<osm' not in head:
            raise RuntimeError("The downloaded file is not valid OSM XML.")

        # Overpass reports timeouts / memory problems as a <remark> element at the end of the XML
        remark = re.search(r'<remark>(.*?)</remark>', tail, re.S)
        if remark and 'error' in remark.group(1).lower():
            raise RuntimeError(f"Overpass API returned an error: {remark.group(1).strip()}")

    # ------------------------------------------------------------------
    # Load
    # ------------------------------------------------------------------
    @staticmethod
    def _ensure_osm_extension(path: str) -> str:
        """GDAL's OSM driver is most reliable with a .osm/.pbf extension; copy if needed."""
        if path.lower().endswith(('.osm', '.pbf')):
            return path
        new_path = path + '.osm'
        if not os.path.exists(new_path) or os.path.getmtime(new_path) < os.path.getmtime(path):
            shutil.copyfile(path, new_path)
        return new_path

    def load_osm_to_map(
            self,
            osm_path: str,
            layer_name: str = "OSM Results",
            osm_types: Optional[List[str]] = None
    ):
        """
        Read an OSM XML file with GDAL's OSM driver and add the results to the map.
        Geometry assembly (including multipolygon / boundary relations) is done by GDAL,
        exactly as in the QuickOSM plugin.

        Layers created (empty ones are skipped):
          points -> Point, lines -> LineString,
          multilinestrings -> MultiLineString, multipolygons -> MultiPolygon

        :param osm_path: Path to the OSM XML file downloaded from Overpass.
        :param layer_name: Base name of the layers to be created.
        :param osm_types: The same OSM types that were passed to query_osm_objects()
                          ('node', 'way', 'relation'). Used to hide the member ways / nodes
                          that were downloaded only to assemble relation geometries.
                          If omitted, every layer found in the file is loaded.
        """
        try:
            if not os.path.exists(osm_path):
                raise FileNotFoundError(f"OSM file not found: {osm_path}")

            types = set(osm_types) if osm_types else {'node', 'way', 'relation'}

            ogr_path = self._ensure_osm_extension(osm_path)

            # (GDAL layer name, optional attribute filter), polygons first so that
            # lines and points are drawn on top of them.
            # In GDAL's multipolygons layer 'osm_id' is set for relations and
            # 'osm_way_id' for closed ways, which lets us hide the member ways that
            # were only fetched for geometry assembly.
            plan = []
            if 'way' in types and 'relation' in types:
                plan.append(('multipolygons', ''))
            elif 'relation' in types:
                plan.append(('multipolygons', '"osm_id" IS NOT NULL'))
            elif 'way' in types:
                plan.append(('multipolygons', '"osm_way_id" IS NOT NULL'))
            if 'relation' in types:
                plan.append(('multilinestrings', ''))
            if 'way' in types:
                plan.append(('lines', ''))
            if 'node' in types:
                plan.append(('points', ''))

            # GDAL's OSM driver is a sequential reader: it knows neither the feature count
            # nor the extent of a layer (Overpass XML has no <bounds> header), so QGIS layers
            # opened directly on the .osm file cannot "zoom to layer". Like QuickOSM, we
            # therefore convert each layer into a GeoPackage and load that instead.
            gpkg_path = os.path.splitext(ogr_path)[0] + '.gpkg'
            try:
                if os.path.exists(gpkg_path):
                    os.remove(gpkg_path)
            except OSError:
                # The old file is still locked (e.g. its layers are still in the project)
                gpkg_path = f"{os.path.splitext(ogr_path)[0]}_{int(time.time())}.gpkg"

            loaded = []
            for ogr_layer, subset in plan:
                src = QgsVectorLayer(
                    f"{ogr_path}|layername={ogr_layer}",
                    f"{layer_name} - {ogr_layer}",
                    "ogr"
                )
                if not src.isValid():
                    continue
                if subset:
                    # If the filter is rejected the layer simply stays unfiltered
                    src.setSubsetString(subset)
                # featureCount() is unknown for the OSM driver; just try to get the first feature.
                if next(src.getFeatures(QgsFeatureRequest().setLimit(1)), None) is None:
                    continue

                options = QgsVectorFileWriter.SaveVectorOptions()
                options.driverName = 'GPKG'
                options.layerName = ogr_layer
                options.fileEncoding = 'UTF-8'
                options.actionOnExistingFile = (
                    QgsVectorFileWriter.CreateOrOverwriteLayer if os.path.exists(gpkg_path)
                    else QgsVectorFileWriter.CreateOrOverwriteFile
                )
                result = QgsVectorFileWriter.writeAsVectorFormatV3(
                    src, gpkg_path, QgsProject.instance().transformContext(), options
                )
                if result[0] != QgsVectorFileWriter.NoError:
                    raise RuntimeError(f"Failed to convert OSM layer '{ogr_layer}' to GeoPackage: {result[1]}")

                layer = QgsVectorLayer(
                    f"{gpkg_path}|layername={ogr_layer}",
                    f"{layer_name} - {ogr_layer}",
                    "ogr"
                )
                if not layer.isValid():
                    continue
                QgsProject.instance().addMapLayer(layer)
                loaded.append(layer)

            if not loaded:
                raise ValueError("No OSM elements found in the OSM file. This might be because the query result is empty. Please consider adjusting parameters such as osm_types, the search area, or the tag keys and values.")

        except Exception as e:
            raise e

    def load_osm_json_to_map(self, json_path: str, layer_name: str = "OSM Results"):
        """
        Backward-compatible wrapper of load_osm_to_map().
        The file is now OSM XML, not JSON; the old name and signature are kept so existing
        tool definitions keep working.
        """
        return self.load_osm_to_map(json_path, layer_name)

    # ------------------------------------------------------------------
    # Place search (unchanged)
    # ------------------------------------------------------------------
    def search_place(
            self,
            place_name: str,
            output_path: str,
            limit: int = 5,
            base_url: str = 'https://nominatim.openstreetmap.org/search'
    ):
        """
        Query place names using OSM Nominatim API.

        :param place_name: The name of the place to search for (e.g., "北京").
        :param output_path: Path to save the query results as JSON.
        :param limit: Maximum number of results to return.
        :param contact_email: Required by Nominatim's Fair Use Policy for identification.
        :param base_url: Base URL of the Nominatim API.
        """
        try:
            # 1. Construct the URL and Parameters
            url = QUrl(base_url)
            url_query = QUrlQuery()
            url_query.addQueryItem('q', place_name)
            url_query.addQueryItem('format', 'json')
            url_query.addQueryItem('limit', str(limit))
            url.setQuery(url_query)

            # 2. Execute request using QgsFileDownloader (GET)
            downloader = QgsFileDownloader(
                url,
                output_path,
                delayStart=True,
                httpMethod=Qgis.HttpMethod.Get
            )

            loop = QEventLoop()
            downloader.downloadExited.connect(loop.quit)
            downloader.startDownload()
            loop.exec()

            # 3. Validate the result
            if os.path.exists(output_path):
                with open(output_path, 'r', encoding='utf8') as f:
                    content = f.read()
                    if not content or '<html' in content.lower() or 'bad request' in content.lower():
                        raise RuntimeError("The downloaded geocoding data is empty or contains an error.")
            else:
                raise FileNotFoundError("Place search result file not found. The API might have timed out.")

        except Exception as e:
            raise e

    def load_place_json_to_map(self, json_path: str, layer_name: str = "Place Search Results"):
        """
        Read Nominatim JSON results and display them as a Point vector layer on the map.

        :param json_path: Path to the JSON file containing Nominatim results.
        :param layer_name: Name of the layer to be created.
        """
        try:
            if not os.path.exists(json_path):
                raise FileNotFoundError(f"Place JSON file not found: {json_path}")

            with open(json_path, 'r', encoding='utf8') as f:
                data = json.load(f)

            if not data or not isinstance(data, list):
                raise ValueError("No place results found in the JSON file or incorrect format.")

            # Create Point layer
            layer = QgsVectorLayer("Point?crs=EPSG:4326", layer_name, "memory")
            if not layer.isValid():
                raise Exception("Failed to create memory layer for place search.")

            provider = layer.dataProvider()

            # Define fields based on Nominatim output
            fields = [
                QgsField("display_name", QVariant.String),
                QgsField("type", QVariant.String),
                QgsField("importance", QVariant.Double),
                QgsField("place_id", QVariant.String)
            ]
            provider.addAttributes(fields)
            layer.updateFields()

            features = []
            for el in data:
                feat = QgsFeature()
                lon, lat = el.get('lon'), el.get('lat')

                if lon is not None and lat is not None:
                    # Parse geometry
                    geom = QgsGeometry.fromPointXY(QgsPointXY(float(lon), float(lat)))
                    feat.setGeometry(geom)

                    # Set attributes
                    feat.setAttributes([
                        el.get('display_name', ''),
                        el.get('type', ''),
                        float(el.get('importance', 0.0)),
                        str(el.get('place_id', ''))
                    ])
                    features.append(feat)

            if not features:
                raise ValueError("No valid coordinates found to create map features.")

            # Add layer to project
            provider.addFeatures(features)
            layer.updateExtents()
            QgsProject.instance().addMapLayer(layer)

        except Exception as e:
            raise e
