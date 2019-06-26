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
import uuid
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

        log_name = 'trackd_{:s}'.format(self.cfg['ssid'])
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

        self.user_con = False
        self.md01_con = False

        self.user = None
        self.session_id = None
        self.ssid = self.cfg['ssid']

        self._tm_msg = self.cfg['messages']['tm']
        self._tm_msg['type'] = 'tm'

        self._tc_msg = self.cfg['messages']['tc']
        self._tc_msg['type'] = 'tc'

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
                    #else:
                    #    self._set_state('FAULT')
                elif self.state == 'FAULT':
                    print "in FAULT state, exiting"
                    sys.exit()
                else:# NOT IN BOOT State
                    #Always check for service message
                    if (self.thread_enable['service'] and (not self.service_thread.rx_q.empty())): #Received a message from user
                        msg = self.service_thread.rx_q.get()
                        self._process_service_message(msg)
                    if (self.thread_enable['md01'] and (not self.md01_thread.rx_q.empty())):
                        msg = self.md01_thread.rx_q.get()
                        self._process_md01_message(msg)

                    if self.state == 'IDLE':
                        self._do_idle() #wait for user conn AND mdo1 conn

                    elif self.state == 'STANDBY':
                        self._do_standby()

                    elif self.state == 'ACTIVE':
                        self._do_active()

                    elif self.state == 'CALIBRATE':
                        self._do_calibrate()

                time.sleep(0.1)

        except (KeyboardInterrupt): #when you press ctrl+c
            print "\n"+self.utc_ts() + "Caught CTRL-C, Killing Threads..."
            self.logger.warning('Caught CTRL-C, Terminating Threads...')
            self._stop_threads()
            self.logger.warning('Terminating Main Thread...')
            sys.exit()
        except SystemExit:
            self.logger.warning('Terminating Main Thread...')
        sys.exit()

    def _do_idle(self):
        #print self.user_con, self.md01_con
        #if self.user_con and self.md01_con:
        #    self.logger.info("Connection Status (USER/MD01): ".format(self.user_con, self.md01_con))
        #    self._set_state('STANDBY')
        self._check_con_status()

    def _do_standby(self):
        #USER Connected
        #MD01 Connected
        self._check_con_status()
        pass

    def _do_active(self):

        pass

    def _do_calibrate(self):
        pass

    def _check_con_status(self):
        #Checks User and MD01 connection status
        #sets daemon state accordingly
        if   self.user_con == True: #user is connected
            if self.md01_con == True: #MD01 is connected
                if self.state == 'IDLE': #Daemon is in IDLE
                    # DO NOT NEED TO STOP MD01
                    self._set_state('STANDBY')
            if self.md01_con == False: #MD01 is not connected
                if ((self.state == 'STANDBY') or (self.state == 'ACTIVE')):
                    self._set_state('IDLE')
        elif self.user_con == False: #user is not connected
            if ((self.state == 'STANDBY') or (self.state == 'ACTIVE')):
                self.md01_thread.set_stop()
                self._set_state('IDLE')


    def _process_service_message(self, msg):
        #validate message?
        if self.state == 'STANDBY':
            if msg['type'] == 'tc':
                if msg['cmd'] == 'start':
                    print '{:s}User \'{:s}\' requested session START'.format(self.utc_ts(), msg['user'])
                    self.logger.info("User \'{:s}\' requested session START".format(msg['user'])
                    self.user = msg['user']
                    self._start_active_session(msg['user'])
                    pass
                if msg['cmd'] == 'query':
                    self.md01_thread.get_feedback()

        elif self.state == 'ACTIVE':
            #validate message
            if msg['type'] == 'tc':
                if msg['cmd'] == 'stop':
                    print '{:s}User \'{:s}\' requested session STOP'.format(self.utc_ts(), msg['user'])
                    self.logger.info("User \'{:s}\' requested session STOP".format(msg['user'])
                    pass
                if msg['cmd'] == 'query':
                    pass
                if msg['cmd'] == 'set':
                    self.tar_az = self.msg['params']['az']
                    self.tar_el = self.msg['params']['el']
        print msg

    def _process_md01_message(self, msg):
        self._format_user_feedback(msg)

    def _format_user_feedback(self,msg):
        new_msg = msg
        print 'main', new_msg
        self.service_thread.tx_q.put(new_msg)


    ### Functions Called by child threads #####
    def set_user_con_status(self, status):
        self.user_con = status

    def set_md01_con_status(self, status):
        self.md01_con = status

    def set_md01_thread_fault(self):
        self.md01_fault = True
        self.md01_thread.stop()
    ### END Functions Called by child threads #####

    def _init_threads(self):
        try:
            #Initialize Threads
            print 'thread_enable', self.thread_enable
            self.logger.info("Thread enable: {:s}".format(json.dumps(self.thread_enable)))
            for key in self.thread_enable.keys():
                if self.thread_enable[key]:
                    if key == 'service': #Initialize Service Thread
                        self.logger.info('Setting up Service Thread')
                        self.service_thread = Service_Thread(self.cfg['service'], self.logger, self) #Service Thread
                        self.service_thread.daemon = True
                    elif key == 'md01': #Initialize mD01 Thread
                        self.logger.info('Setting up MD01 Thread')
                        self.md01_thread = MD01_Thread(self.cfg['md01'], self.logger, self) #MD01 Thread
                        self.md01_thread.daemon = True
            #Launch threads
            for key in self.thread_enable.keys():
                if self.thread_enable[key]:
                    if key == 'service': #Start Service Thread
                        self.logger.info('Launching Service Thread')
                        self.service_thread.start() #non-blocking
                    elif key == 'md01': #Initialize Radio Thread
                        self.logger.info('Launching MD01 Thread')
                        self.md01_thread.start() #non-blocking
            return True
        except Exception as e:
            self.logger.error('Error Launching Threads:', exc_info=True)
            self.logger.warning('Setting STATE --> FAULT')
            self._set_state('FAULT')
            return False

    def _stop_threads(self):
        for key in self.thread_enable.keys():
            if self.thread_enable[key]:
                if key == 'service':
                    self.service_thread.stop()
                    print self.utc_ts() + "Terminated Service Thread."
                    self.logger.warning("Terminated Service Thread.")
                    #self.service_thread.join() # wait for the thread to finish what it's doing
                elif key == 'md01': #Initialize Radio Thread
                    self.md01_thread.stop_thread()
                    print self.utc_ts() + "Terminated MD01 Thread..."
                    self.logger.warning("Terminated MD01 Thread...")
                    #self.md01_thread.join() # wait for the thread to finish what it's doing


    #---STATE FUNCTIONS----
    def _start_thread_logging(self, ts, session_id):
        ts = dt.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        self.service_thread.start_logging(ts, session_id)
        pass

    def _send_session_start(self):
        pass

    def _stop_thread_logging(self):
        pass

    def set_state_fault(self):
        self._set_state('FAULT')

    def _set_state(self, state):
        self.state = state
        if self.state in ['IDLE', 'STANDBY', 'FAULT']: self._stop_thread_logging()
        elif self.state == 'ACTIVE':
            ts = dt.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            session_id = uuid.uuid4()
            print self._utc_ts() + "Started Session ID: {:s}".format(self.session_id)
            self.logger.info("Started Session ID: {:s}".format(self.session_id))
            self._start_thread_logging(ts, ssid)
            self._send_session_start()

        print self.utc_ts() + "Connection Status (USER/MD01): {0}/{1}".format(self.user_con, self.md01_con)
        print self.utc_ts() + 'Changed STATE to: {:s}'.format(self.state)
        self.logger.info("Connection Status (USER/MD01): {0}/{1}".format(self.user_con, self.md01_con))
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
