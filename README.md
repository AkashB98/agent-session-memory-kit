# agent-session-memory-kit

**Compress finished agent session logs into durable memory cards, supersede the stale ones, and inject the right cards into the next session under a strict token budget — with retrieval quality measured, not vibes: recall@3 = 1.0 and precision@3 = 1.0 on a planted corpus, a token budget that is never exceeded in a 0–200 sweep, and a staleness eval proving a superseded card is never injected.**

Every long-running agent re-learns the same facts each session, or worse, acts on a fact that stopped being true last week. This project is the small, inspectable version of the memory layer: session logs (JSONL) go in, JSON memory cards come out, and the next session gets a ranked, budget-capped injection block — not a dump of everything the agent ever said. This work was inspired by the claude-mem trend; independent stdlib implementation focused on measurable retrieval quality. Nothing here copies that project's structure, naming, or features.

> **Synthetic data only.** Every session log is fabricated for a fictional smart-home company (**Helios Home**) and its support agent. No real company, customer, or agent data is used anywhere in this project.

Stdlib-only Python — deliberately. There are **no embeddings, no vector database, no decay curves, and no LLM path**: extraction is one deterministic rule-based strategy, ranking is TF-IDF-style term scoring, and the same input always produces byte-identical outputs, so every number below can be re-run offline and checked.

## Quickstart

```bash
# 1. Ingest session logs into a card store (one JSON file per card)
python3 cli.py ingest fixtures/session_helios-001.jsonl \
                      fixtures/session_helios-002.jsonl \
                      fixtures/session_helios-003.jsonl --cards-dir cards_store
python3 cli.py ingest            # bundled fixtures, in memory

# 2. List cards (active only, or everything including superseded)
python3 cli.py cards --cards-dir cards_store
python3 cli.py cards --cards-dir cards_store --include-superseded

# 3. Rank cards for a new session's query
python3 cli.py retrieve --query "router firmware version" --cards-dir cards_store

# 4. Build the injection block under a strict token budget
python3 cli.py inject --query "router firmware version" --budget 60 --cards-dir cards_store

# 5. CI gate: exit 0 = store valid, 1 = violations, 2 = IO error
python3 cli.py check --cards-dir cards_store; echo $?   # 0 on the fixtures

# 6. One-command end-to-end demo (ingest -> retrieve -> inject -> serve)
python3 demo.py

# 7. Tiny localhost API: POST /retrieve, GET /health on 127.0.0.1
python3 cli.py serve --port 8765
curl -s -X POST localhost:8765/retrieve -d '{"query": "router firmware version", "k": 3}'
```

## The fixture sessions at a glance

Three fictional Helios Home sessions (15 log events) compress to **12 cards — 11 active, 1 superseded**: 5 facts, 3 decisions, 2 open items, 2 errors. The story the evals pin: session 1 records *"router firmware version is 2.4.1"*; session 2, a week later, records *"…is 3.0.0"*. Same subject, newer card — the 2.4.1 card is retained, marked superseded, and can never be retrieved or injected again. Session 1 also plants an email address and a key-like token in a support note; the PII guard redacts both before any card exists.

## How it works

**One extractive strategy.** An event becomes a card only when it carries an explicit cue — `Fact:` / `Confirmed:` / `Note:` → fact, `Decision:` / "decided to" / "chose to" → decision, `TODO:` / "still need to" → open item, `Error:` / an error-typed event → error (priority: error > open item > decision > fact). Chatter produces no card. The card text is the redacted source sentence, verbatim — extractive, never paraphrased — so a card can always be traced to `source_index` in its session log.

**Supersession.** Each card carries a `subject_key`: the first three content words of the cleaned statement (alphabetic tokens, cue phrases and stopwords removed — e.g. both firmware statements land on `router-firmware-version`). Within a subject key the newest card by `(created_at, card_id)` is the only active one; older cards are **retained, marked `superseded`, and point at their winner via `superseded_by`** — and retrieval/injection filter them out unconditionally. Staleness is a data property, not a ranking hope.

