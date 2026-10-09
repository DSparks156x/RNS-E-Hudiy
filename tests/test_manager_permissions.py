"""Check the reviewable policy text; do not install it or execute its commands."""
import unittest
from hudiy_manager.service_permissions import render_sudoers
from hudiy_manager.service_control import SERVICES


class PermissionPolicyTests(unittest.TestCase):
    def test_policy_matches_the_service_allowlist_without_wildcards(self):
        rules = render_sudoers('pi').splitlines()[1:]
        expected = [f'pi ALL=(root) NOPASSWD: /usr/bin/systemctl {"" if service.disruptive else "--no-block "}{action} {service.unit}'
                    for service in SERVICES if service.control for action in ('start', 'stop', 'restart')]
        self.assertEqual(rules, expected)
        self.assertEqual(len(rules), 36)
        self.assertNotIn('*', '\n'.join(rules))
        self.assertNotIn('hudiy_manager.service', '\n'.join(rules))

    def test_username_cannot_inject_rules(self):
        for value in ('', 'pi\nroot ALL=(ALL) ALL', 'pi ALL', 'pi,root', '../pi'):
            with self.assertRaises(ValueError):
                render_sudoers(value)
