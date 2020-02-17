#!/usr/bin/env python3

# VMInstance.py - Class implementing a PVC virtual machine in pvcnoded
# Part of the Parallel Virtual Cluster (PVC) system
#
#    Copyright (C) 2018-2020 Joshua M. Boniface <joshua@boniface.me>
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
import json

import pvcnoded.log as log
import pvcnoded.zkhandler as zkhandler
import pvcnoded.common as common

import pvcnoded.VMConsoleWatcherInstance as VMConsoleWatcherInstance

def flush_locks(zk_conn, logger, dom_uuid):
    logger.out('Flushing RBD locks for VM "{}"'.format(dom_uuid), state='i')
    # Get the list of RBD images
    rbd_list = zkhandler.readdata(zk_conn, '/domains/{}/rbdlist'.format(dom_uuid)).split(',')
    for rbd in rbd_list:
        # Check if a lock exists
        lock_list_retcode, lock_list_stdout, lock_list_stderr = common.run_os_command('rbd lock list --format json {}'.format(rbd))
        if lock_list_retcode != 0:
            logger.out('Failed to obtain lock list for volume "{}"'.format(rbd), state='e')
            continue

        try:
            lock_list = json.loads(lock_list_stdout)
        except Exception as e:
            logger.out('Failed to parse lock list for volume "{}": {}'.format(rbd, e), state='e')
            continue

        # If there's at least one lock
        if lock_list:
            # Loop through the locks
            for lock, detail in lock_list.items():
                # Free the lock
                lock_remove_retcode, lock_remove_stdout, lock_remove_stderr = common.run_os_command('rbd lock remove {} "{}" "{}"'.format(rbd, lock, detail['locker']))
                if lock_remove_retcode != 0:
                    logger.out('Failed to free RBD lock "{}" on volume "{}"\n{}'.format(lock, rbd, lock_remove_stderr), state='e')
                    continue
                logger.out('Freed RBD lock "{}" on volume "{}"'.format(lock, rbd), state='o')

    return True

# Primary command function
def run_command(zk_conn, logger, this_node, data):
    # Get the command and args
    command, args = data.split()

    # Flushing VM RBD locks
    if command == 'flush_locks':
        dom_uuid = args
        if this_node.router_state == 'primary':
            # Lock the command queue
            zk_lock = zkhandler.writelock(zk_conn, '/cmd/domains')
            with zk_lock:
                # Add the OSD
                result = flush_locks(zk_conn, logger, dom_uuid)
                # Command succeeded
                if result:
                    # Update the command queue
                    zkhandler.writedata(zk_conn, {'/cmd/domains': 'success-{}'.format(data)})
                # Command failed
                else:
                    # Update the command queue
                    zkhandler.writedata(zk_conn, {'/cmd/domains': 'failure-{}'.format(data)})
                # Wait 1 seconds before we free the lock, to ensure the client hits the lock
                time.sleep(1)

