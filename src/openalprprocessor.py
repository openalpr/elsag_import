
from openalpr import Alpr
from vehicleclassifier import VehicleClassifier
import os
import threading
from argparse import ArgumentParser
import time
import multiprocessing
import copy
import json
import logging
from alprcommon import AlprProcessorConfig
import requests
import base64
from PIL import Image
import platform
from logging import StreamHandler
import sys

if platform.python_version_tuple()[0] == '2':
    _PYTHON_3=False
    from StringIO import StringIO
    from Queue import Queue, Empty
else:
    _PYTHON_3=True
    from io import BytesIO
    from queue import Queue, Empty

threadLock = threading.Lock()
thread_count = 0

SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))

logger = logging.getLogger('import_logger')

class PlateUploader():
    def __init__(self, config):
        with open(os.path.join(SCRIPT_DIR, '../config/', 'group.template'), 'r') as inf:
            self.group_template = json.load(inf)

        self.config = config
        self.group_template['company_id'] = self.config.company_id
        self.group_template['agent_uid'] = self.config.agent_uid

        self.url = config.openalpr_url
        self.timeout = config.upload_timeout

    def upload(self, camera_name, epoch_time, plate_results, vehicle_results, plate_crop_jpeg_bytes, vehicle_crop_jpeg_bytes):
        upload_template = copy.copy(self.group_template)

        print(plate_results)
        best_plate = plate_results['results'][0]
        del upload_template['vehicle']
        # upload_template['vehicle'] = vehicle_results
        upload_template['best_plate'] = best_plate
        upload_template['best_plate']['plate_crop_jpeg'] = plate_crop_jpeg_bytes

        camera_config = self.config.get_camera_config(camera_name)
        camera_id = camera_config['camera_id']
        gps_latitude = camera_config['gps_latitude']
        gps_longitude = camera_config['gps_longitude']

        uuid = '%s-%s-%s' % ( self.config.agent_uid, camera_id, epoch_time)
        upload_template['best_uuid'] = uuid
        upload_template['uuids'].append(uuid)
        upload_template['gps_latitude'] = gps_latitude
        upload_template['gps_longitude'] = gps_longitude

        upload_template['epoch_start'] = epoch_time
        upload_template['epoch_end'] = epoch_time

        upload_template['best_plate_number'] = best_plate['plate']
        upload_template['best_confidence'] = best_plate['confidence']

        upload_template['best_region_confidence'] = best_plate['region_confidence']
        upload_template['best_region'] = best_plate['region']

        upload_template['candidates'] = best_plate['candidates']
        #upload_template['vehicle_crop_jpeg'] = vehicle_crop_jpeg_bytes

        logger.debug(json.dumps(upload_template, indent=2))
        # print json.dumps(upload_template, indent=2)
        # Upload to webserver
        while True:
            logger.debug("Posting to %s" % (self.url))
            r = requests.post(self.url, json=upload_template, timeout=self.timeout, verify=False)

            logger.info('Webserver POST status {}: {}'.format(r.status_code, r.text))

            if str(r.status_code)[0] == '2':
                break
            else:
                logger.warn('Upload to webserver failed. Retrying indefinitely')
                time.sleep(1.0)



