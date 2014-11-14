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

import multiprocessing
import os
import socket
import sys

from ansible.errors import AnsibleError
from ansible.executor.connection_info import ConnectionInformation
from ansible.executor.play_iterator import PlayIterator
from ansible.executor.process.worker import WorkerProcess
from ansible.executor.process.result import ResultProcess
from ansible.plugins import callback_loader, strategy_loader

__all__ = ['TaskQueueManager']


class TaskQueueManager:

    '''
    This class handles the multiprocessing requirements of Ansible by
    creating a pool of worker forks, a result handler fork, and a
    manager object with shared datastructures/queues for coordinating
    work between all processes.

    The queue manager is responsible for loading the play strategy plugin,
    which dispatches the Play's tasks to hosts.
    '''

    def __init__(self, inventory, num_forks):
        self._inventory = inventory
        self._manager   = multiprocessing.Manager()

        # get the job and result queues from the manager
        self._job_queue = self._manager.JoinableQueue()
        self._res_queue = self._manager.JoinableQueue()

        # Theses dictionaries are shared state between workers, so each
        # each worker can remove the host its operating on from the list
        # of blocked hosts and share any that may have failed. We use a
        # dictionary for quick lookups and removals from the list
        self._blocked_hosts     = self._manager.dict()
        self._failed_hosts      = self._manager.dict()
        self._unreachable_hosts = self._manager.dict()

        # this dictionary is used to keep track of notified handlers
        self._notified_handlers = self._manager.dict()

        # FIXME: hard-coded the default callback plugin here, which
        #        should be configurable.
        self._callback = callback_loader.get('default')

        try:
            fileno = sys.stdin.fileno()
        except ValueError:
            fileno = None

        # create the pool of worker threads, based on the number of forks specified
        self._workers = []
        for i in range(num_forks):
            # duplicate stdin, if possible
            new_stdin = None
            if fileno is not None:
                try:
                    new_stdin = os.fdopen(os.dup(fileno))
                except OSError, e:
                    # couldn't dupe stdin, most likely because it's
                    # not a valid file descriptor, so we just rely on
                    # using the one that was passed in
                    pass

            prc = WorkerProcess(self, new_stdin)
            prc.start()

            self._workers.append(prc)

        # and create the result process, which handles reading results off
        # the queue and firing off callbacks
        self._result_prc = ResultProcess(self)
        self._result_prc.start()

    def _initialize_notified_handlers(self, handlers):
        '''
        Clears and initializes the shared notified handlers dict with entries
        for each handler in the play, which is an empty array that will contain
        inventory hostnames for those hosts triggering the handler.
        '''

        # Zero the dictionary first by removing any entries there.
        # Proxied dicts don't support iteritems, so we have to use keys()
        for key in self._notified_handlers.keys():
            del self._notified_handlers[key]

        # FIXME: there is a block compile helper for this...
        handler_list = []
        for handler_block in handlers:
            handler_list.extend(handler_block.compile())

        # then initalize it with the handler names from the handler list
        for handler in handler_list:
            self._notified_handlers[handler.get_name()] = []

    def run(self, play, variable_manager):
        '''
        Iterates over the roles/tasks in a play, using the given (or default)
        strategy for queueing tasks. The default is the linear strategy, which
        operates like classic Ansible by keeping all hosts in lock-step with
        a given task (meaning no hosts move on to the next task until all hosts
        are done with the current task).
        '''

        self._callback.playbook_on_play_start(play.name)

        # initialize the shared dictionary containing the notified handlers
        self._initialize_notified_handlers(play.handlers)

        # load the specified strategy (or the default linear one)
        strategy = strategy_loader.get(play.strategy, self, variable_manager)
        if strategy is None:
            raise AnsibleError("Invalid play strategy specified: %s" % play.strategy, obj=play._ds)

        # build the iterator and connection info object
        iterator = PlayIterator(inventory=self._inventory, play=play)
        connection_info = ConnectionInformation(play)

        # and run the play using the strategy
        strategy.run(iterator, connection_info, play._loader)

    def get_blocked_hosts(self):
        return self._blocked_hosts

    def get_failed_hosts(self):
        return self._failed_hosts

    def get_unreachable_hosts(self):
        return self._unreachable_hosts

    def get_job_queue(self):
        return self._job_queue

    def get_res_queue(self):
        return self._res_queue

    def get_inventory(self):
        return self._inventory

    def get_callback(self):
        return self._callback

    def get_notified_handlers(self):
        return self._notified_handlers
