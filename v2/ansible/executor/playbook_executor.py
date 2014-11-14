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

from ansible import constants as C
from ansible.executor.task_queue_manager import TaskQueueManager

class PlaybookExecutor:

    '''
    This is the primary class for executing playbooks, and thus the
    basis for bin/ansible-playbook operation.
    '''

    def __init__(self, inventory, options):
        self._inventory = inventory
        self._options = options

        self._tqm = TaskQueueManager(inventory=self._inventory, num_forks=options.forks)

    def run(self, playbook, variable_manager):

        '''
        Run the given playbook, based on the settings in the play which
        may limit the runs to serialized groups, etc.
        '''

        # FIXME: playbook entries are just plays, so we should rename them
        for entry in playbook.get_entries():
            all_vars = variable_manager.get_vars(play=entry)
            entry.post_validate(all_vars=all_vars)
            self._inventory.remove_restriction()
            for batch in self._get_serialized_batches(entry):
                if len(batch) == 0:
                    raise AnsibleError("No hosts matched the list specified in the play", obj=entry._ds)
                # restrict the inventory to the hosts in the serialized batch
                self._inventory.restrict_to_hosts(batch)
                # run it...
                self._tqm.run(play=entry, variable_manager=variable_manager)

    def _get_serialized_batches(self, play):
        '''
        Returns a list of hosts, subdivided into batches based on
        the serial size specified in the play.
        '''

        # make sure we have a unique list of hosts
        all_hosts = self._inventory.get_hosts()[:]

        # check to see if the serial number was specified as a percentage,
        # and convert it to an integer value based on the number of hosts
        if isinstance(play.serial, basestring) and play.serial.endswith('%'):
            serial_pct = int(play.serial.replace("%",""))
            serial = int((serial_pct/100.0) * len(all_hosts))
        else:
            serial = int(play.serial)

        # if the serial count was not specified or is invalid, default to
        # a list of all hosts, otherwise split the list of hosts into chunks
        # which are based on the serial size
        if serial <= 0:
            return [all_hosts]
        else:
            serialized_batches = []

            while len(all_hosts) > 0:
                play_hosts = []
                for x in range(serial):
                    if len(all_hosts) > 0:
                        play_hosts.append(all_hosts.pop(0))

                serialized_batches.append(play_hosts)

            return serialized_batches
