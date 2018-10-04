#!/usr/bin/env python3

# common.py - PVC daemon function library, common fuctions
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

import subprocess
import threading
import signal

import daemon_lib.ansiiprint as ansiiprint

class OSDaemon(object):
    def __init__(self, command, environment):
        self.proc = subprocess.Popen(
            command,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def signal(self, sent_signal):
        signal_map = {
            'hup': signal.SIGHUP,
            'int': signal.SIGINT
        }
        self.proc.send_signal(signal_map[sent_signal])

def run_os_daemon(command_string, background=False, environment=None, return_pid=False):
    command = command_string.split()
    daemon = OSDaemon(command, environment)
    return daemon

# Run a oneshot command, optionally without blocking
def run_os_command(command_string, background=False, environment=None):
    command = command_string.split()
    if background:
        def runcmd():
            subprocess.Popen(
                command,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        thread = threading.Thread(target=runcmd, args=())
        thread.start()
        return 0
    else:
        command_output = subprocess.Popen(
            command,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        return command_output.returncode
