# Copyright (C) 2015  Codethink Limited
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.


# Prepend the contents of common.py to this file to create the final
# self-contained module.


import logging

from ansible.module_utils.basic import *


DOCUMENTATION = '''
---
module: gerrit_group
author: Sam Thursfield
short_description: Manage groups in an instance of Gerrit Code Review
'''

# https://gerrit-review.googlesource.com/Documentation/rest-api-groups.html

GROUP_ARGUMENTS = dict(
    name            = dict(type='str', required=True),

    # Passed straight to the API, can be a unique group name, or a group ID.
    owner           = dict(type='str'),

    description     = dict(type='str'),
)


def create_group(gerrit, name=None):
    # Although we could pass a GroupInput entry here to set details in one
    # go, it's left up to the update_group() function, to avoid having a
    # totally separate code path for create vs. update.
    group_info = gerrit.put('/groups/%s' % quote(name))
    return group_info


def update_group(gerrit, name=None, **params):
    change = False

    try:
        group_info = gerrit.get('/groups/%s' % quote(name))
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            logging.info("Group %s not found, creating it.", name)
            group_info = create_group(gerrit, name)
            change = True
        else:
            raise

    logging.debug(
        'Existing group info for group %s: %s', name,
        json.dumps(group_info, indent=4))

    # We use the group UUID to identify the group, which is already URL-encoded
    # for us. The 'group_id' field into the group_info data is a different,
    # deprecated numeric ID for the group that can be ignored.
    group_id = group_info['id']
    path = 'groups/%s' % group_id

    # Ansible sets the value of params that the user did not provide to None.

    if params.get('description') is not None:
        description = get_string(gerrit, path + '/description')
        description, description_changed = maybe_update_field(
            gerrit, path, 'description', description, params['description'])
        group_info['description'] = description
        change |= description_changed

    if params.get('owner') is not None:
        # This code path might break if there are two groups with the same
        # name. Gerrit doesn't enforce unique group names.
        owner_info = gerrit.get(path + '/owner')
        owner, owner_changed = maybe_update_field(
            gerrit, path, 'owner', owner_info['name'], params['owner'])
        group_info['owner'] = owner
        change |= owner_changed

    return group_info, change


def main():
    logging.basicConfig(filename='/tmp/ansible-gerrit-debug.log',
                        level=logging.DEBUG)

    argument_spec = dict()
    argument_spec.update(GROUP_ARGUMENTS)
    argument_spec.update(GERRIT_COMMON_ARGUMENTS)

    module = AnsibleModule(argument_spec)

    logging.debug('Module parameters: %s', json.dumps(module.params, indent=4))

    gerrit = gerrit_connection(**module.params)

    try:
        group_info, changed = update_group(
            gerrit, **module.params)
        module.exit_json(changed=changed, group_info=group_info)
    except (AnsibleGerritError, requests.exceptions.RequestException) as e:
        logging.error('%r', e)
        module.fail_json(msg=str(e))


main()
