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

import copy

from heat.engine import stack_resource
from heat.common.exception import StackValidationFailed
from heat.common.exception import InvalidTemplateAttribute

from heat.openstack.common import log as logging

logger = logging.getLogger(__name__)

base_properties_schema = {
    "count": {
        "Type": "Integer",
        "Required": "True",
        "Default": 1,
        "MinValue": 1,
        "Description": _("The number of instances to create.")
    },
    "resource_def": {
        "Type": "Map",
        "Required": True,
        "Description": _("Resource definition for the resources in the group.")
    }
}

template_template = {
    "heat_template_version": "2013-05-23",
    "resources": {}
}

class ResourceGroup(stack_resource.StackResource):

    update_allowed_keys = ("Properties",)
    update_allowed_properties = ("count",)

    def __init__(self, name, json_snippet, stack):
        self.resource_class = None
        try:
            resource_type = json_snippet.get('Properties',
                                             {}).get('resource_def',
                                                     {})['type']
        except KeyError:
            raise StackValidationFailed(_("Invalid resource_def. No type defined."))
        else:
            self.resource_class = stack.env.get_class(resource_type)

        self.properties_schema = copy.deepcopy(base_properties_schema)
        res_schema = copy.deepcopy(self.resource_class.properties_schema)

        self.resource_schema = {
            "type": {
                "Type": "String",
                "Required": True
            },
            "properties": {
                "Type": "Map",
                "Schema": res_schema
            }
        }

        self.properties_schema['resource_def']['Schema'] = self.resource_schema
        attrs = self.resource_class.attributes_schema
        self.attributes_schema = copy.deepcopy(attrs)
        
        super(ResourceGroup, self).__init__(name, json_snippet, stack)

    def handle_create(self):
        count = self.properties['count']
        return self.create_with_template(self._assemble_nested(count),
                                         {},
                                         self.stack.timeout_mins)

    def handle_update(self, new_snippet, tmpl_diff, prop_diff):
        count = prop_diff.get("count")
        return self.update_with_template(self._assemble_nested(count),
                                         {},
                                         self.stack.timeout_mins)

    def handle_delete(self):
        return self.delete_nested()
    
    def FnGetAtt(self, key):
        if key.startswith("resource."):
            parts = key.split(".", 2)
            attr_name = parts[-1]
            if attr_name not in self.attributes_schema:
                raise InvalidTemplateAttribute(resource=self.name,
                                               name=key)
            try:
                res = self.nested()[parts[1]]
            except KeyError:
                raise InvalidTemplateAttribute(resource=self.name,
                                               name=key)
            else:
                return res.FnGetAtt(attr_name)
        else:
            if key not in self.attributes_schema:
                raise InvalidTemplateAttribute(resource=self.name,
                                               name=key)
            return [self.nested()[str(v)].FnGetAtt(key) for v
                    in range(self.properties['count'])]
        
    def _assemble_nested(self, count):
        child_template = copy.deepcopy(template_template)
        resource_def = self.properties['resource_def']
        resource_def['properties'] = dict((k, v)
                                          for k, v
                                          in resource_def['properties'].items()
                                          if v)
        resources = dict((str(k), resource_def)
                         for k in range(count))
        child_template['resources'] = resources
        return child_template


def resource_mapping():
    return {
        'OS::Heat::ResourceGroup': ResourceGroup,
    }
