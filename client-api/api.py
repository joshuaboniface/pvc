#!/usr/bin/env python3

# api.py - PVC HTTP API interface
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

import flask
import json

import api_lib.pvcapi as pvcapi

zk_host = "hv1:2181,hv2:2181,hv3:2181"

api = flask.Flask(__name__)
api.config["DEBUG"] = True

@api.route('/api/v1', methods=['GET'])
def api_root():
    return "PVC API version 1", 209

#
# Node endpoints
#
@api.route('/api/v1/node', methods=['GET'])
def api_node():
    """
    Return a list of nodes with limit LIMIT.
    """
    # Get name limit
    if 'limit' in flask.request.values:
        limit = flask.request.values['limit']
    else:
        limit = None

    return pvcapi.node_list(limit)

@api.route('/api/v1/node/<node>', methods=['GET'])
def api_node_info(node):
    """
    Return information about node NODE.
    """
    # Same as specifying /node?limit=NODE
    return pvcapi.node_list(node)

@api.route('/api/v1/node/<node>/secondary', methods=['POST'])
def api_node_secondary(node):
    """
    Take NODE out of primary router mode.
    """
    return pvcapi.node_secondary(node)

@api.route('/api/v1/node/<node>/primary', methods=['POST'])
def api_node_primary(node):
    """
    Set NODE to primary router mode.
    """
    return pvcapi.node_primary(node)

@api.route('/api/v1/node/<node>/flush', methods=['POST'])
def api_node_flush(node):
    """
    Flush NODE of running VMs.
    """
    return pvcapi.node_flush(node)

@api.route('/api/v1/node/<node>/unflush', methods=['POST'])
@api.route('/api/v1/node/<node>/ready', methods=['POST'])
def api_node_ready(node):
    """
    Restore NODE to active service.
    """
    return pvcapi.node_ready(node)

#
# VM endpoints
#
@api.route('/api/v1/vm', methods=['GET'])
def api_vm():
    """
    Return a list of VMs with limit LIMIT.
    """
    # Get node limit
    if 'node' in flask.request.values:
        node = flask.request.values['node']
    else:
        node = None

    # Get state limit
    if 'state' in flask.request.values:
        state = flask.request.values['state']
    else:
        state = None

    # Get name limit
    if 'limit' in flask.request.values:
        limit = flask.request.values['limit']
    else:
        limit = None

    return pvcapi.vm_list(node, state, limit)

@api.route('/api/v1/vm/<vm>', methods=['GET'])
def api_vm_info(vm):
    """
    Get information about a virtual machine named VM.
    """
    # Same as specifying /vm?limit=VM
    return pvcapi.vm_list(None, None, vm, is_fuzzy=False)

# TODO: #22
#@api.route('/api/v1/vm/<vm>/add', methods=['POST'])
#def api_vm_add(vm):
#    """
#    Add a virtual machine named VM.
#    """
#    return pvcapi.vm_add()

@api.route('/api/v1/vm/<vm>/define', methods=['POST'])
def api_vm_define(vm):
    """
    Define a virtual machine named VM from Libvirt XML. Send only the Libvirt XML as data.
    """
    # Get XML from the POST body
    libvirt_xml = flask.request.data

    # Get node name
    if 'node' in flask.request.values:
        node = flask.request.values['node']
    else:
        node = None

    # Get target selector
    if 'selector' in flask.request.values:
        selector = flask.request.values['selector']
    else:
        selector = None

    return pvcapi.vm_define(vm, libvirt_xml, node, selector)

@api.route('/api/v1/vm/<vm>/modify', methods=['POST'])
def api_vm_modify(vm):
    """
    Modify an existing virtual machine named VM from Libvirt XML.
    """
    # Get XML from the POST body
    libvirt_xml = flask.request.data

    # Get node name
    if 'flag_restart' in flask.request.values:
        flag_restart = flask.request.values['flag_restart']
    else:
        flag_restart = None

    return pvcapi.vm_modify(vm, flag_restart, libvirt_xml)

@api.route('/api/v1/vm/<vm>/undefine', methods=['POST'])
def api_vm_undefine(vm):
    """
    Undefine a virtual machine named VM.
    """
    return pvcapi.vm_undefine(vm)

@api.route('/api/v1/vm/<vm>/remove', methods=['POST'])
def api_vm_remove(vm):
    """
    Remove a virtual machine named VM including all disks.
    """
    return pvcapi.vm_remove(vm)

