from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

try:
    from _yaml import CParser, CEmitter
    HAVE_PYYAML_C = True
except ImportError:
    HAVE_PYYAML_C = False

from yaml.resolver import Resolver

from templates.parsing.yaml.constructor import TemplatesConstructor

if HAVE_PYYAML_C:
    class TemplatesLoader(CParser, TemplatesConstructor, Resolver):
        def __init__(self, stream, file_name=None):
            CParser.__init__(self, stream)
            TemplatesConstructor.__init__(self, file_name=file_name)
            Resolver.__init__(self)
else:
    from yaml.composer import Composer
    from yaml.reader import Reader
    from yaml.scanner import Scanner
    from yaml.parser import Parser

    class TemplatesLoader(Reader, Scanner, Parser, Composer, TemplatesConstructor, Resolver):
        def __init__(self, stream, file_name=None):
            Reader.__init__(self, stream)
            Scanner.__init__(self)
            Parser.__init__(self)
            Composer.__init__(self)
            TemplatesConstructor.__init__(self, file_name=file_name)
            Resolver.__init__(self)
