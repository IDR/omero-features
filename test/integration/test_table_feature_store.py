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

import omero
from omero.rtypes import rstring, unwrap, wrap

from features import OmeroTablesFeatureStore


class FeatureTableProxy(OmeroTablesFeatureStore.FeatureTable):
    """
    Replaces __init__ so that get_table() isn't called
    """
    def __init__(self, session, name, ft_space, ann_space, coldesc=None):
        self.session = session
        self.perms = OmeroTablesFeatureStore.PermissionsHandler(session)
        self.name = name
        self.ft_space = ft_space
        self.ann_space = ann_space
        self.cols = None
        self.pendingcols = None
        self.table = None
        self.metanames = None
        self.ftnames = None
        self.header = None
        self.editable = None
        self.chunk_size = None


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
    def get_columns(w):
        meta = [('Image', 'ImageID'), ('Roi', 'RoiID')]
        ftnames = ['x%d' % n for n in xrange(1, w + 1)]
        cols = [
            omero.grid.ImageColumn('ImageID'),
            omero.grid.RoiColumn('RoiID'),
            omero.grid.DoubleArrayColumn(','.join(ftnames), '', w),
        ]
        return cols, meta, ftnames

    @staticmethod
    def create_table(sess, path, name, width):
        table = sess.sharedResources().newTable(0, 'name')
        cols, meta, ftnames = TableStoreHelper.get_columns(width)
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
        store = FeatureTableProxy(
            self.sess, self.name, self.ft_space, self.ann_space)
        with pytest.raises(OmeroTablesFeatureStore.TableUsageException):
            store.get_table()

        tcols, meta, ftnames = TableStoreHelper.get_columns(2)
        store.new_table(meta, ftnames)
        assert store.get_table()
        store.close()

    @pytest.mark.parametrize('exists', [True, False])
    @pytest.mark.parametrize('ofile', [True, False])
    def test_open_or_create_table(self, exists, ofile):
        store = FeatureTableProxy(
            self.sess, self.name, self.ft_space, self.ann_space)
        uid = unwrap(self.user.getId())

        if exists:
            tid, tcols, meta, ftnames = TableStoreHelper.create_table(
                self.sess, self.ft_space, self.name, 1)
            if ofile:
                table = store.open_or_create_table(uid, ofileid=tid)
            else:
                table = store.open_or_create_table(uid)

            assert table and table == store.table
            TableStoreHelper.assert_coltypes_equal(store.cols, tcols)
        else:
            with pytest.raises(OmeroTablesFeatureStore.NoTableMatchException):
                if ofile:
                    store.open_or_create_table(uid, ofileid=-1L)
                else:
                    store.open_or_create_table(uid)

        store.close()

    def test_new_table(self):
        tcols, meta, ftnames = TableStoreHelper.get_columns(2)

        store = FeatureTableProxy(
            self.sess, self.name, self.ft_space, self.ann_space)
        store.new_table(meta, ftnames)
        assert store.table
        TableStoreHelper.assert_coltypes_equal(store.cols, tcols)

        assert store.metadata_names() == [m[1] for m in meta]
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
            self.sess, self.ft_space, self.name, 1)

        store = FeatureTableProxy(
            self.sess, self.name, self.ft_space, self.ann_space)
        store.open_table(omero.model.OriginalFileI(tid))
        assert store.table
        TableStoreHelper.assert_coltypes_equal(store.cols, tcols)
        assert store.metadata_names() == [m[1] for m in meta]
        assert store.feature_names() == ftnames

        store.close()

    @pytest.mark.parametrize('exists', [True, False])
    @pytest.mark.parametrize('replace', [True, False])
    def test_store(self, exists, replace):
        width = 2

        tid, tcols, meta, ftnames = TableStoreHelper.create_table(
            self.sess, self.ft_space, self.name, width)
        imageid = unwrap(TableStoreHelper.create_image(self.sess).getId())
        roiid = unwrap(TableStoreHelper.create_roi(self.sess).getId())

        store = FeatureTableProxy(
            self.sess, self.name, self.ft_space, self.ann_space)
        store.open_table(omero.model.OriginalFileI(tid))

        if exists:
            store.store([imageid, -1], [10, 20])
            assert store.table.getNumberOfRows() == 1

        store.store([imageid, -1], [10, 20], replace=replace)

        if exists and not replace:
            assert store.table.getNumberOfRows() == 2
            d = store.table.readCoordinates(range(0, 2)).columns
            assert len(d) == 3
            assert d[0].values == [imageid, imageid]
            assert d[1].values == [-1, -1]
            assert d[2].values == [[10, 20], [10, 20]]
        else:
            assert store.table.getNumberOfRows() == 1
            d = store.table.readCoordinates(range(0, 1)).columns
            assert len(d) == 3
            assert d[0].values == [imageid]
            assert d[1].values == [-1]
            assert d[2].values == [[10, 20]]

        store.store([-1, roiid], [90, 80], replace=replace)

        if exists and not replace:
            assert store.table.getNumberOfRows() == 3
            d = store.table.readCoordinates(range(0, 3)).columns
            assert len(d) == 3
            assert d[0].values == [imageid, imageid, -1]
            assert d[1].values == [-1, -1, roiid]
            assert d[2].values == [[10, 20], [10, 20], [90, 80]]
        else:
            assert store.table.getNumberOfRows() == 2
            d = store.table.readCoordinates(range(0, 2)).columns
            assert len(d) == 3
            assert d[0].values == [imageid, -1]
            assert d[1].values == [-1, roiid]
            assert d[2].values == [[10, 20], [90, 80]]

        # qs = self.sess.getQueryService()
        # q = 'SELECT l.child FROM %sAnnotationLink l WHERE l.parent.id=%d'

        # anns = qs.findAllByQuery(q % ('Image', imageid), None)
        # assert len(anns) == 1
        # assert unwrap(anns[0].getFile().getId()) == tid

        # anns = qs.findAllByQuery(q % ('Roi', roiid), None)
        # assert len(anns) == 1
        # assert unwrap(anns[0].getFile().getId()) == tid

        store.close()

    def test_store_unowned(self):
        width = 2
        user2 = self.create_user_same_group()
        tablesess = self.create_client_session(user2)

        tid, tcols, meta, ftnames = TableStoreHelper.create_table(
            tablesess, self.ft_space, self.name, width)
        imageid = unwrap(TableStoreHelper.create_image(self.sess).getId())
        assert imageid

        store = FeatureTableProxy(
            self.sess, self.name, self.ft_space, self.ann_space)
        store.open_table(omero.model.OriginalFileI(tid))

        with pytest.raises(
                OmeroTablesFeatureStore.FeaturePermissionException):
            store.store([0, 0], [10, 20])

        store.close()

    def test_store_pending_flush(self):
        width = 2

        tid, tcols, meta, ftnames = TableStoreHelper.create_table(
            self.sess, self.ft_space, self.name, width)
        imageid = unwrap(TableStoreHelper.create_image(self.sess).getId())
        roiid = unwrap(TableStoreHelper.create_roi(self.sess).getId())

        store = FeatureTableProxy(
            self.sess, self.name, self.ft_space, self.ann_space)
        store.open_table(omero.model.OriginalFileI(tid))

        store.store_pending([imageid, -1], [10, 20])
        assert store.table.getNumberOfRows() == 0
        store.store_pending([-1, roiid], [90, 80])
        assert store.table.getNumberOfRows() == 0

        store.store_flush()

        assert store.table.getNumberOfRows() == 2
        d = store.table.readCoordinates(range(0, 2)).columns
        assert len(d) == 3
        assert d[0].values == [imageid, -1]
        assert d[1].values == [-1, roiid]
        assert d[2].values == [[10, 20], [90, 80]]

        store.store_flush()
        assert store.table.getNumberOfRows() == 2

        store.close()

    def create_table_for_fetch(self, owned, width):
        if owned:
            tablesess = self.sess
        else:
            user2 = self.create_user_same_group()
            tablesess = self.create_client_session(user2)

        tid, tcols, meta, ftnames = TableStoreHelper.create_table(
            tablesess, self.ft_space, self.name, width)

        tcols[0].values = [12, -1, 12, 13]
        tcols[1].values = [-1, 34, 56, -1]
        if width == 1:
            tcols[2].values = [[10], [90], [20], [30]]
        else:
            tcols[2].values = [[20, 30], [80, 70], [40, 50], [60, 70]]
        table = tablesess.sharedResources().openTable(
            omero.model.OriginalFileI(tid))
        table.addData(tcols)
        table.close()
        return tid

    @pytest.mark.parametrize('meta', [{'ImageID': 13}, [13, None]])
    def test_fetch_by_metadata1(self, meta):
        tid = self.create_table_for_fetch(owned=True, width=1)
        store = FeatureTableProxy(
            self.sess, self.name, self.ft_space, self.ann_space)
        store.open_table(omero.model.OriginalFileI(tid))

        fr = store.fetch_by_metadata(meta)

        assert len(fr) == 1
        fr = fr[0]
        assert fr.infonames == ['ImageID', 'RoiID']
        assert fr.infovalues == (13, -1)
        assert fr.names == ['x1']
        assert fr.values == [30]

        store.close()

    @pytest.mark.parametrize('meta', [{'ImageID': 12, 'RoiID': 56}, [12, 56]])
    def test_fetch_by_metadata2(self, meta):
        tid = self.create_table_for_fetch(owned=True, width=1)
        store = FeatureTableProxy(
            self.sess, self.name, self.ft_space, self.ann_space)
        store.open_table(omero.model.OriginalFileI(tid))

        fr = store.fetch_by_metadata(meta)

        assert len(fr) == 1
        fr = fr[0]
        assert fr.infonames == ['ImageID', 'RoiID']
        assert fr.infovalues == (12, 56)
        assert fr.names == ['x1']
        assert fr.values == [20]

        store.close()

    @pytest.mark.parametrize('meta', [{'ImageID': 12}, [12, None]])
    @pytest.mark.parametrize('width', [1, 2])
    def test_fetch_by_metadata_raw(self, meta, width):
        tid = self.create_table_for_fetch(owned=True, width=width)
        store = FeatureTableProxy(
            self.sess, self.name, self.ft_space, self.ann_space)
        store.open_table(omero.model.OriginalFileI(tid))

        rvalues = store.fetch_by_metadata_raw(meta)

        assert len(rvalues) == 2
        if width == 1:
            assert rvalues[0] == (12, -1, [10])
            assert rvalues[1] == (12, 56, [20])
        else:
            assert rvalues[0] == (12, -1, [20, 30])
            assert rvalues[1] == (12, 56, [40, 50])

        store.close()

    def test_filter(self):
        tid = self.create_table_for_fetch(owned=True, width=1)
        store = FeatureTableProxy(
            self.sess, self.name, self.ft_space, self.ann_space)
        store.open_table(omero.model.OriginalFileI(tid))

        fr = store.filter('(ImageID==12345) | (RoiID==34)')
        assert len(fr) == 1
        assert fr[0].infonames == ['ImageID', 'RoiID']
        assert fr[0].infovalues == (-1, 34)
        assert fr[0].names == ['x1']
        assert fr[0].values == [90]

        store.close()

    @pytest.mark.parametrize('emptyquery', [True, False])
    def test_filter_raw(self, emptyquery):
        tid = self.create_table_for_fetch(owned=True, width=1)

        store = FeatureTableProxy(
            self.sess, self.name, self.ft_space, self.ann_space)
        store.open_table(omero.model.OriginalFileI(tid))

        if emptyquery:
            rvalues = store.filter_raw('')
            assert len(rvalues) == 4
            assert sorted(rvalues) == [
                (-1, 34, [90]),
                (12, -1, [10]),
                (12, 56, [20]),
                (13, -1, [30]),
                ]
        else:
            rvalues = store.filter_raw('(ImageID==13) | (RoiID==34)')
            assert len(rvalues) == 2
            assert sorted(rvalues) == [(-1, 34, [90]), (13, -1, [30])]

        store.close()

    def test_get_objects(self):
        ims = [
            TableStoreHelper.create_image(self.sess, name='image-test'),
            TableStoreHelper.create_image(self.sess, name='other-test'),
            TableStoreHelper.create_image(self.sess, name='image-test')
        ]
        store = FeatureTableProxy(
            self.sess, self.name, self.ft_space, self.ann_space)

        rs = store.get_objects('Image', {'name': 'image-test'})
        assert sorted(unwrap(r.getId()) for r in rs) == unwrap(
            [ims[0].getId(), ims[2].getId()])

        store.close()

    def test_create_file_annotation(self):
        tid, tcols, meta, ftnames = TableStoreHelper.create_table(
            self.sess, self.ft_space, self.name, 1)
        imageid = unwrap(TableStoreHelper.create_image(self.sess).getId())
        ofile = self.sess.getQueryService().get(
            'omero.model.OriginalFile', tid)
        store = FeatureTableProxy(
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
        uid = unwrap(self.user.getId())
        if owned:
            tablesess = self.sess
            ownerid = uid
        else:
            user2 = self.create_user_same_group()
            tablesess = self.create_client_session(user2)
            ownerid = unwrap(user2.getId())

        iid1 = unwrap(TableStoreHelper.create_image(self.sess).getId())
        iid2 = unwrap(TableStoreHelper.create_image(self.sess).getId())
        store = FeatureTableProxy(
            tablesess, self.name, self.ft_space, self.ann_space)
        ofile = store.open_or_create_table(
            ownerid, [('Long', 'id')], ['x']).getOriginalFile()

        link1 = store.create_file_annotation(
            'Image', iid1, self.ann_space, ofile)
        link2 = store.create_file_annotation(
            'Image', iid2, self.ann_space, ofile)

        if not owned:
            store.close()
            # Reopen the store with a different session
            store = FeatureTableProxy(
                self.sess, self.name, self.ft_space, self.ann_space)
            store.open_or_create_table(ownerid)

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


class TestFeatureTableManager(TableStoreTestHelper):

    def test_create(self, fsname='fsname-create'):
        meta = [('Image', 'ImageID'), ('Roi', 'RoiID')]
        colnames = ['x1', 'x2']
        fts = OmeroTablesFeatureStore.FeatureTableManager(
            self.sess, ft_space=self.ft_space, ann_space=self.ann_space)
        fs = fts.create(fsname, meta, colnames)

        expected_cols = [
            omero.grid.ImageColumn('ImageID', ''),
            omero.grid.RoiColumn('RoiID', ''),
            omero.grid.DoubleArrayColumn('x1,x2', '', 2),
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
