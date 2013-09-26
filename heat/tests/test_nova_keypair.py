# vim: tabstop=4 shiftwidth=4 softtabstop=4

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


from heat.engine.resources import nova_keypair
from heat.tests.common import HeatTestCase


class NovaKeyPairTest(HeatTestCase):

    def setUp(self):
        super(NovaKeyPairTest, self).setUp()
        self.fake_nova = self.m.CreateMockAnything()
        self.fake_keypairs = self.m.CreateMockAnything()
        self.fake_stack = self.m.CreateMockAnything()
        self.fake_nova.keypairs = self.fake_keypairs

    def _get_mock_kp_for_create(self, key_name, public_key=None, priv_saved=False):
        snippet = {
            "type": "OS::Nova::KeyPair",
            "properties": {
                "name": key_name
            }
        }
        if public_key:
            snippet['properties']['public_key'] = public_key
        gen_pk = public_key or "generated test public key"
        nova_key = self.m.CreateMockAnything()
        nova_key.id = key_name
        nova_key.name = key_name
        nova_key.public_key = gen_pk
        if priv_saved:
            nova_key.private_key = "private key for %s" % key_name
        kp_res = nova_keypair.KeyPair(key_name, snippet, self.fake_stack)
        self.m.StubOutWithMock(kp_res, "nova")
        kp_res.nova().MultipleTimes().AndReturn(self.fake_nova)
        self.fake_keypairs.create(key_name, public_key=public_key).AndReturn(nova_key)
        self.fake_keypairs.list().MultipleTimes().AndReturn([nova_key])
        return kp_res, nova_key

    def test_create_key(self):
        key_name = "generate_no_save"
        tp_test, created_key = self._get_mock_kp_for_create(key_name)
        self.m.ReplayAll()
        tp_test.create()
        self.assertEqual("", tp_test.FnGetAttr('private_key'))
        self.assertEqual("generated test public key", tp_test.FnGetAttr('public_key'))
        self.assertEqual(created_key.name, tp_test.resource_id)
        self.m.VerifyAll()