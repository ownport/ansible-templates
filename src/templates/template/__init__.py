from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

import ast
import os
import re
import logging
import contextlib

from io import StringIO
from numbers import Number

from templates.six import string_types, text_type
from templates.filters import all as get_all_filters
from templates.template.safe_eval import safe_eval
from templates.template.template import J2Template
from templates.template.vars import J2Vars
from templates.utils.unicode import to_unicode, to_str
from templates.errors import TemplatesError, TemplatesFilterError, TemplatesUndefinedVariable

from jinja2 import Environment
from jinja2.loaders import FileSystemLoader
from jinja2.exceptions import TemplateSyntaxError, UndefinedError
from jinja2.utils import concat as j2_concat
from jinja2.runtime import Context, StrictUndefined

try:
    from hashlib import sha1
except ImportError:
    from sha import sha as sha1


__all__ = ['Templar']
logger = logging.getLogger(__name__)

# A regex for checking to see if a variable we're trying to
# expand is just a single variable name.

# Primitive Types which we don't want Jinja to convert to strings.
NON_TEMPLATED_TYPES = ( bool, Number )

JINJA2_OVERRIDE = '#jinja2:'
STRING_TYPE_FILTERS = ['string', 'to_json', 'to_nice_json', 'to_yaml', 'ppretty', 'json']
DEFAULT_JINJA2_EXTENSIONS = None
DEFAULT_NULL_REPRESENTATION = None


def _escape_backslashes(data, jinja_env):
    """Double backslashes within jinja2 expressions

    A user may enter something like this in a playbook::

      debug:
        msg: "Test Case 1\\3; {{ test1_name | regex_replace('^(.*)_name$', '\\1')}}"

    The string inside of the {{ gets interpreted multiple times First by yaml.
    Then by python.  And finally by jinja2 as part of it's variable.  Because
    it is processed by both python and jinja2, the backslash escaped
    characters get unescaped twice.  This means that we'd normally have to use
    four backslashes to escape that.  This is painful for playbook authors as
    they have to remember different rules for inside vs outside of a jinja2
    expression (The backslashes outside of the "{{ }}" only get processed by
    yaml and python.  So they only need to be escaped once).  The following
    code fixes this by automatically performing the extra quoting of
    backslashes inside of a jinja2 expression.

    """
    if '\\' in data and '{{' in data:
        new_data = []
        d2 = jinja_env.preprocess(data)
        in_var = False

        for token in jinja_env.lex(d2):
            if token[1] == 'variable_begin':
                in_var = True
                new_data.append(token[2])
            elif token[1] == 'variable_end':
                in_var = False
                new_data.append(token[2])
            elif in_var and token[1] == 'string':
                # Double backslashes only if we're inside of a jinja2 variable
                new_data.append(token[2].replace('\\','\\\\'))
            else:
                new_data.append(token[2])

        data = ''.join(new_data)

    return data


def _count_newlines_from_end(in_str):
    '''
    Counts the number of newlines at the end of a string. This is used during
    the jinja2 templating to ensure the count matches the input, since some newlines
    may be thrown away during the templating.
    '''

    try:
        i = len(in_str)
        j = i -1
        while in_str[j] == '\n':
            j -= 1
        return i - 1 - j
    except IndexError:
        # Uncommon cases: zero length string and string containing only newlines
        return i


class TemplatesContext(Context):
    '''
    A custom context, which intercepts resolve() calls and sets a flag
    internally if any variable lookup returns an AnsibleUnsafe value. This
    flag is checked post-templating, and (when set) will result in the
    final templated result being wrapped via UnsafeProxy.
    '''
    def __init__(self, *args, **kwargs):
        super(TemplatesContext, self).__init__(*args, **kwargs)
        self.unsafe = False

    def _is_unsafe(self, val):
        '''
        Our helper function, which will also recursively check dict and
        list entries due to the fact that they may be repr'd and contain
        a key or value which contains jinja2 syntax and would otherwise
        lose the AnsibleUnsafe value.
        '''
        if isinstance(val, dict):
            for key in val.keys():
                if self._is_unsafe(key) or self._is_unsafe(val[key]):
                    return True
        elif isinstance(val, list):
            for item in val:
                if self._is_unsafe(item):
                    return True
        elif isinstance(val, string_types) and hasattr(val, '__UNSAFE__'):
            return True
        return False

    def resolve(self, key):
        '''
        The intercepted resolve(), which uses the helper above to set the
        internal flag whenever an unsafe variable value is returned.
        '''
        val = super(TemplatesContext, self).resolve(key)
        if val is not None and not self.unsafe:
            if self._is_unsafe(val):
                self.unsafe = True
        return val


