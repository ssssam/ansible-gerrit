#!/usr/bin/env python
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

'''
Common code shared between all ansible-gerrit modules.

There is quite a lot of overlap between the ansible-gerrit modules. It makes
sense to have a set of common code in a separate file, to avoid duplication.

Ansible modules need to be self-contained Python files. In order to insert the
code from this file into each of the modules, use `cat` to join the two files
together. There is a Makefile included in the repo that does this.

'''


import pygerrit.rest
import requests.auth

import json
import logging
import os
import urllib


GERRIT_COMMON_ARGUMENTS = dict(
    gerrit_url            = dict(type='str'),
    gerrit_admin_username = dict(type='str'),
    gerrit_admin_password = dict(type='str')
)


class AnsibleGerritError(Exception):
    pass


def quote(name):
    return urllib.quote(name, safe="")


def gerrit_connection(gerrit_url=None, gerrit_admin_username=None,
                      gerrit_admin_password=None, **ignored_params):

    # Gerrit supports HTTP Digest and HTTP Basic auth. Neither is amazingly
    # secure but HTTP Digest is much better than HTTP Basic. HTTP Basic auth
    # involves sending a password in cleartext. This code only supports Digest.

    if gerrit_url is None:
        gerrit_url = os.environ.get('GERRIT_URL')
    if gerrit_admin_username is None:
        gerrit_admin_username = os.environ.get('GERRIT_ADMIN_USERNAME')
    if gerrit_admin_password is None:
        gerrit_admin_password = os.environ.get('GERRIT_ADMIN_PASSWORD')

    if gerrit_admin_username and gerrit_admin_password:
        auth = requests.auth.HTTPDigestAuth(
            gerrit_admin_username, gerrit_admin_password)
    else:
        auth = None

    gerrit = pygerrit.rest.GerritRestAPI(
        url=gerrit_url, auth=auth)
    return gerrit


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


def get_boolean(gerrit, path):
    response = gerrit.get(path)
    if response == 'ok':
        value = True
    elif response == '':
        value = False
    else:
        raise AnsibleGerritError(
            "Unexpected response for %s: %s" % (path, response))
    return value


def get_list(gerrit, path):
    values = gerrit.get(path)
    return values


def get_string(gerrit, path):
    try:
        value = gerrit.get(path)
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            logging.debug("Ignoring exception %s", e)
            logging.debug("Got %s", e.response.__dict__)
            value = None
        else:
            raise
    return value


def set_boolean(gerrit, path, value):
    if value:
        gerrit.put(path)
    else:
        gerrit.delete(path)


def set_string(gerrit, path, value, field_name=None):
    field_name = field_name or os.path.basename(path)

    # Setting to '' is equivalent to deleting, so we have no need for the
    # DELETE method.
    headers = {'content-type': 'application/json'}
    data = json.dumps({field_name: value})
    gerrit.put(path, data=data, headers=headers)


def maybe_update_field(gerrit, path, field, gerrit_value, ansible_value,
                       type='str', gerrit_api_path = None):

    gerrit_api_path = gerrit_api_path or field
    fullpath = path + '/' + gerrit_api_path

    if gerrit_value == ansible_value:
        logging.info("Not updating %s: same value specified: %s", fullpath,
                     gerrit_value)
        value = gerrit_value
        changed = False
    elif ansible_value is None:
        logging.info("Not updating %s: no value specified, value stays as %s",
                     fullpath, gerrit_value)
        value = gerrit_value
        changed = False
    else:
        logging.info("Changing %s from %s to %s", fullpath, gerrit_value,
                     ansible_value)
        if type == 'str':
            set_string(gerrit, fullpath, ansible_value, field_name=field)
        elif type == 'bool':
            set_boolean(gerrit, fullpath, ansible_value)
        else:
            raise AssertionError("Unknown Ansible parameter type '%s'" % type)

        value = ansible_value
        changed = True
    return value, changed
