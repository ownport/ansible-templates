from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

import jinja2

__all__ = ['J2Template']


class J2Template(jinja2.environment.Template):
    '''
    A helper class, which prevents Jinja2 from running _jinja2_vars through dict().
    Without this, {% include %} and similar will create new contexts unlike the special
    one created in template_from_file. This ensures they are all alike, except for
    potential locals.
    '''

    def new_context(self, vars=None, shared=False, locals=None):
        return self.environment.context_class(self.environment, vars.add_locals(locals), self.name, self.blocks)

