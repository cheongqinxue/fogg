# Ideas

Exploratory ideas that are not committed product requirements.

## Lightweight browser-operation agent

Explore a local browser agent for tasks where navigating a website is useful and
the site permits automated access. The smallest purpose-built, permissively
licensed option found so far is ByteDance's **UI-TARS-2B-SFT** (2B parameters,
Apache-2.0). It takes screenshots and emits GUI actions. The project points to
Midscene.js for browser automation, but recommends larger 7B or 72B models for
better performance. The UI-TARS repository was archived in November 2026, so
the 2B model should be treated as an experiment rather than a production-ready
agent.

A roughly 1B WebBrain fine-tune also exists, but its weights are licensed for
non-commercial research only and its published action results are weak. It is
not a suitable FOGG production candidate under that license.

### Possible evaluation

- Compare screenshot-driven UI-TARS-2B with a DOM/accessibility-tree browser
  controlled by a small text model; the latter may need less compute.
- Test only on websites whose terms permit automation, using read-only tasks
  first. Measure task completion, wrong actions, latency, hardware needs, and
  recovery after page changes.
- Keep confirmation gates before purchases, reservations, submissions, or
  other external side effects.

References: [UI-TARS-2B-SFT model card](https://huggingface.co/ByteDance-Seed/UI-TARS-2B-SFT),
[UI-TARS project](https://github.com/bytedance/UI-TARS),
[WebBrain model card](https://huggingface.co/webbrain-one/minicpmv47-webbrain-v1),
[Google Maps Platform terms](https://cloud.google.com/maps-platform/terms).
