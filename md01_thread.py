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


from optparse import OptionParser
import threading
from datetime import datetime as date
import os
import math
import sys
import string
import time
import inspect
from md01 import *

class MD01Thread(threading.Thread):
    def __init__ (self, ssid,ip, port, poll_rate, az_thresh=2.0, el_thresh=2.0):
        threading.Thread.__init__(self)
        self._stop      = threading.Event()
        self.ssid       = ssid
        self.md01       = md01(ip, port)
        self.poll_rate  = poll_rate #[s]
        self.connected  = False

        self.callback   = None # callback to Daemon Main Thread

        self.cur_az     = 0.0
        self.cur_el     = 0.0
        self.cur_time   = None

        self.last_az    = 0.0
        self.last_el    = 0.0
        self.last_time  = None

        self.az_rate    = 0.0
        self.el_rate    = 0.0
        self.time_delta = 0.0
        self.az_thresh  = az_thresh     #Azimuth Speed threshold, for error detection, deg/s
        self.el_thresh  = el_thresh     #Elevation Speed threshold, for error detection, deg/s

        self.tar_az     = 180.0
        self.tar_el     = 0.0

        self.set_flag   = False
        self.log_flag   = False
        self.log_file   = ""

        self.az_motion          = False #indicates azimuth motion
        self.el_motion          = False #indicates Elevation motion
        self.az_thresh_fault    = False #indicates antenna motion fault.
        self.el_thresh_fault    = False #indicates antenna motion fault.
        self.motion_stop_sent   = False #indicates a stop command has been sent to the MD-01

        self.thread_fault       = False #indicates unknown failure in thread
        self.thread_dormant     = False
    
    def run(self):
        #time.sleep(1)  #Give parent thread time to spool up
        print self.utc_ts() + self.ssid + " MD01 Thread Started..."
        print self.utc_ts() + "  Azimuth Threshold: " + str(self.az_thresh)
        print self.utc_ts() + "Elevation Threshold: " + str(self.el_thresh)
        print self.utc_ts() + "MD-01 Poll Rate [s]: " + str(self.poll_rate)
        while (not self._stop.isSet()):
            try:
                if self.connected == False: 
                    self.connected = self.md01.connect()
                    if self.connected == True:
                        print self.utc_ts() + "Connected to " + self.ssid + " MD01 Controller"
                        self.last_time = date.utcnow()
                        self.connected, self.last_az, self.last_el = self.md01.get_status()
                        self.callback.set_md01_con_status(self.connected) #notify main thread of connection
                        self.set_flag = False
                        time.sleep(1)
                    else:
                        time.sleep(5) #try to reconnect to MD01 every 5 seconds.
                elif self.connected == True:
                    feedback_valid = self.get_md01_feedback()
                    if feedback_valid:
                        if self.set_flag == True:  #Need to issue a set command to MD01
                            self.set_flag = False  #reset set flag
                            #Do current angles match target angles?
                            if ((round(self.cur_az,1) != round(self.tar_az,1)) or (round(self.cur_el,1) != round(self.tar_el,1))):
                                #is antenna in motion?
                                if ((self.az_motion) or (self.el_motion)): #Antenna Is in motion
                                    if self.motion_stop_sent == True: #A Stop command has been issued to the MD01
                                        self.set_flag = True #reset motion flag
                                    else:
                                        opposite_flag = False #indicates set command opposed to direction of motion.
                                        if (self.az_rate < 0) and (self.tar_az > self.cur_az): opposite_flag = True 
                                        elif (self.az_rate > 0) and (self.tar_az < self.cur_az): opposite_flag = True
                                        if (self.el_rate < 0) and (self.tar_el > self.cur_el): opposite_flag = True 
                                        elif (self.el_rate > 0) and (self.tar_el < self.cur_el): opposite_flag = True
                                        if opposite_flag: #Set command in opposite direction of motion
                                            print self.utc_ts()+"Set Command position opposite direction of motion"
                                            print self.utc_ts()+"Sending Stop Command to MD-01"
                                            self.connected, self.cur_az, self.cur_el = self.md01.set_stop() #Stop the rotation
                                            self.set_flag = True #try to resend set command next time around the loop
                                            self.motion_stop_sent = True
                                        else: #Set command is in the direction of rotation
                                            print self.utc_ts()+"Set Command position is in direction of motion"
                                            #Set Position command does not get a feedback response from MD-01   
                                            self.connected, self.cur_az, self.cur_el = self.md01.set_position(self.tar_az, self.tar_el)
                                else: #Antenna is stopped
                                    print self.utc_ts()+"Antenna is Stopped, sending SET command to MD01"
                                    #Set Position command does not get a feedback response from MD-01   
                                    self.motion_stop_sent = False
                                    self.connected, self.cur_az, self.cur_el = self.md01.set_position(self.tar_az, self.tar_el)
                    time.sleep(self.poll_rate)
            except:
                print self.utc_ts() + "Unexpected error in thread:", self.ssid,'\n', sys.exc_info() # substitute logging
                self.connected = False
                self.thread_fault = True

        print self.utc_ts() + "--- DAEMON IS NOW DORMANT ---"
        self.thread_dormant = True
        while 1:
            time.sleep(10)

    def get_md01_feedback(self):
        self.cur_time = date.utcnow()
        self.connected, self.cur_az, self.cur_el = self.md01.get_status()
        if self.connected == False:
            print self.utc_ts() + "Disconnected from " + self.ssid + " MD01 Controller"
            self.callback.set_md01_con_status(self.connected) #notify main thread of disconnection
            self.set_flag = False
            return False #indicates problem with getting feedback
        else:
            self.time_delta = (self.cur_time - self.last_time).total_seconds()
            self.az_rate = (self.cur_az - self.last_az) / self.time_delta
            self.el_rate = (self.cur_el - self.last_el) / self.time_delta
            
            if abs(self.az_rate) > 0: self.az_motion = True
            else: self.az_motion = False

            if abs(self.el_rate) > 0: self.el_motion = True
            else: self.el_motion = False
            
            if self.log_flag: self.update_log()

            if abs(self.az_rate) > self.az_thresh: self.az_thresh_fault = True
            if abs(self.el_rate) > self.el_thresh: self.el_thresh_fault = True

            if ((self.az_thresh_fault == True) or (self.el_thresh_fault)): 
                self.Antenna_Threshold_Fault()
            else:
                self.last_az = self.cur_az
                self.last_el = self.cur_el
                self.last_time = self.cur_time
                return True

    def Antenna_Threshold_Fault(self):
        cur_time_stamp = str(self.cur_time) + " UTC | MD01 | "
        print cur_time_stamp + "----ERROR! ERROR! ERROR!----"
        if self.az_thresh_fault == True:
            print cur_time_stamp + "Antenna Azimuth Motion Fault"
            print "{:s}Rotation Rate: {:2.3f} [deg/s] exceeded threshold {:2.3f} [deg/s]".format(cur_time_stamp, self.az_rate, self.az_thresh)
        if self.el_thresh_fault == True:
            print cur_time_stamp + "Antenna Elevation Motion Fault"
            print "{:s}Rotation Rate: {:2.3f} [deg/s] exceeded threshold {:2.3f} [deg/s]".format(cur_time_stamp, self.el_rate, self.el_thresh)         
        print "{:s}cur_az: {:+3.1f}, last_az: {:+3.1f}".format(cur_time_stamp, self.cur_az, self.last_az)
        print "{:s}cur_el: {:+3.1f}, last_el: {:+3.1f}, time_delta: {:+3.1f} [ms]".format(cur_time_stamp, self.cur_el, self.last_el, self.time_delta*1000)
        print self.utc_ts() + "--- Killing Thread Now... ---"
        #self.callback.set_state_fault()
        self.stop_thread()
        self.callback.set_state_fault()

    def get_position(self):
        return self.cur_az, self.cur_el

    def get_rate(self):
        return self.az_rate, self.el_rate

    def get_connected(self):
        return self.connected

    def start_logging(self, ts):
        self.log_flag = True
        self.log_file = "./log/"+ ts + "_" + self.ssid + "_MD01.log"
        self.log_f = open(self.log_file, 'a')
        msg = "Timestamp [UTC],Azimuth [deg],Elevation [deg],Azimuth Rate [deg/sec],Elevation Rate [deg/sec]\n"
        self.log_f.write(msg)
        self.log_f.close()
        print self.utc_ts() + 'Started Logging: ' + self.log_file

    def stop_logging(self):
        if self.log_flag == True:
            self.log_flag = False
            print self.utc_ts() + 'Stopped Logging: ' + self.log_file

    def update_log(self):
        self.log_f = open(self.log_file, 'a')
        msg = '{:s},{:3.1f},{:3.1f},{:1.3f},{:1.3f}\n'.format(str(self.cur_time),self.cur_az,self.cur_el,self.az_rate,self.el_rate)
        self.log_f.write(msg)
        self.log_f.close()

    def log_data(self):
        pass

    def set_position(self, az, el):
        self.tar_az = az
        self.tar_el = el
        self.set_flag = True
        #self.md01.set_position(self.tar_az, self.tar_el)

    def set_callback(self, callback):
        self.callback = callback

    def utc_ts(self):
        return str(date.utcnow()) + " UTC | MD01 | "

    def set_stop(self):
        self.tar_az = self.cur_az
        self.tar_el = self.cur_el
        self.md01.set_stop()

    def stop_thread(self):
        self.md01.set_stop()
        self.connected = self.md01.disconnect()
        self.callback.set_md01_con_status(self.connected) #notify main thread of connection
        self._stop.set()

    def stopped(self):
        return self._stop.isSet()


