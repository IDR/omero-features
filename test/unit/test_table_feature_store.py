#!/usr/bin/env python
# -*- coding: utf-8 -*-

#
# Copyright (C) 2014 University of Dundee & Open Microscopy Environment
# All Rights Reserved.
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

import pytest
import mox
import copy
import itertools

import omero
from omero.rtypes import unwrap, wrap

from features import OmeroTablesFeatureStore


class TestLRUCache(object):

    class MockClosable:
        def __init__(self):
            self.closed = False

        def close(self):
            assert not self.closed
            self.closed = True

    def test_get_insert(self):
        c = OmeroTablesFeatureStore.LRUCache(2)
        assert len(c) == 0

        assert c.get('key1') is None
        assert c.get('key1', -1) == -1

        c.insert('key1', 1)
        assert c.get('key1') == 1
        assert len(c) == 1

        c.insert('key1', 'a')
        assert c.get('key1') == 'a'
        assert len(c) == 1

        c.insert('key2', 2)
        assert c.get('key1') == 'a'
        assert c.get('key2') == 2
        assert len(c) == 2

    def test_remove_oldest(self):
        c = OmeroTablesFeatureStore.LRUCache(2)

        c.insert('key1', 1)
        c.insert('key2', 2)
        assert c.remove_oldest() == 1
        assert c.cache.keys() == ['key2']

        c.insert('key3', 3)
        c.get('key2')
        assert c.remove_oldest() == 3
        assert c.cache.keys() == ['key2']

        c.insert('key3', 3)
        c.get('key2')
        c.insert('key4', 3)
        assert sorted(c.cache.keys()) == ['key2', 'key4']

    def test_lru_closable_cache(self):
        o1 = self.MockClosable()
        o2 = self.MockClosable()
        c = OmeroTablesFeatureStore.LRUClosableCache(1)
        c.insert('key1', o1)
        c.insert('key2', o2)
        assert c.cache.keys() == ['key2']
        assert o1.closed
        assert not o2.closed

        c.close()
        assert o2.closed
        assert c.cache.keys() == []


class MockSharedResources:
    def __init__(self, tid, table):
        self.tid = tid
        self.table = table

    def newTable(self, repoid, name):
        assert isinstance(repoid, int)
        assert isinstance(name, str)
        return self.table

    def openTable(self, o):
        assert unwrap(o.id) == self.tid
        return self.table


class MockUpdateService:
    def saveAndReturnObject(self, o):
        pass

    def deleteObject(self, o):
        pass


class MockQueryService:
    def findAllByQuery(self, q, p):
        pass

    def projection(self, q, p):
        pass


class MockAdminService:
    class MockEventContext:
        userId = None

    def __init__(self, uid):
        self.uid = uid

    def getEventContext(self):
        ec = self.MockEventContext()
        ec.userId = self.uid
        return ec


class MockSession:
    def __init__(self, tid, table, uid):
        self.us = MockUpdateService()
        self.qs = MockQueryService()
        self.adm = MockAdminService(uid)
        self.msr = MockSharedResources(tid, table)

    def getUpdateService(self):
        return self.us

    def getQueryService(self):
        return self.qs

    def getAdminService(self):
        return self.adm

    def sharedResources(self):
        return self.msr


class MockOmeroObject:
    def __init__(self, id):
        self.id = wrap(id)

    def getId(self):
        return self.id


class MockOriginalFile:
    def __init__(self, id, name=None, path=None):
        self.id = wrap(id)
        self.name = name
        self.path = path

    def getId(self):
        return self.id

    def getName(self):
        return self.name

    def getPath(self):
        return self.path


class MockColumn:
    def __init__(self, name=None, values=None, size=None, desc=None):
        self.name = name
        self.values = values
        self.size = size
        self.description = None
        if desc:
            self.description = '{"columntype":"%s"}' % desc

    def __eq__(self, o):
        return (self.name == o.name and self.values == o.values and
                self.size == o.size)


class MockTableData:
    rowNumbers = None
    columns = None


class MockTable:
    def __init__(self):
        pass

    def addData(self, cols):
        pass

    def close(self):
        pass

    def getHeaders(self):
        pass

    def getNumberOfRows(self):
        pass

    def getOriginalFile(self):
        pass

    def getWhereList(self):
        pass

    def initialize(self, desc):
        pass

    def readCoordinates(self):
        pass

    def update(self):
        pass


class MockPermissionsHandler:
    def __init__(self):
        pass

    def get_userid(self):
        pass

    def can_annotate(self, obj):
        pass

    def can_edit(self, obj):
        pass


