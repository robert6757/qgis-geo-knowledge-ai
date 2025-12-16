# -*- coding: utf-8 -*-
"""
/***************************************************************************
                        Geo Knowledge AI Plugin
 This plugin provides Geo Knowledge AI, combining a LLM with the professional
  GIS knowledge database.
                             -------------------
        begin                : 2025-12-15
        copyright            : (C) 2025 by phoenix-gis
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
 This script initializes the plugin, making it known to QGIS.
"""

# noinspection PyPep8Naming
def classFactory(iface):  # pylint: disable=invalid-name
    """Load GeoKnowledgeAI class from file geo_knowledge_ai.

    :param iface: A QGIS interface instance.
    :type iface: QgsInterface
    """
    #
    from .geo_knowledge_ai import GeoKnowledgeAI
    return GeoKnowledgeAI(iface)
