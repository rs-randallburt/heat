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

'''Implementation of SQLAlchemy backend.'''
from copy import deepcopy

from datetime import datetime
from datetime import timedelta

import sqlalchemy
from sqlalchemy.orm.session import Session

from heat.openstack.common.gettextutils import _

from heat.common import crypt
from heat.common import exception
from heat.db.sqlalchemy import models
from heat.db.sqlalchemy.session import get_engine
from heat.db.sqlalchemy.session import get_session


def model_query(context, *args):
    session = _session(context)
    query = session.query(*args)

    return query


def soft_delete_aware_query(context, *args, **kwargs):
    """Stack query helper that accounts for context's `show_deleted` field.

    :param show_deleted: if present, overrides context's show_deleted field.
    """

    query = model_query(context, *args)
    show_deleted = kwargs.get('show_deleted')

    if not show_deleted:
        query = query.filter_by(deleted_at=None)

    return query


def _session(context):
    return (context and context.session) or get_session()


def raw_template_get(context, template_id):
    result = model_query(context, models.RawTemplate).get(template_id)

    if not result:
        raise exception.NotFound('raw template with id %s not found' %
                                 template_id)

    return result


def raw_template_create(context, values):
    raw_template_ref = models.RawTemplate()
    raw_template_ref.update(values)
    raw_template_ref.save(_session(context))
    return raw_template_ref


def resource_get(context, resource_id):
    result = model_query(context, models.Resource).get(resource_id)

    if not result:
        raise exception.NotFound("resource with id %s not found" % resource_id)

    return result


def resource_get_by_name_and_stack(context, resource_name, stack_id):
    result = model_query(context, models.Resource).\
        filter_by(name=resource_name).\
        filter_by(stack_id=stack_id).first()

    return result


def resource_get_by_physical_resource_id(context, physical_resource_id):
    results = (model_query(context, models.Resource)
               .filter_by(nova_instance=physical_resource_id)
               .all())

    for result in results:
        if context is None or result.stack.tenant == context.tenant_id:
            return result

    return None


def resource_get_all(context):
    results = model_query(context, models.Resource).all()

    if not results:
        raise exception.NotFound('no resources were found')

    return results


def resource_data_get(resource, key):
    """Lookup value of resource's data by key."""
    result = resource_data_get_by_key(resource.context, resource.id, key)
    return result.value


def _encrypt(value):
    return crypt.encrypt(value.encode('utf-8'))


def _decrypt(enc_value):
    value = crypt.decrypt(enc_value)
    if value is not None:
        return unicode(value, 'utf-8')

def resource_data_get_by_key(context, resource_id, key):
    result = deepcopy(model_query(context, models.ResourceData)
              .filter_by(resource_id=resource_id)
              .filter_by(key=key)
              .first())
    if not result:
        raise exception.NotFound('No resource data found')
    if result.redact and result.value:
        result.value = _decrypt(result.value)
    return result


def resource_data_set(resource, key, value, redact=False):
    """Save resource's key/value pair to database."""
    if redact:
        value = _encrypt(value)
    try:
        current = resource_data_get_by_key(resource.context, resource.id, key)
    except exception.NotFound:
        current = models.ResourceData()
        current.key = key
        current.resource_id = resource.id
    current.redact = redact
    current.value = value
    current.save()
    return current


def resource_exchange_stacks(context, resource_id1, resource_id2):
    query = model_query(context, models.Resource)
    session = query.session
    session.begin()

    res1 = query.get(resource_id1)
    res2 = query.get(resource_id2)

    res1.stack, res2.stack = res2.stack, res1.stack

    session.commit()


def resource_data_delete(resource, key):
    result = resource_data_get_by_key(resource.context, resource.id, key)
    result.delete()


def resource_create(context, values):
    resource_ref = models.Resource()
    resource_ref.update(values)
    resource_ref.save(_session(context))
    return resource_ref


def resource_get_all_by_stack(context, stack_id):
    results = model_query(context, models.Resource).\
        filter_by(stack_id=stack_id).all()

    if not results:
        raise exception.NotFound("no resources for stack_id %s were found" %
                                 stack_id)

    return results


def stack_get_by_name(context, stack_name, owner_id=None):
    query = soft_delete_aware_query(context, models.Stack).\
        filter_by(tenant=context.tenant_id).\
        filter_by(name=stack_name).\
        filter_by(owner_id=owner_id)

    return query.first()


def stack_get(context, stack_id, admin=False, show_deleted=False):
    result = model_query(context, models.Stack).get(stack_id)

    if result is None or result.deleted_at is not None and not show_deleted:
        return None

    # If the admin flag is True, we allow retrieval of a specific
    # stack without the tenant scoping
    if admin:
        return result

    if (result is not None and context is not None and
            result.tenant != context.tenant_id):
        return None

    return result


def stack_get_all(context):
    results = soft_delete_aware_query(context, models.Stack).\
        filter_by(owner_id=None).all()
    return results


def _query_stack_get_all_by_tenant(context):
    query = soft_delete_aware_query(context, models.Stack).\
        filter_by(owner_id=None).\
        filter_by(tenant=context.tenant_id)
    return query


def stack_get_all_by_tenant(context):
    return _query_stack_get_all_by_tenant(context).all()


def stack_count_all_by_tenant(context):
    return _query_stack_get_all_by_tenant(context).count()


def stack_create(context, values):
    stack_ref = models.Stack()
    stack_ref.update(values)
    stack_ref.save(_session(context))
    return stack_ref


def stack_update(context, stack_id, values):
    stack = stack_get(context, stack_id)

    if not stack:
        raise exception.NotFound('Attempt to update a stack with id: %s %s' %
                                 (stack_id, 'that does not exist'))

    old_template_id = stack.raw_template_id

    stack.update(values)
    stack.save(_session(context))


