#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import sys
import json
import time
import logging
from multiprocessing import Process
from threading import Thread

try:
   from queue import Queue
except ImportError:
   from Queue import Queue

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import xml.etree.ElementTree as ET

import traceback

import subprocess


from utils import is_dir, is_file, is_step_file, is_xml_file, resource_path, suppress_stdout_stderr
from activate import check_license

from auto import main as auto_main

import logging
logger = logging.getLogger()
file_queue = Queue()

class QueueEventHandler(FileSystemEventHandler):
    '''Watches a specific folder and raises events on_created and on_deleted'''
    def __init__(self, queue_mgr, *args, **kwargs):
        super(QueueEventHandler, self).__init__(*args, **kwargs)
        self.queue_mgr = queue_mgr

    def on_created(self, event):
        '''
        Handles on_created event. Checks that created thing is a file (not a folder) and adds it to a file_queue
        :param event:
        :return:
        '''
        super(QueueEventHandler, self).on_created(event)
        if not event.is_directory:
            logging.info("New file: {}".format(event.src_path))
            file_queue.put_nowait(event.src_path)
            self.queue_mgr.process_file_queue()

    def on_deleted(self, event):
        pass

    def on_modified(self, event):
        super(QueueEventHandler, self).on_modified(event)

        if not event.is_directory:
            logging.info("Modified file: %s", event.src_path)
            file_queue.put_nowait(event.src_path)
            self.queue_mgr.process_file_queue()

    def on_moved(self, event):
        pass


class QueueManager(object):
    '''Manager class for taking files off the file_queue and pushing them into wherever'''

    def __init__(self, file_queue, logger):
        self.thread = Thread(target=self._process_file_queue)
        self.file_queue = file_queue
        self.logger = logger or logging.getLogger(__name__)

    def process_file_queue(self):
        '''Method checks if there is already a thread running or alive processing the queue and if not, creates a new one'''
        if not self.thread or not self.thread.is_alive():
            self.thread = Thread(target=self._process_file_queue)
            self.logger.info("start processing of queue")
            self.thread.start()

    def _process_file_queue(self):
        '''Main method run as a separate thread which pops files off the file_queue and pushes data into whereever'''
        while not file_queue.empty():
            try:
                # Get file off Queue
                file_path = file_queue.get()
                self.logger.info("Processing file {}".format(file_path))

                # Read XML input
                xml_path = is_xml_file(file_path, raise_exceptions=False)
                if xml_path:
                    self.logger.info("Processing XML file {}".format(xml_path))

                    config_file = is_file(resource_path("settings.json"), allowed_extensions=["json"])
                    with open(config_file, 'r') as json_file:
                        config = json.load(json_file)

                    settings = {"input": [], "output": None, "k_factor": 0.5, "repair": True, "material": None, "check_features": True, "label_text": None, "label_height": 20.0}
                    
                    if "default" in config:
                        settings.update(config["default"])

                    if "observe" in config:
                        settings.update(config["observe"])

                    tree = ET.parse(xml_path)
                    root = tree.getroot()

                    for child in root:
                        if child.tag == "file_path":
                            input_file = is_step_file(child.text, raise_exceptions=False)

                            if input_file:
                                settings["input"].append(input_file)

                        elif child.tag == "output_dir":
                            settings["output"] = child.text

                        elif child.tag == "k_factor":
                            settings["k_factor"] = float(child.text)

                        elif child.tag == "material":
                            settings["material"] = child.text

                        elif child.tag == "reference":
                            settings["label_text"] = child.text

                        elif child.tag == "quantity":
                            settings["quantity"] = int(child.text)

                        elif child.tag == "delivery_date":
                            settings["delivery_date"] = child.text

                        elif child.tag == "label_text":
                            settings["label_text"] = child.text

                        elif child.tag == "label_height":
                            settings["label_height"] = float(child.text)

                    if len(settings["input"]) > 0 and settings["output"]:

                        # Output directory
                        if not os.path.exists(settings["output"]):
                            os.mkdir(settings["output"])

                        # Loop over input files
                        for file_path in settings["input"]:
                            with suppress_stdout_stderr():
                                auto_main(file_path, settings["output"],
                                        display=None,
                                        bysoft_autopart=False,
                                        align=True,
                                        k_factor=settings["k_factor"],
                                        repair=settings["repair"],
                                        material=settings["material"],
                                        check_features=settings["check_features"],
                                        label_text=settings["label_text"],
                                        label_height=settings["label_height"],
                                        quantity=settings["quantity"],
                                        date=settings["delivery_date"]
                                    )

            except Exception as e:
                self.logger.error(str(e))
                # traceback.print_exc()
                # sys.exit()

        self.logger.info("end processing of queue")


def main(directory):
    check_license(meter_attribute="observe")

    queue_mgr = QueueManager(file_queue, logger)
    event_handler = QueueEventHandler(queue_mgr)

    observer = Observer()

    observer.schedule(event_handler, directory, recursive=True)
    observer.start()

    try:
        while True:
            time.sleep(10)

    except KeyboardInterrupt:
        observer.stop()

    observer.join()
