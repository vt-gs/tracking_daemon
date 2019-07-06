#!/usr/bin/env python
#################################################



import threading
import os
import math
import sys
import string
import time
import socket
import datetime
import json
from Queue import Queue
from logger import *
from watchdog_timer import *



class Service_Thread(threading.Thread):
    """
    Title: Tracking Daemon, Service Thread
    Project: VTGS Tracking Daemon
    Version: 1.0
    Date: June 2019
    Author: Zach Leffke, KJ4QLP

    Purpose:
        Handles Tracking Service interface to client
        For now is only TCP/IP socket connection.

    Args:
        cfg - Configurations for thread, dictionary format.
        logger - Logger passed from main thread.
        parent - parent thread, used for callbacks

    """
    def __init__ (self, cfg, logger, parent = None):
        threading.Thread.__init__(self, name = 'ServThread')
        self._stop  = threading.Event()
        self.cfg    = cfg
        self.logger = logger #Main logger for high level event logging
        self.parent = parent # callback to Daemon Main Thread

        print self._utc_ts() + "Initializing {:s} Service Thread".format(self.cfg['ssid'])
        self.logger.info("Initializing {:s} Service Thread".format(self.cfg['ssid']))

        self.ssid       = self.cfg['ssid']
        self.ip         = self.cfg['ip']
        self.port       = self.cfg['port']
        self.timeout    = self.cfg['timeout']
        self.wd_timeout = self.cfg['watchdog_interval']

        self.rx_q = Queue() #Commands received from user
        self.tx_q = Queue() #Telemetry for user

        self.watchdog = Watchdog(self.wd_timeout, self._watchdog_event)
        self.user_con   = False
        self.daemon_state = "BOOT"


    def run(self):
        print self._utc_ts() + "{:s} Service Thread Started".format(self.cfg['ssid'])
        self.logger.info("{:s} Service Thread Started".format(self.cfg['ssid']))
        #Setup Socket
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM) #TCP Socket
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1) #To allow socket reuse
        self.sock.bind((self.ip, self.port))
        self.sock.listen(1) #non-Blocking
        #print self._utc_ts() + "Listening for client on: [{:s}:{:d}]".format(self.ip, self.port)
        #self.logger.info("Listening for client on: [{:s}:{:d}]".format(self.ip, self.port))
        while (not self._stop.isSet()):
            try:
                if self.user_con == False:
                    #reset and wait for new connection
                    print self._utc_ts() + "Listening for client on: [{:s}:{:d}]".format(self.ip, self.port)
                    self.logger.info("Listening for client on: [{:s}:{:d}]".format(self.ip, self.port))
                    #Block until User Connects
                    self.conn, self.client = self.sock.accept()#Blocking
                    self._Handle_Client_Connect()

                elif self.user_con == True:
                    data = self.conn.recvfrom(1024)[0]  #blocking?
                    if data == '':
                        self._Handle_Client_Disconnect()
                    else:
                        data = data.strip()
                        ts = datetime.datetime.utcnow()
                        if self._Check_RX_Message(data, ts): #True if fully validated frame
                            print 'serv', type(self.rx_msg), self.rx_msg
                            self.rx_q.put(self.rx_msg)
                        else: #bad msg format
                            #send some kind of NACK feedback
                            #self.conn.sendall('INVALID,' + data + '\n')
                            pass
            except socket.timeout: #Timout, No USer Data
                self._Handle_Socket_Timeout()
            except Exception as e:
                print self._utc_ts() + "Unhandled Exception: {:s}".format(str(e))
                self.logger.info("Unhandled Exception: {:s}".format(str(e)))



    #### FUNCTIONS CALLED BY MAIN THREAD ####
    def start_logging(self, ts, session_id):
        log_name = 'trackd_{:s}_{:s}'.format(self.cfg['ssid'], self.name.lower())
        self.msg_log_fh = setup_logger(log_name,
                                    path=self.cfg['log_path'],
                                    ts=ts)
        self.msg_logger = logging.getLogger(log_name) #main logger

        print self._utc_ts() + "Setup Session Logger: {:s}".format(session_id)
        self.msg_logger.info("Session ID: {:s}".format(session_id))

        print self._utc_ts() + 'Started Logging: ' + self.msg_logger.handlers[-1].baseFilename
        self.logger.info("Started Logging: {:s}".format(self.msg_logger.handlers[-1].baseFilename))

    def stop_logging(self):
        print self._utc_ts() + 'Stopped Logging: ' + self.msg_logger.handlers[-1].baseFilename
        self.logger.info("Stopped Logging: {:s}".format(self.msg_logger.handlers[-1].baseFilename))
        self.msg_logger.removeHandler(self.msg_logger.handlers[-1])

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

    #### FUNCTION CALLS TO MAIN THREAD ####
    def _set_user_con_status(self, status):
        #sets user connection status
        self.user_con = status
        self.parent.set_user_con_status(self.user_con)




    def process_motion(self, ts):
        self.callback.motion_frame_received(self, self.frame, ts)

    def process_management(self, ts):
        self.callback.management_frame_received(self, self.frame, ts)

    def set_callback(self, callback):
        #callback function leads to main thread.
        self.callback = callback


    #### LOCAL FUNCTION CALLS ####
    def _Handle_Client_Connect(self):
        self.conn.settimeout(self.timeout) #Make the connection non-blocking so we can send data
        print self._utc_ts() + "User connected from: [{:s}:{:d}]".format(self.client[0], self.client[1])
        self.logger.info("User connected from: [{:s}:{:d}]".format(self.client[0], self.client[1]))
        print self._utc_ts() + "Starting user activity watchdog: {:3.3f} sec".format(self.wd_timeout)
        self.logger.info("Starting user activity watchdog: {:3.3f} sec".format(self.wd_timeout))
        self.watchdog = Watchdog(self.wd_timeout, self._watchdog_event) #re-initiliaze watchdog
        self.watchdog.start() #start the watchdog, if nothing happens, reset connection
        #generate session id and log it
        #self.session_id = uuid.uuid4()
        #print self._utc_ts() + "Started Session ID: {:s}".format(self.session_id)
        #self.logger.info("Started Session ID: {:s}".format(self.session_id))
        #start session logger
        #self._start_logging()
        #set user connection status
        self._set_user_con_status(True)
        #self.conn.sendall(json.dumps({'session_id':str(self.session_id)})+'\n')



    def _Handle_Client_Disconnect(self):

        print self._utc_ts() + "User disconnected from: [{:s}:{:d}]".format(self.client[0], self.client[1])
        self.logger.info("User disconnected from: [{:s}:{:d}]".format(self.client[0], self.client[1]))
        #stop session logger and watchdog
        self.watchdog.stop() #stop watchdog
        #self._stop_logging()
        #print self._utc_ts() + "Stopped Session ID: {:s}".format(self.session_id)
        #self.logger.info("Stopped Session ID: {:s}".format(self.session_id))
        #self.session_id  = None
        #set user connection status
        self._set_user_con_status(False)
        #close the socket
        self.conn.close()

    def _watchdog_event(self):
        print self._utc_ts() + "Watchdog Expired, no user activity for {:3.3f} seconds".format(self.wd_timeout)
        self.logger.info("Watchdog Expired, no user activity for {:3.3f} seconds".format(self.wd_timeout))
        self._Handle_Client_Disconnect()

    def _Handle_Socket_Timeout(self):
        #Should only happen after user has connected, but is not sending data
        if self.user_con: #USer is connected, see about sending feedback
            #print "TIMEOUT"
            if not self.tx_q.empty(): #something in transmission Queue for User
                msg = self.tx_q.get()
                print 'out of q', msg
                #msg.update({'ts':msg['ts'].strftime('%Y-%m-%dT%H:%M:%S.%fZ')})
                self._Send_Feedback(msg)




    def _Check_RX_Message(self, data, ts):
        print self._utc_ts() + "Received user data, resetting watchdog: {:3.3f} sec".format(self.wd_timeout)
        self.logger.info("Received user data, resetting watchdog: {:3.3f} sec".format(self.wd_timeout))
        self.watchdog.reset()
        rx_ts = ts.strftime('%Y-%m-%dT%H:%M:%S.%fZ')
        try:
            msg = json.loads(data)
            msg.update({'rx_ts':rx_ts})
            #msg.update({'session_id':str(self.session_id)})
            #self.msg_logger.info("Received VALID JSON from [{:s}:{:d}]: {:s}".format(self.client[0], self.client[1], json.dumps(msg)))
            self.rx_msg = msg
            return True
        except Exception as e:
            print e
            print self._utc_ts() + "{:s} from [{:s}:{:d}]: {:s}".format(str(e), self.client[0], self.client[1], str(data))
            #self.msg_logger.info("{:s} from [{:s}:{:d}]: {:s}".format(str(e), self.client[0], self.client[1], str(data)))
            return False

    def _Send_Feedback(self, msg):
        msg.update({'tx_ts':datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.%fZ')})
        print msg
        self.conn.sendall(json.dumps(msg))
        #self.msg_logger.info(json.dumps(msg))
        pass

    def stop(self):
        print self._utc_ts() + "Terminating Service Thread..."
        self.logger.warning("Terminating Service Thread...")
        self._stop.set()
        #sys.quit()

    def stopped(self):
        return self._stop.isSet()

    def _utc_ts(self):
        return "{:s} | serv | ".format(datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.%fZ'))

##################OLD CLASS KEEPING FOR REFERENCE FOR NOW#############################

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

class Service_Thread_OLD(threading.Thread):
    """ docstring """
    def __init__ (self, cfg, logger):
        threading.Thread.__init__(self, name = 'Service')
        self._stop  = threading.Event()
        self.cfg    = cfg
        self.ssid   = self.cfg['ssid']
        self.ip     = self.cfg['ip']
        self.port   = self.cfg['port']
        self.logger = logger

        self.rx_q = Queue() #Commands received from user
        self.tx_q = Queue() #Telemetry for user

        self.user_con   = False
        self.frame      = None
        self.valid      = 0     # 0=invalid, 1=Management Frame, 2=Antenna Frame

        self.callback = None # callback to Daemon Main Thread
        self.daemon_state = "BOOT"

        self.log_flag = False
        self.log_file = "" #Path to server command log










    def run(self):
        print self.utc_ts() + "{:s} Service Thread Started".format(self.cfg['ssid'])
        self.logger.info("{:s} Service Thread Started".format(self.cfg['ssid']))
        #Setup Socket
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM) #TCP Socket
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1) #To allow socket reuse
        self.sock.settimeout(1)
        self.sock.bind((self.ip, self.port))
        print self.utc_ts() + "Listening for client on: [{:s}:{:d}]".format(self.ip, self.port)
        self.logger.info("Listening for client on: [{:s}:{:d}]".format(self.ip, self.port))
        self.sock.listen(1)
        while (not self._stop.isSet()):
            try:
                if self.user_con == False:
                    self.conn, self.addr = self.sock.accept()#Blocking
                    #print self.utc_ts() + "User connected from: " + str(self.addr)
                    print self.utc_ts() + "User connected from: [{:}]".format(self.addr)
                    self.logger.info("User connected from: [{:}]".format(self.addr))
                    #self.user_con = True
                    self.set_user_con_status(True)
                elif self.user_con == True:
                    data = self.conn.recvfrom(1024)[0]
                    ts = datetime.datetime.utcnow()
                    if self.log_flag: self.update_log(data,ts)
                    if data:
                        data = data.strip()
                        #print self.utc_ts() + "User Message: " + str(data)
                        #self.valid = self.check_frame(data)
                        if self.check_frame(data): #True if fully validated frame
                            #Valid FRAME with all checks complete at this point
                            if self.frame.type == 'MOT': #Process Motion Frame
                                self.process_motion(ts)
                            elif self.frame.type == 'MGMT': #Process Management Frame
                                self.process_management(ts)
                        else:
                            self.conn.sendall('INVALID,' + data + '\n')
                    else:
                        print self.utc_ts() + "User disconnected from: " + str(self.addr)
                        #self.user_con = False
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
        self.log_flag = True
        self.log_file = "./log/"+ ts + "_" + self.ssid + "_VTP.log"
        self.log_f = open(self.log_file, 'a')
        msg = "Timestamp [UTC],Received Message\n"
        self.log_f.write(msg)
        self.log_f.close()

        print self.utc_ts() + 'Started Logging: ' + self.log_file

    def stop_logging(self):
        if self.log_flag == True:
            self.log_flag = False
            print self.utc_ts() + 'Stopped Logging: ' + self.log_file


    #### MAIN THREAD FUNCTION CALLS ####
    def set_user_con_status(self, status):
        #sets user connection status
        self.user_con = status
        self.callback.set_user_con_status(self.user_con)

    def process_motion(self, ts):
        self.callback.motion_frame_received(self, self.frame, ts)

    def process_management(self, ts):
        self.callback.management_frame_received(self, self.frame, ts)

    def set_callback(self, callback):
        #callback function leads to main thread.
        self.callback = callback


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
                print self.utc_ts() + 'Invalid number of fields in frame: ', len(fields)
                return False
            else:
                #validate USERID, this will always be accepted and will probably never be excepted
                try:
                    uid = str(fields[0])  #typecast first field to string and assign to request object
                except:
                    print self.utc_ts() + 'Could not assign User ID: ', fields[0]
                    #self.conn.sendall(msg + data)
                    return False

                #Validate SSID
                ssid = str(fields[1]).strip().upper()  #typecast to string, remove whitespace, force to uppercase
                if ssid != self.ssid:
                    print '{:s}Invalid SSID: \'{:s}\' from user \'{:s}\''.format(self.utc_ts(), ssid, self.req.uid)
                    print self.utc_ts() + "This is the VUL Tracking Daemon"
                    #self.conn.sendall(msg+data)
                    return False
                #else:
                #    self.req.ssid = ssid

                #Validate frame TYPE
                frame_type = str(fields[2]).strip().upper()
                if ((frame_type != 'MGMT') and (frame_type != 'MOT')):
                    print '{:s}Invalid Frame Type: \'{:s}\' from user \'{:s}\''.format(self.utc_ts(), frame_type, self.req.uid)
                    print self.utc_ts() + "Valid Frame Types: \'MOT\'=Motion Frame, \'MGMT\'=Management Frame"
                    #self.Serviceconn.sendall(msg+data)
                    return False
                #else:
                #    self.req.type = frame_type

        except Exception as e:
            print '{:s}Unknown Exception: \'{:s}\''.format(self.utc_ts(), e)
            #self.conn.sendall(msg+data)
            return False

        del self.frame
        #self.frame = None

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
                print '{:s}Invalid Motion Frame Command: \'{:s}\' from user \'{:s}\''.format(self.utc_ts(), cmd, self.frame.uid)
                print self.utc_ts() + "Valid MOT Commands: \'SET\', \'GET\', \'STOP\'"
                return False

            if cmd == 'SET':  #get the Commanded az/el angles
                if len(fields) < 6:
                    print '{:s}Invalid number of fields in \'SET\' Command: \'{:s}\' from user \'{:s}\''.format(self.utc_ts(), str(len(fields)), self.frame.uid)
                try:
                    az = float(fields[4].strip())
                    el = float(fields[5].strip())
                except:
                    print '{:s}Invalid data types in az/el fields of \'SET\' Command from user \'{:s}\''.format(self.utc_ts(), self.frame.uid)

        except Exception as e:
            print '{:s}Unknown Exception: \'{:s}\''.format(self.utc_ts(), e)
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
                print '{:s}Invalid Management Frame Command: \'{:s}\' from user \'{:s}\''.format(self.utc_ts(), cmd, self.frame.uid)
                print self.utc_ts() + "Valid MGMT Commands: \'START\', \'STOP\', \'QUERY\'"
                return False

        except Exception as e:
            print '{:s}Unknown Exception: \'{:s}\''.format(self.utc_ts(), e)
            return False

        self.frame.cmd = cmd
        return True

    def utc_ts(self):
        return "{:s} | serv | ".format(datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.%fZ'))

    def stop(self):
        print self.utc_ts() + "Terminating Service Thread..."
        self.logger.warning("Terminating Service Thread...")
        self._stop.set()
        #sys.quit()

    def stopped(self):
        return self._stop.isSet()
