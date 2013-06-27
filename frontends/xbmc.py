#!/usr/bin/python3
import dbus
from dbus.mainloop.glib import DBusGMainLoop
dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
from gi.repository import GObject
import logging
from pydbus2vdr.dbus2vdr import *
import os
import subprocess


class XBMC():
    def __init__(self, main):
        self.main = main
        self.name = 'xbmc'
        os.environ['__GL_SYNC_TO_VBLANK']="1"
        # TODO Display config:
        os.environ['__GL_SYNC_DISPLAY_DEVICE'] = os.environ['DISPLAY']
        #self.cmd = self.main.settings.get_setting('XBMC', 'xbmc')
        standalone = "--standalone"
        self.cmd = ['/usr/lib/xbmc/xbmc.bin',standalone,
                                            '--lircdev','/var/run/lirc/lircd']
        self.proc = None
        self.environ = os.environ
        logging.debug('xbmc command: %s',' '.join(self.cmd))

    def attach(self,frontend=True):
        logging.info('starting xbmc')
        try:
            # Shutdown inhibitor
            self.inhibitor = self.main.inhibit(
                                                    "power:sleep",
                                                    "frontend",
                                                    "xbmc running",
                                                    "block"
                                                    )
            self.proc = subprocess.Popen(self.cmd,env=self.environ)
            GObject.child_watch_add(self.proc.pid,self.on_exit,self.proc) # Add callback on exit
            logging.debug('started xbmc')
        except:
            logging.exception('could not start xbmc')

    def on_exit(self,pid, condition,data):
        logging.debug("called function with pid=%s, condition=%s, data=%s",pid, condition,data)
        if condition == 0:
            logging.info(u"normal xbmc exit")
        elif condition < 16384:
            logging.warn(u"abnormal exit: %s",condition)
        elif condition == 16384:
            logging.info(u"XBMC want's a shutdown")
            self.main.dbus2vdr.Remote.Enable()
            self.main.dbus2vdr.Remote.HitKey(Power)
            self.main.dbus2vdr.Remote.Disable()
        elif condition == 16896:
            logging.info(u"XBMC wants a reboot")
            #logging.info(self.main.powermanager.restart())
        os.close(self.inhibitor)

    def detach(self,active=0):
        logging.info('stopping xbmc')
        try:
            logging.debug('sending terminate signal')
            self.proc.terminate()
        except:
            logging.info('xbmc already terminated')
        self.proc = None
        #self.main_instance.vdrCommands.vdrRemote.disable()

    def status(self):
        if self.proc:
            state = 1
        else:
            state = 0
        return state

    def resume(self):
        if self.proc:
            logging.debug("xbmc already running")
        else:
            self.attach()