**Retrieval.** TF-IDF-style scoring over active cards only: term frequency in the card (kind + subject key + text) × smoothed inverse document frequency, `ln((1+N)/(1+df)) + 1`. Results sort by score descending, ties break on `card_id`, and only score > 0 results return — so the same query over the same store always returns the same list, in the same order.

**Token budget.** One estimator everywhere: `estimate_tokens(text) = ceil(words × 1.3)`, words = whitespace-separated tokens. Injection walks the ranking greedily: a card whose rendered line (`- [kind] text`) fits the remaining budget is included; an oversized card is skipped and smaller lower-ranked cards may still fit. `used_tokens` is the sum of the included lines' estimates and is guaranteed `≤ budget` — the evals sweep budgets 0–200 across four queries and the budget is never exceeded.

**PII guard.** Before a card is saved, a small built-in redaction pass replaces emails and key-like tokens (`sk-…`, `ghp_…`, `AKIA…`, `api_key=…` assignments, long hex strings) with `[REDACTED:email]` / `[REDACTED:key]` markers, and records the kinds redacted on the card. In production this step delegates to the sibling **tool-output-pii-redactor** project (streaming scrubbing, allowlists, hash-chained audit); the standalone regex pass is here so this repo is self-contained, and the `check` gate fails any store whose card text still contains a match.

## Architecture

| Module | Job |
|---|---|
| `extract.py` | The one extraction strategy: cue classification (decision / fact / open_item / error), subject-key derivation, deterministic card ids, PII guard applied at extraction time |
| `cards.py` | Card schema + validation, supersession resolution (newest per subject key wins, older retained and marked), canonical JSON file store (one file per card, no database) |
| `redact.py` | The standalone PII guard: email + key-like-token regexes, idempotent markers, `find_pii` for the check gate |
| `retrieve.py` | Tokenizer, TF-IDF-style scoring over active cards, card_id tie-break, the `ceil(words × 1.3)` token estimator, greedy budgeted injection, recall/precision@k helpers |
| `sessions.py` | JSONL session-log loading + the ingest pipeline (extract → supersede → optionally save) and fixture access |
| `cli.py` | `ingest` / `cards` / `retrieve` / `inject` / `check` (CI exit 0/1/2) / `demo` / `serve` (stdlib `http.server` on 127.0.0.1: `POST /retrieve`, `GET /health`) |
| `demo.py` | End-to-end narrative with asserts: determinism, supersession, PII guard, retrieval headline, 60-token injection, check exit codes, live localhost serve round-trip |
| `fixtures/` | Three fictional Helios Home session logs (JSONL): the firmware supersession pair and the planted email + key |

## Evals

`python3 evals/run_evals.py` → **13/13 golden evals**, report committed at `evals/eval_report.json` (md5 `3bad9e7c457bf12b450c8f2dea17614f`, byte-identical across 3 verified runs):

- **E1–E3** fixture ingest pinned (15 events → 12 cards; kinds fact 5 / decision 3 / open_item 2 / error 2; the firmware pair shares `router-firmware-version`)
- **E4** PII guard — the planted email and key appear in no saved card; the support card records `redactions: ["email", "key"]`
- **E5** retrieval quality headline — **recall@3 = 1.0, precision@3 = 1.0** on an 8-card planted corpus (3 relevant, 5 irrelevant) for *"router firmware version hallway"*
- **E6** recall@2 = 0.6667, precision@2 = 1.0 — partial recall at a smaller k, by construction
- **E7** tie-break determinism — two planted cards score identically (9.054651); reversing the corpus changes nothing
- **E8** token budget — sweep of budgets 0–200 over four queries never exceeded; the pinned 60-token fixture injection uses exactly 36
- **E9** staleness — the superseded 2.4.1 card is never retrieved or injected, including for the query *"router firmware 2.4.1"* itself
- **E10** token estimator pinned (`""` → 0, 1 word → 2, 3 words → 4, 10 words → 13)
- **E11** CLI `check` exit codes 0 / 1 / 2 (clean store / PII-tainted store / missing store)
- **E12** serve round-trip matches local retrieval exactly
- **E13** ingest determinism — canonical card bytes pinned by md5 (`ea1488ea55eb6b81323bcc505582ff6f`)

