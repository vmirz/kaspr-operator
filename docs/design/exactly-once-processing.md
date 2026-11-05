# Design: Exactly-Once Processing for Kaspr Apps

> **Status:** Proposal
> **Date:** 2026-11-05
> **Scope:** twm-faust (transactions, buffers, commit), Kaspr (manual ack, settings), optionally aiokafka.
> **Follows:** twm-faust `commit-after-delivery` (at least once, no loss).

---

## Table of Contents

1. [Summary](#summary)
2. [What exactly once covers](#what-exactly-once-covers)
3. [Where Kaspr apps stand](#where-kaspr-apps-stand)
4. [Design](#design)
5. [Failure modes](#failure-modes)
6. [Costs and tradeoffs](#costs-and-tradeoffs)
7. [Alternatives considered](#alternatives-considered)
8. [Plan](#plan)
9. [Open questions](#open-questions)

---

## Summary

- Every Kaspr app runs `processing_guarantee="exactly_once"` (`kaspr/app.py`), but twm-faust produces every
  message outside transactions. Its transactions carry only the input offsets.
- `commit-after-delivery` makes processing at least once without loss: an offset is committed only after
  everything its processing sent is delivered. After a crash, records since the last commit are processed
  again: their outputs are duplicated, and their table updates are applied twice.
- This design puts each input partition's outputs, table changelog writes and offsets in one Kafka
  transaction. Readers with `isolation.level=read_committed`, including Kaspr's own table recovery, then see
  each record's effects exactly once.
- Recommendation: transactions per input partition (EOS v1), using the per-partition transactional producers
  twm-faust already creates. A single producer per worker (EOS v2, KIP-447) needs aiokafka work, and is a
  later step.

## What exactly once covers

The effects of processing one input record:

| Effect | Example | Covered |
|---|---|---|
| Messages to output topics | Agent `output.topics`, `topicSend` | Yes |
| Table changelog writes | `table[key] = value` in an agent | Yes |
| A key join's internal messages | Subscription, response topics | Yes |
| The input offset | Consumer group commit | Yes |
| External side effects | HTTP calls, object store writes | No: make them idempotent |
| Messages sent outside processing | Web views, timers, tasks | No: they have no input offset |

## Where Kaspr apps stand

Measured on twm-faust 1.17.25, aiokafka 0.15.0, Kafka 4.1.1: a worker copying 200,000 records is SIGKILLed
6–8 times while processing. Its output topic is read with read_uncommitted.

| Code | Records lost | Records output more than once |
|---|---|---|
| master | 1,752 / 2,611 / 1,369 (three rounds) | 9,407 / 13,486 / 18,598 |
| `commit-after-delivery` | 0 / 0 / 0 | 6,582 / 42,079 / 43,458 |

Why the guarantee is weaker than its name:

- `MultiTXNProducer._transactional_id_or_default` returns `None`
  (`faust/transport/drivers/aiokafka.py`, since 8c8cb673), so every send goes to the default,
  non-transactional accumulator.
- `TransactionManager.send` (`faust/transport/consumer.py`) picks the transactional id of the message's
  **destination** partition. The transaction a message belongs to is its **source** record's, which is
  probably why routing was turned off.
- `ProducerBuffer` (`send_soon`: table changelogs, join messages) is one queue for the app, and knows nothing
  of transactions.
- Kaspr's consumers already read with `read_committed` under exactly once (`aiokafka.py`, the consumer
  thread's `isolation_level`), so turning transactions on changes nothing on the read side.
- aiokafka 0.15 sends `TxnOffsetCommit` v0 only: no consumer group metadata, so KIP-447 fencing is not
  available.

Kaspr also has a manual ack ordering gap under any guarantee:

- With `noack: true`, `event.ack()` inside a map runs before the pipeline sends the map's outputs: the
  processor sends them after the operation returns, across several awaits. A commit in between commits the
  record before its outputs are sent, and a crash then loses them.

## Design

### One transaction per input partition

Faust already starts a transactional producer per active (topic group, partition) on assignment, with the
id `{app_id}-{group}-{partition}` (`TransactionManager._tps_to_transactional_ids`). Keep that, and route
messages to it.

| Message | Transaction |
|---|---|
| `topic.send()` while processing a record | The record's `(group, partition)`, from `current_event().message.tp` |
| `send_soon()` while processing a record (changelogs, joins) | The same, recorded on the `FutureMessage` at `send_soon` time (as `during_processing` is now) |
| A join result's downstream sends | The response's partition: the result event carries the response message |
| Sent outside processing (web views, timers, tasks) | None: the default producer, as today |

Changes in twm-faust:

1. `Topic.send_soon` and `Topic.publish_message` resolve the transactional id from the source record,
   not from the destination partition, and pass it to `Producer.send`.
2. `MultiTXNProducer` sends a message with a transactional id to that transaction's accumulator.
3. `ProducerBuffer` keeps pending messages per transactional id, so a commit drains only its own.
4. Remove the destination-partition routing in `TransactionManager.send`.

### Commit

At each commit, per transactional id:

1. Drain its buffered messages into its accumulator.
2. `send_offsets_to_transaction(offsets of its partitions, group_id)`.
3. `commit_transaction()`: aiokafka first flushes the transaction's batches (`flush_for_commit`).
4. `begin_transaction()`.

`commit-after-delivery`'s `wait_delivered` stays for messages sent outside transactions.

### Rebalance and fencing

- Revoked partitions: drain and commit their transactions before the revoke returns, then stop their
  producers. Faust's revoke path already waits for in-flight records (`wait_empty`).
- Assigned partitions: `init_transactions` with the partition's transactional id fences a zombie (the epoch
  goes up) and aborts its open transaction. A record the zombie processed is then processed again, and only
  this transaction's copy is committed.
- Standby replicas: no producers.

### Readers

- Kaspr consumers, table recovery and the join's internal topics: `read_committed` already.
- External consumers of Kaspr output topics must set `isolation.level=read_committed`. With
  read_uncommitted they also see aborted messages: duplicates, as today.

### Kaspr

- **Deferred manual ack:** `event.ack()` on the record being processed takes effect after the pipeline has
  sent that record's outputs. An ack of an earlier record takes effect at once.
- **Commit interval:** outputs become visible at commit, so each hop waits up to `BROKER_COMMIT_INTERVAL`
  (2 s today). A join result crosses three hops: up to about 6 s. Add a setting for the interval under
  exactly once, with a default of 0.5 s or less, to be measured.
- **Rollout setting:** transactional sends behind a setting (e.g. `K_TRANSACTIONAL_SENDS`) until validated,
  then on by default.

## Failure modes

| Failure | Result |
|---|---|
| Crash or SIGKILL mid-transaction | The transaction aborts (fenced at restart, or after `transaction.timeout.ms`); its records are processed again; readers see one committed copy |
| A send fails | Abort the transaction and crash; the records are processed again |
| Processing a record takes longer than `transaction.timeout.ms` (60 s) | The broker aborts the transaction; the commit fails; the app crashes. Agents with slow external calls need a longer timeout |
| Zombie after a network partition | Fenced by the epoch bump; its writes are aborted |
| Reader with read_uncommitted | Sees aborted copies: duplicates |
| Table written outside processing (`update_for_partition` from a web view or task) | Non-transactional; open question 3 |

## Costs and tradeoffs

| | At least once (`commit-after-delivery`) | EOS v1 (this design) | EOS v2 (KIP-447) |
|---|---|---|---|
| Duplicates after a crash | Yes | No, for read_committed readers | No |
| Table updates re-applied after a crash | Yes | No | No |
| Output visible | When delivered | At commit | At commit |
| Latency per hop | Milliseconds | Up to the commit interval | Up to the commit interval |
| Producers per worker | 1 | 1 + 1 per active (group, partition), e.g. 3 groups × 12 partitions = 37 | 1 |
| Broker work per commit | Offset commit | AddOffsetsToTxn, TxnOffsetCommit, EndTxn and a marker per partition, per producer | The same, from one producer |
| aiokafka | As is | As is (`TxnOffsetCommit` v0) | `TxnOffsetCommit` v3 and consumer group metadata, upstream |

## Alternatives considered

| Alternative | Why not now |
|---|---|
| Stay at least once and document idempotent consumers | Tables with read-modify-write updates (counters, sums) double count after every crash; the guarantee's name stays wrong |
| EOS v2 (one producer per worker) | Needs aiokafka changes first; the per-partition producers already exist in twm-faust |
| Transactions only for changelogs | Outputs still duplicate; the same routing work |
| Deduplicating consumers (sequence numbers in headers) | Every consumer must cooperate, Kaspr's own included |

## Plan

| Phase | Work | Done when |
|---|---|---|
| 0 | Harness: podman SIGKILL loop with a read_committed output count (exactly N, no duplicates), a table counter invariant (sum of increments = inputs), a join probe on a test cluster (stop, rebalance, kill) | Fails on `commit-after-delivery` for duplicates, passes its loss checks |
| 1 | twm-faust: source-partition routing (send, send_soon, changelogs), per-transaction buffers, commit and abort paths, revoke and assign; unit tests | Harness passes locally |
| 2 | Kaspr: deferred manual ack, commit interval setting, rollout setting; kaspr-docs: read_committed for consumers | Unit tests; docs merged |
| 3 | Validation: SIGKILL loops, joins on a test cluster and the Midstream control plane under stop, rebalance and kill; throughput and per-hop latency against at least once | Zero duplicates for read_committed readers; costs measured and accepted |
| 4 (optional) | aiokafka: `TxnOffsetCommit` v3 with consumer group metadata (upstream PR); one producer per worker | Upstream merged and released |

## Open questions

1. Rollout: transactional sends on by default at release, or opt in first?
2. The commit interval under exactly once: latency against broker load.
3. Tables written outside processing (Kaspr tasks and web views using `update_for_partition`): commit them in
   their partition's transaction at the next commit, or leave them non-transactional?
4. Priority of EOS v2 against the producer count of apps with many partitions.
