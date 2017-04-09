
from templates.template import Templar


def test_templates_instance():

    templar = Templar()
    assert isinstance(templar, Templar)

    templar = Templar(variables={})
    assert isinstance(templar, Templar)

    templar = Templar(variables={'a': 1})
    assert isinstance(templar, Templar)

