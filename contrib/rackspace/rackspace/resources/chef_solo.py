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

import os
from oslo.config import cfg
import uuid

from heat.engine import resource
from heat.engine import scheduler
from heat.openstack.common import log as logging
from heat.openstack.common.gettextutils import _

from .chef_scripts import ChefScripts  # noqa

logger = logging.getLogger(__name__)

chef_ops = [
    cfg.StrOpt('chef_solo_path',
               default="/tmp/heat_chef",
               help=_('Path to cache chef solo kitchens.')),
    cfg.StrOpt('chef_installer_prefix', default="bundle exec",
               help=_('Command to prefix berks/librarian.'))
]
cfg.CONF.register_opts(chef_ops)


class ChefSolo(resource.Resource, ChefScripts):
    properties_schema = {
        #TODO(andrew-plunk): custom valiation only berks or chef not both
        'Berksfile': {'Type': 'String'},
        'Cheffile': {'Type': 'String'},
        'username': {'Type': 'String',
                             'Default': 'root',
                             'Required': True},
        'host': {'Type': 'String',
                 'Required': True},
        'private_key': {'Type': 'String',
                        'Required': True},
        'data_bags': {'Type': 'Map'},
        'node': {'Type': 'Map'},
        'roles': {'Type': 'Map'},
        'users': {'Type': 'Map'},
        'environments': {'Type': 'Map'},
        'clients': {'Type': 'Map'}
    }

    def __init__(self, name, json_snippet, stack):
        resource.Resource.__init__(self, name, json_snippet, stack)

    def create_kitchen(self, kitchen_path, properties):
        config = {}
        #write encrypted data bag secret if we have any encrypted data_bags
        if properties.get('data_bags') is not None:
            for data_bag, item in properties['data_bags'].iteritems():
                if 'encrypted' in item:
                    logger.debug('ENCRYPTING')
                    secrets_path = self.create_remote_folder(kitchen_path,
                                                             name=
                                                             'certificates')
                    config['encrypted_data_bag_secret'] = (
                        self.create_secrets_file(secrets_path,
                                                 'secrets.pem'))
                    break

        #TODO(andrew-plunk) replicate pattern of roles for others
        #(environments) and make generic
        if properties.get('roles') is not None:
            #write roles
            roles_path = self.create_remote_folder(kitchen_path, name='roles')
            for role, contents in properties['roles'].iteritems():
                self.write_remote_json(roles_path, role, contents)

        #TODO(andrew-plunk) only for chef zero
        if properties.get('users') is not None:
            #write users
            users_path = self.create_remote_folder(kitchen_path, name='users')
            for user, contents in properties['users'].iteritems():
                self.write_remote_json(users_path, user, contents)

        #TODO(andrew-plunk) only for chef zero
        if properties.get('clients') is not None:
            #write clients
            clients_path = self.create_remote_folder(kitchen_path,
                                                     name='clients')
            self.write_remote_json(clients_path,
                                   properties['clients'])

        if properties.get('environments') is not None:
            #write environments
            environments_path = self.create_remote_folder(kitchen_path,
                                                          name='environments')
            self.write_remote_json(environments_path,
                                   properties['environments'])

        if properties.get('Berksfile') or properties.get('Cheffile'):
            #create cookbook directory
            config['cookbooks'] = self.create_remote_folder(kitchen_path,
                                                            name='cookbooks')

            #write Berksfile
            if properties.get('Berksfile'):
                config['installer_content'] = properties.get('Berksfile')
                self.write_remote_file(
                    kitchen_path, 'Berksfile', properties.get('Berksfile'))

            #write Cheffile
            if properties.get('Cheffile'):
                config['installer_content'] = properties.get('Cheffile')
                self.write_remote_file(
                    kitchen_path, 'Cheffile', properties.get('Cheffile'))

        return config

    def handle_create(self):
        ChefScripts.__init__(self,
                             username=self.properties['username'],
                             host=self.properties['host'],
                             private_key=self.properties['private_key'])

        self.future_id = str(uuid.uuid4())
        remote_path = cfg.CONF.chef_solo_path
        self.create_remote_folder(remote_path)

        kitchen_path = self.create_remote_folder(remote_path,
                                                 name=self.future_id)
        #create kitchen
        config = self.create_kitchen(kitchen_path, self.properties)
        config['kitchen_path'] = kitchen_path
        #create knife.rb
        config['knife_path'] = os.path.join(kitchen_path, 'knife.rb')
        with self.sftp_connection.open(config['knife_path'], 'w') as knife_rb:
            log_path = os.path.join(kitchen_path, 'chef.log')
            knife_rb_str = ('log_level :info\n'
                            'log_location "%s"\n'
                            'verbose_logging true\n'
                            'ssl_verify_mode :verify_none\n'
                            'file_cache_path "%s"\n'
                            'data_bag_path "%s"\n'
                            'cookbook_path "%s"\n'
                            'environments_path "%s"\n'
                            'role_path "%s"\n'
                            % (log_path,
                               remote_path,
                               os.path.join(kitchen_path, 'data_bags'),
                               os.path.join(kitchen_path, 'cookbooks'),
                               os.path.join(kitchen_path, 'environments'),
                               os.path.join(kitchen_path, 'roles')))
            if 'encrypted_data_bag_secret' in config:
                knife_rb_str += 'encrypted_data_bag_secret "%s"\n' % (
                    config['encrypted_data_bag_secret'])
            knife_rb.write(knife_rb_str)
        self.resource_id_set(self.future_id)

        def _dependent_tasks():
            install_type = ('Berksfile' if 'Berksfile' in self.properties
                            else 'Cheffile')
            self.bootstrap(path=kitchen_path)
            yield
            cookbook_path = (
                self.create_engine_kitchen(cfg.CONF.chef_solo_path,
                                           self.resource_id,
                                           'cookbooks',
                                           install_type,
                                           config['installer_content'],
                                           install_prefix=
                                           cfg.CONF.chef_installer_prefix))
            yield
            self.copy_cookbooks_to_remote(cookbook_path,
                                          config['kitchen_path'],
                                          path="/")
            yield
            if self.properties.get('data_bags'):
                #write data bags
                config['data_bags'] = (
                    self.write_data_bags(kitchen_path,
                                         self.properties['data_bags'],
                                         config))
            yield
            node_folder = self.create_remote_folder(kitchen_path,
                                                    name="nodes")
            node_file_name = self.properties['host'] + ".json"
            yield
            #actual chef run
            config['node_path'] = (
                self.write_remote_json(node_folder,
                                       node_file_name,
                                       self.properties['node']))
            self.run_chef(config['knife_path'], config['node_path'],
                          path=kitchen_path)

        return scheduler.TaskRunner(_dependent_tasks)

    def check_create_complete(self, tasks):
        if not tasks.started():
            tasks.start()
            return tasks.done()
        return tasks.step()


def resource_mapping():
    return {
        'OS::Heat::ChefSolo': ChefSolo
    }
