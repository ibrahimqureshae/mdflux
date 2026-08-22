## What & why

<!-- What does this change, and why? Link any related issue (e.g. Closes #123). -->

## How was it tested?

<!-- Use frozen command names where applicable: -->
<!-- cd app && npm run check -->
<!-- cd app/src-tauri && cargo check --locked && cargo test --locked -->
<!-- cd app/src-tauri/resources/sidecar && python -m unittest discover -s tests -p "test_*.py" -->
<!-- python -m tools.release --archive ... --platform ... --edition ... (release/packaging PRs) -->

## Cross-platform impact

- [ ] No duplicated platform-specific application logic (adapter/packaging only)
- [ ] Docs updated if user-facing behavior, editions, or support boundaries changed
- [ ] N/A — documentation or tooling only

## Checklist

- [ ] Focused change; matches the surrounding code style
- [ ] `cd app && npm run check` passes (0 errors)
- [ ] `cd app/src-tauri && cargo check --locked` passes
- [ ] Sidecar tests run when Python sidecar files changed
- [ ] No secrets, keys, or personal paths added
