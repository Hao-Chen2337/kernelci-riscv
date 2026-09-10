# Upstream-evidence & project-review report (2026-09-09)

Verification performed live against api.github.com on 2026-09-09 (unauthenticated REST, HTTP 200 for every fetch). All raw JSON saved under 'my-work/evidence/upstream-evidence/' (list at the end).

## PART 1 - Verdicts on the previously-unverified claims

| # | Item | Claim in local docs | Verified reality (api.github.com) | Verdict |
|---|---|---|---|---|
| 1 | kernelci-project issue #579 | Open, by xjysiiau, 2026-08-21, body acts as SOW tracking board, 0 comments | Confirmed. Open, xjysiiau, created 2026-08-21T11:26:32Z, 0 comments. Body cites dev-partners#49 and repo xjysiiau/kernelci-riscv | OK |
| 2 | dev-partners issue #49 | 5 comments; Acidmoon 2026-08-24 calls #579 'the tracking issue'; last update 2026-08-24 -> 21-day clock 09-14 | Confirmed. 5 comments; exact Acidmoon wording exists; last comment gsterlin 2026-08-24T11:35:20Z (+21d = 2026-09-14) | OK |
| 3 | pipeline PR #1313 | nuclearcat, merged 2025-10-23; one review question answered with Google Doc + PoC node_id | Confirmed in substance. Merged 2025-10-23T14:02:22Z; 0 formal reviews; 3 issue comments (JenySadadia asked 2 questions in one comment; nuclearcat answered in two follow-ups) | OK (wording nuance below) |
| 4 | pipeline PR #1357 | zero review, merged 2025-11-06 | Confirmed. nuclearcat, merged 2025-11-06T16:50:47Z; 0 reviews/comments | OK |
| 5 | pipeline PR #1477 | zero review | Confirmed. bhcopeland, merged 2026-04-28T21:11:45Z; 0 reviews; 1 self-comment re depends | OK |
| 6 | pipeline PR #1509 | zero review, merged 2026-06-12 | Confirmed. gumulka, merged 2026-06-12T12:00:22Z; 0 reviews/comments | OK |
| 7 | kernelci-core PR #3008 | pull-only protocol PR, nuclearcat | Confirmed. Title 'runtime: Add Pull-Only labs runtime implementation'; merged 2025-11-06T16:50:57Z; 0 comments/reviews | OK |

Interpretation corrections / nuances
1. Doc 07/09 phrase 'one review question' for #1313 is slightly loose: it was one ISSUE COMMENT (not a formal review) by JenySadadia containing TWO questions, answered in TWO comments by nuclearcat (Google Doc at 2025-10-14T08:25:21Z, PoC node at 2025-10-14T08:27:54Z).
2. The upstream PoC node is 68d9148525e6e187e5a195cb (staging.kernelci.org:9000) - not to be confused with our local PoC nodes 6a9fb8bf... / 6aa11653....
3. #1477 merge date was blank in doc 07: online it is 2026-04-28T21:11:45Z.
4. Count the 21-day clock from gsterlin's comment (2026-08-24T11:35:20Z); same 09-14 deadline either way.

### 1. kernelci/kernelci-project#579 (verbatim core facts)

- Title: RISC-V Development Partners: local QEMU boot + kselftest pipeline seeking the upstream integration path
- Author: xjysiiau - State: open - Created: 2026-08-21T11:26:32Z - Comments: 0
- Body (full): Context states intern at KUBUDS Tech working on SOW https://github.com/riscv-admin/dev-partners/issues/49, repo https://github.com/xjysiiau/kernelci-riscv; pipeline = x86 host cross-build, QEMU virt '-cpu max', seeded openKylin image with '-snapshot', login-prompt detection, cpuinfo (Vector/Hypervisor) + RVV vector_add, riscv kselftests (10 binaries: 9 pass, 1 known XFAIL), 17-option config contract + config diff, cloud + self-hosted GitHub Actions. Known finding: abi/pointer_masking fails on ZPM-capable QEMU '-cpu max' (kernel resets PMLEN to 0, commit 3033b2b1e3). Questions: recommended RISC-V QEMU profile path; existing coverage to extend; interest in registering as pull lab. Status: Phase 1 done; Phase 2 done except real-hardware Hypervisor/KVM testing; aiming for a Phase 3 upstream PR.
- Local-doc match: yes (doc 02 description is accurate).

### 2. riscv-admin/dev-partners#49 (verbatim comments)

