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
Implementation of the OMERO.features AbstractAPI
"""

from AbstractAPI import (
    AbstractFeatureRow, AbstractFeatureStore, AbstractFeatureStoreManager)
import omero
import omero.clients
from omero.rtypes import unwrap, wrap

import itertools
import re

import logging
log = logging.getLogger(__name__)


DEFAULT_NAMESPACE = 'omero.features/0.1'
DEFAULT_FEATURE_SUBSPACE = 'features'
DEFAULT_ANNOTATION_SUBSPACE = 'source'

FEATURE_NAME_RE = r'^[A-Za-z0-9][A-Za-z0-9_ \-\(\)\[\]\{\}\.]*$'

# Column type strings
COLUMN_TYPES = [m.group(1) for m in (
    re.match('([^_]\w+)Column$', s) for s in dir(omero.grid)) if m]
META_COLUMN_TYPES = [t for t in COLUMN_TYPES if not t.endswith('Array')]

# Indicates the object ID is unknown
NOID = -1


class TableStoreException(Exception):
    """
    Parent class for exceptions occuring in the OMERO.features tables store
    implementation
    """
    pass


class OmeroTableException(TableStoreException):
    """
    Errors whilst using the OMERO.tables API
    """
    pass


class NoTableMatchException(TableStoreException):
    """
    No matching annotation was found when searching for a table
    """
    pass


class TooManyTablesException(TableStoreException):
    """
    Too many matching annotation were found when searching for a table
    """
    pass


class TableUsageException(TableStoreException):
    """
    Invalid usage of this implementation of the Features API
    """
    pass


class FeaturePermissionException(TableStoreException):
    """
    Client does not have permission to access a feature table
    """
    pass


class FeatureRowException(TableStoreException):
    """
    Errors in a FeatureRow object
    """
    pass


class FeatureRow(AbstractFeatureRow):

    def __init__(self, names=None, values=None,
                 infonames=None, infovalues=None):
        if not names and not values:
            raise FeatureRowException(
                'At least one of names or values must be provided')

        if names and values and len(names) != len(values):
            raise FeatureRowException(
                'names and values must have the same number of elements')
        self._names = names

        self._values = None
        if values:
            self.values = values

        self._infonames = infonames
        self._infovalues = None
        if infovalues:
            self.infovalues = infovalues

        self._namemap = {}
        self._infonamemap = {}

    def _get_index(self, name):
        try:
            return self._namemap[name], False
        except KeyError:
            pass
        try:
            return self._infonamemap[name], True
        except KeyError:
            pass

        if self._names and not self._namemap:
            self._namemap = dict(ni for ni in zip(
                self._names, xrange(len(self._names))))
        if self._infonames and not self._infonamemap:
            self._infonamemap = dict(ni for ni in zip(
                self._infonames, xrange(len(self._infonames))))
        try:
            return self._namemap[name], False
        except KeyError:
            return self._infonamemap[name], True

    def __getitem__(self, key):
        i, m = self._get_index(key)
        if m:
            return self.infovalues[i]
        return self.values[i]

    def __setitem__(self, key, value):
        i, m = self._get_index(key)
        if m:
            self.infovalues[i] = value
        else:
            self.values[i] = value

    @property
    def names(self):
        return self._names

    @property
    def values(self):
        return self._values

    @values.setter
    def values(self, value):
        if self._names:
            w = len(self._names)
        elif self._values:
            w = len(self._values)
        else:
            w = len(value)
        if len(value) != w:
            raise FeatureRowException(
                'Expected %d elements, received %d' % (w, len(value)))
        self._values = value

    @values.deleter
    def values(self):
        del self._values

    @property
    def infonames(self):
        return self._infonames

    @property
    def infovalues(self):
        return self._infovalues

    @infovalues.setter
    def infovalues(self, value):
        if self._infonames and len(self._infonames) != len(value):
            raise FeatureRowException(
                'Expected %d elements, received %d' % (
                    len(self._infonames), len(value)))
        self._infovalues = value

    @infovalues.deleter
    def infovalues(self):
        del self._infovalues

    def __repr__(self):
        return (
            '%s(names=%r, values=%r, infonames=%r, infovalues=%r)' %
            (self.__class__.__name__, self._names, self._values,
             self._infonames, self._infovalues))


class PermissionsHandler(object):
    """
    Handles permissions checks on objects handled by OMERO.features.

    These are stricter than the OMERO model: only owners are allowed to
    write or edit objects. Annotation permissions are as standard.
    """

    def __init__(self, session):
        self.context = session.getAdminService().getEventContext()

    def get_userid(self):
        return self.context.userId

    def can_annotate(self, obj):
        p = obj.getDetails().getPermissions()
        return p.canAnnotate()

    def can_edit(self, obj):
        d = obj.getDetails()
        return (self.get_userid() == unwrap(d.getOwner().id) and
                d.getPermissions().canEdit())


class FeatureTable(AbstractFeatureStore):
    """
    A feature store.
    Each row is an Image-ID, Roi-ID and a single fixed-width DoubleArray
    """

    def __init__(self, session, name, ft_space, ann_space, ownerid,
                 metadesc=None, coldesc=None, ofileid=None, noopen=False):
        """
        :param session: An OMERO session
        :param name: The feature table name
        :param ft_space: The feature table namespace
        :param ann_space: The feature annotation namespace
        :param ownerid: User ID of the table owner
        :param metadesc: See :meth:`open_or_create_table`
        :param coldesc: See :meth:`open_or_create_table`
        :param ofileid: See :meth:`open_or_create_table`
        :param noopen: Don't automatically open a table (manually call
            :meth:new_table or :meth:open_table)
        """
        self.session = session
        self.perms = PermissionsHandler(session)
        self.name = name
        self.ft_space = ft_space
        self.ann_space = ann_space
        self.cols = None
        self.pendingcols = None
        self.table = None
        self.metanames = None
        self.ftnames = None
        self.chunk_size = None
        self.editable = None
        if not noopen:
            self.open_or_create_table(
                ownerid, metadesc=metadesc, coldesc=coldesc, ofileid=ofileid)

    def _owns_table(func):
        def assert_owns_table(*args, **kwargs):
            self = args[0]
            if self.editable is None:
                self.editable = self.perms.can_edit(
                    self.table.getOriginalFile())
            if not self.editable:
                raise FeaturePermissionException(
                    'Feature table must be owned by the current user')
            return func(*args, **kwargs)
        return assert_owns_table

    def close(self):
        """
        Close the table
        """
        if self.table:
            self.table.close()
            self.table = None
            self.cols = None
            self.ftnames = None
            self.editable = None

    def get_table(self):
        """
        Get the table handle
        """
        if not self.table:
            raise TableUsageException('Table not open')
        return self.table

    def open_or_create_table(
            self, ownerid, metadesc=None, coldesc=None, ofileid=None):
        """
        Get the table using the parameters specified during initialisation

        :param ownerid: The user-ID of the owner of the table file
        :param metadesc, coldesc: If provided a new table will be created
               and initialised with this list of metadata and feature names,
               default None (table must already exist), see :meth:`new_table`
        :param ofileid: If provided use the table with this OriginalFile ID,
               the table must already be initialised, name and ft_space will
               be ignored
        """
        tablepath = self.ft_space + '/' + self.name
        if self.table:
            raise TableUsageException(
                'Table already open: %s' % tablepath)
            assert self.cols
            return self.table

        if ofileid:
            q = {'id': ofileid}
        else:
            q = {'name': self.name, 'path': self.ft_space}
        if ownerid > -1:
            q['details.owner.id'] = ownerid
        tablefile = self.get_objects('OriginalFile', q)

        if ofileid:
            if not tablefile:
                raise NoTableMatchException(
                    'Table OriginalFile not found: %s' % ofileid)
            assert len(tablefile) == 1

        if metadesc or coldesc:
            if tablefile:
                raise TooManyTablesException(
                    'Table file already exists: %s' % tablepath)
            if self.perms.get_userid() != ownerid:
                raise TableUsageException(
                    'Unable to create table for a different user')
            self.new_table(metadesc, coldesc)
        else:
            if len(tablefile) < 1:
                raise NoTableMatchException(
                    'No files found for: %s' % tablepath)
            if len(tablefile) > 1:
                raise TooManyTablesException(
                    'Multiple files found for: %s' % tablepath)
            self.open_table(tablefile[0])
        return self.table

    def _column_from_desc(self, desc):
        """
        Create an omero.grid.*Column from a metadata description
        """
        coltype = getattr(omero.grid, desc[0] + 'Column')
        if len(desc) > 2:
            col = coltype(desc[1], '', desc[2])
        else:
            col = coltype(desc[1], '')
        return col

    def new_table(self, metadesc, coldesc):
        """
        Create a new table

        :param metadesc: A list of (column type, column name[, width])
            tuples. Columns must be scalars or strings, see META_COLUMN_TYPES
            for valid type strings. String columns require an additional width
            parameter.
        :param coldesc: A list of feature column names
        """
        if not metadesc or not coldesc:
            raise TableUsageException('Metadata and feature names required')

        for m in metadesc:
            if len(m) not in (2, 3):
                raise TableUsageException('Invalid metadata: %s' % str(m))
            if not m[0] in META_COLUMN_TYPES:
                raise TableUsageException('Invalid metadata type: %s' % str(m))
            if m[0] == 'String':
                if len(m) != 3 or not m[2] or m[2] < 1:
                    raise TableUsageException(
                        'Invalid metadata width: %s' % str(m))
            if not re.match(FEATURE_NAME_RE, m[1]):
                raise TableUsageException('Invalid metadata name: %s' % str(m))
        for n in coldesc:
            if not re.match(FEATURE_NAME_RE, n):
                raise TableUsageException('Invalid feature name: %s' % n)

        tablepath = self.ft_space + '/' + self.name
        self.table = self.session.sharedResources().newTable(0, tablepath)
        if not self.table:
            raise OmeroTableException(
                'Failed to create table: %s' % tablepath)
        # Name may not be split into dirname (path) and basename (name)
        # components https://trac.openmicroscopy.org.uk/ome/ticket/12576
        tof = self.table.getOriginalFile()
        tid = unwrap(tof.getId())
        if (unwrap(tof.getPath()) != self.ft_space or
                unwrap(tof.getName()) != self.name):
            log.warn('Overriding table path and name')
            tof.setPath(wrap(self.ft_space))
            tof.setName(wrap(self.name))
            tof = self.session.getUpdateService().saveAndReturnObject(tof)

            # Note table.getOriginalFile will still return the old object.
            # Force a reload by re-opening table to avoid sync errors when
            # storing data.
            self.table.close()
            self.table = self.session.sharedResources().openTable(tof)
            if not self.table:
                raise OmeroTableException('Failed to reopen table ID:%d' % tid)

        coldef = [self._column_from_desc(m) for m in metadesc]

        # We don't currently have a good way of storing individual feature
        # names for a DoubleArrayColumn:
        # - The number of DoubleColumns allowed in a table is limited (and
        #   slow)
        # - Tables.setMetadata is broken
        #   https://trac.openmicroscopy.org.uk/ome/ticket/12606
        # - Column descriptions can't be retrieved through the API
        # - The total size of table attributes is limited to around 64K (not
        #   sure if this is a per-attribute/object/table limitation)
        # For now save the feature names into the column name.
        names = ','.join(coldesc)
        if len(names) > 64000:
            log.warn(
                'Feature names may exceed the limit of the current Tables API')
        coldef.append(omero.grid.DoubleArrayColumn(
            names, '', len(coldesc)))

        try:
            self.table.initialize(coldef)
        except omero.InternalException:
            log.error('Failed to initialize table, deleting: %d', tid)
            self.session.getUpdateService().deleteObject(tof)
            raise
        self.cols = self.table.getHeaders()
        if not self.cols:
            raise OmeroTableException(
                'Failed to get columns for table ID:%d' % tid)

    def open_table(self, tablefile):
        """
        Open an existing table

        :param tablefile: An OriginalFile
        """
        tid = unwrap(tablefile.getId())
        self.table = self.session.sharedResources().openTable(tablefile)
        if not self.table:
            raise OmeroTableException('Failed to open table ID:%d' % tid)
        self.cols = self.table.getHeaders()
        if not self.cols:
            raise OmeroTableException(
                'Failed to get columns for table ID:%d' % tid)

    def metadata_names(self):
        """
        Get the list of metadata names
        """
        if not self.metanames:
            self.metanames = [col.name for col in self.cols[:-1]]
        return self.metanames

    def feature_names(self):
        """
        Get the list of feature names
        """
        if not self.ftnames:
            self.ftnames = self.cols[-1].name.split(',')
            assert len(self.ftnames) == self.cols[-1].size
        return self.ftnames

    @_owns_table
    def store(self, meta, values, replace=True):
        meta_len = len(self.metadata_names())

        if len(meta) != meta_len:
            raise TableUsageException('Expected %d metadata values' % meta_len)

        for n in xrange(meta_len):
            self.cols[n].values = [meta[n]]

        offset = -1
        if replace:
            kvs = zip(self.metadata_names(), meta)
            conditions = ' & '.join('(%s==%s)' % kv for kv in kvs)
            offsets = self.table.getWhereList(
                conditions, {}, 0, self.table.getNumberOfRows(), 0)
            if offsets:
                offset = max(offsets)

        self.cols[-1].values = [values]

        if offset > -1:
            data = omero.grid.Data(rowNumbers=[offset], columns=self.cols)
            self.table.update(data)
        else:
            self.table.addData(self.cols)

    @_owns_table
    def store_pending(self, meta, values):
        """
        Append data to a pending table, do not write to server (replace is
        not supported)

        :param meta: See :meth:`store`
        :param values: See :meth:`store`
        """
        if not self.pendingcols:
            self.pendingcols = self.table.getHeaders()
            for col in self.pendingcols:
                col.values = []

        meta_len = len(self.metadata_names())

        if len(meta) != meta_len:
            raise TableUsageException('Expected %d metadata values' % meta_len)

        for n in xrange(meta_len):
            self.pendingcols[n].values.append(meta[n])

        self.pendingcols[-1].values.append(values)

    @_owns_table
    def store_flush(self):
        """
        Write any pending table data

        :return: The number of rows written
        """
        n = 0
        if self.pendingcols:
            self.table.addData(self.pendingcols)
            n = len(self.pendingcols[0].values)
        self.pendingcols = None
        return n

    def fetch_by_metadata(self, meta):
        values = self.fetch_by_metadata_raw(meta)
        return [self.feature_row(v) for v in values]

    def fetch_by_metadata_raw(self, meta):
        try:
            kvs = meta.iteritems()
        except AttributeError:
            meta_len = len(self.metadata_names())
            if len(meta) != meta_len:
                raise TableUsageException(
                    'Expected %d metadata values' % meta_len)
            kvs = zip(self.metadata_names(), meta)

        conditions = ['(%s==%s)' % kv for kv in kvs if kv[1] is not None]
        conditions = ' & '.join(conditions)
        values = self.filter_raw(conditions)
        return values

    def filter(self, conditions):
        log.warn('The filter/query syntax is still under development')
        values = self.filter_raw(conditions)
        return [self.feature_row(v) for v in values]

    def filter_raw(self, conditions):
        """
        Query a feature table, return data as rows

        :param conditions: The query conditions
               Note the query syntax is still to be decided
        :return: A list of tuples (Image-ID, Roi-ID, feature-values)
        """
        if conditions:
            offsets = self.table.getWhereList(
                conditions, {}, 0, self.table.getNumberOfRows(), 0)
        else:
            offsets = range(self.table.getNumberOfRows())
        values = self.chunked_table_read(offsets, self.get_chunk_size())

        # Convert into row-wise storage
        if not values:
            return []
        for v in values:
            assert len(offsets) == len(v)
        return zip(*values)

    def feature_row(self, values):
        """
        Create a FeatureRow object

        :param values: The feature values
        """
        fnames = self.feature_names()
        mnames = self.metadata_names()
        assert len(values) == len(mnames) + 1
        return FeatureRow(
            names=fnames, infonames=mnames,
            values=values[-1], infovalues=values[:-1])

    def get_chunk_size(self):
        """
        Ice has a maximum message size. Use a very rough heuristic to decide
        how many table rows to read in one go

        Assume only doubles are stored (8 bytes), and keep the table chunk size
        to <16MB
        """
        if not self.chunk_size:
            # Use size for ArrayColumns, otherwise 1
            rowsize = sum(getattr(c, 'size', 1) for c in self.cols)
            self.chunk_size = max(16777216 / (rowsize * 8), 1)

        return self.chunk_size

    def chunked_table_read(self, offsets, chunk_size):
        """
        Read part of a table in chunks to avoid the Ice maximum message size
        """
        values = None

        log.info('Chunk size: %d', chunk_size)
        for n in xrange(0, len(offsets), chunk_size):
            log.info('Chunk offset: %d+%d', n, chunk_size)
            data = self.table.readCoordinates(offsets[n:(n + chunk_size)])
            if values is None:
                values = [c.values for c in data.columns]
            else:
                for c, v in itertools.izip(data.columns, values):
                    v.extend(c.values)

        return values

    def get_objects(self, object_type, kvs):
        """
        Retrieve OMERO objects
        """
        params = omero.sys.ParametersI()

        qs = self.session.getQueryService()
        conditions = []

        for k, v in kvs.iteritems():
            ek = k.replace('_', '__').replace('.', '_')
            if isinstance(v, list):
                conditions.append(
                    '%s in (:%s)' % (k, ek))
            else:
                conditions.append(
                    '%s = :%s' % (k, ek))
            params.add(ek, wrap(v))

        q = 'FROM %s' % object_type
        if conditions:
            q += ' WHERE ' + ' AND '.join(conditions)

        results = qs.findAllByQuery(q, params)
        return results

    def create_file_annotation(self, object_type, object_id, ns, ofile):
        """
        Create a file annotation

        :param object_type: The object type
        :param object_id: The object ID
        :param ns: The namespace
        :param ofile: The originalFile
        """
        fid = unwrap(ofile.getId())
        links = self._file_annotation_exists(object_type, object_id, ns, fid)
        if len(links) > 1:
            log.warn('Multiple links found: ns:%s %s:%d file:%d',
                     ns, object_type, object_id, fid)
        if links:
            return links[0]

        obj = self.get_objects(object_type, {'id': object_id})
        if len(obj) != 1:
            raise OmeroTableException(
                'Failed to get object %s:%d' % (object_type, object_id))
        link = getattr(omero.model, '%sAnnotationLinkI' % object_type)()
        ann = omero.model.FileAnnotationI()
        ann.setNs(wrap(ns))
        ann.setFile(ofile)
        link.setParent(obj[0])
        link.setChild(ann)
        link = self.session.getUpdateService().saveAndReturnObject(link)
        return link

    def _file_annotation_exists(self, object_type, object_id, ns, file_id):
        q = ('FROM %sAnnotationLink ial WHERE ial.parent.id=:parent AND '
             'ial.child.ns=:ns AND ial.child.file.id=:file') % object_type
        params = omero.sys.ParametersI()
        params.addLong('parent', object_id)
        params.addString('ns', ns)
        params.addLong('file', file_id)
        links = self.session.getQueryService().findAllByQuery(q, params)
        return links

    @_owns_table
    def delete(self):
        """
        Delete the entire featureset including annotations
        """
        # There's a bug (?) which means multiple FileAnnotations with the same
        # OriginalFile child can't be deleted using the graph spec methods.
        # For now just delete everything individually
        qs = self.session.getQueryService()
        tof = self.table.getOriginalFile()
        fid = unwrap(tof.getId())
        params = omero.sys.ParametersI()
        params.addId(fid)
        ds = []

        linktypes = self._get_annotation_link_types()
        for link in linktypes:
            r = qs.findAllByQuery(
                'SELECT al FROM %s al WHERE al.child.file.id=:id' % link,
                params)
            ds.extend(r)

        r = qs.findAllByQuery(
            'SELECT ann FROM FileAnnotation ann WHERE ann.file.id=:id', params)
        ds.extend(r)
        ds.append(tof)

        log.info('Deleting: %s',
                 [(d.__class__.__name__, unwrap(d.getId())) for d in ds])

        us = self.session.getUpdateService()
        self.close()
        for d in ds:
            us.deleteObject(d)

    @staticmethod
    def _get_annotation_link_types():
        return [s for s in dir(omero.model) if s.endswith(
            'AnnotationLink') and not s.startswith('_')]


class LRUCache(object):
    """
    A naive least-recently-used cache. Removal is O(n)
    TODO: Improve efficiency
    """

    def __init__(self, size):
        self.maxsize = size
        self.cache = {}
        self.counter = 0

    def __len__(self):
        return len(self.cache)

    def get(self, key, miss=None):
        try:
            v = self.cache[key]
            self.counter += 1
            v[1] = self.counter
            return v[0]
        except KeyError:
            return miss

    def insert(self, key, value):
        if key not in self.cache and len(self.cache) >= self.maxsize:
            self.remove_oldest()
        self.counter += 1
        self.cache[key] = [value, self.counter]

    def remove_oldest(self):
        mink, minv = min(self.cache.iteritems(), key=lambda kv: kv[1][1])
        return self.cache.pop(mink)[0]


class LRUClosableCache(LRUCache):
    """
    Automatically call value.close() when an object is removed from the cache
    """
    def remove_oldest(self):
        v = super(LRUClosableCache, self).remove_oldest()
        v.close()
        return v

    def close(self):
        while self.cache:
            log.debug('close, %s', self.cache)
            self.remove_oldest()


class FeatureTableManager(AbstractFeatureStoreManager):
    """
    Manage storage of feature table files
    """

    def __init__(self, session, **kwargs):
        self.session = session
        namespace = kwargs.get('namespace', DEFAULT_NAMESPACE)
        self.ft_space = kwargs.get(
            'ft_space', namespace + '/' + DEFAULT_FEATURE_SUBSPACE)
        self.ann_space = kwargs.get(
            'ann_space', namespace + '/' + DEFAULT_ANNOTATION_SUBSPACE)
        self.cachesize = kwargs.get('cachesize', 10)
        self.fss = LRUClosableCache(kwargs.get('cachesize', 10))

    def create(self, featureset_name, metadesc, names):
        try:
            ownerid = self.session.getAdminService().getEventContext().userId
            fs = self.get(featureset_name, ownerid)
            if fs:
                raise TooManyTablesException(
                    'Featureset already exists: %s' % featureset_name)
        except NoTableMatchException:
            pass

        coldesc = names
        fs = FeatureTable(
            self.session, featureset_name, self.ft_space, self.ann_space,
            ownerid, metadesc, coldesc)
        self.fss.insert((featureset_name, ownerid), fs)
        return fs

    def get(self, featureset_name, ownerid=None):
        if ownerid is None:
            ownerid = self.session.getAdminService().getEventContext().userId
        k = (featureset_name, ownerid)
        fs = self.fss.get(k)
        # If fs.table is None it has probably been closed
        if not fs or not fs.table:
            fs = FeatureTable(
                self.session, featureset_name, self.ft_space, self.ann_space,
                ownerid)
            # raises NoTableMatchException if not found
            self.fss.insert(k, fs)
        return fs

    def close(self):
        self.fss.close()
