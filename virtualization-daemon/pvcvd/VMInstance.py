#!/usr/bin/env python3

# VMInstance.py - Class implementing a PVC virtual machine and run by pvcvd
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
import uuid
import socket
import time
import threading
import libvirt
import kazoo.client

import daemon_lib.ansiiprint as ansiiprint
import daemon_lib.zkhandler as zkhandler

class VMInstance:
    # Initialization function
    def __init__(self, domuuid, zk_conn, config, thishypervisor):
        # Passed-in variables on creation
        self.domuuid = domuuid
        self.zk_conn = zk_conn
        self.config = config
        self.thishypervisor = thishypervisor

        # These will all be set later
        self.hypervisor = None
        self.state = None
        self.instart = False
        self.inrestart = False
        self.inmigrate = False
        self.inreceive = False
        self.inshutdown = False
        self.instop = False

        self.dom = self.lookupByUUID(self.domuuid)

        # Watch for changes to the state field in Zookeeper
        @zk_conn.DataWatch('/domains/{}/state'.format(self.domuuid))
        def watch_state(data, stat, event=""):
            # If we get a delete state, just terminate outselves
            if data == None:
                return
            # Otherwise perform a management command
            else:
                self.manage_vm_state()

    # Get data functions
    def getstate(self):
        return self.state

    def gethypervisor(self):
        return self.hypervisor

    def getdom(self):
        return self.dom

    def getmemory(self):
        try:
            memory = int(self.dom.info()[2] / 1024)
        except:
            memory = 0

        return memory

    def getvcpus(self):
        try:
            vcpus = int(self.dom.info()[3])
        except:
            vcpus = 0

        return vcpus

    # Manage local node domain_list
    def addDomainToList(self):
        if not self.domuuid in self.thishypervisor.domain_list:
            try:
                # Add the domain to the domain_list array
                self.thishypervisor.domain_list.append(self.domuuid)
                # Push the change up to Zookeeper
                zkhandler.writedata(self.zk_conn, { '/nodes/{}/runningdomains'.format(self.thishypervisor.name): ' '.join(self.thishypervisor.domain_list) })
            except Exception as e:
                ansiiprint.echo('Error adding domain to list: {}'.format(e), '', 'c')

    def removeDomainFromList(self):
        if self.domuuid in self.thishypervisor.domain_list:
            try:
                # Remove the domain from the domain_list array
                self.thishypervisor.domain_list.remove(self.domuuid)
                # Push the change up to Zookeeper
                zkhandler.writedata(self.zk_conn, { '/nodes/{}/runningdomains'.format(self.thishypervisor.name): ' '.join(self.thishypervisor.domain_list) })
            except Exception as e:
                ansiiprint.echo('Error removing domain from list: {}'.format(e), '', 'c')

    # Start up the VM
    def start_vm(self):
        ansiiprint.echo('Starting VM', '{}:'.format(self.domuuid), 'i')
        self.instart = True

        # Start up a new Libvirt connection
        libvirt_name = "qemu:///system"
        lv_conn = libvirt.open(libvirt_name)
        if lv_conn == None:
            ansiiprint.echo('Failed to open local libvirt connection', '{}:'.format(self.domuuid), 'e')
            self.instart = False
            return
   
        # Try to get the current state in case it's already running
        try:
            self.dom = self.lookupByUUID(self.domuuid)
            curstate = self.dom.state()[0]
        except:
            curstate = 'notstart'

        if curstate == libvirt.VIR_DOMAIN_RUNNING:
            # If it is running just update the model
            self.addDomainToList()
            zkhandler.writedata(self.zk_conn, { '/domains/{}/failedreason'.format(self.domuuid): '' })
        else:
            # Or try to create it
            try:
                # Grab the domain information from Zookeeper
                xmlconfig = zkhandler.readdata(self.zk_conn, '/domains/{}/xml'.format(self.domuuid))
                dom = lv_conn.createXML(xmlconfig, 0)
                self.addDomainToList()
                ansiiprint.echo('Successfully started VM', '{}:'.format(self.domuuid), 'o')
                self.dom = dom
                zkhandler.writedata(self.zk_conn, { '/domains/{}/failedreason'.format(self.domuuid): '' })
            except libvirt.libvirtError as e:
                ansiiprint.echo('Failed to create VM', '{}:'.format(self.domuuid), 'e')
                zkhandler.writedata(self.zk_conn, { '/domains/{}/state'.format(self.domuuid): 'failed' })
                zkhandler.writedata(self.zk_conn, { '/domains/{}/failedreason'.format(self.domuuid): str(e) })
                self.dom = None

        lv_conn.close()
        self.instart = False
  
    # Restart the VM
    def restart_vm(self):
        ansiiprint.echo('Restarting VM', '{}:'.format(self.domuuid), 'i')
        self.inrestart = True

        # Start up a new Libvirt connection
        libvirt_name = "qemu:///system"
        lv_conn = libvirt.open(libvirt_name)
        if lv_conn == None:
            ansiiprint.echo('Failed to open local libvirt connection', '{}:'.format(self.domuuid), 'e')
            self.inrestart = False
            return
    
        self.shutdown_vm()
        self.start_vm()
        self.addDomainToList()

        zkhandler.writedata(self.zk_conn, { '/domains/{}/state'.format(self.domuuid): 'start' })
        lv_conn.close()
        self.inrestart = False

    # Stop the VM forcibly without updating state
    def terminate_vm(self):
        ansiiprint.echo('Terminating VM', '{}:'.format(self.domuuid), 'i')
        self.instop = True
        try:
            self.dom.destroy()
        except AttributeError:
            ansiiprint.echo('Failed to terminate VM', '{}:'.format(self.domuuid), 'e')
        self.removeDomainFromList()
        ansiiprint.echo('Successfully terminated VM', '{}:'.format(self.domuuid), 'o')
        self.dom = None
        self.instop = False

    # Stop the VM forcibly
    def stop_vm(self):
        ansiiprint.echo('Forcibly stopping VM', '{}:'.format(self.domuuid), 'i')
        self.instop = True
        try:
            self.dom.destroy()
        except AttributeError:
            ansiiprint.echo('Failed to stop VM', '{}:'.format(self.domuuid), 'e')
        self.removeDomainFromList()

        if self.inrestart == False:
            zkhandler.writedata(self.zk_conn, { '/domains/{}/state'.format(self.domuuid): 'stop' })

        ansiiprint.echo('Successfully stopped VM', '{}:'.format(self.domuuid), 'o')
        self.dom = None
        self.instop = False
    
    # Shutdown the VM gracefully
    def shutdown_vm(self):
        ansiiprint.echo('Gracefully stopping VM', '{}:'.format(self.domuuid), 'i')
        self.inshutdown = True
        self.dom.shutdown()
        try:
            tick = 0
            while self.dom.state()[0] == libvirt.VIR_DOMAIN_RUNNING and tick < 60:
                tick += 1
                time.sleep(0.5)

            if tick >= 60:
                ansiiprint.echo('Shutdown timeout expired', '{}:'.format(self.domuuid), 'e')
                self.stop_vm()
                self.inshutdown = False
                return
        except:
            pass

        self.removeDomainFromList()

        if self.inrestart == False:
            zkhandler.writedata(self.zk_conn, { '/domains/{}/state'.format(self.domuuid): 'stop' })

        ansiiprint.echo('Successfully shutdown VM', '{}:'.format(self.domuuid), 'o')
        self.dom = None
        self.inshutdown = False

    def live_migrate_vm(self, dest_hypervisor):
        try:
            dest_lv_conn = libvirt.open('qemu+tcp://{}/system'.format(self.hypervisor))
            if dest_lv_conn == None:
                raise
        except:
            ansiiprint.echo('Failed to open connection to qemu+tcp://{}/system; aborting migration.'.format(self.hypervisor), '{}:'.format(self.domuuid), 'e')
            return 1

        try:
            target_dom = self.dom.migrate(dest_lv_conn, libvirt.VIR_MIGRATE_LIVE, None, None, 0)
            if target_dom == None:
                raise
            ansiiprint.echo('Successfully migrated VM', '{}:'.format(self.domuuid), 'o')

        except:
            dest_lv_conn.close()
            return 1

        dest_lv_conn.close()
        return 0

    # Migrate the VM to a target host
    def migrate_vm(self):
        self.inmigrate = True
        ansiiprint.echo('Migrating VM to hypervisor "{}"'.format(self.hypervisor), '{}:'.format(self.domuuid), 'i')

        try:
            migrate_ret = self.live_migrate_vm(self.hypervisor)
        except:
            migrate_ret = 0

        if migrate_ret != 0:
            ansiiprint.echo('Could not live migrate VM; shutting down to migrate instead', '{}:'.format(self.domuuid), 'e')
            self.shutdown_vm()
            time.sleep(1)
        else:
            self.removeDomainFromList()
            time.sleep(1)

        zkhandler.writedata(self.zk_conn, { '/domains/{}/state'.format(self.domuuid): 'start' })
        self.inmigrate = False

    # Receive the migration from another host (wait until VM is running)
    def receive_migrate(self):
        self.inreceive = True
        ansiiprint.echo('Receiving migration', '{}:'.format(self.domuuid), 'i')
        while True:
            time.sleep(0.5)
            self.state = zkhandler.readdata(self.zk_conn, '/domains/{}/state'.format(self.domuuid))
            self.dom = self.lookupByUUID(self.domuuid)

            if self.dom == None and self.state == 'migrate':
                continue

            if self.state != 'migrate':
                break

            try:
                if self.dom.state()[0] == libvirt.VIR_DOMAIN_RUNNING:
                    break
            except:
                continue

        try:
            dom_state = self.dom.state()[0]
        except AttributeError:
            dom_state = None

        if dom_state == libvirt.VIR_DOMAIN_RUNNING:
            self.addDomainToList()
            ansiiprint.echo('Successfully received migrated VM', '{}:'.format(self.domuuid), 'o')
        else:
            ansiiprint.echo('Failed to receive migrated VM', '{}:'.format(self.domuuid), 'e')

        self.inreceive = False

    #
    # Main function to manage a VM (taking only self)
    #
    def manage_vm_state(self):
        # Give ourselves a bit of leeway time
        time.sleep(0.2)

        # Get the current values from zookeeper (don't rely on the watch)
        self.state = zkhandler.readdata(self.zk_conn, '/domains/{}/state'.format(self.domuuid))
        self.hypervisor = zkhandler.readdata(self.zk_conn, '/domains/{}/hypervisor'.format(self.domuuid))

        # Check the current state of the VM
        try:
            if self.dom != None:
                running, reason = self.dom.state()
            else:
                raise
        except:
            running = libvirt.VIR_DOMAIN_NOSTATE

        ansiiprint.echo('VM state change for "{}": {} {}'.format(self.domuuid, self.state, self.hypervisor), '', 'i')

        #######################
        # Handle state changes
        #######################
        # Valid states are:
        #   start
        #   migrate
        #   restart
        #   shutdown
        #   stop

        # Conditional pass one - Are we already performing an action
        if self.instart == False \
        and self.inrestart == False \
        and self.inmigrate == False \
        and self.inreceive == False \
        and self.inshutdown == False \
        and self.instop == False:
            # Conditional pass two - Is this VM configured to run on this hypervisor
            if self.hypervisor == self.thishypervisor.name:
                # Conditional pass three - Is this VM currently running on this hypervisor
                if running == libvirt.VIR_DOMAIN_RUNNING:
                    # VM is already running and should be
                    if self.state == "start":
                        self.addDomainToList()
                    # VM is already running and should be but stuck in migrate state
                    elif self.state == "migrate":
                        zkhandler.writedata(self.zk_conn, { '/domains/{}/state'.format(self.domuuid): 'start' })
                        self.addDomainToList()
                    # VM should be restarted
                    elif self.state == "restart":
                        self.restart_vm()
                    # VM should be shut down
                    elif self.state == "shutdown":
                        self.shutdown_vm()
                    # VM should be stopped
                    elif self.state == "stop":
                        self.stop_vm()
                else:
                    # VM should be started
                    if self.state == "start":
                        self.start_vm()
                    # VM should be migrated to this hypervisor
                    elif self.state == "migrate":
                        self.receive_migrate()
                    # VM should be restarted (i.e. started since it isn't running)
                    if self.state == "restart":
                        zkhandler.writedata(self.zk_conn, { '/domains/{}/state'.format(self.domuuid): 'start' })
                    # VM should be shut down; ensure it's gone from this node's domain_list
                    elif self.state == "shutdown":
                        self.removeDomainFromList()
                    # VM should be stoped; ensure it's gone from this node's domain_list
                    elif self.state == "stop":
                        self.removeDomainFromList()
                        
            else:
                # Conditional pass three - Is this VM currently running on this hypervisor
                if running == libvirt.VIR_DOMAIN_RUNNING:
                    # VM should be migrated away from this hypervisor
                    if self.state == "migrate":
                        self.migrate_vm()
                    # VM should be terminated
                    else:
                        self.terminate_vm()


    # This function is a wrapper for libvirt.lookupByUUID which fixes some problems
    # 1. Takes a text UUID and handles converting it to bytes
    # 2. Try's it and returns a sensible value if not
    def lookupByUUID(self, tuuid):
        lv_conn = None
        dom = None
        libvirt_name = "qemu:///system"
    
        # Convert the text UUID to bytes
        buuid = uuid.UUID(tuuid).bytes
    
        # Try
        try:
            # Open a libvirt connection
            lv_conn = libvirt.open(libvirt_name)
            if lv_conn == None:
                ansiiprint.echo('Failed to open local libvirt connection', '{}:'.format(self.domuuid), 'e')
                return dom
        
            # Lookup the UUID
            dom = lv_conn.lookupByUUID(buuid)
    
        # Fail
        except:
            pass
    
        # After everything
        finally:
            # Close the libvirt connection
            if lv_conn != None:
                lv_conn.close()
    
        # Return the dom object (or None)
        return dom