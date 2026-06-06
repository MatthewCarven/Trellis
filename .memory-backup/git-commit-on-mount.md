---
name: git-commit-on-mount
description: "How to commit in the Trellis repo on Matthew's mount — stale index.lock + git identity quirks"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 30141e71-1e33-4c90-b8c5-5c767acff512
---

Committing in the Trellis repo from the bash sandbox hits two recurring mount quirks:

1. **`git add` leaves a stale `.git/index.lock`** it can't unlink ("Operation not permitted"), which then blocks `git commit` ("Unable to create index.lock: File exists"). bash `rm -f` also fails. Fix: call the `mcp__cowork__allow_cowork_file_delete` tool on the lock's VM path, then `rm -f .git/index.lock`. Same fix for any "Operation not permitted" delete on this mount.
2. **Git identity is unset** in the sandbox (`Author identity unknown`). Set it locally (not --global) to match prior commits: `git config user.name "Admin" && git config user.email "matthewcarven@gmail.com"`.
3. **Edit/Write-tool changes can be invisible to git on the mount** (Session 25): files edited via the Edit tool (WORKLOG.md, design.md) showed the new content to bash `grep`/`cat` but `git status`/`git diff HEAD` reported *no change* vs HEAD — git's working-tree view was stale. Fix that worked: rewrite each file through bash to force the layers to agree, e.g. `cp f /tmp/f.copy && cat /tmp/f.copy > f`, then `git add`. After that git saw all changes. So when a commit is missing files you know you edited, rewrite-through-bash before `git add`.

The "unable to unlink" warnings on tmp_obj files during add/commit are harmless — the operation still succeeds; filter them with `grep -vi "unable to unlink"`. Related: [[write-protocol-mount-folders]].

**Why:** these block every commit and look fatal but aren't.
**How to apply:** before committing, set the local git identity; if a commit fails on index.lock, allow-delete + rm it and retry.
