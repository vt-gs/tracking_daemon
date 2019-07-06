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




def main():
    """ Main entry point to start the service. """

    startup_ts = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    #--------START Command Line argument parser------------------------------------------------------
    parser = argparse.ArgumentParser(description="RF Frond End Control Daemon",
                                     formatter_class=argparse.ArgumentDefaultsHelpFormatter)

    cwd = os.getcwd()
    cfg_fp_default = '/'.join([cwd, 'config'])
    cfg = parser.add_argument_group('Daemon Configuration File')
    cfg.add_argument('--cfg_path',
                       dest='cfg_path',
                       type=str,
                       default='/'.join([os.getcwd(), 'config']),
                       help="Daemon Configuration File Path",
                       action="store")
    cfg.add_argument('--cfg_file',
                       dest='cfg_file',
                       type=str,
                       default="rffe_config_fed-vu.json",
                       help="Daemon Configuration File",
                       action="store")

    args = parser.parse_args()
    #--------END Command Line argument parser------------------------------------------------------
    os.system('reset')
    fp_cfg = '/'.join([args.cfg_path,args.cfg_file])
    if not os.path.isfile(fp_cfg) == True:
        print 'ERROR: Invalid Configuration File: {:s}'.format(fp_cfg)
        sys.exit()
    print 'Importing configuration File: {:s}'.format(fp_cfg)
    with open(fp_cfg, 'r') as json_data:
        cfg = json.load(json_data)
        json_data.close()
    cfg['startup_ts'] = startup_ts

    log_name = '.'.join([cfg['ssid'],cfg['daemon_name'],'main'])
    cfg['main_log'].update({
        "path":cfg['log_path'],
        "name":log_name,
        "startup_ts":startup_ts
    })

    for key in cfg['thread_enable'].keys():
        cfg[key].update({'log':{}})
        log_name =  '.'.join([cfg['ssid'],cfg['daemon_name'],cfg[key]['name']])
        cfg[key].update({
            'ssid':cfg['ssid'],
            'main_log':cfg['main_log']['name']
        })
        cfg[key]['log'].update({
            'path':cfg['log_path'],
            'name':log_name,
            'startup_ts':startup_ts,
            'verbose':cfg['main_log']['verbose'],
            'level':cfg['main_log']['level']
        })

    print json.dumps(cfg, indent=4)

    main_thread = Main_Thread(cfg, name="Main_Thread")
    main_thread.daemon = True
    main_thread.run()
    sys.exit()















if __name__ == '__main__':
    main()



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
