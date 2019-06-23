#!/usr/bin/env python
#############################################
#   Title: Tracking Daemon Main Thread      #
# Project: VTGS                             #
# Version: 1.0                              #
#    Date: June 2019                        #
#  Author: Zach Leffke, KJ4QLP              #
# Comment:                                  #
#   Main Thread for tracking daemon         #
#############################################

import threading
import os
import math
import sys
import string
import time
import socket
import json
import binascii
import datetime
from logger import *

#import threads
from service_thread import *
from md01_thread import *

class Main_Thread(threading.Thread):
    """ docstring """
    def __init__ (self, cfg):
        threading.Thread.__init__(self, name = 'Main   ')
        self._stop      = threading.Event()
        self.cfg = cfg
        self.thread_enable = self.cfg['thread_enable']

        log_name = 'trackd_{:s}'.format(self.cfg['ssid']
        self.main_log_fh = setup_logger(log_name,
                                        path=self.cfg['log_path'],
                                        ts=self.cfg['startup_ts'])
        self.logger = logging.getLogger(log_name) #main logger
        self.logger.info("configs: {:s}".format(json.dumps(self.cfg)))

        self.state  = 'BOOT' #BOOT, IDLE, STANDBY, ACTIVE, FAULT, CALIBRATE
        self.state_map = {
            'BOOT':0x00,        #bootup
            'IDLE':0x01,        #threads launched, no connections, attempt md01 connect
            'STANDBY':0x02,     #user connected, md01 connected
            'ACTVE':0x04,       #clien activated system, launch az/el logger
            'CALIBRATE':0x08,   #calibration mode, future use
            'FAULT':0x80        #some kind of fault has occured
        }

    def run(self):
        print "Main Thread Started..."
        self.logger.info('Launched main thread')
        try:
            while (not self._stop.isSet()):
                if self.state == 'BOOT':
                    #starting up, Activate all threads
                    #State Change if all is well:  BOOT --> IDLE
                    if self._init_threads():#if all threads activate succesfully
                        self.logger.info('Successfully Launched Threads, Switching to IDLE State')
                        self._set_state('IDLE')
                        time.sleep(1)
                    else:
                        self.set_state('FAULT')
                    pass
                else: # NOT IN BOOT State
                    #Always check for service message
                    if (not self.service_thread.rx_q.empty()): #Received a message from user
                        msg = self.c2_thread.rx_q.get()
                        self._process_service_message(msg.strip())
                    if (not self.md01_thread.rx_q.empty()):
                        fft_msg = self.radio_thread.fft_q.get()
                        self._process_fft_snapshot(fft_msg)
                        #self.radio_thread._fft_snapshot()
                    #self._process_c2_message('fft')
                time.sleep(0.1)

        except (KeyboardInterrupt, SystemExit): #when you press ctrl+c
            print "\nCaught CTRL-C, Killing Threads..."
            self.logger.warning('Caught CTRL-C, Terminating Threads...')
            self._stop_threads()
            self.logger.warning('Terminating Main Thread...')
            sys.exit()
        sys.exit()

    def _process_srvice_message(self, msg):
        print msg


    def _init_threads(self):
        try:
            #Initialize Threads
            print 'thread_enable', self.thread_enable
            self.logger.info("Thread enable: {:s}".format(json.dumps(self.thread_enable)))
            for key in self.thread_enable.keys():
                if self.thread_enable[key]:
                    if key == 'service': #Initialize Service Thread
                        self.logger.info('Setting up Service Thread')
                        self.serv_thread = Service_Thread(self.cfg['service'], self.logger) #Service Thread
                        self.serv_thread.daemon = True
                    elif key == 'md01': #Initialize mD01 Thread
                        self.logger.info('Setting up MD01 Thread')
                        self.md01_thread = MD01_Thread(self.cfg['md01'], self.logger) #MD01 Thread
                        self.md01_thread.daemon = True
            #Launch threads
            for key in self.thread_enable.keys():
                if self.thread_enable[key]:
                    if key == 'service': #Start Service Thread
                        self.logger.info('Launching Service Thread')
                        self.serv_thread.start() #non-blocking
                    elif key == 'md01': #Initialize Radio Thread
                        self.logger.info('Launching MD01 Thread')
                        self.md01_thread.start() #non-blocking
            return True
        except Exception as e:
            self.logger.warning('Error Launching Threads:')
            self.logger.warning(str(e))
            self.logger.warning('Setting STATE --> FAULT')
            self._set_state = 'FAULT'
            return False

    def _stop_threads(self):
        for key in self.thread_enable.keys():
            if self.thread_enable[key]:
                if key == 'service': #Initialize C2 Thread
                    self.serv_thread.stop()
                    #self.c2_thread.join() # wait for the thread to finish what it's doing
                elif key == 'md01': #Initialize Radio Thread
                    self.md01_thread.stop()
                    #self.radio_thread.join() # wait for the thread to finish what it's doing


    #---Data Recorder STATE FUNCTIONS----
    def _set_state(self, state):
        self.state = state
        print 'Changed STATE to: {:s}'.format(self.state)
        self.logger.info('Changed STATE to: {:s}'.format(self.state))

    def get_state(self):
        return self.state
    #---END STATE FUNCTIONS----

    def utc_ts(self):
        return "{:s} | main | ".format(datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.%fZ'))

    def stop(self):
        self._stop.set()

    def stopped(self):
        return self._stop.isSet()
