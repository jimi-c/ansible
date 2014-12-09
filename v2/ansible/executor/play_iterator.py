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

from ansible.playbook.task import Task

__all__ = ['PlayIterator']


# the primary running states for the play iteration
ITERATING_SETUP    = 0
ITERATING_TASKS    = 1
ITERATING_RESCUE   = 2
ITERATING_ALWAYS   = 3
ITERATING_COMPLETE = 4

# the failure states for the play iteration
FAILED_NONE        = 0
FAILED_SETUP       = 1
FAILED_TASKS       = 2
FAILED_RESCUE      = 3
FAILED_ALWAYS      = 4

class PlayState:

    '''
    A helper class, which keeps track of the task iteration
    state for a given playbook. This is used in the PlaybookIterator
    class on a per-host basis.
    '''

    # FIXME: this class is the representation of a finite state machine,
    #        so we really should have a well defined state representation
    #        documented somewhere...

    def __init__(self, parent_iterator):
        '''
        Create the initial state, which tracks the running state as well
        as the failure state, which are used when executing block branches
        (rescue/always)
        '''

        self._run_state       = ITERATING_SETUP
        self._failed_state    = FAILED_NONE
        self._task_list       = parent_iterator._play.compile()
        self._gather_facts    = parent_iterator._play.gather_facts

        self._cur_block       = None
        self._cur_task_pos    = 0
        self._cur_rescue_pos  = 0
        self._cur_always_pos  = 0
        self._cur_handler_pos = 0

    def next(self, peek=False):
        '''
        Determines and returns the next available task from the playbook,
        advancing through the list of plays as it goes. If peek is set to True,
        the internal state is not stored.
        '''

        task = None

        # save this locally so that we can peek at the next task
        # without updating the internal state of the iterator
        run_state       = self._run_state
        failed_state    = self._failed_state
        cur_block       = self._cur_block
        cur_task_pos    = self._cur_task_pos
        cur_rescue_pos  = self._cur_rescue_pos
        cur_always_pos  = self._cur_always_pos
        cur_handler_pos = self._cur_handler_pos

        while True:
            if run_state == ITERATING_SETUP:
                if failed_state == FAILED_SETUP:
                    run_state = ITERATING_COMPLETE
                else:
                    # FIXME: deal with smart vs. true/false for gathering facts
                    run_state = ITERATING_TASKS
                    if self._gather_facts:
                        task = Task()
                        task.action = 'setup'
                        break
            elif run_state == ITERATING_TASKS:
                # if there is any failure state besides FAILED_NONE, we should
                # change to some other running state
                if failed_state != FAILED_NONE or cur_task_pos > len(self._task_list) - 1:
                    # if there is a block (and there always should be), start running
                    # the rescue portion if it exists (and if we haven't failed that
                    # already), or the always portion (if it exists and we didn't fail
                    # there too). Otherwise, we're done iterating.
                    if cur_block:
                        if failed_state != FAILED_RESCUE and cur_block.rescue:
                            run_state = ITERATING_RESCUE
                            cur_rescue_pos = 0
                        elif failed_state != FAILED_ALWAYS and cur_block.always:
                            run_state = ITERATING_ALWAYS
                            cur_always_pos = 0
                        else:
                            run_state = ITERATING_COMPLETE
                    else:
                        run_state = ITERATING_COMPLETE
                else:
                    # FIXME: do tag/conditional evaluation here and advance
                    #        the task position if it should be skipped without
                    #        returning a task
                    task = self._task_list[cur_task_pos]
                    if cur_block is not None and cur_block != task._block:
                        run_state = ITERATING_ALWAYS
                        continue
                    else:
                        cur_block = task._block
                    cur_task_pos += 1

                    # Skip the task if it is the member of a role which has already
                    # been run, unless the role allows multiple executions
                    if task._role:
                        # FIXME: this should all be done via member functions
                        #        instead of direct access to internal variables
                        if task._role.has_run() and not task._role._metadata._allow_duplicates:
                            continue

                    # Break out of the while loop now that we have our task
                    break

            elif run_state == ITERATING_RESCUE:
                # If we're iterating through the rescue tasks, make sure we haven't
                # failed yet. If so, move on to the always block or if not get the
                # next rescue task (if one exists)
                if failed_state == FAILED_RESCUE or cur_block.rescue is None or cur_rescue_pos > len(cur_block.rescue) - 1:
                    run_state = ITERATING_ALWAYS
                else:
                    task = cur_block.rescue[cur_rescue_pos]
                    cur_rescue_pos += 1
                    break

            elif run_state == ITERATING_ALWAYS:
                # If we're iterating through the always tasks, make sure we haven't
                # failed yet. If so, we're done iterating otherwise get the next always
                # task (if one exists)
                if failed_state == FAILED_ALWAYS or cur_block.always is None or cur_always_pos > len(cur_block.always) - 1:
                    cur_block = None
                    if failed_state == FAILED_ALWAYS or cur_task_pos > len(self._task_list) - 1:
                        run_state = ITERATING_COMPLETE
                    else:
                        run_state = ITERATING_TASKS
                else:
                    task = cur_block.always[cur_always_pos]
                    cur_always_pos += 1
                    break

            elif run_state == ITERATING_COMPLETE:
                # done iterating, return None to signify that
                return None

        # If we're not just peeking at the next task, save the internal state 
        if not peek:
            self._run_state       = run_state
            self._failed_state    = failed_state
            self._cur_block       = cur_block
            self._cur_task_pos    = cur_task_pos
            self._cur_rescue_pos  = cur_rescue_pos
            self._cur_always_pos  = cur_always_pos
            self._cur_handler_pos = cur_handler_pos

        return task

    def mark_failed(self):
        '''
        Escalates the failed state relative to the running state.
        '''
        if self._run_state == ITERATING_SETUP:
            self._failed_state = FAILED_SETUP
        elif self._run_state == ITERATING_TASKS:
            self._failed_state = FAILED_TASKS
        elif self._run_state == ITERATING_RESCUE:
            self._failed_state = FAILED_RESCUE
        elif self._run_state == ITERATING_ALWAYS:
            self._failed_state = FAILED_ALWAYS


class PlayIterator:

    '''
    The main iterator class, which keeps the state of the playbook
    on a per-host basis using the above PlaybookState class.
    '''

    def __init__(self, inventory, play):
        self._play         = play
        self._inventory    = inventory
        self._host_entries = dict()
        self._first_host   = None

        # build the per-host dictionary of playbook states
        for host in inventory.filter_hosts(play.hosts):
            if self._first_host is None:
                self._first_host = host
            self._host_entries[host.get_name()] = PlayState(parent_iterator=self)

    def get_next_task(self, peek=False):
        ''' returns the next task for host[0] '''
        return self._host_entries[self._first_host.get_name()].next(peek=peek)

    def get_next_task_for_host(self, host, peek=False):
        ''' fetch the next task for the given host '''
        if host.get_name() not in self._host_entries:
            raise AnsibleError("invalid host specified for playbook iteration")

        return self._host_entries[host.get_name()].next(peek=peek)

    def mark_host_failed(self, host):
       ''' mark the given host as failed '''
       if host.get_name() not in self._host_entries:
           raise AnsibleError("invalid host specified for playbook iteration")

       self._host_entries[host.get_name()].mark_failed()

