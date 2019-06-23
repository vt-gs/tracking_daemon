#!/usr/bin/env python2

# Logger utilities

import math, sys, os, time, struct, traceback, binascii, logging
import datetime as dt

class MyFormatter(logging.Formatter):
    #Overriding formatter for datetime
    converter=dt.datetime.utcfromtimestamp
    def formatTime(self, record, datefmt=None):
        ct = self.converter(record.created)
        if datefmt:
            s = ct.strftime(datefmt)
        else:
            t = ct.strftime("%Y%m%dT%H:%M:%SZ")
            s = "%s,%03d" % (t, record.msecs)
        return s


def setup_logger(log_name, path, level=logging.INFO, ts = None):
    l = logging.getLogger(log_name)
    if ts == None: ts = str(get_uptime())
    log_file = "{:s}_{:s}.log".format(log_name, ts)
    log_path = '/'.join([path, log_file])
    #log_path = os.getcwd() + '/log/' + log_file
    print log_path
    formatter = MyFormatter(fmt='%(asctime)s | %(threadName)s | %(levelname)s | %(message)s',datefmt='%Y-%m-%dT%H:%M:%S.%fZ')
    #fileHandler = logging.FileHandler(log_path, mode='w')
    fileHandler = logging.FileHandler(log_path)
    fileHandler.setFormatter(formatter)
    #streamHandler = logging.StreamHandler()
    #streamHandler.setFormatter(formatter)
    l.setLevel(level)
    l.addHandler(fileHandler)
    l.info('Logger Initialized')
    #l.addHandler(streamHandler)
    return fileHandler
