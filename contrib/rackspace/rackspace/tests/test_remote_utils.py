#    vim: tabstop=4 shiftwidth=4 softtabstop=4

#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import mox
import paramiko

from heat.tests.common import HeatTestCase
from ..resources import remote_utils  # noqa


class TestRemoteUtils(HeatTestCase, remote_utils.RemoteCommands):
    def setUp(self):
        remote_utils.RemoteCommands.__init__(self, 'username', 'host',
                                             'private_key')
        super(TestRemoteUtils, self).setUp()

    def _setup_connection_manager(self, closed=False):
        self.m.StubOutWithMock(self.__class__, 'sftp_connection')
        self.m.StubOutWithMock(self.sftp_connection, 'sock')
        self.m.StubOutWithMock(self.sftp_connection.sock, 'closed')
        self.sftp_connection.sock.closed = closed
        self.m.StubOutWithMock(self.sftp_connection, 'close')
        self.sftp_connection.close().AndReturn(None)

    def test_connection_manager_close_connection(self):
        self._setup_connection_manager()
        self.m.ReplayAll()

        def test(self, close_connection=True):
            pass
        remote_utils.connection_manager(test)(self, close_connection=True)
        self.m.VerifyAll()

    def test_connection_manager_close_on_error(self):
        self._setup_connection_manager()
        self.m.ReplayAll()

        def test(self, close_on_error=True):
            raise ValueError
        wrapped = remote_utils.connection_manager(test)
        self.assertRaises(ValueError, wrapped, self, close_on_error=True)
        self.m.VerifyAll()

    def _stub_execute_remote_command(self, exit_code=0, logfile=None,
                                     stdout='stdout', stderr='stderr',
                                     command='ls',
                                     close=True):
        self.m.StubOutWithMock(paramiko, "SSHClient")
        self.m.StubOutWithMock(paramiko, "MissingHostKeyPolicy")
        ssh = self.m.CreateMockAnything()
        paramiko.SSHClient().AndReturn(ssh)
        paramiko.MissingHostKeyPolicy()
        ssh.set_missing_host_key_policy(None)
        ssh.connect(self.host,
                    username=self.username,
                    key_filename=mox.IgnoreArg())

        stdout_buf = self.m.CreateMockAnything()
        stderr_buf = self.m.CreateMockAnything()
        ssh.exec_command(command).AndReturn(('x', stdout_buf, stderr_buf))

        stdout_buf.channel = self.m.CreateMockAnything()
        stdout_buf.channel.recv_exit_status().AndReturn(exit_code)
        stdout_buf.read().AndReturn(stdout)
        stderr_buf.read().AndReturn(stderr)
        if close:
            ssh.close()
        return ssh

    def test_execute_remote_command_pass(self):
        self._stub_execute_remote_command()
        self.m.ReplayAll()
        (stdout, stderr) = remote_utils._execute_remote_command(self, 'ls')
        self.m.VerifyAll()
        self.assertEqual(stdout, 'stdout')
        self.assertEqual(stderr, 'stderr')

    def test_execute_remote_command_fail_no_log(self):
        self._stub_execute_remote_command(exit_code=1)
        self.m.ReplayAll()
        self.assertRaises(remote_utils.RemoteCommandException,
                          remote_utils._execute_remote_command,
                          self, 'ls')
        self.m.VerifyAll()

    def test_execute_remote_command_fail_with_log(self):
        ssh = self._stub_execute_remote_command(exit_code=1, logfile='log',
                                                close=False)
        self.m.StubOutWithMock(self, 'read_remote_file')
        self.read_remote_file('log')
        ssh.close()
        self.m.ReplayAll()
        self.assertRaises(remote_utils.RemoteCommandException,
                          remote_utils._execute_remote_command,
                          self, 'ls', logfile='log')
        self.m.VerifyAll()

    def _stub_remote_execute(self, path='/tmp', script='script'):
        def test_fn(self, *args, **kwargs):
            return dict(**kwargs)

        name = test_fn.__name__

        wrap = ("#!/bin/bash -x\n"
                "cd %(path)s\n"
                "%(script)s"
                % dict(path=path,
                       script=script))

        self.m.StubOutWithMock(self, 'write_remote_file')
        self.write_remote_file(path, name, mox.IgnoreArg(),
                               mode=mox.IgnoreArg()).AndReturn(path)
        self.m.StubOutWithMock(remote_utils, '_execute_remote_command')
        if kwargs.get('save', True):
            remote_utils._execute_remote_command(self, )
        else:
            remote_utils._execute_remote_command(self, wrap, logfile=None)

        self.m.ReplayAll()
        remote_utils.remote_execute(test_fn)(self, script=script, path=path)
