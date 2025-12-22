# -*- coding: utf-8 -*-
"""
/***************************************************************************
                        Geo Knowledge AI Plugin
 This plugin provides Geo Knowledge AI, combining a LLM with the professional
  GIS knowledge database.

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
"""
from qgis.PyQt.QtCore import QSettings, QTranslator, QCoreApplication, Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction
from .global_defs import USER_ID_TAG
import uuid
from datetime import datetime

# Initialize Qt resources from file resources_rc.py
# Extend to load root directory.
import sys
import os.path
sys.path.append(os.path.dirname(__file__))
from .resources_rc import *

# Import the code for the DockWidget
from .geo_knowledge_ai_dockwidget import GeoKnowledgeAIDockWidget

class GeoKnowledgeAI:
    """QGIS Plugin Implementation."""

    def __init__(self, iface):
        """Constructor.

        :param iface: An interface instance that will be passed to this class
            which provides the hook by which you can manipulate the QGIS
            application at run time.
        :type iface: QgsInterface
        """
        # Save reference to the QGIS interface
        self.iface = iface

        # initialize plugin directory
        self.plugin_dir = os.path.dirname(__file__)

        # initialize locale
        locale = QSettings().value('locale/userLocale')
        locale_path = os.path.join(
            self.plugin_dir,
            'i18n',
            'GeoKnowledgeAI_{}.qm'.format(locale))

        # initialize uid
        if not QSettings().value(USER_ID_TAG):
            date_str = datetime.now().strftime("%Y%m%d")
            uid_short = uuid.uuid4().hex[:6]
            QSettings().setValue(USER_ID_TAG, f"{date_str}-{uid_short}")

        if os.path.exists(locale_path):
            self.translator = QTranslator()
            self.translator.load(locale_path)
            QCoreApplication.installTranslator(self.translator)

        # Declare instance attributes
        self.actions = []
        self.menu = self.tr(u'&Geo Knowledge AI')
        self.toolbar = self.iface.addToolBar(self.tr(u'GeoKnowledgeAI'))
        self.toolbar.setObjectName(u'GeoKnowledgeAI')

        self.dockwidget = None

    # noinspection PyMethodMayBeStatic
    def tr(self, message):
        """Get the translation for a string using Qt translation API.

        We implement this ourselves since we do not inherit QObject.

        :param message: String for translation.
        :type message: str, QString

        :returns: Translated version of message.
        :rtype: QString
        """
        # noinspection PyTypeChecker,PyArgumentList,PyCallByClass
        return QCoreApplication.translate('GeoKnowledgeAI', message)


    def add_action(
        self,
        icon_path,
        text,
        callback,
        enabled_flag=True,
        add_to_menu=True,
        add_to_toolbar=True,
        status_tip=None,
        whats_this=None,
        parent=None):
        """Add a toolbar icon to the toolbar.

        :param icon_path: Path to the icon for this action. Can be a resource
            path (e.g. ':/plugins/foo/bar.png') or a normal file system path.
        :type icon_path: str

        :param text: Text that should be shown in menu items for this action.
        :type text: str

        :param callback: Function to be called when the action is triggered.
        :type callback: function

        :param enabled_flag: A flag indicating if the action should be enabled
            by default. Defaults to True.
        :type enabled_flag: bool

        :param add_to_menu: Flag indicating whether the action should also
            be added to the menu. Defaults to True.
        :type add_to_menu: bool

        :param add_to_toolbar: Flag indicating whether the action should also
            be added to the toolbar. Defaults to True.
        :type add_to_toolbar: bool

        :param status_tip: Optional text to show in a popup when mouse pointer
            hovers over the action.
        :type status_tip: str

        :param parent: Parent widget for the new action. Defaults None.
        :type parent: QWidget

        :param whats_this: Optional text to show in the status bar when the
            mouse pointer hovers over the action.

        :returns: The action that was created. Note that the action is also
            added to self.actions list.
        :rtype: QAction
        """

        icon = QIcon(icon_path)
        action = QAction(icon, text, parent)
        action.triggered.connect(callback)
        action.setEnabled(enabled_flag)

        if status_tip is not None:
            action.setStatusTip(status_tip)

        if whats_this is not None:
            action.setWhatsThis(whats_this)

        if add_to_toolbar:
            self.toolbar.addAction(action)

        if add_to_menu:
            self.iface.addPluginToMenu(
                self.menu,
                action)

        self.actions.append(action)

        return action


    def initGui(self):
        """Create the menu entries and toolbar icons inside the QGIS GUI."""

        icon_path = ':/plugins/geo_knowledge_ai/icon.png'
        self.add_action(
            icon_path,
            text=self.tr(u'Geo Knowledge AI'),
            callback=self.run,
            parent=self.iface.mainWindow())

        # show docking widget in initializing.
        self.show_dockwidget(True)

    #--------------------------------------------------------------------------

    def onClosePlugin(self):
        """Cleanup necessary items here when plugin dockwidget is closed"""

        #print "** CLOSING GeoKnowledgeAI"

        # disconnects
        self.dockwidget.closingPlugin.disconnect(self.onClosePlugin)

        # remove this statement if dockwidget is to remain
        # for reuse if plugin is reopened
        # Commented next statement since it causes QGIS crashe
        # when closing the docked window:
        # self.dockwidget = None

    def unload(self):
        """Removes the plugin menu item and icon from QGIS GUI."""

        #print "** UNLOAD GeoKnowledgeAI"

        for action in self.actions:
            self.iface.removePluginMenu(
                self.tr(u'&Geo Knowledge AI'),
                action)
            self.iface.removeToolBarIcon(action)
        # remove the toolbar
        del self.toolbar

    #--------------------------------------------------------------------------

    def run(self):
        """Run method that loads and starts the plugin"""
        # switch plugin active.
        dockwidget_visible = self.dockwidget.isVisible()
        self.show_dockwidget(not dockwidget_visible)

    def show_dockwidget(self, is_show):
        if self.dockwidget == None:
            # Create the dockwidget (after translation) and keep reference
            self.dockwidget = GeoKnowledgeAIDockWidget(self.iface)

            # connect to provide cleanup on closing of dockwidget
            self.dockwidget.closingPlugin.connect(self.onClosePlugin)

            # add the dockwidget
            self.iface.addDockWidget(Qt.RightDockWidgetArea, self.dockwidget)

        if is_show:
            self.dockwidget.show()
        else:
            self.dockwidget.hide()