class PlateProcessorThread (threading.Thread):

    def __init__(self, plate_queue, country='us'):
        threading.Thread.__init__(self)
        self.plate_queue = plate_queue
        self.active = True
        self.country = country


    def deactivate(self):
        self.active = False

    def _resize_img(self, x,y,w,h, new_width, image_path):

        img = Image.open(image_path)
        img_shape = img.size
        if x < 0:
            x = 0
        if y < 0:
            y = 0
        if x+w > img_shape[0]:
            x = img_shape[0] - w
        if y+h > img_shape[1]:
            y = img_shape[1] - h

        cropped = img.crop((x,y,w+x,h+y))
        wpercent = (new_width / float(cropped.size[0]))
        hsize = int((float(cropped.size[1]) * float(wpercent)))
        img = cropped.resize((new_width, hsize), Image.ANTIALIAS)
        #img.save('sompic.jpg')
        if _PYTHON_3:
            buffer = BytesIO()
        else:
            buffer = StringIO()
        img.save(buffer, format="JPEG")
        img_str = base64.b64encode(buffer.getvalue()).decode("utf-8")

        return img_str

    def run(self):
        global threadLock, thread_count

        # Parser config bypasses detection on crop
        parser_config = os.path.join(SCRIPT_DIR, '../config/', "openalprparser.conf")
        self.alpr = Alpr(self.country, "", "")
        self.vehicle_classifier = VehicleClassifier("","")

        config = AlprProcessorConfig()
        plate_uploader = PlateUploader(config)

        if not self.alpr.is_loaded():
            logger.warn("Alpr instance loaded")

        threadLock.acquire()
        self.thread_number = thread_count
        logger.info("Initiating thread #%d" % (self.thread_number))
        thread_count += 1
        threadLock.release()

        while self.active:

            curplate = None
            threadLock.acquire()
            try:
                curplate = self.plate_queue.get(block=False)
            except Empty:
                curplate = None
            threadLock.release()

            if curplate is None:
                # No plate to process, sleep and continue
                time.sleep(0.25)
                continue

            # We have a plate to process, let's do it
            plate_results = self.alpr.recognize_file(curplate['crop_image'])

            import json
            print(json.dumps( plate_results, indent=2))
            # print plate_results
            if len(plate_results['results']) > 0:
                plate_coords = plate_results['results'][0]['coordinates']
                min_x = plate_coords[0]['x']
                max_x = plate_coords[0]['x']
                min_y = plate_coords[0]['y']
                max_y = plate_coords[0]['y']
                for coord in plate_coords:
                    if coord['x'] > max_x:
                        max_x = coord['x']
                    if coord['x'] < min_x:
                        min_x = coord['x']
                    if coord['y'] > max_y:
                        max_y = coord['y']
                    if coord['y'] < min_y:
                        min_y = coord['y']

                x = min_x
                y = min_y
                width = max_x - min_x
                height = max_y - min_y

                # Add 20%
                adjust_x = width * 0.2
                adjust_y = height * 0.2
                x -= adjust_x /2
                y -= adjust_y /2
                width += adjust_x
                height += adjust_y

                print((x,y,width,height))
                plate_crop_encoded = self._resize_img( x,y,width,height, 150, curplate['crop_image'])

                # Skip vehicles for now.  In version 2.8.101 the vehicle detector can be used to scan / recognize the overview image

                # vehicle_results = self.vehicle_classifier.recognize_file(self.country, curplate['overview_image'])
                # print vehicle_results
                vehicle_results = None
                vehicle_crop_encoded = None

                # vehicle_crop_encoded = self._resize_img(256, curplate['overview_image'])

                plate_uploader.upload(curplate['camera_name'], curplate['epoch_time'], plate_results, vehicle_results, plate_crop_encoded, vehicle_crop_encoded )

class OpenALPRProcessor():
    def __init__(self, num_threads=multiprocessing.cpu_count()):
        if num_threads > 8:
            num_threads = 8
        # Initialize the lib
        self.queue = Queue()

        self.max_queue_size = num_threads * 3

        self.threads = []
        for thread in range(0, num_threads):

            t = PlateProcessorThread(self.queue)
            t.daemon = True
            t.start()
            self.threads.append(t)

        logger.info("All processing threads started")

    ''' Process the image files and provide the JSON'''
    def process(self, camera_name, epoch_time, crop_image, overview_image):
        global threadLock

        threadLock.acquire()
        self.queue.put({
            "camera_name": camera_name,
            "epoch_time": epoch_time,
            "crop_image": crop_image,
            "overview_image": overview_image
            })
        threadLock.release()

        # Block on large queue size
        while self.queue.qsize() >= self.max_queue_size:
            time.sleep(0.1)

    def close(self):
        for t in self.threads:
            t.deactivate()

    def join(self):
        for t in self.threads:
            t.join()


if __name__ == "__main__":

    parser = ArgumentParser(description='OpenALPR Parser Test')


    parser.add_argument( "-o", "--overview_image", dest="overview_image", action="store", type=str, required=True, 
                      help="Overview Image Path" )

    parser.add_argument( "-c", "--crop_image", dest="crop_image", action="store", type=str, required=True, 
                      help="Crop Image Path" )

    parser.add_argument( "--camera_name", dest="camera_name", action="store", type=str, required=True,
                      help="Camera name" )

    parser.add_argument( "--epoch_time", dest="epoch_time", action="store", type=str, required=True,
                      help="Epoch Time" )

    parser.add_argument( "--threads", dest="threads", action="store", type=int, required=False, default=multiprocessing.cpu_count(),
                      help="Total # of simmultaneous processes" )

    options = parser.parse_args()

    print("Logging to console")
    # If not configured, write to console
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler = StreamHandler(stream=sys.stdout)
    handler.setLevel(logging.DEBUG)
    logger.setLevel(logging.DEBUG)
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.debug("Writing to Stream handler")


    processor = OpenALPRProcessor(num_threads=options.threads)
    processor.process(options.camera_name, options.epoch_time, options.crop_image, options.overview_image)
    time.sleep(5.0)
    processor.close()
    processor.join()
