# Beta research upload repair — 12 October 2026

The Mac diagnostic reported `BETA_TOO_LARGE`: a 969,597-byte combined report
after Beta-only compression exceeded the 850,000-byte transport budget.
The dashboard consequently had no Beta snapshot to render.

The transport now tries bounded, lossless compression of the complete sanitized
report when Beta-only compression is insufficient. This also compresses repeated
QQQ trade context. It preserves all data accepted by the existing sanitizers,
including Beta dossiers, positions, orders and activity. Existing small reports
and the original Beta-only compressed format remain supported.

The SQL-required headers, uploader report status and controller status remain
visible in the outer envelope. The reader verifies matching headers, SHA-256,
advertised output length, one complete compressed stream and a 16 MB logical
limit, then reapplies the existing field allowlists. The 850 KB wire budget,
900 KB SQL limit, credentials, trading rules and ON/OFF controls are unchanged.

Deploy this dashboard reader before updating the Mac uploader. The matching
`Victor_Beta_Upload_Fix_v2.zip` repair supports the verified installed telemetry
module whose SHA-256 starts `a18276d35a3d`. It checks source and worker hashes,
backs up changed source and release-manifest entries, and restarts only the
verified telemetry uploader through its existing supervisor. It prints whether
a new uploader acknowledged a fresh upload or confirmation is still pending.

After the Mac repair, refresh VictorTerminal.com and inspect Beta Research's
Overview, Research, Positions and Activity tabs. Check the snapshot timestamp
and open a stock dossier. An offline test or repository commit does not establish
that the user's Mac upload or hosted Streamlit deployment has completed.
