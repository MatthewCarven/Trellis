---
name: design-philosophy-open-extensibility
description: "Matthew prefers open, hook-rich frameworks over locked-down APIs — trust users (other devs) to wield it correctly and accommodate their behavior rather than restrict it"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: f41ce9c6-54d4-4aa3-9871-15a925746349
---

When designing libraries, frameworks, or anything other developers will consume, Matthew prefers exposing hooks and letting downstream users extend and bend things — even if that means they could shoot themselves in the foot. He calls this "chaotic good" extensibility.

**Why:** His view is that the school of thought where you "bury functionality where nobody can touch it" is overpaid-for safety; the better practice is to put the onus for correct operation back on the user and accommodate their behavior. Stated in the context of his spreadsheet/framework project but expressed as a general engineering preference.

**How to apply:**
- Favor public-by-default APIs, lifecycle hooks, registries other code can register into, and base classes designed for subclassing.
- Don't over-encapsulate or hide internals "for safety" unless there's a concrete reason — Matthew would rather give a sharp tool than a dull one.
- When a feature is "out of scope," check whether the framework can still *express* it via extension hooks — that's often the right answer instead of "no."
- Document extension points clearly; safety rails come from docs and conventions, not locked doors.
