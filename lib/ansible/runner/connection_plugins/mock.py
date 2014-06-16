# (c) 2014, Michael DeHaan <michael.dehaan@gmail.com>
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

import traceback
import os
import pipes
import shutil
import subprocess
import select
import fcntl
from ansible import errors
from ansible import utils
from ansible.utils.display_functions import vvv

class Connection(object):
    '''
    This connection object is used for testing only, to simulate connections
    out to hosts without having to modify any systems.
    '''

    def __init__(self, runner, host, port, *args, **kwargs):
        self.runner = runner
        self.host = host
        self.port = port 
        self.has_pipelining = True

    def connect(self, port=None):
        return self

    def exec_command(self, cmd, tmp_path, sudo_user=None, sudoable=False, executable='/bin/sh', in_data=None, su=None, su_user=None):
        ''' simulate running a command on the target host '''
        return (0, '', '', '')

    def put_file(self, in_path, out_path):
        ''' simulate transfering a file  '''
        pass

    def fetch_file(self, in_path, out_path):
        ''' simulate fetching a file  '''
        pass

    def close(self):
        ''' simulate closing of the connection '''
        pass
