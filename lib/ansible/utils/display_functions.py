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

import fcntl
import logging
import os
import re
import subprocess
import sys
import tempfile
import textwrap

from ansible import constants as C
from ansible import errors
from ansible.color import stringc

__all__ = ['deprecated', 'warning', 'system_warning', 'VERBOSITY']

# the global logging verbosity
VERBOSITY=0

# list of all deprecation messages to prevent duplicate display
deprecations = {}
warns = {}

def get_logger():
    if C.DEFAULT_LOG_PATH != '':
        path = C.DEFAULT_LOG_PATH

        if (os.path.exists(path) and not os.access(path, os.W_OK)) and not os.access(os.path.dirname(path), os.W_OK):
            sys.stderr.write("log file at %s is not writeable, aborting\n" % path)
            sys.exit(1)

        logging.basicConfig(filename=path, level=logging.DEBUG, format='%(asctime)s %(name)s %(message)s')
        mypid = str(os.getpid())
        user = getpass.getuser()
        return logging.getLogger("p=%s u=%s | " % (mypid, user))
    else:
        return None

def get_cowsay_info():
    if C.ANSIBLE_NOCOWS:
        return (None, None)
    cowsay = None
    if os.path.exists("/usr/bin/cowsay"):
        cowsay = "/usr/bin/cowsay"
    elif os.path.exists("/usr/games/cowsay"):
        cowsay = "/usr/games/cowsay"
    elif os.path.exists("/usr/local/bin/cowsay"):
        # BSD path for cowsay
        cowsay = "/usr/local/bin/cowsay"
    elif os.path.exists("/opt/local/bin/cowsay"):
        # MacPorts path for cowsay
        cowsay = "/opt/local/bin/cowsay"

    noncow = os.getenv("ANSIBLE_COW_SELECTION",None)
    if cowsay and noncow == 'random':
        cmd = subprocess.Popen([cowsay, "-l"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        (out, err) = cmd.communicate()
        cows = out.split()
        cows.append(False)
        noncow = random.choice(cows)
    return (cowsay, noncow)

def log_lockfile():
    # create the path for the lockfile and open it
    tempdir = tempfile.gettempdir()
    uid = os.getuid()
    path = os.path.join(tempdir, ".ansible-lock.%s" % uid)
    lockfile = open(path, 'w')
    # use fcntl to set FD_CLOEXEC on the file descriptor,
    # so that we don't leak the file descriptor later
    lockfile_fd = lockfile.fileno()
    old_flags = fcntl.fcntl(lockfile_fd, fcntl.F_GETFD)
    fcntl.fcntl(lockfile_fd, fcntl.F_SETFD, old_flags | fcntl.FD_CLOEXEC)
    return lockfile

LOG_LOCK = log_lockfile()

def log_flock(runner):
    if runner is not None:
        try:
            fcntl.lockf(runner.output_lockfile, fcntl.LOCK_EX)
        except OSError:
            # already got closed?
            pass
    else:
        try:
            fcntl.lockf(LOG_LOCK, fcntl.LOCK_EX)
        except OSError:
            pass


def log_unflock(runner):
    if runner is not None:
        try:
            fcntl.lockf(runner.output_lockfile, fcntl.LOCK_UN)
        except OSError:
            # already got closed?
            pass
    else:
        try:
            fcntl.lockf(LOG_LOCK, fcntl.LOCK_UN)
        except OSError:
            pass

def display(msg, color=None, stderr=False, screen_only=False, log_only=False, runner=None):
    # prevent a very rare case of interlaced multiprocess I/O
    log_flock(runner)
    logger = get_logger()
    msg2 = msg
    if color:
        msg2 = stringc(msg, color)
    if not log_only:
        if not stderr:
            try:
                print msg2
            except UnicodeEncodeError:
                print msg2.encode('utf-8')
        else:
            try:
                print >>sys.stderr, msg2
            except UnicodeEncodeError:
                print >>sys.stderr, msg2.encode('utf-8')
    if logger:
        while msg.startswith("\n"):
            msg = msg.replace("\n","")
        if not screen_only:
            if color == 'red':
                logger.error(msg)
            else:
                logger.info(msg)
    log_unflock(runner)

def deprecated(msg, version, removed=False):
    ''' used to print out a deprecation message.'''

    if not removed and not C.DEPRECATION_WARNINGS:
        return

    if not removed:
        if version:
            new_msg = "\n[DEPRECATION WARNING]: %s. This feature will be removed in version %s." % (msg, version)
        else:
            new_msg = "\n[DEPRECATION WARNING]: %s. This feature will be removed in a future release." % (msg)
        new_msg = new_msg + " Deprecation warnings can be disabled by setting deprecation_warnings=False in ansible.cfg.\n\n"
    else:
        raise errors.AnsibleError("[DEPRECATED]: %s.  Please update your playbooks." % msg)

    wrapped = textwrap.wrap(new_msg, 79)
    new_msg = "\n".join(wrapped) + "\n"

    if new_msg not in deprecations:
        display(new_msg, color='purple', stderr=True)
        deprecations[new_msg] = 1

def warning(msg):
    new_msg = "\n[WARNING]: %s" % msg
    wrapped = textwrap.wrap(new_msg, 79)
    new_msg = "\n".join(wrapped) + "\n"
    if new_msg not in warns:
        display(new_msg, color='bright purple', stderr=True)
        warns[new_msg] = 1

def system_warning(msg):
    if C.SYSTEM_WARNINGS:
        warning(msg)

def sanitize_output(str):
    ''' strips private info out of a string '''

    private_keys = ['password', 'login_password']

    filter_re = [
        # filter out things like user:pass@foo/whatever
        # and http://username:pass@wherever/foo
        re.compile('^(?P<before>.*:)(?P<password>.*)(?P<after>\@.*)$'),
    ]

    parts = str.split()
    output = ''
    for part in parts:
        try:
            (k,v) = part.split('=', 1)
            if k in private_keys:
                output += " %s=VALUE_HIDDEN" % k
            else:
                found = False
                for filter in filter_re:
                    m = filter.match(v)
                    if m:
                        d = m.groupdict()
                        output += " %s=%s" % (k, d['before'] + "********" + d['after'])
                        found = True
                        break
                if not found:
                    output += " %s" % part
        except:
            output += " %s" % part

    return output.strip()

def vv(msg, host=None):
    return verbose(msg, host=host, caplevel=1)

def vvv(msg, host=None):
    return verbose(msg, host=host, caplevel=2)

def vvvv(msg, host=None):
    return verbose(msg, host=host, caplevel=3)

def verbose(msg, host=None, caplevel=2):
    msg = sanitize_output(msg)
    if VERBOSITY > caplevel:
        if host is None:
            display(msg, color='blue')
        else:
            display("<%s> %s" % (host, msg), color='blue')

def banner_cowsay(msg):
    cowsay, noncow = get_cowsay_info()
    if ": [" in msg:
        msg = msg.replace("[","")
        if msg.endswith("]"):
            msg = msg[:-1]
    runcmd = [cowsay,"-W", "60"]
    if noncow:
        runcmd.append('-f')
        runcmd.append(noncow)
    runcmd.append(msg)
    cmd = subprocess.Popen(runcmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (out, err) = cmd.communicate()
    return "%s\n" % out

def banner_normal(msg):
    width = 78 - len(msg)
    if width < 3:
        width = 3
    filler = "*" * width
    return "\n%s %s " % (msg, filler)

def banner(msg):
    cowsay, noncow = get_cowsay_info()
    if cowsay:
        try:
            return banner_cowsay(msg)
        except OSError:
            # somebody cleverly deleted cowsay or something during the PB run.  heh.
            return banner_normal(msg)
    return banner_normal(msg)

