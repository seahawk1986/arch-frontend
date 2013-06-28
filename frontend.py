#!/usr/bin/python3
# Alexander Grothe, June 2013
'''
    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.
'''

import configparser
import datetime
from gi.repository import GObject
import dbus
import dbus.service
from dbus.mainloop.glib import DBusGMainLoop
dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
import itertools
import logging
from optparse import OptionParser
import os
import signal
import struct
import subprocess
import sys
from pydbus2vdr.dbus2vdr import *
from frontends.base import *
from frontends.Softhddevice import *
from frontends.xbmc import XBMC


class Main(dbus.service.Object):
    def __init__(self, options):
        self.options = options
        self.bus = dbus.SystemBus()
        bus_name = dbus.service.BusName('de.yavdr.frontend', bus=self.bus)
        dbus.service.Object.__init__(self, bus_name, '/frontend')
        self.settings = Settings(self.options.config)
        logging.debug(u"read settings from {0}".format(self.options.config))
        logging.debug(u"starting frontend script")
        self.dbus2vdr = DBus2VDR(dbus.SystemBus(), instance=0)
        # track vdr status changes
        self.vdrStatusSignal()
        self.vdrDBusSignal()
        self.wakeup = self.checkWakeup()
        # init Frontends
        self.frontends = {}
        self.frontends['vdr'] = self.get_vdrFrontend()
        self.frontends['xbmc'] = self.get_xbmcFrontend()
        self.current = None
        for frontend, obj in self.frontends.items():
            if not obj:
                logging.warning("using dummy frontend")
                self.frontends[frontend] = vdrFrontend(self, 'dummy')
        self.switch = itertools.cycle(self.frontends.keys())
        while not next(self.switch) == self.settings.frontend:
            pass
        logging.debug("set main frontend to {0}".format(self.settings.frontend))
        self.startup()

    def startup(self):
        logging.debug("running startup()")
        if self.settings.attach == 'never' or (
                        self.settings.attach == 'auto' and not self.wakeup):
            self.setBackground('detached')
            return
        if self.current == 'xbmc' or (
                        self.settings.frontend == 'xbmc' and not self.current):
            self.frontends['xbmc'].attach()
            self.current = 'xbmc'
        elif self.current == 'vdr' or (
                        self.settings.frontend == 'vdr' and not self.current):
            # check if vdr is ready
            if self.dbus2vdr.checkVDRstatus():
                self.frontends['vdr'].resume()
                self.current = 'vdr'
                logging.debug("activated vdr frontend")
            else:
                logging.debug("vdr not ready")
                return

    def checkWakeup(self):
        """Check if started manually (True) or for a Timer or Plugin (False)"""
        # TODO include check for external wakeup sources
        return self.dbus2vdr.Shutdown.ManualStart()

    @dbus.service.method('de.yavdr.frontend', out_signature='i')
    def checkFrontend(self):
        return self.frontends[self.current].status()



    @dbus.service.method('de.yavdr.frontend', out_signature='s')
    def switchFrontend(self):
        if  self.frontends[self.current].status() == 2:
            self.frontends[self.current].resume()
        old = self.current
        self.current = next(self.switch)
        logging.debug("next frontend is {0}".format(self.current))
        self.frontends[old].detach()
        self.frontends[self.current].attach()
        return self.getFrontend()

    @dbus.service.method('de.yavdr.frontend', out_signature='s')
    def getFrontend(self):
        m = "current frontend is {0}".format(self.frontends[self.current].name)
        return m

    @dbus.service.method('de.yavdr.frontend', in_signature='s',
                         out_signature='b')
    def attach(self, options=None):
        return self.frontends[self.current].attach(options)

    @dbus.service.method('de.yavdr.frontend', out_signature='b')
    def detach(self):
        return self.frontends[self.current].detach()

    @dbus.service.method('de.yavdr.frontend', in_signature='s',
                         out_signature='b')
    def setBackground(self, background):
        if background == 'detached':
            path = self.settings.get_setting('Frontend', 'bg_detached')
        elif background == 'attached':
            path = self.settings.get_setting('Frontend', 'bg_attached')
        #TODO: set background

    def inhibit(self, what='sleep:shutdown', who='First Base', why="left field",
                                                                mode="block"):
        try:
            a = self.bus.get_object('org.freedesktop.login1', '/org/freedesktop/login1')
            interface = 'org.freedesktop.login1.Manager'
            fd = a.Inhibit(what, who, why, mode, dbus_interface=interface)
            return fd
        except Exception as error:
            logging.exception(error)
            logging.warning("could not set inhibitor lock")

    def get_vdrFrontend(self):
        #plugins = self.dbus2vdr.Plugins.List()
        if self.dbus2vdr.Plugins.check_plugin('softhddevice'):
            return Softhddevice(self, 'softhddevice')
        elif 'xineliboutput' in plugins and self.xineliboutput:
            return VDRsxfe(self, 'vdr-sxfe')
        elif 'xine' in plugins and self.xine:
            self.frontend = Xine(self, 'xine')
        else:
            logging.warning("no vdr frontend found")
            return None
        logging.debug("primary frontend is {0}".format(self.frontend.name))

    def get_xbmcFrontend(self):
        if self.settings.xbmc:
            return XBMC(self)
        else:
            logging.warning("no XBMC configuration found")
            return None

    def vdrStatusSignal(self):
        self.bus.add_signal_receiver(self.dbus2vdr_signal,
                                             bus_name=self.dbus2vdr.vdr_obj,
                                             sender_keyword='sender',
                                             member_keyword='member',
                                             interface_keyword='interface',
                                             path_keyword='path',
                                            )

    def dbus2vdr_signal(self, *args, **kwargs):
        logging.debug("got signal %s", kwargs['member'])
        logging.debug(args)
        if kwargs['member'] == "Ready":
            logging.debug("vdr ready")
            self.startup()
        elif kwargs['member'] == "Stop":
            logging.debug("vdr stopping")
        elif kwargs['member'] == "Start":
            logging.debug("vdr starting")

    def vdrDBusSignal(self):
        self.bus.watch_name_owner(self.dbus2vdr.vdr_obj, self.name_owner_changed)

    def name_owner_changed(self, *args, **kwargs):
        if len(args[0]) == 0:
            logging.debug("vdr has no dbus name ownership")
        else:
            logging.debug("vdr has dbus name ownership")
        logging.debug(args)

    def set_toggle(self, target):
        while not next(self.switch) == self.target:
             pass

    def sigint(self, signal, frame, **args):
        logging.info("got %s" % signal)
        self.frontends[self.current].detach()
        #loop.quit()
        sys.exit(0)


