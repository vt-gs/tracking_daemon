#!/usr/bin/env python
#################################################
#   Title: Tracking Daemon                      #
# Project: VTGS Tracking Daemon                 #
# Version: v0.1.0                               #
#    Date: July, 2019                           #
#  Author: Zach Leffke, KJ4QLP                  #
# Comment: main control thread                  #
#################################################

import threading
import os
import math
import sys
import string
import time
import socket
import json

from optparse import OptionParser
#from datetime import datetime as date
import datetime

from logger import *
from md01_thread import *
from server_thread import *
from watchdog_timer import *

class Main_Thread(threading.Thread):
    """ docstring """
    def __init__ (self,cfg, name):
        threading.Thread.__init__(self)
        threading.current_thread().name = "Main_Thread"
        self.setName("Main_Thread")
        self._stop      = threading.Event()
        self.cfg        = cfg

        setup_logger(self.cfg['main_log'])
        self.logger = logging.getLogger(self.cfg['main_log']['name']) #main logger
        self.logger.info("configs: {:s}".format(json.dumps(self.cfg)))

        #### DAEMON STATE ####
        self.state  = 'BOOT'    #BOOT, IDLE, STANDBY, ACTIVE, CALIBRATE, FAULT
        self.user_con = False
        self.md01_con = False

        self.log_flag   = False #trigger logging start/stop
        self.log_active = False #indicates whether logging is active
        self.filename   = ""

        #self.active_watchdog = 0 #watchdog counter for active state, if
        #self.active_timeout  = self.cfg['service']['timeout'] #watchdog counter for active state
        self.active_user = None #current user of active session



        self.state_map = {
            'BOOT':0x00,        #bootup
            'IDLE':0x01,        #threads launched, no connections, attempt md01 connect
            'STANDBY':0x02,     #client connected, device connected, Start loggers
            'ACTIVE':0x04,      #client requested acti!
            'CALIBRATE':0x08,   #calibration mode, future use
            'FAULT':0x80        #some kind of fault has occured
        }

    def run(self):
        self.logger.info('Launched {:s}'.format(self.name))
        self.print_state()
        try:
            while (not self._stop.isSet()):
                if self.state == 'BOOT':
                    self._handle_state_boot()
                elif self.state == 'IDLE':
                    self._handle_state_idle()
                elif self.state == 'STANDBY':
                    self._handle_state_standby()
                elif self.state == 'ACTIVE':
                    self._handle_state_active()
                elif self.state == 'FAULT':
                    self._handle_state_fault()
                time.sleep(1)
        except (KeyboardInterrupt): #when you press ctrl+c
            self.logger.warning('Caught CTRL-C, Terminating Threads...')
            self._stop_threads()
            self.logger.warning('Terminating Main Thread...')
            sys.exit()
        except SystemExit:
            self.logger.warning('Terminating Main Thread...')
        sys.exit()

    #### State Handlers ########################
    def _handle_state_boot(self):
        if self._init_threads():#if all threads activate succesfully
            self.logger.info('Successfully Launched Threads, Switching to IDLE State')
            self.set_state_idle()
            time.sleep(1)
        else:
            self.logger.info('Failed to Launched Threads...')
            self.set_state_fault()

    def _handle_state_idle(self):
        pass

    def _handle_state_standby(self):
        pass

    def _handle_state_active(self):
        pass
    def _handle_state_calibrate(self):
        pass

    def _handle_state_fault(self):
        pass

    def _handle_active_watchdog(self):
        self.logger.info('ACTIVE session timeout ({:3.1f}s), User \'{:s}\', switching to STANDBY'.format(self.cfg['service']['timeout'], self.active_user))
        self.device_thread.set_stop()
        self.set_state_standby()
    ############################################

    #---- MAIN THREAD CONTROLS -----------------------------------
    def _init_threads(self):
        try:
            #Initialize Threads
            #print 'thread_enable', self.thread_enable
            self.logger.info("Thread enable: {:s}".format(json.dumps(self.cfg['thread_enable'])))
            for key in self.cfg['thread_enable'].keys():
                if self.cfg['thread_enable'][key]:
                    if key == 'service': #Initialize Service Thread
                        self.logger.info('Setting up Service Thread')
                        if self.cfg['service']['type'] == "TCP":
                            self.service_thread = VTP_Service_Thread_TCP(self.cfg['service'], self) #Service Thread
                        self.service_thread.daemon = True
                    elif key == 'device': #Initialize Device Thread
                        self.logger.info('Setting up Device Thread')
                        self.device_thread = MD01_Thread(self.cfg['device'], self)
                        self.device_thread.daemon = True
            #Launch threads
            for key in self.cfg['thread_enable'].keys():
                if self.cfg['thread_enable'][key]:
                    if key == 'service': #Start Service Thread
                        self.logger.info('Launching Service Thread...')
                        self.service_thread.start() #non-blocking
                    elif key == 'device': #Start Device
                        self.logger.info('Launching Device Thread...')
                        self.device_thread.start() #non-blocking
            return True
        except Exception as e:
            self.logger.error('Error Launching Threads:', exc_info=True)
            self.logger.warning('Setting STATE --> FAULT')
            self.set_state_fault()
            return False

    def _stop_threads(self):
        #stop all threads
        for key in self.cfg['thread_enable'].keys():
            if self.cfg['thread_enable'][key]:
                if key == 'service':
                    self.service_thread.stop()
                    self.logger.warning("Terminated Service Thread.")
                    #self.service_thread.join() # wait for the thread to finish what it's doing
                elif key == 'device': #Initialize Radio Thread
                    self.device_thread.stop()
                    self.logger.warning("Terminated Device Thread...")
                    #self.device_threadead.join() # wait for the thread to finish what it's doing

    def stop(self):
        #print '{:s} Terminating...'.format(self.name)
        self.logger.info('{:s} Terminating...'.format(self.name))
        self._stop.set()

    def stopped(self):
        return self._stop.isSet()

    #---- END MAIN THREAD CONTROLS -----------------------------------

    #### FUNCTIONS CALLED BY SERVER THREAD ####
    def set_user_con_status(self, con):
        #Sets user connection status
        self.user_con = con
        self.check_con_status()

    def management_frame_received(self, frame, ts):
        #Called from server thread when management frame received
        if frame.cmd == 'START':  #initiate User Session
            #print '{:s}User \'{:s}\' requested session START'.format(self.utc_ts(), frame.uid)
            self.logger.info('User \'{:s}\' requested session START'.format(frame.uid))
            if self.state == 'STANDBY':
                self.set_state_active(frame.uid)
        elif frame.cmd == 'STOP':  #initiate User Session
            #print '{:s}User \'{:s}\' requested session STOP'.format(self.utc_ts(), frame.uid)
            self.logger.info('User \'{:s}\' requested session STOP'.format(frame.uid))
            if self.state == 'ACTIVE':
                self.device_thread.set_stop()
                self.set_state_standby()
        elif frame.cmd == 'QUERY':  #initiate User Session
            pass
            #print '{:s}User \'{:s}\' requested session QUERY'.format(self.utc_ts(), frame.uid)

        self.service_thread.send_management_feedback(self.state)

    def motion_frame_received(self, parent, frame, ts):
        #Called from server thread when motion frame received
        if self.state == 'ACTIVE': #Motion commands only processed when daemon is ACTIVE
            #self.active_watchdog = 0 #reset watchdog timer

            if frame.cmd == 'SET':  #SET TARGET AZ/EL
                #print '{:s}User \'{:s}\' requested MOTION SET: AZ={:3.1f}, EL={:3.1f}'.format(self.utc_ts(), frame.uid, frame.az, frame.el)
                self.logger.info('User \'{:s}\' requested MOTION SET: AZ={:3.1f}, EL={:3.1f}'.format(frame.uid, frame.az, frame.el))
                #MD01 Set target angles
                self.device_thread.set_position(frame.az, frame.el)
                self.active_watchdog.reset()
                #parent.send_motion_feedback(self.state)
            elif frame.cmd == 'STOP':  #STOP ANTENNA MOTION
                #print '{:s}User \'{:s}\' requested MOTION STOP'.format(self.utc_ts(), frame.uid)
                self.logger.info('User \'{:s}\' requested MOTION STOP'.format(frame.uid))
                #MD01 set stop
                self.device_thread.set_stop()
                self.active_watchdog.reset() #timer
                #parent.send_motion_feedback(self.state)
            elif frame.cmd == 'GET':  #QUERY ANTENNA POSITION
                pass
                #print '{:s}User \'{:s}\' requested MOTION GET'.format(self.utc_ts(), frame.uid)
                #MD01 query
            az, el, az_rate, el_rate = self.get_motion_state()
            self.service_thread.send_motion_feedback(az, el, az_rate, el_rate)

    def get_motion_state(self):
        az, el   = self.device_thread.get_position()
        az_rate, el_rate = self.device_thread.get_rate()
        return az, el, az_rate, el_rate

    #### FUNCTIONS CALLED BY MD01 THREAD ####
    def set_md01_con_status(self, con):
        #Sets user connection status
        self.md01_con = con
        self.check_con_status()

    ### LOGGING FUNCTIONS ###
    def start_logging(self):
        ts = date.utcnow().strftime('%Y%m%d_%H%M%S')
        if self.cfg['thread_enable']['service']:
            self.service_thread.start_logging(ts)
        if self.cfg['thread_enable']['device']:
            self.device_thread.start_logging(ts)

    def stop_logging(self):
        if self.cfg['thread_enable']['service']:
            self.service_thread.stop_logging()
        if self.cfg['thread_enable']['device']:
            self.device_thread.stop_logging()

    #### FUNCTIONS CALLED LOCALLY ####
    def check_con_status(self):
        #Checks User and MD01 connection status
        #sets daemon state accordingly
        if   self.user_con == True: #user is connected
            if self.md01_con == True: #MD01 is connected
                if self.state == 'IDLE': #Daemon is in IDLE
                    # DO NOT NEED TO STOP MD01
                    self.set_state_standby()
            if self.md01_con == False: #MD01 is not connected
                if ((self.state == 'STANDBY') or (self.state == 'ACTIVE')):
                    self.set_state_idle()
        elif self.user_con == False: #user is not connected
            if ((self.state == 'STANDBY') or (self.state == 'ACTIVE')):
                self.device_thread.set_stop()
                self.set_state_idle()

    def set_state_idle(self):
        self.state = 'IDLE'
        self.stop_logging()
        self.print_state()

    def set_state_standby(self):
        self.state = 'STANDBY'
        self.stop_logging()
        self.active_watchdog.stop()
        self.logger.info("Stopped ACTIVE session Watchdog Timer")
        self.print_state()

    def set_state_active(self, user):
        self.start_logging()
        self.active_user = user
        self.active_watchdog = Watchdog(timeout = self.cfg['service']['timeout'],
                                        userHandler=self._handle_active_watchdog)
        self.logger.info("Started ACTIVE session Watchdog Timer: {:3.2f}".format(self.cfg['service']['timeout']))
        self.active_watchdog.start()
        #self.logger.info("Started ACTIVE session Watchdog Timer: {:3.2f}".format(self.cfg['service']['timeout']))
        self.state = 'ACTIVE'
        self.print_state()

    def set_state_fault(self):
        self.stop_logging()
        self.state = 'FAULT'
        self.print_state()
        pass

    def print_state(self):
        self.logger.info("Connection Status (USER/MD01): {0}/{1}".format(self.user_con, self.md01_con))
        self.logger.info("Daemon State: {:s}".format(self.state))

    # def utc_ts(self):
    #     return str(date.utcnow()) + " UTC | MAIN | "
    #
    # def stop(self):
    #     self._stop.set()
    #     sys.quit()
    #
    # def stopped(self):
    #     return self._stop.isSet()