class MockFeatureTable(OmeroTablesFeatureStore.FeatureTable):
    def __init__(self, session):
        self.session = session
        self.perms = None
        self.name = 'table-name'
        self.ft_space = '/test/features/ft_space'
        self.ann_space = '/test/features/ann_space'
        self.cols = None
        self.colnamemap = None
        self.metacols = None
        self.singleftcols = None
        self.multiftcols = None
        self.pendingcols = None
        self.table = None
        self.metanames = None
        self.ftnames = None
        self.header = None
        self.editable = None
        self.chunk_size = None


class TestFeatureRow(object):

    def test_init(self):
        with pytest.raises(OmeroTablesFeatureStore.FeatureRowException):
            OmeroTablesFeatureStore.FeatureRow(names=['a'], values=[1, 2])

        fr = OmeroTablesFeatureStore.FeatureRow(
            names=['a', 'b'], values=[1, 2])
        assert fr.names == ['a', 'b']
        assert fr.values == [1, 2]

        fr = OmeroTablesFeatureStore.FeatureRow(names=['a', 'b'])
        assert fr.names == ['a', 'b']
        assert fr.values is None

    def test_values(self):
        fr = OmeroTablesFeatureStore.FeatureRow(names=['a', 'b'])

        fr.values = [1, 2]
        assert fr.values == [1, 2]

        with pytest.raises(OmeroTablesFeatureStore.FeatureRowException):
            fr.values = [0, 0, 0]

        assert fr._get_index('a') == (0, False)
        assert fr._get_index('b') == (1, False)
        assert fr['a'] == 1
        assert fr['b'] == 2

        fr['a'] = 10
        assert fr.values == [10, 2]

        with pytest.raises(KeyError):
            fr['c'] = [0]

        fr = OmeroTablesFeatureStore.FeatureRow(values=[1, 2])
        with pytest.raises(OmeroTablesFeatureStore.FeatureRowException):
            fr.values = [0, 0, 0]

    def test_infovalues(self):
        fr = OmeroTablesFeatureStore.FeatureRow(
            names=['a', 'b'], infonames=['ma', 'mb'])

        with pytest.raises(OmeroTablesFeatureStore.FeatureRowException):
            fr.infovalues = ['va']
        fr.infovalues = ['x', 'y']

        assert fr._get_index('ma') == (0, True)
        assert fr._get_index('mb') == (1, True)

        fr['ma'] = 'z'
        assert fr.infovalues == ['z', 'y']

    def test_repr(self):
        fr = OmeroTablesFeatureStore.FeatureRow(
            names=['a'], values=[1], infonames=['ma'], infovalues=[0])
        assert repr(fr) == ("FeatureRow(names=['a'], values=[1], "
                            "infonames=['ma'], infovalues=[0])")


