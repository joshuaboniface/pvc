#!/usr/bin/env python3

# pvc.py - PVC client command-line interface
# Part of the Parallel Virtual Cluster (PVC) system
#
#    Copyright (C) 2018-2019 Joshua M. Boniface <joshua@boniface.me>
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

import socket
import click
import tempfile
import os
import subprocess
import difflib
import re
import colorama
import yaml
import lxml.etree as etree
import requests

import cli_lib.ansiprint as ansiprint
import cli_lib.cluster as pvc_cluster
import cli_lib.node as pvc_node
import cli_lib.vm as pvc_vm
import cli_lib.network as pvc_network
import cli_lib.ceph as pvc_ceph

myhostname = socket.gethostname().split('.')[0]
zk_host = ''

config = dict()
config['debug'] = False
config['api_scheme'] = 'http'
config['api_host'] = 'localhost:7370'
config['api_prefix'] = '/api/v1'

CONTEXT_SETTINGS = dict(help_option_names=['-h', '--help'], max_content_width=120)

def cleanup(retcode, retmsg):
    if retcode == True:
        if retmsg != '':
            click.echo(retmsg)
        exit(0)
    else:
        if retmsg != '':
            click.echo(retmsg)
        exit(1)

###############################################################################
# pvc node
###############################################################################
@click.group(name='node', short_help='Manage a PVC node.', context_settings=CONTEXT_SETTINGS)
def cli_node():
    """
    Manage the state of a node in the PVC cluster.
    """
    pass

###############################################################################
# pvc node secondary
###############################################################################
@click.command(name='secondary', short_help='Set a node in secondary node status.')
@click.argument(
    'node'
)
def node_secondary(node):
    """
    Take NODE out of primary router mode.
    """
    
    retcode, retmsg = pvc_node.node_coordinator_state(config, node, 'secondary')
    cleanup(retcode, retmsg)

###############################################################################
# pvc node primary
###############################################################################
@click.command(name='primary', short_help='Set a node in primary status.')
@click.argument(
    'node'
)
def node_primary(node):
    """
    Put NODE into primary router mode.
    """

    retcode, retmsg = pvc_node.node_coordinator_state(config, node, 'primary')
    cleanup(retcode, retmsg)

###############################################################################
# pvc node flush
###############################################################################
@click.command(name='flush', short_help='Take a node out of service.')
@click.option(
    '-w', '--wait', 'wait', is_flag=True, default=False,
    help='Wait for migrations to complete before returning.'
)
@click.argument(
    'node', default=myhostname
)
def node_flush(node, wait):
    """
    Take NODE out of active service and migrate away all VMs. If unspecified, defaults to this host.
    """
    
    retcode, retmsg = pvc_node.node_domain_state(config, node, 'flush', wait)
    cleanup(retcode, retmsg)

###############################################################################
# pvc node ready/unflush
###############################################################################
@click.command(name='ready', short_help='Restore node to service.')
@click.argument(
    'node', default=myhostname
)
@click.option(
    '-w', '--wait', 'wait', is_flag=True, default=False,
    help='Wait for migrations to complete before returning.'
)
def node_ready(node, wait):
    """
    Restore NODE to active service and migrate back all VMs. If unspecified, defaults to this host.
    """

    retcode, retmsg = pvc_node.node_domain_state(config, node, 'ready', wait)
    cleanup(retcode, retmsg)

@click.command(name='unflush', short_help='Restore node to service.')
@click.argument(
    'node', default=myhostname
)
@click.option(
    '-w', '--wait', 'wait', is_flag=True, default=False,
    help='Wait for migrations to complete before returning.'
)
def node_unflush(node, wait):
    """
    Restore NODE to active service and migrate back all VMs. If unspecified, defaults to this host.
    """

    retcode, retmsg = pvc_node.node_domain_state(config, node, 'ready', wait)
    cleanup(retcode, retmsg)

###############################################################################
# pvc node info
###############################################################################
@click.command(name='info', short_help='Show details of a node object.')
@click.argument(
    'node', default=myhostname
)
@click.option(
    '-l', '--long', 'long_output', is_flag=True, default=False,
    help='Display more detailed information.'
)
def node_info(node, long_output):
    """
    Show information about node NODE. If unspecified, defaults to this host.
    """

    retcode, retdata = pvc_node.node_info(config, node)
    if retcode:
        pvc_node.format_info(retdata, long_output)
        retdata = ''
    cleanup(retcode, retdata)

###############################################################################
# pvc node list
###############################################################################
@click.command(name='list', short_help='List all node objects.')
@click.argument(
    'limit', default=None, required=False
)
def node_list(limit):
    """
    List all nodes in the cluster; optionally only match names matching regex LIMIT.
    """

    retcode, retdata = pvc_node.node_list(config, limit)
    if retcode:
        pvc_node.format_list(retdata)
        retdata = ''
    cleanup(retcode, retdata)

###############################################################################
# pvc vm
###############################################################################
@click.group(name='vm', short_help='Manage a PVC virtual machine.', context_settings=CONTEXT_SETTINGS)
def cli_vm():
    """
    Manage the state of a virtual machine in the PVC cluster.
    """
    pass

###############################################################################
# pvc vm define
###############################################################################
@click.command(name='define', short_help='Define a new virtual machine from a Libvirt XML file.')
@click.option(
    '-t', '--target', 'target_node',
    help='Home node for this domain; autoselect if unspecified.'
)
@click.option(
    '-l', '--limit', 'node_limit', default=None, show_default=False,
    help='Comma-separated list of nodes to limit VM operation to; saved with VM.'
)
@click.option(
    '-s', '--selector', 'node_selector', default='mem', show_default=True,
    type=click.Choice(['mem','load','vcpus','vms']),
    help='Method to determine optimal target node during autoselect; saved with VM.'
)
@click.option(
    '-a/-A', '--autostart/--no-autostart', 'node_autostart', is_flag=True, default=False,
    help='Start VM automatically on next unflush/ready state of home node; unset by daemon once used.'
)
@click.argument(
    'config', type=click.File()
)
def vm_define(config, target_node, node_limit, node_selector, node_autostart):
    """
    Define a new virtual machine from Libvirt XML configuration file CONFIG.
    """

    # Open the XML file
    config_data = config.read()
    config.close()

    retcode, retmsg = pvc_vm.define_vm(zk_conn, config_data, target_node, node_limit, node_selector, node_autostart)
    cleanup(retcode, retmsg)

###############################################################################
# pvc vm meta
###############################################################################
@click.command(name='meta', short_help='Modify PVC metadata of an existing VM.')
@click.option(
    '-l', '--limit', 'node_limit', default=None, show_default=False,
    help='Comma-separated list of nodes to limit VM operation to; set to an empty string to remove.'
)
@click.option(
    '-s', '--selector', 'node_selector', default=None, show_default=False,
    type=click.Choice(['mem','load','vcpus','vms']),
    help='Method to determine optimal target node during autoselect.'
)
@click.option(
    '-a/-A', '--autostart/--no-autostart', 'node_autostart', is_flag=True, default=None,
    help='Start VM automatically on next unflush/ready state of home node; unset by daemon once used.'
)
@click.argument(
    'domain'
)
def vm_meta(domain, node_limit, node_selector, node_autostart):
    """
    Modify the PVC metadata of existing virtual machine DOMAIN. At least one option to update must be specified. DOMAIN may be a UUID or name.
    """

    if node_limit is None and node_selector is None and node_autostart is None:
        cleanup(False, 'At least one metadata option must be specified to update.')

    retcode, retmsg = pvc_vm.vm_metadata(config, domain, node_limit, node_selector, node_autostart)
    cleanup(retcode, retmsg)

