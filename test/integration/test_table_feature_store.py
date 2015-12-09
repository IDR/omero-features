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

from integration_test_lib import UserAccount

import itertools
import sys

import omero
from omero.rtypes import rstring, unwrap, wrap

from features import OmeroTablesFeatureStore
from features.OmeroTablesFeatureStore import FeatureTable


class TableStoreHelper(object):
    @staticmethod
    def assert_coltypes_equal(xs, ys):
        for x, y in itertools.izip(xs, ys):
            assert isinstance(x, omero.grid.Column)
            assert isinstance(y, omero.grid.Column)
            assert type(x) == type(y)
            assert x.name == y.name
            assert x.description == y.description
            assert getattr(x, 'size', None) == getattr(y, 'size', None)

    @staticmethod
    def get_columns(ws, coltype, interleave):
        meta = [('Image', 'ImageID'), ('Roi', 'RoiID'), ('String', 'Name', 8)]
        ftnames = tuple('x%d' % n for n in xrange(1, sum(ws) + 1))
        metacols = [
            omero.grid.ImageColumn('ImageID', '{"columntype": "metadata"}'),
            omero.grid.RoiColumn('RoiID', '{"columntype": "metadata"}'),
            omero.grid.StringColumn(
                'Name', '{"columntype": "metadata"}', size=8)]
        if coltype == 'single':
            ftcols = [
                omero.grid.DoubleColumn(fn, '{"columntype": "feature"}')
                for fn in ftnames]
        else:
            ftcols = []
            p = 0
            for w in ws:
                q = p + w
                ftcols.append(omero.grid.DoubleArrayColumn(
                    ','.join(ftnames[p:q]),
                    '{"columntype": "multifeature"}', w))
                p = q
        if interleave:
            n = min(len(metacols), len(ftcols))
            cols = [c for z in zip(metacols, ftcols) for c in z
                    ] + metacols[n:] + ftcols[n:]
        else:
            cols = metacols + ftcols
        return cols, meta, ftnames

    @staticmethod
    def create_table(sess, path, name, widths, coltype, interleave):
        table = sess.sharedResources().newTable(0, 'name')
        cols, meta, ftnames = TableStoreHelper.get_columns(
            widths, coltype, interleave)
        table.initialize(cols)
        ofile = table.getOriginalFile()
        ofile.setPath(wrap(path))
        ofile.setName(wrap(name))
        ofile = sess.getUpdateService().saveAndReturnObject(ofile)
        tid = unwrap(ofile.getId())
        table.close()
        return tid, cols, meta, ftnames

    @staticmethod
    def create_image(sess, **kwargs):
        im = omero.model.ImageI()
        im.setAcquisitionDate(omero.rtypes.rtime(0))
        im.setName(rstring(None))
        for k, v in kwargs.iteritems():
            setattr(im, k, wrap(v))
        im = sess.getUpdateService().saveAndReturnObject(im)
        return im

    @staticmethod
    def create_roi(sess):
        roi = omero.model.RoiI()
        roi = sess.getUpdateService().saveAndReturnObject(roi)
        return roi


class TableStoreTestHelper(object):

    def setup_class(self):
        self.ua = UserAccount()
        self.user = self.ua.new_user(perms='rwra--')

    def teardown_class(self):
        self.ua.close()

    def setup_method(self, method):
        self.clis = []
        self.sess = self.create_client_session(self.user)
        self.name = UserAccount.uuid()
        ns = UserAccount.uuid()
        self.ft_space = ns + '/features'
        self.ann_space = ns + '/source'

    def teardown_method(self, method):
        for cli in self.clis:
            cli.closeSession()

    def create_user_same_group(self):
        g = self.sess.getAdminService().getDefaultGroup(self.user.id.val)
        return self.ua.new_user(group=g)

    def create_client_session(self, user):
        cli = omero.client()
        self.clis.append(cli)
        un = unwrap(user.getOmeName())
        sess = cli.createSession(un, un)
        return sess


