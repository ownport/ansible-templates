from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

import ast
import sys

from templates.six import string_types
from templates.six.moves import builtins

DEFAULT_CALLABLE_WHITELIST = []

def safe_eval(expr, locals={}, include_exceptions=False):
    '''
    This is intended for allowing things like:
    with_items: a_list_variable

    Where Jinja2 would return a string but we do not want to allow it to
    call functions (outside of Jinja2, where the env is constrained). If
    the input data to this function came from an untrusted (remote) source,
    it should first be run through _clean_data_struct() to ensure the data
    is further sanitized prior to evaluation.

    Based on:
    http://stackoverflow.com/questions/12523516/using-ast-and-whitelists-to-make-pythons-eval-safe
    '''

    # define certain JSON types
    # eg. JSON booleans are unknown to python eval()
    JSON_TYPES = {
        'false': False,
        'null': None,
        'true': True,
    }

    # this is the whitelist of AST nodes we are going to
    # allow in the evaluation. Any node type other than
    # those listed here will raise an exception in our custom
    # visitor class defined below.
    SAFE_NODES = set(
        (
            ast.Add,
            ast.BinOp,
            ast.Call,
            ast.Compare,
            ast.Dict,
            ast.Div,
            ast.Expression,
            ast.List,
            ast.Load,
            ast.Mult,
            ast.Num,
            ast.Name,
            ast.Str,
            ast.Sub,
            ast.Tuple,
            ast.UnaryOp,
        )
    )

    # AST node types were expanded after 2.6
    if sys.version_info[:2] >= (2, 7):
        SAFE_NODES.update(
            set(
                (ast.Set,)
            )
        )

    # And in Python 3.4 too
    if sys.version_info[:2] >= (3, 4):
        SAFE_NODES.update(
            set(
                (ast.NameConstant,)
            )
        )

    CALL_WHITELIST = DEFAULT_CALLABLE_WHITELIST

    class CleansingNodeVisitor(ast.NodeVisitor):
        def generic_visit(self, node, inside_call=False):
            if type(node) not in SAFE_NODES:
                raise Exception("invalid expression (%s)" % expr)
            elif isinstance(node, ast.Call):
                inside_call = True
            elif isinstance(node, ast.Name) and inside_call:
                if hasattr(builtins, node.id) and node.id not in CALL_WHITELIST:
                    raise Exception("invalid function: %s" % node.id)
            # iterate over all child nodes
            for child_node in ast.iter_child_nodes(node):
                self.generic_visit(child_node, inside_call)

    if not isinstance(expr, string_types):
        # already templated to a datastructure, perhaps?
        if include_exceptions:
            return (expr, None)
        return expr

    cnv = CleansingNodeVisitor()
    try:
        parsed_tree = ast.parse(expr, mode='eval')
        cnv.visit(parsed_tree)
        compiled = compile(parsed_tree, expr, 'eval')
        result = eval(compiled, JSON_TYPES, dict(locals))

        if include_exceptions:
            return (result, None)
        else:
            return result
    except SyntaxError as e:
        # special handling for syntax errors, we just return
        # the expression string back as-is
        if include_exceptions:
            return (expr, None)
        return expr
    except Exception as e:
        if include_exceptions:
            return (expr, e)
        return expr