###############################################################################
# pvc vm modify
###############################################################################
@click.command(name='modify', short_help='Modify an existing VM configuration.')
@click.option(
    '-e', '--editor', 'editor', is_flag=True,
    help='Use local editor to modify existing config.'
)
@click.option(
    '-r', '--restart', 'restart', is_flag=True,
    help='Immediately restart VM to apply new config.'
)
@click.argument(
    'domain'
)
@click.argument(
    'cfgfile', type=click.File(), default=None, required=False
)
def vm_modify(domain, cfgfile, editor, restart):
    """
    Modify existing virtual machine DOMAIN, either in-editor or with replacement CONFIG. DOMAIN may be a UUID or name.
    """

    if editor == False and cfgfile == None:
        cleanup(False, 'Either an XML config file or the "--editor" option must be specified.')

    retcode, vm_information = pvc_vm.vm_info(config, domain)
    if not retcode and not vm_information.get('name', None):
        cleanup(False, 'ERROR: Could not find VM "{}" in the cluster!'.format(domain))

    dom_uuid = vm_information.get('uuid')
    dom_name = vm_information.get('name')

    if editor == True:
        # Grab the current config
        current_vm_cfg_raw = vm_information.get('xml')
        xml_data = etree.fromstring(current_vm_cfg_raw)
        current_vm_cfgfile = etree.tostring(xml_data, pretty_print=True).decode('utf8')

        # Write it to a tempfile
        fd, path = tempfile.mkstemp()
        fw = os.fdopen(fd, 'w')
        fw.write(current_vm_cfgfile.strip())
        fw.close()

        # Edit it
        editor = os.getenv('EDITOR', 'vi')
        subprocess.call('%s %s' % (editor, path), shell=True)

        # Open the tempfile to read
        with open(path, 'r') as fr:
            new_vm_cfgfile = fr.read()
            fr.close()

        # Delete the tempfile
        os.unlink(path)

        # Show a diff and confirm
        diff = list(difflib.unified_diff(current_vm_cfgfile.split('\n'), new_vm_cfgfile.split('\n'), fromfile='current', tofile='modified', fromfiledate='', tofiledate='', n=3, lineterm=''))
        if len(diff) < 1:
            click.echo('Aborting with no modifications.')
            exit(0)

        click.echo('Pending modifications:')
        click.echo('')
        for line in diff:
            if re.match('^\+', line) != None:
                click.echo(colorama.Fore.GREEN + line + colorama.Fore.RESET)
            elif re.match('^\-', line) != None:
                click.echo(colorama.Fore.RED + line + colorama.Fore.RESET)
            elif re.match('^\^', line) != None:
                click.echo(colorama.Fore.BLUE + line + colorama.Fore.RESET)
            else:
                click.echo(line)
        click.echo('')

        click.confirm('Write modifications to Zookeeper?', abort=True)

        if restart:
            click.echo('Writing modified configuration of VM "{}" and restarting.'.format(dom_name))
        else:
            click.echo('Writing modified configuration of VM "{}".'.format(dom_name))

    # We're operating in replace mode
    else:
        # Open the XML file
        new_vm_cfgfile = cfgfile.read()
        cfgfile.close()

        if restart:
            click.echo('Replacing configuration of VM "{}" with file "{}" and restarting.'.format(dom_name, cfgfile.name))
        else:
            click.echo('Replacing configuration of VM "{}" with file "{}".'.format(dom_name, cfgfile.name))

    retcode, retmsg = pvc_vm.vm_modify(config, domain, new_vm_config, restart)
    cleanup(retcode, retmsg)

###############################################################################
# pvc vm undefine
###############################################################################
@click.command(name='undefine', short_help='Undefine a virtual machine.')
@click.argument(
    'domain'
)
def vm_undefine(domain):
    """
    Stop virtual machine DOMAIN and remove it from the cluster database, preserving disks. DOMAIN may be a UUID or name.
    """

    retcode, retmsg = pvc_vm.vm_remove(config, domain, delete_disks=False)
    cleanup(retcode, retmsg)

###############################################################################
# pvc vm remove
###############################################################################
@click.command(name='remove', short_help='Remove a virtual machine.')
@click.argument(
    'domain'
)
def vm_remove(domain):
    """
    Stop virtual machine DOMAIN and remove it, along with all disks, from the cluster. DOMAIN may be a UUID or name.
    """

    retcode, retmsg = pvc_vm.vm_remove(config, domain, delete_disks=True)
    cleanup(retcode, retmsg)

###############################################################################
# pvc vm start
###############################################################################
@click.command(name='start', short_help='Start up a defined virtual machine.')
@click.argument(
    'domain'
)
def vm_start(domain):
    """
    Start virtual machine DOMAIN on its configured node. DOMAIN may be a UUID or name.
    """

    retcode, retmsg = pvc_vm.vm_state(config, domain, 'start')
    cleanup(retcode, retmsg)

###############################################################################
# pvc vm restart
###############################################################################
@click.command(name='restart', short_help='Restart a running virtual machine.')
@click.argument(
    'domain'
)
def vm_restart(domain):
    """
    Restart running virtual machine DOMAIN. DOMAIN may be a UUID or name.
    """

    retcode, retmsg = pvc_vm.vm_state(config, domain, 'restart')
    cleanup(retcode, retmsg)

###############################################################################
# pvc vm shutdown
###############################################################################
@click.command(name='shutdown', short_help='Gracefully shut down a running virtual machine.')
@click.argument(
	'domain'
)
def vm_shutdown(domain):
    """
    Gracefully shut down virtual machine DOMAIN. DOMAIN may be a UUID or name.
    """

    retcode, retmsg = pvc_vm.vm_state(config, domain, 'shutdown')
    cleanup(retcode, retmsg)

###############################################################################
# pvc vm stop
###############################################################################
@click.command(name='stop', short_help='Forcibly halt a running virtual machine.')
@click.argument(
    'domain'
)
def vm_stop(domain):
    """
    Forcibly halt (destroy) running virtual machine DOMAIN. DOMAIN may be a UUID or name.
    """

    retcode, retmsg = pvc_vm.vm_state(config, domain, 'stop')
    cleanup(retcode, retmsg)

###############################################################################
# pvc vm disable
###############################################################################
@click.command(name='disable', short_help='Mark a virtual machine as disabled.')
@click.argument(
    'domain'
)
def vm_disable(domain):
    """
    Prevent stopped virtual machine DOMAIN from being counted towards cluster health status. DOMAIN may be a UUID or name.

    Use this option for VM that are stopped intentionally or long-term and which should not impact cluster health if stopped. A VM can be started directly from disable state.
    """

    retcode, retmsg = pvc_vm.vm_state(config, domain, 'disable')
    cleanup(retcode, retmsg)

###############################################################################
# pvc vm move
###############################################################################
@click.command(name='move', short_help='Permanently move a virtual machine to another node.')
@click.argument(
	'domain'
)
@click.option(
    '-t', '--target', 'target_node', default=None,
    help='Target node to migrate to; autodetect if unspecified.'
)
def vm_move(domain, target_node):
    """
    Permanently move virtual machine DOMAIN, via live migration if running and possible, to another node. DOMAIN may be a UUID or name.
    """

    retcode, retmsg = pvc_vm.vm_node(config, domain, target_node, 'move', force=False)
    cleanup(retcode, retmsg)

