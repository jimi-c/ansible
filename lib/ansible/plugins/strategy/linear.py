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

DOCUMENTATION = '''
    name: linear
    short_description: Executes tasks in a linear fashion
    description:
        - Task execution is in lockstep per host batch as defined by C(serial) (default all).
          Up to the fork limit of hosts will execute each task at the same time and then
          the next series of hosts until the batch is done, before going on to the next task.
    version_added: "2.0"
    notes:
     - This was the default Ansible behaviour before 'strategy plugins' were introduced in 2.0.
    author: Ansible Core Team
'''

import copy

from ansible import constants as C
from ansible.errors import AnsibleError, AnsibleAssertionError, AnsibleParserError, AnsibleUndefinedVariable
from ansible.executor.play_iterator import IteratingStates, FailedStates
from ansible.module_utils.common.text.converters import to_text
from ansible.playbook.handler import Handler
from ansible.playbook.included_file import IncludedFile
from ansible.playbook.task import Task
from ansible.plugins.loader import action_loader
from ansible.plugins.strategy import StrategyBase
from ansible.template import Templar
from ansible.utils.display import Display

display = Display()


class StrategyModule(StrategyBase):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # used for the lockstep to indicate to run handlers
        self._in_handlers = False

    def _get_next_task_lockstep(self, hosts, iterator):
        '''
        Returns a list of (host, task) tuples, where the task may
        be a noop task to keep the iterator in lock step across
        all hosts.
        '''
        noop_task = Task()
        noop_task.action = 'meta'
        noop_task.args['_raw_params'] = 'noop'
        noop_task.implicit = True
        noop_task.set_loader(iterator._play._loader)

        state_task_per_host = {}
        for host in hosts:
            state, task = iterator.get_next_task_for_host(host, peek=True)
            if task is not None:
                state_task_per_host[host] = state, task

        if not state_task_per_host:
            return [(h, None) for h in hosts]

        if self._in_handlers and not any(filter(
            lambda rs: rs == IteratingStates.HANDLERS,
            (s.run_state for s, dummy in state_task_per_host.values()))
        ):
            self._in_handlers = False

        if self._in_handlers:
            lowest_cur_handler = min(
                s.cur_handlers_task for s, t in state_task_per_host.values()
                if s.run_state == IteratingStates.HANDLERS
            )
        else:
            task_uuids = [t._uuid for s, t in state_task_per_host.values()]
            _loop_cnt = 0
            while _loop_cnt <= 1:
                try:
                    cur_task = iterator.all_tasks[iterator.cur_task]
                except IndexError:
                    # pick up any tasks left after clear_host_errors
                    iterator.cur_task = 0
                    _loop_cnt += 1
                else:
                    iterator.cur_task += 1
                    if cur_task._uuid in task_uuids:
                        break
            else:
                # prevent infinite loop
                raise AnsibleAssertionError(
                    'BUG: There seems to be a mismatch between tasks in PlayIterator and HostStates.'
                )

        host_tasks = []
        for host, (state, task) in state_task_per_host.items():
            if ((self._in_handlers and lowest_cur_handler == state.cur_handlers_task) or
                    (not self._in_handlers and cur_task._uuid == task._uuid)):
                iterator.set_state_for_host(host.name, state)
                host_tasks.append((host, task))
            else:
                host_tasks.append((host, noop_task))

        # once hosts synchronize on 'flush_handlers' lockstep enters
        # '_in_handlers' phase where handlers are run instead of tasks
        # until at least one host is in IteratingStates.HANDLERS
        if (not self._in_handlers and cur_task.action in C._ACTION_META and
                cur_task.args.get('_raw_params') == 'flush_handlers'):
            self._in_handlers = True

        return host_tasks

    def run(self, iterator, play_context):
        '''
        The linear strategy is simple - get the next task and queue
        it for all hosts, then wait for the queue to drain before
        moving on to the next task
        '''

        # iterate over each task, while there is one left to run
        result = self._tqm.RUN_OK
        work_to_do = True

        self._set_hosts_cache(iterator._play)

        # a dictionary to store loop eval errors, which may not be immediately
        # fatal when first hit if the host is not later skipped. The key is the
        # hostname, and the value is the raised exception
        loop_eval_error = None

        while work_to_do and not self._tqm._terminated:

            try:
                display.debug("getting the remaining hosts for this loop")
                hosts_left = self.get_hosts_left(iterator)
                display.debug("done getting the remaining hosts for this loop")

                # queue up this task for each host in the inventory
                callback_sent = False
                work_to_do = False

                host_tasks = self._get_next_task_lockstep(hosts_left, iterator)

                # skip control
                skip_rest = False
                choose_step = True

                # flag set if task is set to any_errors_fatal
                any_errors_fatal = False

                results = []
                for (host, task) in host_tasks:
                    if not task:
                        continue

                    if self._tqm._terminated:
                        break

                    run_once = False
                    work_to_do = True

                    # check to see if this task should be skipped, due to it being a member of a
                    # role which has already run (and whether that role allows duplicate execution)
                    if not isinstance(task, Handler) and task._role:
                        role_obj = self._get_cached_role(task, iterator._play)
                        if role_obj.has_run(host) and role_obj._metadata.allow_duplicates is False:
                            display.debug("'%s' skipped because role has already run" % task)
                            continue

                    display.debug("getting variables")
                    task_vars = self._variable_manager.get_vars(
                        play=iterator._play, host=host, task=task, _hosts=self._hosts_cache, _hosts_all=self._hosts_cache_all
                    )
                    self.add_tqm_variables(task_vars, play=iterator._play)

                    templar = Templar(loader=self._loader, variables=task_vars)
                    display.debug("done getting variables")

                    # test to see if the task across all hosts points to an action plugin which
                    # sets BYPASS_HOST_LOOP to true, or if it has run_once enabled. If so, we
                    # will only send this task to the first host in the list.

                    task_action = templar.template(task.action)

                    try:
                        action = action_loader.get(task_action, class_only=True, collection_list=task.collections)
                    except KeyError:
                        # we don't care here, because the action may simply not have a
                        # corresponding action plugin
                        action = None

                    #print("TASK ACTION:", task_action)
                    # determine if this task should only run once, and if any errors are fatal
                    run_once = templar.template(task.run_once) or action and getattr(action, 'BYPASS_HOST_LOOP', False)
                    if (task.any_errors_fatal or run_once) and not task.ignore_errors:
                        any_errors_fatal = True

                    # build list of loop items, if this task has a loop
                    try:
                        items = self._get_loop_items(task, templar, task_vars)
                    except AnsibleUndefinedVariable as e:
                        # save the error raised here for use later
                        items = []
                        loop_eval_error = e

                    has_loop = False
                    loop_control = None
                    #print(items)
                    if items is not None and len(items) > 0:
                        has_loop = True
                        loop_control = copy.deepcopy(task.loop_control)
                        loop_control.post_validate(templar=templar)

                    #print("ARE WE LOOPING?", has_loop)
                    pc = play_context.copy()

                    if not callback_sent:
                        display.debug("sending task start callback, copying the task so we can template it temporarily")
                        saved_name = task.name
                        display.debug("done copying, going to template now")
                        try:
                            task.name = to_text(templar.template(task.name, fail_on_undefined=False), nonstring='empty')
                            display.debug("done templating")
                        except Exception:
                            # just ignore any errors during task name templating,
                            # we don't care if it just shows the raw name
                            display.debug("templating failed for some reason")
                        display.debug("here goes the callback...")
                        if isinstance(task, Handler):
                            self._tqm.send_callback('v2_playbook_on_handler_task_start', task)
                        else:
                            self._tqm.send_callback('v2_playbook_on_task_start', task, is_conditional=False)
                        task.name = saved_name
                        callback_sent = True
                        display.debug("sending task start callback")

                    cur_item = 0
                    while True:
                        item = None
                        # setup loop variables in the task_vars if we're in a loop
                        if has_loop:
                            item = items[cur_item]
                            #print("LOOP ITEM:", item)
                            task_vars['ansible_loop_var'] = loop_control.loop_var
                            task_vars[loop_control.loop_var] = item

                            if loop_control.index_var:
                                task_vars['ansible_index_var'] = loop_control.index_var
                                task_vars[loop_control.index_var] = cur_item

                            if loop_control.extended:
                                items_len = len(items)
                                task_vars['ansible_loop'] = {
                                    'index': cur_item + 1,
                                    'index0': cur_item,
                                    'first': cur_item == 0,
                                    'last': cur_item + 1 == items_len,
                                    'length': items_len,
                                    'revindex': items_len - cur_item,
                                    'revindex0': items_len - cur_item - 1,
                                }
                                if loop_control.extended_allitems:
                                    task_vars['ansible_loop']['allitems'] = items
                                try:
                                    task_vars['ansible_loop']['nextitem'] = items[cur_item + 1]
                                except IndexError:
                                    pass
                                if cur_item - 1 >= 0:
                                    task_vars['ansible_loop']['previtem'] = items[cur_item - 1]

                        if task_action in C._ACTION_META:
                            #print("DOING META FOR TASK:", task)
                            # for the linear strategy, we run meta tasks just once and for
                            # all hosts currently being iterated over rather than one host
                            results.extend(self._execute_meta(task, play_context, iterator, host))
                            if task.args.get('_raw_params', None) not in ('noop', 'reset_connection', 'end_host', 'role_complete', 'flush_handlers'):
                                run_once = True
                            if (task.any_errors_fatal or run_once) and not task.ignore_errors:
                                any_errors_fatal = True
                        elif task_action in C._ACTION_INCLUDE_TASKS:
                            # if this task is a TaskInclude, we just return now with a success code so the
                            # main thread can expand the task list for the given host
                            include_args = task.args.copy()
                            include_file = include_args.pop('_raw_params', None)
                            if not include_file:
                                # FIXME: handle properly
                                #return dict(failed=True, msg="No include file was specified to the include")
                                pass

                            include_file = templar.template(include_file)
                            # FIXME: handle properly
                            #return dict(include=include_file, include_args=include_args)
                        elif task_action in C._ACTION_INCLUDE_ROLE:
                            # if this task is a IncludeRole, we just return now with a success code so the main thread can expand the task list for the given host
                            include_args = task.args.copy()
                            # FIXME: handle properly
                            #return dict(include_args=include_args)
                        else:
                            # WAS _calculate_delegate_to
                            # can (should) be moved to the base class for use in other strategies
                            delegated_vars, delegated_host_name = self._variable_manager.get_delegated_vars_and_hostname(
                                templar,
                                task,
                                task_vars,
                            )
                            # At the point this is executed it is safe to mutate self._task,
                            # since `self._task` is either a copy referred to by `tmp_task` in `_run_loop`
                            # or just a singular non-looped task
                            if delegated_host_name:
                                task.delegate_to = delegated_host_name
                                task_vars.update(delegated_vars)
                            # END _calculate_delegate_to

                            context_validation_error = None
                            try:
                                # TODO: remove play_context as this does not take delegation nor loops correctly into account,
                                # the task itself should hold the correct values for connection/shell/become/terminal plugin options to finalize.
                                #  Kept for now for backwards compatibility and a few functions that are still exclusive to it.

                                # apply the given task's information to the connection info,
                                # which may override some fields already set by the play or
                                # the options specified on the command line
                                pc = pc.set_task_and_variable_override(task=task, variables=task_vars, templar=templar)

                                # fields set from the play/task may be based on variables, so we have to
                                # do the same kind of post validation step on it here before we use it.
                                pc.post_validate(templar=templar)

                                # now that the play context is finalized, if the remote_addr is not set
                                # default to using the host's address field as the remote address
                                if not pc.remote_addr:
                                    pc.remote_addr = host.address

                                # We also add "magic" variables back into the variables dict to make sure
                                # FIXME: THIS DOES NOT SEEM RIGHT
                                pc.update_vars(task_vars)

                            except AnsibleError as e:
                                # save the error, which we'll raise later if we don't end up
                                # skipping this task during the conditional evaluation step
                                context_validation_error = e

                            # Evaluate the conditional (if any) for this task, which we do before running
                            # the final task post-validation. We do this before the post validation due to
                            # the fact that the conditional may specify that the task be skipped due to a
                            # variable not being present which would otherwise cause validation to fail
                            try:
                                conditional_result, false_condition = task.evaluate_conditional_with_result(templar, task_vars)
                                if not conditional_result:
                                    display.debug("when evaluation is False, skipping this task")
                                    # FIXME: need to insert result into task_results
                                    continue
                            except AnsibleError as e:
                                # FIXME: need to insert result into task_results and mark host failed
                                # loop error takes precedence
                                if loop_eval_error is not None:
                                    # Display the error from the conditional as well to prevent
                                    # losing information useful for debugging.
                                    display.v(to_text(e))
                                continue

                            # Not skipping, if we had loop error raised earlier we need to raise it now to halt the execution of this task
                            if loop_eval_error is not None:
                                # FIXME: need to insert result into task_results and mark host failed
                                continue

                            # if we ran into an error while setting up the PlayContext, raise it now, unless is known issue with delegation
                            # and undefined vars (correct values are in cvars later on and connection plugins, if still error, blows up there)
                            if context_validation_error is not None:
                                raiseit = True
                                if task.delegate_to:
                                    if isinstance(context_validation_error, AnsibleUndefinedVariable):
                                        raiseit = False
                                    elif isinstance(context_validation_error, AnsibleParserError):
                                        # parser error, might be cause by undef too
                                        orig_exc = getattr(context_validation_error, 'orig_exc', None)
                                        if isinstance(orig_exc, AnsibleUndefinedVariable):
                                            raiseit = False
                                if raiseit:
                                    # FIXME: need to insert result into task_results and mark host failed
                                    continue

                            # handle step if needed, skip meta actions as they are used internally
                            if self._step and choose_step:
                                if self._take_step(task):
                                    choose_step = False
                                else:
                                    skip_rest = True
                                    break

                            # Now we do final validation on the task, which sets all fields to their final values.
                            try:
                                final_task = task.copy()
                                final_task.post_validate(templar=templar)
                            except AnsibleError:
                                raise
                            except Exception:
                                #return dict(changed=False, failed=True, _ansible_no_log=no_log, exception=to_text(traceback.format_exc()))
                                raise

                            self._blocked_hosts[host.get_name()] = True
                            #print("QUEUEING TASK")
                            self._queue_task(host, final_task, task_vars, pc, templar, item)

                        # if we had no loop items, or if we've run out of items we're done
                        if not has_loop or cur_item >= len(items) - 1:
                            #print("DONE WITH LOOP (or not)")
                            break

                        # otherwise move on to the next item in the loop
                        cur_item += 1


                    # if we're bypassing the host loop, break out now
                    if run_once:
                        break

                    # cleanup task vars, as we no longer need them
                    del task_vars

                    # do in-flight process result handling to make sure things aren't
                    # queueing up too badly while we're sending out jobs to workers
                    results.extend(self._process_pending_results(iterator, max_passes=max(1, int(len(self._tqm._workers) * 0.1))))

                # go to next host/task group
                if skip_rest:
                    continue

                display.debug("done queuing things up, now waiting for results queue to drain")
                if self._pending_results > 0:
                    results.extend(self._wait_on_pending_results(iterator))

                self.update_active_connections(results)

                included_files = IncludedFile.process_include_results(
                    results,
                    iterator=iterator,
                    loader=self._loader,
                    variable_manager=self._variable_manager
                )

                if len(included_files) > 0:
                    display.debug("we have included files to process")

                    display.debug("generating all_blocks data")
                    all_blocks = dict((host, []) for host in hosts_left)
                    display.debug("done generating all_blocks data")
                    included_tasks = []
                    failed_includes_hosts = set()
                    for included_file in included_files:
                        display.debug("processing included file: %s" % included_file._filename)
                        is_handler = False
                        try:
                            if included_file._is_role:
                                new_ir = self._copy_included_file(included_file)

                                new_blocks, handler_blocks = new_ir.get_block_list(
                                    play=iterator._play,
                                    variable_manager=self._variable_manager,
                                    loader=self._loader,
                                )
                            else:
                                is_handler = isinstance(included_file._task, Handler)
                                new_blocks = self._load_included_file(included_file, iterator=iterator, is_handler=is_handler)

                            # let PlayIterator know about any new handlers included via include_role or
                            # import_role within include_role/include_taks
                            iterator.handlers = [h for b in iterator._play.handlers for h in b.block]

                            display.debug("iterating over new_blocks loaded from include file")
                            for new_block in new_blocks:
                                if is_handler:
                                    for task in new_block.block:
                                        task.notified_hosts = included_file._hosts[:]
                                    final_block = new_block
                                else:
                                    task_vars = self._variable_manager.get_vars(
                                        play=iterator._play,
                                        task=new_block.get_first_parent_include(),
                                        _hosts=self._hosts_cache,
                                        _hosts_all=self._hosts_cache_all,
                                    )
                                    display.debug("filtering new block on tags")
                                    final_block = new_block.filter_tagged_tasks(task_vars)
                                    display.debug("done filtering new block on tags")

                                    included_tasks.extend(final_block.get_tasks())

                                for host in hosts_left:
                                    if host in included_file._hosts:
                                        all_blocks[host].append(final_block)

                            display.debug("done iterating over new_blocks loaded from include file")
                        except AnsibleParserError:
                            raise
                        except AnsibleError as e:
                            if included_file._is_role:
                                # include_role does not have on_include callback so display the error
                                display.error(to_text(e), wrap_text=False)
                            for r in included_file._results:
                                r._result['failed'] = True
                                failed_includes_hosts.add(r._host)
                            continue

                    for host in failed_includes_hosts:
                        self._tqm._failed_hosts[host.name] = True
                        iterator.mark_host_failed(host)

                    # finally go through all of the hosts and append the
                    # accumulated blocks to their list of tasks
                    display.debug("extending task lists for all hosts with included blocks")

                    for host in hosts_left:
                        iterator.add_tasks(host, all_blocks[host])

                    iterator.all_tasks[iterator.cur_task:iterator.cur_task] = included_tasks

                    display.debug("done extending task lists")
                    display.debug("done processing included files")

                display.debug("results queue empty")

                display.debug("checking for any_errors_fatal")
                failed_hosts = []
                unreachable_hosts = []
                for res in results:
                    # execute_meta() does not set 'failed' in the TaskResult
                    # so we skip checking it with the meta tasks and look just at the iterator
                    if (res.is_failed() or res._task.action in C._ACTION_META) and iterator.is_failed(res._host):
                        failed_hosts.append(res._host.name)
                    elif res.is_unreachable():
                        unreachable_hosts.append(res._host.name)

                # if any_errors_fatal and we had an error, mark all hosts as failed
                if any_errors_fatal and (len(failed_hosts) > 0 or len(unreachable_hosts) > 0):
                    dont_fail_states = frozenset([IteratingStates.RESCUE, IteratingStates.ALWAYS])
                    for host in hosts_left:
                        (s, dummy) = iterator.get_next_task_for_host(host, peek=True)
                        # the state may actually be in a child state, use the get_active_state()
                        # method in the iterator to figure out the true active state
                        s = iterator.get_active_state(s)
                        if s.run_state not in dont_fail_states or \
                           s.run_state == IteratingStates.RESCUE and s.fail_state & FailedStates.RESCUE != 0:
                            self._tqm._failed_hosts[host.name] = True
                            result |= self._tqm.RUN_FAILED_BREAK_PLAY
                display.debug("done checking for any_errors_fatal")

                display.debug("checking for max_fail_percentage")
                if iterator._play.max_fail_percentage is not None and len(results) > 0:
                    percentage = iterator._play.max_fail_percentage / 100.0

                    if (len(self._tqm._failed_hosts) / iterator.batch_size) > percentage:
                        for host in hosts_left:
                            # don't double-mark hosts, or the iterator will potentially
                            # fail them out of the rescue/always states
                            if host.name not in failed_hosts:
                                self._tqm._failed_hosts[host.name] = True
                                iterator.mark_host_failed(host)
                        self._tqm.send_callback('v2_playbook_on_no_hosts_remaining')
                        result |= self._tqm.RUN_FAILED_BREAK_PLAY
                    display.debug('(%s failed / %s total )> %s max fail' % (len(self._tqm._failed_hosts), iterator.batch_size, percentage))
                display.debug("done checking for max_fail_percentage")

                display.debug("checking to see if all hosts have failed and the running result is not ok")
                if result != self._tqm.RUN_OK and len(self._tqm._failed_hosts) >= len(hosts_left):
                    display.debug("^ not ok, so returning result now")
                    self._tqm.send_callback('v2_playbook_on_no_hosts_remaining')
                    return result
                display.debug("done checking to see if all hosts have failed")

            except (IOError, EOFError) as e:
                display.debug("got IOError/EOFError in task loop: %s" % e)
                # most likely an abort, return failed
                return self._tqm.RUN_UNKNOWN_ERROR

        # run the base class run() method, which executes the cleanup function
        # and runs any outstanding handlers which have been triggered

        return super(StrategyModule, self).run(iterator, play_context, result)
