from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

from templates.six import text_type


class BaseYAMLObject(object):
    '''
    the base class used to sub-class python built-in objects
    so that we can add attributes to them during yaml parsing

    '''
    _data_source = None
    _line_number = 0
    _column_number = 0

    def _get_ansible_position(self):
        return (self._data_source, self._line_number, self._column_number)

    def _set_ansible_position(self, obj):
        try:
            (src, line, col) = obj
        except (TypeError, ValueError):
            raise AssertionError(
                'ansible_pos can only be set with a tuple/list '
                'of three values: source, line number, column number'
            )
        self._data_source = src
        self._line_number = line
        self._column_number = col

    ansible_pos = property(_get_ansible_position, _set_ansible_position)


class TemplatesMapping(BaseYAMLObject, dict):
    ''' sub class for dictionaries '''
    pass


class TemplatesUnicode(BaseYAMLObject, text_type):
    ''' sub class for unicode objects '''
    pass


class TemplatesSequence(BaseYAMLObject, list):
    ''' sub class for lists '''
    pass