###############################################################################
# pvc vm migrate
###############################################################################
@click.command(name='migrate', short_help='Temporarily migrate a virtual machine to another node.')
@click.argument(
    'domain'
)
@click.option(
    '-t', '--target', 'target_node', default=None,
    help='Target node to migrate to; autodetect if unspecified.'
)
@click.option(
    '-f', '--force', 'force_migrate', is_flag=True, default=False,
    help='Force migrate an already migrated VM; does not replace an existing previous node value.'
)
def vm_migrate(domain, target_node, force_migrate):
    """
    Temporarily migrate running virtual machine DOMAIN, via live migration if possible, to another node. DOMAIN may be a UUID or name. If DOMAIN is not running, it will be started on the target node.
    """

    retcode, retmsg = pvc_vm.vm_node(config, domain, target_node, 'migrate', force=force_migrate)
    cleanup(retcode, retmsg)

###############################################################################
# pvc vm unmigrate
###############################################################################
@click.command(name='unmigrate', short_help='Restore a migrated virtual machine to its original node.')
@click.argument(
    'domain'
)
def vm_unmigrate(domain):
    """
    Restore previously migrated virtual machine DOMAIN, via live migration if possible, to its original node. DOMAIN may be a UUID or name. If DOMAIN is not running, it will be started on the target node.
    """

    retcode, retmsg = pvc_vm.vm_node(config, domain, None, 'unmigrate', force=False)
    cleanup(retcode, retmsg)

###############################################################################
# pvc vm flush-locks
###############################################################################
@click.command(name='flush-locks', short_help='Flush stale RBD locks for a virtual machine.')
@click.argument(
    'domain'
)
def vm_flush_locks(domain):
    """
    Flush stale RBD locks for virtual machine DOMAIN. DOMAIN may be a UUID or name. DOMAIN must be in a stopped state before flushing locks.
    """

    retcode, retmsg = pvc_vm.vm_locks(config, domain)
    cleanup(retcode, retmsg)

###############################################################################
# pvc vm log
###############################################################################
@click.command(name='log', short_help='Show console logs of a VM object.')
@click.argument(
    'domain'
)
@click.option(
    '-l', '--lines', 'lines', default=100, show_default=True,
    help='Display this many log lines from the end of the log buffer.'
)
@click.option(
    '-f', '--follow', 'follow', is_flag=True, default=False,
    help='Follow the log buffer; output may be delayed by a few seconds relative to the live system. The --lines value defaults to 10 for the initial output.'
)
def vm_log(domain, lines, follow):
    """
	Show console logs of virtual machine DOMAIN on its current node in the 'less' pager or continuously. DOMAIN may be a UUID or name. Note that migrating a VM to a different node will cause the log buffer to be overwritten by entries from the new node.
    """

    if follow:
        retcode, retmsg = pvc_vm.follow_console_log(config, domain, lines)
    else:
        retcode, retmsg = pvc_vm.view_console_log(config, domain, lines)
    cleanup(retcode, retmsg)

###############################################################################
# pvc vm info
###############################################################################
@click.command(name='info', short_help='Show details of a VM object.')
@click.argument(
    'domain'
)
@click.option(
    '-l', '--long', 'long_output', is_flag=True, default=False,
    help='Display more detailed information.'
)
def vm_info(domain, long_output):
    """
	Show information about virtual machine DOMAIN. DOMAIN may be a UUID or name.
    """

    retcode, retdata = pvc_vm.vm_info(config, domain)
    if retcode:
        pvc_vm.format_info(config, retdata, long_output)
        retdata = ''
    cleanup(retcode, retdata)

###############################################################################
# pvc vm dump
###############################################################################
@click.command(name='dump', short_help='Dump a virtual machine XML to stdout.')
@click.argument(
    'domain'
)
def vm_dump(domain):
    """
    Dump the Libvirt XML definition of virtual machine DOMAIN to stdout. DOMAIN may be a UUID or name.
    """

    retcode, vm_information = pvc_vm.vm_info(config, domain)
    if not retcode and not vm_information.get('name', None):
        cleanup(False, 'ERROR: Could not find VM "{}" in the cluster!'.format(domain))

    # Grab the current config
    current_vm_cfg_raw = vm_information.get('xml')
    xml_data = etree.fromstring(current_vm_cfg_raw)
    current_vm_cfgfile = etree.tostring(xml_data, pretty_print=True).decode('utf8')
    click.echo(current_vm_cfgfile.strip())

###############################################################################
# pvc vm list
###############################################################################
@click.command(name='list', short_help='List all VM objects.')
@click.argument(
    'limit', default=None, required=False
)
@click.option(
    '-t', '--target', 'target_node', default=None,
    help='Limit list to VMs on the specified node.'
)
@click.option(
    '-s', '--state', 'target_state', default=None,
    help='Limit list to VMs in the specified state.'
)
@click.option(
    '-r', '--raw', 'raw', is_flag=True, default=False,
    help='Display the raw list of VM names only.'
)
def vm_list(target_node, target_state, limit, raw):
    """
    List all virtual machines in the cluster; optionally only match names matching regex LIMIT.

    NOTE: Red-coloured network lists indicate one or more configured networks are missing/invalid.
    """

    retcode, retdata = pvc_vm.vm_list(config, limit, target_node, target_state)
    if retcode:
        pvc_vm.format_list(config, retdata, raw)
        retdata = ''
    cleanup(retcode, retdata)

###############################################################################
# pvc network
###############################################################################
@click.group(name='network', short_help='Manage a PVC virtual network.', context_settings=CONTEXT_SETTINGS)
def cli_network():
    """
    Manage the state of a VXLAN network in the PVC cluster.
    """
    pass

###############################################################################
# pvc network add
###############################################################################
@click.command(name='add', short_help='Add a new virtual network to the cluster.')
@click.option(
    '-d', '--description', 'description',
    required=True,
    help='Description of the network; must be unique and not contain whitespace.'
)
@click.option(
    '-p', '--type', 'nettype',
    required=True,
    type=click.Choice(['managed', 'bridged']),
    help='Network type; managed networks control IP addressing; bridged networks are simple vLAN bridges. All subsequent options are unused for bridged networks.'
)
@click.option(
    '-n', '--domain', 'domain',
    default=None,
    help='Domain name of the network.'
)
@click.option(
    '--dns-server', 'name_servers',
    multiple=True,
    help='DNS nameserver for network; multiple entries may be specified.'
)
@click.option(
    '-i', '--ipnet', 'ip_network',
    default=None,
    help='CIDR-format IPv4 network address for subnet.'
)
@click.option(
    '-i6', '--ipnet6', 'ip6_network',
    default=None,
    help='CIDR-format IPv6 network address for subnet; should be /64 or larger ending "::/YY".'
)
@click.option(
    '-g', '--gateway', 'ip_gateway',
    default=None,
    help='Default IPv4 gateway address for subnet.'
)
@click.option(
    '-g6', '--gateway6', 'ip6_gateway',
    default=None,
    help='Default IPv6 gateway address for subnet.  [default: "X::1"]'
)
@click.option(
    '--dhcp/--no-dhcp', 'dhcp_flag',
    is_flag=True,
    default=False,
    help='Enable/disable IPv4 DHCP for clients on subnet.'
)
@click.option(
    '--dhcp-start', 'dhcp_start',
    default=None,
    help='IPv4 DHCP range start address.'
)
@click.option(
    '--dhcp-end', 'dhcp_end',
    default=None,
    help='IPv4 DHCP range end address.'
)
@click.argument(
    'vni'
)
def net_add(vni, description, nettype, domain, ip_network, ip_gateway, ip6_network, ip6_gateway, dhcp_flag, dhcp_start, dhcp_end, name_servers):
    """
    Add a new virtual network with VXLAN identifier VNI to the cluster.

    Examples:

    pvc network add 101 --type bridged

      > Creates vLAN 101 and a simple bridge on the VNI dev interface.
    
    pvc network add 1001 --type managed --domain test.local --ipnet 10.1.1.0/24 --gateway 10.1.1.1

      > Creates a VXLAN with ID 1001 on the VNI dev interface, with IPv4 managed networking.

    IPv6 is fully supported with --ipnet6 and --gateway6 in addition to or instead of IPv4. PVC will configure DHCPv6 in a semi-managed configuration for the network if set.
    """

    if nettype == 'managed' and not ip_network and not ip6_network:
        click.echo('Error: At least one of "-i" / "--ipnet" or "-i6" / "--ipnet6" must be specified.')
        exit(1)

    zk_conn = pvc_common.startZKConnection(zk_host)
    retcode, retmsg = pvc_network.add_network(zk_conn, vni, description, nettype, domain, name_servers, ip_network, ip_gateway, ip6_network, ip6_gateway, dhcp_flag, dhcp_start, dhcp_end)
    cleanup(retcode, retmsg, zk_conn)

