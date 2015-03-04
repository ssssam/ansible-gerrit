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
module: gerrit_account
author: Sam Thursfield
short_description: Manage accounts in an instance of Gerrit Code Review
'''

# From Gerrit AccountInfo / AccountInput entity
# https://gerrit-review.googlesource.com/Documentation/rest-api-accounts.html#account-info

ACCOUNT_ARGUMENTS = dict(
    username        = dict(type='str', required=True),

    # This is called 'name' in the Gerrit API, but that word implies 'unique
    # identifier' in Ansible which is not true of a person's name. Hopefully
    # calling it 'fullname' will prevent confusion.
    fullname        = dict(type='str'),

    # Sets the 'primary' email. Any other email address the account has will be
    # removed. The 'no_confirmation' setting will be used, so you don't have to
    # authorize the email account.
    email           = dict(type='str'),

    # This will remove any SSH keys that aren't what the user specified. As
    # with emails, this is probably annoying in some situations (sorry if it
    # annoyed you), but Ansible modules should *ensure* the system is in the
    # specified state. Right now the module only lets you specify one SSH key,
    # so it should *ensure* that there is only that key.
    ssh_key         = dict(type='str'),

    http_password   = dict(type='str'),
    groups          = dict(type='list'),

    active          = dict(type='bool', choices=BOOLEANS)
)


def create_account(gerrit, username=None):
    # Although we could pass an AccountInput entry here to set details in one
    # go, it's left up to the update_account() function, to avoid having a
    # totally separate code path for create vs. update.
    account_info = gerrit.put('/accounts/%s' % quote(username))
    return account_info


def create_account_email(gerrit, account_id, email, preferred=False,
                         no_confirmation=False):
    logging.info('Creating email %s for account %s', email, account_id)

    email_input = {
        # Setting 'email' is optional (it's already in the URL) but it's good
        # to double check that the email is encoded in the URL properly.
        'email': email,
        'preferred': preferred,
        'no_confirmation': no_confirmation,
    }
    logging.debug(email_input)

    path = 'accounts/%s/emails/%s' % (account_id, quote(email))
    headers = {'content-type': 'application/json'}
    gerrit.post(path, data=json.dumps(email_input), headers=headers)


def create_account_ssh_key(gerrit, account_id, ssh_public_key):
    logging.info('Creating SSH key %s for account %s', ssh_public_key,
                 account_id)

    path = 'accounts/%s/sshkeys' % (account_id)
    gerrit.post(path, data=ssh_public_key)


def create_group_membership(gerrit, account_id, group_id):
    logging.info('Creating membership of %s in group %s', account_id, group_id)
    path = 'groups/%s/accounts/%s' % (quote(group_id), account_id)
    gerrit.put(path)


def ensure_only_member_of_these_groups(gerrit, account_id, groups):
    path = 'accounts/%s' % account_id
    group_info_list = get_list(gerrit, path + '/groups')

    changed = False
    found_groups = []
    for group_info in group_info_list:
        if group_info['name'] in groups:
            logging.info("Preserving %s membership of group %s", path,
                         group_info)
            found_groups.append(group_info)
        else:
            logging.info("Removing %s from group %s", path, group_info)
            membership_path = 'groups/%s/members/%s' % (
                quote(group_info['id']), account_id)
            gerrit.delete(membership_path)
            changed = True

    for new_group_info in set(found_groups).difference(groups):
        create_group_membership(gerrit, account_id, new_group_info['id'])
        changed = True

    return groups, changed


def ensure_only_one_account_email(gerrit, account_id, email):
    path = 'accounts/%s' % account_id
    email_info_list = get_list(gerrit, path + '/emails')

    changed = False
    found_email = False
    for email_info in email_info_list:
        existing_email = email_info['email']
        if existing_email == email:
            # Since we're deleting all emails except this one, there's no need
            # to care whether it's the 'preferred' one. It soon will be!
            logging.info("Keeping %s email %s", path, email)
            found_email = True
        else:
            logging.info("Removing %s email %s", path, existing_email)
            gerrit.delete(path + '/emails/%s' % quote(existing_email))
            changed = True

    if len(email) > 0 and not found_email:
        create_account_email(gerrit, account_id, email,
                             preferred=True, no_confirmation=True)
        changed = True

    return email, changed


def ensure_only_one_account_ssh_key(gerrit, account_id, ssh_public_key):
    path = 'accounts/%s' % account_id
    ssh_key_info_list = get_list(gerrit, path + '/sshkeys')

    changed = False
    found_ssh_key = False
    for ssh_key_info in ssh_key_info_list:
        if ssh_key_info['ssh_public_key'] == ssh_public_key:
            logging.info("Keeping %s SSH key %s", path, ssh_key_info)
            found_ssh_key = True
        else:
            logging.info("Removing %s SSH key %s", path, ssh_key_info)
            gerrit.delete(path + '/sshkeys/%i' % ssh_key_info['seq'])
            changed = True

    if len(ssh_public_key) > 0 and not found_ssh_key:
        create_account_ssh_key(gerrit, account_id, ssh_public_key)
        changed = True

    return ssh_public_key, changed


def update_account(gerrit, username=None, **params):
    change = False

    try:
        account_info = gerrit.get('/accounts/%s' % quote(username))
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            logging.info("Account %s not found, creating it.", username)
            account_info = create_account(gerrit, username)
            change = True
        else:
            raise

    logging.debug(
        'Existing account info for account %s: %s', username,
        json.dumps(account_info, indent=4))

    account_id = account_info['_account_id']
    path = 'accounts/%s' % account_id

    output = {}
    output['id'] = account_id

    fullname, fullname_changed = maybe_update_field(
        gerrit, path, 'name', account_info.get('name'), params.get('fullname'))
    output['fullname'] = fullname
    change |= fullname_changed

    # Ansible sets the value of params that the user did not provide to None.

    if params.get('active') is not None:
        active = get_boolean(gerrit, path + '/active')
        active, active_changed = maybe_update_field(
            gerrit, path, 'active', active, params['active'], type='bool')
        output['active'] = active
        change |= active_changed

    if params.get('email') is not None:
        email, emails_changed = ensure_only_one_account_email(
            gerrit, account_id, params['email'])
        output['email'] = email
        change |= emails_changed

    if params.get('groups') is not None:
        groups, groups_changed = ensure_only_member_of_these_groups(
            gerrit, account_id, params['groups'])
        output['groups'] = groups
        change |= groups_changed

    if params.get('http_password') is not None:
        http_password = get_string(gerrit, path + '/password.http')
        http_password, http_password_changed = maybe_update_field(
            gerrit, path, 'http_password', http_password,
            params.get('http_password'),
            gerrit_api_path='password.http')
        output['http_password'] = http_password
        change |= http_password_changed

    if params.get('ssh_key') is not None:
        ssh_key, ssh_keys_changed = ensure_only_one_account_ssh_key(
            gerrit, account_id,  params['ssh_key'])
        output['ssh_key'] = ssh_key
        change |= ssh_keys_changed

    return output, change


def main():
    logging.basicConfig(filename='/tmp/ansible-gerrit-debug.log',
                        level=logging.DEBUG)

    argument_spec = dict()
    argument_spec.update(ACCOUNT_ARGUMENTS)
    argument_spec.update(GERRIT_COMMON_ARGUMENTS)

    module = AnsibleModule(argument_spec)

    logging.debug('Module parameters: %s', json.dumps(module.params, indent=4))

    gerrit = gerrit_connection(**module.params)

    try:
        output, changed = update_account(
            gerrit, **module.params)
        module.exit_json(changed=changed, **output)
    except (AnsibleGerritError, requests.exceptions.RequestException) as e:
        logging.error('%r', e)
        module.fail_json(msg=str(e))


main()
