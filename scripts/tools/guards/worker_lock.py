"""Two workers on one state file: the flock must refuse the second one."""
import os
import tempfile

from kcilib.core import config
from kcilib.run import jobrun, poll

from .support import _poll_config, check


def test_worker_lock():
    """#25: a second worker on the same state file must refuse to start.

    Two workers on one state file would each see half the queue and fight over
    the same workspaces and ports."""
    import fcntl

    with tempfile.TemporaryDirectory() as tmp:
        state_file = os.path.join(tmp, "state.json")
        # The file must stay open for the flock to be held (SIM115 deliberate,
        # as in poll_loop).
        holder = open(state_file + ".lock", "w")  # noqa: SIM115
        fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            poll_config = _poll_config(state_file)
            try:
                poll.poll_loop(poll_config, jobrun.run_node, config.RunConfig())
                check(False, "a second worker was allowed to start while the "
                             "lock was held")
            except SystemExit as exit_error:
                check(exit_error.code == 1, f"expected exit 1, got {exit_error}")
        finally:
            holder.close()
    print("test_worker_lock OK")
