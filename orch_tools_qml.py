# -*- coding: utf-8 -*-
"""
/***************************************************************************
                                  Define Tools for QML Styles
   Define all tools related to QGIS QML style templates for orchestration.
                               -------------------
         begin                : 2026-07-16
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

from typing import Optional

class QmlStyleTool:
    """
    Provides QML style templates for QGIS vector layers.
    """

    def get_qml_template(self, style_type: str) -> str:
        """
        Return a QML style template based on the style type.

        :param style_type: 'raster' for raster layers or 'vector' for vector layers.
        :return: QML XML string.
        """
        if style_type == "raster":
            return self._get_raster_style()
        elif style_type == "vector":
            return self._get_vector_style()
        else:
            raise ValueError(f"Unsupported style type: {style_type}. Use 'raster' or 'vector'.")

    def _get_raster_style(self) -> str:
        return """<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis version="3.0" styleCategories="Symbology">
  <pipe>
    <!-- type="singlebandpseudocolor" This represents single-band pseudocolor; band="1" indicates that it is applied in band 1. -->
    <rasterrenderer type="singlebandpseudocolor" alphaBand="-1" opacity="1" band="1" classificationMin="0" classificationMax="3000">
      <rasterTransparency/>
      <minMaxOrigin>
        <limits>None</limits>
        <extent>WholeRaster</extent>
        <statAccuracy>Estimated</statAccuracy>
        <cumulativeCutLower>0.02</cumulativeCutLower>
        <cumulativeCutUpper>0.98</cumulativeCutUpper>
        <stdDevFactor>2</stdDevFactor>
      </minMaxOrigin>
      <rastershader>
        <!-- colorRampType="INTERPOLATED" Represents color gradient interpolation -->
        <colorrampshader minimumValue="0" maximumValue="3000" colorRampType="INTERPOLATED" clip="0" classificationMode="1">
          <item alpha="255" value="0" color="#228b22" label="Low"/>
          <item alpha="255" value="1200" color="#ffff00" label="Mid"/>
          <item alpha="255" value="2000" color="#8b4513" label="High"/>
          <item alpha="255" value="3000" color="#ffffff" label="Peak"/>
        </colorrampshader>
      </rastershader>
    </rasterrenderer>
  </pipe>
</qgis>"""

    def _get_vector_style(self) -> str:
        return """<!-- 
Please select the corresponding <symbol> structure in <symbols> to generate the vector layer based on its geometry type (Point, Line, Polygon).
- For polygons, use `type="fill"` and `SimpleFill`. Attribute names must include `color`, `outline_color`, etc.
- For lines, use `type="line"` and `SimpleLine`. Attribute names must include `line_color`, `line_width`, `line_style`, etc.
- For points, use `type="marker"` and `SimpleMarker`. Attribute names must include `color`, `outline_color`, `size`, etc.
-->

<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis version="3.28.0-Firenze" styleCategories="AllStyleCategories">
  <renderer-v2 type="categorizedSymbol" attr="YOUR_FIELD_HERE">
    <categories>
      <!-- Category items are generated based on requirements -->
      <category render="true" value="value1" symbol="0" label="Label1"/>
    </categories>
    
    <symbols>
      
      <!-- Type 1: If the layer is a polygon, please use this structure -->
      <symbol type="fill" name="0" alpha="1" clip_to_extent="1" force_rhr="0">
        <layer pass="0" class="SimpleFill" locked="0">
          <prop k="color" v="255,200,200,255"/> <!-- Fill color -->
          <prop k="outline_color" v="35,35,35,255"/> <!-- Border color -->
          <prop k="outline_style" v="solid"/>
          <prop k="outline_width" v="0.26"/>
          <prop k="style" v="solid"/>
        </layer>
      </symbol>

      <!-- Type 2: Use this structure if the layer is a line -->
      <symbol type="line" name="1" alpha="1" clip_to_extent="1" force_rhr="0">
        <layer pass="0" class="SimpleLine" locked="0">
          <prop k="line_color" v="255,0,0,255"/> <!-- Line color -->
          <prop k="line_width" v="1.0"/> <!-- line width -->
          <prop k="line_style" v="solid"/>
        </layer>
      </symbol>

      <!-- Type 3: Use this structure if the layer is a Point -->
      <symbol type="marker" name="2" alpha="1" clip_to_extent="1" force_rhr="0">
        <layer pass="0" class="SimpleMarker" locked="0">
          <prop k="name" v="circle"/> <!-- Shapes: circle, square, star, etc. -->
          <prop k="color" v="0,255,0,255"/> <!-- Fill color -->
          <prop k="outline_color" v="35,35,35,255"/> <!-- Border color -->
          <prop k="size" v="2.0"/> <!-- Size of the dot -->
        </layer>
      </symbol>

    </symbols>
  </renderer-v2>
</qgis>"""