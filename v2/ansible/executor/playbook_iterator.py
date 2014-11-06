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

class PlaybookState:
   def __init__(self, parent_iterator):
       self._parent_iterator = parent_iterator
       self._cur_play        = 0
       self._task_list       = None
       self._cur_task_pos    = 0

   def next(self):
       while True:
           if self._cur_play > len(self._parent_iterator._playbook._entries) - 1:
               return None

           if self._task_list is None:
               self._task_list = self._parent_iterator._playbook._entries[self._cur_play].compile()

           if self._cur_task_pos > len(self._task_list) - 1:
               self._cur_play += 1
               self._task_list = None
               self._cur_task_pos = 0
               continue
           else:
               # FIXME: do tag/conditional evaluation here and advance
               #        the task position if it should be skipped without
               #        returning a task
               task = self._task_list[self._cur_task_pos]
               self._cur_task_pos += 1

               # Skip the task if it is the member of a role which has already
               # been run, unless the role allows multiple executions
               if task._role:
                   if task._role.has_run() and not task._role._metadata._allow_duplicates:
                       continue

               return task

class PlaybookIterator:

   def __init__(self, inventory, log_manager, playbook):
       self._playbook     = playbook
       self._log_manager  = log_manager
       self._host_entries = dict()

       for host in inventory.get_hosts():
           self._host_entries[host.get_name()] = PlaybookState(parent_iterator=self)

   def get_next_task_for_host(self, host):
       if host.get_name() not in self._host_entries:
           raise AnsibleError("invalid host specified for playbook iteration")

       return self._host_entries[host.get_name()].next()
