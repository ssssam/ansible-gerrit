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


EXAMPLES = '''
- gerrit_group:
    name: Submitters
    description: Users that can submit patches
    owner: Administrators
    included_groups:
        - Registered Users
    gerrit_url: http://gerrit.example.com:8080/
    gerrit_admin_username: dicky
    gerrit_admin_password: b0sst0nes

- gerrit_group:
    name: Testers
    description: Accounts that can give +1/-1 Verified
    owner: Administrators
'''


# https://gerrit-review.googlesource.com/Documentation/rest-api-groups.html


GROUP_ARGUMENTS = dict(
    name            = dict(type='str', required=True),

    description     = dict(type='str'),

    # Groups that are included as members in this group
    included_groups = dict(type='list'),

    # Passed straight to the API, can be a unique group name, or a group ID.
    owner           = dict(type='str'),
)


def create_group(gerrit, name=None):
    # Although we could pass a GroupInput entry here to set details in one
    # go, it's left up to the update_group() function, to avoid having a
    # totally separate code path for create vs. update.
    group_info = gerrit.put('/groups/%s' % quote(name))
    return group_info


def create_group_inclusion(gerrit, group_id, include_group_id):
    logging.info('Creating membership of %s in group %s', include_group_id,
                 group_id)
    path = 'groups/%s/groups/%s' % (quote(group_id), quote(include_group_id))
    gerrit.put(path)


def ensure_group_includes_only(gerrit, group_id, ansible_included_groups):
    path = 'groups/%s' % group_id
    included_group_info_list = get_list(gerrit, path + '/groups')

    changed = False
    gerrit_included_groups = []
    for included_group_info in included_group_info_list:
        if included_group_info['name'] in ansible_included_groups:
            logging.info("Preserving %s membership of %s", included_group_info,
                         path)
            gerrit_included_groups.append(included_group_info['name'])
        else:
            logging.info("Removing %s from %s", included_group_info, path)
            membership_path = 'groups/%s/groups/%s' % (
                quote(group_id), quote(included_group_info['id']))
            gerrit.delete(membership_path)
            changed = True

    # If the user gave group IDs instead of group names, this will
    # needlessly recreate the membership. The only actual issue will be that
    # Ansible reports 'changed' when nothing really did change, I think.
    #
    # We might receive [""] when the user tries to pass in an empty list, so
    # handle that.
    to_add = set(ansible_included_groups).difference(gerrit_included_groups)
    for include_group in to_add:
        if len(include_group) > 0:
            create_group_inclusion(gerrit, group_id, include_group)
            gerrit_included_groups.append(include_group)
            changed = True

    return gerrit_included_groups, changed


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

    output = {}
    output['group_id'] = group_id

    # Ansible sets the value of params that the user did not provide to None.

    if params.get('description') is not None:
        description = get_string(gerrit, path + '/description')
        description, description_changed = maybe_update_field(
            gerrit, path, 'description', description, params['description'])
        group_info['description'] = description
        change |= description_changed

    if params.get('included_groups') is not None:
        included_groups, included_groups_changed = ensure_group_includes_only(
            gerrit, group_id, params['included_groups'])
        output['included_groups'] = included_groups
        change |= included_groups_changed

    if params.get('owner') is not None:
        # This code path might break if there are two groups with the same
        # name. Gerrit doesn't enforce unique group names.
        owner_info = gerrit.get(path + '/owner')
        owner, owner_changed = maybe_update_field(
            gerrit, path, 'owner', owner_info['name'], params['owner'])
        group_info['owner'] = owner
        change |= owner_changed

    output['group_info'] = group_info

    return output, change


def main():
    logging.basicConfig(filename='/tmp/ansible-gerrit-debug.log',
                        level=logging.DEBUG)

    argument_spec = dict()
    argument_spec.update(GROUP_ARGUMENTS)
    argument_spec.update(GERRIT_COMMON_ARGUMENTS)

    module = AnsibleModule(argument_spec)

    logging.debug('Module parameters: %s', json.dumps(module.params, indent=4))

    try:
        gerrit = gerrit_connection(**module.params)

        output, changed = update_group(
            gerrit, **module.params)
        module.exit_json(changed=changed, **output)
    except (AnsibleGerritError, requests.exceptions.RequestException) as e:
        logging.error('%r', e)
        module.fail_json(msg=str(e))


main()
