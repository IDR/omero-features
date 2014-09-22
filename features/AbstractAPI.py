#!/usr/bin/env python
# -*- coding: utf-8 -*-

#
# Copyright (C) 2014 University of Dundee & Open Microscopy Environment.
# All rights reserved.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

"""
OMERO.features abstract API
"""


class AbstractFeatureRow(object):
    """
    A featureset row

    Each row consists of a list of arrays of doubles
    """
    pass

    def __init__(self, widths=None, names=None, values=None):
        self._widths = widths
        self._names = names
        self._values = values

    def __getitem__(self, key):
        raise Exception('Not implemented')

    def __setitem__(self, key, value):
        raise Exception('Not implemented')

    @property
    def names(self):
        return self._names

    @property
    def widths(self):
        return self._widths

    @property
    def values(self):
        return self._values


class AbstractFeatureStorageManager(object):
    """
    Manages multiple feature stores

    Each entry in a feature store consists of a FeatureRow
    """

    def create(self, featureset_name, names, widths):
        """
        Create a new feature store

        :param featureset_name: The featureset identifier
        :param names: A list of feature names
        :param widths: A list of widths of each feature
        """
        raise Exception('Not implemented')

    def store(self, featureset_name, image_id, roi_id, values):
        """
        Store a row of features identified by Image ID and/or ROI ID

        :param featureset_name: The featureset identifier
        :param image_id: The Image ID
        :param roi_id: The ROI ID, may be None
        :params values: A list of FeatureRows
        """
        raise Exception('Not implemented')

    def fetch_by_image(self, featureset_name, image_id):
        """
        Retrieve a single FeatureRow by Image ID

        :param featureset_name: The featureset identifier
        :param image_id: The Image ID
        :return: A FeatureRow
        """
        raise Exception('Not implemented')

    def fetch_by_roi(self, featureset_name, roi_id):
        """
        Retrieve a single FeatureRow by ROI ID

        :param featureset_name: The featureset identifier
        :param roi_id: The ROI ID
        :return: A FeatureRow
        """
        raise Exception('Not implemented')

    def fetch_all(self, featureset_name, image_id):
        """
        Retrieve all rows of features identified by Image ID

        :param featureset_name: The featureset identifier
        :param image_id: The Image ID
        :return: A list of FeatureRows
        """
        raise Exception('Not implemented')


    def filter(self, featureset_name, conditions):
        """
        Retrieve the features and Image/ROI IDs which fulfill the conditions

        :param featureset_name: The featureset identifier
        :param conditions: The feature query conditions
        :return: A list of (Image-ID, ROI-ID, FeatureRow) triplets
        """
        raise Exception('Not implemented')