class Settings:
    def __init__(self, config):
        self.config = config
        self.init_parser()

    def get_setting(self, category, setting, default):
        if self.parser.has_option(category, setting):
            return self.parser.get(category, setting)
        else:
            return default

    def get_settingb(self, category, setting, default):
        if self.parser.has_option(category, setting):
            return self.parser.getboolean(category, setting)
        else:
            return default

    def init_parser(self, config=None):
        self.parser = configparser.SafeConfigParser(delimiters=(":", "="),
                                                    interpolation=None
                                                    )
        self.parser.optionxform = str
        with open(self.config, 'r', encoding='utf-8') as f:
            self.parser.readfp(f)
        self.log2file = self.get_settingb('Logging', 'use_file', False)
        self.logfile = self.get_setting('Logging', 'logfile', "/tmp/frontend.log")
        self.loglevel = self.get_setting('Logging', 'loglevel', "DEBUG")
        if self.log2file:
            logging.basicConfig(
                    filename=self.logfile,
                    level=getattr(logging,self.loglevel),
                    format='%(asctime)-15s %(levelname)-6s %(message)s',
            )
        else:
            logging.basicConfig(
                    level=getattr(logging,self.loglevel),
                    format='%(asctime)-15s %(levelname)-6s %(message)s',
            )
        # frontend settings: primary: vdr|xbmc
        self.frontend = self.get_setting('Frontend', 'frontend', "vdr")
        self.xine = self.get_setting("Frontend", 'xine', None)
        self.xineliboutput = self.get_setting('Frontend', 'xineliboutput', None)
        self.xbmc = self.get_setting('XBMC', 'xbmc', None)
        # attach always|never|auto
        self.attach = self.get_setting('Frontend', 'attach', 'always')


class Options():
    def __init__(self):
        self.parser = OptionParser()
        self.parser.add_option("-c", "--config",
                               dest="config",
                               default='/etc/conf.d/frontend.conf',
                               metavar="CONFIG_FILE")

    def get_options(self):
        (options, args) = self.parser.parse_args()
        return options



if __name__ == '__main__':
    DBusGMainLoop(set_as_default=True)
    options = Options()
    main = Main(options.get_options())
    signal.signal(signal.SIGTERM, main.sigint)
    signal.signal(signal.SIGINT, main.sigint)
    loop = GObject.MainLoop()
    loop.run()
