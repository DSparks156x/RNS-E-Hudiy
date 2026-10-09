"""Render the proposed service-only sudo policy; this module installs nothing."""
import re

from .service_control import SERVICES


def render_sudoers(username):
    if not re.fullmatch(r'[a-z_][a-z0-9_-]*\$?', username):
        raise ValueError('Expected a local Linux username.')
    lines = ['# RNS-E Manager: exact project unit actions only.']
    for service in SERVICES:
        if not service.control:
            continue
        flags = '' if service.disruptive else '--no-block '
        for action in ('start', 'stop', 'restart'):
            lines.append(f'{username} ALL=(root) NOPASSWD: /usr/bin/systemctl {flags}{action} {service.unit}')
    return '\n'.join(lines) + '\n'
