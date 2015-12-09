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

from abc import ABCMeta, abstractmethod


class AbstractFeatureRow(object):
    """
    A featureset row

    Each row consists of a list of arrays of doubles
    """

    __metaclass__ = ABCMeta

    def __init__(self, names=None, values=None,
                 infonames=None, infovalues=None):
        self._names = names
        self._values = values
        self._infonames = None
        self._infovalues = None

    @abstractmethod
    def __getitem__(self, key):
        pass

    @abstractmethod
    def __setitem__(self, key, value):
        pass

    @property
    def names(self):
        return self._names

    @property
    def values(self):
        return self._values


class AbstractFeatureStore(object):
    """
    A single feature store including metadata columns

    Each entry in a feature store consists of a FeatureRow
    """

    __metaclass__ = ABCMeta

    @abstractmethod
    def store(self, meta, values):
        """
        Store a single FeatureRow

        :param meta: The metadata values
        :param values: The feature values
        """
        pass

    @abstractmethod
    def fetch_by_metadata(self, meta, raw=False):
        """
        Retrieve FeatureRows by matching metadata

        :param meta: Either a dict of fieldname=value, or an array of
               metadata values to be match (use <None> to ignore a column)
        :return: FeatureRows
        """
        pass

    @abstractmethod
    def filter(self, conditions):
        """
        Retrieve the features which fulfill the conditions

        :param conditions: The feature query conditions
        :return: A list of FeatureRows

        TODO: Decide on the query syntax
        """
        pass


class AbstractFeatureStoreManager(object):
    """
    Manages multiple feature stores
    """

    __metaclass__ = ABCMeta

    @abstractmethod
    def create(self, featureset_name, names, widths):
        """
        Create a new feature store

        :param featureset_name: The featureset identifier
        :param names: A list of feature names
        :param widths: A list of widths of each feature
        """
        pass

    @abstractmethod
    def get(self, featureset_name):
        """
        Get an existing feature store

        :param featureset_name: The featureset identifier
        :return: An AbstractFeatureStore
        """
        pass
