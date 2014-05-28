# -*- coding: utf-8 -*-

import mock
import tempfile
import unittest

from ansible import callbacks
from ansible import utils

class StubCallback(object):
    def __init__(self):
        self.play = None
        self.task = None

class StubPlay:
    pass

class StubTask:
    pass

class TestCallbacks(unittest.TestCase):
    def test_callback_plugins_loader(self):
        callbacks.load_callback_plugins()
        print "callback_plugins are %s" % (callbacks.callback_plugins,)
        print "callback plugins from utils are %s" % (callbacks.callback_plugins,)
        assert len(callbacks.callback_plugins) == len([x for x in utils.plugins.callback_loader.all()])

    def test_set_play(self):
        stub_callback = StubCallback()
        stub_play = StubPlay()

        callbacks.set_play(stub_callback, stub_play)
        assert stub_callback.play == stub_play
        for plugin in callbacks.callback_plugins:
            assert plugin.play == stub_play

    def test_set_task(self):
        stub_callback = StubCallback()
        stub_task = StubTask()

        callbacks.set_task(stub_callback, stub_task)
        assert stub_callback.task == stub_task
        for plugin in callbacks.callback_plugins:
            assert plugin.task == stub_task

