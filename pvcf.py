#!/usr/bin/env python3

import os, sys, libvirt, uuid

#
# Generic function helpers for PVC
#

# > lookupByUUID
# This function is a wrapper for libvirt.lookupByUUID which fixes some problems
# 1. Takes a text UUID and handles converting it to bytes
# 2. Try's it and returns a sensible value if not
def lookupByUUID(tuuid):
    conn = None
    dom = None
    libvirt_name = "qemu:///system"

    # Convert the text UUID to bytes
    buuid = uuid.UUID(tuuid).bytes

    # Try
    try:
        # Open a libvirt connection
        conn = libvirt.open(libvirt_name)
        if conn == None:
            print('>>> %s - Failed to open local libvirt connection.' % self.domuuid)
            return dom
    
        # Lookup the UUID
        dom = conn.lookupByUUID(buuid)

    # Fail
    except:
        pass

    # After everything
    finally:
        # Close the libvirt connection
        if conn != None:
            conn.close()

    # Return the dom object (or None)
    return dom