@api.route('/api/v1/vm/<vm>/dump', methods=['GET'])
def api_vm_dump(vm):
    """
    Dump the Libvirt XML configuration of a virtual machine named VM.
    """
    return pvcapi.vm_dump(vm)

@api.route('/api/v1/vm/<vm>/start', methods=['POST'])
def api_vm_start(vm):
    """
    Start a virtual machine named VM.
    """
    return pvcapi.vm_start(vm)

@api.route('/api/v1/vm/<vm>/restart', methods=['POST'])
def api_vm_restart(vm):
    """
    Restart a virtual machine named VM.
    """
    return pvcapi.vm_restart(vm)

@api.route('/api/v1/vm/<vm>/shutdown', methods=['POST'])
def api_vm_shutdown(vm):
    """
    Shutdown a virtual machine named VM.
    """
    return pvcapi.vm_shutdown(vm)

@api.route('/api/v1/vm/<vm>/stop', methods=['POST'])
def api_vm_stop(vm):
    """
    Forcibly stop a virtual machine named VM.
    """
    return pvcapi.vm_stop(vm)

@api.route('/api/v1/vm/<vm>/move', methods=['POST'])
def api_vm_move(vm):
    """
    Move a virtual machine named VM to another node.
    """
    # Get node name
    if 'node' in flask.request.values:
        node = flask.request.values['node']
    else:
        node = None

    # Get target selector
    if 'selector' in flask.request.values:
        selector = flask.request.values['selector']
    else:
        selector = None

    return pvcapi.vm_move(vm, node, selector)

@api.route('/api/v1/vm/<vm>/migrate', methods=['POST'])
def api_vm_migrate(vm):
    """
    Temporarily migrate a virtual machine named VM to another node.
    """
    # Get node name
    if 'node' in flask.request.values:
        node = flask.request.values['node']
    else:
        node = None

    # Get target selector
    if 'selector' in flask.request.values:
        selector = flask.request.values['selector']
    else:
        selector = None

    # Get target selector
    if 'flag_force' in flask.request.values:
        flag_force = True
    else:
        flag_force = False

    return pvcapi.vm_migrate(vm, node, selector, flag_force)

@api.route('/api/v1/vm/<vm>/unmigrate', methods=['POST'])
def api_vm_unmigrate(vm):
    """
    Unmigrate a migrated virtual machine named VM.
    """
    return pvcapi.vm_move(vm)

#
# Network endpoints
#
@api.route('/api/v1/network', methods=['GET'])
def api_net():
    """
    Return a list of virtual client networks with limit LIMIT.
    """
    # Get name limit
    if 'limit' in flask.request.values:
        limit = flask.request.values['limit']
    else:
        limit = None

    return pvcapi.net_list(limit)

@api.route('/api/v1/network/<network>', methods=['GET'])
def api_net_info(network):
    """
    Get information about a virtual client network with description NETWORK.
    """
    # Same as specifying /network?limit=NETWORK
    return pvcapi.net_list(network)

@api.route('/api/v1/network/<network>/add', methods=['POST'])
def api_net_add(network):
    """
    Add a virtual client network with description NETWORK.
    """
    return pvcapi.net_add()

@api.route('/api/v1/network/<network>/modify', methods=['POST'])
def api_net_modify(network):
    """
    Modify a virtual client network with description NETWORK.
    """
    return pvcapi.net_modify()

@api.route('/api/v1/network/<network>/remove', methods=['POST'])
def api_net_remove(network):
    """
    Remove a virtual client network with description NETWORK.
    """
    return pvcapi.net_remove()

@api.route('/api/v1/network/<network>/dhcp', methods=['GET'])
def api_net_dhcp(network):
    """
    Return a list of DHCP leases in virtual client network with description NETWORK with limit LIMIT.
    """
    # Get name limit
    if 'limit' in flask.request.values:
        limit = flask.request.values['limit']
    else:
        limit = None

    # Get static-only flag
    if 'flag_static' in flask.request.values:
        flag_static = True
    else:
        flag_static = False

    return pvcapi.net_dhcp_list(network, limit. flag_static)

@api.route('/api/v1/network/<network>/dhcp/<lease>', methods=['GET'])
def api_net_dhcp_info(network, lease):
    """
    Get information about a DHCP lease for MAC address LEASE in virtual client network with description NETWORK.
    """
    # Same as specifying /network?limit=NETWORK
    return pvcapi.net_dhcp_list(network, lease, False)

