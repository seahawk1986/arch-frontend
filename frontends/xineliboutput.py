#!/usr/bin/python3
import dbus
from dbus.mainloop.glib import DBusGMainLoop
dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
import logging
from pydbus2vdr.dbus2vdr import *
from frontends.base import *
import os
import socket
import subprocess

class VDRsxfe():
    def __init__(self, main_instance, path='/usr/bin/vdr-sxfe',
                                            origin='127.0.0.1',port='37890'):
        self.main_instance = main_instance
        self.origin = origin
        self.port = port
        self.mode = self.main.settings.get_setting('Xineliboutput',
                                                   'xineliboutput',
                                                   'remote')
        self.main.settings.get_settingb('Xineliboutput', 'autocrop', False)
        os.environ['__GL_SYNC_TO_VBLANK']="1"
        # TODO Display config:
        os.environ['__GL_SYNC_DISPLAY_DEVICE'] = os.environ['DISPLAY']
        self.cmd = [
            '/usr/bin/vdr-sxfe --post tvtime:method=use_vo_driver \
            --reconnect --audio=alsa \
            --syslog xvdr+tcp://%s:%s'%(origin,port)
            ]
        self.proc = None
        self.environ = os.environ
        logging.debug('vdr-sxfe command: %s',' '.join(self.cmd))
        self.state = 0

    def attach(self):
        if self.mode == 'remote' and self.status() == 0:
            while not self.isOpen():
                time.sleep(1)
            logging.info('starting vdr-sxfe')
            self.proc = subprocess.Popen(self.cmd,shell=True,env=self.environ)
            logging.debug('started vdr-sxfe')
        elif self.mode == 'local' and self.status() == 0:
            self.main.dbus2vdr.Plugins.SVDRPCommand('xinelibputput', 'LFRO',
                                                    'sxfe')
            self.state = 1

    def detach(self,active=0):
        if self.mode == 'remote':
            logging.info('stopping vdr-sxfe')
            try:
                self.proc.kill()
            except:
                logging.info('vdr-sxfe already terminated')
            self.proc = None
            self.main_instance.vdrCommands.vdrRemote.disable()
        elif self.mode == 'local':
             self.main.dbus2vdr.Plugins.SVDRPCommand('xinelibputput', 'LFRO',
                                                        'none')
             self.state = 0

    def status(self):
        if self.mode == 'remote':
            if self.proc: return 1
            else: return 0
        elif self.mode == 'local':
            return self.state


    def resume(self):
        if self.mode == 'remote':
            if self.proc: pass
            else: self.attach()
        elif self.mode == 'local':
            if self.state == 0:
                self.attach()

    def isOpen(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.connect((self.origin, int(self.port)))
            s.shutdown(2)
            return True
        except:
            return False