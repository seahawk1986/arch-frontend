#!/usr/bin/python3
import dbus
from dbus.mainloop.glib import DBusGMainLoop
dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
import logging
from pydbus2vdr.dbus2vdr import *
from frontends.base import *
import os
import subprocess

class Xine():
    def __init__(self, main, name, path='/usr/bin/xine',origin='127.0.0.1',port='37890'):
        self.main = main
        self.name = name
        self.main_instance.hdf.updateKey('yavdr.frontend.sxfe.autocrop','0') # Remove
        self.main_instance.hdf.updateKey('yavdr.frontend.xine.anamorphic','') # Remove
        self.main_instance.hdf.updateKey('yavdr.frontend.xine.autocrop','0') # Remove
        if self.main.settings.get_settingb('xine', 'autocrop', False):
            autocrop = "--post autocrop:enable_autodetect=1,enable_subs_detect=1,soft_start=1,stabilize=1"
        else:
            autocrop = ""
        if self.main.settings.get_settingb('xine', 'anamorphic', False):
            aspectratio = "--aspect-ratio=%s"%(self.main.settings.get_setting(
                                                'xine', 'aspect_ratio', '16:9')
            )
        else:
            aspectratio = ""
        os.environ['__GL_SYNC_TI_VBLANK']="1"
        # TODO Display config:
        os.environ['__GL_SYNC_DISPLAY_DEVICE'] = os.environ['DISPLAY']

        self.cmd = ['/usr/bin/xine --post tvtime:method=use_vo_driver \
            --config /etc/xine/config \
            --keymap=file:/etc/xine/keymap \
            --post vdr --post vdr_video --post vdr_audio --verbose=2 \
            --no-gui --no-logo --no-splash --deinterlace -pq \
            -A pulseaudio \
            %s %s \
            vdr:/tmp/vdr-xine/stream#demux:mpeg_pes'%(autocrop, aspectratio)]
        self.proc = None
        self.environ = os.environ
        logging.debug(' '.join(self.cmd))

    def attach(self):
        logging.debug('starting xine')
        self.proc = subprocess.Popen("exec " + self.cmd,
                                     shell=True,env=os.environ)
        logging.debug('started xine')

    def detach(self,active=0):
        logging.debug('stopping xine')
        try:
            self.proc.terminate()
        except:
            logging.debug('xine already terminated')
        self.proc = None

    def status(self):
        if self.proc: return 1
        else: return 0

    def resume(self):
        if self.proc: pass
        else: self.attach()
