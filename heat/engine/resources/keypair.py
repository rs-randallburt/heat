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

from heat.db.sqlalchemy import api as db_api
from heat.engine.resources.rackspace import rackspace_resource
from heat.engine.resources import nova_utils
from heat.openstack.common import log as logging

from novaclient.exceptions import NotFound

logger = logging.getLogger(__name__)

class KeyPair(rackspace_resource.RackspaceResource):
    properties_schema = {
        'key_name': {'Type': 'String',
                     'Required': True}
    }

    attributes_schema = {
        'key_name': ('Name of the created keypair.'),
        'public_key': ('The public key.'),
        'private_key': ('The private key.')
    }

    def __init__(self, name, json_snippet, stack):
        super(KeyPair, self).__init__(name, json_snippet, stack)
        self._private_key = None
        self._public_key = None

    @property
    def private_key(self):
        """Return the private SSH key for the resource."""
        if self._private_key:
            return self._private_key
        if self.id is not None:
            private_key = db_api.resource_data_get(self, 'private_key')
            if not private_key:
                return None
            self._private_key = private_key
            return private_key

    @private_key.setter
    def private_key(self, private_key):
        """Save the resource's private SSH key to the database."""
        self._private_key = private_key
        if self.id is not None:
            db_api.resource_data_set(self, 'private_key', private_key, True)

    @property
    def public_key(self):
        """Return the private SSH key for the resource."""
        if self._public_key:
            return self._public_key
        if self.id is not None:
            public_key = db_api.resource_data_get(self, 'public_key')
            if not public_key:
                return None
            self._public_key = public_key
            return public_key

    @public_key.setter
    def public_key(self, public_key):
        """Save the resource's private SSH key to the database."""
        self._public_key = public_key
        if self.id is not None:
            db_api.resource_data_set(self, 'public_key', public_key, True)

    def handle_create(self):
        if self.properties.get('private_key'):
            self.private_key = self.properties['private_key']
            self.public_key = self.properties['public_key']
        else:
            rsa = RSA.generate(1024)
            self.private_key = rsa.exportKey()
            self.public_key = rsa.publickey().exportKey('OpenSSH')

        try:
            existing = self.nova().keypairs.get(self.properties['key_name'])
            if existing.public_key == self.public_key:
                logger.info('Keypair %s already exists for tenant %s' % 
                            (self.properties['key_name'],
                            self.context.tenant))
            else:
                raise ValueError("The keypair %s already exists for tenant %s"
                                 " however the public key does not match."
                                 % (self.properties['key_name'],
                                    self.context.tenant))
        except NotFound:
            keypair = nova_utils.upload_keypair(self.nova(),
                                      self.properties['key_name'],
                                      self.public_key)
            self.resource_id_set(keypair.id)

    def validate(self):
        if hasattr(self.properties, 'private_key') or \
           hasattr(self.properties, 'public_key'):
            if hasattr(self.properties, 'private_key') and \
               hasattr(self.properties, 'public_key'):
               pass
            else:
                return {'Error': 'Both the public and private key are required'
                        ' for heat to manage a keypair.'}


    def _resolve_attribute(self, key):
        attr_fn = {'key_name': self.properties['key_name'],
                   'private_key': self.private_key,
                   'public_key': self.public_key}
        return unicode(attr_fn[key])

def resource_mapping():
    return {'OS::Nova::KeyPair': KeyPair}
