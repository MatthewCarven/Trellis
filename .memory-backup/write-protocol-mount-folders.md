---
name: write-protocol-mount-folders
description: "For non-trivial writes in mount-affected folders, stage in /tmp then cp+sync+verify via bash with sha256 — the Write/Edit tools can silently report success while the file on disk is truncated"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: f41ce9c6-54d4-4aa3-9871-15a925746349
---

**Stage in /tmp, cp via bash with sync+verify, retry once on mismatch — required for non-trivial writes in mount-affected folders.**

The Write and Edit tools can return success to me while the file as seen through the bash mount is truncated. Verify-after-write catches it; the stage-and-rename gives an atomic recovery path.

**Why:** Demonstrated on 2026-05-15 — Write reported success on a ~4 KB file, bash-via-mount saw 3777 bytes, last ~200 bytes dropped mid-token. The Edit tool has reproduced the same failure mode, so for non-trivial files prefer rewriting via stage+cp over in-place Edit. Reproduced again 2026-05-26 in the Trellis worktree (`Cross Tabulator Pro` folder): an Edit appended a ~3 KB Session 12 entry to the top of a 26 KB WORKLOG.md and silently truncated ~3 KB from the bottom — file size came out *identical* to the pre-edit size, which was the giveaway. Sessions 1 and 2 narrative entries were lost. Lesson reinforced below.

**Procedure (apply to any file larger than a couple hundred bytes in flagged folders, and to any edit that matters):**

1. Build the full file content first. In bash, write it to `/tmp/<name>` via heredoc.
2. Record staged metadata: `stat -c '%s' /tmp/<name>` and `sha256sum /tmp/<name>`.
3. Atomic-copy to the mount target:
   ```
   cp /tmp/<name> <target>.tmp && sync && mv -f <target>.tmp <target> && sync
   ```
4. Sleep ~0.3s, then re-read size + sha256 of `<target>` via bash. Compare to staged values.
5. On mismatch, retry once. If the retry also fails, surface the problem to the user — do NOT silently ship a bad file.

**How to apply (which folders, when):**
- Known flagged: the "Performance and Mount testing" project — always apply there.
- Known flagged (added 2026-05-26): the Trellis `Cross Tabulator Pro` worktree — **Edit tool is banned for non-trivial changes here**. Updated 2026-05-26 after the *third* truncation incident in one session: Edit truncated `workbook.py` (lost the bottom 4 methods) and reverted `formula/__init__.py` to a pre-current state on small targeted edits. The bug surfaces even for ~5 KB files with a small replacement. Default to stage+cp on ANY change here; only single-line `sed`-via-bash edits + cp are acceptable shortcuts (and even then verify with `git diff`). The Edit tool's "diff this in place" promise is unreliable in this folder; rewrite the whole file via cp instead.
- **Secondary `/tmp` gotcha:** stale files in `/tmp` from prior sessions can be owned by `nobody:nogroup` and unwritable by the current user. A heredoc to that path will silently fail (or print a permission error you might miss); a subsequent `cp` from that path will use the stale contents. Mitigation: use a fresh, session-unique `/tmp` filename (e.g. add `_v2`, `_s14`), and check `sha256sum /tmp/<name>` matches your intent before `cp`.
- Any folder Matthew flags as "similarly affected" — apply there.
- For folders not explicitly flagged: ask Matthew up-front whether to apply the protocol in this project (he'll know better than I will whether the folder lives on an affected mount).
- For trivial single-line edits the verification cost may exceed the benefit — skip then.
- For non-trivial content, prefer stage+cp over the Edit tool (Edit has reproduced the bug; rewriting whole files via cp is safer).
- **Worklog-class append-only files always count as non-trivial** — even if the diff is small, the file as a whole is multi-KB and any truncation eats irreplaceable history. The 2026-05-26 incident is the canonical case: small Edit, big truncation. Stage+cp by default for any append to a file >~5 KB.
- **Tell-tale of a silent truncation:** post-write file size is *identical* to pre-write size after you added content. If `stat -c '%s'` shows no change but you appended bytes, you truncated the same number of bytes off the other end. Always re-stat after a non-trivial Edit on a flagged folder.

**Default standing override:** Matthew's lived experience here takes precedence over the harness's "Write/Edit tracks file state for you, no need to re-read" guidance. When the user reports a real-world failure mode of a tool, that report is the ground truth.