class TestFeatureTable(TableStoreTestHelper):

    def test_get_table(self):
        store = FeatureTable(
            self.sess, self.name, self.ft_space, self.ann_space)
        with pytest.raises(OmeroTablesFeatureStore.TableUsageException):
            store.get_table()

        tcols, meta, ftnames = TableStoreHelper.get_columns(
            [2], 'multi', False)
        store.new_table(meta, ftnames)
        assert store.get_table()
        store.close()

    def test_new_table(self):
        tcols, meta, ftnames = TableStoreHelper.get_columns(
            [2], 'multi', False)

        store = FeatureTable(
            self.sess, self.name, self.ft_space, self.ann_space)
        store.new_table(meta, ftnames)
        assert store.table
        TableStoreHelper.assert_coltypes_equal(store.cols, tcols)

        assert store.metadata_names() == tuple(m[1] for m in meta)
        assert store.feature_names() == ftnames

        # Need to reload
        # ofile = store.table.getOriginalFile()
        tid = unwrap(store.table.getOriginalFile().getId())
        ofile = self.sess.getQueryService().get('OriginalFile', tid)
        assert unwrap(ofile.getName()) == self.name
        assert unwrap(ofile.getPath()) == self.ft_space

        store.close()

    def test_open_table(self):
        tid, tcols, meta, ftnames = TableStoreHelper.create_table(
            self.sess, self.ft_space, self.name, [1], 'multi', False)

        store = FeatureTable(
            self.sess, self.name, self.ft_space, self.ann_space)
        store.open_table(tid)
        assert store.table
        TableStoreHelper.assert_coltypes_equal(store.cols, tcols)
        assert store.metadata_names() == tuple(m[1] for m in meta)
        assert store.feature_names() == ftnames

        store.close()

    @pytest.mark.parametrize('exists', [True, False])
    @pytest.mark.parametrize('replace', [True, False])
    def test_store(self, exists, replace):
        width = 2

        tid, tcols, meta, ftnames = TableStoreHelper.create_table(
            self.sess, self.ft_space, self.name, [width], 'multi', False)
        imageid = unwrap(TableStoreHelper.create_image(self.sess).getId())
        roiid = unwrap(TableStoreHelper.create_roi(self.sess).getId())

        store = FeatureTable(
            self.sess, self.name, self.ft_space, self.ann_space)
        store.open_table(tid)

        if exists:
            store.store([imageid, -1, 'aa'], [10, 20])
            assert store.table.getNumberOfRows() == 1

        store.store([imageid, -1, 'aa'], [10, 20], replace=replace)

        if exists and not replace:
            assert store.table.getNumberOfRows() == 2
            d = store.table.readCoordinates(range(0, 2)).columns
            assert len(d) == 4
            assert d[0].values == [imageid, imageid]
            assert d[1].values == [-1, -1]
            assert d[2].values == ['aa', 'aa']
            assert d[3].values == [[10, 20], [10, 20]]
        else:
            assert store.table.getNumberOfRows() == 1
            d = store.table.readCoordinates(range(0, 1)).columns
            assert len(d) == 4
            assert d[0].values == [imageid]
            assert d[1].values == [-1]
            assert d[2].values == ['aa']
            assert d[3].values == [[10, 20]]

        store.store([-1, roiid, 'bb'], [90, 80], replace=replace)

        if exists and not replace:
            assert store.table.getNumberOfRows() == 3
            d = store.table.readCoordinates(range(0, 3)).columns
            assert len(d) == 4
            assert d[0].values == [imageid, imageid, -1]
            assert d[1].values == [-1, -1, roiid]
            assert d[2].values == ['aa', 'aa', 'bb']
            assert d[3].values == [[10, 20], [10, 20], [90, 80]]
        else:
            assert store.table.getNumberOfRows() == 2
            d = store.table.readCoordinates(range(0, 2)).columns
            assert len(d) == 4
            assert d[0].values == [imageid, -1]
            assert d[1].values == [-1, roiid]
            assert d[2].values == ['aa', 'bb']
            assert d[3].values == [[10, 20], [90, 80]]

        # qs = self.sess.getQueryService()
        # q = 'SELECT l.child FROM %sAnnotationLink l WHERE l.parent.id=%d'

        # anns = qs.findAllByQuery(q % ('Image', imageid), None)
        # assert len(anns) == 1
        # assert unwrap(anns[0].getFile().getId()) == tid

        # anns = qs.findAllByQuery(q % ('Roi', roiid), None)
        # assert len(anns) == 1
        # assert unwrap(anns[0].getFile().getId()) == tid

        store.close()

    @pytest.mark.parametrize('coltype', ['single', 'multi'])
    @pytest.mark.parametrize('interleave', [True, False])
    def test_store_multi(self, coltype, interleave):
        widths = [2, 3]

        tid, tcols, meta, ftnames = TableStoreHelper.create_table(
            self.sess, self.ft_space, self.name, widths, coltype, interleave)
        imageid = unwrap(TableStoreHelper.create_image(self.sess).getId())
        roiid = unwrap(TableStoreHelper.create_roi(self.sess).getId())

        store = FeatureTable(
            self.sess, self.name, self.ft_space, self.ann_space)
        store.open_table(tid)

        store.store([imageid, -1, 'aa'], [10, 20, 30, 40, 50])
        assert store.table.getNumberOfRows() == 1

        assert store.table.getNumberOfRows() == 1
        d = store.table.readCoordinates(range(0, 1)).columns

        if coltype == 'single':
            assert len(d) == 8
            if interleave:
                assert [c.values for c in d] == [
                    [imageid], [10], [-1], [20], ['aa'], [30], [40], [50]]
            else:
                assert [c.values for c in d] == [
                    [imageid], [-1], ['aa'], [10], [20], [30], [40], [50]]
        else:
            assert len(d) == 5
            if interleave:
                assert [c.values for c in d] == [
                    [imageid], [[10, 20]], [-1], [[30, 40, 50]], ['aa']]
            else:
                assert [c.values for c in d] == [
                    [imageid], [-1], ['aa'], [[10, 20]], [[30, 40, 50]]]

        store.store([-1, roiid, 'bb'], [90, 80, 70, 60, 50])

        assert store.table.getNumberOfRows() == 2
        d = store.table.readCoordinates(range(0, 2)).columns

        if coltype == 'single':
            assert len(d) == 8
            if interleave:
                assert [c.values for c in d] == [
                    [imageid, -1],
                    [10, 90],
                    [-1, roiid],
                    [20, 80],
                    ['aa', 'bb'],
                    [30, 70],
                    [40, 60],
                    [50, 50]]
            else:
                assert [c.values for c in d] == [
                    [imageid, -1],
                    [-1, roiid],
                    ['aa', 'bb'],
                    [10, 90],
                    [20, 80],
                    [30, 70],
                    [40, 60],
                    [50, 50]]
        else:
            assert len(d) == 5
            if interleave:
                assert [c.values for c in d] == [
                    [imageid, -1],
                    [[10, 20], [90, 80]],
                    [-1, roiid],
                    [[30, 40, 50], [70, 60, 50]],
                    ['aa', 'bb']]
            else:
                assert [c.values for c in d] == [
                    [imageid, -1],
                    [-1, roiid],
                    ['aa', 'bb'],
                    [[10, 20], [90, 80]],
                    [[30, 40, 50], [70, 60, 50]]]

        store.close()

    def test_store_unowned(self):
        width = 2
        user2 = self.create_user_same_group()
        tablesess = self.create_client_session(user2)

        tid, tcols, meta, ftnames = TableStoreHelper.create_table(
            tablesess, self.ft_space, self.name, [width], 'multi', False)
        imageid = unwrap(TableStoreHelper.create_image(self.sess).getId())
        assert imageid

        store = FeatureTable(
            self.sess, self.name, self.ft_space, self.ann_space)
        store.open_table(tid)

        with pytest.raises(
                OmeroTablesFeatureStore.FeaturePermissionException):
            store.store([0, 0, ''], [10, 20])

        store.close()

    def test_store_pending_flush(self):
        width = 2

        tid, tcols, meta, ftnames = TableStoreHelper.create_table(
            self.sess, self.ft_space, self.name, [width], 'multi', False)
        imageid = unwrap(TableStoreHelper.create_image(self.sess).getId())
        roiid = unwrap(TableStoreHelper.create_roi(self.sess).getId())

        store = FeatureTable(
            self.sess, self.name, self.ft_space, self.ann_space)
        store.open_table(tid)

        store.store_pending([imageid, -1, 'aa'], [10, 20])
        assert store.table.getNumberOfRows() == 0
        store.store_pending([-1, roiid, 'bb'], [90, 80])
        assert store.table.getNumberOfRows() == 0

        store.store_flush()

        assert store.table.getNumberOfRows() == 2
        d = store.table.readCoordinates(range(0, 2)).columns
        assert len(d) == 4
        assert d[0].values == [imageid, -1]
        assert d[1].values == [-1, roiid]
        assert d[2].values == ['aa', 'bb']
        assert d[3].values == [[10, 20], [90, 80]]

        store.store_flush()
        assert store.table.getNumberOfRows() == 2

        store.close()

    def create_table_for_fetch(self, owned, widths, coltype, interleaved):
        """
        Helper method for populating a table with test data
        """
        if owned:
            tablesess = self.sess
        else:
            user2 = self.create_user_same_group()
            tablesess = self.create_client_session(user2)

        tid, tcols, meta, ftnames = TableStoreHelper.create_table(
            tablesess, self.ft_space, self.name, widths, coltype, interleaved)

        assert widths in ([1], [2, 3])
        meta = ([12, -1, 12, 13], [-1, 34, 56, -1], ['aa', 'bb', 'cc', 'dd'])
        if interleaved:
            tcols[0].values = meta[0]
            tcols[2].values = meta[1]
            if len(widths) > 1:
                tcols[4].values = meta[2]
            else:
                tcols[3].values = meta[2]
        else:
            tcols[0].values = meta[0]
            tcols[1].values = meta[1]
            tcols[2].values = meta[2]

        if widths == [1]:
            if coltype == 'single':
                values = [10, 90, 20, 30]
            else:
                values = [[10], [90], [20], [30]]
            if interleaved:
                tcols[1].values = values
            else:
                tcols[3].values = values
        else:
            if coltype == 'single':
                values = (
                    [11, 21, 31, 41], [12, 22, 32, 42], [13, 23, 33, 43],
                    [14, 24, 34, 44], [15, 25, 35, 45])
                if interleaved:
                    (tcols[1].values, tcols[3].values, tcols[5].values,
                     tcols[6].values, tcols[7].values) = values
                else:
                    (tcols[3].values, tcols[4].values, tcols[5].values,
                     tcols[6].values, tcols[7].values) = values
            else:
                values = (
                    [[11, 12], [21, 22], [31, 32], [41, 42]],
                    [[13, 14, 15], [23, 24, 25], [33, 34, 35], [43, 44, 45]])
                if interleaved:
                    tcols[1].values, tcols[3].values = values
                else:
                    tcols[3].values, tcols[4].values = values

        table = tablesess.sharedResources().openTable(
            omero.model.OriginalFileI(tid))
        table.addData(tcols)
        table.close()
        return tid

    @pytest.mark.parametrize('meta', [{'ImageID': 13}, [13, None, None]])
    @pytest.mark.parametrize('coltype', ['single', 'multi'])
    @pytest.mark.parametrize('interleave', [True, False])
    def test_fetch_by_metadata1(self, meta, coltype, interleave):
        tid = self.create_table_for_fetch(True, [1], 'multi', False)
        store = FeatureTable(
            self.sess, self.name, self.ft_space, self.ann_space)
        store.open_table(tid)

        fr = store.fetch_by_metadata(meta)

        assert len(fr) == 1
        fr = fr[0]
        assert fr.infonames == ('ImageID', 'RoiID', 'Name')
        assert fr.infovalues == (13, -1, 'dd')
        assert fr.names == ('x1',)
        assert fr.values == (30,)

        store.close()

    @pytest.mark.parametrize('meta', [
        {'ImageID': 12, 'RoiID': 56, 'Name': 'cc'}, [12, 56, 'cc']])
    @pytest.mark.parametrize('coltype', ['single', 'multi'])
    @pytest.mark.parametrize('interleave', [True, False])
    def test_fetch_by_metadata2(self, meta, coltype, interleave):
        tid = self.create_table_for_fetch(True, [1], coltype, interleave)
        store = FeatureTable(
            self.sess, self.name, self.ft_space, self.ann_space)
        store.open_table(tid)

        fr = store.fetch_by_metadata(meta)

        assert len(fr) == 1
        fr = fr[0]
        assert fr.infonames == ('ImageID', 'RoiID', 'Name')
        assert fr.infovalues == (12, 56, 'cc')
        assert fr.names == ('x1',)
        assert fr.values == (20,)

        store.close()

    @pytest.mark.parametrize('coltype', ['single', 'multi'])
    @pytest.mark.parametrize('interleave', [True, False])
    def test_fetch_by_metadata3(self, coltype, interleave):
        tid = self.create_table_for_fetch(True, [2, 3], coltype,  interleave)
        store = FeatureTable(
            self.sess, self.name, self.ft_space, self.ann_space)
        store.open_table(tid)

        meta = {'ImageID': 12}
        fr = store.fetch_by_metadata(meta)

        assert len(fr) == 2
        fr0, fr1 = fr
        assert fr0.infonames == ('ImageID', 'RoiID', 'Name')
        assert fr1.infonames == ('ImageID', 'RoiID', 'Name')
        assert fr0.infovalues == (12, -1, 'aa')
        assert fr1.infovalues == (12, 56, 'cc')
        assert fr0.names == ('x1', 'x2', 'x3', 'x4', 'x5')
        assert fr1.names == ('x1', 'x2', 'x3', 'x4', 'x5')
        assert fr0.values == (11, 12, 13, 14, 15)
        assert fr1.values == (31, 32, 33, 34, 35)

        store.close()

    @pytest.mark.parametrize('meta', [{'ImageID': 12}, [12, None, None]])
    @pytest.mark.parametrize('widths', [[1], [2, 3]])
    def test_fetch_by_metadata_raw(self, meta, widths):
        tid = self.create_table_for_fetch(True, widths, 'multi', False)
        store = FeatureTable(
            self.sess, self.name, self.ft_space, self.ann_space)
        store.open_table(tid)

        rvalues = store.fetch_by_metadata_raw(meta)

        assert len(rvalues) == 2
        if widths == [1]:
            assert rvalues[0] == (12, -1, 'aa', [10])
            assert rvalues[1] == (12, 56, 'cc', [20])
        else:
            assert rvalues[0] == (12, -1, 'aa', [11, 12], [13, 14, 15])
            assert rvalues[1] == (12, 56, 'cc', [31, 32], [33, 34, 35])

        store.close()

    @pytest.mark.parametrize('coltype', ['single', 'multi'])
    @pytest.mark.parametrize('interleave', [True, False])
    @pytest.mark.parametrize('widths', [[1], [2, 3]])
    def test_filter(self, coltype, interleave, widths):
        tid = self.create_table_for_fetch(True, widths, coltype, interleave)
        store = FeatureTable(
            self.sess, self.name, self.ft_space, self.ann_space)
        store.open_table(tid)

        fr = store.filter('(ImageID==12345) | (RoiID==34) | (Name=="abcde")')
        assert len(fr) == 1
        fr = fr[0]
        assert fr.infonames == ('ImageID', 'RoiID', 'Name')
        assert fr.infovalues == (-1, 34, 'bb')
        if widths == [1]:
            assert fr.names == ('x1',)
            assert fr.values == (90,)
        else:
            assert fr.names == ('x1', 'x2', 'x3', 'x4', 'x5')
            assert fr.values == (21, 22, 23, 24, 25)

        store.close()

    @pytest.mark.parametrize('emptyquery', [True, False])
    def test_filter_raw(self, emptyquery):
        tid = self.create_table_for_fetch(True, [1], 'multi', False)

        store = FeatureTable(
            self.sess, self.name, self.ft_space, self.ann_space)
        store.open_table(tid)

        if emptyquery:
            rvalues = store.filter_raw('')
            assert len(rvalues) == 4
            assert sorted(rvalues) == [
                (-1, 34, 'bb', [90]),
                (12, -1, 'aa', [10]),
                (12, 56, 'cc', [20]),
                (13, -1, 'dd', [30]),
                ]
        else:
            rvalues = store.filter_raw(
                '(ImageID==13) | (RoiID==34) | (Name=="cc")')
            assert len(rvalues) == 3
            assert sorted(rvalues) == [
                (-1, 34, 'bb', [90]),
                (12, 56, 'cc', [20]),
                (13, -1, 'dd', [30]),
                ]

        store.close()

    def test_get_objects(self):
        ims = [
            TableStoreHelper.create_image(self.sess, name='image-test'),
            TableStoreHelper.create_image(self.sess, name='other-test'),
            TableStoreHelper.create_image(self.sess, name='image-test')
        ]
        store = FeatureTable(
            self.sess, self.name, self.ft_space, self.ann_space)

        rs = store.get_objects('Image', {'name': 'image-test'})
        assert sorted(unwrap(r.getId()) for r in rs) == unwrap(
            [ims[0].getId(), ims[2].getId()])

        store.close()

    def test_create_file_annotation(self):
        tid, tcols, meta, ftnames = TableStoreHelper.create_table(
            self.sess, self.ft_space, self.name, [1], 'multi', False)
        imageid = unwrap(TableStoreHelper.create_image(self.sess).getId())
        ofile = self.sess.getQueryService().get(
            'omero.model.OriginalFile', tid)
        store = FeatureTable(
            self.sess, self.name, self.ft_space, self.ann_space)

        assert store._file_annotation_exists(
            'Image', imageid, self.ann_space, tid) == []

        link = store.create_file_annotation(
            'Image', imageid, self.ann_space, ofile)
        p = link.getParent()
        c = link.getChild()
        assert isinstance(p, omero.model.Image)
        assert isinstance(c, omero.model.FileAnnotation)
        assert unwrap(p.getId()) == imageid
        assert unwrap(c.getFile().getId()) == tid

        links = store._file_annotation_exists(
            'Image', imageid, self.ann_space, tid)
        assert len(links) == 1
        assert links[0].__class__ == link.__class__ and links[0].id == link.id

        store.close()

    @pytest.mark.parametrize('owned', [True, False])
    def test_delete(self, owned):
        if owned:
            tablesess = self.sess
        else:
            user2 = self.create_user_same_group()
            tablesess = self.create_client_session(user2)

        iid1 = unwrap(TableStoreHelper.create_image(self.sess).getId())
        iid2 = unwrap(TableStoreHelper.create_image(self.sess).getId())
        store = FeatureTable(
            tablesess, self.name, self.ft_space, self.ann_space)
        store.new_table([('Long', 'id')], ['x'])
        ofile = store.get_table().getOriginalFile()

        link1 = store.create_file_annotation(
            'Image', iid1, self.ann_space, ofile)
        link2 = store.create_file_annotation(
            'Image', iid2, self.ann_space, ofile)

        if not owned:
            store.close()
            # Reopen the store with a different session
            store = FeatureTable(
                self.sess, self.name, self.ft_space, self.ann_space)
            store.open_table(unwrap(ofile.getId()))

        def get(obj):
            # Fetch the latest copy of an object
            return self.sess.getQueryService().find(
                'omero.model.%s' % obj.__class__.__name__, unwrap(obj.getId()))

        assert get(link1) is not None
        assert get(link1.getParent()) is not None
        assert get(link1.getChild())
        assert get(link1.getChild().getFile())

        assert get(link2)
        assert get(link2.getParent())
        assert get(link2.getChild())
        assert get(link2.getChild().getFile())

        if owned:
            store.delete()

            assert get(link1) is None
            assert get(link1.getParent())
            assert get(link1.getChild()) is None
            assert get(link1.getChild().getFile()) is None

            assert get(link2) is None
            assert get(link2.getParent())
            assert get(link2.getChild()) is None
            assert get(link2.getChild().getFile()) is None
        else:
            with pytest.raises(
                    OmeroTablesFeatureStore.FeaturePermissionException):
                store.delete()

        store.close()