- Title: 'KernelCI: Statement of Work' - Author: gsterlin - open - created 2026-08-11T11:49:16Z - updated 2026-08-24T11:35:20Z - 5 comments.
- Body essentials: Version 1.0 / 2026-06-30 / Draft; problem statement = lack of consistent integrated continuous testing for RISC-V under mainline; 'Target Parent Community: KernelCI Community / Linux Kernel mainline'; AI usage permitted; Project Lead placeholder '[Name/Email]'; Phases 1-4 (setup/containerized pipeline/tracking issue/validation; core logic deployed + drift + regression on QEMU/Spike; formal PR to integrate the RISC-V test profile suite into mainline KernelCI; runbook/blog/demo/LF badges); Sunset: 21+ days of inactivity without milestone tracking updates.

Comment 1 - Acidmoon, 2026-08-17T10:01:01Z (verbatim, trimmed):
  Hi, I'm an intern at KUBUDS Tech, a RISC-V International member organization. I'm very interested in this KernelCI Statement of Work and would like to get involved... questions: is this SOW still open? who is the mentor/coordinator? recommended onboarding path? how to formally engage?

Comment 2 - xjysiiau, 2026-08-22T08:08:44Z (verbatim, trimmed):
  Update (2026-08-22): ... three fix experiments for the pointer_masking failure in our guest (kernel v7.2.0-rc7, QEMU -cpu max): 1. Test-side: passing PR_TAGGED_ADDR_ENABLE makes the test SIGSEGV (rc=139); 2. Kernel-side: remembering the rounded PMLEN without touching envcfg has no effect - PR_GET derives effective PMLEN from envcfg.PMM; 3. Conclusion: the test's expectation contradicts the kernel's documented semantics, so the test itself needs a rewrite (e.g. probing via a raw-syscall child). Logs/patches: https://github.com/xjysiiau/kernelci-riscv/tree/main/patches

Comment 3 - Acidmoon, 2026-08-24T11:31:01Z (verbatim, trimmed) - THE tracking-issue source:
  ## Update(2026-08-24): real-hardware (Lichee Pi 3A) validation is now running as the second target ... Status on real hardware (Lichee Pi 3A / SpacemiT K1, Bianbu 0.6, kernel 6.1.15): 1. cpuinfo ISA detection: PASS (rv64imafdcv_..., Vector present) 2. RVV vector test: PASS on real silicon, VLEN = 256 bits (vs 128 in QEMU) 3. Vector performance baseline: 4M-element add in ~36 ms 4. Repo: https://github.com/Acidmoon/kernelci-riscv-li3a ... Known boundaries: 1. K1 has no H (Hypervisor) extension -> KVM real-hardware tests impossible; 2. No ZPM -> abi/pointer_masking takes the SKIP path; 3. Board kernel is 6.1.15 (vendor BSP); 4. We're still very happy to hear from a mentor/coordinator on next steps and the upstream integration path (see the tracking issue at kernelci/kernelci-project#579).

Comment 4 - gsterlin, 2026-08-24T11:33:52Z (substantive part verbatim):
  Excellent and happy to hear! We are still working out who will lead this, but excited to get you involved. We have our next Dev Partners meeting tomorrow, and I will make sure to raise that there is interest in this projects.
  (rest is GitHub email-quote boilerplate of comment 1)

Comment 5 - gsterlin, 2026-08-24T11:35:20Z (substantive part verbatim):
  Thanks for the information! It sounds like we'll have plenty to talk about tomorrow for the Dev Partners meeting and the KernelCI SoW.
  (rest is GitHub email-quote boilerplate of comment 2)

- Is the 'tracking issue' interpretation correct? YES. Exact wording: '(see the tracking issue at kernelci/kernelci-project#579)'. Context: Acidmoon's hardware update ends by pointing mentor/coordinator next-steps to xjysiiau's #579. #579 remains xjysiiau's issue with 0 comments; gsterlin never responded to it.

### 3. kernelci/kernelci-pipeline#1313 (verbatim conversation)

PR: 'feat: Implementing pull-only labs' - nuclearcat - closed/merged 2025-10-23T14:02:22Z - base main <- head pull-labs - 1 commit, 5 files, +108/-16 - 0 formal reviews, 0 inline review comments - 3 issue comments; PR body is empty.

- JenySadadia, 2025-10-03T07:06:59Z (verbatim):
    Hi, thanks for this.
    Do we have any design doc for this?
    Also, did we get any results yet?
- nuclearcat, 2025-10-14T08:25:21Z (verbatim):
    > Do we have any design doc for this?
    Design doc (work in progress): https://docs.google.com/document/d/1Nbz79wrgIwKTadhIC543KkutHYsT64V0loaO9nYL8vk/edit?tab=t.0#heading=h.h7gixwvt75it
- nuclearcat, 2025-10-14T08:27:54Z (verbatim):
    https://staging.kernelci.org:9000/viewer?node_id=68d9148525e6e187e5a195cb
    example of pull-only lab PoC job definition (in artifacts)

