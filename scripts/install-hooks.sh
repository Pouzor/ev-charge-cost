#!/bin/bash
# Install local git hooks for ev-charge-cost.
# Run once after cloning: ./scripts/install-hooks.sh
set -e

ROOT=$(git rev-parse --show-toplevel)
HOOK="$ROOT/.git/hooks/pre-commit"

cat > "$HOOK" <<'HOOK_EOF'
#!/bin/bash
set -e

ROOT=$(git rev-parse --show-toplevel)
STAGED=$(git diff --cached --name-only --diff-filter=ACMR)

if echo "$STAGED" | grep -qE "\.(py|json)$"; then
  echo "⚡ Integration: ruff + tests..."
  cd "$ROOT"
  if [ -x .venv/bin/pytest ]; then
    .venv/bin/ruff check .
    .venv/bin/ruff format --check .
    .venv/bin/pytest -q
  else
    echo "  (skipping — .venv missing; see README.md to enable.)"
  fi
fi

echo "✅ All checks passed."
HOOK_EOF

chmod +x "$HOOK"
echo "Installed pre-commit hook → $HOOK"
