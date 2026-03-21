# -*- coding: utf-8 -*-
"""
/***************************************************************************
                                 Qt5/Qt6 compatibility module
    This module provides compatibility handling for both Qt5 and Qt6 versions
  within the QGIS PyQt environment. It detects the Qt major version at runtime
  and provides flags for conditional code execution based on the version.
                              -------------------
        begin                : 2026-03-18
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

from qgis.PyQt.QtCore import Qt, QT_VERSION_STR, QStandardPaths
from qgis.PyQt.QtNetwork import QNetworkReply, QNetworkRequest
from qgis.PyQt.QtWidgets import QDialog, QMessageBox
from qgis.PyQt.QtGui import QTextDocument

QT_MAJOR_VERSION = int(QT_VERSION_STR.split(".")[0])
IS_QT5 = QT_MAJOR_VERSION == 5
IS_QT6 = QT_MAJOR_VERSION == 6

if IS_QT5:
    RightDockWidgetArea = Qt.RightDockWidgetArea
    NoError = QNetworkReply.NoError
    TempLocation = QStandardPaths.TempLocation
    ArrowCursor = Qt.ArrowCursor
    UserRole = Qt.UserRole
    Accepted = QDialog.Accepted
    PointingHandCursor = Qt.PointingHandCursor
    ContentTypeHeader = QNetworkRequest.ContentTypeHeader
    DirectConnection = Qt.DirectConnection
    QMessageBoxOK = QMessageBox.Ok
    QMessageBoxCancel = QMessageBox.Cancel
    QMessageBoxYes = QMessageBox.Yes
    QMessageBoxAcceptRole = QMessageBox.AcceptRole
    QMessageBoxCritical = QMessageBox.Critical
    SmoothTransformation = Qt.SmoothTransformation
    IgnoreAspectRatio = Qt.IgnoreAspectRatio
    ImageResource = QTextDocument.ImageResource

if IS_QT6:
    RightDockWidgetArea = Qt.DockWidgetArea.RightDockWidgetArea
    NoError = QNetworkReply.NetworkError.NoError
    TempLocation = QStandardPaths.StandardLocation.TempLocation
    ArrowCursor = Qt.CursorShape.ArrowCursor
    UserRole = Qt.ItemDataRole.UserRole
    Accepted = QDialog.DialogCode.Accepted
    PointingHandCursor = Qt.CursorShape.PointingHandCursor
    ContentTypeHeader = QNetworkRequest.KnownHeaders.ContentTypeHeader
    DirectConnection = Qt.ConnectionType.DirectConnection
    QMessageBoxOK = QMessageBox.StandardButton.Ok
    QMessageBoxCancel = QMessageBox.StandardButton.Cancel
    QMessageBoxYes = QMessageBox.StandardButton.Yes
    QMessageBoxAcceptRole = QMessageBox.ButtonRole.AcceptRole
    QMessageBoxCritical = QMessageBox.Icon.Critical
    SmoothTransformation = Qt.TransformationMode.SmoothTransformation
    IgnoreAspectRatio = Qt.AspectRatioMode.IgnoreAspectRatio
    ImageResource = QTextDocument.ResourceType.ImageResource