def stack_delete(context, stack_id):
    s = stack_get(context, stack_id)
    if not s:
        raise exception.NotFound('Attempt to delete a stack with id: %s %s' %
                                 (stack_id, 'that does not exist'))

    session = Session.object_session(s)

    for r in s.resources:
        session.delete(r)

    s.soft_delete(session=session)

    session.flush()


def user_creds_create(context):
    values = context.to_dict()
    user_creds_ref = models.UserCreds()
    if values.get('trust_id'):
        user_creds_ref.trust_id = _encrypt(values.get('trust_id'))
        user_creds_ref.trustor_user_id = values.get('trustor_user_id')
        user_creds_ref.username = None
        user_creds_ref.password = None
    else:
        user_creds_ref.update(values)
        user_creds_ref.password = _encrypt(values['password'])
    user_creds_ref.save(_session(context))
    return user_creds_ref


def user_creds_get(user_creds_id):
    db_result = model_query(None, models.UserCreds).get(user_creds_id)
    # Return a dict copy of db results, do not decrypt details into db_result
    # or it can be committed back to the DB in decrypted form
    result = dict(db_result)
    result['password'] = _decrypt(result['password'])
    result['trust_id'] = _decrypt(result['trust_id'])
    return result


def event_get(context, event_id):
    result = model_query(context, models.Event).get(event_id)

    return result


def event_get_all(context):
    stacks = soft_delete_aware_query(context, models.Stack)
    stack_ids = [stack.id for stack in stacks]
    results = model_query(context, models.Event).\
        filter(models.Event.stack_id.in_(stack_ids)).all()

    return results


def event_get_all_by_tenant(context):
    stacks = soft_delete_aware_query(context, models.Stack).\
        filter_by(tenant=context.tenant_id).all()
    results = []
    for stack in stacks:
        results.extend(model_query(context, models.Event).
                       filter_by(stack_id=stack.id).all())

    return results


def event_get_all_by_stack(context, stack_id):
    results = model_query(context, models.Event).\
        filter_by(stack_id=stack_id).all()

    return results


def event_create(context, values):
    event_ref = models.Event()
    event_ref.update(values)
    event_ref.save(_session(context))
    return event_ref


def watch_rule_get(context, watch_rule_id):
    result = model_query(context, models.WatchRule).get(watch_rule_id)
    return result


def watch_rule_get_by_name(context, watch_rule_name):
    result = model_query(context, models.WatchRule).\
        filter_by(name=watch_rule_name).first()
    return result


def watch_rule_get_all(context):
    results = model_query(context, models.WatchRule).all()
    return results


def watch_rule_get_all_by_stack(context, stack_id):
    results = model_query(context, models.WatchRule).\
        filter_by(stack_id=stack_id).all()
    return results


def watch_rule_create(context, values):
    obj_ref = models.WatchRule()
    obj_ref.update(values)
    obj_ref.save(_session(context))
    return obj_ref


def watch_rule_update(context, watch_id, values):
    wr = watch_rule_get(context, watch_id)

    if not wr:
        raise exception.NotFound('Attempt to update a watch with id: %s %s' %
                                 (watch_id, 'that does not exist'))

    wr.update(values)
    wr.save(_session(context))


def watch_rule_delete(context, watch_id):
    wr = watch_rule_get(context, watch_id)
    if not wr:
        raise exception.NotFound('Attempt to delete watch_rule: %s %s' %
                                 (watch_id, 'that does not exist'))

    session = Session.object_session(wr)

    for d in wr.watch_data:
        session.delete(d)

    session.delete(wr)
    session.flush()


def watch_data_create(context, values):
    obj_ref = models.WatchData()
    obj_ref.update(values)
    obj_ref.save(_session(context))
    return obj_ref


def watch_data_get_all(context):
    results = model_query(context, models.WatchData).all()
    return results


def watch_data_delete(context, watch_name):
    ds = model_query(context, models.WatchRule).\
        filter_by(name=watch_name).all()

    if not ds:
        raise exception.NotFound('Attempt to delete watch_data: %s %s' %
                                 (watch_name, 'that does not exist'))

    session = Session.object_session(ds)
    for d in ds:
        session.delete(d)
    session.flush()


def purge_deleted(age):
    if age is not None:
        try:
            age = int(age)
        except ValueError:
            raise exception.Error(_("age should be an integer"))
        if age < 0:
            raise exception.Error(_("age should be a positive integer"))
    else:
        age = 90

    time_line = datetime.now() - timedelta(days=age)
    engine = get_engine()
    meta = sqlalchemy.MetaData()
    meta.bind = engine

    stack = sqlalchemy.Table('stack', meta, autoload=True)
    event = sqlalchemy.Table('event', meta, autoload=True)
    raw_template = sqlalchemy.Table('raw_template', meta, autoload=True)
    user_creds = sqlalchemy.Table('user_creds', meta, autoload=True)

    stmt = sqlalchemy.select([stack.c.id,
                              stack.c.raw_template_id,
                              stack.c.user_creds_id]).\
        where(stack.c.deleted_at < time_line)
    deleted_stacks = engine.execute(stmt)

    for s in deleted_stacks:
        event_del = event.delete().where(event.c.stack_id == s[0])
        engine.execute(event_del)
        stack_del = stack.delete().where(stack.c.id == s[0])
        engine.execute(stack_del)
        raw_template_del = raw_template.delete().\
            where(raw_template.c.id == s[1])
        engine.execute(raw_template_del)
        user_creds_del = user_creds.delete().where(user_creds.c.id == s[2])
        engine.execute(user_creds_del)
