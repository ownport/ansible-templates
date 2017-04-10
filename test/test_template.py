
from templates.template import Templar


def test_templates_instance():

    templar = Templar()
    assert isinstance(templar, Templar)

    templar = Templar(variables={})
    assert isinstance(templar, Templar)

    templar = Templar(variables={'a': 1})
    assert isinstance(templar, Templar)


def test_templates_template_string_types():

    templar = Templar(variables={'var1': 'test'})
    assert templar.template('test') == 'test'
    assert templar.template('{{var1}}') == 'test'
    assert templar.template('var1={{var1}}') == 'var1=test'

