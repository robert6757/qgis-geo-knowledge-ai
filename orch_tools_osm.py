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
        Read OSM JSON results and display them as vector layers on the map.
        Supports nodes (Point), ways (LineString), and relations (Multipolygon).
        
        :param json_path: Path to the JSON file containing Overpass results.
        :param layer_name: Base name of the layers to be created.
        :return: True if at least one layer was successfully created, False otherwise.
        """
        try:
            if not os.path.exists(json_path):
                return False

            with open(json_path, 'r', encoding='utf8') as f:
                data = json.load(f)

            elements = data.get('elements', [])
            if not elements:
                return False

            # 1. Separate elements by type
            nodes = [el for el in elements if el.get('type') == 'node']
            ways = [el for el in elements if el.get('type') == 'way']
            relations = [el for el in elements if el.get('type') == 'relation']

            # 2. Determine all unique keys in tags for a common attribute set
            all_tag_keys = set()
            for el in elements:
                all_tag_keys.update(el.get('tags', {}).keys())
            sorted_keys = sorted(list(all_tag_keys))

            def create_layer(geom_type, suffix, element_list):
                if not element_list:
                    return False
                
                name = f"{layer_name} - {suffix}"
                layer = QgsVectorLayer(f"{geom_type}?crs=EPSG:4326", name, "memory")
                if not layer.isValid():
                    return False
                
                provider = layer.dataProvider()
                fields = [QgsField(key, QVariant.String) for key in sorted_keys]
                provider.addAttributes(fields)
                layer.updateFields()

                features = []
                for el in element_list:
                    feat = QgsFeature()
                    geom = None
                    el_type = el.get('type')

                    if el_type == 'node':
                        lon, lat = el.get('lon'), el.get('lat')
                        if lon is not None and lat is not None:
                            geom = QgsGeometry.fromPointXY(QgsPointXY(lon, lat))
                    
                    elif el_type == 'way':
                        geometry_data = el.get('geometry')
                        if geometry_data and isinstance(geometry_data, list):
                            points = [QgsPoint(p['lon'], p['lat']) for p in geometry_data if 'lon' in p and 'lat' in p]
                            if points:
                                geom = QgsGeometry.fromPolyline(points)
                    
                    elif el_type == 'relation':
                        # For relations (multipolygons), build geometry from member ways using WKT
                        members = el.get('members', [])
                        rings_wkt = []
                        for m in members:
                            if m.get('type') == 'way':
                                m_geom = m.get('geometry')
                                if m_geom and isinstance(m_geom, list):
                                    # Format points as 'lon lat'
                                    pts = [f"{p['lon']} {p['lat']}" for p in m_geom if 'lon' in p and 'lat' in p]
                                    if pts:
                                        # Ensure the ring is closed for WKT Polygon
                                        if pts[0] != pts[-1]:
                                            pts.append(pts[0])
                                        rings_wkt.append(f"({', '.join(pts)})")
                        
                        if rings_wkt:
                            # Construct WKT: POLYGON((outer), (inner1), (inner2)...)
                            wkt = f"POLYGON({', '.join(rings_wkt)})"
                            geom = QgsGeometry.fromWkt(wkt)
                    if geom:
                        feat.setGeometry(geom)
                    else:
                        continue
                    
                    tags = el.get('tags', {})
                    feat.setAttributes([tags.get(key, "") for key in sorted_keys])
                    features.append(feat)

                if features:
                    provider.addFeatures(features)
                    layer.updateExtents()
                    QgsProject.instance().addMapLayer(layer)
                    return True
                return False

            # Create the three layers
            success_nodes = create_layer("Point", "Nodes", nodes)
            success_ways = create_layer("LineString", "Ways", ways)
            success_rels = create_layer("Multipolygon", "Relations", relations)
            
            return success_nodes or success_ways or success_rels

        except Exception as e:
            print(f"Error loading OSM JSON to map: {e}")
            return False
