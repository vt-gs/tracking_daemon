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

import math
import string
import time
import sys
import csv
import os
import datetime

from optparse import OptionParser
from server_thread import *
from main_thread import *

if __name__ == '__main__':
    #--------START Command Line option parser------------------------------------------------------
    usage  = "usage: %prog "
    parser = OptionParser(usage = usage)
    h_serv_ip   = "Set Service IP [default=%default]"
    h_serv_port = "Set Service Port [default=%default]"
    h_md01_ip   = "Set MD01 IP [default=%default]"
    h_md01_port = "Set MD01 Port [default=%default]"
    h_az_thresh = "Set Azimuth Threshold [default=%default]"
    h_el_thresh = "Set Elevation Threshold [default=%default]"
    h_ssid      = "Set Sub-System ID [default=%default]"
    h_poll_rate = "Set MD-01 Poll Rate in seconds [default=%default]"
    
    parser.add_option("", "--serv_ip"  , dest="serv_ip"  , type="string", default="127.0.0.1"    , help=h_serv_ip)
    parser.add_option("", "--serv_port", dest="serv_port", type="int"   , default="2000"         , help=h_serv_port)
    parser.add_option("", "--md01_ip"  , dest="md01_ip"  , type="string", default="192.168.42.21", help=h_md01_ip)
    parser.add_option("", "--md01_port", dest="md01_port", type="int"   , default="2000"         , help=h_md01_port)
    parser.add_option("", "--az_thresh", dest="az_thresh", type="float" , default="4.0"          , help=h_az_thresh)
    parser.add_option("", "--el_thresh", dest="el_thresh", type="float" , default="4.0"          , help=h_el_thresh)
    parser.add_option("", "--ssid"     , dest="ssid"     , type="string", default="VUL"          , help=h_ssid)
    parser.add_option("", "--poll_rate", dest="poll_rate", type="float" , default="0.25"         , help=h_poll_rate)

    (options, args) = parser.parse_args()
    #--------END Command Line option parser------------------------------------------------------    

    #Start Data Server Thread
    serv_thread = ServerThread(options.ssid, options.serv_ip, options.serv_port)
    serv_thread.daemon = True
    #serv.run()# blocking
    serv_thread.start()# non-blocking

    time.sleep(0.1)

    #Start MD01 Thread
    md01_thread = MD01Thread(options.ssid, options.md01_ip, options.md01_port, options.poll_rate, options.az_thresh, options.el_thresh)
    md01_thread.daemon = True
    md01_thread.start() #non-blocking

    time.sleep(0.1)

    #Start Main Thread
    main = MainThread(options.ssid, serv_thread, md01_thread)
    main.daemon = True

    serv_thread.set_callback(main)
    md01_thread.set_callback(main)
    
    main.run()#blocking
    sys.exit()
    

