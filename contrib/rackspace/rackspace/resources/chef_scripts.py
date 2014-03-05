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

from Crypto.PublicKey import RSA
import os
import subprocess
import tarfile
import uuid

from .remote_utils import connection_manager  # noqa
from .remote_utils import remote_execute  # noqa
from .remote_utils import RemoteCommands  # noqa


class ChefScripts(RemoteCommands):
    def create_tar(self, output_path, contents, compression="gz"):
        assert isinstance(contents, list)

        name = (str(uuid.uuid4())
                + ".tar"
                + "." + compression)
        compressed = os.path.join(output_path, name)

        with tarfile.open(compressed, "w:%s" % compression) as tar:
            for item in contents:
                tar.add(item)

        return (compressed, name)

    def execute_command(self, path, command):
        cmd = ("set -e\n"
               "cd %(path)s\n"
               "%(command)s" % dict(path=path, command=command))
        return subprocess.check_output(cmd,
                                       shell=True,
                                       stderr=subprocess.STDOUT,
                                       executable="/bin/bash")

    @connection_manager
    def create_secrets_file(self, path, name):
        key = RSA.generate(2048)
        self.secret_key = key.exportKey('PEM')
        return self.write_remote_file(path, name, self.secret_key)

    @remote_execute
    def encrypt_data_bag(self, databag, item_path, config_path,
                         databag_secret_path, path=None):
        outputs = dict(databag=databag,
                       path=item_path,
                       config=config_path,
                       encrypt=databag_secret_path)
        return dict(script="knife data bag from file %(databag)s %(path)s -c "
                           "%(config)s --secret-file %(encrypt)s -z" % outputs)

    @connection_manager
    def write_data_bags(self, path, data_bags, config):
        databag_dir = self.create_remote_folder(path, name='data_bags',
                                                )
        for data_bag, item in data_bags.iteritems():
            databag_path = self.create_remote_folder(databag_dir,
                                                     name=data_bag,
                                                     )
            #write databags
            item_name = item['id'] + ".json"
            if 'encrypted' in item:
                del item['encrypted']
                item_path = os.path.join(databag_path, item_name)
                self.write_remote_json(databag_path,
                                       item_name,
                                       item,
                                       )
                self.encrypt_data_bag(data_bag,
                                      item_path,
                                      config['knife_path'],
                                      config['encrypted_data_bag_secret'],
                                      path=config['kitchen_path'])
            else:
                self.write_remote_json(databag_path, item_name, item)
        return databag_dir

    @remote_execute
    def bootstrap(self, path=None):
        outputs = dict(output=os.path.join(path, 'install.sh'),
                       url="https://www.opscode.com/chef/install.sh")

        return dict(script="wget -O %(output)s %(url)s\n"
                           "bash %(output)s"
                           % outputs)

    def get_knife_command(self, knife_path, node_file, command):
        return "knife %s -c %s -z -j %s" % (command,
                                            knife_path,
                                            node_file)

    @remote_execute
    def run_chef(self, knife_config_path, node_file, path=None):
        return dict(script="chef-solo -c %s -j %s"
                    % (knife_config_path, node_file))

    def _installer(self, installer_type, install_prefix):
        installer = ('berks' if installer_type is 'Berksfile'
                     else 'librarian-chef')
        if install_prefix:
            return "%s %s" % (install_prefix, installer)
        return installer

    def create_engine_kitchen(self, file_cache, node_name, cookbook_dir_name,
                              installer_type, installer_file,
                              install_prefix=None):
        node_path = os.path.join(file_cache, node_name)
        cookbook_path = os.path.join(node_path, cookbook_dir_name)
        if os.path.exists(cookbook_path):
            return

        if not os.path.exists(file_cache):
            os.mkdir(file_cache)
        os.mkdir(node_path)
        os.mkdir(cookbook_path)

        with open(os.path.join(node_path, installer_type), 'w') as i_file:
            i_file.write(installer_file)

        installer = self._installer(installer_type, install_prefix) 
        command = "%s install --path %s" % (installer, cookbook_path)
        self.execute_command(node_path, command)
        return cookbook_path

    @remote_execute
    def copy_cookbooks_to_remote(self, cookbook_path, kitchen_path, path=None):
        compressed_cookbooks, name = self.create_tar(kitchen_path,
                                                     [cookbook_path])
        remote_file = os.path.join(path, name)
        self.scp_file(compressed_cookbooks, remote_file)
        return dict(script=("tar -xzf %(remote_file)s\n"
                            "rm %(remote_file)s"
                            % dict(remote_file=remote_file)))