class TestOmeroTablesFeatureStore(TableStoreTestHelper):

    # Need a new account for each test, so disable setup_class and call it
    # for each method instead

    def setup_class(self):
        pass

    def teardown_class(self):
        pass

    def setup_method(self, method):
        super(TestOmeroTablesFeatureStore, self).setup_class()
        super(TestOmeroTablesFeatureStore, self).setup_method(method)

    def teardown_method(self, method):
        super(TestOmeroTablesFeatureStore, self).teardown_method(method)
        super(TestOmeroTablesFeatureStore, self).teardown_class()

    INVALID_UID = long(sys.maxint)

    @staticmethod
    def get_table_id(ft):
        return unwrap(ft.get_table().getOriginalFile().getId())

    # list_tables(session, name, ft_space, ann_space, ownerid, parent)

    def setup_tables_for_list(self):
        tcols, meta, ftnames = TableStoreHelper.get_columns(
            [2], 'multi', False)

        iid = unwrap(TableStoreHelper.create_image(self.sess).getId())
        store1 = OmeroTablesFeatureStore.new_table(
            self.sess, 'name-1', 'ft_space-12', 'ann_space-1', meta, ftnames,
            'Image:%s' % iid)
        store2 = OmeroTablesFeatureStore.new_table(
            self.sess, 'name-2', 'ft_space-12', 'ann_space-2', meta, ftnames)

        r1 = (self.get_table_id(store1),
              'name-1', 'ft_space-12', 'ann_space-1')
        r2 = (self.get_table_id(store2),
              'name-2', 'ft_space-12', 'ann_space-2')

        store1.close()
        store2.close()

        return r1, r2, iid

    @pytest.mark.parametrize('name', [None, 'name-2'])
    @pytest.mark.parametrize('ann_space', [None, 'ann_space-1'])
    @pytest.mark.parametrize('parent', [None, True, False])
    def test_list_tables_ann(self, name, ann_space, parent):
        r1, r2, iid = self.setup_tables_for_list()
        r1noann = tuple(r1[:-1] + (None,))
        r2noann = tuple(r2[:-1] + (None,))

        if parent is None:
            parentim = None
        elif parent:
            parentim = 'Image:%s' % iid
        else:
            # Non-existent
            parentim = 'Image:%s' % (iid + 1)

        expected1 = (
            (not name or name == 'name-1') and
            (not ann_space or ann_space == 'ann_space-1') and
            (parent is None or parent))
        expected2 = (
            (not name or name == 'name-2') and
            (not ann_space) and
            (parent is None))

        if name is None and ann_space is None and parent is None:
            with pytest.raises(OmeroTablesFeatureStore.OmeroTableException):
                tables = OmeroTablesFeatureStore.list_tables(
                    self.sess, name=name, ann_space=ann_space, parent=parentim)
        else:
            tables = OmeroTablesFeatureStore.list_tables(
                self.sess, name=name, ann_space=ann_space, parent=parentim)
            assert len(tables) in (0, 1, 2)
            if ann_space is None and parent is None:
                assert (r1noann in tables) == expected1
                assert (r2noann in tables) == expected2
            else:
                assert (r1 in tables) == expected1
                assert (r2 in tables) == expected2

    @pytest.mark.parametrize('name', [None, 'name-1'])
    @pytest.mark.parametrize('ft_space', [None, 'ft_space-12'])
    @pytest.mark.parametrize('owner', [-1, INVALID_UID, 'uid'])
    def test_list_tables_noann(self, name, ft_space, owner):
        uid = unwrap(self.user.getId())
        r1, r2, iid = self.setup_tables_for_list()
        # Ignore ann_space
        r1noann = tuple(r1[:-1] + (None,))
        r2noann = tuple(r2[:-1] + (None,))

        if owner == 'uid':
            ownerid = uid
        else:
            ownerid = owner

        expected1 = (
            (not name or name == 'name-1') and
            (not ft_space or ft_space == 'ft_space-12') and
            (ownerid is None or ownerid == -1 or ownerid == uid))
        expected2 = (
            (not name or name == 'name-2') and
            (not ft_space or ft_space == 'ft_space-12') and
            (ownerid is None or ownerid == -1 or ownerid == uid))

        if name is None and ft_space is None and (owner in (None, -1)):
            with pytest.raises(OmeroTablesFeatureStore.OmeroTableException):
                tables = OmeroTablesFeatureStore.list_tables(
                    self.sess, name=name, ft_space=ft_space, ownerid=ownerid)
        else:
            tables = OmeroTablesFeatureStore.list_tables(
                self.sess, name=name, ft_space=ft_space, ownerid=ownerid)
            assert len(tables) in (0, 1, 2)
            assert (r1noann in tables) == expected1
            assert (r2noann in tables) == expected2

    def test_open_table(self):
        tid, tcols, meta, ftnames = TableStoreHelper.create_table(
            self.sess, self.ft_space, self.name, [1], 'multi', False)
        store = OmeroTablesFeatureStore.open_table(
            self.sess, tid, self.ann_space)
        assert unwrap(store.get_table().getOriginalFile().getId()) == tid
        assert store.ann_space == self.ann_space
        store.close()

    @pytest.mark.parametrize('parent', [True, False])
    def test_new_table(self, parent):
        tcols, meta, ftnames = TableStoreHelper.get_columns(
            [2], 'multi', False)

        if parent:
            iid = unwrap(TableStoreHelper.create_image(self.sess).getId())
            store = OmeroTablesFeatureStore.new_table(
                self.sess, self.name, self.ft_space, self.ann_space,
                meta, ftnames, 'Image:%d' % iid)
        else:
            store = OmeroTablesFeatureStore.new_table(
                self.sess, self.name, self.ft_space, self.ann_space,
                meta, ftnames)

        assert store.table
        TableStoreHelper.assert_coltypes_equal(store.cols, tcols)

        if parent:
            tid = unwrap(store.get_table().getOriginalFile().getId())
            q = ('SELECT link.child FROM ImageAnnotationLink link '
                 'WHERE link.parent.id=:id')
            p = omero.sys.ParametersI()
            p.addId(iid)
            r = self.sess.getQueryService().findAllByQuery(q, p)
            assert len(r) == 1
            assert isinstance(r[0], omero.model.FileAnnotation)
            assert unwrap(r[0].getFile().getId()) == tid

        store.close()


