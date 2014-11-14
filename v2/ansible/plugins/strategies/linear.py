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

from ansible.plugins.strategies import StrategyBase

class StrategyModule(StrategyBase):

    def run(self, iterator, connection_info, loader):
        '''
        The linear strategy is simple - get the next task and queue
        it for all hosts, then wait for the queue to drain before
        moving on to the next task
        '''

        # iteratate over each task, while there is one left to run
        task = iterator.get_next_task()
        while task:

            hosts_left = self.get_hosts_remaining()
            if len(hosts_left) == 0:
                self._callback.playbook_on_no_hosts_remaining()
                break
            else:
                self._callback.playbook_on_task_start(task.get_name(), False)

            # queue up this task for each host in the inventory
            for host in hosts_left:
                host_name = host.get_name()

                if host_name not in self._failed_hosts and host_name not in self._unreachable_hosts:
                    self._blocked_hosts[host_name] = True
                    self._queue_task(iterator._play, host, task, connection_info, loader)

            # wait for the queue to be run and for all results to be processed
            self._job_queue.join()
            self._res_queue.join()

            # and get the next task
            task = iterator.get_next_task()

        # run the base class run() method, which executes the cleanup function
        # and runs any outstanding handlers which have been triggered
        super(StrategyModule, self).run(iterator, connection_info, loader)

