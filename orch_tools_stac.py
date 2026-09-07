# -*- coding: utf-8 -*-
"""
/***************************************************************************
                                 Define Tools for STAC Queries
  Define all tools related to SpatioTemporal Asset Catalog (STAC) queries
  for orchestration. STAC is a standardized API implemented by many major
  geodata catalogs (Microsoft Planetary Computer, AWS Earth Search, USGS
  Landsat STAC, Copernicus Data Space, etc.), so a single client here can
  reach a large share of public satellite/raster data without a bespoke
  connector per provider.
                              -------------------
        begin                : 2026-09-07
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

import json
from typing import List, Optional, Dict
from qgis.PyQt.QtCore import QByteArray, QUrl, QUrlQuery
from qgis.PyQt.QtNetwork import QNetworkRequest
from qgis.core import QgsVectorLayer, QgsRasterLayer, QgsProject, QgsBlockingNetworkRequest


class StacTool:
    """
    Provides a high-level interface to search and load data from STAC
    (SpatioTemporal Asset Catalog) compliant APIs. Implemented as a
    standalone tool using PyQGIS standard libraries, mirroring the
    structure of OverpassTool.
    """

    def search_stac_items(
            self,
            collections: List[str],
            bbox: Optional[List[float]] = None,
            datetime_range: Optional[str] = None,
            query: Optional[Dict] = None,
            limit: int = 20,
            base_url: str = 'https://planetarycomputer.microsoft.com/api/stac/v1'
    ) -> dict:
        """
        Search a STAC API for items matching the given spatial/temporal/query filters.

        :param collections: STAC collection ids to search, e.g. ['sentinel-2-l2a'].
        :param bbox: Bounding box [xmin, ymin, xmax, ymax] in EPSG:4326 (optional).
        :param datetime_range: ISO8601 instant or interval, e.g. '2024-01-01/2024-06-30' (optional).
        :param query: STAC 'query' extension filters, e.g. {'eo:cloud_cover': {'lt': 20}} (optional).
        :param limit: Max number of items to return.
        :param base_url: Root URL of the STAC API.
        :return: Parsed JSON response (GeoJSON FeatureCollection) from the STAC API.
        """
        # 1. Build the STAC search request body
        body = self._generate_search_body(collections, bbox, datetime_range, query, limit)

        # 2. Construct the endpoint URL
        endpoint = base_url.rstrip('/') + '/search'
        url = QUrl(endpoint)

        # 3. Prepare the network request with required JSON headers
        request = QNetworkRequest(url)
        request.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json")
        request.setRawHeader(b"Accept", b"application/json")

        # 4. Execute a blocking POST request
        payload = QByteArray(json.dumps(body, ensure_ascii=False).encode('utf-8'))
        blocking_request = QgsBlockingNetworkRequest()
        err = blocking_request.post(request, payload)

        if err != QgsBlockingNetworkRequest.ErrorCode.NoError:
            raise RuntimeError(f"STAC search request failed: {blocking_request.errorMessage()}")

        reply = blocking_request.reply()
        content = bytes(reply.content()).decode('utf-8')
        if not content:
            raise RuntimeError("The STAC search response is empty. "
                               "Check that the collection id and base_url are correct.")

        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            raise RuntimeError("The STAC search response is not valid JSON. "
                               "Check that the collection id and base_url are correct.") from exc

        return data

    def _generate_search_body(self, collections, bbox, datetime_range, query, limit) -> dict:
        """Internal helper to build a STAC API /search JSON request body."""
        body = {
            'collections': collections,
            'limit': limit
        }
        if bbox:
            body['bbox'] = bbox
        if datetime_range:
            body['datetime'] = datetime_range
        if query:
            body['query'] = query
        return body

    def list_stac_assets(self, stac_data: dict) -> List[dict]:
        """
        Parse a STAC search response (GeoJSON FeatureCollection of Items)
        into a flat list of downloadable assets with their metadata. This is
        the equivalent of load_osm_json_to_map's parsing step, but STAC
        results describe *assets to fetch* rather than geometry to render.

        :param stac_data: Parsed STAC search response (GeoJSON FeatureCollection dict).
        :return: List of dicts: {item_id, asset_key, href, media_type, roles}
        """
        try:
            features = stac_data.get('features', [])
            if not features:
                raise ValueError("No STAC items found. Try widening the bbox, datetime range, "
                                  "or double-check the collection id.")

            assets = []
            for feat in features:
                item_id = feat.get('id')
                for asset_key, asset in feat.get('assets', {}).items():
                    assets.append({
                        'item_id': item_id,
                        'asset_key': asset_key,
                        'href': asset.get('href'),
                        'media_type': asset.get('type'),
                        'roles': asset.get('roles', [])
                    })
            return assets

        except Exception as e:
            raise e

    def sign_planetary_computer_href(
            self,
            href: str,
            sign_base_url: str = 'https://planetarycomputer.microsoft.com/api/sas/v1/sign'
    ) -> str:
        """
        Example of a Tier-1 auth flow (see the tiered auth strategy discussed
        earlier): Planetary Computer serves most assets from private Azure
        Blob Storage and requires a short-lived SAS token appended to the URL
        before GDAL/OGR can stream it. This calls the public signing endpoint
        (anonymous, rate-limited access; no API key required for light use)
        and returns a ready-to-use signed URL.

        :param href: Unsigned asset URL returned by list_stac_assets().
        :param sign_base_url: Planetary Computer's signing endpoint.
        :return: Signed URL with a valid SAS token appended.
        """
        try:
            sign_url = QUrl(sign_base_url)
            url_query = QUrlQuery()
            url_query.addQueryItem('href', href)
            sign_url.setQuery(url_query)

            request = QNetworkRequest(sign_url)
            blocking_request = QgsBlockingNetworkRequest()
            err = blocking_request.get(request)

            if err != QgsBlockingNetworkRequest.ErrorCode.NoError:
                raise RuntimeError(f"Failed to sign STAC asset URL: {blocking_request.errorMessage()}")

            reply = blocking_request.reply()
            content = bytes(reply.content()).decode('utf-8')
            signed = json.loads(content)
            return signed.get('href', href)

        except Exception as e:
            raise e

    def load_stac_asset_to_map(self, href: str, layer_name: str = "STAC Asset", is_vector: bool = False):
        """
        Load a single STAC asset directly into the QGIS project as a raster or
        vector layer. Many STAC assets (Cloud-Optimized GeoTIFFs on public
        buckets, or already-signed Planetary Computer URLs) can be opened
        directly by GDAL/OGR over HTTP via the /vsicurl/ virtual file system,
        without a manual download-and-extract step.

        :param href: Direct asset URL (already signed, if the provider requires it).
        :param layer_name: Name to assign the new layer.
        :param is_vector: True to load via OGR (QgsVectorLayer), False for GDAL raster.
        """
        try:
            # /vsicurl/ lets GDAL/OGR stream the remote file without a local copy.
            gdal_path = href if href.startswith('/vsicurl/') else f"/vsicurl/{href}"

            if is_vector:
                layer = QgsVectorLayer(gdal_path, layer_name, "ogr")
            else:
                layer = QgsRasterLayer(gdal_path, layer_name, "gdal")

            if not layer.isValid():
                raise RuntimeError(f"Failed to load STAC asset as a valid layer: {href}. "
                                    f"The URL may require a signing step (e.g. Planetary Computer) "
                                    f"or an authentication token before it can be streamed.")

            QgsProject.instance().addMapLayer(layer)

        except Exception as e:
            raise e
