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
import json
from typing import List, Optional
from qgis.PyQt.QtCore import QByteArray, QEventLoop, QUrl, QUrlQuery, QVariant
from qgis.core import (
    Qgis, QgsFileDownloader, QgsVectorLayer, QgsField, 
    QgsFeature, QgsGeometry, QgsPoint, QgsPointXY, QgsProject, QgsWkbTypes
)

class OverpassTool:
    """
    Provides a high-level interface to query OpenStreetMap data via Overpass API.
    Implemented as a standalone tool using PyQGIS standard libraries.
    """

    def query_osm_objects(
        self, 
        key: str, 
        value: Optional[str] = None, 
        area: Optional[str] = None, 
        osm_types: Optional[List[str]] = None, 
        around_distance: Optional[int] = None,
        output_path: str = "",
        base_url: str = 'https://overpass-api.de/api/'
    ) -> bool:
        """
        Query OSM objects based on key/value and location.
        
        :param key: OSM key to filter by.
        :param value: OSM value to filter by (optional).
        :param area: Place name for the query (optional).
        :param osm_types: List of OSM types ('node', 'way', 'relation'). Defaults to all.
        :param around_distance: Distance in meters for 'around' queries (optional).
        :param output_path: Path to save the query results.
        :param base_url: Base URL of the Overpass API.
        :return: True if query was successful and file saved, False otherwise.
        """
        try:
            # 1. Generate the OQL Query
            oql = self._generate_oql(key, value, area, osm_types, around_distance)
            
            # 2. Construct the URL
            # Ensure base_url ends with / and append 'interpreter'
            endpoint = base_url.rstrip('/') + '/interpreter'
            url = QUrl(endpoint)
            
            url_query = QUrlQuery()
            url_query.addQueryItem('target', 'json') # Ensure JSON output
            url_query.addQueryItem('info', 'LLM_OverpassTool')
            url.setQuery(url_query)

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
            if os.path.exists(output_path):
                with open(output_path, 'r', encoding='utf8') as f:
                    content = f.read()
                    # If file is empty or contains HTML error page, consider it failed
                    if not content or '<html' in content.lower() or '<!doctype' in content.lower():
                        return False
                    return True
            else:
                return False

        except Exception as e:
            return False

    def _generate_oql(self, key: str, value: Optional[str], area: Optional[str], 
                      osm_types: Optional[List[str]], around_distance: Optional[int]) -> str:
        """Internal helper to generate a simple Overpass QL string."""
        
        # Header: JSON output and timeout
        query = '[out:json][timeout:30];\n'
        
        # Handle Area
        area_id = None
        if area:
            # Simple name-based area query: find the area by name and assign to variable .a
            query += f'area["name"="{area}"] -> .a;\n'
            area_id = '.a'

        # Determine types to query
        types = osm_types if osm_types else ['node', 'way', 'relation']
        
        # Build the filters
        # Filter: [key="value"] or just [key]
        filter_str = f'["{key}"="{value}"]' if value else f'["{key}"]'
        
        # Combine types into a union
        query += '(\n'
        for t in types:
            # Filter and spatial constraint
            spatial = ''
            if around_distance and area_id:
                spatial = f'(around:{around_distance}, {area_id})'
            elif area_id:
                spatial = f'(area{area_id})'
            
            query += f'  {t}{filter_str}{spatial};\n'
        query += ');\n'
        
        # Output body with geometry (essential for constructing ways from coordinates)
        query += 'out geom;'
        
        return query

    def load_osm_json_to_map(self, json_path: str, layer_name: str = "OSM Results") -> bool:
        """
        Read OSM JSON results and display them as a vector layer on the map.
        Supports both nodes (Points) and ways (LineStrings).
        
        :param json_path: Path to the JSON file containing Overpass results.
        :param layer_name: Name of the layer to be created.
        :return: True if the layer was successfully created and added, False otherwise.
        """
        try:
            if not os.path.exists(json_path):
                return False

            with open(json_path, 'r', encoding='utf8') as f:
                data = json.load(f)

            elements = data.get('elements', [])
            if not elements:
                return False

            # 1. Determine the dominant geometry type to create the layer
            # If any 'way' is present, we use LineString as it's typically the desired result for ways
            has_ways = any(el.get('type') == 'way' for el in elements)
            geom_type = "LineString" if has_ways else "Point"
            
            # 2. Determine all unique keys in tags to define fields
            all_tag_keys = set()
            for el in elements:
                tags = el.get('tags', {})
                all_tag_keys.update(tags.keys())
            
            sorted_keys = sorted(list(all_tag_keys))

            # 3. Create a memory layer
            layer = QgsVectorLayer(f"{geom_type}?crs=EPSG:4326", layer_name, "memory")
            if not layer.isValid():
                return False

            # 4. Define fields
            provider = layer.dataProvider()
            fields = []
            for key in sorted_keys:
                fields.append(QgsField(key, QVariant.String))
            
            provider.addAttributes(fields)
            layer.updateFields()

            # 5. Create features and add to layer
            features = []
            for el in elements:
                feat = QgsFeature()
                el_type = el.get('type')
                
                # Geometry construction
                geom = None
                if el_type == 'node':
                    lon = el.get('lon')
                    lat = el.get('lat')
                    if lon is not None and lat is not None:
                        geom = QgsGeometry.fromPointXY(QgsPointXY(lon, lat))
                elif el_type == 'way':
                    # Overpass 'out geom' returns a 'geometry' field: [{"lat": ..., "lon": ...}, ...]
                    geometry_data = el.get('geometry')
                    if geometry_data and isinstance(geometry_data, list):
                        points = [QgsPoint(p['lon'], p['lat']) for p in geometry_data if 'lon' in p and 'lat' in p]
                        if points:
                            geom = QgsGeometry.fromPolyline(points)
                
                if geom:
                    feat.setGeometry(geom)
                else:
                    # Skip features without geometry to avoid adding empty features to the layer
                    continue
                
                # Attributes: tags
                tags = el.get('tags', {})
                attrs = [tags.get(key, "") for key in sorted_keys]
                feat.setAttributes(attrs)
                
                features.append(feat)

            if not features:
                return False

            provider.addFeatures(features)
            layer.updateExtents()

            # 6. Add layer to the project
            QgsProject.instance().addMapLayer(layer)
            
            return True

        except Exception as e:
            print(f"Error loading OSM JSON to map: {e}")
            return False