Local-doc claim: nuclearcat/Collabora - PR JSON gives login 'nuclearcat' (org not in payload). 'Google Doc + PoC node_id' answer = accurate.

### 4-6. Pull-lab config PRs - zero-review claims

| PR | Title | Author | Merged | reviews | issue comments | inline comments |
|---|---|---|---|---|---|---|
| #1357 | labs: Add pull-only labs support and demo | nuclearcat | 2025-11-06T16:50:47Z | 0 | 0 | 0 |
| #1477 | pull-labs: add AWS EC2 platform and scheduler config | bhcopeland | 2026-04-28T21:11:45Z | 0 | 1 (self): 'This also depends on https://github.com/kernelci/kernelci-core/pull/3088 and https://github.com/kernelci/kernelci-pipeline/pull/1471' | 0 |
| #1509 | scheduler-pull-labs: add first pull lab for pengutronix | gumulka | 2026-06-12T12:00:22Z | 0 | 0 | 0 |

#1357 body: 'Depends-on: https://github.com/kernelci/kernelci-core/pull/3008. This PR implement new runtime, pull-only lab'. #1509 body: 'This is more of a test, that everything in the pipeline works. More boards will follow, as soon as it is validated.'

### 7. kernelci/kernelci-core#3008

- Title: 'runtime: Add Pull-Only labs runtime implementation' - nuclearcat - merged 2025-11-06T16:50:57Z - 3 files, +619/-45.
- Body: 'New PULL_LABS runtime for KernelCI that implements the Job Definition creation according to the PULL_LABS protocol specification: [gist] ... New files: kernelci/runtime/pull_labs.py - Main runtime implementation config/runtime/base/pull_labs.jinja2 - JSON job definition template ... RuntimePullLabs configuration class Properties: poll_interval, timeout, storage_name ... Registered in RuntimeFactory._lab_types as pull_labs'
- 0 issue comments, 0 reviews. Notable linkage: pipeline #1357 merged 5 seconds later with 'Depends-on: #3008'.

## PART 2 - Whole-project review (issues, ranked)

### 0. [CRITICAL - handover] Top-level repo /home/hao/kernelci-riscv is a git time-bomb

- 'git status --porcelain --untracked-files=all | wc -l' = 153,409 untracked files; my-work alone is 14 GB (14 GB in my-work/evidence/worker-out: rootfs/ext4 images, logs, job dirs; the empty venv-tuxrun and __pycache__ were removed on 2026-09-09).
- Top-level .gitignore ignores kernelci-*/ checkouts and tools/ but NOT my-work/, so 'git add -A' at the top level would try to stage ~14 GB / 153k files.
- Top-level tracked files also show 6 uncommitted deletions (.github/workflows/ci.yml, Dockerfile, README.md, config-drift-check.sh, run-kvm-tests.sh, run-tests.sh) - probably intentional cleanup, but they sit as unstaged deletions.
- Recommendation before handover (now applied): .gitignore covers 'my-work/evidence/worker-out/' and 'my-work/evidence/latest-runs/'; never run 'git add -A' at the top level.

### a. Working tree / lint / validate (kernelci-pipeline)

- git status: 5 modified = config/platforms.yaml, jobs-pull-labs.yaml, scheduler-pull-labs.yaml, pipeline-pull-labs.yaml, pyproject.toml (the 64-insertion PR1 diff); 5 untracked = doc/regression-tracking.md, src/config_drift.py, src/regression_tracker.py, tools/riscv_pull_worker.py, tools/tuxlava-kselftest-riscv.patch. Nothing staged.
- python3 tests/validate_yaml.py: exit 0, 'All yaml files are valid' (with local modifications).
- ruff check on the 3 untracked python files: 'All checks passed!'; ruff format --check: all already formatted.
- No stray .pyc/venv/logs are untracked inside kernelci-pipeline (gitignore covers *.pyc, *.log, data, .env). The only files an accidental 'git add -A' there would add are the 5 untracked text files above - all intended to stay out of PR1.

### b. PR1 diff consistency with upstream siblings

- Faithful clone: same anchors, kselftest-pull-labs.jinja2 template, collection riscv|kvm, platform qemu-riscv64 clones qemu-arm64 (arch riscv / cpu rv64,v=true / machine virt / memory 4G).
- 'kselftest.kvm' is already used upstream by job kselftest-kvm (config/jobs.yaml:2216-2221); 'kselftest.riscv' is new but follows the kselftest.<collection> convention. No registry to update: validate_yaml only checks presence of kcidb_test_suite, and send_kcidb only validates the KCIDB dot-path regex. Both names are schema-valid.
- Real difference vs the arm64 sibling: upstream qemu-arm64 kselftest uses the ...-nfsboot kbuild event; riscv PR reuses plain kbuild-gcc-14-riscv by design. This is the point a reviewer may probe - keep the scheduler comment's explanation in the PR body.

