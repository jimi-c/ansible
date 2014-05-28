# (c) 2014, Michael DeHaan <michael.dehaan@gmail.com>
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

import json

__all__ = ['isprintable', 'count_newlines_from_end', 'jsonify']

def isprintable(instring):
    if isinstance(instring, str):
        #http://stackoverflow.com/a/3637294
        import string
        printset = set(string.printable)
        isprintable = set(instring).issubset(printset)
        return isprintable
    else:
        return True

def count_newlines_from_end(str):
    i = len(str)
    while i > 0:
        if str[i-1] != '\n':
            break
        i -= 1
    return len(str) - i

def jsonify(result, format=False):
    ''' format JSON output (uncompressed or uncompressed) '''

    if result is None:
        return "{}"
    result2 = result.copy()
    for key, value in result2.items():
        if type(value) is str:
            result2[key] = value.decode('utf-8', 'ignore')
    if format:
        return json.dumps(result2, sort_keys=True, indent=4)
    else:
        return json.dumps(result2, sort_keys=True)