@api.route('/api/v1/network/<network>/dhcp/<lease>/add', methods=['POST'])
def api_net_dhcp_add(network, lease):
    """
    Add a static DHCP lease for MAC address LEASE to virtual client network with description NETWORK.
    """
    return pvcapi.net_dhcp_add()

@api.route('/api/v1/network/<network>/dhcp/<lease>/remove', methods=['POST'])
def api_net_dhcp_remove(network, lease):
    """
    Remove a static DHCP lease for MAC address LEASE from virtual client network with description NETWORK.
    """
    return pvcapi.net_dhcp_remove()

@api.route('/api/v1/network/<network>/acl', methods=['GET'])
def api_net_acl(network):
    """
    Return a list of network ACLs in network NETWORK with limit LIMIT.
    """
    # Get name limit
    if 'limit' in flask.request.values:
        limit = flask.request.values['limit']
    else:
        limit = None

    # Get direction limit
    if 'direction' in flask.request.values:
        direction = flask.request.values['direction']
        if not 'in' in direction or not 'out' in direction:
            return "Error: Direction must be either 'in' or 'out'; for both, do not specify a direction.\n", 510
    else:
        direction = None

    return pvcapi.net_acl_list(network, limit, direction)

@api.route('/api/v1/network/<network>/acl/<acl>', methods=['GET'])
def api_net_acl_info(network, acl):
    """
    Get information about a network access control entry with description ACL in virtual client network with description NETWORK.
    """
    # Same as specifying /network?limit=NETWORK
    return pvcapi.net_acl_list(network, acl, None)

@api.route('/api/v1/network/<network>/acl/<acl>/add', methods=['POST'])
def api_net_acl_add(network, acl):
    """
    Add an access control list with description ACL to virtual client network with description NETWORK.
    """
    return pvcapi.net_acl_add()

@api.route('/api/v1/network/<network>/acl/<acl>/remove', methods=['POST'])
def api_net_acl_remove(network, acl):
    """
    Remove an access control list with description ACL from virtual client network with description NETWORK.
    """
    return pvcapi.net_acl_remove()

#
# Ceph endpoints
#
@api.route('/api/v1/ceph', methods=['GET'])
def api_ceph():
    """
    Get the current Ceph cluster status.
    """
    return pvcapi.ceph_status()

@api.route('/api/v1/ceph/osd', methods=['GET'])
def api_ceph_osd():
    """
    Get the list of OSDs in the Ceph storage cluster.
    """
    # Get name limit
    if 'limit' in flask.request.values:
        limit = flask.request.values['limit']
    else:
        limit = None

    return pvcapi.ceph_osd_list(limit)

@api.route('/api/v1/ceph/osd/set', methods=['POST'])
def api_ceph_osd_set():
    """
    Set options on a Ceph OSD in the PVC Ceph storage cluster.
    """
    return pvcapi.ceph_osd_set()

@api.route('/api/v1/ceph/osd/unset', methods=['POST'])
def api_ceph_osd_unset():
    """
    Unset options on a Ceph OSD in the PVC Ceph storage cluster.
    """
    return pvcapi.ceph_osd_unset()

@api.route('/api/v1/ceph/osd/<osd>', methods=['GET'])
def api_ceph_osd_info(osd):
    """
    Get information about an OSD with ID OSD.
    """
    # Same as specifying /osd?limit=OSD
    return pvcapi.ceph_osd_list(osd)

@api.route('/api/v1/ceph/osd/<osd>/add', methods=['POST'])
def api_ceph_osd_add(osd):
    """
    Add a Ceph OSD with ID OSD.
    """
    return pvcapi.ceph_osd_add()

@api.route('/api/v1/ceph/osd/<osd>/remove', methods=['POST'])
def api_ceph_osd_remove(osd):
    """
    Remove a Ceph OSD with ID OSD.
    """
    return pvcapi.ceph_osd_remove()

@api.route('/api/v1/ceph/osd/<osd>/in', methods=['POST'])
def api_ceph_osd_in(osd):
    """
    Set in a Ceph OSD with ID OSD.
    """
    return pvcapi.ceph_osd_in()

@api.route('/api/v1/ceph/osd/<osd>/out', methods=['POST'])
def api_ceph_osd_out(osd):
    """
    Set out a Ceph OSD with ID OSD.
    """
    return pvcapi.ceph_osd_out()

