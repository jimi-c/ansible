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

from ansible.plugins.callback import CallbackBase


class CallbackModule(CallbackBase):

    '''
    This is the default callback interface, which simply prints messages
    to stdout when new callback events are received.
    '''

    def __init__(self):
        pass

    def _print_banner(self, msg):
        '''
        Prints a header-looking line with stars taking up to 80 columns
        of width (3 columns, minimum)
        '''
        msg = msg.strip()
        star_len = (80 - len(msg))
        if star_len < 0:
            star_len = 3
        stars = "*" * star_len
        print("\n%s %s\n" % (msg, stars))

    def on_any(self, *args, **kwargs):
        pass

    def runner_on_failed(self, task, result, ignore_errors=False):
        print("HOST %s: FAILED! => %s" % (result._host.get_name(), result._result))

    def runner_on_ok(self, task, result):
        print("HOST %s: %s OK => %s" % (result._host.get_name(), task, result._result))

    def runner_on_skipped(self, task, result):
        print("HOST %s: SKIPPED..." % result._host.get_name())

    def runner_on_unreachable(self, task, result):
        print("HOST %s: UNREACHABLE!" % result._host.get_name())

    def runner_on_no_hosts(self, task):
        pass

    def runner_on_async_poll(self, host, res, jid, clock):
        pass

    def runner_on_async_ok(self, host, res, jid):
        pass

    def runner_on_async_failed(self, host, res, jid):
        pass

    def playbook_on_start(self):
        pass

    def playbook_on_notify(self, host, handler):
        pass

    def playbook_on_no_hosts_matched(self):
        pass

    def playbook_on_no_hosts_remaining(self):
        self._print_banner("NO MORE HOSTS LEFT")

    def playbook_on_task_start(self, name, is_conditional):
        self._print_banner("TASK [%s]" % name.strip())

    def playbook_on_cleanup_task_start(self, name):
        self._print_banner("CLEANUP TASK [%s]" % name.strip())

    def playbook_on_handler_task_start(self, name):
        self._print_banner("RUNNING HANDLER [%s]" % name.strip())

    def playbook_on_vars_prompt(self, varname, private=True, prompt=None, encrypt=None, confirm=False, salt_size=None, salt=None, default=None):
        pass

    def playbook_on_setup(self):
        pass

    def playbook_on_import_for_host(self, host, imported_file):
        pass

    def playbook_on_not_import_for_host(self, host, missing_file):
        pass

    def playbook_on_play_start(self, name):
        self._print_banner("PLAY [%s]" % name.strip())

    def playbook_on_stats(self, stats):
        pass

