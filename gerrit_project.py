#!/usr/bin/env python
#
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

# pygerrit.rest example:
# https://github.com/sonyxperiadev/pygerrit/blob/master/rest_example.py


import pygerrit.rest
import requests.auth

import logging
import urllib

from ansible.module_utils.basic import *


GERRIT_COMMON_ARGUMENTS = dict(
    gerrit_url      = dict(required=True),
    gerrit_username = dict(),
    gerrit_password = dict()
)


# From Gerrit ConfigInfo / ConfigInput entity (besides 'name')
# https://gerrit-review.googlesource.com/Documentation/rest-api-projects.html#config-info

PROJECT_ARGUMENTS = dict(
    name        = dict(required=True),

    description = dict(),
    #HEAD
    #owners
    #parent

    # You might expect there to be an 'absent' state, but there's actually no
    # way to delete projects out of the box with Gerrit. There is a
    # delete-project plugin that allows it.
    state       = dict(default='active',
                       choices=['active', 'hidden', 'read_only'])
)


class AnsibleGerritError(Exception):
    pass


def quote(name):
    return urllib.quote(name, safe='')


def gerrit_connection(gerrit_url=None, gerrit_username=None,
                      gerrit_password=None, **ignored_params):

    # Gerrit supports HTTP Digest and HTTP Basic auth. Neither is amazingly
    # secure but HTTP Digest is much better than HTTP Basic. HTTP Basic auth
    # involves sending a password in cleartext.

    if gerrit_username and gerrit_password:
        auth = requests.auth.HTTPDigestAuth(
            gerrit_username, gerrit_password)
    else:
        auth = None

    gerrit = pygerrit.rest.GerritRestAPI(
        url=gerrit_url, auth=auth)
    return gerrit


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


def value_from_param(field, spec, param_value):
    if 'choices' in spec:
        if param_value not in spec['choices']:
            raise ValueError(
                "'%s' is not valid for field %s" % (param_value, field))
        value = param_value.upper()
    else:
        value = param_value
    return value


def value_from_config_info(field, spec, info_value):
    if isinstance(info_value, dict):
        # This is a ConfigParameterInfo field. We need to figure out if the
        # value is TRUE, FALSE or INHERIT.
        if 'configured_value' in info_value:
            value = info_value['configured_value']
        else:
            value = 'INHERIT'
    else:
        value = info_value
    return value


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