@api.route('/api/v1/ceph/pool', methods=['GET'])
def api_ceph_pool():
    """
    Get the list of RBD pools in the Ceph storage cluster.
    """
    # Get name limit
    if 'limit' in flask.request.values:
        limit = flask.request.values['limit']
    else:
        limit = None

    return pvcapi.ceph_pool_list(limit)

@api.route('/api/v1/ceph/pool/<pool>', methods=['GET'])
def api_ceph_pool_info(pool):
    """
    Get information about an RBD pool with name POOL.
    """
    # Same as specifying /pool?limit=POOL
    return pvcapi.ceph_pool_list(pool)

@api.route('/api/v1/ceph/pool/<pool>/add', methods=['POST'])
def api_ceph_pool_add(pool):
    """
    Add a Ceph RBD pool with name POOL.
    """
    return pvcapi.ceph_pool_add()

@api.route('/api/v1/ceph/pool/<pool>/remove', methods=['POST'])
def api_ceph_pool_remove(pool):
    """
    Remove a Ceph RBD pool with name POOL.
    """
    return pvcapi.ceph_pool_remove()

@api.route('/api/v1/ceph/volume', methods=['GET'])
def api_ceph_volume():
    """
    Get the list of RBD volumes in the Ceph storage cluster.
    """
    # Get pool limit
    if 'pool' in flask.request.values:
        pool = flask.request.values['pool']
    else:
        pool = None

    # Get name limit
    if 'limit' in flask.request.values:
        limit = flask.request.values['limit']
    else:
        limit = None

    return pvcapi.ceph_volume_list(pool, limit)

@api.route('/api/v1/ceph/volume/<pool>/<volume>', methods=['GET'])
def api_ceph_volume_info(pool, volume):
    """
    Get information about an RBD volume with name VOLUME in RBD pool with name POOL.
    """
    # Same as specifying /volume?limit=VOLUME
    return pvcapi.ceph_osd_list(pool, osd)

@api.route('/api/v1/ceph/volume/<pool>/<volume>/add', methods=['POST'])
def api_ceph_volume_add(pool, volume):
    """
    Add a Ceph RBD volume with name VOLUME to RBD pool with name POOL.
    """
    return pvcapi.ceph_volume_add()

@api.route('/api/v1/ceph/volume/<pool>/<volume>/remove', methods=['POST'])
def api_ceph_volume_remove(pool, volume):
    """
    Remove a Ceph RBD volume with name VOLUME from RBD pool with name POOL.
    """
    return pvcapi.ceph_volume_remove()

@api.route('/api/v1/ceph/volume/snapshot', methods=['GET'])
def api_ceph_volume_snapshot():
    """
    Get the list of RBD volume snapshots in the Ceph storage cluster.
    """
    # Get pool limit
    if 'pool' in flask.request.values:
        pool = flask.request.values['pool']
    else:
        pool = None

    # Get volume limit
    if 'volume' in flask.request.values:
        volume = flask.request.values['volume']
    else:
        volume = None

    # Get name limit
    if 'limit' in flask.request.values:
        limit = flask.request.values['limit']
    else:
        limit = None

    return pvcapi.ceph_volume_snapshot_list(pool, volume, limit)

@api.route('/api/v1/ceph/volume/snapshot/<pool>/<volume>/<snapshot>', methods=['GET'])
def api_ceph_volume_snapshot_info(pool, volume, snapshot):
    """
    Get information about a snapshot with name SNAPSHOT of RBD volume with name VOLUME in RBD pool with name POOL.
    """
    # Same as specifying /snapshot?limit=VOLUME
    return pvcapi.ceph_snapshot_list(pool, volume, snapshot)

@api.route('/api/v1/ceph/volume/snapshot/<pool>/<volume>/<snapshot>/add', methods=['POST'])
def api_ceph_volume_snapshot_add(pool, volume, snapshot):
    """
    Add a Ceph RBD volume snapshot with name SNAPSHOT of RBD volume with name VOLUME in RBD pool with name POOL.
    """
    return pvcapi.ceph_volume_snapshot_add()

@api.route('/api/v1/ceph/volume/snapshot/<pool>/<volume>/<snapshot>/remove', methods=['POST'])
def api_ceph_volume_snapshot_remove(pool, volume, snapshot):
    """
    Remove a Ceph RBD volume snapshot with name SNAPSHOT from RBD volume with name VOLUME in RBD pool with name POOL.
    """
    return pvcapi.ceph_volume_snapshot_remove()

#
# Entrypoint
#
api.run()
