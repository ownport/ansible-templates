from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

import logging

from yaml.constructor import Constructor, ConstructorError
from yaml.nodes import MappingNode
from templates.parsing.yaml.objects import TemplatesMapping, TemplatesSequence, TemplatesUnicode
from templates.vars.unsafe_proxy import wrap_var

logger = logging.getLogger(__name__)


class TemplatesConstructor(Constructor):

    def __init__(self, file_name=None):
        self._ansible_file_name = file_name
        super(Constructor, self).__init__()

    def construct_yaml_map(self, node):
        data = TemplatesMapping()
        yield data
        value = self.construct_mapping(node)
        data.update(value)
        data.ansible_pos = self._node_position_info(node)

    def construct_mapping(self, node, deep=False):
        # Most of this is from yaml.constructor.SafeConstructor.  We replicate
        # it here so that we can warn users when they have duplicate dict keys
        # (pyyaml silently allows overwriting keys)
        if not isinstance(node, MappingNode):
            raise ConstructorError(None, None,
                    "expected a mapping node, but found %s" % node.id,
                    node.start_mark)
        self.flatten_mapping(node)
        mapping = TemplatesMapping()

        # Add our extra information to the returned value
        mapping.ansible_pos = self._node_position_info(node)

        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            try:
                hash(key)
            except TypeError as exc:
                raise ConstructorError("while constructing a mapping", node.start_mark,
                        "found unacceptable key (%s)" % exc, key_node.start_mark)

            if key in mapping:
                logger.warning(u'While constructing a mapping from {1}, line {2}, column {3}, found a duplicate dict key ({0}).  Using last defined value only.'.format(key, *mapping.ansible_pos))

            value = self.construct_object(value_node, deep=deep)
            mapping[key] = value

        return mapping

    def construct_yaml_str(self, node, unsafe=False):
        # Override the default string handling function
        # to always return unicode objects
        value = self.construct_scalar(node)
        ret = TemplatesUnicode(value)

        ret.ansible_pos = self._node_position_info(node)

        if unsafe:
            ret = wrap_var(ret)

        return ret

    def construct_yaml_seq(self, node):
        data = TemplatesSequence()
        yield data
        data.extend(self.construct_sequence(node))
        data.ansible_pos = self._node_position_info(node)

    def construct_yaml_unsafe(self, node):
        return self.construct_yaml_str(node, unsafe=True)

    def _node_position_info(self, node):
        # the line number where the previous token has ended (plus empty lines)
        # Add one so that the first line is line 1 rather than line 0
        column = node.start_mark.column + 1
        line = node.start_mark.line + 1

        # in some cases, we may have pre-read the data and then
        # passed it to the load() call for YAML, in which case we
        # want to override the default datasource (which would be
        # '<string>') to the actual filename we read in
        datasource = self._ansible_file_name or node.start_mark.name

        return (datasource, line, column)

TemplatesConstructor.add_constructor(u'tag:yaml.org,2002:map', TemplatesConstructor.construct_yaml_map)
TemplatesConstructor.add_constructor(u'tag:yaml.org,2002:python/dict', TemplatesConstructor.construct_yaml_map)
TemplatesConstructor.add_constructor(u'tag:yaml.org,2002:str', TemplatesConstructor.construct_yaml_str)
TemplatesConstructor.add_constructor(u'tag:yaml.org,2002:python/unicode', TemplatesConstructor.construct_yaml_str)
TemplatesConstructor.add_constructor(u'tag:yaml.org,2002:seq', TemplatesConstructor.construct_yaml_seq)
TemplatesConstructor.add_constructor(u'!unsafe', TemplatesConstructor.construct_yaml_unsafe)
