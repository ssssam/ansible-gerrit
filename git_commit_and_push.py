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


import contextlib
import logging
import shutil
import tempfile

from ansible.module_utils.basic import *


DOCUMENTATION = '''
---
module: git_commit_and_push
author: Sam Thursfield
short_description: Create new Git commits and push them to a remote repository
'''

EXAMPLES = '''
- git_commit_and_push:
    repo: ssh://me@gerrit.example.com:29418/All-Projects
    ref: refs/meta/config
    files:
      - ./All-Projects/groups
      - ./All-Projects/project.config
    strip_path_components: 1
    commit_message: |
      Update Gerrit top-level project configuration.

      This is commit was made from an Ansible playbook.
'''


class GitDirectory(object):
    def __init__(self, module, path):
        self.module = module
        self.path = path

    def run_git(self, args):
        logging.debug("Running: %s", args)

        rc, stdout, stderr = self.module.run_command(
            ['git'] + args, cwd=self.path, check_rc=True)

        if len(stdout.strip()) > 0:
            logging.debug("Stdout: %s", stdout.strip())
        if len(stderr.strip()) > 0:
            logging.debug("Stderr: %s", stderr.strip())

    def run_git_unchecked(self, args):
        logging.debug("Running: git %s", args)

        rc, stdout, stderr = self.module.run_command(
            ['git'] + args, cwd=self.path, check_rc=False)

        logging.debug("Return code: %s", rc)
        if len(stdout.strip()) > 0:
            logging.debug("Stdout: %s", stdout.strip())
        if len(stderr.strip()) > 0:
            logging.debug("Stderr: %s", stderr.strip())

        return rc

    def ref_exists_in_origin(self, ref):
        logging.debug("Checking for ref %s in origin", ref)
        result = self.run_git_unchecked(
            ['ls-remote', '--exit-code', 'origin', ref])

        if result == 0:
            return True
        elif result == 2:
            return False
        else:
            raise subprocess.CalledProcessError(
                "git ls-remote command failed.")

    def checkout_ref(self, ref, local_ref=None, create=False):
        local_ref = local_ref or ref

        # It's a bit weird to use `git fetch` to checkout a ref instead of
        # using `git checkout`, but this works in cases where the ref is a
        # special ref that isn't under refs/heads/* or refs/tags/* and so isn't
        # already fetched by the `git clone` command.

        if self.ref_exists_in_origin(ref):
            self.run_git(['fetch', '--quiet', 'origin', ref + ':' + local_ref])
            self.run_git(['checkout', '--quiet', local_ref])
        elif create:
            self.run_git(['checkout', '--quiet', '-b', local_ref])
        else:
            raise RuntimeError("Remote ref '%s' does not exist" % ref)

    def add_files(self, files_in_repo):
        self.run_git(['add'] + files_in_repo)

    def staging_area_has_changes(self):
        result = self.run_git_unchecked(['diff-index', '--quiet', 'HEAD'])
        return result

    def commit(self, author_name='', author_email='', committer_name='',
               committer_email='', commit_message='', **ignored_kwargs):
        # self.module.run_command() doesn't let us pass in a separate
        # environment, so we have to temporarily change os.environ to pass this
        # in.
        old_env = os.environ.copy()
        if author_email:
            os.environ['GIT_AUTHOR_EMAIL'] = author_email
        if author_name:
            os.environ['GIT_AUTHOR_NAME'] = author_name
        if committer_email:
            os.environ['GIT_COMMITTER_EMAIL'] = committer_email
        if committer_name:
            os.environ['GIT_COMMITTER_NAME'] = committer_name
        self.run_git(['commit', '--quiet', '--message', commit_message])
        os.environ = old_env

    def push(self, remote_url=None, local_ref=None, remote_ref=None):
        refspec = local_ref + ':' + remote_ref
        self.run_git(['push', '--quiet', remote_url, refspec])


@contextlib.contextmanager
def clone_repo(module, url, path=None):
    '''Clone repo to location for the duration of a 'with' block.'''
    if path is None:
        path = tempfile.mkdtemp()
        logging.debug('Created temporary checkout directory %s' % path)
    elif os.path.exists(path):
        raise RuntimeError("Path %s already exists, not overwriting.", path)

    try:
        rc, stdout, stderr = module.run_command(
            ['git', 'clone', '--quiet', '--no-checkout', url, path])

        if rc != 0:
            raise RuntimeError('Cloning %s failed: %s' % (url, stderr))

        git_directory = GitDirectory(module, path)
        yield git_directory
    finally:
        if os.path.exists(path):
            shutil.rmtree(path)


def strip_path_components(path, n_components_to_strip):
    if n_components_to_strip == 0:
        return path

    components = os.path.normpath(path).split(os.path.sep)

    logging.debug("Stripping path %s: components %s, %i to strip", path,
                  components, n_components_to_strip)
    if n_components_to_strip >= len(components):
        raise RuntimeError(
            "Cannot strip more than %i component(s) from path %s" %
            len(components), path)

    return os.path.sep.join(components[n_components_to_strip:])


def main():
    logging.basicConfig(filename='/tmp/ansible-gerrit-debug.log',
                        level=logging.DEBUG)

    argument_spec = dict(
        author_name     = dict(type='str'),
        author_email    = dict(type='str'),
        commit_message  = dict(type='str', required=True),
        committer_name  = dict(type='str'),
        committer_email = dict(type='str'),
        create_ref      = dict(type='bool', choices=BOOLEANS, default=False),
        files           = dict(type='list', required=True),
        prepend_path    = dict(type='str', default=''),
        ref             = dict(type='str', default='master'),
        repo            = dict(type='str', required=True),
        strip_path_components = dict(type='int', default=0)
    )

    module = AnsibleModule(argument_spec)

    logging.debug('Module parameters: %s', json.dumps(module.params, indent=4))

    try:
        with clone_repo(module, module.params['repo']) as repo:
            repo.checkout_ref(module.params['ref'], local_ref='local',
                              create=module.params['create_ref'])

            files_in_repo = []

            for source_path in module.params['files']:
                stripped_path = strip_path_components(
                    source_path, module.params['strip_path_components'])
                target_path = os.path.join(
                    repo.path, module.params['prepend_path'], stripped_path)
                if not os.path.exists(os.path.dirname(target_path)):
                    os.makedirs(os.path.dirname(target_path))
                shutil.copy(source_path, target_path)
                files_in_repo.append(target_path)

            repo.add_files(files_in_repo)

            if repo.staging_area_has_changes():
                logging.info(
                    "Staging area has changes, creating a new commit.")
                repo.commit(**module.params)

                logging.info(
                    "Pushing to remote %s ref %s", module.params['repo'],
                    module.params['ref'])
                repo.push(remote_url=module.params['repo'], local_ref='local',
                          remote_ref=module.params['ref'])
                module.exit_json(changed=True)
            else:
                logging.info("Staging area has no changes after adding files.")
                module.exit_json(changed=False)

    except (subprocess.CalledProcessError, RuntimeError) as e:
        logging.error('%r', e)
        module.fail_json(msg=str(e))

main()
