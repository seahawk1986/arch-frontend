#!/usr/bin/python3
# -*- coding: utf-8 -*-
# Alexander Grothe, June 2013
'''
    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 2 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.
'''

import configparser
from gi.repository import GObject
import dbus
import dbus.service
from dbus.mainloop.glib import DBusGMainLoop
dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
import itertools
import logging
from optparse import OptionParser
import os
import time
import signal
import shlex
import subprocess
import sys
from dbus2vdr import DBus2VDR
from frontends.base import vdrFrontend
from frontends.Softhddevice import Softhddevice
from frontends.kodi import KODI
from frontends.xineliboutput import VDRsxfe
from frontends.xine import Xine
from tools.lirc_socket import lircConnection


class Main(dbus.service.Object):
    def __init__(self, options):
        self.options = options
        self.bus = dbus.SystemBus()
        bus_name = dbus.service.BusName('de.yavdr.frontend', bus=self.bus)
        dbus.service.Object.__init__(self, bus_name, '/frontend')
        self.settings = Settings(self.options.config)
        logging.debug("read settings from {0}".format(self.options.config))
        logging.debug("starting frontend script")
        # track vdr status changes
        self.dbus2vdr = DBus2VDR(dbus.SystemBus(), instance=0, watchdog=True)
        # bind function to Signal "Ready"
        self.dbus2vdr.onSignal("Ready", self.onStart)
        # bind function to Signal "Stop"
        self.dbus2vdr.onSignal("Stop", self.onStop)
        self.vdrDBusSignal()
        self.current = None
        self.external = False
        self.vdrStatus = 0
        self.wants_shutdown = False
        self.expect_stop = False
        signal.signal(signal.SIGTERM, self.sigint)
        signal.signal(signal.SIGINT, self.sigint)
        self.lircConnection = lircConnection(self)
        if self.dbus2vdr.checkVDRstatus():
            self.prepare()

    def prepare(self):
        # init Frontends
        self.dbus2vdr = DBus2VDR(dbus.SystemBus(), instance=0)
        self.frontends = {}
        self.frontends['vdr'] = self.get_vdrFrontend()
        self.frontends['kodi'] = self.get_kodiFrontend()
        for frontend, obj in self.frontends.items():
            if not obj:
                logging.warning("using dummy frontend")
                self.frontends[frontend] = vdrFrontend(self, 'dummy')
        self.switch = itertools.cycle(self.frontends.keys())
        while not next(self.switch) == self.settings.frontend:
            pass
        logging.debug("set main frontend to {0}".format(
            self.settings.frontend))
        self.startup()

    def restart(self):
        try:
            self.frontends['vdr'].detach()
        except:
            pass
        self.frontends['vdr'] = self.get_vdrFrontend()
        for frontend, obj in self.frontends.items():
            if not obj:
                logging.warning("using dummy frontend")
                self.frontends[frontend] = vdrFrontend(self, 'dummy')
        self.startup()

    def startup(self):
        self.wakeup = self.checkWakeup()
        logging.debug("running startup()")
        if self.settings.attach == 'never' or (self.settings.attach == 'auto'
                                               and not self.wakeup):
            self.current = self.settings.frontend
            self.setBackground()
            return
        elif self.current == 'kodi' or (self.settings.frontend == 'kodi' and
                                        not self.current):
            self.frontends['kodi'].attach()
            self.current = 'kodi'
            self.dbus2vdr.Remote.Disable()
            logging.debug('startup: frontend is kodi')
        elif self.current == 'vdr' or (self.settings.frontend == 'vdr' and
                                       not self.current):
            # check if vdr is ready
            if self.dbus2vdr.checkVDRstatus():
                self.vdrStatus = 1
                self.frontends['vdr'].resume()
                self.current = 'vdr'
                logging.debug("startup: using vdr frontend %s", self.current)
            else:
                logging.debug("vdr not ready")
                self.vdrStatus = 0
                return

    def checkWakeup(self):
        """Check if started manually (True) or for a Timer or Plugin (False)"""
        # TODO include check for external wakeup sources
        if self.dbus2vdr.checkVDRstatus():

            return self.dbus2vdr.Shutdown.ManualStart()
        else:
            return True

    @dbus.service.method('de.yavdr.frontend', out_signature='i')
    def checkFrontend(self):
        """return status of current frontend"""
        return self.status()

    @dbus.service.method('de.yavdr.frontend', out_signature='b')
    def toggleFrontend(self):
        """toggle between active and inactive frontend"""
        if self.status() == 1:
            self.detach()
        else:
            self.frontends[self.current].resume()
        return True

    @dbus.service.method('de.yavdr.frontend', out_signature='s')
    def switchFrontend(self):
        """switch from vdr frontend to kodi and vice versa"""
        if self.status() == 2:
            self.resume()
        if self.current == 'vdr':
            self.dbus2vdr.Remote.Disable()
        old = self.current
        self.current = next(self.switch)
        logging.debug("next frontend is {0}".format(self.current))
        if self.frontends[old].status():
            self.frontends[old].detach()
        if self.current == "kodi":
            self.attach()
        return self.getFrontend()

    @dbus.service.method('de.yavdr.frontend', out_signature='s')
    def tempDisplay(self):
        """show currently used display"""
        self.setBackground(self.settings.get_setting('Frontend', 'bg_attached',
                                                     None))
        self.settings.update_display(os.environ['DISPLAY'])
        return os.environ['DISPLAY']

    @dbus.service.method('de.yavdr.frontend',
                         in_signature='s',
                         out_signature='b')
    def setDisplay(self, display=None):
        """set DISPLAY varible for internal use"""
        if display:
            os.env['DISPLAY'] = display
            return True
        else:
            return False

    @dbus.service.method('de.yavdr.frontend', out_signature='s')
    def getDisplay(self):
        return os.env['DISPLAY']

    def completeFrontendSwitch(self):
        self.attach()
        if self.current == 'vdr':
            self.dbus2vdr.Remote.Enable()
        if self.wants_shutdown and self.frontends[self.current
                                                  ].name == 'softhddevice':
            self.send_shutdown()
            self.wants_shutdown = False
            self.dbus2vdr.Remote.Enable()
        logging.debug("frontend after switch: %s", self.current)
        return self.getFrontend()

    @dbus.service.method('de.yavdr.frontend', out_signature='s')
    def getFrontend(self):
        """return current frontend"""
        m = "current frontend is {0}".format(
            self.frontends[self.current].name)
        return m

    @dbus.service.method('de.yavdr.frontend', in_signature='s',
                         out_signature='b')
    def attach(self, options=None):
        try:
            GObject.source_remove(self.timer)
        except:
            pass
        self.setBackground(self.settings.get_setting('Frontend', 'bg_attached',
                                                     None))
        if not self.external:
            if self.current:
                return self.frontends[self.current].attach(options)
                return True

    @dbus.service.method('de.yavdr.frontend', out_signature='b')
    def detach(self, set_bg=True, expect_stop=True):
        self.expect_stop = expect_stop
        answer = self.frontends[self.current].detach()
        if set_bg:
            self.setBackground(self.settings.get_setting('Frontend',
                                                         'bg_detached', None))
        return answer

    @dbus.service.method('de.yavdr.frontend', out_signature='b')
    def resume(self):
        if not self.external:
            status = self.frontends[self.current].resume()
            self.dbus2vdr.Remote.Enable()
            self.setBackground()
            return status

    @dbus.service.method('de.yavdr.frontend', out_signature='i')
    def status(self):
        if not self.external and self.current:
            return self.frontends[self.current].status()
        elif not self.current:
            return 0
        else:
            return 3

    @dbus.service.method('de.yavdr.frontend', out_signature='b')
    def begin_external(self):
        self.external = True
        self.detach(set_bg=False)
        snd_free = False
        while not snd_free:
            logging.debug("check if frontend has freed sound device")
            fuser_pid = subprocess.Popen(['fuser', '-v',
                                          '/dev/snd/*p'],
                                         stdout=subprocess.PIPE,
                                         stderr=subprocess.PIPE, shell=True)
            fuser_pid.wait()
            stdout, stderr = fuser_pid.communicate()
            logging.debug("fuser output: %s", stderr)
            if ("kodi") in str(stderr) or str(stderr).endswith("vdr"):
                snd_free = False
                time.sleep(0.25)
            else:
                snd_free = True
                logging.debug('kodi has freed sound device')

        return True

    @dbus.service.method('de.yavdr.frontend', out_signature='b')
    def end_external(self):
        self.external = False
        self.attach()
        return True

    @dbus.service.method('de.yavdr.frontend', out_signature='b')
    def soft_detach(self):
        logging.debug("running soft_detach")
        if self.settings.get_setting('Frontend', 'attach', 'always'
                                     ) in ['auto', 'always']:
            self.detach()
            logging.debug("add timer for send_shutdown")
        self.timer = GObject.timeout_add(300000, self.send_shutdown)
        return False

    @dbus.service.method('de.yavdr.frontend', out_signature='b')
    def init_shutdown(self):
        if self.current == 'xmbc':
            self.detach()
        self.send_shutdown()

    @dbus.service.method('de.yavdr.frontend', out_signature='b')
    def send_shutdown(self, user=False):
        disable_remote = False
        if (self.dbus2vdr.Shutdown.ConfirmShutdown(user)
                and self.check_lifeguard()):
            logging.debug("send 'HitKey POWER' to vdr")
            if not self.dbus2vdr.Remote.Status():
                self.dbus2vdr.Remote.Enable()
                disable_remote = True
            self.dbus2vdr.Remote.HitKey("POWER")
            if disable_remote:
                self.dbus2vdr.Remote.Disable()
        else:
            logging.debug("send_shutdown: VDR not ready to shut down")
        return True

    @dbus.service.method('de.yavdr.frontend', in_signature='ss',
                         out_signature='b')
    def setBackground(self, path=None, display=None):
        status = self.status()
        old_display = None
        if display:
            old_display = os.environ['DISPLAY']
            os.environ['DISPLAY'] = display
        logging.debug("setBackground: status is %s, type is %s" %
                      (status, type(status)))
        if status == 0 and not path:
                path = self.settings.get_setting('Frontend', 'bg_detached',
                                                 None)
        elif status == 1 and not path:
                path = self.settings.get_setting('Frontend', 'bg_attached',
                                                 None)
        logging.debug("Background path is %s" % path)
        if path:
            command = ["/usr/bin/feh", "--bg-fill", path]
            logging.debug("command for setting bg is: %s" % (
                " ".join(command)))
            subprocess.call(command, env=os.environ)
        if old_display:
            os.environ['DISPLAY'] = old_display
        return True

    def inhibit(self, what='sleep:shutdown', who='First Base',
                why="left field", mode="block"):
        try:
            a = self.bus.get_object('org.freedesktop.login1',
                                    '/org/freedesktop/login1')
            interface = 'org.freedesktop.login1.Manager'
            fd = a.Inhibit(what, who, why, mode, dbus_interface=interface)
            return fd
        except Exception as error:
            logging.exception(error)
            logging.warning("could not set inhibitor lock")

    def check_lifeguard(self):
        try:
            if_lifeguard = "org.yavdr.lifeguard"
            lifeguard = self.bus.get_object('org.yavdr.lifeguard',
                                            "/Lifeguard")
            status, text = lifeguard.Check(dbus_interface=if_lifeguard)
            if not status:
                logging.debug("lifeguard-ng is not ready to shutdown")
                return False
        except Exception as error:
            logging.exception(error)
            logging.debug("could not reach lifeguard-ng")
        finally:
            return True

    def get_vdrFrontend(self):
        if self.dbus2vdr.Plugins.check_plugin('softhddevice'):
            frontend = Softhddevice(self, 'softhddevice')
        elif self.dbus2vdr.Plugins.check_plugin('xineliboutput'):
            frontend = VDRsxfe(self, 'vdr-sxfe')
        elif self.dbus2vdr.Plugins.check_plugin('xine'):
            frontend = Xine(self, 'xine')
        else:
            logging.warning("no vdr frontend found")
            frontend = None
        logging.debug("primary frontend is {0}".format(frontend.name))
        return frontend

    def get_kodiFrontend(self):
        if self.settings.kodi and not self.current == 'kodi':
            return KODI(self)
        elif self.current == 'kodi':
            return self.frontends[self.current]
        else:
            logging.warning("no KODI configuration found")
            return None

    def onStart(self, *args, **kwargs):
        print("VDR Ready")
        if self.current == 'kodi':
            self.restart()
        else:
            self.prepare()
        self.vdrStatus == 1

    def onStop(self, *args, **kwargs):
        print("VDR stopped")
        logging.debug("vdr stopping")
        if self.current == 'vdr':
            self.current = None
        self.vdrStatus == 0

    def dbus2vdr_signal(self, *args, **kwargs):
        logging.debug("got signal %s", kwargs['member'])
        logging.debug(args)
        if kwargs['member'] == "Ready":
            logging.debug("vdr ready")
            if self.current == 'kodi':
                self.restart()
            else:
                self.prepare()
        elif kwargs['member'] == "Stop":
            logging.debug("vdr stopping")
            if self.current == 'vdr':
                self.current = None
        elif kwargs['member'] == "Start":
            logging.debug("vdr starting")

    def vdrDBusSignal(self):
        self.bus.watch_name_owner(self.dbus2vdr.vdr_obj,
                                  self.name_owner_changed)

    def name_owner_changed(self, *args, **kwargs):
        if len(args[0]) == 0:
            logging.debug("vdr has no dbus name ownership")
            if self.current == 'vdr':
                self.current = None
            if self.vdrStatus != 0:
                self.onStop()
        else:
            logging.debug("vdr has dbus name ownership")
        logging.debug(args)

    def set_toggle(self, target):
        while not next(self.switch) == self.target:
            pass

    @dbus.service.method('de.yavdr.frontend')
    def quit(self):
        logging.info("quit frontend script")
        self.frontends[self.current].detach()
        self.loop.quit()
        sys.exit()

    def sigint(self, signal, *args, **kwargs):
        logging.info("got %s" % signal)
        self.frontends[self.current].detach()
        time.sleep(1)
        self.loop.quit()
        sys.exit()


