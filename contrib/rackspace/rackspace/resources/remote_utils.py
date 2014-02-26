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

from oslo.config import cfg
from functools import wraps
import json
import paramiko
import tempfile
import os

from heat.common import exception
from heat.openstack.common import log as logging

logger = logging.getLogger(__name__)


cloud_opts = [
    cfg.StrOpt('debug_remote_connection',
               default=None,
               help=_('Write the ip and private_key of the server we are '
                      'connecting to, to the specified directory.'))
]
cfg.CONF.register_opts(cloud_opts)


def connection_manager(function):
    """This decorator handles cleaning up sftp connections.
    :kwarg close_connection: True if you would like to close the connection
        after the function is called. Default False
    :kwarg close_on_error: Close the connection if there was an error. Default
        True.
    :kwarg retry: True if the function should be retried when a connection
        error happens. Default False.
    """
    @wraps(function)
    def wrapper(remote, *args, **kwargs):
            assert isinstance(remote, RemoteCommands)

            close_connection = kwargs.get('close_connection', False)
            close_on_error = kwargs.get('close_on_error', True)
            try:
                return function(remote, *args, **kwargs)
            except (EOFError, paramiko.SSHException):
                if kwargs.get('retry', False) is True:
                    remote.reconnect_sftp()
                    return function(remote, *args, **kwargs)
                else:
                    raise
            except Exception as e:
                if (not remote.sftp_connection.sock.closed) and close_on_error:
                    remote.sftp_connection.close()
                raise e
            finally:
                if close_connection:
                    if not remote.sftp_connection.sock.closed:
                        remote.sftp_connection.close()
    return wrapper


class RemoteCommandException(exception.HeatException):
    def __init__(self, **kwargs):
        self.msg_fmt = _("Host:%(host)s\n"
                         "Output:\n%(output)s\n"
                         "Command:%(command)s\n"
                         "Exit Code:%(exit_code)s\n"
                         "Remote Log:%(remote_log)s")
        super(RemoteCommandException, self).__init__(**kwargs)


class RemoteCommands(object):
    """Must call connection_info(username, host, private_key)."""

    def __init__(self, username, host, private_key):
        self.private_key = private_key
        self.username = username
        self.host = host
        self._sftp_connection = None

        debug_dir = cfg.CONF.debug_remote_connection
        if debug_dir is not None:
            key_path = os.path.join(debug_dir, "%s_private_key" % self.host)
            with open(key_path, 'w', 0o600) as keyfile:
                keyfile.write(self.private_key)

            host_path = os.path.join(debug_dir, "%s_host" % self.host)
            with open(host_path, 'w') as hostfile:
                hostfile.write(self.host)

    def get_sftp_connection(self, username, host, private_key):
        with tempfile.NamedTemporaryFile() as private_key_file:
            private_key_file.write(private_key)
            private_key_file.seek(0)
            pkey = paramiko.RSAKey.from_private_key_file(
                private_key_file.name)
            transport = paramiko.Transport((host, 22))
            transport.connect(hostkey=None, username=username, pkey=pkey)
            return paramiko.SFTPClient.from_transport(transport)

    @property
    def sftp_connection(self):
        if self._sftp_connection is None or self._sftp_connection.sock.closed:
            self._sftp_connection = self.get_sftp_connection(self.username,
                                                             self.host,
                                                             self.private_key)
        return self._sftp_connection

    def reconnect_sftp(self):
        if not self._sftp_connection.sock.closed:
            self._sftp_connection.close()
        self._sftp_connection = self.get_sftp_connection(self.username,
                                                         self.host,
                                                         self.private_key)

    @connection_manager
    def scp_recursive(self, local_path, remote_path, retry=True):
        new_path = os.path.join(remote_path, local_path)
        if not (local_path.endswith(".") or local_path.endswith("..")):
            if os.path.isfile(local_path):
                logger.debug("creating remote file %s" % new_path)
                self.sftp_connection.put(local_path, new_path)
            elif os.path.isdir(local_path):
                logger.debug("creating remote folder %s" % new_path)
                self.create_remote_folder(new_path)
                for x in os.listdir(local_path):
                    new_local_path = os.path.join(local_path, x)
                    self.scp_recursive(new_local_path, new_path, retry=retry)

    @connection_manager
    def scp_file(self, local_path, remote_path, retry=True, byte_size=10000):
        #TODO(andrew-plunk) the max byte size should be able to be 32768,
        #but I cannont get this to work without throwing EOF errors
        with open(local_path, "rb") as f:
            byte = f.read(byte_size)
            with self.sftp_connection.open(remote_path, 'wb') as remote_file:
                while byte != "":
                    remote_file.write(byte)
                    byte = f.read(byte_size)

    @connection_manager
    def create_remote_folder(self, path, name=None):
        if name:
            folder = os.path.join(path, name)
        else:
            folder = path

        try:
            self.sftp_connection.mkdir(folder)
        except IOError as ioe:
            if ioe.errno == 13:
                logger.warn(_("Permission denied to create %(folder)s on "
                              "%(remote)s") % dict(folder=folder,
                                                   remote=self.host))
                raise ioe
            #TODO(andrew-plunk) add error checking here, we probably want
            #to raise an exception or something
            logger.warn(_("There was an error creating the remote folder "
                          "%(folder)s. The remote folder probably already "
                          "exists.") % dict(folder=folder))
        return folder

    @connection_manager
    def read_remote_file(self, path):
        with self.sftp_connection.open(path, 'r') as remote_file:
            return [x for x in remote_file]

    @connection_manager
    def write_remote_file(self, path, name, data, mode=None):
        remote_file = os.path.join(path, name)
        sftp_file = None
        try:
            sftp_file = self.sftp_connection.open(remote_file, 'w')
            sftp_file.write(data)
            if mode is not None:
                self.sftp_connection.chmod(remote_file, mode)
        finally:
            if sftp_file is not None:
                sftp_file.close()
        return remote_file

    @connection_manager
    def write_remote_json(self, path, name, data):
        return self.write_remote_file(path, name, json.dumps(data))


