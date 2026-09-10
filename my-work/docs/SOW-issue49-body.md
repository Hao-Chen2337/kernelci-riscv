# riscv-admin/dev-partners#49 SOW 原文快照(2026-09-09 在线复核)

> 来源: https://github.com/riscv-admin/dev-partners/issues/49 (GitHub API)
> title: KernelCI: Statement of Work | state: open | created: 2026-08-11T11:49:16Z | updated: 2026-08-24T11:35:20Z | comments: 5 | author: gsterlin
> 保存原因: 原缓存 /tmp/issue49.json 已丢失,此快照永久存档,供 SOW 逐句核对。

Version: 1.0 | Date: 2026-06-30 | Status: Draft

Executive Summary
Problem Statement: While RISC-V architecture specifications and software enablement profiles (like RVA23) continue to mature, the platform currently lacks consistent, integrated, and continuous testing under the mainline Linux architecture. Testing gaps persist for architectural side channels, extensions, and hardware behavior variance across early-adopter development boards.
Project Goal: Build out full, localized KernelCI automation support for RISC-V targets to enforce rigorous, upstream testing parameters that catch regressions across compilers, toolchains, and varying microarchitectures.
Target Parent Community: KernelCI Community / Linux Kernel mainline.
AI Usage/Expectation: AI tools are permitted to assist in building automation logic, test schemas, and localized documentation scripts without structural constraints.
Copyright/Patent Concerns: Delivered entirely open source under the standard regulatory framework and applicable licensing (e.g., Apache 2.0 / GPL-2.0).

Roles & Staffing
Project Lead (Mentor): [Name/Email]
Primary Contributor (Mentees): [Name/Email]
Stakeholder Sponsor: [Name/Department]
Estimated Effort: [e.g., 10 hours/week for 12 weeks]

Phased Build Plan

Phase 1
Setup & Initial PR
Local development containerized testing pipeline initialized. Initial tracking issue board established with parent community. First validation script successfully parsed locally.

Phase 2
Core Logic / Feature
Primary KernelCI execution logic deployed. Script automatically catches configuration drift and tests regression pass-rates for targeted extensions (e.g., Vector/Hypervisor) on a virtualized target (QEMU/Spike).

Phase 3
Upstream / Integration
Formal Pull Request submitted to the mainline KernelCI parent code base to integrate the RISC-V test profile suite.

Phase 4
Documentation & Demo
Comprehensive test execution runbook finalized. Technical blog post drafted for the developer community and demo recorded. Earnable LF Badges awarded.


Graduation & Exit Strategy
Select the intended path for this project upon completion:
[ ] Upstream: Merge test framework features directly into the core KernelCI code base or Linux Kernel tree.
[ ] Hand-off: Transition long-term maintenance and hardware-runner coordination to Ecosystem Lab Partners.
[ ] Incubate: Move toward a formal, long-term RISE / LF joint framework initiative.
[ ] Other: [Specify]


Maintenance & Support
Post-Graduation Owner: (Who looks after this code once the short-term sprint ends?)
Sunset Criteria: Project will be flagged for evaluation or archived if it is unable to produce functioning validation results, or suffers from 21+ days of inactivity without milestone tracking updates.


Recognition & Badging
Earnable Badges for this SOW:
Earnable Badges for this SOW:
[ ] First PR Milestone
[ ] Upstream Navigator
[ ] STIP Graduate
Publicity Plan: (e.g., "Feature on RISE blog," "Presentation at RISC-V Summit")

