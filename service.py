#!/usr/bin/env python
# -*- coding: utf-8 -*-

import win32service, win32serviceutil, win32api, win32con, win32event, win32evtlogutil
import psutil
import subprocess
import os, sys, string, time, socket, signal, json
import servicemanager

import logging
import logging.handlers

from observe import main as observe_main
from utils import is_dir, is_file, resource_path, suppress_stdout_stderr


logger = logging.getLogger()
def configure_logger(level=logging.DEBUG):
    # CRITICAL 50
    # ERROR 40
    # WARNING 30
    # INFO 20
    # DEBUG 10
    # NOTSET 0

    if len(logger.handlers):
        logger.handlers = []

    if os.name == 'nt':
        logging_dir = os.path.join(os.environ["APPDATA"], "SmartPart")
        logging_path = os.path.join(logging_dir, "instapart.log")
        if not os.path.exists(logging_dir):
            os.mkdir(logging_dir)

        handler = logging.handlers.RotatingFileHandler(logging_path, maxBytes=5*1024*1024)
        formatter = logging.Formatter("%(asctime)s %(levelname)-8s %(message)s")
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    logger.setLevel(level)


class Service (win32serviceutil.ServiceFramework):
    _svc_name_ = 'batchUnfolderService'
    _svc_display_name_ = 'Batch Unfolder Service'
    _svc_description_ = 'Batch Unfolder is a tool made by SmartPart BV to automatically process CAD files for production.'

    def __init__(self,args):
        win32serviceutil.ServiceFramework.__init__(self, *args)
        self.log('Service Initialized.')
        self.stop_event = win32event.CreateEvent(None, 0, 0, None)
        socket.setdefaulttimeout(60)


    def log(self, msg):
        # servicemanager.LogInfoMsg(str(msg))
        logger.info(str(msg))

    def sleep(self, sec):
        win32api.Sleep(sec*1000, True)

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        self.stop()
        self.log('Service is stopping.')
        win32event.SetEvent(self.stop_event)
        self.ReportServiceStatus(win32service.SERVICE_STOPPED)

    def SvcDoRun(self):
        self.ReportServiceStatus(win32service.SERVICE_START_PENDING)
        try:
            self.ReportServiceStatus(win32service.SERVICE_RUNNING)
            self.log('Service is starting.')
            self.main()
            win32event.WaitForSingleObject(self.stop_event, win32event.INFINITE)
            servicemanager.LogMsg(servicemanager.EVENTLOG_INFORMATION_TYPE,servicemanager.PYS_SERVICE_STARTED,(self._svc_name_, ''))
        except Exception as e:
            s = str(e);
            self.log('Exception :' + s)
            self.SvcStop()

    def stop(self):
        self.runflag = False
        try:
            pass

        except Exception as e:
            self.log(str(e))

    def main(self):
        self.runflag = True

        while self.runflag:
            try:
                config_file = is_file(resource_path("settings.json"), allowed_extensions=["json"])
                with open(config_file, 'r') as json_file:
                    config = json.load(json_file)

                settings = {"directory": None}

                if "default" in config:
                        settings.update(config["default"])

                if "service" in config:
                    settings.update(config["service"])

                directory_path = is_dir(resource_path(settings["directory"]), raise_exceptions=False)

                if directory_path:
                    with suppress_stdout_stderr():
                        observe_main(directory_path)

            except Exception as e:
                self.log(str(e))

def main():
    from cryptlex.lexactivator import LexActivator, LexStatusCodes, PermissionFlags, LexActivatorException
    LexActivator.SetProductFile(resource_path("product_v38505766-362d-47bf-a0a1-02c677e7124c.dat"))
    LexActivator.SetProductId("38505766-362d-47bf-a0a1-02c677e7124c", PermissionFlags.LA_USER);

    if len(sys.argv) == 1:
        configure_logger()
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(Service)
        servicemanager.StartServiceCtrlDispatcher()

    else:
        win32serviceutil.HandleCommandLine(Service)