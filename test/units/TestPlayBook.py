# -*- coding: utf-8 -*-

import collections
import mock
import os
import unittest
import yaml

from ansible import callbacks
from ansible import constants
from ansible import inventory
from ansible import utils
from ansible.errors import AnsibleError
from ansible.playbook import PlayBook

foo_yaml = yaml.safe_load("""
---
- name: main playbook
  hosts: all
  connection: mock
  vars:
    a: 1
    b: 2
    c: 3
  include: bar.yml foo=bar
  tasks:
    - name: test task
      debug: msg="hi there"
      when: 1 == 1
      register: result
      failed_when: result.rc != 0
      tags:
        - foo
        - bar
      notify: 
        - test_handler
    - name: test async
      debug: msg="async task"
      async: 1
      poll: 1
      tags:
        - foo
  handlers:
    - name: test_handler
      debug: msg="in test_handler"
""")

bar_yaml = yaml.safe_load("""
---
- name: included playbook
  hosts: all
  connection: mock
  vars:
  - x: x
  - y: y
  - z: z
  tasks:
  - name: test task in bar
    debug: msg="hi from bar"
    tags: bam
  - name: test async
    ping:
    async: 1
    poll: 1
""")

class TestPlayBook(unittest.TestCase):
    def setUp(self):

        def mock_yaml_load(filename, vault_password=None):
            basename = os.path.basename(filename)
            if basename == 'foo.yml':
                return foo_yaml
            elif basename == 'bar.yml':
                return bar_yaml
            else:
                raise Exception("unknown file name: %s" % filename)

        self.host_list = ['a','b','c','d','e']
        with mock.patch('ansible.utils.parse_yaml_from_file') as mock_yaml:
            mock_yaml.side_effect = mock_yaml_load

            stats = callbacks.AggregateStats()
            playbook_cb = callbacks.DefaultRunnerCallbacks() #callbacks.PlaybookCallbacks(verbose=utils.VERBOSITY)
            runner_cb = callbacks.DefaultRunnerCallbacks()   #callbacks.PlaybookRunnerCallbacks(stats, verbose=utils.VERBOSITY)

            test_inventory = inventory.Inventory(host_list=self.host_list)
            self.assertEqual(test_inventory.list_hosts(), self.host_list)

            stats._increment('dark', 'd')
            assert 'd' in stats.dark
            stats._increment('failures', 'e')
            assert 'e' in stats.failures

            self.pb = PlayBook(
                playbook         = 'foo.yml',
                callbacks        = playbook_cb,
                runner_callbacks = runner_cb,
                stats            = stats,
                module_path      = '../../library',
                inventory        = test_inventory,
            )

    def test_playbook_get_playbook_vars(self):
        existing_vars = dict(a=None)
        test_ds1 = dict(vars=dict(a=1, b=2, c=3))
        test_ds2 = dict(vars=[dict(x=7), dict(y=8), dict(z=9)])
        test_ds3 = dict()

        results = self.pb._get_playbook_vars(test_ds1, existing_vars)
        # assert that the vars were merged with the existing vars
        self.assertEqual(results, dict(a=1, b=2, c=3))
        # assert that the vars merge did not mutate the existing vars
        self.assertEqual(existing_vars, dict(a=None))

        results = self.pb._get_playbook_vars(test_ds2, existing_vars)
        self.assertEqual(results, dict(a=None, x=7, y=8, z=9))
        # assert that the vars merge did not mutate the existing vars
        self.assertEqual(existing_vars, dict(a=None))

        results = self.pb._get_playbook_vars(test_ds3, existing_vars)
        self.assertEqual(results, existing_vars)

    def test_playbook_get_playbook_vars_files(self):
        existing_vars_files = ['file1', 'file2']
        test_ds1 = dict(vars_files=['file2', 'file3'])
        test_ds2 = dict(vars_files=[])

        results = self.pb._get_playbook_vars_files(test_ds1, existing_vars_files)
        results.sort()
        self.assertEqual(results, ['file1', 'file2', 'file3'])
        self.assertEqual(existing_vars_files, ['file1', 'file2'])

        results = self.pb._get_playbook_vars_files(test_ds2, existing_vars_files)
        # FIXME: order is not preserved, fixed by PR # https://github.com/ansible/ansible/pull/7597
        results.sort()
        self.assertEqual(results, ['file1', 'file2'])
        self.assertEqual(existing_vars_files, ['file1', 'file2'])

    def test_playbook_get_include_info(self):
        existing_vars = dict(a=1, b=2)
        test_ds1 = dict(include="new_pb b=100 x={{a}}")

        new_vars, include_name = self.pb._get_include_info(test_ds1, './', existing_vars)
        self.assertEqual(include_name, "new_pb")
        self.assertEqual(new_vars, dict(a=1, b='100', x=u'1'))
        self.assertEqual(existing_vars, dict(a=1, b=2))

    def test_playbook_run(self):
        self.pb.only_tags = ['baz']
        with self.assertRaises(AnsibleError) as e:
            self.pb.run()
            self.assertEqual(str(e), "tag(s) not found in playbook: baz.  possible values: foo,bar,bam")
        self.pb.only_tags = []
        self.pb.run()

    def test_playbook_trim_unavailable_hosts(self):
        host_list = self.pb._trim_unavailable_hosts(self.host_list)
        self.assertEqual(host_list, ['a','b','c'])

    def test_playbook_async_poll(self):
        class StubRunner(object):
            vars_cache = collections.defaultdict(dict)

        class StubPoller(object):
            hosts_to_poll = ['c']
            runner = StubRunner()
            def wait(self, seconds, poll_interval):
                # leave host 'e' in the list of hosts to
                # poll to simulate an async timeout
                return dict(
                    contacted = dict(
                        a = dict(rc=0, msg="ok"),
                        b = dict(rc=0, msg="ok"),
                    ),
                    dark = dict(),
                    polled = dict(),
                )

        poller = StubPoller()
        for host in self.host_list:
            poller.runner.vars_cache[host]['ansible_job_id'] = 1

        results = self.pb._async_poll(poller, 1, 1)
        self.assertEqual(results['contacted']['a'], dict(rc=0, msg="ok"))
        self.assertEqual(results['contacted']['b'], dict(rc=0, msg="ok"))
        self.assertEqual(results['contacted']['c'], dict(failed=1, rc=None, msg="timed out"))
        
