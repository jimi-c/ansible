# (c) 2012-2014, Michael DeHaan <michael.dehaan@gmail.com>
#
# This file is part of Ansible
#
# Ansible is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Ansible is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Ansible.  If not, see <http://www.gnu.org/licenses/>.

# Make coding more python3-ish
from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

import json
import os

from yaml import load, YAMLError

from ansible.errors import AnsibleParserError

from ansible.parsing.vault import VaultLib
from ansible.parsing.yaml.loader import AnsibleLoader
from ansible.parsing.yaml.objects import AnsibleBaseYAMLObject
from ansible.parsing.yaml.strings import YAML_SYNTAX_ERROR

class DataLoader():

    _FILE_CACHE = dict()

    def __init__(self, vault_password=None):
        if vault_password:
            self._vault = VaultLib(password=vault_password)
        else:
            self._vault = None

    def load(self, data, file_name='<string>', show_content=True):
        try:
            # we first try to load this data as JSON
            return json.loads(data)
        except:
            try:
                # if loading JSON failed for any reason, we go ahead
                # and try to parse it as YAML instead
                return self._safe_load(data)
            except YAMLError, yaml_exc:
                self._handle_error(yaml_exc, file_name, show_content)

    def load_from_file(self, file_name):
        # if the file has already been read in and cached, we'll
        # return those results to avoid more file/vault operations
        if file_name in self._FILE_CACHE:
            return self._FILE_CACHE

        # read the file contents and load the data structure from them
        (file_data, show_content) = self._get_file_contents(file_name)
        parsed_data = self.load(data=file_data, file_name=file_name, show_content=show_content)

        # cache the file contents for next time
        self._FILE_CACHE[file_name] = parsed_data

        return parsed_data

    def _safe_load(self, stream):
        ''' implements yaml.safe_load(), except using our custom loader class '''
        return load(stream, AnsibleLoader)

    def _get_file_contents(self, file_name):
        if not os.path.exists(file_name) or not os.path.isfile(file_name):
            raise AnsibleParserError("the file_name '%s' does not exist, or is not readable" % file_name)

        show_content = True
        try:
            with open(file_name, 'r') as f:
                data = f.read()
                if self._vault.is_encrypted(data):
                    data = self._vault.decrypt(data)
                    show_content = False
            return (data, show_content)
        except (IOError, OSError) as e:
            raise AnsibleParserError("an error occured while trying to read the file '%s': %s" % (file_name, str(e)))

    def _handle_error(self, yaml_exc, file_name, show_content):

        # if the YAML exception contains a problem mark, use it to construct
        # an object the error class can use to display the faulty line
        err_obj = None
        if hasattr(yaml_exc, 'problem_mark'):
            err_obj = AnsibleBaseYAMLObject()
            err_obj.set_position_info(file_name, yaml_exc.problem_mark.line + 1, yaml_exc.problem_mark.column + 1)

        raise AnsibleParserError(YAML_SYNTAX_ERROR, obj=err_obj, show_content=show_content)

