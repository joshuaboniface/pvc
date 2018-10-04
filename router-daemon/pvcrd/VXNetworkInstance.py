#!/usr/bin/env python3

# VXNetworkInstance.py - Class implementing a PVC VM network (router-side) and run by pvcrd
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

import os
import sys

import daemon_lib.ansiiprint as ansiiprint
import daemon_lib.zkhandler as zkhandler
import daemon_lib.common as common

class VXNetworkInstance():
    # Initialization function
    def __init__ (self, vni, zk_conn, config, this_router):
        self.vni = vni
        self.zk_conn = zk_conn
        self.this_router = this_router
        self.vni_dev = config['vni_dev']

        self.old_description = None
        self.description = None
        self.domain = None
        self.ip_gateway = zkhandler.readdata(self.zk_conn, '/networks/{}/ip_gateway'.format(self.vni))
        self.ip_network = None
        self.ip_cidrnetmask = None
        self.dhcp_flag = zkhandler.readdata(self.zk_conn, '/networks/{}/dhcp_flag'.format(self.vni))
        self.dhcp_start = None
        self.dhcp_end = None

        self.vxlan_nic = 'vxlan{}'.format(self.vni)
        self.bridge_nic = 'br{}'.format(self.vni)

        self.firewall_rules = {}

        self.dhcp_server_daemon = None

        self.dnsmasq_hostsdir = '/var/lib/dnsmasq/{}'.format(self.vni)
        self.dhcp_reservations = zkhandler.listchildren(self.zk_conn, '/networks/{}/dhcp_reservations'.format(self.vni))

        self.createNetwork()

        # Zookeper handlers for changed states
        @self.zk_conn.DataWatch('/networks/{}'.format(self.vni))
        def watch_network_description(data, stat, event=''):
            if event and event.type == 'DELETED':
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            if data and self.description != data.decode('ascii'):
                self.old_description = self.description
                self.description = data.decode('ascii')

        @self.zk_conn.DataWatch('/networks/{}/domain'.format(self.vni))
        def watch_network_domain(data, stat, event=''):
            if event and event.type == 'DELETED':
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            if data and self.domain != data.decode('ascii'):
                domain = data.decode('ascii')
                self.domain = domain

        @self.zk_conn.DataWatch('/networks/{}/ip_network'.format(self.vni))
        def watch_network_ip_network(data, stat, event=''):
            if event and event.type == 'DELETED':
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            if data and self.ip_network != data.decode('ascii'):
                ip_network = data.decode('ascii')
                self.ip_network = ip_network
                self.ip_cidrnetmask = ip_network.split('/')[-1]

        @self.zk_conn.DataWatch('/networks/{}/ip_gateway'.format(self.vni))
        def watch_network_gateway(data, stat, event=''):
            if event and event.type == 'DELETED':
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            if data and self.ip_gateway != data.decode('ascii'):
                orig_gateway = self.ip_gateway
                self.ip_gateway = data.decode('ascii')
                if self.this_router.network_state == 'primary':
                    if orig_gateway:
                        self.removeGatewayAddress()
                    self.createGatewayAddress()

        @self.zk_conn.DataWatch('/networks/{}/dhcp_flag'.format(self.vni))
        def watch_network_dhcp_status(data, stat, event=''):
            if event and event.type == 'DELETED':
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            if data and self.dhcp_flag != data.decode('ascii'):
                self.dhcp_flag = ( data.decode('ascii') == 'True' )
                if self.dhcp_flag and self.this_router.network_state == 'primary':
                    self.startDHCPServer()
                elif self.this_router.network_state == 'primary':
                    self.stopDHCPServer()

        @self.zk_conn.DataWatch('/networks/{}/dhcp_start'.format(self.vni))
        def watch_network_dhcp_start(data, stat, event=''):
            if event and event.type == 'DELETED':
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            if data and self.dhcp_start != data.decode('ascii'):
                self.dhcp_start = data.decode('ascii')

        @self.zk_conn.DataWatch('/networks/{}/dhcp_end'.format(self.vni))
        def watch_network_dhcp_end(data, stat, event=''):
            if event and event.type == 'DELETED':
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            if data and self.dhcp_end != data.decode('ascii'):
                self.dhcp_end = data.decode('ascii')

        @self.zk_conn.ChildrenWatch('/networks/{}/dhcp_reservations'.format(self.vni))
        def watch_network_dhcp_reservations(reservations, event=''):
            print(reservations)
            if self.dhcp_reservations != reservations:
                for reservation in reservations:
                    if reservation not in self.dhcp_reservations:
                        # Add new reservation file
                        filename = '{}/{}'.format(self.dnsmasq_hostsdir, reservation)
                        ipaddr = zkhandler.readdata(
                            self.zk_conn,
                            '/networks/{}/dhcp_reservations/{}/ipaddr'.format(
                                self.vni,
                                reservation
                            )
                        )
                        entry = '{},{}'.format(reservation, ipaddr)
                        with open(filename, 'w') as outfile:
                            outfile.write(entry)
                for reservation in self.dhcp_reservations:
                    if reservation not in reservations:
                        filename = '{}/{}'.format(self.dnsmasq_hostsdir, reservation)
                        # Remove old reservation file
                        os.remove(filename)
                self.dhcp_server_daemon.signal('hup')
                self.dhcp_reservations = reservations

    def getvni(self):
        return self.vni

    def createNetwork(self):
        ansiiprint.echo(
            'Creating VNI {} device on interface {}'.format(
                self.vni,
                self.vni_dev
            ),
            '',
            'o'
        )
        common.run_os_command(
            'ip link add {} type vxlan id {} dstport 4789 dev {}'.format(
                self.vxlan_nic,
                self.vni,
                self.vni_dev
            )
        )
        common.run_os_command(
            'brctl addbr {}'.format(
                self.bridge_nic
            )
        )
        common.run_os_command(
            'brctl addif {} {}'.format(
                self.bridge_nic,
                self.vxlan_nic
            )
        )
        common.run_os_command(
            'ip link set {} up'.format(
                self.vxlan_nic
            )
        )
        common.run_os_command(
            'ip link set {} up'.format(
                self.bridge_nic
            )
        )

    def createGatewayAddress(self):
        if self.this_router.getnetworkstate() == 'primary':
            ansiiprint.echo(
                'Creating gateway {} on interface {} (VNI {})'.format(
                    self.ip_gateway,
                    self.bridge_nic,
                    self.vni
                ),
                '',
                'o'
            )
            common.run_os_command(
                'ip address add {}/{} dev {}'.format(
                    self.ip_gateway,
                    self.ip_cidrnetmask,
                    self.bridge_nic
                )
            )
            common.run_os_command(
                'arping -A -c2 -I {} {}'.format(
                    self.bridge_nic,
                    self.ip_gateway
                ),
                background=True
            )

    def startDHCPServer(self):
        if self.this_router.getnetworkstate() == 'primary':
            ansiiprint.echo(
                'Starting dnsmasq DHCP server on interface {} (VNI {})'.format(
                    self.bridge_nic,
                    self.vni
                ),
                '',
                'o'
            )
            # Create the network hostsdir
            common.run_os_command(
                '/bin/mkdir --parents {}'.format(
                    self.dnsmasq_hostsdir
                )
            )
            # Recreate the environment we need for dnsmasq
            pvcrd_config_file = os.environ['PVCRD_CONFIG_FILE']
            dhcp_environment = {
                'DNSMASQ_INTERFACE': self.bridge_nic,
                'PVCRD_CONFIG_FILE': pvcrd_config_file
            }
            # Define the dnsmasq config
            dhcp_configuration = [
                '--domain-needed',
                '--bogus-priv',
                '--no-resolv',
                '--filterwin2k',
                '--expand-hosts',
                '--domain={}'.format(self.domain),
                '--local=/{}/'.format(self.domain),
                '--listen-address={}'.format(self.ip_gateway),
                '--bind-interfaces',
                '--leasefile-ro',
                '--dhcp-script=/usr/share/pvc/pvcrd/dnsmasq-zookeeper-leases.py',
                '--dhcp-range={},{},4h'.format(self.dhcp_start, self.dhcp_end),
                '--dhcp-lease-max=99',
                '--dhcp-hostsdir={}'.format(self.dnsmasq_hostsdir),
                '--log-facility=DAEMON',
                '--keep-in-foreground'
            ]
            # Start the dnsmasq process in a thread
            self.dhcp_server_daemon = common.run_os_daemon(
                '/usr/sbin/dnsmasq {}'.format(
                    ' '.join(dhcp_configuration)
                ),
                environment=dhcp_environment,
                return_pid=True
            )

    def removeNetwork(self):
        ansiiprint.echo(
            'Removing VNI {} device on interface {}'.format(
                self.vni,
                self.vni_dev
            ),
            '',
            'o'
        )
        common.run_os_command(
            'ip link set {} down'.format(
                self.bridge_nic
            )
        )
        common.run_os_command(
            'ip link set {} down'.format(
                self.vxlan_nic
            )
        )
        common.run_os_command(
            'brctl delif {} {}'.format(
                self.bridge_nic,
                self.vxlan_nic
            )
        )
        common.run_os_command(
            'brctl delbr {}'.format(
                self.bridge_nic
            )
        )
        common.run_os_command(
            'ip link delete {}'.format(
                self.vxlan_nic
            )
        )

    def removeGatewayAddress(self):
        ansiiprint.echo(
            'Removing gateway {} from interface {} (VNI {})'.format(
                self.ip_gateway,
                self.bridge_nic,
                self.vni
            ),
            '',
            'o'
        )
        common.run_os_command(
            'ip address delete {}/{} dev {}'.format(
                self.ip_gateway,
                self.ip_cidrnetmask,
                self.bridge_nic
            )
        )

    def stopDHCPServer(self):
        if self.dhcp_server_daemon:
            ansiiprint.echo(
                'Stopping DHCP server on interface {} (VNI {})'.format(
                    self.bridge_nic,
                    self.vni
                ),
                '',
                'o'
            )
            self.dhcp_server_daemon.signal('int')