class TestFeatureTable(object):

    def setup_method(self, method):
        self.mox = mox.Mox()

    def teardown_method(self, method):
        self.mox.UnsetStubs()

    @staticmethod
    def parameters_equal(a, b):
        return a.map == b.map and (
            (a.theFilter is None and b.theFilter is None) or
            (a.theFilter.__dict__ == b.theFilter.__dict__)) and (
            (a.theOptions is None and b.theOptions is None) or
            (a.theOptions.__dict__ == b.theOptions.__dict__))

    @staticmethod
    def columns_equal(xs, ys):
        def comparecol(x, y):
            return all([
                type(x) == type(y),
                x.name == y.name,
                x.description == y.description,
                getattr(x, 'size', None) == getattr(y, 'size', None),
                x.values == y.values
            ])
        return all([comparecol(x, y) for x, y in itertools.izip(xs, ys)])

    def test_close(self):
        table = self.mox.CreateMock(MockTable)
        table.close()
        store = MockFeatureTable(None)
        store.table = table

        self.mox.ReplayAll()

        store.close()
        assert store.table is None
        self.mox.VerifyAll()

    @pytest.mark.parametrize('opened', [True, False])
    def test_get_table(self, opened):
        table = self.mox.CreateMock(MockTable)
        store = MockFeatureTable(None)
        if opened:
            store.table = table

        if opened:
            assert store.get_table() == table
        else:
            with pytest.raises(OmeroTablesFeatureStore.TableUsageException):
                store.get_table()

    def test_column_from_desc(self):
        store = MockFeatureTable(None)
        expected = [
            omero.grid.DoubleColumn('d', '{"columntype": "metadata"}'),
            omero.grid.StringColumn('s', '{"columntype": "metadata"}', 2),
        ]
        cols = [store._column_from_desc(('Double', 'd')),
                store._column_from_desc(('String', 's', 2))]
        assert self.columns_equal(expected, cols)

    def test_get_column_json(self):
        store = MockFeatureTable(None)
        assert store._get_column_json('multifeature') == (
            '{"columntype": "multifeature"}')

    def test_get_column_type(self):
        store = MockFeatureTable(None)
        col = MockColumn(name='a', desc='metadata')
        assert store._get_column_type(col) == 'metadata'

    def test_get_cols(self):
        store = MockFeatureTable(None)
        table = self.mox.CreateMock(MockTable)
        self.mox.StubOutWithMock(table, 'getHeaders')
        cols = (
            MockColumn(name='a', desc='metadata'),
            MockColumn(name='b', desc='metadata'), MockColumn(desc='feature'))
        table.getHeaders().AndReturn(cols)
        store.table = table

        self.mox.ReplayAll()
        store._get_cols()
        assert store.metacols == (0, 1)
        assert store.singleftcols == (2,)
        assert store.multiftcols == ()

    @pytest.mark.parametrize('opened', [True, False])
    @pytest.mark.parametrize('create', [True, False])
    @pytest.mark.parametrize('owned', [True, False])
    @pytest.mark.parametrize('ofile', [True, False])
    def test_open_or_create_table(self, opened, create, owned, ofile):
        tid = 1
        if create and not ofile:
            mfs = None
        else:
            mfs = [MockOriginalFile(tid)]
        perms = self.mox.CreateMock(MockPermissionsHandler)
        self.mox.StubOutWithMock(perms, 'get_userid')
        store = MockFeatureTable(None)
        store.perms = perms
        self.mox.StubOutWithMock(store, 'get_objects')
        self.mox.StubOutWithMock(store, 'open_table')
        self.mox.StubOutWithMock(store, 'new_table')
        table = self.mox.CreateMock(MockTable)
        userid = 123
        if owned:
            ownerid = userid
        else:
            ownerid = 321

        meta = [('Image', 'ImageID')]
        col_desc = ['x']
        if ofile:
            filedesc = {'id': tid, 'details.owner.id': ownerid}
        else:
            filedesc = {'name': 'table-name', 'path': store.ft_space,
                        'details.owner.id': ownerid}

        if opened:
            store.table = table
            store.cols = object()
        else:
            store.get_objects('OriginalFile', filedesc).AndReturn(mfs)
            if create:
                if not ofile:
                    perms.get_userid().AndReturn(userid)
                    if owned:
                        store.new_table(meta, col_desc)
            else:
                store.open_table(mfs[0])

        self.mox.ReplayAll()

        # open_table is mocked so it won't set store.table
        # assert store.get_table() == table
        if create:
            if opened:
                with pytest.raises(
                        OmeroTablesFeatureStore.TableUsageException):
                    store.open_or_create_table(ownerid, meta, col_desc)
            elif ofile:
                with pytest.raises(
                        OmeroTablesFeatureStore.TooManyTablesException):
                    store.open_or_create_table(
                        ownerid, meta, col_desc, ofileid=1)
            elif not owned:
                with pytest.raises(
                        OmeroTablesFeatureStore.TableUsageException):
                    store.open_or_create_table(ownerid, meta, col_desc)
            else:
                store.open_or_create_table(ownerid, meta, col_desc)
        else:
            if opened:
                with pytest.raises(
                        OmeroTablesFeatureStore.TableUsageException):
                    store.open_or_create_table(ownerid)
            elif ofile:
                store.open_or_create_table(ownerid, ofileid=1)
            else:
                store.open_or_create_table(ownerid)
        self.mox.VerifyAll()

    def test_new_table(self):
        table = self.mox.CreateMock(MockTable)
        session = MockSession(1, table, None)
        store = MockFeatureTable(session)

        mf = MockOriginalFile(1, 'table-name', store.ft_space)
        table.getOriginalFile().AndReturn(mf)

        tcols = (
            omero.grid.ImageColumn('ImageID', '{"columntype": "metadata"}'),
            omero.grid.RoiColumn('RoiID', '{"columntype": "metadata"}'),
            omero.grid.DoubleArrayColumn(
                'x', '{"columntype": "multifeature"}', 1),
        )
        meta = [('Image', 'ImageID'), ('Roi', 'RoiID')]
        desc = ['x']

        table.initialize(mox.Func(lambda xs: self.columns_equal(xs, tcols)))
        table.getHeaders().AndReturn(tcols)

        self.mox.ReplayAll()

        store.new_table(meta, desc)
        assert store.table == table
        assert store.cols == tcols
        self.mox.VerifyAll()

    def test_new_table_invalid_ftname(self):
        store = MockFeatureTable(None)
        with pytest.raises(OmeroTablesFeatureStore.TableUsageException):
            store.new_table([('Image', 'ImageID')], ['x1', '<>'])
        with pytest.raises(OmeroTablesFeatureStore.TableUsageException):
            store.new_table([('Image', '<>')], ['x1', 'x2'])

    def test_open_table(self):
        mf = MockOriginalFile(1)
        table = self.mox.CreateMock(MockTable)
        session = MockSession(1, table, None)
        store = MockFeatureTable(session)
        cols = (MockColumn(desc='metadata'),)

        table.getHeaders().AndReturn(cols)
        self.mox.ReplayAll()

        store.open_table(mf)
        assert store.table == table
        assert store.cols == cols
        self.mox.VerifyAll()

    def test_get_column(self):
        store = MockFeatureTable(None)
        cola = MockColumn(name='a')
        colb = MockColumn(name='b')
        colc = MockColumn(name='c')
        store.cols = [cola, colb, colc]

        assert store._get_column('a') == cola
        assert store.colnamemap == {'a': cola, 'b': colb, 'c': colc}
        assert store._get_column('b') == colb
        assert store._get_column('c') == colc

        with pytest.raises(OmeroTablesFeatureStore.OmeroTableException):
            store._get_column('non-existent')

    def test_metadata_names(self):
        table = self.mox.CreateMock(MockTable)
        store = MockFeatureTable(None)
        store.table = table
        store.cols = (
            MockColumn(name='a', desc='metadata'),
            MockColumn(name='b', desc='metadata'), MockColumn(desc='feature'))
        store.metacols = (0, 1)

        self.mox.ReplayAll()
        assert store.metadata_names() == ('a', 'b')
        self.mox.VerifyAll()

    def test_feature_names(self):
        table = self.mox.CreateMock(MockTable)
        store = MockFeatureTable(None)
        store.table = table
        store.cols = [
            MockColumn(), MockColumn(), MockColumn(name='a,b', size=2)]
        store.multiftcols = (2,)

        self.mox.ReplayAll()
        assert store.feature_names() == ('a', 'b')
        self.mox.VerifyAll()

    def setup_test_store(self):
        owned = True
        perms = self.mox.CreateMock(MockPermissionsHandler)
        table = self.mox.CreateMock(MockTable)
        store = MockFeatureTable(None)
        store.perms = perms
        store.table = table
        store.cols = [MockColumn('a'), MockColumn('b'),
                      MockColumn('c', None, 2)]
        store.metacols = (0, 1)
        store.multiftcols = (2,)

        self.mox.StubOutWithMock(perms, 'can_edit')
        self.mox.StubOutWithMock(table, 'getOriginalFile')
        self.mox.StubOutWithMock(table, 'getNumberOfRows')
        self.mox.StubOutWithMock(table, 'getWhereList')
        self.mox.StubOutWithMock(table, 'update')
        self.mox.StubOutWithMock(table, 'addData')
        self.mox.StubOutWithMock(store, 'create_file_annotation')

        mf = MockOriginalFile(3)
        meta = [12, -1]
        values = [10, 20]
        expectedcols = [MockColumn('a', [12]), MockColumn('b', [-1]),
                        MockColumn('c', [[10, 20]], 2)]

        table.getOriginalFile().AndReturn(mf)
        perms.can_edit(mf).AndReturn(owned)

        return store, table, meta, values, expectedcols

    def test_get_condition(self):
        store = MockFeatureTable(None)
        store.cols = [
            MockColumn(name='a'), omero.grid.StringColumn(name='b', size=8),
            MockColumn(name='c', size=1)]

        assert store._get_condition('a', None) is None
        assert store._get_condition('a', [None, None]) is None
        assert store._get_condition('a', 1) == '(a==1)'
        assert store._get_condition('a', [1]) == '((a==1))'
        assert store._get_condition('a', (1,)) == '((a==1))'
        assert store._get_condition('a', [1, 2]) == '((a==1) | (a==2))'
        assert store._get_condition('a', (1, None, 2)) == '((a==1) | (a==2))'

        assert store._get_condition('b', 'ab') == '(b=="ab")'
        assert store._get_condition('b', 'a"b') == '(b=="a\\"b")'
        assert store._get_condition('b', ['a', None]) == '((b=="a"))'
        assert store._get_condition('b', ['a', '']) == '((b=="a") | (b==""))'
        assert store._get_condition('b', ['a"b', '', 'c " " d']) == (
            '((b=="a\\"b") | (b=="") | (b=="c \\" \\" d"))')

    def test_vals_to_cols(self):
        store = MockFeatureTable(None)
        store.cols = [
            MockColumn(name='a', values=[]),
            omero.grid.StringColumn(name='b', values=[], size=8),
            MockColumn(name='c,d', values=[], size=2)]
        store.metacols = (0, 1)
        store.multiftcols = (2,)

        store._vals_to_cols(store.cols, [1, 'abc'], [2, 3])
        assert store.cols[0].values == [1]
        assert store.cols[1].values == ['abc']
        assert store.cols[2].values == [[2, 3]]

    def test_colrow_to_vals(self):
        store = MockFeatureTable(None)
        store.metacols = (0, 1)
        store.multiftcols = (2,)

        metas, values = store._colrow_to_vals((1, 'abc', [2, 3]))
        assert metas == (1, 'abc')
        assert values == (2, 3)

    @pytest.mark.parametrize('exists', [True, False])
    def test_store(self, exists):
        store, table, meta, values, expectedcols = self.setup_test_store()

        if exists:
            offsets = [10, 20]
        else:
            offsets = None
        table.getNumberOfRows().AndReturn(100)
        table.getWhereList('(a==12) & (b==-1)',
                           {}, 0, 100, 0).AndReturn(offsets)

        if exists:
            table.update(mox.Func(
                lambda o: o.rowNumbers == [20] and
                o.columns == expectedcols))
        else:
            table.addData(expectedcols)

        self.mox.ReplayAll()
        store.store(meta, values)
        self.mox.VerifyAll()

    def test_store_unowned(self):
        owned = False
        perms = self.mox.CreateMock(MockPermissionsHandler)
        table = self.mox.CreateMock(MockTable)
        store = MockFeatureTable(None)
        store.perms = perms
        store.table = table

        self.mox.StubOutWithMock(perms, 'can_edit')
        self.mox.StubOutWithMock(table, 'getOriginalFile')

        mf = MockOriginalFile(3)
        table.getOriginalFile().AndReturn(mf)
        perms.can_edit(mf).AndReturn(owned)

        self.mox.ReplayAll()
        with pytest.raises(
                OmeroTablesFeatureStore.FeaturePermissionException):
            store.store([], [])
        self.mox.VerifyAll()

    def test_store_pending_and_flush(self):
        store, table, meta, values, expectedcols = self.setup_test_store()
        self.mox.StubOutWithMock(table, 'getHeaders')
        table.getHeaders().AndReturn(copy.deepcopy(store.cols))
        table.addData(expectedcols)

        self.mox.ReplayAll()
        store.store_pending(meta, values)
        assert [col.values for col in store.cols] == [None, None, None]
        assert [col.values for col in store.pendingcols] == [
            [meta[0]], [meta[1]], [values]]

        store.store_flush()
        assert [col.values for col in store.cols] == [None, None, None]
        assert store.pendingcols is None
        self.mox.VerifyAll()

    def test_fetch_by_metadata(self):
        store = MockFeatureTable(None)
        store.cols = [MockColumn(name='a')]
        self.mox.StubOutWithMock(store, 'filter_raw')
        self.mox.StubOutWithMock(store, 'feature_row')

        meta = {'a': 1}
        rs = (1, 2, [0])
        r1 = object()

        store.fetch_by_metadata_raw(meta).AndReturn([rs])
        store.feature_row(rs).AndReturn(r1)

        self.mox.ReplayAll()
        assert store.fetch_by_metadata(meta) == [r1]
        self.mox.VerifyAll()

    @pytest.mark.parametrize('meta', [[1, 2], {'a': 1, 'b': 2}])
    def test_fetch_by_metadata_raw(self, meta):
        table = self.mox.CreateMock(MockTable)
        store = MockFeatureTable(None)
        store.table = table
        store.cols = [
            MockColumn(name='a'), MockColumn(name='b'),
            MockColumn(name='c', size=1)]
        store.metacols = (0, 1)
        store.ftcols = (2,)

        self.mox.StubOutWithMock(store, 'filter_raw')
        rs = (1, 2, [0])

        store.filter_raw('(a==1) & (b==2)').AndReturn([rs])

        self.mox.ReplayAll()
        assert store.fetch_by_metadata_raw(meta) == [rs]
        self.mox.VerifyAll()

    def test_fetch_by_metadata_raw_complex_query(self):
        table = self.mox.CreateMock(MockTable)
        store = MockFeatureTable(None)
        store.table = table
        store.cols = [
            MockColumn(name='a'), omero.grid.StringColumn(name='b', size=8),
            MockColumn(name='c', size=1)]

        self.mox.StubOutWithMock(store, 'filter_raw')
        rs = (1, 'string', [0])

        meta = {'a': None, 'a': [1, 2, 4], 'b': 'str"ing'}
        expected = '((a==1) | (a==2) | (a==4)) & (b=="str\\"ing")'
        store.filter_raw(expected).AndReturn([rs])

        self.mox.ReplayAll()
        assert store.fetch_by_metadata_raw(meta) == [rs]
        self.mox.VerifyAll()

    def test_filter(self):
        store = MockFeatureTable(None)
        self.mox.StubOutWithMock(store, 'filter_raw')
        self.mox.StubOutWithMock(store, 'feature_row')
        values1 = (0, 1, [5])
        r1 = object()

        store.filter_raw('RoiID==1').AndReturn([values1])
        store.feature_row(values1).AndReturn(r1)

        self.mox.ReplayAll()
        assert store.filter('RoiID==1') == [r1]
        self.mox.VerifyAll()

    @pytest.mark.parametrize('ncols', [1, 2])
    @pytest.mark.parametrize('nrows', [0, 1, 2])
    def test_filter_raw(self, ncols, nrows):
        table = self.mox.CreateMock(MockTable)
        store = MockFeatureTable(None)
        store.table = table
        store.cols = [MockColumn() for n in xrange(ncols)]

        offsets = [3, 7][:nrows]

        self.mox.StubOutWithMock(table, 'getWhereList')
        self.mox.StubOutWithMock(table, 'getNumberOfRows')
        self.mox.StubOutWithMock(store, 'get_chunk_size')
        self.mox.StubOutWithMock(store, 'chunked_table_read')

        table.getNumberOfRows().AndReturn(123)
        table.getWhereList('(ImageID==99)', {}, 0, 123, 0).AndReturn(offsets)

        data = None
        if nrows > 0:
            data = []
            for c in xrange(ncols):
                cvals = [[r * 10 + c] for r in xrange(1, nrows + 1)]
                data.append(cvals)

        store.get_chunk_size().AndReturn(2)
        store.chunked_table_read(offsets, 2).AndReturn(data)

        self.mox.ReplayAll()

        rvalues = store.filter_raw('(ImageID==99)')

        assert len(rvalues) == len(offsets)
        if ncols == 1 and nrows == 1:
            assert rvalues == [([10],)]
        elif ncols == 1 and nrows == 2:
            assert rvalues == [([10],), ([20],)]
        elif ncols == 2 and nrows == 1:
            assert rvalues == [([10], [11])]
        elif ncols == 2 and nrows == 2:
            assert rvalues == [([10], [11]), ([20], [21])]
        else:
            assert rvalues == []
        self.mox.VerifyAll()

    def test_feature_row(self):
        store = MockFeatureTable(None)
        store.cols = (
            MockColumn('ma'), MockColumn('mb'), MockColumn())
        store.metacols = (0, 1)
        store.multiftcols = (2,)
        self.mox.StubOutWithMock(store, 'metadata_names')
        self.mox.StubOutWithMock(store, 'feature_names')
        store.metadata_names().AndReturn(('ma', 'mb'))
        store.feature_names().AndReturn(('a', 'b'))
        row = [10, 20, (1, 2)]

        self.mox.ReplayAll()
        rv = store.feature_row(row)
        assert rv.names == ('a', 'b')
        assert rv.values == (1, 2)
        assert rv.infonames == ('ma', 'mb')
        assert rv.infovalues == (10, 20)
        self.mox.VerifyAll()

    def test_get_chunk_size(self):
        table = self.mox.CreateMock(MockTable)
        store = MockFeatureTable(None)
        store.table = table
        store.cols = [MockColumn(size=2) for n in xrange(100)]

        self.mox.ReplayAll()
        assert store.get_chunk_size() == 10485
        self.mox.VerifyAll()

    def test_chunked_table_read(self):
        table = self.mox.CreateMock(MockTable)
        store = MockFeatureTable(None)
        store.table = table

        self.mox.StubOutWithMock(table, 'readCoordinates')

        offsets = [2, 7, 5]

        data1 = MockTableData()
        data1.columns = [MockColumn()]
        data1.columns[0].values = [[1], [2]]

        data2 = MockTableData()
        data2.columns = [MockColumn()]
        data2.columns[0].values = [[3]]

        table.readCoordinates([2, 7]).AndReturn(data1)
        table.readCoordinates([5]).AndReturn(data2)

        self.mox.ReplayAll()

        d = store.chunked_table_read(offsets, 2)
        assert d == [[[1], [2], [3]]]
        self.mox.VerifyAll()

    def test_get_objects(self):
        session = MockSession(None, None, None)
        store = MockFeatureTable(session)
        self.mox.StubOutWithMock(session.qs, 'findAllByQuery')

        kvs = {'x': 'aaa', 'y.z': ['bbb', 'ccc']}
        # Need to figure out which order the keys will be read
        if kvs.keys() == ['x', 'y.z']:
            q = "FROM ObjectType WHERE x = :x AND y.z in (:y_z)"
        else:
            q = "FROM ObjectType WHERE y.z in (:y_z) AND x = :x"

        params = omero.sys.ParametersI()
        params.add('x', wrap('aaa'))
        params.add('y_z', wrap(['bbb', 'ccc']))
        m = object()

        session.qs.findAllByQuery(q, mox.Func(
            lambda o: self.parameters_equal(params, o))).AndReturn([m])

        self.mox.ReplayAll()

        assert store.get_objects('ObjectType', kvs) == [m]
        self.mox.VerifyAll()

    @pytest.mark.parametrize('exists', [True, False])
    def test_create_file_annotation(self, exists):
        session = MockSession(None, None, None)
        store = MockFeatureTable(session)
        self.mox.StubOutWithMock(store, 'get_objects')
        self.mox.StubOutWithMock(store, '_file_annotation_exists')
        self.mox.StubOutWithMock(session.us, 'saveAndReturnObject')

        ofile = omero.model.OriginalFileI(2)
        image = omero.model.ImageI(3)

        if exists:
            r = [MockOmeroObject(21), MockOmeroObject(22)]
        else:
            r = []
        store._file_annotation_exists('Image', 3, 'ns', 2).AndReturn(r)

        if not exists:
            store.get_objects('Image', {'id': 3}).AndReturn([image])
            mocklink = MockOmeroObject(23)

            session.us.saveAndReturnObject(mox.Func(
                lambda o: o.getParent() == image and
                o.getChild().getNs() == wrap('ns') and
                o.getChild().getFile() == ofile)).AndReturn(mocklink)

        self.mox.ReplayAll()
        if exists:
            assert store.create_file_annotation(
                'Image', 3, 'ns', ofile) == r[0]
        else:
            assert store.create_file_annotation(
                'Image', 3, 'ns', ofile) == mocklink
        self.mox.VerifyAll()

    def test_file_annotation_exists(self):
        session = MockSession(None, None, None)
        store = MockFeatureTable(session)
        self.mox.StubOutWithMock(session.qs, 'findAllByQuery')

        imageid = 3
        fileid = 2
        ns = 'ns'
        result = [object()]
        params = omero.sys.ParametersI()
        params.addLong('parent', imageid)
        params.addLong('file', fileid)
        params.addString('ns', ns)

        session.qs.findAllByQuery(
            'FROM ImageAnnotationLink ial WHERE ial.parent.id=:parent AND '
            'ial.child.ns=:ns AND ial.child.file.id=:file',
            mox.Func(lambda o: self.parameters_equal(params, o))).AndReturn(
            result)

        self.mox.ReplayAll()
        assert store._file_annotation_exists(
            'Image', imageid, ns, fileid) == result
        self.mox.VerifyAll()

    def test_delete(self):
        perms = self.mox.CreateMock(MockPermissionsHandler)
        table = self.mox.CreateMock(MockTable)
        session = MockSession(1, table, None)
        store = MockFeatureTable(session)
        store.perms = perms
        store.table = table

        self.mox.StubOutWithMock(store, 'close')
        self.mox.StubOutWithMock(perms, 'can_edit')
        self.mox.StubOutWithMock(table, 'getOriginalFile')
        self.mox.StubOutWithMock(store, '_get_annotation_link_types')
        self.mox.StubOutWithMock(session.qs, 'findAllByQuery')
        self.mox.StubOutWithMock(session.us, 'deleteObject')

        fid = 123
        mf = MockOriginalFile(fid, 'table-name', store.ft_space)
        table.getOriginalFile().AndReturn(mf)
        perms.can_edit(mf).AndReturn(True)
        table.getOriginalFile().AndReturn(mf)

        store._get_annotation_link_types().AndReturn(
            ['ImageAnnotationLink', 'RoiAnnotationLink'])

        mockimlink = MockOmeroObject(12)
        mockfileann = MockOmeroObject(34)
        params = omero.sys.ParametersI()
        params.addId(fid)
        session.qs.findAllByQuery(
            'SELECT al FROM ImageAnnotationLink al WHERE al.child.file.id=:id',
            mox.Func(lambda o: self.parameters_equal(params, o))).AndReturn(
            [mockimlink])
        session.qs.findAllByQuery(
            'SELECT al FROM RoiAnnotationLink al WHERE al.child.file.id=:id',
            mox.Func(lambda o: self.parameters_equal(params, o))).AndReturn([])
        session.qs.findAllByQuery(
            'SELECT ann FROM FileAnnotation ann WHERE ann.file.id=:id',
            mox.Func(lambda o: self.parameters_equal(params, o))).AndReturn(
            [mockfileann])

        store.close()

        session.us.deleteObject(mockimlink)
        session.us.deleteObject(mockfileann)
        session.us.deleteObject(mf)

        self.mox.ReplayAll()
        store.delete()
        self.mox.VerifyAll()

    def test_get_annotation_link_types(self):
        store = MockFeatureTable(None)
        types = store._get_annotation_link_types()
        assert 'ImageAnnotationLink' in types
        assert 'RoiAnnotationLink' in types


