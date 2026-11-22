# AuthOps design: what it models and why

AuthOps is a portfolio-scale rebuild of the operating system behind AI prior-authorization
agents: documents in, validated cases out, submitted through whichever channel a payor
offers, with experiments, QA and metrics around every agent. All payors, providers and
patients are fictional. Nothing here touches a real portal or real PHI.

## 1. Research basis

Public engineering write-ups on prior-authorization automation (2026) describe four systems
that production teams run. Each maps to a module here.

| System (public write-ups) | What is described | AuthOps module |
|---|---|---|
| Autonomous Browser Agents (Feb 2026) | Playwright over CDP in isolated Kasm containers; in-house durable "Pipelines" on Dramatiq + Postgres where each inference and tool call is a step; windowed context; priority scheduling; credential pooling with leases; TOTP and email-OTP handling; 50-turn cap; smoothness score; verification of downloaded approval letters | `agent/runtime.py`, `agent/tools.py`, `agent/credentials.py`, `ops/store.py`, `ops/scoring.py` |
| Beyond the Agent: AI Operations (May 2026) | Per payor x specialty configuration; sandbox backtests; model chosen per portal on cost, context, intelligence and speed; Experiments platform splitting auto-submit vs human QA and model arms (e.g. Haiku-4.5 vs GPT-5.4); failure modes: hidden pop-ups, concurrency limits, upload rules, non-standard UI, conditional forms, lockouts, context bloat, session drift; 0-100 insight signal | `portals/app.py` (sandbox with those failure modes), `ops/experiments.py`, `agent/policy.py`, `playbooks/` |
| Phone Agents (Apr 2026) | Twilio, Deepgram STT with keyword boosting, LLM, text normalization, ElevenLabs TTS; IVR/DTMF; interruption handling; ordered event timeline; eval and A/B still to be built | `phone/ivr.py` |
| Document Validation (Jun 2026) | Rules engine of boolean predicates; default rules in code (expiry, ICD-10), custom rules in natural language answered yes/no by an LLM; configurations as a gated graph; Pydantic schemas; chunk, extract in parallel, synthesize; payor requirements database | `validation/rules.py`, `configs/payor_requirements.yaml`, `docintel/extract.py` |

## 2. Where the market is going, and the bet this repo makes

CMS-0057-F requires impacted payors (Medicare Advantage, Medicaid, CHIP, QHPs on the
federal exchanges) to run four FHIR APIs, including a Prior Authorization API, by
January 1, 2027. Decision time limits (72 hours urgent, 7 days standard) have applied since
January 1, 2026.

Two consequences shape the design:

1. **Channels multiply rather than switch.** Commercial plans outside the rule, late
   implementations and out-of-scope services (drugs) keep portals, fax and phone alive for
   years. `channels/router.py` routes each case FHIR first, portal agent second, phone
   third, and the same validation and QA sit in front of all three.
2. **The value moves upstream.** Once submission is an API call, the hard part is
   submitting a complete, correct request the first time. That is the rules engine plus
   extraction, and it is why validation runs before any channel.

Published next steps in the field also point upstream: background document agents that loop
with tools instead of one-shot calls, and automating agent configuration itself. The playbook format here (plain-English `.md` for
people and the LLM, structured `.yaml` for the deterministic policy) is the input such a
configuration generator would produce and test.

## 4. Safety and data handling choices

- Credentials are injected by tools (`type_credential`, `enter_totp`) and never enter a prompt.
- Every extracted field carries quoted evidence; evidence not found in the OCR text caps confidence.
- Fields below the confidence threshold abstain and route to a human: a blank field is cheaper than a wrong one.
- LLM yes/no rules are cast strictly; any answer that is not YES or NO is "could not evaluate", never a pass.
- The agent may only call tools on its portal's allow-list, is capped at 50 turns and a wall-clock budget, and stops hard after submission.
- Consecutive login failures disable a credential before the portal locks it.
- Synthetic data only. A real deployment would add a BAA with the model provider, zero data retention, row-level security per provider and session recording.

## 5. Metric definitions

| Metric | Definition | Why it matters |
|---|---|---|
| Field accuracy | correct fields / all fields (abstain counts as wrong) | overall usefulness |
| Precision when answered | correct / answered | how far to trust a filled field |
| Silent error | answered and wrong / all fields | the error that reaches a payor |
| Docs fully correct | docs with every critical field right | what auto-submit needs |
| Verified submit rate | runs that submitted and whose confirmation matched patient, member and CPT | outcome |
| Smoothness (0-100) | 100 minus explicit penalties for retries, guards, drift, loops, invalid actions, credential swaps, extra steps, timeouts, verification mismatch | execution quality separate from outcome; low scores go to review |
| QA share | share of runs routed to human QA per portal; lowered only while success, smoothness and audited silent errors hold | the auto-submit ramp |
| Denial catch recall | payor denials flagged by validation before submission / all payor denials | first-pass acceptance |

## 6. Known limits (stated, not hidden)

- The sandbox portals are built by the same person who wrote the agent. Passing them shows the
  controls work. It does not prove the agent would handle an unseen real portal. Lakeshore is held
  out (no hand-written playbook) and auto-config drafts a working playbook for it, but the same
  person wrote Lakeshore and the label lexicon. The Claude label mapper (no lexicon) is the fairer
  test, and a real unseen portal is the only real one.
- The playbook policy is deterministic (RPA with recovery). It is the baseline, not the "AI".
- Rendered documents are cleaner than real faxes: no handwriting, no stamps, no multi-column scans.
- The requirements database is tiny and fictional. One hidden payor policy change is planted on
  purpose to show requirements drift as a source of missed denials.
- The phone agent is text only. No STT/TTS latency, barge-in or audio quality is modeled.
