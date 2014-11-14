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

from multiprocessing.managers import SyncManager
from ansible.playbook.handler import Handler
from ansible.playbook.task import Task
from ansible.playbook.play import Play


__all__ = ['AnsibleManager']


class VariableManagerWrapper:
    '''
    This class simply acts as a wrapper around the VariableManager class,
    since manager proxies expect a new object to be returned rather than
    any existing one. Using this wrapper, a shared proxy can be created
    and an existing VariableManager class assigned to it, which can then
    be accessed through the exposed proxy methods.
    '''

    def __init__(self):
        self._vm = None

    def set_play(self, play_data):
        play = Play()
        play.deserialize(play_data)
        self._vm.set_play(play)

    def set_variable_manager(self, vm):
        self._vm = vm

    def get_vars(self, host=None, task_data=None):
        if self._vm:
            # since this is a shared object, everything passed through
            # the proxy is serialized, we have to manually deserialize
            # objects based on the PlaybookBase class.
            task = None
            if task_data:
                if 'is_handler' in task_data:
                    task = Task()
                else:
                    task = Handler()
                task.deserialize(task_data)

            return self._vm.get_vars(host=host, task=task)
        else:
            return dict()

class AnsibleManager(SyncManager):
    '''
    This is our custom manager class, which exists only so we may register
    the new proxy below
    '''
    pass

AnsibleManager.register(
    typeid='VariableManagerWrapper',
    callable=VariableManagerWrapper,
    exposed=('get_vars', 'set_play', 'set_variable_manager')
)
