from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

import yaml
from templates.six import PY3

from templates.parsing.yaml.objects import TemplatesUnicode, TemplatesSequence, TemplatesMapping
from templates.vars.hostvars import HostVars


class TemplatesDumper(yaml.SafeDumper):
    '''
    A simple stub class that allows us to add representers
    for our overridden object types.
    '''
    pass


def represent_hostvars(self, data):
    return self.represent_dict(dict(data))

if PY3:
    represent_unicode = yaml.representer.SafeRepresenter.represent_str
else:
    represent_unicode = yaml.representer.SafeRepresenter.represent_unicode

TemplatesDumper.add_representer(
    TemplatesUnicode,
    represent_unicode,
)

TemplatesDumper.add_representer(
    HostVars,
    represent_hostvars,
)

TemplatesDumper.add_representer(
    TemplatesSequence,
    yaml.representer.SafeRepresenter.represent_list,
)

TemplatesDumper.add_representer(
    TemplatesMapping,
    yaml.representer.SafeRepresenter.represent_dict,
)

