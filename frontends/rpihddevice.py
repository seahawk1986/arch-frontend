#!/usr/bin/python3
#import dbus
#from dbus.mainloop.glib import DBusGMainLoop
#dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
import dbus
import logging
from frontends.base import vdrFrontend
import os


class Rpihddevice(vdrFrontend):
    def __init__(self, main, dbus2vdr, name="rpihddevice"):
        super().__init__(main, dbus2vdr)

    def attach(self, options=None):
        try:
            self.main.dbus2vdr.Devices.request_primary_by_name(
                'rpihddevice')
        except Exception as error:
            logging.exception(error)
            return False

    def detach(self):
        try:
            self.main.dbus2vdr.Devices.RequestPrimary(
                self.main.dbus2vdr.Devices.GetNullDevice())
        except dbus.exceptions.DBusException as error:
            logging.exception(error)
            return False

    def resume(self):
        self.attach()

    def status(self):
        current_primary_device = self.main.dbus2vdr.Devices.GetPrimary()[-1]
        if current_primary_device == 'rpihddevice':
            state = 1
        else:
            state = 0
        logging.debug("rpihddevice: got status: %d", state)
        return state
