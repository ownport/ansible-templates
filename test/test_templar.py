
import pytest

from templates import template
from templates.template import Templar
from templates.errors import TemplatesError
from templates.errors import TemplatesUndefinedVariable


VARIABLES = dict(
    foo="bar",
    bam="{{foo}}",
    num=1,
    var_true=True,
    var_false=False,
    var_dict=dict(a="b"),
    bad_dict="{a='b'",
    var_list=[1],
    recursive="{{recursive}}",
)


def test_templar_simple():

    templar = Templar(variables=VARIABLES)

    # test some basic templating
    assert templar.template("{{foo}}") == "bar"
    assert templar.template("{{foo}}\n") == "bar\n"
    assert templar.template("{{foo}}\n", preserve_trailing_newlines=True) == "bar\n"
    assert templar.template("{{foo}}\n", preserve_trailing_newlines=False) == "bar"
    assert templar.template("foo", convert_bare=True) == "bar"
    assert templar.template("{{bam}}") == "bar"
    assert templar.template("{{num}}") == 1
    assert templar.template("{{var_true}}") == True
    assert templar.template("{{var_false}}") == False
    assert templar.template("{{var_dict}}") == dict(a="b")
    assert templar.template("{{bad_dict}}") == "{a='b'"
    assert templar.template("{{var_list}}") == [1]
    assert templar.template(1, convert_bare=True) == 1


def test_templar_errors():
    # force errors

    templar = Templar(variables=VARIABLES)
    with pytest.raises(TemplatesUndefinedVariable):
        assert templar.template("{{bad_var}}")

    with pytest.raises(TemplatesUndefinedVariable):
        assert templar.template("{{lookup('file', bad_var)}}")

    with pytest.raises(TemplatesError):
        assert templar.template("{{recursive}}")

    with pytest.raises(TemplatesUndefinedVariable):
        assert templar.template("{{foo-bar}}")


def test_with_fail_on_undefined_false():

    templar = Templar(variables=VARIABLES)
    assert templar.template("{{bad_var}}", fail_on_undefined=False) == "{{bad_var}}"


def test_set_available_variables():

    templar = Templar(variables=VARIABLES)
    templar.set_available_variables(variables=dict(foo="bam"))
    assert templar.template("{{foo}}") == "bam"


def test_variables_must_be_a_dict_for_set_available_variables():

    templar = Templar(variables=VARIABLES)
    with pytest.raises(AssertionError):
        assert templar.set_available_variables("foo=bam")


def test_templar_escape_backslashes():
    # Rule of thumb: If escape backslashes is True you should end up with
    # the same number of backslashes as when you started.

    templar = Templar(variables=VARIABLES)
    assert templar.template("\t{{foo}}", escape_backslashes=True) == "\tbar"
    assert templar.template("\t{{foo}}", escape_backslashes=False) == "\tbar"
    assert templar.template("\\{{foo}}", escape_backslashes=True) == "\\bar"
    assert templar.template("\\{{foo}}", escape_backslashes=False) == "\\bar"
    assert templar.template("\\{{foo + '\t' }}", escape_backslashes=True) == "\\bar\t"
    assert templar.template("\\{{foo + '\t' }}", escape_backslashes=False) == "\\bar\t"
    assert templar.template("\\{{foo + '\\t' }}", escape_backslashes=True) == "\\bar\\t"
    assert templar.template("\\{{foo + '\\t' }}", escape_backslashes=False) == "\\bar\t"
    assert templar.template("\\{{foo + '\\\\t' }}", escape_backslashes=True) == "\\bar\\\\t"
    assert templar.template("\\{{foo + '\\\\t' }}", escape_backslashes=False) == "\\bar\\t"


def test_template_jinja2_extensions():

    templar = Templar(variables=VARIABLES)

    old_exts = template.DEFAULT_JINJA2_EXTENSIONS
    try:
        template.DEFAULT_JINJA2_EXTENSIONS = "foo,bar"
        assert templar._get_extensions() == ['foo', 'bar']
    finally:
        template.DEFAULT_JINJA2_EXTENSIONS = old_exts