###############################################################################
# pvc network modify
###############################################################################
@click.command(name='modify', short_help='Modify an existing virtual network.')
@click.option(
    '-d', '--description', 'description',
    default=None,
    help='Description of the network; must be unique and not contain whitespace.'
)
@click.option(
    '-n', '--domain', 'domain',
    default=None,
    help='Domain name of the network.'
)
@click.option(
    '--dns-server', 'name_servers',
    multiple=True,
    help='DNS nameserver for network; multiple entries may be specified (will overwrite all previous entries).'
)
@click.option(
    '-i', '--ipnet', 'ip4_network',
    default=None,
    help='CIDR-format IPv4 network address for subnet.'
)
@click.option(
    '-i6', '--ipnet6', 'ip6_network',
    default=None,
    help='CIDR-format IPv6 network address for subnet.'
)
@click.option(
    '-g', '--gateway', 'ip4_gateway',
    default=None,
    help='Default IPv4 gateway address for subnet.'
)
@click.option(
    '-g6', '--gateway6', 'ip6_gateway',
    default=None,
    help='Default IPv6 gateway address for subnet.'
)
@click.option(
    '--dhcp/--no-dhcp', 'dhcp_flag',
    is_flag=True,
    default=None,
    help='Enable/disable DHCP for clients on subnet.'
)
@click.option(
    '--dhcp-start', 'dhcp_start',
    default=None,
    help='DHCP range start address.'
)
@click.option(
    '--dhcp-end', 'dhcp_end',
    default=None,
    help='DHCP range end address.'
)
@click.argument(
    'vni'
)
def net_modify(vni, description, domain, name_servers, ip6_network, ip6_gateway, ip4_network, ip4_gateway, dhcp_flag, dhcp_start, dhcp_end):
    """
    Modify details of virtual network VNI. All fields optional; only specified fields will be updated.

    Example:
    pvc network modify 1001 --gateway 10.1.1.1 --dhcp
    """

    zk_conn = pvc_common.startZKConnection(zk_host)
    retcode, retmsg = pvc_network.modify_network(zk_conn, vni, description=description, domain=domain, name_servers=name_servers, ip6_network=ip6_network, ip6_gateway=ip6_gateway, ip4_network=ip4_network, ip4_gateway=ip4_gateway, dhcp_flag=dhcp_flag, dhcp_start=dhcp_start, dhcp_end=dhcp_end)
    cleanup(retcode, retmsg, zk_conn)

###############################################################################
# pvc network remove
###############################################################################
@click.command(name='remove', short_help='Remove a virtual network from the cluster.')
@click.argument(
    'net'
)
def net_remove(net):
    """
    Remove an existing virtual network NET from the cluster; NET can be either a VNI or description.

    WARNING: PVC does not verify whether clients are still present in this network. Before removing, ensure
    that all client VMs have been removed from the network or undefined behaviour may occur.
    """

    zk_conn = pvc_common.startZKConnection(zk_host)
    retcode, retmsg = pvc_network.remove_network(zk_conn, net)
    cleanup(retcode, retmsg, zk_conn)

###############################################################################
# pvc network info
###############################################################################
@click.command(name='info', short_help='Show details of a network.')
@click.argument(
    'vni'
)
@click.option(
    '-l', '--long', 'long_output', is_flag=True, default=False,
    help='Display more detailed information.'
)
def net_info(vni, long_output):
    """
	Show information about virtual network VNI.
    """

	# Open a Zookeeper connection
    zk_conn = pvc_common.startZKConnection(zk_host)
    retcode, retdata = pvc_network.get_info(zk_conn, vni)
    if retcode:
        pvc_network.format_info(retdata, long_output)
        retdata = ''
    cleanup(retcode, retdata, zk_conn)


###############################################################################
# pvc network list
###############################################################################
@click.command(name='list', short_help='List all VM objects.')
@click.argument(
    'limit', default=None, required=False
)
def net_list(limit):
    """
    List all virtual networks in the cluster; optionally only match VNIs or Descriptions matching regex LIMIT.
    """

    zk_conn = pvc_common.startZKConnection(zk_host)
    retcode, retdata = pvc_network.get_list(zk_conn, limit)
    if retcode:
        pvc_network.format_list(retdata)
        retdata = ''
    cleanup(retcode, retdata, zk_conn)

###############################################################################
# pvc network dhcp
###############################################################################
@click.group(name='dhcp', short_help='Manage IPv4 DHCP leases in a PVC virtual network.', context_settings=CONTEXT_SETTINGS)
def net_dhcp():
    """
    Manage host IPv4 DHCP leases of a VXLAN network in the PVC cluster.
    """
    pass

###############################################################################
# pvc network dhcp list
###############################################################################
@click.command(name='list', short_help='List active DHCP leases.')
@click.argument(
    'net'
)
@click.argument(
    'limit', default=None, required=False
)
def net_dhcp_list(net, limit):
    """
    List all DHCP leases in virtual network NET; optionally only match elements matching regex LIMIT; NET can be either a VNI or description.
    """

    zk_conn = pvc_common.startZKConnection(zk_host)
    retcode, retdata = pvc_network.get_list_dhcp(zk_conn, net, limit, only_static=False)
    if retcode:
        pvc_network.format_list_dhcp(retdata)
        retdata = ''
    cleanup(retcode, retdata, zk_conn)

###############################################################################
# pvc network dhcp static
###############################################################################
@click.group(name='static', short_help='Manage DHCP static reservations in a PVC virtual network.', context_settings=CONTEXT_SETTINGS)
def net_dhcp_static():
    """
    Manage host DHCP static reservations of a VXLAN network in the PVC cluster.
    """
    pass

###############################################################################
# pvc network dhcp static add
###############################################################################
@click.command(name='add', short_help='Add a DHCP static reservation.')
@click.argument(
    'net'
)
@click.argument(
    'ipaddr'
)
@click.argument(
    'hostname'
)
@click.argument(
    'macaddr'
)
def net_dhcp_static_add(net, ipaddr, macaddr, hostname):
    """
    Add a new DHCP static reservation of IP address IPADDR with hostname HOSTNAME for MAC address MACADDR to virtual network NET; NET can be either a VNI or description.
    """

    zk_conn = pvc_common.startZKConnection(zk_host)
    retcode, retmsg = pvc_network.add_dhcp_reservation(zk_conn, net, ipaddr, macaddr, hostname)
    cleanup(retcode, retmsg, zk_conn)

###############################################################################
# pvc network dhcp static remove
###############################################################################
@click.command(name='remove', short_help='Remove a DHCP static reservation.')
@click.argument(
    'net'
)
@click.argument(
    'reservation'
)
def net_dhcp_static_remove(net, reservation):
    """
    Remove a DHCP static reservation RESERVATION from virtual network NET; RESERVATION can be either a MAC address, an IP address, or a hostname; NET can be either a VNI or description.
    """

    zk_conn = pvc_common.startZKConnection(zk_host)
    retcode, retmsg = pvc_network.remove_dhcp_reservation(zk_conn, net, reservation)
    cleanup(retcode, retmsg, zk_conn)

