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

"""Database setup and migration commands."""

from heat.openstack.common.db import api as db_api


INIT_VERSION = 14
_BACKEND_MAPPING = {'sqlalchemy': 'heat.db.sqlalchemy.migration'}

IMPL = db_api.DBAPI(backend_mapping=_BACKEND_MAPPING)


def db_sync(version=None):
    """Migrate the database to `version` or the most recent version."""
    return IMPL.db_sync(version=version)


def db_version():
    """Display the current database version."""
    return IMPL.db_version()
