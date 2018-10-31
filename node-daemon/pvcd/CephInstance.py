#!/usr/bin/env python3

# CehpInstance.py - Class implementing a PVC node Ceph instance
# Part of the Parallel Virtual Cluster (PVC) system
#
#    Copyright (C) 2018  Joshua M. Boniface <joshua@boniface.me>
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
###############################################################################

import time
import ast
import json
import psutil

import pvcd.log as log
import pvcd.zkhandler as zkhandler
import pvcd.fencing as fencing
import pvcd.common as common

class CephInstance(object):
    def __init__(self):
        pass

class CephOSDInstance(object):
    def __init__(self, zk_conn, this_node, osd_id):
        self.zk_conn = zk_conn
        self.this_node = this_node
        self.osd_id = osd_id
        self.node = None
        self.size = None
        self.stats = dict()

        @self.zk_conn.DataWatch('/ceph/osds/{}/node'.format(self.osd_id))
        def watch_osd_node(data, stat, event=''):
            if event and event.type == 'DELETED':
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            try:
                data = data.decode('ascii')
            except AttributeError:
                data = ''

            if data and data != self.node:
                self.node = data

        @self.zk_conn.DataWatch('/ceph/osds/{}/stats'.format(self.osd_id))
        def watch_osd_stats(data, stat, event=''):
            if event and event.type == 'DELETED':
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            try:
                data = data.decode('ascii')
            except AttributeError:
                data = ''

            if data and data != self.stats:
                self.stats = json.loads(data)

def add_osd(zk_conn, logger, node, device):
    # We are ready to create a new OSD on this node
    logger.out('Creating new OSD disk', state='i')
    try:
        # 1. Create an OSD; we do this so we know what ID will be gen'd
        retcode, stdout, stderr = common.run_os_command('ceph osd create')
        if retcode:
            print('ceph osd create')
            print(stdout)
            print(stderr)
            raise
        osd_id = stdout.rstrip()

        # 2. Remove that newly-created OSD
        retcode, stdout, stderr = common.run_os_command('ceph osd rm {}'.format(osd_id))
        if retcode:
            print('ceph osd rm')
            print(stdout)
            print(stderr)
            raise

        # 3. Create the OSD for real
        retcode, stdout, stderr = common.run_os_command(
            'ceph-volume lvm prepare --bluestore --data {device}'.format(
                osdid=osd_id,
                device=device
            )
        )
        if retcode:
            print('ceph-volume lvm prepare')
            print(stdout)
            print(stderr)
            raise

        # 4. Activate the OSD
        retcode, stdout, stderr = common.run_os_command(
            'ceph-volume lvm activate --bluestore {osdid}'.format(
                osdid=osd_id
            )
        )
        if retcode:
            print('ceph-volume lvm activate')
            print(stdout)
            print(stderr)
            raise

        # 5. Add it to the crush map
        retcode, stdout, stderr = common.run_os_command(
            'ceph osd crush add osd.{osdid} 1.0 root=default host={node}'.format(
                osdid=osd_id,
                node=node
            )
        )
        if retcode:
            print('ceph osd crush add')
            print(stdout)
            print(stderr)
            raise
        time.sleep(0.5)

        # 6. Verify it started
        retcode, stdout, stderr = common.run_os_command(
            'systemctl status ceph-osd@{osdid}'.format(
                osdid=osd_id
            )
        )
        if retcode:
            print('systemctl status')
            print(stdout)
            print(stderr)
            raise

        # 7. Add the new OSD to the list
        zkhandler.writedata(zk_conn, {
            '/ceph/osds/{}'.format(osd_id): '',
            '/ceph/osds/{}/node'.format(osd_id): node,
            '/ceph/osds/{}/stats'.format(osd_id): '{}'
        })

        # Log it
        logger.out('Created new OSD disk with ID {}'.format(osd_id), state='o')
        return True
    except Exception as e:
        # Log it
        logger.out('Failed to create new OSD disk: {}'.format(e), state='e')
        return False

def remove_osd(zk_conn, logger, osd_id, osd_obj):
    logger.out('Removing OSD disk {}'.format(osd_id), state='i')
    try:
        # 1. Verify the OSD is present
        retcode, stdout, stderr = common.run_os_command('ceph osd ls')
        osd_list = stdout.split('\n')
        if not osd_id in osd_list:
            logger.out('Could not find OSD {} in the cluster'.format(osd_id), state='e')
            return True
            
        # 1. Set the OSD out so it will flush
        retcode, stdout, stderr = common.run_os_command('ceph osd out {}'.format(osd_id))
        if retcode:
            print('ceph osd out')
            print(stdout)
            print(stderr)
            raise
        
        # 2. Wait for the OSD to flush
        osd_string = str()
        while True:
            retcode, stdout, stderr = common.run_os_command('ceph pg dump osds --format json')
            dump_string = json.loads(stdout)
            for osd in dump_string:
                if str(osd['osd']) == osd_id:
                    osd_string = osd
            print(osd_string)
            num_pgs = osd_string['num_pgs']
            if num_pgs > 0:
               time.sleep(5)
            else:
               break

        # 3. Stop the OSD process and wait for it to be terminated
        retcode, stdout, stderr = common.run_os_command('systemctl stop ceph-osd@{}'.format(osd_id))
        if retcode:
            print('systemctl stop')
            print(stdout)
            print(stderr)
            raise

        # FIXME: There has to be a better way to do this /shrug
        while True:
            is_osd_up = False
            # Find if there is a process named ceph-osd with arg '--id {id}'
            for p in psutil.process_iter(attrs=['name', 'cmdline']):
                if 'ceph-osd' == p.info['name'] and '--id {}'.format(osd_id) in ' '.join(p.info['cmdline']):
                    is_osd_up = True
            # If there isn't, continue
            if not is_osd_up:
                break

        # 4. Delete OSD from ZK
        zkhandler.deletekey(zk_conn, '/ceph/osds/{}'.format(osd_id))

        # 5. Determine the block devices
        retcode, stdout, stderr = common.run_os_command('readlink /var/lib/ceph/osd/ceph-{}/block'.format(osd_id))
        vg_name = stdout.split('/')[-2] # e.g. /dev/ceph-<uuid>/osd-block-<uuid>
        retcode, stdout, stderr = common.run_os_command('vgs --separator , --noheadings -o pv_name {}'.format(vg_name))
        pv_block = stdout

        # 6. Zap the volumes
        retcode, stdout, stderr = common.run_os_command('ceph-volume lvm zap --destroy {}'.format(pv_block))
        if retcode:
            print('ceph-volume lvm zap')
            print(stdout)
            print(stderr)
            raise
        
        # 7. Purge the OSD from Ceph
        retcode, stdout, stderr = common.run_os_command('ceph osd purge {} --yes-i-really-mean-it'.format(osd_id))
        if retcode:
            print('ceph osd purge')
            print(stdout)
            print(stderr)
            raise

        # Log it
        logger.out('Purged OSD disk with ID {}'.format(osd_id), state='o')
        return True
    except Exception as e:
        # Log it
        logger.out('Failed to purge OSD disk with ID {}: {}'.format(osd_id, e), state='e')
        return False

class CephPool(object):
    def __init__(self):
        pass
