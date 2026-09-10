#!/usr/bin/env python3
"""Render config/local-callback.toml into a deployment-local settings file.

Why: kernelci reads its settings with a plain ``toml.load()`` that does not
expand environment variables, so a tracked TOML file cannot say "the config
next to me" - it has to carry absolute paths.  Carrying one machine's checkout
paths (the previous state: three absolute entries naming a single home
directory) made every clone silently read another deployment's YAML config and
SSH key.

So the tracked file is a template using ``@KCI_ROOT@``, and this script writes
a concrete copy under ``work/`` (gitignored) at stack time.

    python3 scripts/render-local-config.py                 # -> work/local-callback.toml
    python3 scripts/render-local-config.py --output /tmp/x.toml
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PLACEHOLDER = "@KCI_ROOT@"


def render(template_text, output_path, root):
    rendered = template_text.replace(PLACEHOLDER, root)
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as handle:
        handle.write(rendered)
    return rendered.count(root)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--template",
        default=os.path.join(ROOT, "config", "local-callback.toml"),
        help="settings template (default: config/local-callback.toml)",
    )
    parser.add_argument(
        "--output",
        default=os.path.join(ROOT, "work", "local-callback.toml"),
        help="rendered settings file (default: work/local-callback.toml)",
    )
    parser.add_argument(
        "--root",
        default=ROOT,
        help=f"value substituted for {PLACEHOLDER} (default: this repository)",
    )
    args = parser.parse_args()

    if not os.path.exists(args.template):
        sys.exit(f"settings template not found: {args.template}")
    with open(args.template, encoding="utf-8") as handle:
        template_text = handle.read()
    if PLACEHOLDER not in template_text:
        sys.exit(
            f"{args.template} has no {PLACEHOLDER} placeholder; refusing to "
            "render (it would keep whatever absolute paths it carries)"
        )
    count = render(template_text, args.output, args.root)
    print(f"OK  rendered {args.output} ({count} path(s) -> {args.root})")


if __name__ == "__main__":
    main()
