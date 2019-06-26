#!/usr/bin/env python
#################################################
#   Title: Tracking Daemon                      #
# Project: VTGS Tracking Daemon                 #
# Version: 2.1                                  #
#    Date: Aug 03, 2016                         #
#  Author: Zach Leffke, KJ4QLP                  #
# Comment: This version of the Tracking Daemon  #
#           is intended to be a 1:1 interface   #
#           for the MD01.  It will run on the   #
#           Control Server 'eddie' and provide  #
#           a single interface to the MD01      #
#           controllers.                        #
#           This daemon is a protocol translator#
#################################################

import threading
import os
import math
import sys
import string
import time
import socket
import SocketServer

from optparse import OptionParser
from datetime import datetime as date
from md01_thread import *

class MainThread(threading.Thread):
    def __init__ (self, ssid, serv_thr, md01_thr):
        threading.Thread.__init__(self)
        self._stop      = threading.Event()
        self.ssid       = ssid

        #### DAEMON STATE ####
        self.state  = 'IDLE'    #IDLE, STANDBY, ACTIVE, FAULT, CALIBRATE
        self.user_con = False
        self.md01_con = False

        self.log_flag   = False #trigger logging start/stop
        self.log_active = False #indicates whether logging is active
        self.filename   = ""

        self.md01_thr = md01_thr
        self.serv_thr = serv_thr

        self.active_watchdog = 0 #watchdog counter for active state, if
        self.active_timeout  = 10 #watchdog counter for active state
        self.active_user = None #current user of active session

    def run(self):
        print self.utc_ts() + self.ssid + " Main Thread Started..."
        self.print_state()
        while (not self._stop.isSet()): 
            if self.state == 'IDLE':
                pass
            elif self.state == 'STANDBY':
                pass
            elif self.state == 'ACTIVE':
                self.active_watchdog += 1
                if self.active_watchdog >= self.active_timeout: #watchdog for active state, if no activity, switch to STANDBY
                    print '{:s}ACTIVE session timeout ({:3.1f}s), User \'{:s}\', switching to STANDBY'.format(self.utc_ts(), self.active_timeout, self.active_user)
                    self.md01_thr.set_stop()
                    self.set_state_standby()
            elif self.state == 'FAULT':
                pass
            time.sleep(1)

    #### FUNCTIONS CALLED BY SERVER THREAD ####
    def set_user_con_status(self, con):
        #Sets user connection status
        self.user_con = con
        self.check_con_status()
    
    def management_frame_received(self, parent, frame, ts):
        #Called from server thread when management frame received
        if frame.cmd == 'START':  #initiate User Session
            print '{:s}User \'{:s}\' requested session START'.format(self.utc_ts(), frame.uid)
            if self.state == 'STANDBY':
                self.set_state_active(frame.uid)
        elif frame.cmd == 'STOP':  #initiate User Session
            print '{:s}User \'{:s}\' requested session STOP'.format(self.utc_ts(), frame.uid)
            if self.state == 'ACTIVE':
                self.md01_thr.set_stop()
                self.set_state_standby()
        elif frame.cmd == 'QUERY':  #initiate User Session
            pass
            #print '{:s}User \'{:s}\' requested session QUERY'.format(self.utc_ts(), frame.uid)

        parent.send_management_feedback(self.state)

    def motion_frame_received(self, parent, frame, ts):
        #Called from server thread when motion frame received
        if self.state == 'ACTIVE': #Motion commands only processed when daemon is ACTIVE
            self.active_watchdog = 0 #reset watchdog timer
            if frame.cmd == 'SET':  #SET TARGET AZ/EL
                print '{:s}User \'{:s}\' requested MOTION SET: AZ={:3.1f}, EL={:3.1f}'.format(self.utc_ts(), frame.uid, frame.az, frame.el)
                #MD01 Set target angles
                self.md01_thr.set_position(frame.az, frame.el)
                #parent.send_motion_feedback(self.state)
            elif frame.cmd == 'STOP':  #STOP ANTENNA MOTION
                print '{:s}User \'{:s}\' requested MOTION STOP'.format(self.utc_ts(), frame.uid)
                #MD01 set stop
                self.md01_thr.set_stop()
                #parent.send_motion_feedback(self.state)
            elif frame.cmd == 'GET':  #QUERY ANTENNA POSITION
                pass
                #print '{:s}User \'{:s}\' requested MOTION GET'.format(self.utc_ts(), frame.uid)
                #MD01 query
            az, el, az_rate, el_rate = self.get_motion_state()
            parent.send_motion_feedback(az, el, az_rate, el_rate)

    def get_motion_state(self):
        az, el   = self.md01_thr.get_position()
        az_rate, el_rate = self.md01_thr.get_rate()
        return az, el, az_rate, el_rate

    #### FUNCTIONS CALLED BY MD01 THREAD ####
    def set_md01_con_status(self, con):
        #Sets user connection status
        self.md01_con = con
        self.check_con_status()

    ### LOGGING FUNCTIONS ###
    def start_logging(self):
        ts = date.utcnow().strftime('%Y%m%d_%H%M%S')
        self.serv_thr.start_logging(ts)
        self.md01_thr.start_logging(ts)

    def stop_logging(self):
        self.serv_thr.stop_logging()
        self.md01_thr.stop_logging()

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
                self.md01_thr.set_stop()
                self.set_state_idle()

    def set_state_idle(self):
        self.state = 'IDLE'
        self.stop_logging()
        self.print_state()        
        
    def set_state_standby(self):
        self.state = 'STANDBY'
        self.stop_logging()
        self.print_state()

    def set_state_active(self, user):
        self.start_logging()
        self.active_user = user
        self.active_watchdog = 0
        self.state = 'ACTIVE'
        self.print_state()

    def set_state_fault(self):
        self.stop_logging()
        self.state = 'FAULT'
        self.print_state()
        pass

    def print_state(self):
        print self.utc_ts() + "Connection Status (USER/MD01): " + str(self.user_con) + '/' + str(self.md01_con)
        print self.utc_ts() + self.ssid + " Daemon State: " + str(self.state)
    
    def utc_ts(self):
        return str(date.utcnow()) + " UTC | MAIN | "

    def stop(self):
        self._stop.set()
        sys.quit()

    def stopped(self):
        return self._stop.isSet()


