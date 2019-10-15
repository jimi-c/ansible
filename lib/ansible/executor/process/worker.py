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

import msgpack
import multiprocessing
import os
import sys
import traceback

from jinja2.exceptions import TemplateNotFound

HAS_PYCRYPTO_ATFORK = False
try:
    from Crypto.Random import atfork
    HAS_PYCRYPTO_ATFORK = True
except Exception:
    # We only need to call atfork if pycrypto is used because it will need to
    # reinitialize its RNG.  Since old paramiko could be using pycrypto, we
    # need to take charge of calling it.
    pass

from ansible.errors import AnsibleConnectionFailure
from ansible.executor.task_executor import TaskExecutor
from ansible.executor.task_result import TaskResult
from ansible.module_utils._text import to_text
from ansible.module_utils.urls import ParseResultDottedDict as DottedDict
from ansible.utils.display import Display
from ansible.utils.sentinel import Sentinel

__all__ = ['WorkerProcess']

display = Display()


class WorkerProcess(multiprocessing.Process):
    '''
    The worker thread class, which uses TaskExecutor to run tasks
    read from a job queue and pushes results into a results queue
    for reading later.
    '''

    def __init__(self, in_q, final_q, loader, variable_manager, hostvars, shared_loader_obj):

        super(WorkerProcess, self).__init__()
        # takes a task queue manager as the sole param:
        self._in_q = in_q
        self._final_q = final_q
        self._loader = loader
        self._variable_manager = variable_manager
        self._shared_loader_obj = shared_loader_obj
        self._hostvars = hostvars

    def _save_stdin(self):
        self._new_stdin = os.devnull
        try:
            if sys.stdin.isatty() and sys.stdin.fileno() is not None:
                try:
                    self._new_stdin = os.fdopen(os.dup(sys.stdin.fileno()))
                except OSError:
                    # couldn't dupe stdin, most likely because it's
                    # not a valid file descriptor, so we just rely on
                    # using the one that was passed in
                    pass
        except (AttributeError, ValueError):
            # couldn't get stdin's fileno, so we just carry on
            pass

    def start(self):
        '''
        multiprocessing.Process replaces the worker's stdin with a new file
        opened on os.devnull, but we wish to preserve it if it is connected to
        a terminal. Therefore dup a copy prior to calling the real start(),
        ensuring the descriptor is preserved somewhere in the new child, and
        make sure it is closed in the parent when start() completes.
        '''

        self._save_stdin()
        try:
            return super(WorkerProcess, self).start()
        finally:
            if self._new_stdin != os.devnull:
                self._new_stdin.close()

    def _hard_exit(self, e):
        '''
        There is no safe exception to return to higher level code that does not
        risk an innocent try/except finding itself executing in the wrong
        process. All code executing above WorkerProcess.run() on the stack
        conceptually belongs to another program.
        '''

        try:
            display.debug(u"WORKER HARD EXIT: %s" % to_text(e))
        except BaseException:
            # If the cause of the fault is IOError being generated by stdio,
            # attempting to log a debug message may trigger another IOError.
            # Try printing once then give up.
            pass

        os._exit(1)

    def run(self):
        '''
        Wrap _run() to ensure no possibility an errant exception can cause
        control to return to the StrategyBase task loop, or any other code
        higher in the stack.

        As multiprocessing in Python 2.x provides no protection, it is possible
        a try/except added in far-away code can cause a crashed child process
        to suddenly assume the role and prior state of its parent.
        '''
        try:
            return self._run()
        except BaseException as e:
            self._hard_exit(e)

    def _run(self):
        '''
        Called when the process is started.  Pushes the result onto the
        results queue. We also remove the host from the blocked hosts list, to
        signify that they are ready for their next task.
        '''

        # import cProfile, pstats, StringIO
        # pr = cProfile.Profile()
        # pr.enable()

        if HAS_PYCRYPTO_ATFORK:
            atfork()

        ########################################################################
        # MITOGEN STUFF
        import ctypes
        import random
        import struct

        def _mask_to_bytes(mask):
            """
            Convert the (type long) mask to a cpu_set_t.
            """
            chunks = []
            shiftmask = (2 ** 64) - 1
            for x in range(16):
                chunks.append(struct.pack('<Q', mask & shiftmask))
                mask >>= 64
            return str.encode('').join(chunks)

        _libc = ctypes.CDLL(None, use_errno=True)
        _sched_setaffinity = _libc.sched_setaffinity
        # forking seems to work best when the forks are given free reign
        # over all the CPUs available. So we just mask off CPU0 to dedicate
        # those to the main proc and results thread.
        s = _mask_to_bytes(0xFFFFFFFFFFFFFFFE)
        _sched_setaffinity(os.getpid(), len(s), s)
        ########################################################################

        # execute the task and build a TaskResult from the result
        while True:
            try:
                job = self._in_q.get()
                if isinstance(job, Sentinel):
                    break

                task_vars = {}
                try:
                    (host, task, task_vars_path, play_context, plugin_paths) = job
                    host = DottedDict(host)
                    task = DottedDict(task)
                    play_context = DottedDict(play_context)
                    with open(task_vars_path, 'rb') as f:
                        task_vars = msgpack.unpackb(f.read(), raw=False)
                    os.unlink(task_vars_path)
                except ValueError as e:
                    # FIXME: send back a failed result re: invalid job params
                    # FIXME: catch possible errors from JSON and unlink
                    print("OOPS: %s" % e)
                    break

                # readd the hostvars to task_vars (which were excluded earlier)
                task_vars['hostvars'] = self._hostvars

                display.debug("running TaskExecutor() for %s/%s [name: %s]" % (host.name, task.uuid, task.name))
                executor_result = TaskExecutor(
                    host,
                    task,
                    task_vars,
                    play_context,
                    self._new_stdin,
                    self._loader,
                    self._shared_loader_obj,
                    self._final_q,
                ).run()
                display.debug("done running TaskExecutor() for %s/%s [name: %s]" % (host.name, task.uuid, task.name))

                task_result = TaskResult(
                    host.name,
                    task.uuid,
                    executor_result,
                    task_fields=task,
                )

                # put the result on the result queue
                display.debug("sending task result for task %s" % task.uuid)
                self._final_q.put(task_result)
                display.debug("done sending task result for task %s" % task.uuid)

            except AnsibleConnectionFailure:
                task_result = TaskResult(
                    host.name,
                    task.uuid,
                    dict(unreachable=True),
                    task_fields=task,
                )
                self._final_q.put(task_result, block=False)

            except Exception as e:
                if not isinstance(e, (IOError, EOFError, KeyboardInterrupt, SystemExit)) or isinstance(e, TemplateNotFound):
                    try:
                        task_result = TaskResult(
                            host.name,
                            task.uuid,
                            dict(failed=True, exception=to_text(traceback.format_exc()), stdout=''),
                            task_fields=task,
                        )
                        self._final_q.put(task_result, block=False)
                    except Exception:
                        display.debug(u"WORKER EXCEPTION: %s" % to_text(e))
                        display.debug(u"WORKER TRACEBACK: %s" % to_text(traceback.format_exc()))
                break

        display.debug("WORKER PROCESS EXITING")

        # pr.disable()
        # s = StringIO.StringIO()
        # sortby = 'time'
        # ps = pstats.Stats(pr, stream=s).sort_stats(sortby)
        # ps.print_stats()
        # with open('worker_%06d.stats' % os.getpid(), 'w') as f:
        #     f.write(s.getvalue())
