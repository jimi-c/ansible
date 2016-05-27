# (c) 2016, Ansible, Inc. <support@ansible.com>
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

from collections import MutableMapping

from ansible import constants as C
from ansible.utils.vars import merge_hash

class AnsibleChainMap(MutableMapping):
    '''
    A variation of the ChainMap idea, which is extended here to
    also support merging dicts values from multiple levels.
    '''
    def __init__(self, *args, **kwargs):
        self._maps = [dict()]

    def __str__(self):
        return str(self.to_dict())

    def __getitem__(self, k):
        if C.DEFAULT_HASH_BEHAVIOUR == 'merge':
            tmp = None
            found = False
            for m in self._maps:
                if k in m:
                    if isinstance(m[k], dict) and isinstance(tmp, dict):
                        tmp = merge_hash(tmp, m[k])
                    else:
                        tmp = m[k]
                    found = True
            if found:
                return tmp
        else:
            for m in reversed(self._maps):
                if k in m:
                    return m[k]
        raise KeyError

    def __setitem__(self, k, v):
        '''
        This sets the key to the value specified if it is found in any
        mapping in the list, otherwise it is set in the default dict
        (slot 0 in the maps list)
        '''
        for m in reversed(self._maps):
            if k in m:
                m[k] = v
                break
        else:
            self._maps[0][k] = v

    def __delitem__(self, k):
        '''
        This deletes the key in ALL maps contained within the list.
        '''
        for m in self._maps:
            if k in m:
                del m[k]

    def __iter__(self):
        for k in self.keys():
            yield k

    def __len__(self):
        return len(self.keys())

    def keys(self):
        key_set = set()
        for m in self._maps:
            key_set.update(m)

        return list(key_set)

    def update(self, m):
        assert isinstance(m, MutableMapping)
        self.push(m)

    def push(self, m):
        self._maps.append(m)

    def pop(self):
        return self._maps.pop()

    def copy(self):
        new_map = AnsibleChainMap()
        new_map._maps = self._maps[:]
        return new_map

    def to_dict(self):
        return dict((k, self[k]) for k in self.keys())