### c. Scheduler event kbuild-gcc-14-riscv and artifacts

- Exists in production config: scheduler.yaml:345-347 defines the event and it is consumed by baseline-riscv-broonie/clabbe/collabora (scheduler.yaml:335-360); k8s build entries at scheduler.yaml:814+.
- Job block jobs.yaml:1447-1455: image riscv64-kselftest-kernelci, defconfig defconfig, no fragments, no 'kselftest: disable'.
- kbuild.py builds kselftest by default and packages modules.tar.xz + kselftest.tar.xz; the pull-labs template only emits kselftest when node.artifacts.kselftest_tar_xz|gz exists. Local evidence plain riscv defconfig yields them: logs/job_retry.log:240 shows a real kbuild-gcc-14-riscv node event with artifacts modules, kselftest_tar_xz, kselftest_metadata_json; the storage dir for node 6a9693ad... contains kselftest.tar.xz, modules.tar.xz, Image.gz and its .config has CONFIG_MODULES=y, CONFIG_KVM=m, CONFIG_VIRTIO=y/BLK=y/PCI=y. (Local docker-runtime node, not re-verified against production api.kernelci.org which times out; same config/code path.)
- Caveat: CONFIG_KVM=m only confirmed for a local 6.18 kernel build from linux-local.git; re-verify on a current production riscv .config if the PR cites it as fact.

### d. Adding runtime/token pull-labs-riscv / kernelci-pull-labs-riscv

- In-repo naming locations are only config/pipeline-pull-labs.yaml (runtime + notify token) and config/scheduler-pull-labs.yaml (references). No central runtime-name registry; config loader merges all config yaml by top-level key, so nothing else in-repo.
- Deployment-side, outside this PR: kernelci.toml secret [runtime.pull-labs-riscv] runtime_token=...; scheduler started with --runtimes pull-labs-riscv; secret handed out-of-band to the lab -> PULL_LABS_CALLBACK_TOKEN.
- Code caveat: the pull-labs template renders 'callback_token_name | default(kernelci-pipeline-callback)' and no code path in these clones forwards runtime.notify.callback.token into the job definition (PullLabs.get_params adds no notify; only LAVA does, kernelci-core/kernelci/runtime/lava.py:429-431). Keep notify.callback.token to mirror upstream entries, but do not claim it becomes the job-definition token_name (matches the caveat already in docs 00/09).

### e. Doc audit (00/02/05/07 skim)

1. [HIGH] 05 still says PR1 should state result collection is pending upstream wiring and that results cannot be collected until then - superseded by 07/00/09 (upstream already has 1983 pass nodes via LAVA-compatible bodies). Drafting the PR description from 05 produces exactly the phrase docs warn against.
2. [HIGH] PR1 accounting inconsistent: 00/09(§0,§8) say 63 lines/4 config files, pyproject follows worker PR2; 02/05/09(§3,§6,§7) say 64 insertions/5 files incl pyproject. Reality: 64 insertions/5 files; the pyproject C901 hunk references tools/riscv_pull_worker.py which is not committed unless the worker is submitted. Decide: drop the pyproject hunk from PR1 or reconsider submitting the worker.
3. [MED] Worker-length history inconsistent across docs (779 -> 1008 -> 1040) plus stale line refs; 09 §11.3 should be canonical for handover.
4. [LOW] Evidence node ids differ between 00 §9 (6a9fb8bf..., 6aa00148...) and 09 §11.2 (6aa11653fa..., 6aa114effa...); all valid local artifacts, but do not mix node ids in the PR description.
5. [LOW] No further contradictions vs fetched PR data; #1477 author bhcopeland confirmed.

## Saved files (all fetched JSON, in my-work/evidence/upstream-evidence/)

issue-579.json, comments-579.json
issue-49.json, comments-49.json
pr-1313.json, issue-comments-1313.json, reviews-1313.json, review-comments-1313.json
pr-1357.json, issue-comments-1357.json, reviews-1357.json, review-comments-1357.json
pr-1477.json, issue-comments-1477.json, reviews-1477.json, review-comments-1477.json
pr-1509.json, issue-comments-1509.json, reviews-1509.json, review-comments-1509.json
pr-3008-core.json, issue-comments-3008-core.json, reviews-3008-core.json
(this report: verify-report-2026-09-09.md)

Total: 23 JSON files, all HTTP 200.
