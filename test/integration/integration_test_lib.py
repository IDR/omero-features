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

import uuid

import omero
from omero.rtypes import rbool, rstring


class UserAccount(object):
    """
    Copied from components/tools/OmeroPy/test/integration/library.py
    """

    def __init__(self):
        self.root = omero.client()
        self.root.setAgent(__name__)
        rootpass = self.root.getProperty('omero.rootpass')
        self.root.createSession('root', rootpass)

    def close(self):
        self.root.closeSession()

    @staticmethod
    def uuid():
        return str(uuid.uuid4())

    def new_user(self, group=None, perms=None,
                 admin=False, system=False):
        """
        admin: If user is to be an admin of the created group
        system: If user is to be a system admin
        """

        if not self.root:
            raise Exception('No root client. Cannot create user')

        adminService = self.root.getSession().getAdminService()
        name = self.uuid()

        # Create group if necessary
        if not group:
            g = self.new_group(perms=perms)
        else:
            g = group

        # Create user
        e = omero.model.ExperimenterI()
        e.omeName = rstring(name)
        e.firstName = rstring(name)
        e.lastName = rstring(name)
        e.ldap = rbool(False)
        uid = adminService.createExperimenterWithPassword(
            e, rstring(name), g, [g, adminService.lookupGroup('user')])
        e = adminService.lookupExperimenter(name)
        if admin:
            adminService.setGroupOwner(g, e)
        if system:
            adminService.addGroups(e,
                                   [omero.model.ExperimenterGroupI(0, False)])

        return adminService.getExperimenter(uid)

    def new_group(self, experimenters=None, perms=None):
        admin = self.root.sf.getAdminService()
        gname = self.uuid()
        group = omero.model.ExperimenterGroupI()
        group.name = rstring(gname)
        group.ldap = rbool(False)
        if perms:
            group.details.permissions = omero.model.PermissionsI(perms)
        gid = admin.createGroup(group)
        group = admin.getGroup(gid)
        self.add_experimenters(group, experimenters)
        return group

    def add_experimenters(self, group, experimenters):
        admin = self.root.sf.getAdminService()
        if experimenters:
            for exp in experimenters:
                user, name = self.user_and_name(exp)
                admin.addGroups(user, [group])