###############################################################################
# pvc network dhcp static list
###############################################################################
@click.command(name='list', short_help='List DHCP static reservations.')
@click.argument(
    'net'
)
@click.argument(
    'limit', default=None, required=False
)
def net_dhcp_static_list(net, limit):
    """
    List all DHCP static reservations in virtual network NET; optionally only match elements matching regex LIMIT; NET can be either a VNI or description.
    """

    zk_conn = pvc_common.startZKConnection(zk_host)
    retcode, retdata = pvc_network.get_list_dhcp(zk_conn, net, limit, only_static=True)
    if retcode:
        pvc_network.format_list_dhcp(retdata)
        retdata = ''
    cleanup(retcode, retdata, zk_conn)

###############################################################################
# pvc network acl
###############################################################################
@click.group(name='acl', short_help='Manage a PVC virtual network firewall ACL rule.', context_settings=CONTEXT_SETTINGS)
def net_acl():
    """
    Manage firewall ACLs of a VXLAN network in the PVC cluster.
    """
    pass

###############################################################################
# pvc network acl add
###############################################################################
@click.command(name='add', short_help='Add firewall ACL.')
@click.option(
    '--in/--out', 'direction',
    is_flag=True,
    required=True,
    default=None,
    help='Inbound or outbound ruleset.'
)
@click.option(
    '-d', '--description', 'description',
    required=True,
    help='Description of the ACL; must be unique and not contain whitespace.'
)
@click.option(
    '-r', '--rule', 'rule',
    required=True,
    help='NFT firewall rule.'
)
@click.option(
    '-o', '--order', 'order',
    default=None,
    help='Order of rule in the chain (see "list"); defaults to last.'
)
@click.argument(
    'net'
)
def net_acl_add(net, direction, description, rule, order):
    """
    Add a new NFT firewall rule to network NET; the rule is a literal NFT rule belonging to the forward table for the client network; NET can be either a VNI or description.

    NOTE: All client networks are default-allow in both directions; deny rules MUST be added here at the end of the sequence for a default-deny setup.

    NOTE: Ordering places the rule at the specified ID, not before it; the old rule of that ID and all subsequent rules will be moved down.

    Example:

    pvc network acl add 1001 --in --rule "tcp dport 22 ct state new accept" --description "ssh-in" --order 3
    """

    zk_conn = pvc_common.startZKConnection(zk_host)
    retcode, retmsg = pvc_network.add_acl(zk_conn, net, direction, description, rule, order)
    cleanup(retcode, retmsg, zk_conn)

###############################################################################
# pvc network acl remove
###############################################################################
@click.command(name='remove', short_help='Remove firewall ACL.')
@click.option(
    '--in/--out', 'direction',
    is_flag=True,
    required=True,
    default=None,
    help='Inbound or outbound rule set.'
)
@click.argument(
    'net'
)
@click.argument(
    'rule',
)
def net_acl_remove(net, rule, direction):
    """
    Remove an NFT firewall rule RULE from network NET; RULE can be either a sequence order identifier or description; NET can be either a VNI or description."
    """

    zk_conn = pvc_common.startZKConnection(zk_host)
    retcode, retmsg = pvc_network.remove_acl(zk_conn, net, rule, direction)
    cleanup(retcode, retmsg, zk_conn)

###############################################################################
# pvc network acl list
###############################################################################
@click.command(name='list', short_help='List firewall ACLs.')
@click.option(
    '--in/--out', 'direction',
    is_flag=True,
    required=False,
    default=None,
    help='Inbound or outbound rule set only.'
)
@click.argument(
    'net'
)
@click.argument(
    'limit', default=None, required=False
)
def net_acl_list(net, limit, direction):
    """
    List all NFT firewall rules in network NET; optionally only match elements matching description regex LIMIT; NET can be either a VNI or description.
    """

    zk_conn = pvc_common.startZKConnection(zk_host)
    retcode, retdata = pvc_network.get_list_acl(zk_conn, net, limit, direction)
    if retcode:
        pvc_network.format_list_acl(retdata)
        retdata = ''
    cleanup(retcode, retdata, zk_conn)

###############################################################################
# pvc storage
###############################################################################
# Note: The prefix `storage` allows future potential storage subsystems.
#       Since Ceph is the only section not abstracted by PVC directly
#       (i.e. it references Ceph-specific concepts), this makes more
#       sense in the long-term.
###############################################################################
@click.group(name='storage', short_help='Manage the PVC storage cluster.', context_settings=CONTEXT_SETTINGS)
def cli_storage():
    """
    Manage the storage of the PVC cluster.
    """
    pass

###############################################################################
# pvc storage ceph
###############################################################################
@click.group(name='ceph', short_help='Manage the PVC Ceph storage cluster.', context_settings=CONTEXT_SETTINGS)
def cli_ceph():
    """
    Manage the Ceph storage of the PVC cluster.

    NOTE: The PVC Ceph interface is limited to the most common tasks. Any other administrative tasks must be performed on a node directly.
    """
    pass

###############################################################################
# pvc storage ceph status
###############################################################################
@click.command(name='status', short_help='Show storage cluster status.')
def ceph_status():
    """
    Show detailed status of the storage cluster.
    """

    zk_conn = pvc_common.startZKConnection(zk_host)
    retcode, retdata = pvc_ceph.get_status(zk_conn)
    if retcode:
        pvc_ceph.format_raw_output(retdata)
        retdata = ''
    cleanup(retcode, retdata, zk_conn)

###############################################################################
# pvc storage ceph df
###############################################################################
@click.command(name='df', short_help='Show storage cluster utilization.')
def ceph_radosdf():
    """
    Show utilization of the storage cluster.
    """

    zk_conn = pvc_common.startZKConnection(zk_host)
    retcode, retdata = pvc_ceph.get_radosdf(zk_conn)
    if retcode:
        pvc_ceph.format_raw_output(retdata)
        retdata = ''
    cleanup(retcode, retdata, zk_conn)

###############################################################################
# pvc storage ceph osd
###############################################################################
@click.group(name='osd', short_help='Manage OSDs in the PVC storage cluster.', context_settings=CONTEXT_SETTINGS)
def ceph_osd():
    """
    Manage the Ceph OSDs of the PVC cluster.
    """
    pass

###############################################################################
# pvc storage ceph osd add
###############################################################################
@click.command(name='add', short_help='Add new OSD.')
@click.argument(
    'node'
)
@click.argument(
    'device'
)
@click.option(
    '-w', '--weight', 'weight',
    default=1.0, show_default=True,
    help='Weight of the OSD within the CRUSH map.'
)
@click.option(
    '--yes', 'yes',
    is_flag=True, default=False,
    help='Pre-confirm the disk destruction.'
)
def ceph_osd_add(node, device, weight, yes):
    """
    Add a new Ceph OSD on node NODE with block device DEVICE to the cluster.
    """

    if not yes:
        click.echo('DANGER: This will completely destroy all data on {} disk {}.'.format(node, device))
        choice = input('Are you sure you want to do this? (y/N) ')
        if choice != 'y' and choice != 'Y':
            exit(0)

    zk_conn = pvc_common.startZKConnection(zk_host)
    retcode, retmsg = pvc_ceph.add_osd(zk_conn, node, device, weight)
    cleanup(retcode, retmsg, zk_conn)

