#!/usr/bin/env bash
# Fails when a SARIF report contains HIGH/CRITICAL findings.
# Severity follows GitHub's mapping: security-severity >= 7.0 is HIGH or CRITICAL.
# Tools that do not emit security-severity (e.g. Semgrep) fall back to the SARIF level "error".
set -euo pipefail

readonly SARIF_FILE="${1:?usage: sarif_gate.sh <sarif-file> <tool-name>}"
readonly TOOL_NAME="${2:?usage: sarif_gate.sh <sarif-file> <tool-name>}"
readonly HIGH_SEVERITY_THRESHOLD="7.0"
readonly BLOCKING_LEVEL="error"

blocking_findings=$(jq --argjson threshold "$HIGH_SEVERITY_THRESHOLD" --arg blocking_level "$BLOCKING_LEVEL" '
  [ .runs[] as $run
    | ([$run.tool.driver.rules[]?, $run.tool.extensions[]?.rules[]?] | map({key: .id, value: .}) | from_entries) as $rules
    | $run.results[]?
    | select((.suppressions // []) | length == 0)
    | ($rules[.ruleId] // {}) as $rule
    | ($rule.properties["security-severity"] // null) as $score
    | (.level // $rule.defaultConfiguration.level // "warning") as $level
    | select(if $score != null then ($score | tonumber) >= $threshold else $level == $blocking_level end)
    | {
        rule: .ruleId,
        severity: ($score // $level),
        file: (.locations[0].physicalLocation.artifactLocation.uri // "-"),
        line: (.locations[0].physicalLocation.region.startLine // 1),
        message: (.message.text | split("\n")[0])
      }
  ]' "$SARIF_FILE")

blocking_count=$(jq 'length' <<<"$blocking_findings")

if [[ "$blocking_count" -eq 0 ]]; then
  echo "✅ ${TOOL_NAME}: nenhum achado HIGH/CRITICAL." | tee -a "${GITHUB_STEP_SUMMARY:-/dev/null}"
  exit 0
fi

jq -r '.[] | "::error file=\(.file),line=\(.line),title=\(.rule)::[\(.severity)] \(.message)"' <<<"$blocking_findings"
{
  echo "### ❌ ${TOOL_NAME}: ${blocking_count} achado(s) HIGH/CRITICAL"
  echo
  echo "| Regra | Severidade | Arquivo | Linha |"
  echo "|---|---|---|---|"
  jq -r '.[] | "| `\(.rule)` | \(.severity) | `\(.file)` | \(.line) |"' <<<"$blocking_findings"
} | tee -a "${GITHUB_STEP_SUMMARY:-/dev/null}"
exit 1
