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

#############################################

import pipes
import shlex
import os
import sys
import uuid
import json

from ansible import constants as C
from ansible import utils
from ansible import errors
from ansible.playbook.task import Task
from ansible.utils.template import template

ROLE_CACHE = {}

__all__ = [ 'Role' ]

def _get_role_data(play, role_def):
    '''
    Returns the path on disk to the directory containing
    the role directories like tasks, templates, etc. Also
    returns any variables that were included with the role
    '''

    orig_path = template(play.basedir, role_def, play.vars)

    role_vars = {}
    if type(orig_path) == dict:
        # what, not a path?
        role_name = orig_path.get('role', None)
        if role_name is None:
            raise errors.AnsibleError("expected a role name in dictionary: %s" % orig_path)
        del orig_path['role']
        role_vars = orig_path
        orig_path = role_name
    else:
        role_name = orig_path

    role_path = None

    possible_paths = [
        utils.path_dwim(play.basedir, os.path.join('roles', orig_path)),
        utils.path_dwim(play.basedir, orig_path)
    ]

    if C.DEFAULT_ROLES_PATH:
        search_locations = C.DEFAULT_ROLES_PATH.split(os.pathsep)
        for loc in search_locations:
            loc = os.path.expanduser(loc)
            possible_paths.append(utils.path_dwim(loc, orig_path))

    for path_option in possible_paths:
        if os.path.isdir(path_option):
            role_path = path_option
            break

    if role_path is None:
        raise errors.AnsibleError("cannot find role in %s" % " or ".join(possible_paths))

    return (role_name, role_path, role_vars)

def _get_role_metadata(play, role_path):
    '''
    Loads the meta/main.yml for a role, if it exists
    '''

    meta_file = utils.resolve_main(utils.path_dwim(play.basedir, os.path.join(role_path, 'meta')))
    if os.path.isfile(meta_file):
        return utils.parse_yaml_from_file(meta_file, vault_password=play.vault_password)
    else:
        return {}

