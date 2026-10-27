#!/usr/bin/env bash
# Fails when a pip-audit JSON report contains vulnerabilities that already have a fixed version.
# pip-audit does not report severity, so "fix available" is the actionable blocking criterion.
set -euo pipefail

readonly REPORT_FILE="${1:?usage: pip_audit_gate.sh <pip-audit-json-report>}"

fixable_vulns=$(jq '[
  .dependencies[]
  | . as $dependency
  | .vulns[]?
  | select((.fix_versions // []) | length > 0)
  | {
      package: $dependency.name,
      version: $dependency.version,
      id: .id,
      aliases: ((.aliases // []) | map(select(startswith("CVE-"))) | join(", ")),
      fix: (.fix_versions | join(", "))
    }
]' "$REPORT_FILE")

fixable_count=$(jq 'length' <<<"$fixable_vulns")
total_count=$(jq '[.dependencies[].vulns[]?] | length' "$REPORT_FILE")

if [[ "$fixable_count" -eq 0 ]]; then
  echo "✅ pip-audit: nenhuma vulnerabilidade com correção disponível (total sem correção: ${total_count})." | tee -a "${GITHUB_STEP_SUMMARY:-/dev/null}"
  exit 0
fi

jq -r '.[] | "::error title=\(.id)::\(.package)==\(.version) vulnerável (\(.aliases)); atualize para \(.fix)"' <<<"$fixable_vulns"
{
  echo "### ❌ pip-audit: ${fixable_count} vulnerabilidade(s) com correção disponível"
  echo
  echo "| Pacote | Versão | ID | CVE | Corrigido em |"
  echo "|---|---|---|---|---|"
  jq -r '.[] | "| `\(.package)` | \(.version) | \(.id) | \(.aliases) | \(.fix) |"' <<<"$fixable_vulns"
} | tee -a "${GITHUB_STEP_SUMMARY:-/dev/null}"
exit 1
