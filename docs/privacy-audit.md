# Public release privacy and history boundary

The public repository is created from an audited **single filesystem snapshot**
with a **new root commit**. It is not a fork, history rewrite or mirror of the
earlier private development repository. Historical commits, tags, pull requests,
comments, log files, binaries and workflow execution data from private
development are not included.

Current sources, tests, workflows, documentation, build scripts and release
package contents are checked for host-specific recipients, private Mac usernames,
credentials, tokens, absolute home paths, tailnet names and private endpoints.
Run `python3 tools/privacy-check.py` before committing and as part of CI.
Additional manual review is still required because no pattern-based scan
can prove absence of every personal identifier or secret.

All real FaceTime recipients, local NanoKVM endpoints, cloud API keys and
OpenClaw runtime settings must be supplied by each user through their local
private configuration. The repository intentionally includes no live credentials.

A public first release must be created from its clean root commit, not by
importing older tags or Git objects. The original private development history
is independently preserved in an owner-only archive and is outside this
public repository's reachable history.

The distribution does not include paid third-party apps such as Rogue Amoeba
Loopback, nor does the MIT license replace their licensing terms.
