#!/usr/bin/env python
##################################################
# Title: Data Recording Startup script
# Author: Zach Leffke
# Description: Controls GNU Radio flowgraphs for IQ collection
# Generated: Mar 2019
##################################################


import os
import sys
import string
import serial
import math
import time
import numpy
import argparse
import json
from threading import Thread
from main_thread import *
import datetime as dt


def main(cfg):
    main_thread = Main_Thread(cfg)
    main_thread.daemon = True
    main_thread.run()
    sys.exit()

if __name__ == '__main__':
    startup_ts = dt.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
	#--------START Command Line option parser------------------------------------------------------
    parser = argparse.ArgumentParser(description="VTGS Tracking Daemon",
                                     formatter_class=argparse.ArgumentDefaultsHelpFormatter)

    #General Options
    cwd = os.getcwd()
    #sch_fp_default = '/'.join([cwd, 'schedule'])
    cfg_fp_default = '/'.join([cwd, 'config'])
    parser.add_argument("--cfg_fp"   ,
                        dest   = "cfg_path" ,
                        action = "store",
                        type   = str,
                        default=cfg_fp_default,
                        help   = 'config path')
    parser.add_argument("--cfg_file" ,
                        dest="cfg_file" ,
                        action = "store",
                        type = str,
                        default="fed_vu_config.json" ,
                        help = 'config file')

    args = parser.parse_args()
    #--------END Command Line option parser------------------------------------------------------
    print "args", args
    cfg_fp = '/'.join([args.cfg_path, args.cfg_file])
    print "config file:", cfg_fp
    with open(cfg_fp, 'r') as cfg_f:
        cfg = json.loads(cfg_f.read())

    cfg.update({'startup_ts':startup_ts})
    cfg['service'].update({'ssid':cfg['ssid']})
    cfg['service'].update({'log_path':cfg['log_path']})
    cfg['md01'].update({'ssid':cfg['ssid']})
    cfg['md01'].update({'log_path':cfg['log_path']})
    print json.dumps(cfg, indent=4)

    #print cfg
    #sys.exit()
    main(cfg)
    sys.exit()
