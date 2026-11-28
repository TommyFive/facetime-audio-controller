# v3.2.2 — lockscreen reliability

This patch improves notification classification, handling of GUI lock transitions, and stale unavailable-card recovery. The controller still refuses ambiguous call confirmation and never chooses a card merely by its screen position.

A consented locked-screen live call on the private deployment completed connection, speech playback, and verified hangup after the operator resolved a missing Python permission. The recipient independently confirmed audible speech. The mixed-card path is covered by offline regression tests; the live successful call used a single pending card. The underlying cause of repeated native media-service crashes and duplicate notifications has not been established.

See [incident and recovery notes](lockscreen-audio-recovery.md). No automatic restart of the audio stack, change to TCC, or migration of existing private deployments is performed by this release.
