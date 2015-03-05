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
module: gerrit_project
author: Sam Thursfield
short_description: Manage projects in an instance of Gerrit Code Review
'''


EXAMPLES = '''
- gerrit_project:
    name: Morph
    description: Baserock build tool
    state: active
    gerrit_url: http://gerrit.example.com:8080/
    gerrit_admin_username: dicky
    gerrit_admin_password: b0sst0nes
'''


# https://gerrit-review.googlesource.com/Documentation/rest-api-projects.html


PROJECT_ARGUMENTS = dict(
    name        = dict(required=True),

    description = dict(),

    # You might expect there to be an 'absent' state, but there's actually no
    # way to delete projects out of the box with Gerrit. There is a
    # delete-project plugin that allows it.
    state       = dict(default='active',
                       choices=['active', 'hidden', 'read_only'])
)


def create_project(gerrit, name=None):
    # It's possible to pass a ProjectInput structure to configure the
    # project now, but to reduce the amount of code here we leave it to the
    # update_project() function.
    project_info = gerrit.put('/projects/%s' % quote(name))
    project_config_info = gerrit.get('/projects/%s/config' % quote(name))
    return project_config_info


def remove_project(gerrit, name=None):
    try:
        project_info = gerrit.get('/projects/%s' % quote(name))
        raise AnsibleGerritError(
            "Cannot remove project %s: deleting projects is not supported by "
            "Gerrit. (Although you could use the delete-projects plugin, if "
            "you really want to get rid of it)." % name)
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            logging.info("Project %s not found.", name)
            changed = False
        else:
            raise e

    return changed


def update_project(gerrit, name=None, **params):
    change = False

    try:
        config_info = gerrit.get('/projects/%s/config' % quote(name))
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            logging.info("Project %s not found, creating it.", name)
            config_info = create_project(gerrit, name)
            change = True
        else:
            raise

    logging.debug(
        'Existing config info for project %s: %s', name,
        json.dumps(config_info, indent=4))

    # We provide a value for all fields of the ConfigInput structure. Most of
    # them are optional and will be unchanged if we don't provide a value, but
    # 'description' needs a value or the project's description will be removed.
    # To err on the side of safety, we provide values for all the fields we
    # can.
    config_input = {}

    # This is going to be ugly, needs to be split up into functions.
    for field, spec in PROJECT_ARGUMENTS.iteritems():
        if field != 'name':

            if params.get(field) is None:
                # User didn't specify a value.
                if field in config_info:
                    # Keep the current value.
                    current_value = value_from_config_info(
                        field, spec, config_info[field])
                    config_input[field] = current_value
                else:
                    logging.warning(
                        "Ignoring field %s that is missing from config_info",
                        field)
            else:
                # User specified a new value.
                if field in config_info:
                    old_value = value_from_config_info(
                        field, spec, config_info[field])
                else:
                    old_value = None

                new_value = value_from_param(
                    field, spec, params[field])

                if old_value != new_value:
                    change = True

                if new_value is not None:
                    config_info[field] = new_value
                    config_input[field] = new_value

    if change:
        logging.debug(
            'Config input for project %s: %s', name,
            json.dumps(config_input, indent=4))
        headers = {'content-type': 'application/json'}
        gerrit.put('/projects/%s/config' % quote(name), data=json.dumps(config_input),
                   headers=headers)

    return config_info, change


def main():
    logging.basicConfig(filename='/tmp/ansible-gerrit-debug.log',
                        level=logging.DEBUG)

    argument_spec = dict()
    argument_spec.update(PROJECT_ARGUMENTS)
    argument_spec.update(GERRIT_COMMON_ARGUMENTS)

    module = AnsibleModule(argument_spec)

    logging.debug('Module parameters: %s', json.dumps(module.params, indent=4))

    gerrit = gerrit_connection(**module.params)

    try:
        if module.params['state'] == 'absent':
            changed = remove_project(gerrit, **module.params)
            module.exit_json(changed=changed)
        else:
            project_config_info, changed = update_project(
                gerrit, **module.params)
            module.exit_json(changed=changed,
                             project_config_info=project_config_info)
    except (AnsibleGerritError, requests.exceptions.RequestException) as e:
        logging.error('%r', e)
        module.fail_json(msg=str(e))


main()