def remote_execute(function):
    """
    kwargs (The decorated function should accept):
        :kwarg connection: The sftp connection to re-use
        :kwarg path: The path to execute the remote command in.
        :kwarg logfile: The file contents to return in the event of an error.

        ex: function(self, connection=None, path=None)

    returns (The function should return):
        :returns dict:
            :key script: [String] The commands to execute.
            :key save: [Boolean] True if the script should be saved on the
                remote server.
            :key path: Path on the remote server to write the script to (this
                enables logging). False otherwise. Defaults to True.

        ex: return dict(script="ls -al", save=True)
    """
    @wraps(function)
    def wrapper(remote, *args, **kwargs):
        results = function(remote, *args, **kwargs)
        name = function.__name__
        save = results.get('save', True)
        script = results.get('script')

        logfile = kwargs.get('logfile')
        path = kwargs.get('path')

        assert script is not None, (_("The script function %(name)s must "
                                      "return a script's contents to execute.")
                                    % {"name": name})
        assert isinstance(remote, RemoteCommands)

        logger.debug(_("Executing remote script %(name)s.") % {'name': name})
        wrap = ("#!/bin/bash -x\n"
                "cd %(path)s\n"
                "%(script)s"
                % dict(path=path,
                       script=script))

        if save:
            script_path = remote.write_remote_file(path, name, wrap,
                                                   mode=0o655)
            if logfile is None:
                logfile = os.path.join(path, name + ".log")
            command = "%s > %s 2>&1" % (script_path, logfile)
            return _execute_remote_command(remote, command, logfile=logfile)
        else:
            return _execute_remote_command(remote, wrap, logfile=logfile)
    return wrapper


def _execute_remote_command(remote, command, logfile=None):
    """Executes a remote command over ssh without blocking."""
    with tempfile.NamedTemporaryFile() as private_key_file:
        private_key_file.write(remote.private_key)
        private_key_file.seek(0)
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(
                paramiko.MissingHostKeyPolicy())
            ssh.connect(remote.host,
                        username=remote.username,
                        key_filename=private_key_file.name)

            logger.debug("Executing command:%s" % command)
            x, stdout_buf, stderr_buf = ssh.exec_command(command)

            exit_code = stdout_buf.channel.recv_exit_status()
            stdout, stderr = (stdout_buf.read(), stderr_buf.read())
            if exit_code != 0:
                if logfile is not None:
                    logger.debug("Reading remote log:%s" % logfile)
                    output = remote.read_remote_file(logfile)
                else:
                    output = stderr
                raise RemoteCommandException(command=command,
                                             exit_code=exit_code,
                                             remote_log=logfile,
                                             output=output,
                                             host=remote.host)
            else:
                return(stdout, stderr)
        finally:
            if ssh:
                ssh.close()
