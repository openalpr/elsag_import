
import os
import platform
if platform.python_version_tuple()[0] == '2':
    from StringIO import StringIO
    from ConfigParser import ConfigParser, NoOptionError
else:
    from io import StringIO
    from configparser import ConfigParser, NoOptionError



class AlprProcessorConfig():

    def __init__(self):

        self.default_section_name = 'default'

        CUR_DIR = os.path.dirname(os.path.realpath(__file__))
        self.config_file = os.path.join(CUR_DIR, '../config/', 'import_config.ini')
        self.camera_config = {}

        parser = self._get_parser()

        self.server = parser.get(self.default_section_name, 'database_server')
        self.user = parser.get(self.default_section_name, 'database_user')
        self.password = parser.get(self.default_section_name, 'database_password')
        self.port = parser.get(self.default_section_name, 'database_port')
        self.database_name = parser.get(self.default_section_name, 'database_name')
        self.base_image_path = parser.get(self.default_section_name, 'base_image_path')


        try:
            self.log_file = os.path.join(CUR_DIR, '../log/', parser.get(self.default_section_name, 'log_file'))
        except NoOptionError:
            self.log_file = None

        self.company_id = parser.get(self.default_section_name, 'openalpr_company_id')
        self.agent_uid = parser.get(self.default_section_name, 'openalpr_agent_uid')

        self.openalpr_url = parser.get(self.default_section_name, 'openalpr_url')
        self.upload_timeout = float(parser.get(self.default_section_name, 'upload_timeout'))

    def _get_parser(self):

        parser = ConfigParser()

        with open(self.config_file, 'r') as f:
            config_string = '[%s]\n' % (self.default_section_name) + f.read()

        buf = StringIO(config_string)
        parser.readfp(buf)

        return parser

    def get_camera_config(self, camera_name):

        parser = self._get_parser()

        # Cache the lookups
        if camera_name not in self.camera_config:
           self.camera_config[camera_name] = {
               'camera_id': parser.get(camera_name, 'camera_id'),
               'gps_latitude': parser.get(camera_name, 'gps_latitude'),
               'gps_longitude': parser.get(camera_name, 'gps_longitude')
           }

        return self.camera_config[camera_name]