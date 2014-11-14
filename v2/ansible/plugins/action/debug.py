# Copyright 2012, Dag Wieers <dag@wieers.com>
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

from ansible.plugins.action import ActionBase

class ActionModule(ActionBase):
    ''' Print statements during execution '''

    TRANSFERS_FILES = False

    def run(self, tmp=None):

        if 'msg' in self._task.args:
            # FIXME: the boolean function needs to be relocated
            #if 'fail' in args and utils.boolean(args['fail']):
            #    result = dict(failed=True, msg=args['msg'])
            #else:
            #    result = dict(msg=args['msg'])
            result = dict(msg=self._task.args['msg'])
        # FIXME: move this somewhere else, as it won't be in utils anymore
        #elif 'var' in args and not utils.LOOKUP_REGEX.search(args['var']):
        #    results = template.template(self.basedir, args['var'], inject, convert_bare=True)
        #    result[args['var']] = results
        else:
            result = dict(msg='here we are')

        # force flag to make debug output module always verbose
        result['verbose_always'] = True

        return result
