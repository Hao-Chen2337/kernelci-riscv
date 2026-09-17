# SPDX-License-Identifier: LGPL-2.1-or-later
#
"""One build -> the tests to run: a table row, and the executor's definition.

JobSpec is a row of the table (build_id, test, timeout_s) with no callback URL,
which is only known at run time. JobDefinition is what run_node receives, shaped
exactly like the upstream pull_labs.jinja2 render, so run_node cannot tell ours
from the API's; a callback section decides report-back versus ledger only.
"""

from dataclasses import dataclass

from kcilib.table.buildref import build_ref_from_node

# The three tests this configuration claims: the three runtime=pull-labs-riscv
# entries of config/scheduler-pull-labs.yaml (3 of that file's 44).
DEFAULT_TESTS = ("boot", "kselftest-riscv", "kselftest-kvm")

# Default timeout per test: boot only starts the kernel, the two kselftest sets are long runs.
TEST_TIMEOUTS = {
    "boot": 600,
    "kselftest-riscv": 1800,
    "kselftest-kvm": 1800,
}

PLATFORM = "qemu-riscv64"
ARCH = "riscv"


@dataclass
class JobSpec:
    """One row of the table: a build x a test.

    Deliberately three fields - this is intent, not instructions.
    """

    build_id: str
    test: str
    timeout_s: int = 0
    build: object = None                # BuildRef; held aside so as_row() names ids only

    def __post_init__(self):
        if not self.timeout_s:
            self.timeout_s = TEST_TIMEOUTS.get(self.test, 1800)

    def as_row(self):
        return {"build_id": self.build_id, "test": self.test,
                "timeout_s": self.timeout_s}


def jobs_from_build(build, tests=None, timeout_s=None):
    """★ One build -> N JobSpecs. Pure: no network, no disk, no test run.

    *build* may be a BuildRef or a full node dict, deliberately: a self-made node
    has no queryable id, and taking either treats both sources alike. Returns
    (specs, skipped); a test with a missing artifact is skipped and the reason
    recorded, never dropped silently.
    """
    tests = tuple(tests) if tests else DEFAULT_TESTS
    if not hasattr(build, "missing_for"):
        build = build_ref_from_node(build)
    specs, skipped = [], []
    for test in tests:
        missing = build.missing_for(test)
        if missing:
            skipped.append((test, f"missing artifact(s): {', '.join(missing)}"))
            continue
        specs.append(JobSpec(
            build_id=build.build_id,
            test=test,
            timeout_s=timeout_s or 0,
            build=build,
        ))
    return specs, skipped


def test_of(definition):
    """A definition -> the test it asks for (tests[0].type, then id, then boot).

    One place owns "what is this job called": the ledger files rows under it.
    """
    tests = definition.get("tests") or [{}]
    first = tests[0] if isinstance(tests[0], dict) else {}
    return first.get("type") or first.get("id") or "boot"


def job_definition(spec, callback_url=None, token_name=None):
    """★ JobSpec -> the definition handed to run_node. Pure.

    *callback_url* is the sink switch: with it the run reports back, without it
    only the ledger is written. It lives here rather than on JobSpec because the
    listing stage does not know where results would go (local stack, production).
    """
    build = getattr(spec, "build", None)
    if build is None:
        raise ValueError(
            f"JobSpec {spec.build_id}/{spec.test} carries no build; specs come "
            "from jobs_from_build(), which keeps a reference to it")
    test = spec.test
    definition = {
        "artifacts": dict(build.artifacts),
        "tests": [{
            "id": test,
            "type": test,
            "depends": [],
            "timeout_s": spec.timeout_s,
            "pre-commands": [],
            "post-commands": [],
        }],
        "environment": {
            "platform": PLATFORM,
            "arch": ARCH,
            "console": {"method": "serial", "baud": 115200},
        },
    }
    if callback_url:
        definition["callback"] = {
            "url": callback_url,
            "token_name": token_name or "kernelci-pipeline-callback",
        }
    return definition
