#!/usr/bin/env python3
"""Render a tracked config template into the runtime file a deployment uses.

Why: kernelci loads its settings with a plain ``toml.load()`` that does not
expand environment variables, so a tracked file cannot say "the config next to
me" or "whatever API port this deployment picked" - it has to carry absolute
values.  Carrying them meant every clone silently read another deployment's
paths, and a second isolated stack could not even be told apart from the first.

Placeholders are written ``@NAME@`` and are replaced from ``--var NAME=VALUE``
plus ``KCI_ROOT`` (this checkout).  Values are NOT taken from the ambient
environment on purpose: an inherited variable of the same name would silently
satisfy a placeholder, and a template comment mentioning ``@SOMETHING@`` got
substituted from the environment during testing - which is exactly the kind of
invisible wrong value this script exists to prevent.  A name with no value is
an error, never something left in place.

    python3 scripts/render-local-config.py \\
        --template config/local-callback.toml \\
        --output work/local-callback.toml \\
        --var KCI_ROOT=/srv/kernelci-riscv
"""
import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TOKEN_RE = re.compile(r"@([A-Z][A-Z0-9_]*)@")


def render(text, values):
    """Substitute every @NAME@ in *text*; None when the template has none."""
    names = {match.group(1) for match in TOKEN_RE.finditer(text)}
    if not names:
        return None
    missing = sorted(name for name in names if not values.get(name))
    if missing:
        sys.exit(
            "no value for "
            + ", ".join(f"@{name}@" for name in missing)
            + " (pass --var NAME=VALUE or set it in the environment)"
        )
    return TOKEN_RE.sub(lambda match: values[match.group(1)], text)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--template",
        default=os.path.join(ROOT, "config", "local-callback.toml"),
        help="template to render (default: config/local-callback.toml)",
    )
    parser.add_argument(
        "--output",
        default=os.path.join(ROOT, "work", "local-callback.toml"),
        help="rendered file (default: work/local-callback.toml)",
    )
    parser.add_argument(
        "--var",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help="value for a placeholder; may be repeated",
    )
    args = parser.parse_args()

    values = {"KCI_ROOT": ROOT}
    for item in args.var:
        if "=" not in item:
            sys.exit(f"--var expects NAME=VALUE, got {item!r}")
        name, value = item.split("=", 1)
        values[name] = value

    if not os.path.exists(args.template):
        sys.exit(f"template not found: {args.template}")
    with open(args.template, encoding="utf-8") as handle:
        template_text = handle.read()
    rendered = render(template_text, values)
    if rendered is None:
        sys.exit(
            f"{args.template} contains no @NAME@ placeholder; refusing to "
            "render (it would keep whatever absolute values it carries)"
        )
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as handle:
        handle.write(rendered)
    print(f"OK  rendered {args.output} from {args.template}")


if __name__ == "__main__":
    main()
