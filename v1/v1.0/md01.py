#!/usr/bin/env python
#################################################
#   Title: MD01 Class                           #
# Project: VTGS Tracking Daemon                 #
# Version: 3.                                   #
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

import socket
import os
import string
import sys
import time
import threading
import binascii
import datetime
import logging
import numpy

class md01(object):
    """docstring for ."""
    def __init__ (self, cfg, logger, name='md01'):
        self.cfg        = cfg
        self.logger     = logger
        self.name       = name

        print self._utc_ts() + "Initializing {:s} MD01 Interface".format(self.cfg['ssid'])
        self.logger.info("Initializing {:s} MD01 Interface".format(self.cfg['ssid']))

        self.ip         = self.cfg['ip']        #IP Address of MD01 Controller
        self.port       = self.cfg['port']      #Port number of MD01 Controller
        self.timeout    = self.cfg['timeout']   #Socket Timeout interval, default = 1.0 seconds
        self.ssid       = self.cfg['ssid']

        self.connected  = False
        self.cmd_az     = 0         #Commanded Azimuth, used in Set Position Command
        self.cmd_el     = 0         #Commanded Elevation, used in Set Position command
        self.cur_az     = 0         #  Current Azimuth, in degrees, from feedback
        self.cur_el     = 0         #Current Elevation, in degrees, from feedback
        self.ph         = 10        #  Azimuth Resolution, in pulses per degree, from feedback, default = 10
        self.pv         = 10        #Elevation Resolution, in pulses per degree, from feedback, default = 10
        self.feedback   = ''        #Feedback data from socket

        self.status = {
            'ts': None,
            'connected':False,
            'cur_az': 0.0,
            'cur_el':0.0
        }

        self.stop_cmd   = bytearray()   #Stop Command Message
        self.status_cmd = bytearray()   #Status Command Message
        self.set_cmd    = bytearray()   #Set Command Message
        for x in [0x57,0,0,0,0,0,0,0,0,0,0,0x0F,0x20]: self.stop_cmd.append(x)
        for x in [0x57,0,0,0,0,0,0,0,0,0,0,0x1F,0x20]: self.status_cmd.append(x)
        for x in [0x57,0,0,0,0,0x0a,0,0,0,0,0x0a,0x2F,0x20]: self.set_cmd.append(x) #PH=PV=0x0a, 0x0a = 10, BIG-RAS/HR is 10 pulses per degree

    def _utc_ts(self):
        return "{:s} | md01 | ".format(datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.%fZ'))

    def connect(self):
        #connect to md01 controller
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM) #TCP Socket
        self.sock.settimeout(self.timeout)   #set socket timeout
        try:
            self.sock.connect((self.ip, self.port))
            time.sleep(0.1)
            self.connected = True
            self.status['connected'] = self.connected
            self.status['ts'] = None #clear rx timestamp
            #self.logger.info("Connected to MD01 at: [{:s}:{:d}]".format(self.ip, self.port))
            return self.connected
        except socket.error as msg:
            #self.logger.info("Failed to connected to MD01 at [{:s}:{:d}]: {:s}".format(self.ip, self.port, msg))
            self.sock.close()
            self.connected = False
            self.status['connected'] = self.connected
            self.status['ts'] = None #clear rx timestamp
            return self.connected

    def disconnect(self):
        #disconnect from md01 controller
        #print self.getTimeStampGMT() + "MD01 |  Attempting to disconnect from MD01 Controller"
        self.sock.shutdown(socket.SHUT_RDWR)
        self.sock.close()
        self.connected = False
        self.status['connected'] = self.connected
        self.status['ts'] = None #clear rx timestamp
        print self._utc_ts() + "Disconnected from {:s} MD01 Controller".format(self.ssid)
        self.logger.info("Disconnected from {:s} MD01 Controller".format(self.ssid))
        return self.connected

    def get_status(self):
        #get azimuth and elevation feedback from md01
        if self.connected == False:
            return self._set_bad_status()
        else:
            try:
                #print 'sending STATUS'
                self.sock.send(self.status_cmd)
                #print self._utc_ts() + 'Sent \'GET\' command to MD01'
                self.feedback = self._recv_data()
                #print binascii.hexlify(self.feedback)
                self._convert_feedback()
            except socket.error as e:
                self._Handle_Socket_Exception(e)
            return self.status #return 0 good status, feedback az/el

    def set_stop(self):
        #stop md01 immediately
        if self.connected == False:
            self._set_bad_status()
        else:
            try:
                self.sock.send(self.stop_cmd)
                print self._utc_ts() + 'Sent \'STOP\' command to MD01'
                self.logger.info('Sent \'STOP\' command to MD01')
                self.feedback = self._recv_data()
                self._convert_feedback()
            except socket.error as e:
                self._Handle_Socket_Exception(e)
            return self.status #return 0 good status, feedback az/el

    def set_position(self, az, el):
        #set azimuth and elevation of md01
        self.cmd_az = az
        self.cmd_el = el
        self._format_set_cmd()
        if self.connected == False:
            return self._set_bad_status
        else:
            try:
                self.sock.send(self.set_cmd)
                print self._utc_ts() + 'Sent \'SET\' command to MD01: AZ={:3.1f}, EL={:3.1f}'.format(self.cmd_az, self.cmd_el)
                self.logger.info('Sent \'SET\' command to MD01: AZ={:3.1f}, EL={:3.1f}'.format(self.cmd_az, self.cmd_el))
                #Set Position command does not get a feedback response from MD-01
            except socket.error as msg:
                self._Handle_Socket_Exception(e)
            return self.status #return 0 good status, feedback az/el

    #### PRIVATE FUNCTION CALLS ####
    def _Handle_Socket_Exception(self, e):
        self.logger.info("Socket Exception Thrown: {:s}".format(str(e)))
        self.logger.info("Shutting Down Socket...")
        self.sock.close()
        self._set_bad_status()

    def _set_bad_status(self):
        print self._utc_ts() + 'bad status'
        self.status['ts'] = None
        self.status['connected'] = False
        self.status['cur_az'] = 0.0
        self.status['cur_el'] = 0.0
        return self.status

    def _recv_data(self):
        #reset RX Timestamp
        self.status['ts'] = None
        self.status['connected'] = True
        #receive socket data
        feedback = ''
        while True: #cycle through recv buffer
            c = self.sock.recv(1)
            #print c, binascii.hexlify(c)
            if binascii.hexlify(c) == '57': # Start Flag detected
            #if c == 0x57: # Start Flag detected
                #print 'ping'
                if self.status['ts'] == None: #set timestamp on first valid character
                    self.status['ts'] = datetime.datetime.utcnow()
                feedback += c
                flag = True
                while flag: #continue cycling through receive buffer
                    c = self.sock.recv(1)
                    #print c, binascii.hexlify(c)
                    if binascii.hexlify(c) == '20':
                    #if c == 0x20:
                        feedback += c
                        flag = False
                    else:
                        feedback += c
                break
        #print binascii.hexlify(feedback)
        return feedback

    def _convert_feedback(self):
        h1 = ord(self.feedback[1])
        h2 = ord(self.feedback[2])
        h3 = ord(self.feedback[3])
        h4 = ord(self.feedback[4])
        #print h1, h2, h3, h4
        self.status['cur_az'] = (h1*100.0 + h2*10.0 + h3 + h4/10.0) - 360.0
        #print self.status['cur_az']
        self.ph = ord(self.feedback[5])

        v1 = ord(self.feedback[6])
        v2 = ord(self.feedback[7])
        v3 = ord(self.feedback[8])
        v4 = ord(self.feedback[9])
        self.status['cur_el'] = (v1*100.0 + v2*10.0 + v3 + v4/10.0) - 360.0
        #print self.status['cur_el']
        self.pv = ord(self.feedback[10])
        #print self.status

    def _format_set_cmd(self):
        #make sure cmd_az in range -180 to +540
        if   (self.cmd_az>540): self.cmd_az = 540
        elif (self.cmd_az < -180): self.cmd_az = -180
        #make sure cmd_el in range 0 to 180
        if   (self.cmd_el < 0): self.cmd_el = 0
        elif (self.cmd_el>180): self.cmd_el = 180
        #convert commanded az, el angles into strings
        cmd_az_str = str(int((float(self.cmd_az) + 360) * self.ph))
        cmd_el_str = str(int((float(self.cmd_el) + 360) * self.pv))
        #print target_az, len(target_az)
        #ensure strings are 4 characters long, pad with 0s as necessary
        if   len(cmd_az_str) == 1: cmd_az_str = '000' + cmd_az_str
        elif len(cmd_az_str) == 2: cmd_az_str = '00'  + cmd_az_str
        elif len(cmd_az_str) == 3: cmd_az_str = '0'   + cmd_az_str
        if   len(cmd_el_str) == 1: cmd_el_str = '000' + cmd_el_str
        elif len(cmd_el_str) == 2: cmd_el_str = '00'  + cmd_el_str
        elif len(cmd_el_str) == 3: cmd_el_str = '0'   + cmd_el_str
        #print target_az, len(str(target_az)), target_el, len(str(target_el))
        #update Set Command Message
        self.set_cmd[1] = cmd_az_str[0]
        self.set_cmd[2] = cmd_az_str[1]
        self.set_cmd[3] = cmd_az_str[2]
        self.set_cmd[4] = cmd_az_str[3]
        self.set_cmd[5] = self.ph
        self.set_cmd[6] = cmd_el_str[0]
        self.set_cmd[7] = cmd_el_str[1]
        self.set_cmd[8] = cmd_el_str[2]
        self.set_cmd[9] = cmd_el_str[3]
        self.set_cmd[10] = self.pv
