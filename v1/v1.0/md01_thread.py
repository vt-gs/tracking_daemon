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
import datetime
import os
import math
import sys
import string
import time
import inspect
import copy
from Queue import Queue

from md01 import *

class MD01_Thread(threading.Thread):
    #def __init__ (self, ssid,ip, port, poll_rate, az_thresh=2.0, el_thresh=2.0):
    def __init__ (self, cfg, logger, parent = None):
        threading.Thread.__init__(self, name = "MD01Thread")
        self._stop      = threading.Event()
        self.cfg        = cfg
        self.logger     = logger
        self.parent     = parent # callback to Daemon Main Thread

        print self._utc_ts() + "Initializing {:s} MD01 Thread".format(self.cfg['ssid'])
        self.logger.info("Initializing {:s} MD01 Thread".format(self.cfg['ssid']))

        self.ssid       = self.cfg['ssid']
        self.ip         = self.cfg['ip']
        self.port       = self.cfg['port']
        self.timeout    = self.cfg['timeout']
        self.poll_rate  = self.cfg['poll_rate'] #[s]
        self.az_thresh  = self.cfg['az_thresh'] #Azimuth Speed threshold, for error detection, deg/s
        self.el_thresh  = self.cfg['el_thresh'] #Elevation Speed threshold, for error detection, deg/s

        self.md01       = md01(self.cfg, self.logger)

        self.rx_q = Queue()
        self.tx_q = Queue()

        #self.connected  = False
        #self.cur_az     = 0.0
        #self.cur_el     = 0.0
        #self.cur_time   = None
        #self.az_rate    = 0.0
        #self.el_rate    = 0.0
        self.last_az    = 0.0
        self.last_el    = 0.0
        self.last_time  = None
        self.time_delta = 0.0
        self.tar_az     = 180.0
        self.tar_el     = 0.0
        self.set_flag   = False
        self.log_flag   = False
        self.log_file   = ""

        self.status = {
            'ts': None,
            'connected':False,
            'cur_az': 0.0,
            'cur_el':0.0
        } #returns ts, connection state, cur_az, cur_el

        self.feedback = {
            'ts':None,
            'cur_az':0.0,
            'cur_el':0.0,
            'az_rate':0.0,
            'el_rate':0.0
        }

        self.az_motion          = False #indicates azimuth motion
        self.el_motion          = False #indicates Elevation motion
        self.az_thresh_fault    = False #indicates antenna motion fault.
        self.el_thresh_fault    = False #indicates antenna motion fault.
        self.motion_stop_sent   = False #indicates a stop command has been sent to the MD-01

        self.thread_fault       = False #indicates unknown failure in thread
        self.thread_dormant     = False

    def run(self):
        #time.sleep(1)  #Give parent thread time to spool up
        print self._utc_ts() + "{:s} MD01 Thread Started".format(self.ssid)
        self.logger.info("{:s} MD01 Thread Started".format(self.ssid))
        print self._utc_ts() + "Azimuth Threshold: {:3.3f}".format(self.az_thresh)
        self.logger.info("Azimuth Threshold: {:3.3f}".format(self.az_thresh))
        print self._utc_ts() + "Elevation Threshold: {:3.3f}".format(self.el_thresh)
        self.logger.info("Elevation Threshold: {:3.3f}".format(self.el_thresh))
        print self._utc_ts() + "MD-01 Poll Rate [s]: {:3.3f}".format(self.poll_rate)
        self.logger.info("MD-01 Poll Rate [s]: {:3.3f}".format(self.poll_rate))

        while (not self._stop.isSet()):
            try:
                if self.status['connected'] == False:
                    self.status['connected'] = self.md01.connect()
                    if self.status['connected'] == True:
                        print self._utc_ts() + "Connected to {:s} MD01 Controller".format(self.ssid )
                        self.logger.info("Connected to {:s} MD01 Controller".format(self.ssid ))
                        self.status = self.md01.get_status()
                        self._update_feedback()
                        #print status
                        self.last_time = self.status['ts']
                        #self.status['connected'] = status['connected']
                        self.last_az = self.status['cur_az']
                        self.last_el = self.status['cur_el']
                        self.parent.set_md01_con_status(self.status['connected']) #notify main thread of connection
                        self.set_flag = False

                        time.sleep(1)
                    else:
                        time.sleep(self.timeout) #try to reconnect to MD01 every 5 seconds.
                elif self.status['connected'] == True:
                    feedback_valid = self.get_md01_feedback()
                    if feedback_valid:
                        if self.set_flag == True:  #Need to issue a set command to MD01
                            self.set_flag = False  #reset set flag
                            #Do current angles match target angles?
                            if ((round(self.status['cur_az'],1) != round(self.tar_az,1)) or (round(self.status['cur_el'],1) != round(self.tar_el,1))):
                                #is antenna in motion?
                                if ((self.az_motion) or (self.el_motion)): #Antenna Is in motion
                                    if self.motion_stop_sent == True: #A Stop command has been issued to the MD01
                                        self.set_flag = True #reset motion flag
                                    else:
                                        opposite_flag = False #indicates set command opposed to direction of motion.
                                        if (self.status['az_rate'] < 0) and (self.tar_az > self.status['cur_az']): opposite_flag = True
                                        elif (self.status['az_rate'] > 0) and (self.tar_az < self.status['cur_az']): opposite_flag = True
                                        if (self.status['el_rate'] < 0) and (self.tar_el > self.status['cur_el']): opposite_flag = True
                                        elif (self.status['el_rate'] > 0) and (self.tar_el < self.status['cur_el']): opposite_flag = True
                                        if opposite_flag: #Set command in opposite direction of motion
                                            print self._utc_ts()+"Set Command position opposite direction of motion"
                                            print self._utc_ts()+"Sending Stop Command to MD-01"
                                            #self.connected, self.cur_az, self.cur_el = self.md01.set_stop() #Stop the rotation
                                            self.status = self.md01.set_stop()
                                            self._update_feedback()
                                            self.set_flag = True #try to resend set command next time around the loop
                                            self.motion_stop_sent = True
                                        else: #Set command is in the direction of rotation
                                            print self._utc_ts()+"Set Command position is in direction of motion"
                                            #Set Position command does not get a feedback response from MD-01
                                            #self.connected, self.cur_az, self.cur_el = self.md01.set_position(self.tar_az, self.tar_el)
                                            self.status = self.md01.set_position(self.tar_az, self.tar_el)
                                            #self._update_feedback()
                                else: #Antenna is stopped
                                    print self._utc_ts()+"Antenna is Stopped, sending SET command to MD01"
                                    #Set Position command does not get a feedback response from MD-01
                                    self.motion_stop_sent = False
                                    #self.connected, self.cur_az, self.cur_el = self.md01.set_position(self.tar_az, self.tar_el)
                                    self.status = self.md01.set_position(self.tar_az, self.tar_el)
                                    #self._update_feedback()
                    time.sleep(self.poll_rate)
            except:
                print self._utc_ts() + "Unexpected error in thread:", self.ssid,'\n', sys.exc_info() # substitute logging
                self.status['connected'] = False
                self.thread_fault = True

        print self._utc_ts() + "--- DAEMON IS NOW DORMANT ---"
        self.thread_dormant = True
        while 1:
            time.sleep(10)

    def _update_feedback(self):
        status = self.status
        for k in self.feedback.keys():
            if k in status:
                self.feedback[k] = status[k]
            else:
                if 'rate' in k:
                    self.feedback[k] = 0.0
        #print 'md01', self.feedback
        #self.rx_q.put(self.feedback)

    def get_md01_feedback(self):
        #self.cur_time = date.utcnow()
        #self.connected, self.cur_az, self.cur_el = self.md01.get_status()
        self.status = self.md01.get_status()
        if self.status['connected'] == False:
            print self._utc_ts() + "Disconnected from {:s} MD01 Controller".format(self.ssid )
            self.logger.info("Disconnected from {:s} MD01 Controller".format(self.ssid ))

            self.parent.set_md01_con_status(self.status['connected']) #notify main thread of disconnection
            self.set_flag = False
            return False #indicates problem with getting feedback
        else:
            self.time_delta = (self.status['ts'] - self.last_time).total_seconds()
            self.status['az_rate'] = (self.status['cur_az'] - self.last_az) / self.time_delta
            self.status['el_rate'] = (self.status['cur_el'] - self.last_el) / self.time_delta

            if abs(self.status['az_rate']) > 0: self.az_motion = True
            else: self.az_motion = False

            if abs(self.status['el_rate']) > 0: self.el_motion = True
            else: self.el_motion = False

            if self.log_flag:
                self.update_log()

            if abs(self.status['az_rate']) > self.az_thresh: self.az_thresh_fault = True
            if abs(self.status['el_rate']) > self.el_thresh: self.el_thresh_fault = True

            if ((self.az_thresh_fault == True) or (self.el_thresh_fault)):
                self.Antenna_Threshold_Fault()
            else:
                self.last_az = self.status['cur_az']
                self.last_el = self.status['cur_el']
                self.last_time = self.status['ts']
                self._update_feedback()
                return True

    def Antenna_Threshold_Fault(self):
        cur_time_stamp = str(self.status['ts']) + " UTC | MD01 | "
        print cur_time_stamp + "----ERROR! ERROR! ERROR!----"
        if self.az_thresh_fault == True:
            print cur_time_stamp + "Antenna Azimuth Motion Fault"
            print "{:s}Rotation Rate: {:2.3f} [deg/s] exceeded threshold {:2.3f} [deg/s]".format(cur_time_stamp, self.status['az_rate'], self.az_thresh)
        if self.el_thresh_fault == True:
            print cur_time_stamp + "Antenna Elevation Motion Fault"
            print "{:s}Rotation Rate: {:2.3f} [deg/s] exceeded threshold {:2.3f} [deg/s]".format(cur_time_stamp, self.status['el_rate'], self.el_thresh)
        print "{:s}cur_az: {:+3.1f}, last_az: {:+3.1f}".format(cur_time_stamp, self.status['cur_az'], self.last_az)
        print "{:s}cur_el: {:+3.1f}, last_el: {:+3.1f}, time_delta: {:+3.1f} [ms]".format(cur_time_stamp, self.status['cur_el'], self.last_el, self.time_delta*1000)
        print self._utc_ts() + "--- Killing Thread Now... ---"
        #self.callback.set_state_fault()
        self.stop_thread()
        self.parent.set_state_fault()

    def get_position(self):
        return self.status['cur_az'], self.status['cur_el']

    def get_rate(self):
        return self.status['az_rate'], self.status['el_rate']

    def get_connected(self):
        return self.connected

    def get_feedback(self):
        msg = copy.deepcopy(self.feedback)
        msg['ts'] = msg['ts'].strftime('%Y-%m-%dT%H:%M:%S.%fZ')
        self.rx_q.put(msg)
        #return self.status

    def start_logging(self, ts, session_id):
        log_name = 'trackd_{:s}_{:s}'.format(self.cfg['ssid'], self.name.lower())
        self.msg_log_fh = setup_logger(log_name,
                                    path=self.cfg['log_path'],
                                    ts=ts)
        self.msg_logger = logging.getLogger(log_name) #main logger

        print self._utc_ts() + "Setup Session Logger: {:s}".format(session_id)
        self.msg_logger.info("Session ID: {:s}".format(session_id))
        msg = "Timestamp [UTC],Azimuth [deg],Elevation [deg],Azimuth Rate [deg/sec],Elevation Rate [deg/sec]"
        self.msg_logger.info(msg)
        print self._utc_ts() + 'Started Logging: ' + self.msg_logger.handlers[-1].baseFilename
        self.logger.info("Started Logging: {:s}".format(self.msg_logger.handlers[-1].baseFilename))
        self.log_flag = True

    def stop_logging(self):
        print self._utc_ts() + 'Stopped Logging: ' + self.msg_logger.handlers[-1].baseFilename
        self.logger.info("Stopped Logging: {:s}".format(self.msg_logger.handlers[-1].baseFilename))
        self.msg_logger.removeHandler(self.msg_logger.handlers[-1])

    def set_position(self, az, el):
        self.tar_az = az
        self.tar_el = el
        self.set_flag = True
        #self.md01.set_position(self.tar_az, self.tar_el)

    def set_callback(self, callback):
        self.callback = callback

    def _utc_ts(self):
        return "{:s} | MD01 | ".format(datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.%fZ'))

    def set_stop(self):
        self.tar_az = self.status['cur_az']
        self.tar_el = self.status['cur_el']
        self.md01.set_stop()

    def stop_thread(self):
        self.md01.set_stop()
        self.status['connected'] = self.md01.disconnect()
        self.parent.set_md01_con_status(self.status['connected']) #notify main thread of connection
        self._stop.set()

    def stopped(self):
        return self._stop.isSet()