class Role(object):

    __slots__ = [
        'name', 'uuid', 'path', 'params', 'role_vars', 'default_vars', 'inherited_vars',
        'dependencies', 'allow_dupes', 'has_run', 'parent_role', 'tasks', 'handlers', 'depth',
        'play', 'metadata', 'tags', 'conditionals', 'multi_owner',
    ]

    def __repr__(self):
        if self.name:
            return "role: <name=%s uuid=%s>" % (self.name, self.uuid)
        else:
            return "unitialized role"

    def __new__(self, play, role_def, inherited_vars={}, *args, **kwargs):
        # check the ROLE_CACHE for a role with the same name and 
        # same parameters, and return it if a match is found so 
        # we don't create a new role object

        (role_name, role_path, role_params) = _get_role_data(play, role_def)
        metadata = _get_role_metadata(play, role_path)

        new_key = role_name + json.dumps(tuple(role_params.iteritems()))

        allow_dupes = False
        if metadata and isinstance(metadata, dict):
            allow_dupes = utils.boolean(metadata.get('allow_duplicates','no'))

        if not isinstance(inherited_vars, dict):
            raise errors.AnsibleErrors("inherted vars passed to a role must be a dictionary")

        for r in ROLE_CACHE.keys():
            if r == new_key:
                old_role = ROLE_CACHE[r]
                old_role.multi_owner    = True
                old_role.inherited_vars = utils.combine_vars(old_role.inherited_vars, inherited_vars)
                return ROLE_CACHE[r]
        else:
            new_role = super(Role, self).__new__(self, play, role_def, inherited_vars, *args, **kwargs)

            # these should only be initialized here, as __init__ is always called 
            # after __new__ even when we're returning an object that already exists, 
            # so we don't want to wipe out pre-existing data
            new_role.uuid           = str(uuid.uuid4())
            new_role.name           = role_name
            new_role.path           = role_path
            new_role.params         = role_params
            new_role.inherited_vars = inherited_vars
            new_role.metadata       = metadata
            new_role.allow_dupes    = allow_dupes
            new_role.tags           = []
            new_role.conditionals   = []
            new_role.multi_owner    = False

            # save it in the cache for later and return it
            ROLE_CACHE[new_key] = new_role
            return new_role

    def __init__(self, play, role_def, inherited_vars={}, depth=1):
        '''
        Creates a role from a given role definition, i.e.:
        # from a play or include
        roles:
          - foo
          - { role: foo }
        # from another role's meta/main.yml
        dependency: 
          - foo
          - { role: foo }
        '''

        if depth > 20:
            raise errors.AnsibleError("too many levels of recursion while resolving role dependencies")

        self.play    = play
        self.depth   = depth
        self.has_run = False

        self.role_vars    = self._load_role_vars_file('vars')
        self.default_vars = self._load_role_vars_file('defaults')

        self._load_conditionals()
        self._load_tags()
        self._load_dependencies()


    def _load_dependencies(self):
        '''
        Loads this roles dependencies from the metadata, and creates objects out of them
        '''

        self.dependencies = []
        if isinstance(self.metadata, dict):
            dependencies = self.metadata.get('dependencies',[])
            if dependencies is None:
                dependencies = []
            elif isinstance(dependencies, basestring):
                dependencies = [ dependencies, ]
            elif not isinstance(dependencies, list):
                raise errors.AnsibleError("dependencies must be a list in %s" % meta_file)

            for dependency in dependencies:
                passed_vars = utils.combine_vars(self.inherited_vars, self.role_vars)
                passed_vars = utils.combine_vars(passed_vars, self.params)
                if len(self.tags) > 0:
                    passed_vars['tags'] = self.tags
                if len(self.conditionals) > 0:
                    passed_vars['when'] = self.conditionals
                r = Role(self.play, dependency, passed_vars, self.depth+1)
                self.dependencies.append(r)

    def _load_conditionals(self):
        '''
        Loads conditionals based on the inherited variables as well as the role parameters
        '''

        def _do_load_conditionals(obj):
            if isinstance(obj, dict):
                conds = obj.get('when', None)
                if isinstance(conds, list):
                   self.conditionals.extend(conds)
                elif isinstance(conds, (basestring, bool)):
                   self.conditionals.append(conds)

        _do_load_conditionals(self.inherited_vars)
        _do_load_conditionals(self.params)

    def _load_tags(self):
        '''
        Loads tags from the inherited variables as well as the role parameters.
        '''

        def _merge_tags(obj):
            if isinstance(obj, dict):
                new_tags = obj.get('tags', [])
                if isinstance(new_tags, basestring):
                    new_tags = [new_tags, ]

            # filter tags we're applying to this based on the 
            # skipped/only tags present in the play
            self.tags = list(set(self.tags).union(set(new_tags)))

        _merge_tags(self.params)
        _merge_tags(self.inherited_vars)

        if self.multi_owner:
            # filter out tags that may cause problems later but make sure
            # we're not wiping out every tag, which would cause this role
            # to run as a dependency even if all parent roles were skipped
            filtered_tags = self.play._filter_tags(self.tags)
            if filtered_tags and filtered_tags != ['all']:
                self.tags = filtered_tags

    def _load_role_vars_file(self, type):
        '''
        Loads and returns the YAML variables contained within a file,
        which for roles is either defaults/main.yml or vars/main.yml.
        '''

        if type not in ['vars', 'defaults']:
            raise errors.AnsibleError("invalid role variable type: %s" % type)

        vars_file = utils.resolve_main(utils.path_dwim(self.play.basedir, os.path.join(self.path, type)))
        if os.path.isfile(vars_file):
            vars_data = utils.parse_yaml_from_file(vars_file, vault_password=self.play.vault_password)
            if not isinstance(vars_data, dict):
                 return {}
            return vars_data
        else:
            return {}

    def get_vars(self, global_vars={}):
        '''
        returns the merged view of the variables as seen
        by this role at the time it was created
        '''

        # inherited vars have the lowest priority
        vars = self.inherited_vars.copy()
        # merge the child vars recursively
        for dep in self.dependencies:
            vars = utils.combine_vars(vars, dep.get_vars())
        # and then merge in the higher-priority vars
        # starting with the role_vars (vars/main.yml)
        vars = utils.combine_vars(vars, self.role_vars)
        # and then the role params
        vars = utils.combine_vars(vars, self.params)
        # clean out things which may have shown up in vars
        # due to the nature of the declaration structure, but
        # which we do not want included as vars
        for bad_key in ('tags', 'when'):
            if vars.get(bad_key):
                del vars[bad_key]
        # and finally some special vars
        vars['role_name'] = self.name
        vars['role_uuid'] = self.uuid
        # done
        return vars
