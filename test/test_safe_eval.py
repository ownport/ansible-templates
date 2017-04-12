from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

from collections import defaultdict

from templates.template import safe_eval


def test_safe_eval_usage():
    # test safe eval calls with different possible types for the
    # locals dictionary, to ensure we don't run into problems like
    # ansible/ansible/issues/12206 again
    for locals_vars in (dict(), defaultdict(dict)):
        assert safe_eval('True', locals=locals_vars) == True
        assert safe_eval('False', locals=locals_vars) == False
        assert safe_eval('0', locals=locals_vars) == 0
        assert safe_eval('[]', locals=locals_vars) == []
        assert safe_eval('{}', locals=locals_vars) == {}


def test_set_literals():

    assert safe_eval('{0}') == set([0])