Unit tests: `python3 -m unittest discover -s tests` → **55 hermetic tests**, including a no-network enforcement test (sockets stubbed), supersession generations and timestamp ties, idempotent redaction, the budget sweep, CLI exit codes, and serve round-trips.

## Development loop — what the checks actually caught

1. **The PII guard flagged its own output.** When the fixture's planted secret changed from an `sk-…` token to assignment form (`api_key=…`), the redacted card text — `api_key=[REDACTED:key]` — matched the assignment pattern again, so `check` failed a perfectly clean store and the demo broke at the gate stage. The redactor was not idempotent for assignment-form secrets, exactly the case the idempotence test hadn't covered (it only exercised the `sk-…` form). Fixed by making the assignment pattern refuse a value that is already a redaction marker, pinned by a regression test; a redactor that cannot recognise its own markers will eventually fail every store it touches.
2. **Two planted cards tie at exactly 9.054651, and that tie is load-bearing.** The reboot decision and the update fact share the same query-term profile for *"router firmware version hallway"*, so ranks 2 and 3 are decided entirely by the tie-break. Sorting by score alone would leave their order to corpus order — the same store loaded from a differently-ordered directory could inject in a different order. The ranking now sorts by `(-score, card_id)`, and E7 pins it by retrieving from the reversed corpus and demanding identical output; a unit test pins the same property on a synthetic pair.
3. **Version numbers would have split the supersession key.** The obvious subject-key recipe — first three tokens of the statement — turns *"router firmware version is 2.4.1"* and *"…is 3.0.0"* into different keys once the version digits land inside the first tokens of a differently-phrased update, and the stale card would stay active forever. Subject keys therefore use alphabetic tokens only, so numbers can never split a topic; `test_firmware_variants_share_key` and E3 pin the pair to one key.
4. **Precision@k needs its denominator stated, or the headline lies by omission.** A query can legitimately return fewer than k results (only score > 0 cards return — *"thermostat night schedule"* returns exactly 1). This repo defines precision@k as hits ÷ k and recall@k as hits ÷ |relevant|, says so in `retrieve.py`, and pins a partial-recall case (E6) alongside the perfect headline (E5) so both numbers stay honest.

## Scope and honest limits

- **Cue-based extraction only hears explicit statements.** A decision phrased without any cue phrase ("Let's go with the 2.4 band, then") produces no card. That is the price of a deterministic, auditable extractor — and the reason the card text stays verbatim instead of paraphrased.
- **Subject keys are topics, not propositions.** Two complementary facts whose first three content words coincide will supersede each other even if they don't strictly contradict. Finer keys (or a contradiction check) are the obvious next step; the current rule is deliberately simple and its failure mode is visible in the store.
- **TF-IDF is lexical.** A query that shares no terms with the right card ("how do I reach the network box?") retrieves nothing. There is deliberately no embedding fallback in this repo — the point is a retrieval layer whose misses are explainable from the scores.
- **The PII guard is a backstop, not a product.** Two pattern families, no allowlist, no audit log — production use delegates to `tool-output-pii-redactor`, as documented in `redact.py`.
- **The API is a demo surface.** It binds 127.0.0.1 only, holds its cards in memory, and resets on restart.

## Why this project

Memory is where agent demos quietly become agent incidents: yesterday's fact, injected with full confidence, after it stopped being true. This project treats agent memory the way a forward-deployed engineer has to treat it in front of a customer — compression you can audit line by line, staleness resolved as data rather than hoped away by ranking, a token budget enforced as an invariant, and retrieval quality stated as recall/precision numbers with the evals to re-check them.

## License

MIT — see LICENSE.
