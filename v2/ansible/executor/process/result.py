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

import Queue
import multiprocessing
import os
import signal
import sys
import time
import traceback

HAS_ATFORK=True
try:
    from Crypto.Random import atfork
except ImportError:
    HAS_ATFORK=False

from ansible.executor.task_result import TaskResult
from ansible.playbook.handler import Handler
from ansible.playbook.task import Task


__all__ = ['ResultProcess']


class ResultProcess(multiprocessing.Process):
    '''
    The result worker thread, which reads results from the results
    queue and fires off callbacks/etc. as necessary.
    '''

    def __init__(self, tqm):

        # takes a task queue manager as the sole param:
        self._blocked_hosts     = tqm.get_blocked_hosts()
        self._failed_hosts      = tqm.get_failed_hosts()
        self._unreachable_hosts = tqm.get_unreachable_hosts()
        self._notified_handlers = tqm.get_notified_handlers()
        self._res_queue         = tqm.get_res_queue()
        self._callback          = tqm._callback

        super(ResultProcess, self).__init__()

    def run(self):
        '''
        The main thread execution, which reads from the results queue
        indefinitely and sends callbacks/etc. when results are received.
        '''

        if HAS_ATFORK:
            atfork()

        signal.signal(signal.SIGINT, signal.SIG_IGN)
        while True:
            try:
                result = self._res_queue.get(block=True)

                if 'is_handler' in result._task:
                    task = Handler()
                else:
                    task = Task()
                # FIXME: there should be a cleaner way to get the task
                #        from the results here
                task.deserialize(result._task)

                host_name = result._host.get_name()

                # send callbacks, execute other options based on the result status
                if result.is_failed():
                    self._callback.runner_on_failed(task, result)
                    self._failed_hosts[host_name] = True
                elif result.is_unreachable():
                    self._callback.runner_on_unreachable(task, result)
                    self._unreachable_hosts[host_name] = True
                elif result.is_skipped():
                    self._callback.runner_on_skipped(task, result)
                else:
                    self._callback.runner_on_ok(task, result)

                    # if this task is notifying a handler, do it now
                    if task.notify:
                        # The shared dictionary for notified handlers is a proxy, which
                        # does not detect when sub-objects within the proxy are modified.
                        # So, per the docs, we reassign the list so the proxy picks up and
                        # notifies all other threads
                        for notify in task.notify:
                            host_list = self._notified_handlers[notify]
                            host_list.append(result._host)
                            self._notified_handlers[notify] = host_list

                # and remove the host from the blocked list, since we're done with it
                if host_name in self._blocked_hosts:
                    del self._blocked_hosts[host_name]

                # notify the queue that the task was completed, so any joined
                # threads will be properly notified when all tasks are complete
                self._res_queue.task_done()

            except Queue.Empty:
                pass
            except (IOError, EOFError):
                break
            except:
                traceback.print_exc()
                break

