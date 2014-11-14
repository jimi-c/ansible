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

import time

from ansible.playbook.helpers import compile_block_list


__all__ = ['StrategyBase']


class StrategyBase:

    '''
    This is the base class for strategy plugins, which contains some common
    code useful to all strategies like running handlers, cleanup actions, etc.
    '''

    def __init__(self, tqm, variable_manager):
        self._inventory         = tqm.get_inventory()
        self._job_queue         = tqm.get_job_queue()
        self._res_queue         = tqm.get_res_queue()
        self._failed_hosts      = tqm.get_failed_hosts()
        self._unreachable_hosts = tqm.get_unreachable_hosts()
        self._notified_handlers = tqm.get_notified_handlers()
        self._blocked_hosts     = tqm.get_blocked_hosts()
        self._callback          = tqm.get_callback()
        self._variable_manager  = variable_manager

    def run(self, iterator, connection_info, loader):
        self.cleanup(iterator, connection_info, loader)
        self.run_handlers(iterator, connection_info, loader)

    def get_hosts_remaining(self):
        hosts_excluded = set(self._failed_hosts.keys()).union(self._unreachable_hosts.keys())
        return [host for host in self._inventory.get_hosts() if host.get_name() not in hosts_excluded]

    def get_failed_hosts(self):
        failed_hosts = self._failed_hosts.keys()
        return [host for host in self._inventory.get_hosts() if host.get_name() in failed_hosts]

    def _queue_task(self, play, host, task, connection_info, loader):
        ''' handles queueing the task up to be sent to a worker '''
        task_vars = self._variable_manager.get_vars(play=play, host=host, task=task)
        task.post_validate(task_vars)
        self._job_queue.put((host, task.serialize(), task_vars, connection_info, loader))

    def cleanup(self, iterator, connection_info, loader):
        '''
        Iterates through failed hosts and runs any outstanding rescue/always blocks
        and handlers which may still need to be run after a failure.
        '''

        failed_hosts = self.get_failed_hosts()

        # mark the host as failed in the iterator so it will take
        # any required rescue paths which may be outstanding
        for host in failed_hosts:
            iterator.mark_host_failed(host)

        # clear the failed hosts dictionary now while also
        for entry in self._failed_hosts.keys():
            del self._failed_hosts[entry]

        work_to_do = True
        while work_to_do:
            if self._job_queue.qsize() < len(failed_hosts):
                work_to_do = False
                for host in failed_hosts:
                    host_name = host.get_name()

                    if host_name in self._failed_hosts:
                        iterator.mark_host_failed(host)
                        del self._failed_hosts[host_name]

                    #if host_name not in self._failed_hosts and host_name not in self._unreachable_hosts and iterator.get_next_task_for_host(host, peek=True):
                    if host_name not in self._unreachable_hosts and iterator.get_next_task_for_host(host, peek=True):
                        work_to_do = True
                        # check to see if this host is blocked (still executing a previous task)
                        if not host_name in self._blocked_hosts:
                            # pop the task, mark the host blocked, and queue it
                            self._blocked_hosts[host_name] = True
                            task = iterator.get_next_task_for_host(host)
                            self._callback.playbook_on_cleanup_task_start(task.get_name())
                            self._queue_task(iterator._play, host, task, connection_info, loader)

            # pause briefly so we don't spin lock
            time.sleep(0.2)

        # no more work, wait until the queue is drained
        self._job_queue.join()

    def run_handlers(self, iterator, connection_info, loader):
        '''
        Runs handlers on those hosts which have been notified.
        '''

        # FIXME: this should be a method on the iterator, which may
        #        also filter the list of handlers based on the notified
        #        list
        handlers = compile_block_list(iterator._play.handlers)
        for handler in handlers:
            handler_name = handler.get_name()

            if not len(self.get_hosts_remaining()):
                self._callback.playbook_on_no_hosts_remaining()
                break

            if handler_name in self._notified_handlers and len(self._notified_handlers[handler_name]):
                self._callback.playbook_on_handler_task_start(handler_name)
                for host in self._notified_handlers[handler_name]:
                    if not handler.has_triggered(host):
                        temp_data = handler.serialize()
                        self._queue_task(iterator._play, host, handler, connection_info, loader)
                        handler.flag_for_host(host)

                self._job_queue.join()
                self._res_queue.join()

                # wipe the notification list
                self._notified_handlers[handler_name] = []

