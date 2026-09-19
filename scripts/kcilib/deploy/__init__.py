# SPDX-License-Identifier: LGPL-2.1-or-later
#
"""Deployment: what this machine prepares once and serves many times.

Not part of a run.  A run bakes or reuses what it needs (kcilib.run.bake); this
package is about the artifacts that outlive one run - the kernel Image this
deployment publishes for its own stack, and the record of which build that is.
It sits beside the run layer rather than in it, because a deployment has a
lifetime and a job does not.
"""