class TestFeatureTableManager(object):

    def setup_method(self, method):
        self.mox = mox.Mox()

    def teardown_method(self, method):
        self.mox.UnsetStubs()

    def test_init(self):
        fts = OmeroTablesFeatureStore.FeatureTableManager(None)
        assert fts.ft_space == 'omero.features/0.1/features'
        assert fts.ann_space == 'omero.features/0.1/source'

        fts = OmeroTablesFeatureStore.FeatureTableManager(None, namespace='x')
        assert fts.ft_space == 'x/features'
        assert fts.ann_space == 'x/source'

        fts = OmeroTablesFeatureStore.FeatureTableManager(
            None, ft_space='y', ann_space='z')
        assert fts.ft_space == 'y'
        assert fts.ann_space == 'z'

    def test_create(self):
        ownerid = 123
        session = MockSession(None, None, ownerid)
        fs = MockFeatureTable(None)
        self.mox.StubOutWithMock(OmeroTablesFeatureStore, 'FeatureTable')
        fsname = 'fsname'
        meta = [('Float', 'f')]
        colnames = ['x1', 'x2']

        OmeroTablesFeatureStore.FeatureTable(
            session, fsname, 'x/features', 'x/source', ownerid).AndReturn(None)

        OmeroTablesFeatureStore.FeatureTable(
            session, fsname, 'x/features', 'x/source', ownerid, meta, colnames
            ).AndReturn(fs)

        self.mox.ReplayAll()

        fts = OmeroTablesFeatureStore.FeatureTableManager(
            session, namespace='x')
        assert fts.create(fsname, meta, colnames) == fs

        assert len(fts.fss) == 1
        assert fts.fss.get((fsname, ownerid)) == fs

        self.mox.VerifyAll()

    @pytest.mark.parametrize('state', ['opened', 'unopened', 'closed'])
    def test_get(self, state):
        ownerid = 123
        session = MockSession(None, None, ownerid)
        fs = MockFeatureTable(session)
        fs.table = object()
        self.mox.StubOutWithMock(OmeroTablesFeatureStore, 'FeatureTable')
        fsname = 'fsname'
        fts = OmeroTablesFeatureStore.FeatureTableManager(
            session, namespace='x')

        self.mox.StubOutWithMock(fts.fss, 'get')
        self.mox.StubOutWithMock(fts.fss, 'insert')

        k = (fsname, ownerid)

        if state == 'opened':
            fts.fss.get(k).AndReturn(fs)
        else:
            if state == 'unopened':
                fts.fss.get(k).AndReturn(None)
            if state == 'closed':
                fsold = MockFeatureTable(None)
                fts.fss.get(k).AndReturn(fsold)
            OmeroTablesFeatureStore.FeatureTable(
                session, fsname, 'x/features', 'x/source', ownerid
                ).AndReturn(fs)
            fts.fss.insert(k, fs)

        self.mox.ReplayAll()

        assert fts.get(fsname, ownerid) == fs
        self.mox.VerifyAll()
