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
import logging

from datetime import datetime as date

from logger import *

class MotionFrame(object):
    def __init__ (self, uid=None, ssid=None, cmd_type=None):
        #Header Fields
        self.uid     = uid       #User ID
        self.ssid    = ssid      #Subsystem ID
        self.type    = cmd_type  #Command Type
        self.cmd     = None   #
        self.az      = None
        self.el      = None
        self.az_rate = None
        self.el_rate = None

class ManagementFrame(object):
    def __init__ (self, uid=None, ssid=None, cmd_type=None):
        #Header Fields
        self.uid    = uid       #User ID
        self.ssid   = ssid      #Subsystem ID
        self.type   = cmd_type  #Command Type
        self.cmd    = None      #Valid Values: START, STOP, QUERY

class VTP_Service_Thread_TCP(threading.Thread):
    def __init__ (self, cfg, parent):
        threading.Thread.__init__(self)
        self._stop      = threading.Event()
        self.cfg        = cfg
        self.parent     = parent

        self.setName(self.cfg['thread_name'])
        self.logger     = logging.getLogger(self.cfg['main_log'])
        self.data_logger = None

        self.ssid       = self.cfg['ssid'].lower()
        self.ip         = self.cfg['ip']
        self.port       = self.cfg['port']

        #Setup Socket
        #self.sock      = socket.socket(socket.AF_INET, socket.SOCK_DGRAM) #UDP Socket
        self.sock       = socket.socket(socket.AF_INET, socket.SOCK_STREAM) #TCP Socket
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1) #To allow socket reuse
        self.sock.settimeout(1)

        self.user_con   = False
        self.frame      = None
        self.valid      = 0     # 0=invalid, 1=Management Frame, 2=Antenna Frame

        self.callback = None # callback to Daemon Main Thread

        self.log_flag = False
        self.log_file = "" #Path to server command log

    def run(self):
        self.logger.info('Launched {:s}'.format(self.name))
        self.sock.bind((self.ip, self.port))
        self.logger.info('Listening for client on [{:s},{:d}]'.format(self.ip, self.port))
        self.sock.listen(1)
        while (not self._stop.isSet()):
            try:
                if self.user_con == False:
                    self.conn, self.addr = self.sock.accept()#Blocking
                    self.logger.info('User connected from [{:s},{:d}]'.format(self.addr[0], self.addr[1]))
                    #self.user_con = True
                    self.set_user_con_status(True)
                elif self.user_con == True:
                    data = self.conn.recvfrom(1024)[0]
                    ts = date.utcnow()
                    if data:
                        data = data.strip()
                        if self.data_logger != None: self.data_logger.info(data)
                        if self.check_frame(data): #True if fully validated frame
                            #Valid FRAME with all checks complete at this point
                            if self.frame.type == 'MOT': #Process Motion Frame
                                self.process_motion(ts)
                            elif self.frame.type == 'MGMT': #Process Management Frame
                                self.process_management(ts)
                        else:
                            self.conn.sendall('INVALID,' + data + '\n')
                    else:
                        self.logger.info('User disconnected from [{:s},{:d}]'.format(self.addr[0], self.addr[1]))
                        self.set_user_con_status(False)

            except Exception as e:
                #print e
                pass

    #### FUNCTIONS CALLED BY MAIN THREAD ####
    def send_management_feedback(self, daemon_state):
        msg = ""
        msg += self.frame.uid + ','
        msg += self.frame.ssid + ','
        msg += self.frame.type + ','
        msg += daemon_state + '\n'
        self.conn.sendall(msg)

    def send_motion_feedback(self, az,el,az_rate,el_rate):
        msg = ""
        msg += self.frame.uid + ','
        msg += self.frame.ssid + ','
        msg += self.frame.type + ','
        msg += 'STATE,'
        msg += '{:3.1f},{:3.1f},{:1.3f},{:1.3f}\n'.format(az,el,az_rate,el_rate)
        self.conn.sendall(msg)

    def start_logging(self, ts):
        self.cfg['log']['startup_ts'] = ts
        #print self.cfg['log']
        setup_logger(self.cfg['log'])
        self.data_logger = logging.getLogger(self.cfg['log']['name']) #main logger
        for handler in self.data_logger.handlers:
            if isinstance(handler, logging.FileHandler):
                self.logger.info("Started {:s} Data Logger: {:s}".format(self.name, handler.baseFilename))

    def stop_logging(self):
        if self.data_logger != None:
            handlers = self.data_logger.handlers[:]
            #print handlers
            for handler in handlers:
                if isinstance(handler, logging.FileHandler):
                    self.logger.info("Stopped Logging: {:s}".format(handler.baseFilename))
                handler.close()
                self.data_logger.removeHandler(handler)
            self.data_logger = None

    #### MAIN THREAD FUNCTION CALLS ####
    def set_user_con_status(self, status):
        #sets user connection status
        self.user_con = status
        self.parent.set_user_con_status(self.user_con)

    def process_motion(self, ts):
        self.parent.motion_frame_received(self, self.frame, ts)

    def process_management(self, ts):
        try:
            self.parent.management_frame_received(self.frame, ts)
        except Exception as e:
            self.logger.warning(sys.exec_info())

    #### LOCAL FUNCTION CALLS ####
    def update_log(self, data, ts):
        self.log_f = open(self.log_file, 'a')
        msg = str(ts) + ','
        msg += data
        msg += '\n'
        self.log_f.write(msg)
        self.log_f.close()

    def check_frame(self, data):
        #validates header field of received frame.
        uid     = None
        ssid    = None
        frame_type = None
        try: #look for generic exception
            fields = data.split(",")
            msg = 'INVALID: '
            if len(fields) < 4:
                self.logger.info('Invalid number of fields in frame: {:d}'.format(len(fields)))
                return False
            else:
                #validate USERID, this will always be accepted and will probably never be excepted
                try:
                    uid = str(fields[0])  #typecast first field to string and assign to request object
                except:
                    self.logger.info('Could not assign User ID: {:s}'.format(fields[0]))
                    return False

                #Validate SSID
                ssid = str(fields[1]).strip().lower()  #typecast to string, remove whitespace, force to uppercase
                if ssid != self.ssid:
                    self.logger.info('Invalid SSID: \'{:s}\' (user) != \'{:s}\' (self)'.format(ssid, self.ssid))
                    return False

                #Validate frame TYPE
                frame_type = str(fields[2]).strip().upper()
                if ((frame_type != 'MGMT') and (frame_type != 'MOT')):
                    self.logger.info('Invalid Frame Type: \'{:s}\' from user'.format(frame_type))
                    return False

        except Exception as e:
            self.logger.warning('Unknown Exception: \'{:s}\''.format(self.utc_ts(), e))
            return False

        del self.frame

        if frame_type == 'MGMT':
            self.frame = ManagementFrame(uid, ssid, frame_type)
            return self.check_management_frame(fields)
        elif frame_type == 'MOT':
            self.frame = MotionFrame(uid, ssid, frame_type)
            return self.check_motion_frame(fields)
        else:
            return False

    def check_motion_frame(self, fields):
        cmd = None
        az  = None
        el  = None
        try:
            cmd = fields[3].strip().upper()
            if ((cmd != 'SET') and (cmd != 'GET') and (cmd != 'STOP')):
                self.logger.info('Invalid Motion Frame Command: \'{:s}\' from user \'{:s}\''.format(cmd, self.frame.uid))
                self.logger.info("Valid MOT Commands: \'SET\', \'GET\', \'STOP\'")
                return False

            if cmd == 'SET':  #get the Commanded az/el angles
                if len(fields) < 6:
                    self.logger.info('Invalid number of fields in \'SET\' Command: \'{:s}\' from user \'{:s}\''.format(str(len(fields)), self.frame.uid))
                try:
                    az = float(fields[4].strip())
                    el = float(fields[5].strip())
                except:
                    self.logger.info('Invalid data types in az/el fields of \'SET\' Command from user \'{:s}\''.format(self.frame.uid))

        except Exception as e:
            self.logger.info('Unknown Exception: \'{:s}\''.format(e))
            return False

        self.frame.cmd = cmd
        self.frame.az = az
        self.frame.el = el
        return True


    def check_management_frame(self, fields):
        #Check fourth field for valid command
        cmd = None
        try:
            cmd = fields[3].strip().upper()
            if ((cmd != 'START') and (cmd != 'STOP') and (cmd != 'QUERY')):
                self.logger.info('Invalid Management Frame Command: \'{:s}\' from user \'{:s}\''.format(cmd, self.frame.uid))
                self.logger.info("Valid MGMT Commands: \'START\', \'STOP\', \'QUERY\'")
                return False

        except Exception as e:
            self.logger.info('Unknown Exception: \'{:s}\''.format(e))
            return False

        self.frame.cmd = cmd
        return True

    def utc_ts(self):
        return str(date.utcnow()) + " UTC | SERV | "

    def stop(self):
        self.logger.info('{:s} Terminating...'.format(self.name))
        self._stop.set()

    def stopped(self):
        return self._stop.isSet()
