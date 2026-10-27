## Fase
<!-- Ex.: Fase 1 — Fundação (docs/planejamento/PLANO_DE_DESENVOLVIMENTO.md) -->

## O que foi feito
-

## Por que (decisões)
<!-- Motivo de cada decisão relevante; links para RFC/ADR quando houver. -->
-

## Trade-offs
<!-- O que ganhamos, o que abrimos mão e o que fica para depois. Remova a seção se não se aplicar. -->
-

## Como testar
```bash
make check
```

## Checklist
- [ ] Cobertura ≥ 95% (`make check`)
- [ ] Endpoints novos com rate limit e autenticação quando consomem créditos
- [ ] Nenhum segredo versionado; `.env.example` atualizado
- [ ] README / `docs/manuais/` atualizados
- [ ] ADR criado, se a mudança for arquitetural