###############################################################################
# pvc storage ceph osd remove
###############################################################################
@click.command(name='remove', short_help='Remove OSD.')
@click.argument(
    'osdid'
)
@click.option(
    '--yes', 'yes',
    is_flag=True, default=False,
    help='Pre-confirm the removal.'
)
def ceph_osd_remove(osdid, yes):
    """
    Remove a Ceph OSD with ID OSDID from the cluster.
    """

    if not yes:
        click.echo('DANGER: This will completely remove OSD {} from cluster. OSDs will rebalance.'.format(osdid))
        choice = input('Are you sure you want to do this? (y/N) ')
        if choice != 'y' and choice != 'Y':
            exit(0)

    zk_conn = pvc_common.startZKConnection(zk_host)
    retcode, retmsg = pvc_ceph.remove_osd(zk_conn, osdid)
    cleanup(retcode, retmsg, zk_conn)

###############################################################################
# pvc storage ceph osd in
###############################################################################
@click.command(name='in', short_help='Online OSD.')
@click.argument(
    'osdid'
)
def ceph_osd_in(osdid):
    """
    Set a Ceph OSD with ID OSDID online in the cluster.
    """

    zk_conn = pvc_common.startZKConnection(zk_host)
    retcode, retmsg = pvc_ceph.in_osd(zk_conn, osdid)
    cleanup(retcode, retmsg, zk_conn)

###############################################################################
# pvc storage ceph osd out
###############################################################################
@click.command(name='out', short_help='Offline OSD.')
@click.argument(
    'osdid'
)
def ceph_osd_out(osdid):
    """
    Set a Ceph OSD with ID OSDID offline in the cluster.
    """

    zk_conn = pvc_common.startZKConnection(zk_host)
    retcode, retmsg = pvc_ceph.out_osd(zk_conn, osdid)
    cleanup(retcode, retmsg, zk_conn)

###############################################################################
# pvc storage ceph osd set
###############################################################################
@click.command(name='set', short_help='Set property.')
@click.argument(
    'osd_property'
)
def ceph_osd_set(osd_property):
    """
    Set a Ceph OSD property OSD_PROPERTY on the cluster.

    Valid properties are:

      full|pause|noup|nodown|noout|noin|nobackfill|norebalance|norecover|noscrub|nodeep-scrub|notieragent|sortbitwise|recovery_deletes|require_jewel_osds|require_kraken_osds 
    """

    zk_conn = pvc_common.startZKConnection(zk_host)
    retcode, retmsg = pvc_ceph.set_osd(zk_conn, osd_property)
    cleanup(retcode, retmsg, zk_conn)

###############################################################################
# pvc storage ceph osd unset
###############################################################################
@click.command(name='unset', short_help='Unset property.')
@click.argument(
    'osd_property'
)
def ceph_osd_unset(osd_property):
    """
    Unset a Ceph OSD property OSD_PROPERTY on the cluster.

    Valid properties are:

      full|pause|noup|nodown|noout|noin|nobackfill|norebalance|norecover|noscrub|nodeep-scrub|notieragent|sortbitwise|recovery_deletes|require_jewel_osds|require_kraken_osds 
    """

    zk_conn = pvc_common.startZKConnection(zk_host)
    retcode, retmsg = pvc_ceph.unset_osd(zk_conn, osd_property)
    cleanup(retcode, retmsg, zk_conn)

###############################################################################
# pvc storage ceph osd list
###############################################################################
@click.command(name='list', short_help='List cluster OSDs.')
@click.argument(
    'limit', default=None, required=False
)
def ceph_osd_list(limit):
    """
    List all Ceph OSDs in the cluster; optionally only match elements matching ID regex LIMIT.
    """

    zk_conn = pvc_common.startZKConnection(zk_host)
    retcode, retdata = pvc_ceph.get_list_osd(zk_conn, limit)
    if retcode:
        pvc_ceph.format_list_osd(retdata)
        retdata = ''
    cleanup(retcode, retdata, zk_conn)

###############################################################################
# pvc storage ceph pool
###############################################################################
@click.group(name='pool', short_help='Manage RBD pools in the PVC storage cluster.', context_settings=CONTEXT_SETTINGS)
def ceph_pool():
    """
    Manage the Ceph RBD pools of the PVC cluster.
    """
    pass

###############################################################################
# pvc storage ceph pool add
###############################################################################
@click.command(name='add', short_help='Add new RBD pool.')
@click.argument(
    'name'
)
@click.argument(
    'pgs'
)
@click.option(
    '--replcfg', 'replcfg',
    default='copies=3,mincopies=2', show_default=True, required=False,
    help="""
    The replication configuration, specifying both a "copies" and "mincopies" value, separated by a
    comma, e.g. "copies=3,mincopies=2". The "copies" value specifies the total number of replicas and should not exceed the total number of nodes; the "mincopies" value specifies the minimum number of available copies to allow writes. For additional details please see the Cluster Architecture documentation.
    """
)
def ceph_pool_add(name, pgs, replcfg):
    """
    Add a new Ceph RBD pool with name NAME and PGS placement groups.

    """

    zk_conn = pvc_common.startZKConnection(zk_host)
    retcode, retmsg = pvc_ceph.add_pool(zk_conn, name, pgs, replcfg)
    cleanup(retcode, retmsg, zk_conn)

###############################################################################
# pvc storage ceph pool remove
###############################################################################
@click.command(name='remove', short_help='Remove RBD pool.')
@click.argument(
    'name'
)
@click.option(
    '--yes', 'yes',
    is_flag=True, default=False,
    help='Pre-confirm the removal.'
)
def ceph_pool_remove(name, yes):
    """
    Remove a Ceph RBD pool with name NAME and all volumes on it.
    """

    if not yes:
        click.echo('DANGER: This will completely remove pool {} and all data contained in it.'.format(name))
        choice = input('Are you sure you want to do this? (y/N) ')
        if choice != 'y' and choice != 'Y':
            pool_name_check = input('Please enter the pool name to confirm: ')
            if pool_name_check != name:
                exit(0)

    zk_conn = pvc_common.startZKConnection(zk_host)
    retcode, retmsg = pvc_ceph.remove_pool(zk_conn, name)
    cleanup(retcode, retmsg, zk_conn)

###############################################################################
# pvc storage ceph pool list
###############################################################################
@click.command(name='list', short_help='List cluster RBD pools.')
@click.argument(
    'limit', default=None, required=False
)
def ceph_pool_list(limit):
    """
    List all Ceph RBD pools in the cluster; optionally only match elements matching name regex LIMIT.
    """

    zk_conn = pvc_common.startZKConnection(zk_host)
    retcode, retdata = pvc_ceph.get_list_pool(zk_conn, limit)
    if retcode:
        pvc_ceph.format_list_pool(retdata)
        retdata = ''
    cleanup(retcode, retdata, zk_conn)

###############################################################################
# pvc storage ceph volume
###############################################################################
@click.group(name='volume', short_help='Manage RBD volumes in the PVC storage cluster.', context_settings=CONTEXT_SETTINGS)
def ceph_volume():
    """
    Manage the Ceph RBD volumes of the PVC cluster.
    """
    pass

###############################################################################
# pvc storage ceph volume add
###############################################################################
@click.command(name='add', short_help='Add new RBD volume.')
@click.argument(
    'pool'
)
@click.argument(
    'name'
)
@click.argument(
    'size'
)
def ceph_volume_add(pool, name, size):
    """
    Add a new Ceph RBD volume with name NAME and size SIZE [in human units, e.g. 1024M, 20G, etc.] to pool POOL.
    """

    zk_conn = pvc_common.startZKConnection(zk_host)
    retcode, retmsg = pvc_ceph.add_volume(zk_conn, pool, name, size)
    cleanup(retcode, retmsg, zk_conn)