class TestFeatureTableManager(TableStoreTestHelper):

    def test_create(self, fsname='fsname-create'):
        meta = [('Image', 'ImageID'), ('Roi', 'RoiID')]
        colnames = ('x1', 'x2')
        fts = OmeroTablesFeatureStore.FeatureTableManager(
            self.sess, ft_space=self.ft_space, ann_space=self.ann_space)
        fs = fts.create(fsname, meta, colnames)

        expected_cols = [
            omero.grid.ImageColumn('ImageID', '{"columntype": "metadata"}'),
            omero.grid.RoiColumn('RoiID', '{"columntype": "metadata"}'),
            omero.grid.DoubleArrayColumn(
                'x1,x2', '{"columntype": "multifeature"}', 2),
        ]
        h = fs.get_table().getHeaders()
        TableStoreHelper.assert_coltypes_equal(expected_cols, h)
        assert fs.feature_names() == colnames

        with pytest.raises(OmeroTablesFeatureStore.TooManyTablesException):
            fs = fts.create(fsname, meta, colnames)

        fts.close()

    def test_get(self):
        uid = unwrap(self.user.getId())
        fsname1 = 'fsname-get1'
        fsname2 = 'fsname-get2'
        fts = OmeroTablesFeatureStore.FeatureTableManager(
            self.sess, ft_space=self.ft_space, ann_space=self.ann_space)

        with pytest.raises(OmeroTablesFeatureStore.NoTableMatchException):
            fts.get(fsname1)

        self.test_create(fsname1)

        fs1 = fts.get(fsname1)
        assert fs1 is not None

        assert fs1 == fts.get(fsname1)

        self.test_create(fsname2)
        fs2 = fts.get(fsname2)
        assert fs2 is not None

        assert unwrap(fs1.get_table().getOriginalFile().getId()) != unwrap(
            fs2.get_table().getOriginalFile().getId())

        fts.close()

        user2 = self.create_user_same_group()
        sess2 = self.create_client_session(user2)
        uid2 = unwrap(user2.getId())
        fts2 = OmeroTablesFeatureStore.FeatureTableManager(
            sess2, ft_space=self.ft_space, ann_space=self.ann_space)

        # Check ownerId is respected
        with pytest.raises(OmeroTablesFeatureStore.NoTableMatchException):
            fts2.get(fsname1)
        with pytest.raises(OmeroTablesFeatureStore.NoTableMatchException):
            fts2.get(fsname1, uid2)
        assert fts.get(fsname1, uid) is not None

        fts2.close()
