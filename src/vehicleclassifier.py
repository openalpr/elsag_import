import ctypes
import json
import platform
import numpy as np
import numpy.ctypeslib as npct


# We need to do things slightly differently for Python 2 vs. 3
# ... because the way str/unicode have changed to bytes/str
if platform.python_version_tuple()[0] == '2':
    # Using Python 2
    bytes = str
    _PYTHON_3 = False
else:
    # Assume using Python 3+
    unicode = str
    _PYTHON_3 = True


def _convert_to_charp(string):
    # Prepares function input for use in c-functions as char*
    if type(string) == unicode:
        return string.encode("UTF-8")
    elif type(string) == bytes:
        return string
    else:
        raise TypeError("Expected unicode string values or ascii/bytes values. Got: %r" % type(string))


def _convert_from_charp(charp):
    # Prepares char* output from c-functions into Python strings
    if _PYTHON_3 and type(charp) == bytes:
        return charp.decode("UTF-8")
    else:
        return charp

class VehicleClassifierCRegionOfInterest(ctypes.Structure):
    _fields_ = [("x",  ctypes.c_int),
                ("y", ctypes.c_int),
                ("width", ctypes.c_int),
                ("height", ctypes.c_int)]

class VehicleClassifier:
    def __init__(self, config_file, runtime_dir, license_key="", use_gpu=False, gpu_id=0, gpu_batch_size=10):
        """
        Initializes an OpenALPR Vehicle Classifier instance in memory.

        :param config_file: The path to the OpenALPR config file
        :param runtime_dir: The path to the OpenALPR runtime data directory
        :return: An OpenALPR instance
        """

        self.use_gpu = use_gpu
        config_file = _convert_to_charp(config_file)
        runtime_dir = _convert_to_charp(runtime_dir)
        try:
        # Load the .dll for Windows and the .so for Unix-based
            if platform.system().lower().find("windows") != -1:
                self._vehicleclassifierpy_lib = ctypes.cdll.LoadLibrary("libopenalpr.dll")
            elif platform.system().lower().find("darwin") != -1:
                self._vehicleclassifierpy_lib = ctypes.cdll.LoadLibrary("libopenalpr.dylib")
            else:
                self._vehicleclassifierpy_lib = ctypes.cdll.LoadLibrary("libopenalpr.so.2")
        except OSError as e:
            nex = OSError("Unable to locate the OpenALPR Vehicle Classification library. Please make sure that it is properly "
                          "installed on your system and that the libraries are in the appropriate paths.")
            if _PYTHON_3:
                nex.__cause__ = e;
            raise nex

        array_1_uint8 = npct.ndpointer(dtype=np.uint8, ndim=1, flags='CONTIGUOUS')
        
        self._dispose_func = self._vehicleclassifierpy_lib.vehicleclassifier_cleanup
        self._dispose_func.argtypes = [ctypes.c_void_p]

        self._free_json_mem_func = self._vehicleclassifierpy_lib.vehicleclassifier_free_response_string

        self._get_version_func = self._vehicleclassifierpy_lib.openalpr_get_version
        self._get_version_func.argtypes = [ctypes.c_void_p]
        self._get_version_func.restype = ctypes.c_void_p

        self._is_loaded_func = self._vehicleclassifierpy_lib.vehicleclassifier_is_loaded
        self._is_loaded_func.argtypes = [ctypes.c_void_p]
        self._is_loaded_func.restype = ctypes.c_bool

        self._initialize_func = self._vehicleclassifierpy_lib.vehicleclassifier_init
        self._initialize_func.restype = ctypes.c_void_p
        self._initialize_func.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_char_p]

        self._recognize_file_func = self._vehicleclassifierpy_lib.vehicleclassifier_recognize_imagefile
        self._recognize_file_func.restype = ctypes.c_void_p
        self._recognize_file_func.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p]

        self._recognize_array_func = self._vehicleclassifierpy_lib.vehicleclassifier_recognize_encodedimage
        self._recognize_array_func.restype = ctypes.c_void_p
        self._recognize_array_func.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.POINTER(ctypes.c_ubyte), ctypes.c_uint, VehicleClassifierCRegionOfInterest]

        self._recognize_raw_image_func = self._vehicleclassifierpy_lib.vehicleclassifier_recognize_rawimage
        self._recognize_raw_image_func.restype = ctypes.c_void_p
        self._recognize_raw_image_func.argtypes = [
            ctypes.c_void_p, ctypes.c_char_p, array_1_uint8, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint, VehicleClassifierCRegionOfInterest]

        self._set_top_n_func = self._vehicleclassifierpy_lib.vehicleclassifier_set_topn
        self._set_top_n_func.argtypes = [ctypes.c_void_p, ctypes.c_int]

        if self.use_gpu:
            self.vehicleclassifier_pointer = self._initialize_func(config_file, runtime_dir, 1, gpu_id, gpu_batch_size, _convert_to_charp(license_key))
        else:
            self.vehicleclassifier_pointer = self._initialize_func(config_file, runtime_dir, 0, 0, 1, _convert_to_charp(license_key))
        

    def __del__(self):
        self.unload()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.unload()

    def get_top_result(self, results):
        """Extract the top result for each JSON category.

        :param dict results: From ``recognize_*()`` methods.
        :return str vehicle_data: Highest confidence result.
        """
        fields = ['year', 'color', 'make_model', 'body_type', 'orientation']
        combined = []
        for f in fields:
            try:
                combined.append(results[f][0]['name'])
            except IndexError:
                combined.append('')
        combined = [c for c in combined if c != '']
        if len(combined) > 0:
            combined.insert(-1, 'oriented at')
            combined[-1] = '{} degress'.format(combined[-1])
            vehicle_data = ' '.join(combined)
        else:
            vehicle_data = ''
        return vehicle_data

    def get_version(self):
        """
        This gets the version of OpenALPR Vehicle Classifier

        :return: Version information
        """

        ptr = self._get_version_func(self.vehicleclassifier_pointer)
        version_number = ctypes.cast(ptr, ctypes.c_char_p).value
        version_number = _convert_from_charp(version_number)
        self._free_json_mem_func(ctypes.c_void_p(ptr))
        return version_number

    def is_loaded(self):
        """
        Checks if OpenALPR is loaded.

        :return: A bool representing if OpenALPR is loaded or not
        """
        return self._is_loaded_func(self.vehicleclassifier_pointer)

    def recognize_file(self, country, file_path):
        """
        This causes OpenALPR Vehicle Classifier to attempt to recognize an image by opening a file on
        disk.

        :param file_path: The path to the image that will be analyzed
        :return: An OpenALPR analysis in the form of a response dictionary
        """
        file_path = _convert_to_charp(file_path)
        country = _convert_to_charp(country)
        ptr = self._recognize_file_func(self.vehicleclassifier_pointer, country, file_path)
        json_data = ctypes.cast(ptr, ctypes.c_char_p).value
        json_data = _convert_from_charp(json_data)
        response_obj = json.loads(json_data)
        self._free_json_mem_func(ctypes.c_void_p(ptr))
        return response_obj

    def recognize_array(self, country, byte_array, x=None, y=None, width=None, height=None):
        """
        This causes OpenALPR Vehicle Classifier to attempt to recognize an image passed in as a byte array.

        :param byte_array: This should be a string (Python 2) or a bytes object (Python 3)
        :return: An OpenALPR analysis in the form of a response dictionary
        """
        country = _convert_to_charp(country)
        if type(byte_array) != bytes:
            raise TypeError("Expected a byte array (string in Python 2, bytes in Python 3)")
        pb = ctypes.cast(byte_array, ctypes.POINTER(ctypes.c_ubyte))

        if x == None or y == None or width == None or height == None:
            x = 0
            y = 0
            width = 1000000
            height = 1000000

        roi = VehicleClassifierCRegionOfInterest(x, y, width, height)

        ptr = self._recognize_array_func(self.vehicleclassifier_pointer, country, pb, len(byte_array), roi)

        json_data = ctypes.cast(ptr, ctypes.c_char_p).value
        json_data = _convert_from_charp(json_data)
        response_obj = json.loads(json_data)
        self._free_json_mem_func(ctypes.c_void_p(ptr))
        return response_obj


    def recognize_ndarray(self, country, ndarray, x=None, y=None, width=None, height=None):
        """Recognize an image passed in as a numpy array.

        :param ndarray: numpy.array as used in cv2 module
        :return: An OpenALPR analysis in the form of a response dictionary
        """
        height, width = ndarray.shape[:2]
        bpp = ndarray.shape[2] if len(ndarray.shape) > 2 else 1

        country = _convert_to_charp(country)

        if x == None or y == None or width == None or height == None:
            x = 0
            y = 0
            width = 1000000
            height = 1000000

        roi = VehicleClassifierCRegionOfInterest(x, y, width, height)

        ptr = self._recognize_raw_image_func(self.vehicleclassifier_pointer, country, ndarray.flatten(), bpp, width, height, roi)

        json_data = ctypes.cast(ptr, ctypes.c_char_p).value
        json_data = _convert_from_charp(json_data)
        response_obj = json.loads(json_data)
        self._free_json_mem_func(ctypes.c_void_p(ptr))
        return response_obj

    def set_top_n(self, topn):
        """
        Sets the number of returned results when analyzing an image. For example,
        setting topn = 5 returns the top 5 results.

        :param topn: An integer that represents the number of returned results.
        :return: None
        """
        self._set_top_n_func(self.vehicleclassifier_pointer, topn)

    def unload(self):
        """
        Unloads OpenALPR Vehicle Classifier from memory.

        :return: None
        """
        if self.vehicleclassifier_pointer is not None:
            self._vehicleclassifierpy_lib.vehicleclassifier_cleanup(self.vehicleclassifier_pointer)

            self.vehicleclassifier_pointer = None