###############################################################################
# pvc storage ceph volume remove
###############################################################################
@click.command(name='remove', short_help='Remove RBD volume.')
@click.argument(
    'pool'
)
@click.argument(
    'name'
)
@click.option(
    '--yes', 'yes',
    is_flag=True, default=False,
    help='Pre-confirm the removal.'
)
def ceph_volume_remove(pool, name, yes):
    """
    Remove a Ceph RBD volume with name NAME from pool POOL.
    """

    if not yes:
        click.echo('DANGER: This will completely remove volume {} from pool {} and all data contained in it.'.format(name, pool))
        choice = input('Are you sure you want to do this? (y/N) ')
        if choice != 'y' and choice != 'Y':
            exit(0)

    zk_conn = pvc_common.startZKConnection(zk_host)
    retcode, retmsg = pvc_ceph.remove_volume(zk_conn, pool, name)
    cleanup(retcode, retmsg, zk_conn)

###############################################################################
# pvc storage ceph volume resize
###############################################################################
@click.command(name='resize', short_help='Resize RBD volume.')
@click.argument(
    'pool'
)
@click.argument(
    'name'
)
@click.argument(
    'size'
)
def ceph_volume_resize(pool, name, size):
    """
    Resize an existing Ceph RBD volume with name NAME in pool POOL to size SIZE [in human units, e.g. 1024M, 20G, etc.].
    """
    zk_conn = pvc_common.startZKConnection(zk_host)
    retcode, retmsg = pvc_ceph.resize_volume(zk_conn, pool, name, size)
    cleanup(retcode, retmsg, zk_conn)

###############################################################################
# pvc storage ceph volume rename
###############################################################################
@click.command(name='rename', short_help='Rename RBD volume.')
@click.argument(
    'pool'
)
@click.argument(
    'name'
)
@click.argument(
    'new_name'
)
def ceph_volume_rename(pool, name, new_name):
    """
    Rename an existing Ceph RBD volume with name NAME in pool POOL to name NEW_NAME.
    """
    zk_conn = pvc_common.startZKConnection(zk_host)
    retcode, retmsg = pvc_ceph.rename_volume(zk_conn, pool, name, new_name)
    cleanup(retcode, retmsg, zk_conn)

###############################################################################
# pvc storage ceph volume clone
###############################################################################
@click.command(name='rename', short_help='Clone RBD volume.')
@click.argument(
    'pool'
)
@click.argument(
    'name'
)
@click.argument(
    'new_name'
)
def ceph_volume_clone(pool, name, new_name):
    """
    Clone a Ceph RBD volume with name NAME in pool POOL to name NEW_NAME in pool POOL.
    """
    zk_conn = pvc_common.startZKConnection(zk_host)
    retcode, retmsg = pvc_ceph.clone_volume(zk_conn, pool, name, new_name)
    cleanup(retcode, retmsg, zk_conn)

###############################################################################
# pvc storage ceph volume list
###############################################################################
@click.command(name='list', short_help='List cluster RBD volumes.')
@click.argument(
    'limit', default=None, required=False
)
@click.option(
    '-p', '--pool', 'pool',
    default=None, show_default=True,
    help='Show volumes from this pool only.'
)
def ceph_volume_list(limit, pool):
    """
    List all Ceph RBD volumes in the cluster; optionally only match elements matching name regex LIMIT.
    """

    zk_conn = pvc_common.startZKConnection(zk_host)
    retcode, retdata = pvc_ceph.get_list_volume(zk_conn, pool, limit)
    if retcode:
        pvc_ceph.format_list_volume(retdata)
        retdata = ''
    cleanup(retcode, retdata, zk_conn)

###############################################################################
# pvc storage ceph volume snapshot
###############################################################################
@click.group(name='snapshot', short_help='Manage RBD volume snapshots in the PVC storage cluster.', context_settings=CONTEXT_SETTINGS)
def ceph_volume_snapshot():
    """
    Manage the Ceph RBD volume snapshots of the PVC cluster.
    """
    pass

###############################################################################
# pvc storage ceph volume snapshot add
###############################################################################
@click.command(name='add', short_help='Add new RBD volume snapshot.')
@click.argument(
    'pool'
)
@click.argument(
    'volume'
)
@click.argument(
    'name'
)
def ceph_volume_snapshot_add(pool, volume, name):
    """
    Add a snapshot with name NAME of Ceph RBD volume VOLUME in pool POOL.
    """

    zk_conn = pvc_common.startZKConnection(zk_host)
    retcode, retmsg = pvc_ceph.add_snapshot(zk_conn, pool, volume, name)
    cleanup(retcode, retmsg, zk_conn)

###############################################################################
# pvc storage ceph volume snapshot rename
###############################################################################
@click.command(name='rename', short_help='Rename RBD volume snapshot.')
@click.argument(
    'pool'
)
@click.argument(
    'volume'
)
@click.argument(
    'name'
)
@click.argument(
    'new_name'
)
def ceph_volume_snapshot_rename(pool, volume, name, new_name):
    """
    Rename an existing Ceph RBD volume snapshot with name NAME to name NEW_NAME for volume VOLUME in pool POOL.
    """
    zk_conn = pvc_common.startZKConnection(zk_host)
    retcode, retmsg = pvc_ceph.rename_snapshot(zk_conn, pool, volume, name, new_name)
    cleanup(retcode, retmsg, zk_conn)

###############################################################################
# pvc storage ceph volume snapshot remove
###############################################################################
@click.command(name='remove', short_help='Remove RBD volume snapshot.')
@click.argument(
    'pool'
)
@click.argument(
    'volume'
)
@click.argument(
    'name'
)
@click.option(
    '--yes', 'yes',
    is_flag=True, default=False,
    help='Pre-confirm the removal.'
)
def ceph_volume_snapshot_remove(pool, volume, name, yes):
    """
    Remove a Ceph RBD volume snapshot with name NAME from volume VOLUME in pool POOL.
    """

    if not yes:
        click.echo('DANGER: This will completely remove snapshot {} from volume {}/{} and all data contained in it.'.format(name, pool, volume))
        choice = input('Are you sure you want to do this? (y/N) ')
        if choice != 'y' and choice != 'Y':
            exit(0)

    zk_conn = pvc_common.startZKConnection(zk_host)
    retcode, retmsg = pvc_ceph.remove_snapshot(zk_conn, pool, volume, name)
    cleanup(retcode, retmsg, zk_conn)

###############################################################################
# pvc storage ceph volume snapshot list
###############################################################################
@click.command(name='list', short_help='List cluster RBD volume shapshots.')
@click.argument(
    'limit', default=None, required=False
)
@click.option(
    '-p', '--pool', 'pool',
    default=None, show_default=True,
    help='Show snapshots from this pool only.'
)
@click.option(
    '-p', '--volume', 'volume',
    default=None, show_default=True,
    help='Show snapshots from this volume only.'
)
def ceph_volume_snapshot_list(pool, volume, limit):
    """
    List all Ceph RBD volume snapshots; optionally only match elements matching name regex LIMIT.
    """

    zk_conn = pvc_common.startZKConnection(zk_host)
    retcode, retdata = pvc_ceph.get_list_snapshot(zk_conn, pool, volume, limit)
    if retcode:
        pvc_ceph.format_list_snapshot(retdata)
        retdata = ''
    cleanup(retcode, retdata, zk_conn)


