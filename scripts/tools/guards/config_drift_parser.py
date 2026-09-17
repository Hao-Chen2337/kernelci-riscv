"""config_drift's .config parser: the two ways it used to lie."""
import importlib.util
import os

from .support import TOOLS, check


def _config_drift():
    """Load scripts/tools/config_drift.py without importing it as a package."""
    path = os.path.join(TOOLS, "config_drift.py")
    spec = importlib.util.spec_from_file_location("config_drift", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_config_drift_parser():
    """A drift report must not lie: quoted '#' kept, annotated 'is not set' kept.

    Two defects from the self-audit (INTERNAL-DEEP-DIVE section 12.1): the parser
    cut a value at the first '#', so CONFIG_STR="a#b" became "a and a real change
    could be hidden; and it dropped "# CONFIG_X is not set  # why" entirely, so an
    option that was disabled read as never present - the wrong category.
    """
    cd = _config_drift()

    def parse(text):
        return cd.parse_config(text)

    # Quoted values keep a '#' inside the quotes.
    check(parse('CONFIG_STR="a#b"').get("CONFIG_STR") == '"a#b"',
          "a quoted value must keep its '#'")
    check(parse('CONFIG_CMDLINE="root=/dev/vda#frag quiet"').get("CONFIG_CMDLINE")
          == '"root=/dev/vda#frag quiet"',
          "a quoted cmdline must keep its '#'")
    check(parse('CONFIG_LOCALVERSION="x#y"').get("CONFIG_LOCALVERSION") == '"x#y"',
          "a quoted localversion must keep its '#'")

    # A '#' outside quotes is still a comment.
    check(parse("CONFIG_PLAIN=0x1234 # was 0x1000").get("CONFIG_PLAIN") == "0x1234",
          "a trailing comment must still be dropped")
    check(parse("CONFIG_TAIL=y#no-space comment").get("CONFIG_TAIL") == "y",
          "a comment without a space must still be dropped")
    check(parse('CONFIG_AFTER="a#b" # trailing note').get("CONFIG_AFTER") == '"a#b"',
          "a comment after a quoted value must be dropped")

    # An escaped quote does not end the string.
    check(parse('CONFIG_ESC="a\\"#b" # note').get("CONFIG_ESC") == '"a\\"#b"',
          "an escaped quote must stay inside the value")

    # "# CONFIG_X is not set" wins over whatever follows it.
    for text in ("# CONFIG_C is not set  # keep it off for riscv",
                 "# CONFIG_C is not set",
                 "# CONFIG_C is not set    ",
                 "# CONFIG_C is not set. Why: see the fragment"):
        check(parse(text).get("CONFIG_C") == "n",
              f"a disabled option must survive trailing text: {text!r}")

    # Ordinary comments and blanks are ignored.
    check(parse("#\n#\n# Automatically generated file; DO NOT EDIT.") == {},
          "header comments are not options")
    check(parse("# an ordinary comment mentioning CONFIG_D=y") == {},
          "a comment naming a CONFIG_ is not an option")
    check(parse("# CONFIG_E is not a thing we want") == {},
          "only ' is not set' marks a disabled option")

    # The report reads the right category.
    added, removed, changed = cd.diff_config(
        parse("# CONFIG_C is not set  # disabled on purpose"), parse("CONFIG_C=y"))
    check((added, removed, changed) == ([], [], [("CONFIG_C", "n", "y")]),
          "disabled -> enabled is 'changed', not 'added'")
    added, removed, changed = cd.diff_config(parse('CONFIG_STR="a#b"'),
                                             parse('CONFIG_STR="a#b"'))
    check((added, removed, changed) == ([], [], []),
          "a '#' inside a quoted value is not drift")
    _, _, changed = cd.diff_config(parse('CONFIG_STR="a#b"'), parse('CONFIG_STR="a#c"'))
    check(changed == [("CONFIG_STR", '"a#b"', '"a#c"')],
          "a real change after a '#' must still be reported")
    print("test_config_drift_parser OK")
