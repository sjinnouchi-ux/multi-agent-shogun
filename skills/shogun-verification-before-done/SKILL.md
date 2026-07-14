---
name: shogun-verification-before-done
description: Require fresh, bounded evidence on the current revision before any Shogun completion claim. Use before commit, acceptance, deployment, merge, or reporting work done.
---

# Shogun verification before done

## Iron law

**No completion claim without fresh evidence that directly proves every acceptance criterion on the current revision.**

Confidence, a code review, a generator success message, yesterday's green run, and “only docs changed” are not substitutes for verification.

## Role ownership

- **Ashigaru runs** the exact required checks on the completed candidate and produces bounded, sanitized evidence.
- **Gunshi verifies** the evidence-to-criterion mapping, command scope, freshness, and failure/skip handling. Gunshi does not implement.
- **Oometsuke** performs targeted or final review of the integrated artifact and reports findings to Karo.
- **Karo alone accepts** the result, updates the dashboard, or routes follow-up. Karo must not turn a deadline into a verification exception.

Shogun reports only Karo-accepted state to the Lord and does not convert `in_progress` into done.

## Define the proof before running it

For each acceptance criterion, name the observable that would prove it and the exact command or bounded inspection that produces that observable. Karo derives required gates from the repository's canonical Primary Docs, CI configuration, and supported test entrypoints; Gunshi verifies that selection. The command must cover the affected public boundary, not merely a convenient internal unit. Record why the selected scope is sufficient and which broader repository-required gates also apply.

## Fresh evidence packet

Ashigaru records the [evidence packet](references/evidence-packet.md) for each check:

- acceptance criterion and observable;
- exact command and working scope;
- current revision plus whether the candidate tree is clean or the bounded diff identity;
- execution time after the last relevant change;
- exit status;
- pass, fail, and skip counts;
- compact sanitized result and artifact identity;
- any caveat, timeout, unavailable dependency, or uncovered boundary.

`SKIP=FAIL` for every required check. A timeout, filter that selects no tests, missing dependency, or unknown count is blocked work, not success.

Before and after the command, record the commit plus a hash of the bounded working-tree diff. If either identity changes during verification, discard the result. Evidence becomes **stale** when production source, test, configuration, generated input/output, dependency lock, or acceptance criterion changes after its command ran. If ownership of a changed file or its dependency impact is uncertain, treat it as relevant and re-run. Never reuse another revision's result.

For every built or generated artifact, bind its hash to the source candidate identity and the recorded build command. If deployment or publication is an acceptance criterion, retrieve the deployed artifact hash through an approved bounded check and require it to match the verified artifact; a source-tree pass does not prove that the same bytes were deployed.

## Generated output and documentation

For **generated output**, generated does not mean trusted. Re-run the canonical generator, verify deterministic or idempotent output, inspect the bounded diff, and run the lock/schema/consumer tests that establish consistency. A generator's exit zero alone proves only that the generator exited zero.

Documentation is executable guidance. Verify commands, links, anchors, paired-language structure, security statements, and any referenced generated inventory that changed. “Non-code” is not an exemption from relevant tests or Oometsuke review.

## Partial evidence

A focused pass may support a narrow diagnostic statement, but it cannot prove completion when broader required gates remain. Keep status `in_progress` and state exactly which criteria are proven and which are blocked. A three-minute deadline changes the status update, not the acceptance standard.

## Evidence boundary

Return only **bounded, sanitized evidence**. Use an allowlist: command identity, candidate hash, counts, exit status, criterion IDs, artifact hashes, and brief failure categories. Replace tokens, credentials, account/user identifiers, private paths/URLs, and unrelated payloads with typed redaction labels. Never paste raw secrets, authentication data, tmux panes, queue or report bodies, or raw logs. If sanitization would remove the proof, route a safe verification design through Karo rather than broadening access.

## Acceptance sequence

1. Ashigaru runs the proof packet after the last relevant change.
2. Gunshi checks freshness, scope, counts, criterion coverage, and unresolved failures.
3. Karo routes the integrated candidate to Oometsuke for required targeted/final review.
4. Oometsuke reports pass or actionable findings to Karo.
5. Karo accepts only when every criterion has fresh passing evidence and required review passes.

Any change made in response to Gunshi or Oometsuke invalidates affected evidence and returns to step 1.

Design-time pressure evidence is retained in the canonical repository and is intentionally excluded from the installed runtime package.
