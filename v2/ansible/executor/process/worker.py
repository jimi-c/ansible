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

from ansible.errors import AnsibleError, AnsibleConnectionFailure
from ansible.executor.task_executor import TaskExecutor
from ansible.executor.task_result import TaskResult
from ansible.playbook.handler import Handler
from ansible.playbook.task import Task

__all__ = ['ExecutorProcess']


class WorkerProcess(multiprocessing.Process):
    '''
    The worker thread class, which uses TaskExecutor to run tasks
    read from a job queue and pushes results into a results queue
    for reading later.
    '''

    def __init__(self, tqm, new_stdin):

        # takes a task queue manager as the sole param:
        self._job_queue = tqm.get_job_queue()
        self._res_queue = tqm.get_res_queue()
        self._failed_hosts = tqm.get_failed_hosts()
        self._callback  = tqm.get_callback()

        # dupe stdin, if we have one
        try:
            fileno = sys.stdin.fileno()
        except ValueError:
            fileno = None

        self._new_stdin = new_stdin
        if not new_stdin and fileno is not None:
            try:
                self._new_stdin = os.fdopen(os.dup(fileno))
            except OSError, e:
                # couldn't dupe stdin, most likely because it's
                # not a valid file descriptor, so we just rely on
                # using the one that was passed in
                pass

        super(WorkerProcess, self).__init__()

    def run(self):
        '''
        Called when the process is started, and loops indefinitely
        until an error is encountered (typically an IOerror from the
        queue pipe being disconnected). During the loop, we attempt
        to pull tasks off the job queue and run them, pushing the result
        onto the results queue. We also remove the host from the blocked
        hosts list, to signify that they are ready for their next task.
        '''

        if HAS_ATFORK:
            atfork()

        signal.signal(signal.SIGINT, signal.SIG_IGN)

        while True:
            task_data = None
            try:
                if not self._job_queue.empty():
                    (host, task_data, job_vars, connection_info, loader) = self._job_queue.get(block=False)

                    # deserialize the task/handler from the data sent through the queue
                    if 'is_handler' in task_data:
                        task = Handler()
                    else:
                        task = Task()
                    task.deserialize(task_data)

                    new_connection_info = connection_info.set_task_override(task)

                    # execute the task and build a TaskResult from the result
                    executor_result = TaskExecutor(host, task, job_vars, new_connection_info, loader).run()
                    task_result = TaskResult(host, task_data, executor_result)

                    # put the result on the result queue
                    self._res_queue.put(task_result)

                    # notify the queue that the task was completed, so any joined
                    # threads will be properly notified when all tasks are complete
                    self._job_queue.task_done()

            except Queue.Empty:
                pass
            except (IOError, EOFError):
                break
            except AnsibleConnectionFailure:
                if task_data:
                    task_result = TaskResult(host, task_data, dict(unreachable=True))
                    self._res_queue.put(task_result)
                self._job_queue.task_done()
                break
            except:
                if task_data:
                    task_result = TaskResult(host, task_data, dict(failed=True, stdout=traceback.format_exc()))
                    self._res_queue.put(task_result)
                self._job_queue.task_done()
                break

            # a small pause here, to avoid a tight spin
            time.sleep(0.2)

