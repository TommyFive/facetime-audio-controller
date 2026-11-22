# Local usage journal and CLI

The FaceTime Controller writes **only allowlisted metadata**, never speech text.
This is a local journal and CLI feature, not an MCP tool or an online dashboard.

## What is recorded

Every record contains a UTC timestamp, schema version and random per-call
correlation identifier. The ID is not a recipient, caller or MCP request ID.

- `minimax_request`: a MiniMax HTTPS attempt that was sent, selected endpoint
  (`api.minimax.io` or `api.minimaxi.com`), model, input Unicode character
  count, successful generation or safe error category, API latency, and
  `extra_info.usage_characters` when the service returns it.
- `tts_render`: one successfully finalized playable audio file: chosen/actual
  provider and endpoint, model, input characters, synthesis duration, actual
  audio duration, and whether macOS was used as the MiniMax fallback.
- `call_result`: controller runtime, dial requested, observed connected
  (accepted/answered), playback completed, hangup verified and final outcome.

A MiniMax API response is recorded before local audio conversion and before
FaceTime dialing. Therefore an accepted MiniMax render is counted even if the
user never answers, if the caller disconnects, or if subsequent conversion
fails and the controller falls back to macOS. A macOS fallback produces its
own final TTS record, categorized separately from direct macOS synthesis.

**Do not add raw response payloads or speech text to this schema.** Provider
`usage_characters` is a measured API field; the local `input_characters`
value is a Python Unicode code-point count. These can differ. Missing provider
usage metadata is represented as `null`, not zero. The journal does not
store currency amounts or imply that a request was charged.

## How to read

```bash
python3 tools/usage.py
python3 tools/usage.py --since 2026-11-01 --until 2026-11-30
python3 tools/usage.py --json
```

Date filters use the **UTC event date**, inclusive. Human reports show
counts, model/endpoint/fallback splits and generated audio totals in hours.
The JSON mode is read-only and returns the same aggregates for scripts.

The local file is:

`~/.local/state/facetime-controller/usage.jsonl`

The parent must be owned by the local user and have no group/other access
(mode 0700). The append-only regular file must be 0600, have one hard link,
and must not be a symlink. Each write uses an OS-level append lock and an
explicit narrow schema. `FACETIME_USAGE_DIR` can point to a separate
absolute directory for test isolation or packaging.

The journal begins collecting only after the instrumented TTS and call
controllers are deployed. Older request-ID journals and tunnel warnings
do **not** reconstruct historical character usage accurately.

## Reliability and interpretation

The journal is best-effort telemetry: if the disk is full or the permissions
are unsafe, calls and their safety cleanup must still work. A short
`USAGE_JOURNAL_WARNING` with no path or contents appears on stderr.

Call `connected` is a CallServices-observed state correlated with the
transaction, not independent cryptographic proof of recipient identity,
handset-side audio, or user comprehension. A dropped call may have
`connected=true` but `playback_completed=false`.

**Never** sum API input characters and rendered characters as if they were
the same invoice. When MiniMax succeeds but a later step fails, a separate
macOS fallback render may be generated for the same source text. The two
events represent distinct synthesis work. For invoicing, use MiniMax's
account-side usage instead of estimating a price from this journal.

## Automated verification

`tests/test_usage_journal.py` checks the schema's privacy allowlist,
owner-only permissions, symlink refusal, concurrent append safety, captured
provider usage from synthetic HTTP responses, unknown billing counts on
network errors, fallback separation, generated audio when calls fail,
aggregation and CLI JSON output. CI runs on Linux and macOS without
placing calls or sending requests to MiniMax.