class Settings:
    def __init__(self, config):
        self.config = config
        self.init_parser()

    def get_setting(self, category, setting, default):
        return self.parser[category].get(setting, default)

    def get_settingb(self, category, setting, default):
        return self.parser[category].getboolean(setting, default)

    def get_settingi(self, category, setting, default):
        return self.parser[category].getint(setting, default)

    def get_settingf(self, category, setting, default):
        return self.parser[category].getfloat(setting, default)

    def init_parser(self, config=None):
        self.parser = configparser.ConfigParser(delimiters=(":", "="),
                                                    interpolation=None
                                                    )
        self.parser.optionxform = str
        with open(self.config, 'r', encoding='utf-8') as f:
            self.parser.read_file(f)
        self.log2file = self.get_settingb('Logging', 'use_file', False)
        self.logfile = self.get_setting('Logging', 'logfile',
                                        "/tmp/frontend.log")
        self.loglevel = self.get_setting('Logging', 'loglevel', "DEBUG")
        line_format = '%(asctime)-15s %(levelname)-6s %(message)s'
        if self.log2file:
            logging.basicConfig(filename=self.logfile,
                                level=getattr(logging, self.loglevel),
                                format=line_format
                                )
        else:
            logging.basicConfig(level=getattr(logging, self.loglevel),
                                format=line_format
                                )
        # frontend settings: primary: vdr|kodi
        self.frontend = self.get_setting('Frontend', 'frontend', "vdr")
        self.kodi = self.get_setting('KODI', 'kodi', None)
        # attach always|never|auto
        self.attach = self.get_setting('Frontend', 'attach', 'always')
        get_tempdisplay = self.get_setting('Frontend', 'get_tempdisplay',
                                           'dbget vdr.tempdisplay')
        self.get_tempdisplay = shlex.split(get_tempdisplay)
        display = self.get_setting('Frontend', 'DISPLAY', ":0")
        logging.debug(display)
        self.update_display(display)

    def update_display(self, display):
        try:
            tempdisplay = subprocess.check_output(self.get_tempdisplay
                                                  ).decode()
        except:
            tempdisplay = ""
        if len(tempdisplay) > 0:
            logging.debug("got:", display.split(".")[0], tempdisplay)
            os.environ['DISPLAY'] = display.split(".")[0] + tempdisplay
            logging.debug("DISPLAY is", os.environ['DISPLAY'])
        else:
            os.environ['DISPLAY'] = display.split(".")[0]
        logging.debug("DISPLAY: %s", os.environ['DISPLAY'])


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
    global main
    main = Main(options.get_options())
    main.loop = GObject.MainLoop()
    try:
        main.loop.run()
    except KeyboardInterrupt:
        main.sigint("KeyboardInterrupt")
        sys.exit("Good Bye")
