#!/usr/bin/python

import os
import sys
import pytds
import pytds.login
import socket
import datetime
import json
import time
import pytz
import logging
from alprcommon import AlprProcessorConfig
from logging.handlers import RotatingFileHandler
from logging import StreamHandler
from openalprprocessor import OpenALPRProcessor


CUR_DIR = os.path.dirname(os.path.realpath(__file__))
state_file = os.path.join(CUR_DIR, '../config/', 'state.json')
log_file = os.path.join(CUR_DIR, '../log/', 'import.log')
logger = logging.getLogger('import_logger')


def _datetime_to_epochms( dt, tzinfo=pytz.utc):
    epoch = datetime.datetime.utcfromtimestamp(0)
    if tzinfo is not None:
        epoch = epoch.replace(tzinfo=tzinfo)
    return int((dt - epoch).total_seconds() * 1000)


def _epochms_to_datetime( epoch_ms, tzinfo=pytz.utc):
    datestamp = datetime.datetime.utcfromtimestamp(float(epoch_ms) / 1000.0)
    if tzinfo is not None:
        datestamp = datestamp.replace(tzinfo=pytz.utc)
    return datestamp

## last_parse corresponds to the current
class ParsingState:
    def __init__(self):
        self.state = None
        try:
            if os.path.isfile(state_file):
                with open(state_file, 'r') as inf:
                    self.state = json.load(inf)
        except:
            pass

        if self.state is None:  
            self.state = {'version': 1, 'last_parse': 0, 'last_save': 0}

    def save(self):
        self.state['last_save'] = _datetime_to_epochms(datetime.datetime.now(tz=pytz.utc), tzinfo=pytz.utc)
        self.state['version'] = 1
        with open(state_file, 'w') as outf:
            json.dump(self.state, outf, indent=2)

    def get_last_parse(self):
        return _epochms_to_datetime( self.state['last_parse'], True )

    def set_last_parse(self, newtime):
        self.state['last_parse'] = _datetime_to_epochms(newtime)




class ElsagInterface:

    def __init__(self, server, user, password, database_name, port, base_image_path):
        self.server = server
        self.user = user
        self.password = password
        self.database_name = database_name
        self.port = port
        self.base_image_path = base_image_path

        self.parsing_state = ParsingState()

        self.openalpr_processor = OpenALPRProcessor()


    def process_read(self, conn, read_id, plate, camera, read_date, lat, lng):
        # we have a single read, grab all the image data and process it
        logger.debug("Processing {read_id} on {read_date}".format(read_id=read_id, read_date=read_date))

        overview_image_path = None
        crop_image_path = None

        with conn.cursor() as cursor:
            OVERVIEW_IMAGE_ID = 1
            CROP_IMAGE_ID = 2

            cursor.execute('SELECT image_id, create_date, read_date, plate_image_type FROM images WHERE read_id = %s', (read_id,))

            # "Getting all images"
            results = cursor.fetchall()

            for row in results:
                image_id = row[0]
                create_date = row[1]
                read_date = row[2]
                plate_image_type = int(row[3])
                if plate_image_type == OVERVIEW_IMAGE_ID:
                    overview_image_path = os.path.join(self.base_image_path, str(image_id))
                elif plate_image_type == CROP_IMAGE_ID:
                    crop_image_path = os.path.join(self.base_image_path, str(image_id))

            logger.debug("Processing images.  Overview: %s  Crop: %s" % (overview_image_path, crop_image_path))
            for img in [overview_image_path, crop_image_path]:
                if img is None:
                    logger.warn("Failed to find image for read_id {read_id} in database".format(read_id=read_id))
                    return
                if not os.path.isfile(img):
                    logger.warn("Unable to find image {img} on disk for read_id {read_id}".format(img=img, read_id=read_id))
                    return

            # Load the images and process them
            logger.debug("Found crop image {crop_image_path}".format(crop_image_path=crop_image_path))
            logger.debug("Found overview image {overview_image_path}".format(overview_image_path=overview_image_path))

        read_epoch = read_date
        self.openalpr_processor.process(camera, _datetime_to_epochms(read_epoch), crop_image_path, overview_image_path, lat, lng)

        # Parsing with OpenALPR
        # We have two images, do the LPR processing on one and the 

    def run(self):

        while True:

            try:
                auth_obj = None
                logger.info("Connecting to database {server}:{port}/{database} as {user}".format(server=self.server, port=self.port, database=self.database_name, user=self.user))
                # Handle NTML Authentication -- assume that's what they want if username has a domain.  Otherwise use normal auth
                if '\\' in self.user:
                    logger.info("Logging in via NTLM")
                    auth_obj = pytds.login.NtlmAuth (self.user, self.password)

                with pytds.connect(self.server, self.database_name, self.user, self.password, port=self.port, auth=auth_obj) as conn:

                    while True:
                        with conn.cursor() as cursor:

                            last_parse = self.parsing_state.get_last_parse()
                            logger.debug( "Last parse: " + str(last_parse))

                            #cursor.execute('SELECT read_id, plate, camera, read_date, lat, lon FROM reads WHERE read_date > 2010-01-01 ORDER BY read_date asc LIMIT 1000')
                            cursor.execute('SELECT TOP 1000 read_id, plate, camera, read_date, lat, lon FROM reads WHERE read_date > %s ORDER BY read_date ASC', (last_parse,))


                            results = cursor.fetchall()

                            if len(results) == 0:
                                # No results, sleep for a while
                                logger.debug ("No results.  Sleeping...")
                                time.sleep(5)
                                continue

                            logger.info("Grabbed {count} results from db starting from time: {time}".format(count=len(results), time=last_parse))
                            for row in results:
                                read_id = row[0]
                                plate = row[1]
                                camera = row[2]
                                read_date = row[3]
                                lat = row[4]
                                lng = row[5]

                                if read_date > last_parse:
                                    self.parsing_state.set_last_parse(read_date)

                                self.process_read(conn, read_id, plate, camera, read_date, lat, lng)

                                # Now select each image for the given row

                            self.parsing_state.save()

            except (pytds.tds_base.Error, socket.error, Exception) as e:
                logger.exception(e)
                logger.warn("Error connecting to database.  Retrying in 15 seconds...")
                time.sleep(15)



if __name__ == "__main__":

    NEEDED_DIRS = ['log', 'config' ]
    for adir in NEEDED_DIRS:
        fulldir = os.path.join(CUR_DIR, '../', adir)
        if not os.path.isdir(fulldir):
            os.makedirs(fulldir)

    proc_config = AlprProcessorConfig()


    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    if proc_config.log_file is not None:
        print("Logging to %s" % (proc_config.log_file))
        log_file = proc_config.log_file
        handler = RotatingFileHandler(log_file, maxBytes=10000000, backupCount=1)
        handler.setLevel(logging.INFO)
        logger.setLevel(logging.INFO)
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.info("Writing to File handler")
    else:
        print("Logging to console")
        # If not configured, write to console
        handler = StreamHandler(stream=sys.stdout)
        handler.setLevel(logging.DEBUG)
        logger.setLevel(logging.DEBUG)
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.debug("Writing to Stream handler")




    elsag = ElsagInterface(proc_config.server, 
        proc_config.user, proc_config.password, 
        proc_config.database_name, proc_config.port,
        proc_config.base_image_path)

    elsag.run()