class TemplatesEnvironment(Environment):
    '''
    Our custom environment, which simply allows us to override the class-level
    values for the Template and Context classes used by jinja2 internally.
    '''
    context_class = TemplatesContext
    template_class = J2Template


class Templar:
    '''
    The main class for templating, with the main entry-point of template().
    '''

    def __init__(self, variables=dict()):
        self._filters = None
        self._tests = None
        self._available_variables = variables
        self._cached_result = {}

        # flags to determine whether certain failures during templating
        # should result in fatal errors being raised
        self._fail_on_undefined_errors = True

        self.environment = TemplatesEnvironment(
            trim_blocks=True,
            undefined=StrictUndefined,
            extensions=self._get_extensions(),
            finalize=self._finalize,
        )

        self.SINGLE_VAR = re.compile(r"^%s\s*(\w*)\s*%s$" % (self.environment.variable_start_string, self.environment.variable_end_string))

        self.block_start = self.environment.block_start_string
        self.block_end = self.environment.block_end_string
        self.variable_start = self.environment.variable_start_string
        self.variable_end = self.environment.variable_end_string
        self._clean_regex = re.compile(r'(?:%s|%s|%s|%s)' % (self.variable_start, self.block_start, self.block_end, self.variable_end))
        self._no_type_regex = re.compile(r'.*\|\s*(?:%s)\s*(?:%s)?$' % ('|'.join(STRING_TYPE_FILTERS), self.variable_end))

    def _get_extensions(self):
        '''
        Return jinja2 extensions to load.

        If some extensions are set via jinja_extensions in ansible.cfg, we try
        to load them with the jinja environment.
        '''

        jinja_exts = []
        if DEFAULT_JINJA2_EXTENSIONS:
            # make sure the configuration directive doesn't contain spaces
            # and split extensions in an array
            jinja_exts = DEFAULT_JINJA2_EXTENSIONS.replace(" ", "").split(',')

        return jinja_exts

    def _clean_data(self, orig_data):
        ''' remove jinja2 template tags from a string '''

        if not isinstance(orig_data, string_types) or hasattr(orig_data, '__UNSAFE__'):
            return orig_data

        with contextlib.closing(StringIO(orig_data)) as data:
            # these variables keep track of opening block locations, as we only
            # want to replace matched pairs of print/block tags
            print_openings = []
            block_openings = []
            for mo in self._clean_regex.finditer(orig_data):
                token = mo.group(0)
                token_start = mo.start(0)

                if token[0] == self.variable_start[0]:
                    if token == self.block_start:
                        block_openings.append(token_start)
                    elif token == self.variable_start:
                        print_openings.append(token_start)

                elif token[1] == self.variable_end[1]:
                    prev_idx = None
                    if token == self.block_end and block_openings:
                        prev_idx = block_openings.pop()
                    elif token == self.variable_end and print_openings:
                        prev_idx = print_openings.pop()

                    if prev_idx is not None:
                        # replace the opening
                        data.seek(prev_idx, os.SEEK_SET)
                        data.write(to_unicode(self.environment.comment_start_string))
                        # replace the closing
                        data.seek(token_start, os.SEEK_SET)
                        data.write(to_unicode(self.environment.comment_end_string))

                else:
                    raise TemplatesError("Error while cleaning data for safety: unhandled regex match")

            return data.getvalue()

    def set_available_variables(self, variables):
        '''
        Sets the list of template variables this Templar instance will use
        to template things, so we don't have to pass them around between
        internal methods. We also clear the template cache here, as the variables
        are being changed.
        '''

        assert isinstance(variables, dict)
        self._available_variables = variables
        self._cached_result = {}

    def template(self, variable, convert_bare=False, preserve_trailing_newlines=True, escape_backslashes=True,
                 fail_on_undefined=None, overrides=None, convert_data=True, static_vars=[''],
                 cache=True, bare_deprecated=True):
        '''
        Templates (possibly recursively) any given data as input. If convert_bare is
        set to True, the given data will be wrapped as a jinja2 variable ('{{foo}}')
        before being sent through the template engine. 
        '''

        if fail_on_undefined is None:
            fail_on_undefined = self._fail_on_undefined_errors

        # Don't template unsafe variables, instead drop them back down to their constituent type.
        if hasattr(variable, '__UNSAFE__'):
            if isinstance(variable, text_type):
                rval = self._clean_data(variable)
            else:
                # Do we need to convert these into text_type as well?
                # return self._clean_data(to_text(variable._obj, nonstring='passthru'))
                rval = self._clean_data(variable._obj)
            return rval

        try:
            if convert_bare:
                variable = self._convert_bare_variable(variable, bare_deprecated=bare_deprecated)

            if isinstance(variable, string_types):
                result = variable

                if self._contains_vars(variable):

                    # Check to see if the string we are trying to render is just referencing a single
                    # var.  In this case we don't want to accidentally change the type of the variable
                    # to a string by using the jinja template renderer. We just want to pass it.
                    only_one = self.SINGLE_VAR.match(variable)
                    if only_one:
                        var_name = only_one.group(1)
                        if var_name in self._available_variables:
                            resolved_val = self._available_variables[var_name]
                            if isinstance(resolved_val, NON_TEMPLATED_TYPES):
                                return resolved_val
                            elif resolved_val is None:
                                return DEFAULT_NULL_REPRESENTATION

                    # Using a cache in order to prevent template calls with already templated variables
                    sha1_hash = None
                    if cache:
                        variable_hash = sha1(text_type(variable).encode('utf-8'))
                        options_hash  = sha1((text_type(preserve_trailing_newlines) + text_type(escape_backslashes)
                                              + text_type(fail_on_undefined) + text_type(overrides)).encode('utf-8'))
                        sha1_hash = variable_hash.hexdigest() + options_hash.hexdigest()
                    if cache and sha1_hash in self._cached_result:
                        result = self._cached_result[sha1_hash]
                    else:
                        result = self._do_template(
                            variable,
                            preserve_trailing_newlines=preserve_trailing_newlines,
                            escape_backslashes=escape_backslashes,
                            fail_on_undefined=fail_on_undefined,
                            overrides=overrides,
                        )
                        unsafe = hasattr(result, '__UNSAFE__')
                        if convert_data and not self._no_type_regex.match(variable):
                            # if this looks like a dictionary or list, convert it to such using the safe_eval method
                            if (result.startswith("{") and not result.startswith(self.environment.variable_start_string)) or \
                                result.startswith("[") or result in ("True", "False"):
                                eval_results = safe_eval(result, locals=self._available_variables, include_exceptions=True)
                                if eval_results[1] is None:
                                    result = eval_results[0]
                                    if unsafe:
                                        from templates.vars.unsafe_proxy import wrap_var
                                        result = wrap_var(result)
                                else:
                                    # FIXME: if the safe_eval raised an error, should we do something with it?
                                    pass

                        # we only cache in the case where we have a single variable
                        # name, to make sure we're not putting things which may otherwise
                        # be dynamic in the cache (filters, lookups, etc.)
                        if cache:
                            self._cached_result[sha1_hash] = result

                return result

            elif isinstance(variable, (list, tuple)):
                return [self.template(
                            v,
                            preserve_trailing_newlines=preserve_trailing_newlines,
                            fail_on_undefined=fail_on_undefined,
                            overrides=overrides,
                        ) for v in variable]
            elif isinstance(variable, dict):
                d = {}
                # we don't use iteritems() here to avoid problems if the underlying dict
                # changes sizes due to the templating, which can happen with hostvars
                for k in variable.keys():
                    if k not in static_vars:
                        d[k] = self.template(
                                   variable[k],
                                   preserve_trailing_newlines=preserve_trailing_newlines,
                                   fail_on_undefined=fail_on_undefined,
                                   overrides=overrides,
                               )
                    else:
                        d[k] = variable[k]
                return d
            else:
                return variable

        except TemplatesFilterError:
            if self._fail_on_filter_errors:
                raise
            else:
                return variable

    def _contains_vars(self, data):
        '''
        returns True if the data contains a variable pattern
        '''
        for marker in  [self.environment.block_start_string, self.environment.variable_start_string, self.environment.comment_start_string]:
            if marker in data:
                return True
        return False

    def _convert_bare_variable(self, variable, bare_deprecated):
        '''
        Wraps a bare string, which may have an attribute portion (ie. foo.bar)
        in jinja2 variable braces so that it is evaluated properly.
        '''

        if isinstance(variable, string_types):
            contains_filters = "|" in variable
            first_part = variable.split("|")[0].split(".")[0].split("[")[0]
            if (contains_filters or first_part in self._available_variables) and self.environment.variable_start_string not in variable:
                if bare_deprecated:
                     logger.warning("DEPRECATED: Using bare variables is deprecated. Update your playbooks so that the environment value uses the full variable syntax ('%s%s%s')" %
                        (self.environment.variable_start_string, variable, self.environment.variable_end_string))
                return "%s%s%s" % (self.environment.variable_start_string, variable, self.environment.variable_end_string)

        # the variable didn't meet the conditions to be converted,
        # so just return it as-is
        return variable

    def _finalize(self, thing):
        '''
        A custom finalize method for jinja2, which prevents None from being returned
        '''
        return thing if thing is not None else ''

    def _do_template(self, data, preserve_trailing_newlines=True, escape_backslashes=True, fail_on_undefined=None, overrides=None):

        # For preserving the number of input newlines in the output (used
        # later in this method)
        data_newlines = _count_newlines_from_end(data)

        if fail_on_undefined is None:
            fail_on_undefined = self._fail_on_undefined_errors

        try:
            # allows template header overrides to change jinja2 options.
            if overrides is None:
                myenv = self.environment.overlay()
            else:
                myenv = self.environment.overlay(overrides)

            # Get jinja env overrides from template
            if data.startswith(JINJA2_OVERRIDE):
                eol = data.find('\n')
                line = data[len(JINJA2_OVERRIDE):eol]
                data = data[eol+1:]
                for pair in line.split(','):
                    (key,val) = pair.split(':')
                    key = key.strip()
                    setattr(myenv, key, ast.literal_eval(val.strip()))

            if escape_backslashes:
                # Allow users to specify backslashes in playbooks as "\\"
                # instead of as "\\\\".
                data = _escape_backslashes(data, myenv)

            try:
                t = myenv.from_string(data)
            except TemplateSyntaxError as e:
                raise TemplatesError("template error while templating string: %s. String: %s" % (to_str(e), to_str(data)))
            except Exception as e:
                if 'recursion' in to_str(e):
                    raise TemplatesError("recursive loop detected in template string: %s" % to_str(data))
                else:
                    return data

            t.globals['finalize'] = self._finalize

            jvars = J2Vars(self, t.globals)

            new_context = t.new_context(jvars, shared=True)
            rf = t.root_render_func(new_context)

            try:
                res = j2_concat(rf)
                if new_context.unsafe:
                    from templates.vars.unsafe_proxy import wrap_var
                    res = wrap_var(res)
            except TypeError as te:
                if 'StrictUndefined' in to_str(te):
                    errmsg  = "Unable to look up a name or access an attribute in template string (%s).\n" % to_str(data)
                    errmsg += "Make sure your variable name does not contain invalid characters like '-': %s" % to_str(te)
                    raise TemplatesUndefinedVariable(errmsg)
                else:
                    logger.debug("failing because of a type error, template data is: %s" % to_str(data))
                    raise TemplatesError("Unexpected templating type error occurred on (%s): %s" % (to_str(data),to_str(te)))

            if preserve_trailing_newlines:
                # The low level calls above do not preserve the newline
                # characters at the end of the input data, so we use the
                # calculate the difference in newlines and append them
                # to the resulting output for parity
                #
                # jinja2 added a keep_trailing_newline option in 2.7 when
                # creating an Environment.  That would let us make this code
                # better (remove a single newline if
                # preserve_trailing_newlines is False).  Once we can depend on
                # that version being present, modify our code to set that when
                # initializing self.environment and remove a single trailing
                # newline here if preserve_newlines is False.
                res_newlines = _count_newlines_from_end(res)
                if data_newlines > res_newlines:
                    res += '\n' * (data_newlines - res_newlines)

            return res
        except (UndefinedError, TemplatesUndefinedVariable) as e:
            if fail_on_undefined:
                raise TemplatesUndefinedVariable(e)
            else:
                #TODO: return warning about undefined var
                return data