###############################################################################
# pvc status
###############################################################################
@click.command(name='status', short_help='Show current cluster status.')
@click.option(
    '-f', '--format', 'oformat', default='plain', show_default=True,
    type=click.Choice(['plain', 'json', 'json-pretty']),
    help='Output format of cluster status information.'
)
def status_cluster(oformat):
    """
    Show basic information and health for the active PVC cluster.
    """
    zk_conn = pvc_common.startZKConnection(zk_host)
    retcode, retdata = pvc_cluster.get_info(zk_conn)
    if retcode:
        pvc_cluster.format_info(retdata, oformat)
        retdata = ''
    cleanup(retcode, retdata, zk_conn)

###############################################################################
# pvc init
###############################################################################
@click.command(name='init', short_help='Initialize a new cluster.')
@click.option(
    '--yes', 'yes',
    is_flag=True, default=False,
    help='Pre-confirm the initialization.'
)
def init_cluster(yes):
    """
    Perform initialization of a new PVC cluster.
    """

    if not yes:
        click.echo('DANGER: This will remove any existing cluster on these coordinators and create a new cluster. Any existing resources on the old cluster will be left abandoned.')
        choice = input('Are you sure you want to do this? (y/N) ')
        if choice != 'y' and choice != 'Y':
            exit(0)

    click.echo('Initializing a new cluster with Zookeeper address "{}".'.format(zk_host))

    # Easter-egg
    click.echo("Some music while we're Layin' Pipe? https://youtu.be/sw8S_Kv89IU")

    # Open a Zookeeper connection
    zk_conn = pvc_common.startZKConnection(zk_host)

    # Destroy the existing data
    try:
        zk_conn.delete('/networks', recursive=True)
        zk_conn.delete('/domains', recursive=True)
        zk_conn.delete('/nodes', recursive=True)
        zk_conn.delete('/primary_node', recursive=True)
        zk_conn.delete('/ceph', recursive=True)
    except:
        pass

    # Create the root keys
    transaction = zk_conn.transaction()
    transaction.create('/nodes', ''.encode('ascii'))
    transaction.create('/primary_node', 'none'.encode('ascii'))
    transaction.create('/domains', ''.encode('ascii'))
    transaction.create('/networks', ''.encode('ascii'))
    transaction.create('/ceph', ''.encode('ascii'))
    transaction.create('/ceph/osds', ''.encode('ascii'))
    transaction.create('/ceph/pools', ''.encode('ascii'))
    transaction.create('/ceph/volumes', ''.encode('ascii'))
    transaction.create('/ceph/snapshots', ''.encode('ascii'))
    transaction.create('/cmd', ''.encode('ascii'))
    transaction.create('/cmd/domains', ''.encode('ascii'))
    transaction.create('/cmd/ceph', ''.encode('ascii'))
    transaction.commit()

    # Close the Zookeeper connection
    pvc_common.stopZKConnection(zk_conn)

    click.echo('Successfully initialized new cluster. Any running PVC daemons will need to be restarted.')


###############################################################################
# pvc
###############################################################################
@click.group(context_settings=CONTEXT_SETTINGS)
@click.option(
    '-z', '--zookeeper', '_zk_host', envvar='PVC_ZOOKEEPER', default=None,
    help='Zookeeper connection string.'
)
@click.option(
    '-v', '--debug', '_debug', envvar='PVC_DEBUG', is_flag=True, default=False,
    help='Additional debug details.'
)
def cli(_zk_host, _debug):
    """
    Parallel Virtual Cluster CLI management tool

    Environment variables:

      "PVC_ZOOKEEPER": Set the cluster Zookeeper address instead of using "--zookeeper".

    If no PVC_ZOOKEEPER/--zookeeper is specified, attempts to load coordinators list from /etc/pvc/pvcd.yaml.
    """

    # If no zk_host was passed, try to read from /etc/pvc/pvcd.yaml; otherwise fail
    if _zk_host is None:
        try:
            cfgfile = '/etc/pvc/pvcd.yaml'
            with open(cfgfile) as cfgf:
                o_config = yaml.load(cfgf)
            _zk_host = o_config['pvc']['cluster']['coordinators']
        except:
            _zk_host = None

    if _zk_host is None:
        print('ERROR: Must specify a PVC_ZOOKEEPER value or have a coordinator set configured in /etc/pvc/pvcd.yaml.')
        exit(1)

    global zk_host
    zk_host = _zk_host
    global config
    config['debug'] = _debug


#
# Click command tree
#
cli_node.add_command(node_secondary)
cli_node.add_command(node_primary)
cli_node.add_command(node_flush)
cli_node.add_command(node_ready)
cli_node.add_command(node_unflush)
cli_node.add_command(node_info)
cli_node.add_command(node_list)

cli_vm.add_command(vm_define)
cli_vm.add_command(vm_meta)
cli_vm.add_command(vm_modify)
cli_vm.add_command(vm_undefine)
cli_vm.add_command(vm_remove)
cli_vm.add_command(vm_dump)
cli_vm.add_command(vm_start)
cli_vm.add_command(vm_restart)
cli_vm.add_command(vm_shutdown)
cli_vm.add_command(vm_stop)
cli_vm.add_command(vm_disable)
cli_vm.add_command(vm_move)
cli_vm.add_command(vm_migrate)
cli_vm.add_command(vm_unmigrate)
cli_vm.add_command(vm_flush_locks)
cli_vm.add_command(vm_info)
cli_vm.add_command(vm_log)
cli_vm.add_command(vm_list)

cli_network.add_command(net_add)
cli_network.add_command(net_modify)
cli_network.add_command(net_remove)
cli_network.add_command(net_info)
cli_network.add_command(net_list)
cli_network.add_command(net_dhcp)
cli_network.add_command(net_acl)

net_dhcp.add_command(net_dhcp_list)
net_dhcp.add_command(net_dhcp_static)

net_dhcp_static.add_command(net_dhcp_static_add)
net_dhcp_static.add_command(net_dhcp_static_remove)
net_dhcp_static.add_command(net_dhcp_static_list)

net_acl.add_command(net_acl_add)
net_acl.add_command(net_acl_remove)
net_acl.add_command(net_acl_list)

ceph_osd.add_command(ceph_osd_add)
ceph_osd.add_command(ceph_osd_remove)
ceph_osd.add_command(ceph_osd_in)
ceph_osd.add_command(ceph_osd_out)
ceph_osd.add_command(ceph_osd_set)
ceph_osd.add_command(ceph_osd_unset)
ceph_osd.add_command(ceph_osd_list)

ceph_pool.add_command(ceph_pool_add)
ceph_pool.add_command(ceph_pool_remove)
ceph_pool.add_command(ceph_pool_list)

ceph_volume.add_command(ceph_volume_add)
ceph_volume.add_command(ceph_volume_resize)
ceph_volume.add_command(ceph_volume_rename)
ceph_volume.add_command(ceph_volume_remove)
ceph_volume.add_command(ceph_volume_list)
ceph_volume.add_command(ceph_volume_snapshot)

ceph_volume_snapshot.add_command(ceph_volume_snapshot_add)
ceph_volume_snapshot.add_command(ceph_volume_snapshot_rename)
ceph_volume_snapshot.add_command(ceph_volume_snapshot_remove)
ceph_volume_snapshot.add_command(ceph_volume_snapshot_list)

cli_ceph.add_command(ceph_status)
cli_ceph.add_command(ceph_radosdf)
cli_ceph.add_command(ceph_osd)
cli_ceph.add_command(ceph_pool)
cli_ceph.add_command(ceph_volume)

cli_storage.add_command(cli_ceph)

cli.add_command(cli_node)
cli.add_command(cli_vm)
cli.add_command(cli_network)
cli.add_command(cli_storage)
cli.add_command(status_cluster)
cli.add_command(init_cluster)

#
# Main entry point
#
def main():
    return cli(obj={})

if __name__ == '__main__':
    main()

