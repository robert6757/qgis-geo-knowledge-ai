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

import os
import json
from collections import defaultdict
from urllib.parse import urlparse
from typing import List, Optional, Dict
from qgis.PyQt.QtCore import QByteArray, QUrl, QUrlQuery
from qgis.PyQt.QtNetwork import QNetworkRequest
from qgis.core import (
    QgsVectorLayer, QgsRasterLayer, QgsProject, QgsNetworkAccessManager,
    QgsGeometry, QgsRectangle, QgsDistanceArea, QgsCoordinateReferenceSystem
)
from qgis.PyQt.QtNetwork import QNetworkReply

class StacTool:
    """
    Provides a high-level interface to search and load data from STAC
    (SpatioTemporal Asset Catalog) compliant APIs. Implemented as a
    standalone tool using PyQGIS standard libraries, mirroring the
    structure of OverpassTool.

    Auth model differs by provider:
      - Planetary Computer: nearly everything is private and needs a
        per-asset SAS token from a lightweight public sign endpoint
        (see sign_planetary_computer_href).
      - AWS Earth Search (Element84): most collections (e.g. sentinel-2-l2a
        on the public 'sentinel-cogs' bucket) are fully public, no auth at
        all. A few collections (e.g. landsat-c2-l2 on 'usgs-landsat') sit on
        Requester Pays buckets and need real AWS credentials configured via
        configure_aws_credentials(), read through /vsis3/ instead of
        /vsicurl/.

    About spatial coverage:
      The STAC API has NO "coverage ratio" parameter. The 'bbox' filter is a
      plain "intersects" test, so an Item that only touches a corner of the
      bbox is returned just like one that fully contains it. One Sentinel-2
      Item is a single ~110x110 km MGRS tile, so any AOI larger than that
      can never be covered by one Item. Coverage therefore has to be computed
      client-side from each Item's footprint geometry:
        - compute_coverage():            how much of the bbox a result set covers
        - select_items_for_coverage():   pick the Items that reach a target coverage
        - search_stac_items_with_coverage(): search + paginate + select in one call
    """

    # ------------------------------------------------------------------
    # Search helpers (the public entry point is search_stac_items_with_coverage)
    # ------------------------------------------------------------------

    def _send_json_request(self, url: str, body: Optional[dict] = None) -> dict:
        """Blocking GET (body is None) or JSON POST; returns the parsed JSON dict."""
        request = QNetworkRequest(QUrl(url))
        request.setRawHeader(b"Accept", b"application/json")

        network_manager = QgsNetworkAccessManager.instance()

        if body is None:
            reply = network_manager.blockingGet(request)
        else:
            request.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json")
            payload = QByteArray(json.dumps(body, ensure_ascii=False).encode('utf-8'))
            reply = network_manager.blockingPost(request, payload)

        if reply.error() != QNetworkReply.NetworkError.NoError:
            raise RuntimeError(f"STAC search request failed: {reply.errorString()}")

        content = bytes(reply.content()).decode('utf-8')
        if not content:
            raise RuntimeError("The STAC search response is empty. "
                               "Check that the collection id and base_url are correct.")
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise RuntimeError("The STAC search response is not valid JSON. "
                               "Check that the collection id and base_url are correct.") from exc

    @staticmethod
    def _find_next_link(page: dict) -> Optional[dict]:
        for link in page.get('links', []):
            if link.get('rel') == 'next':
                return link
        return None

    @staticmethod
    def _to_rfc3339(date_str: str, end_of_day: bool = False) -> str:
        """
        Normalize a bare date (YYYY-MM-DD) into a full RFC3339 timestamp.
        Some STAC servers (e.g. Earth Search's stac-server) strictly validate
        the 'datetime' parameter against RFC3339 and reject date-only
        strings, even though bare dates are a common convention shown in
        many STAC client docs/examples. Strings that already contain 'T'
        (i.e. already a full timestamp) are returned unchanged.
        """
        if not date_str or 'T' in date_str or date_str == '..':
            return date_str
        return f"{date_str}T23:59:59Z" if end_of_day else f"{date_str}T00:00:00Z"

    @classmethod
    def _normalize_datetime_range(cls, datetime_range: str) -> str:
        """
        Normalize a STAC 'datetime' value (single instant or 'start/end'
        interval, per the STAC API spec, including open-ended '..' bounds)
        so bare dates are expanded to full RFC3339 before being sent.
        """
        if not datetime_range:
            return datetime_range
        if '/' in datetime_range:
            start, end = datetime_range.split('/', 1)
            start = cls._to_rfc3339(start.strip(), end_of_day=False)
            end = cls._to_rfc3339(end.strip(), end_of_day=True)
            return f"{start}/{end}"
        return cls._to_rfc3339(datetime_range.strip(), end_of_day=False)

    def _generate_search_body(self, collections, bbox, datetime_range, query, limit) -> dict:
        """Internal helper to build a STAC API /search JSON request body."""
        body = {
            'collections': collections,
            'limit': limit
        }
        if bbox is not None and bbox != "":
            body['bbox'] = bbox
        if datetime_range:
            body['datetime'] = self._normalize_datetime_range(datetime_range)
        if query:
            body['query'] = query
        return body

    # ------------------------------------------------------------------
    # Spatial coverage
    # ------------------------------------------------------------------

    @staticmethod
    def _geojson_to_geometry(geojson: Optional[dict]) -> QgsGeometry:
        """Convert a GeoJSON Polygon/MultiPolygon dict into a valid QgsGeometry (EPSG:4326)."""
        if not geojson:
            return QgsGeometry()
        gtype = geojson.get('type')
        coords = geojson.get('coordinates')

        def ring(r):
            return '(' + ', '.join(f"{p[0]} {p[1]}" for p in r) + ')'

        def poly(p):
            return '(' + ', '.join(ring(r) for r in p) + ')'

        if gtype == 'Polygon':
            wkt = f"POLYGON{poly(coords)}"
        elif gtype == 'MultiPolygon':
            wkt = "MULTIPOLYGON(" + ', '.join(poly(p) for p in coords) + ")"
        else:
            return QgsGeometry()

        geom = QgsGeometry.fromWkt(wkt)
        if not geom.isNull() and not geom.isGeosValid():
            geom = geom.makeValid()
        return geom

    @staticmethod
    def _make_area_calculator() -> QgsDistanceArea:
        """Ellipsoidal area calculator, so ratios are not distorted by degree-based planar area."""
        da = QgsDistanceArea()
        da.setSourceCrs(QgsCoordinateReferenceSystem('EPSG:4326'),
                        QgsProject.instance().transformContext())
        da.setEllipsoid('WGS84')
        return da

    @staticmethod
    def _area(da: QgsDistanceArea, geom: Optional[QgsGeometry]) -> float:
        if geom is None or geom.isNull() or geom.isEmpty():
            return 0.0
        return da.measureArea(geom)

    def _clip_features(self, features: List[dict], bbox_geom: QgsGeometry) -> List[dict]:
        """
        For each Item, intersect its footprint with the bbox. Items that do
        not actually overlap the bbox area (e.g. only touching its edge) are dropped.
        """
        entries = []
        for feat in features:
            geom = self._geojson_to_geometry(feat.get('geometry'))
            if geom.isNull() or geom.isEmpty():
                continue
            clipped = geom.intersection(bbox_geom)
            if clipped.isNull() or clipped.isEmpty():
                continue
            props = feat.get('properties', {}) or {}
            cloud = props.get('eo:cloud_cover')
            dt = props.get('datetime') or ''
            entries.append({
                'feat': feat,
                'geom': clipped,
                'cloud': float(cloud) if cloud is not None else 0.0,
                'has_cloud': cloud is not None,
                'date': dt[:10],
                'datetime': dt,
            })
        return entries

    def compute_coverage(self, stac_data: dict, bbox: List[float]) -> dict:
        """
        Compute how much of the bbox is covered by a STAC search result.

        :param stac_data: STAC search response (FeatureCollection).
        :param bbox: [xmin, ymin, xmax, ymax] in EPSG:4326.
        :return: {
            'bbox_area_km2': float,
            'total_coverage': float,      # union of all footprints / bbox area, 0..1
            'items': [{item_id, datetime, cloud_cover, coverage}, ...]  # per-Item share of bbox
        }
        """
        bbox_geom = QgsGeometry.fromRect(QgsRectangle(*bbox))
        da = self._make_area_calculator()
        bbox_area = self._area(da, bbox_geom)
        if bbox_area <= 0:
            raise ValueError("Invalid bbox: area is zero.")

        entries = self._clip_features(stac_data.get('features', []), bbox_geom)
        union = QgsGeometry.unaryUnion([e['geom'] for e in entries]) if entries else QgsGeometry()
        items = [{
            'item_id': e['feat'].get('id'),
            'datetime': e['datetime'],
            'cloud_cover': e['cloud'] if e['has_cloud'] else None,
            'coverage': min(self._area(da, e['geom']) / bbox_area, 1.0),
        } for e in entries]

        return {
            'bbox_area_km2': bbox_area / 1e6,
            'total_coverage': min(self._area(da, union) / bbox_area, 1.0),
            'items': items,
        }

    def _greedy_cover(self, entries: List[dict], bbox_geom: QgsGeometry, bbox_area: float,
                      da: QgsDistanceArea, target: float, min_gain: float):
        """
        Greedy set cover: repeatedly take the Item adding the most new area
        (weighted by clearness = 1 - cloud/100) until 'target' is reached or
        no remaining Item adds at least 'min_gain' (fraction of bbox).
        Returns (chosen_entries, covered_ratio).
        """
        remaining = QgsGeometry(bbox_geom)
        pool = list(entries)
        chosen = []
        covered = 0.0

        while pool and covered < target:
            best, best_score, best_gain = None, 0.0, 0.0
            for e in pool:
                gain = self._area(da, e['geom'].intersection(remaining)) / bbox_area
                if gain < min_gain:
                    continue
                score = gain * max(1.0 - e['cloud'] / 100.0, 0.05)
                if score > best_score:
                    best, best_score, best_gain = e, score, gain
            if best is None:
                break
            best['gain'] = best_gain
            chosen.append(best)
            pool.remove(best)
            remaining = remaining.difference(best['geom'])
            covered = 1.0 - self._area(da, remaining) / bbox_area

        return chosen, max(0.0, min(covered, 1.0))

    def select_items_for_coverage(
            self,
            stac_data: dict,
            bbox: List[float],
            target_coverage: float = 0.95,
            strategy: str = 'single_date',
            min_gain: float = 0.005,
            max_items: Optional[int] = None
    ) -> dict:
        """
        Pick the subset of Items that covers the bbox to the requested ratio.

        Strategies:
          - 'single_date' (default): group Items by acquisition date, pick the
            date whose Items cover the bbox best (among dates reaching the
            target: the one with the lowest mean cloud cover), then drop
            redundant/duplicate Items inside that date. Gives a radiometrically
            consistent mosaic from one overpass.
          - 'greedy': ignore dates, choose Items across the whole time range
            with greedy set cover (cloud-weighted). Reaches the target with the
            fewest Items, but mixes acquisition dates.

        If the target cannot be reached, the best achievable result is returned
        and coverage['reached'] is False.

        :param stac_data: STAC search response (FeatureCollection) containing
            MANY Items, i.e. all pages of a search, not just the first page.
        :param bbox: [xmin, ymin, xmax, ymax] in EPSG:4326.
        :param target_coverage: Desired covered fraction of the bbox, 0..1.
        :param strategy: 'single_date' or 'greedy'.
        :param min_gain: Ignore Items adding less than this fraction of the bbox.
        :param max_items: If set, cap the number of returned selected Items.
        :return: FeatureCollection of the selected Items plus a 'coverage' summary dict.
            Compatible with list_stac_assets().
        """
        if strategy not in ('single_date', 'greedy'):
            raise ValueError("strategy must be 'single_date' or 'greedy'.")

        bbox_geom = QgsGeometry.fromRect(QgsRectangle(*bbox))
        da = self._make_area_calculator()
        bbox_area = self._area(da, bbox_geom)
        if bbox_area <= 0:
            raise ValueError("Invalid bbox: area is zero.")

        entries = self._clip_features(stac_data.get('features', []), bbox_geom)
        if not entries:
            raise ValueError("No STAC items overlap the bbox. Try widening the bbox, "
                             "datetime range, or relaxing the cloud-cover filter.")

        if strategy == 'single_date':
            groups = defaultdict(list)
            for e in entries:
                groups[e['date']].append(e)

            best_key, best_group = None, None
            for date, group in groups.items():
                union = QgsGeometry.unaryUnion([e['geom'] for e in group])
                cov = self._area(da, union) / bbox_area
                mean_cloud = sum(e['cloud'] for e in group) / len(group)
                reached = cov >= target_coverage
                # Reached target -> prefer clearer; otherwise -> prefer larger coverage.
                key = (reached, -mean_cloud if reached else cov)
                if best_key is None or key > best_key:
                    best_key, best_group = key, group
            candidates = best_group
        else:
            candidates = entries

        chosen, _ = self._greedy_cover(candidates, bbox_geom, bbox_area, da,
                                             target_coverage, min_gain)

        if max_items is not None:
            chosen = chosen[:max_items]

        return {
            'type': 'FeatureCollection',
            'features': [e['feat'] for e in chosen]
        }

    def search_stac_items_with_coverage(
            self,
            collections: List[str],
            bbox: List[float],
            datetime_range: Optional[str] = None,
            query: Optional[Dict] = None,
            base_url: str = 'https://planetarycomputer.microsoft.com/api/stac/v1',
            target_coverage: float = 0.95,
            strategy: str = 'single_date',
            max_items: int = 5
    ) -> dict:
        """
        One-call helper: fetch up to max_items matching Items in a SINGLE
        request (no pagination), then select the ones that reach
        target_coverage of the bbox.

        Example:
            tool.search_stac_items_with_coverage(
                collections=['sentinel-2-l2a'],
                bbox=[118.3345905, 31.2267477, 119.2395068, 32.615778],
                datetime_range='2024-01-01/2024-12-31',
                query={'eo:cloud_cover': {'lt': 20}},
                base_url='https://earth-search.aws.element84.com/v1',
                target_coverage=0.95)

        Items come back newest-first (the server default), so only the most
        recent max_items Items are evaluated.
        Servers cap 'limit' (commonly at about 1000), so keep max_items below that.

        :param max_items: Max Items to fetch (sent as the STAC 'limit').
        :return: FeatureCollection of selected Items + 'coverage' summary
            (see select_items_for_coverage()).
        """
        if not bbox:
            raise ValueError("bbox is required to evaluate spatial coverage.")

        # 1. Single request; 'limit' is the number of Items returned.
        body = self._generate_search_body(collections, bbox, datetime_range, query, 20)
        endpoint = base_url.rstrip('/') + '/search'
        page = self._send_json_request(endpoint, body)

        stac_data = {
            'type': 'FeatureCollection',
            'features': page.get('features', [])
        }

        # 2. Evaluate footprints against the bbox and pick Items reaching the target.
        if not stac_data['features']:
            raise ValueError("No STAC items found. Try widening the bbox, datetime range, "
                             "or double-check the collection id.")

        return self.select_items_for_coverage(stac_data, bbox, target_coverage, strategy, max_items=max_items)

    # ------------------------------------------------------------------
    # Assets / auth / loading
    # ------------------------------------------------------------------

    def list_stac_assets(self, stac_data: dict, data_only: bool = True) -> List[dict]:
        """
        Parse a STAC search response (GeoJSON FeatureCollection of Items)
        into a flat list of downloadable assets with their metadata.

        Items typically mix several asset roles: 'data' (the actual pixel
        data you want, e.g. 'vv'/'vh' GeoTIFFs for Sentinel-1), 'metadata'
        (e.g. 'safe-manifest', an XML file describing the product -- NOT
        loadable as a raster/vector layer), and 'thumbnail'/'overview'. Set
        data_only=True to skip everything except actual imagery assets.

        :param stac_data: Parsed STAC search response (GeoJSON FeatureCollection dict).
        :param data_only: If True, only return assets whose 'roles' include 'data'.
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
                    roles = asset.get('roles', [])
                    if data_only and 'data' not in roles:
                        continue
                    assets.append({
                        'item_id': item_id,
                        'asset_key': asset_key,
                        'href': asset.get('href'),
                        'media_type': asset.get('type'),
                        'roles': roles
                    })
            return assets

        except Exception as e:
            raise e

    def configure_aws_credentials(
            self,
            access_key_id: str,
            secret_access_key: str,
            session_token: Optional[str] = None
    ):
        """
        Configure AWS credentials for GDAL so it can read from Requester Pays
        S3 buckets (e.g. 'usgs-landsat' on Earth Search). This is not a
        per-asset sign step like Planetary Computer -- it's a one-time,
        per-session setup: GDAL/vsis3 picks up standard AWS environment
        variables automatically for every subsequent /vsis3/ read.

        The user must bring their own AWS account/credentials here (this is
        the Tier-2 "account login" case from the auth-tier strategy, not
        Tier-1 "call a public sign endpoint"). Store access_key_id /
        secret_access_key via QGIS's Authentication Manager rather than
        keeping them as plain strings in memory or on disk.

        :param access_key_id: AWS access key id.
        :param secret_access_key: AWS secret access key.
        :param session_token: Optional session token (for temporary/STS credentials).
        """
        os.environ['AWS_ACCESS_KEY_ID'] = access_key_id
        os.environ['AWS_SECRET_ACCESS_KEY'] = secret_access_key
        if session_token:
            os.environ['AWS_SESSION_TOKEN'] = session_token
        # Required for GDAL to accept billing responsibility on Requester Pays buckets.
        os.environ['AWS_REQUEST_PAYER'] = 'requester'

    @staticmethod
    def _to_vsis3_path(href: str) -> str:
        """
        Convert a virtual-hosted-style public HTTPS S3 URL, e.g.
        'https://usgs-landsat.s3.us-west-2.amazonaws.com/collection02/...tif'
        (or an equivalent 's3://bucket/key' URI) into a GDAL /vsis3/ virtual
        path: '/vsis3/usgs-landsat/collection02/...tif'

        /vsis3/ (instead of /vsicurl/) is required so GDAL signs the request
        with AWS SigV4 credentials -- this is what actually lets GDAL read a
        Requester Pays bucket; there is no separate "sign the URL" call for
        this path, unlike Planetary Computer.
        """
        parsed = urlparse(href)
        bucket = parsed.netloc.split('.s3')[0]
        return f"/vsis3/{bucket}{parsed.path}"

    def sign_planetary_computer_href(
            self,
            href: str,
            sign_base_url: str = 'https://planetarycomputer.microsoft.com/api/sas/v1/sign',
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
            network_manager = QgsNetworkAccessManager.instance()
            reply = network_manager.blockingGet(request)

            if reply.error() != QNetworkReply.NetworkError.NoError:
                raise RuntimeError(f"Failed to sign STAC asset URL: {reply.errorString()}")

            content = bytes(reply.content()).decode('utf-8')
            signed = json.loads(content)
            return signed.get('href', href)

        except Exception as e:
            raise e

    def load_stac_asset_to_map(
            self,
            href: str,
            layer_name: str = "STAC Asset",
            is_vector: bool = False,
            requester_pays: bool = False
    ):
        """
        Load a single STAC asset directly into the QGIS project as a raster or
        vector layer. Most STAC assets (Cloud-Optimized GeoTIFFs on public
        buckets like Earth Search's 'sentinel-cogs', or already-signed
        Planetary Computer URLs) can be opened directly by GDAL/OGR over
        HTTP via the /vsicurl/ virtual file system, without a manual
        download-and-extract step.

        Whether an asset sits on a Requester Pays bucket is a property of
        the data provider/collection, not something reliably inferable from
        the URL itself -- bucket names change and new providers appear
        faster than any hardcoded list could track. The caller (who chose
        the collection/base_url in search_stac_items_with_coverage) is expected to know
        this and pass requester_pays explicitly.

        :param href: Direct asset URL (already signed, if the provider requires it).
        :param layer_name: Name to assign the new layer.
        :param is_vector: True to load via OGR (QgsVectorLayer), False for GDAL raster.
        :param requester_pays: True if this asset's bucket is Requester Pays --
            routes through /vsis3/ (AWS SigV4) instead of /vsicurl/. Requires
            configure_aws_credentials() to have been called beforehand.
        """
        try:
            if requester_pays:
                # Needs AWS SigV4 auth -- configure_aws_credentials() must have
                # been called already, or this will fail with an access-denied error.
                gdal_path = self._to_vsis3_path(href)
            else:
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
