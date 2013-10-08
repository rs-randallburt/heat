# vim: tabstop=4 shiftwidth=4 softtabstop=4

#
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

PYRAX_INSTALLED = True
try:
    import pyrax
except ImportError:
    PYRAX_INSTALLED = False

from oslo.config import cfg

from heat.common import exception
from heat.engine import resource
from heat.openstack.common import log as logging

logger = logging.getLogger(__name__)


class RackspaceResource(resource.Resource):
    '''
    Common base class for Rackspace Resource Providers
    '''
    properties_schema = {}

    def __init__(self, name, json_snippet, stack):
        super(RackspaceResource, self).__init__(name, json_snippet, stack)
        self.pyrax = {}

    def _get_client(self, name):
        if not self.pyrax:
            self.__authenticate()
        return self.pyrax.get(name)

    def cloud_db(self):
        '''Rackspace cloud database client.'''
        return self._get_client("database")

    def cloud_lb(self):
        '''Rackspace cloud loadbalancer client.'''
        return self._get_client("load_balancer")

    def cloud_dns(self):
        '''Rackspace cloud dns client.'''
        return self._get_client("dns")

    def nova(self):
        '''Rackspace cloudservers client.'''
        return self._get_client("compute")

    def cinder(self):
        '''Rackspace cinder client.'''
        return self._get_client("volume")

    def neutron(self):
        '''Rackspace neutron client.'''
        return self._get_client("network")

    def __authenticate(self):
        # current implemenation shown below authenticates using
        # username and password. Need make it work with auth-token
        pyrax.set_setting("identity_type", "rackspace")
        pyrax.set_setting("auth_endpoint", self.context.auth_url)
        logger.info("Authenticating with username:%s" %
                    self.context.username)
        self.pyrax = pyrax.auth_with_token(self.context.auth_token,
                                           tenant_id=self.context.tenant_id,
                                           tenant_name=self.context.tenant,
                                           region=(cfg.CONF.region_name or
                                                   None))
        if not self.pyrax:
            raise exception.AuthorizationFailure("No services available.")
        logger.info("User %s authenticated successfully."
                    % self.context.username)