class VMInstance(object):
    # Initialization function
    def __init__(self, domuuid, zk_conn, config, logger, this_node):
        # Passed-in variables on creation
        self.domuuid = domuuid
        self.zk_conn = zk_conn
        self.config = config
        self.logger = logger
        self.this_node = this_node

        # Get data from zookeeper
        self.domname = zkhandler.readdata(zk_conn, '/domains/{}'.format(domuuid))
        self.state = zkhandler.readdata(self.zk_conn, '/domains/{}/state'.format(self.domuuid))
        self.node = zkhandler.readdata(self.zk_conn, '/domains/{}/node'.format(self.domuuid))
        try:
            self.pinpolicy = zkhandler.readdata(self.zk_conn, '/domains/{}/pinpolicy'.format(self.domuuid))
        except:
            self.pinpolicy = "None"

        # These will all be set later
        self.instart = False
        self.inrestart = False
        self.inmigrate = False
        self.inreceive = False
        self.inshutdown = False
        self.instop = False

        # Libvirt domuuid
        self.dom = self.lookupByUUID(self.domuuid)

        # Log watcher instance
        self.console_log_instance = VMConsoleWatcherInstance.VMConsoleWatcherInstance(self.domuuid, self.domname, self.zk_conn, self.config, self.logger, self.this_node)

        # Watch for changes to the state field in Zookeeper
        @self.zk_conn.DataWatch('/domains/{}/state'.format(self.domuuid))
        def watch_state(data, stat, event=""):
            if event and event.type == 'DELETED':
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            # Perform a management command
            self.logger.out('Updating state of VM {}'.format(self.domuuid), state='i')
            state_thread = threading.Thread(target=self.manage_vm_state, args=(), kwargs={})
            state_thread.start()

    # Get data functions
    def getstate(self):
        return self.state

    def getnode(self):
        return self.node

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
        if not self.domuuid in self.this_node.domain_list:
            try:
                # Add the domain to the domain_list array
                self.this_node.domain_list.append(self.domuuid)
                # Push the change up to Zookeeper
                zkhandler.writedata(self.zk_conn, { '/nodes/{}/runningdomains'.format(self.this_node.name): ' '.join(self.this_node.domain_list) })
            except Exception as e:
                self.logger.out('Error adding domain to list: {}'.format(e), state='e')

    def removeDomainFromList(self):
        if self.domuuid in self.this_node.domain_list:
            try:
                # Remove the domain from the domain_list array
                self.this_node.domain_list.remove(self.domuuid)
                # Push the change up to Zookeeper
                zkhandler.writedata(self.zk_conn, { '/nodes/{}/runningdomains'.format(self.this_node.name): ' '.join(self.this_node.domain_list) })
            except Exception as e:
                self.logger.out('Error removing domain from list: {}'.format(e), state='e')

    # Start up the VM
    def start_vm(self):
        # Start the log watcher
        self.console_log_instance.start()

        self.logger.out('Starting VM', state='i', prefix='Domain {}:'.format(self.domuuid))
        self.instart = True

        # Start up a new Libvirt connection
        libvirt_name = "qemu:///system"
        lv_conn = libvirt.open(libvirt_name)
        if lv_conn == None:
            self.logger.out('Failed to open local libvirt connection', state='e', prefix='Domain {}:'.format(self.domuuid))
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
                self.logger.out('Successfully started VM', state='o', prefix='Domain {}:'.format(self.domuuid))
                self.dom = dom
                zkhandler.writedata(self.zk_conn, { '/domains/{}/failedreason'.format(self.domuuid): '' })
            except libvirt.libvirtError as e:
                self.logger.out('Failed to create VM', state='e', prefix='Domain {}:'.format(self.domuuid))
                zkhandler.writedata(self.zk_conn, { '/domains/{}/state'.format(self.domuuid): 'fail' })
                zkhandler.writedata(self.zk_conn, { '/domains/{}/failedreason'.format(self.domuuid): str(e) })
                self.dom = None

        lv_conn.close()

        self.instart = False

    # Restart the VM
    def restart_vm(self):
        self.logger.out('Restarting VM', state='i', prefix='Domain {}:'.format(self.domuuid))
        self.inrestart = True

        # Start up a new Libvirt connection
        libvirt_name = "qemu:///system"
        lv_conn = libvirt.open(libvirt_name)
        if lv_conn == None:
            self.logger.out('Failed to open local libvirt connection', state='e', prefix='Domain {}:'.format(self.domuuid))
            self.inrestart = False
            return

        self.shutdown_vm()
        time.sleep(0.2)
        self.start_vm()
        self.addDomainToList()

        zkhandler.writedata(self.zk_conn, { '/domains/{}/state'.format(self.domuuid): 'start' })
        lv_conn.close()
        self.inrestart = False

    # Stop the VM forcibly without updating state
    def terminate_vm(self):
        self.logger.out('Terminating VM', state='i', prefix='Domain {}:'.format(self.domuuid))
        self.instop = True
        try:
            self.dom.destroy()
        except AttributeError:
            self.logger.out('Failed to terminate VM', state='e', prefix='Domain {}:'.format(self.domuuid))
        self.removeDomainFromList()
        self.logger.out('Successfully terminated VM', state='o', prefix='Domain {}:'.format(self.domuuid))
        self.dom = None
        self.instop = False

        # Stop the log watcher
        self.console_log_instance.stop()

    # Stop the VM forcibly
    def stop_vm(self):
        self.logger.out('Forcibly stopping VM', state='i', prefix='Domain {}:'.format(self.domuuid))
        self.instop = True
        try:
            self.dom.destroy()
        except AttributeError:
            self.logger.out('Failed to stop VM', state='e', prefix='Domain {}:'.format(self.domuuid))
        self.removeDomainFromList()

        if self.inrestart == False:
            zkhandler.writedata(self.zk_conn, { '/domains/{}/state'.format(self.domuuid): 'stop' })

        self.logger.out('Successfully stopped VM', state='o', prefix='Domain {}:'.format(self.domuuid))
        self.dom = None
        self.instop = False

        # Stop the log watcher
        self.console_log_instance.stop()

    # Shutdown the VM gracefully
    def shutdown_vm(self):
        self.logger.out('Gracefully stopping VM', state='i', prefix='Domain {}:'.format(self.domuuid))
        is_aborted = False
        self.inshutdown = True
        self.dom.shutdown()
        tick = 0
        while True:
            tick += 2
            time.sleep(2)

            # Abort shutdown if the state changes to start
            current_state = zkhandler.readdata(self.zk_conn, '/domains/{}/state'.format(self.domuuid))
            if current_state not in ['shutdown', 'restart']:
                self.logger.out('Aborting VM shutdown due to state change', state='i', prefix='Domain {}:'.format(self.domuuid))
                is_aborted = True
                break

            try:
                lvdomstate = self.dom.state()[0]
            except:
                lvdomstate = None

            if lvdomstate != libvirt.VIR_DOMAIN_RUNNING:
                self.removeDomainFromList()
                zkhandler.writedata(self.zk_conn, { '/domains/{}/state'.format(self.domuuid): 'stop' })
                self.logger.out('Successfully shutdown VM', state='o', prefix='Domain {}:'.format(self.domuuid))
                self.dom = None
                # Stop the log watcher
                self.console_log_instance.stop()
                break

            # HARDCODE: 90s is a reasonable amount of time for any operating system to shut down cleanly
            if tick >= 90:
                self.logger.out('Shutdown timeout expired', state='e', prefix='Domain {}:'.format(self.domuuid))
                zkhandler.writedata(self.zk_conn, { '/domains/{}/state'.format(self.domuuid): 'stop' })
                break

        self.inshutdown = False

        if is_aborted:
            self.manage_vm_state()

        if self.inrestart:
            # Wait to prevent race conditions
            time.sleep(1)
            zkhandler.writedata(self.zk_conn, { '/domains/{}/state'.format(self.domuuid): 'start' })

    def live_migrate_vm(self):
        dest_lv = 'qemu+tcp://{}.{}/system'.format(self.node, self.config['cluster_domain'])
        dest_tcp = 'tcp://{}.{}'.format(self.node, self.config['cluster_domain'])
        try:
            # Open a connection to the destination
            dest_lv_conn = libvirt.open(dest_lv)
            if not dest_lv_conn:
                raise
        except:
            self.logger.out('Failed to open connection to {}; aborting live migration.'.format(dest_lv), state='e', prefix='Domain {}:'.format(self.domuuid))
            return False

        try:
            # Send the live migration; force the destination URI to ensure we transit over the cluster network
            target_dom = self.dom.migrate(dest_lv_conn, libvirt.VIR_MIGRATE_LIVE, None, dest_tcp, 0)
            if not target_dom:
                raise
        except Exception as e:
            self.logger.out('Failed to send VM to {} - aborting live migration; error: {}'.format(dest_lv, e), state='e', prefix='Domain {}:'.format(self.domuuid))
            dest_lv_conn.close()
            return False

        self.logger.out('Successfully migrated VM', state='o', prefix='Domain {}:'.format(self.domuuid))
        dest_lv_conn.close()
        return True

    # Migrate the VM to a target host
    def migrate_vm(self):
        self.inmigrate = True
        self.logger.out('Migrating VM to node "{}"'.format(self.node), state='i', prefix='Domain {}:'.format(self.domuuid))

        migrate_ret = self.live_migrate_vm()
        if not migrate_ret:
            self.logger.out('Could not live migrate VM; shutting down to migrate instead', state='e', prefix='Domain {}:'.format(self.domuuid))
            zkhandler.writedata(self.zk_conn, { '/domains/{}/state'.format(self.domuuid): 'shutdown' })
        else:
            self.removeDomainFromList()
            # Stop the log watcher
            self.console_log_instance.stop()

        self.inmigrate = False

    # Receive the migration from another host (wait until VM is running)
    def receive_migrate(self):
        self.inreceive = True
        live_receive = True
        tick = 0
        self.logger.out('Receiving migration', state='i', prefix='Domain {}:'.format(self.domuuid))
        while True:
            # Wait 1 second and increment the tick
            time.sleep(1)
            tick += 1

            # Get zookeeper state and look for the VM in the local libvirt database
            self.state = zkhandler.readdata(self.zk_conn, '/domains/{}/state'.format(self.domuuid))
            self.dom = self.lookupByUUID(self.domuuid)

            # If the dom is found
            if self.dom:
                lvdomstate = self.dom.state()[0]
                if lvdomstate == libvirt.VIR_DOMAIN_RUNNING:
                    # VM has been received and started
                    self.addDomainToList()
                    zkhandler.writedata(self.zk_conn, { '/domains/{}/state'.format(self.domuuid): 'start' })
                    self.logger.out('Successfully received migrated VM', state='o', prefix='Domain {}:'.format(self.domuuid))
                    break
                else:
                    # If the state is no longer migrate
                    if self.state != 'migrate':
                        # The receive was aborted before it timed out or was completed
                        self.logger.out('Receive aborted via state change', state='w', prefix='Domain {}:'.format(self.domuuid))
                        break
            # If the dom is not found
            else:
                # If the state is changed to shutdown or stop
                if self.state == 'shutdown' or self.state == 'stop':
                    # The receive failed on the remote end, and VM is being shut down instead
                    live_receive = False
                    self.logger.out('Send failed on remote end', state='w', prefix='Domain {}:'.format(self.domuuid))
                    break

            # If we've already been waiting 90s for a receive
            # HARDCODE: 90s should be plenty of time for even extremely large VMs on reasonable networks
            if tick > 90:
                # The receive timed out
                zkhandler.writedata(self.zk_conn, { '/domains/{}/state'.format(self.domuuid): 'fail' })
                self.logger.out('Receive timed out without state change', state='e', prefix='Domain {}:'.format(self.domuuid))
                break

        # We are waiting on a shutdown
        if not live_receive:
            tick = 0
            self.logger.out('Waiting for VM to shut down on remote end', state='i', prefix='Domain {}:'.format(self.domuuid))
            while True:
                # Wait 1 second and increment the tick
                time.sleep(1)
                tick += 1

                # Get zookeeper state and look for the VM in the local libvirt database
                self.state = zkhandler.readdata(self.zk_conn, '/domains/{}/state'.format(self.domuuid))

                # If the VM has stopped
                if self.state == 'stop':
                    # Wait one more second to avoid race conditions
                    time.sleep(1)
                    # Start the VM up
                    zkhandler.writedata(self.zk_conn, { '/domains/{}/state'.format(self.domuuid): 'start' })
                    break

                # If we've already been waiting 120s for a shutdown
                # HARDCODE: The remote timeout is 90s, so an extra 30s of buffer
                if tick > 120:
                    # The shutdown timed out; something is very amiss, so switch state to fail and abort
                    zkhandler.writedata(self.zk_conn, {
                       '/domains/{}/state'.format(self.domuuid): 'fail',
                       '/domains/{}/failedreason'.format(self.domuuid): 'Timeout waiting for migrate or shutdown'
                    })
                    self.logger.out('Shutdown timed out without state change', state='e', prefix='Domain {}:'.format(self.domuuid))
                    break

        self.inreceive = False

    #
    # Main function to manage a VM (taking only self)
    #
    def manage_vm_state(self):
        # Update the current values from zookeeper
        self.state = zkhandler.readdata(self.zk_conn, '/domains/{}/state'.format(self.domuuid))
        self.node = zkhandler.readdata(self.zk_conn, '/domains/{}/node'.format(self.domuuid))

        # Check the current state of the VM
        try:
            if self.dom != None:
                running, reason = self.dom.state()
            else:
                raise
        except:
            running = libvirt.VIR_DOMAIN_NOSTATE

        self.logger.out('VM state change for "{}": {} {}'.format(self.domuuid, self.state, self.node), state='i')

        #######################
        # Handle state changes
        #######################
        # Valid states are:
        #   start
        #   migrate
        #   restart
        #   shutdown
        #   stop
        # States we don't (need to) handle are:
        #   disable
        #   provision

        # Conditional pass one - Are we already performing an action
        if self.instart == False \
        and self.inrestart == False \
        and self.inmigrate == False \
        and self.inreceive == False \
        and self.inshutdown == False \
        and self.instop == False:
            # Conditional pass two - Is this VM configured to run on this node
            if self.node == self.this_node.name:
                # Conditional pass three - Is this VM currently running on this node
                if running == libvirt.VIR_DOMAIN_RUNNING:
                    # VM is already running and should be
                    if self.state == "start":
                        # Start the log watcher
                        self.console_log_instance.start()
                        # Add domain to running list
                        self.addDomainToList()
                    # VM is already running and should be but stuck in migrate state
                    elif self.state == "migrate":
                        # Start the log watcher
                        self.console_log_instance.start()
                        zkhandler.writedata(self.zk_conn, { '/domains/{}/state'.format(self.domuuid): 'start' })
                        # Add domain to running list
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
                        # Start the domain
                        self.start_vm()
                    # VM should be migrated to this node
                    elif self.state == "migrate":
                        # Receive the migration
                        self.receive_migrate()
                    # VM should be restarted (i.e. started since it isn't running)
                    if self.state == "restart":
                        zkhandler.writedata(self.zk_conn, { '/domains/{}/state'.format(self.domuuid): 'start' })
                    # VM should be shut down; ensure it's gone from this node's domain_list
                    elif self.state == "shutdown":
                        self.removeDomainFromList()
                        # Stop the log watcher
                        self.console_log_instance.stop()
                    # VM should be stoped; ensure it's gone from this node's domain_list
                    elif self.state == "stop":
                        self.removeDomainFromList()
                        # Stop the log watcher
                        self.console_log_instance.stop()

            else:
                # Conditional pass three - Is this VM currently running on this node
                if running == libvirt.VIR_DOMAIN_RUNNING:
                    # VM should be migrated away from this node
                    if self.state == "migrate":
                        self.migrate_vm()
                    # VM should be shutdown gracefully
                    elif self.state == 'shutdown':
                        self.shutdown_vm()
                    # VM should be forcibly terminated
                    else:
                        self.terminate_vm()


    # This function is a wrapper for libvirt.lookupByUUID which fixes some problems
    # 1. Takes a text UUID and handles converting it to bytes
    # 2. Try's it and returns a sensible value if not
    def lookupByUUID(self, tuuid):
        # Don't do anything if the VM shouldn't live on this node
        if self.node != self.this_node.name:
            return None

        lv_conn = None
        libvirt_name = "qemu:///system"

        # Convert the text UUID to bytes
        buuid = uuid.UUID(tuuid).bytes

        # Try
        try:
            # Open a libvirt connection
            lv_conn = libvirt.open(libvirt_name)
            if lv_conn == None:
                self.logger.out('Failed to open local libvirt connection', state='e', prefix='Domain {}:'.format(self.domuuid))
                return None

            # Lookup the UUID
            dom = lv_conn.lookupByUUID(buuid)

        # Fail
        except:
            dom = None

        # After everything
        finally:
            # Close the libvirt connection
            if lv_conn != None:
                lv_conn.close()

        # Return the dom object (or None)
        return dom