# COMPARATIVO DAS OPÇÕES

Precisamos considerar que, para esse teste/protótipo, temos arquivos de mais de 16MB (o que pode ser um impeditivo em hospedagens gratuitas) e a aplicação não pode cair, pois não sabemos a data/hora que o gestor vai realizar os testes. 

Dito isso, fiz um levantamento e vi que, inicialmente, as melhores opções para hospedar essa aplicação são:
- `Google Cloud Run` - código mais enxuto por não precisar implementar chunks no ato de upload;
- `Vercel` - código um pouco mais com a implementação de chunks no ato do upload.
De qualquer forma, implementarei o chunks no ato do upload para que não tenhamos restrição em nenhuma das hospedagens disponíveis. Desconsiderei o `Render` pelo desastre que poderíamos ter em casos de reinicialização, suspensão ou novos deploy.

---

## 1. GOOGLE CLOUD RUN

- Custo: pode ficar em R$ 0 dentro da franquia gratuita.
- Aceita requisições HTTP/1 de até 32 MiB — suficiente para um PDF de 20 MB, desde que o corpo total não ultrapasse o limite.
- Suporta streaming HTTP, adequado para SSE.
- Executa a aplicação em container Python/FastAPI.
- Tem franquia mensal gratuita, mas exige atenção ao faturamento e ao consumo excedente.

## 2. Render

- Custo: plano gratuito para aplicações web.
- Hospeda serviços Python, incluindo FastAPI.
- Bom para publicar rapidamente uma API de demonstração.
- Entra em suspensão após 15 minutos sem tráfego; a reativação pode levar cerca de um minuto.
- O sistema de arquivos é efêmero: uploads e índices locais podem desaparecer após reinicializações, suspensão ou novo deploy.

## 3. Vercel
- Custo: plano Hobby gratuito, com restrições.
- O problema é o limite de 4,5 MB por requisição às Functions.
- Um PDF de 16 MB enviado diretamente ao FastAPI hospedado na Vercel ultrapassa esse limite. 
- A própria documentação recomenda uploads diretos para armazenamento externo para contornar a restrição.
