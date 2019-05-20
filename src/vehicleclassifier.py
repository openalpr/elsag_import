import ctypes
import json
import platform


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

class VehicleClassifier():
    def __init__(self, config_file, runtime_dir):
        """
        Initializes an OpenALPR Vehicle Classifier instance in memory.

        :param config_file: The path to the OpenALPR config file
        :param runtime_dir: The path to the OpenALPR runtime data directory
        :return: An OpenALPR instance
        """

        config_file = _convert_to_charp(config_file)
        runtime_dir = _convert_to_charp(runtime_dir)
        try:
        # Load the .dll for Windows and the .so for Unix-based
            if platform.system().lower().find("windows") != -1:
                self._vehicleclassifierpy_lib = ctypes.cdll.LoadLibrary("libvehicleclassifierpy.dll")
            elif platform.system().lower().find("darwin") != -1:
                self._vehicleclassifierpy_lib = ctypes.cdll.LoadLibrary("libvehicleclassifierpy.dylib")
            else:
                self._vehicleclassifierpy_lib = ctypes.cdll.LoadLibrary("libvehicleclassifierpy.so.2")
        except OSError as e:
            nex = OSError("Unable to locate the OpenALPR Vehicle Classification library. Please make sure that it is properly "
                          "installed on your system and that the libraries are in the appropriate paths.")
            if _PYTHON_3:
                nex.__cause__ = e;
            raise nex

        self._initialize_func = self._vehicleclassifierpy_lib.initialize
        self._initialize_func.restype = ctypes.c_void_p
        self._initialize_func.argtypes = [ctypes.c_char_p, ctypes.c_char_p]

        self._dispose_func = self._vehicleclassifierpy_lib.dispose
        self._dispose_func.argtypes = [ctypes.c_void_p]

        self._is_loaded_func = self._vehicleclassifierpy_lib.isLoaded
        self._is_loaded_func.argtypes = [ctypes.c_void_p]
        self._is_loaded_func.restype = ctypes.c_bool


        self._recognize_file_func = self._vehicleclassifierpy_lib.recognizeFile
        self._recognize_file_func.restype = ctypes.c_void_p
        self._recognize_file_func.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p]

        self._recognize_array_func = self._vehicleclassifierpy_lib.recognizeArray
        self._recognize_array_func.restype = ctypes.c_void_p
        self._recognize_array_func.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.POINTER(ctypes.c_ubyte), ctypes.c_uint]

        self._free_json_mem_func = self._vehicleclassifierpy_lib.freeJsonMem


        self._set_top_n_func = self._vehicleclassifierpy_lib.setTopN
        self._set_top_n_func.argtypes = [ctypes.c_void_p, ctypes.c_int]

        self._get_version_func = self._vehicleclassifierpy_lib.getVersion
        self._get_version_func.argtypes = [ctypes.c_void_p]
        self._get_version_func.restype = ctypes.c_void_p

        self.vehicleclassifier_pointer = self._initialize_func(config_file, runtime_dir)


    def unload(self):
        """
        Unloads OpenALPR Vehicle Classifier from memory.

        :return: None
        """
        if self.vehicleclassifier_pointer is not None:
            self._vehicleclassifierpy_lib.dispose(self.vehicleclassifier_pointer)

            self.vehicleclassifier_pointer = None


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
        ptr = self._recognize_file_func(self.vehicleclassifier_pointer, country, file_path)
        json_data = ctypes.cast(ptr, ctypes.c_char_p).value
        json_data = _convert_from_charp(json_data)
        response_obj = json.loads(json_data)
        self._free_json_mem_func(ctypes.c_void_p(ptr))
        return response_obj

    def recognize_array(self, country, byte_array):
        """
        This causes OpenALPR Vehicle Classifier to attempt to recognize an image passed in as a byte array.

        :param byte_array: This should be a string (Python 2) or a bytes object (Python 3)
        :return: An OpenALPR analysis in the form of a response dictionary
        """
        if type(byte_array) != bytes:
            raise TypeError("Expected a byte array (string in Python 2, bytes in Python 3)")
        pb = ctypes.cast(byte_array, ctypes.POINTER(ctypes.c_ubyte))
        ptr = self._recognize_array_func(self.vehicleclassifier_pointer, country, pb, len(byte_array))
        json_data = ctypes.cast(ptr, ctypes.c_char_p).value
        json_data = _convert_from_charp(json_data)
        response_obj = json.loads(json_data)
        self._free_json_mem_func(ctypes.c_void_p(ptr))
        return response_obj

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

    def set_top_n(self, topn):
        """
        Sets the number of returned results when analyzing an image. For example,
        setting topn = 5 returns the top 5 results.

        :param topn: An integer that represents the number of returned results.
        :return: None
        """
        self._set_top_n_func(self.vehicleclassifier_pointer, topn)



    def __del__(self):
        self.unload()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.unload()


