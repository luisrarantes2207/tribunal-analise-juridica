# Tribunal de Análise Jurídica

Ferramenta de apoio à análise de peças processuais brasileiras: confronta a peça de ataque com a peça de
resposta (Contestação × Réplica, Inicial × Contestação, Recurso × Contrarrazões, Embargos × Resposta), mede a
robustez de cada ponto por um roteiro fixo e propõe um plano cirúrgico de melhoria da peça.

> **Aviso.** É uma ferramenta de apoio. Todo parecer exige revisão do advogado responsável. Não envie documentos com
> dados pessoais reais de clientes a instâncias que você não controla (LGPD e sigilo profissional).

## O que faz (v5.x)

- **Matriz de confronto** tese a tese, com nota de robustez (enfrentamento 20 · fatos 20 · norma 20 · prova 30 ·
  pedido 10) e chance por ponto; êxito geral limitado a 94%.
- **Regras jurídicas separadas do modelo de IA** (`diretrizes_juridicas_v5.md` + `diretrizes.py`): o modelo analisa e
  sugere; o código confere e retira o que viola regras duras (perícia no Juizado, revelia da Fazenda tratada como
  presunção, número de acórdão inventado, placeholders, honorários em 1º grau de Juizado, "súmula vinculante do STJ").
- **Perfil do magistrado** a partir dos atos do juízo que estão nos autos (sem histórico externo inventado).
- **Auditoria fato-folha**: cada "fls. X" citado na peça é conferido no PDF do processo.
- **Dosimetria do dano moral**, **chat copiloto** com `/adversario` (a parte contrária ataca a sua peça), peça
  sugerida em verde e exportação `.docx` consolidada.

## Instalação

Requisitos: Python 3.11+ e uma chave de API compatível com OpenAI (OpenAI, OpenRouter, Omniroute etc.).
A guarda da chave usa o DPAPI do Windows; em outros sistemas, ajuste `cofre.py`.

```bash
pip install -r requirements.txt
python -m uvicorn app:app --host 127.0.0.1 --port 8778
```

Abra `http://127.0.0.1:8778`, informe a URL do provedor e a chave no item **02 · Inteligência & cofre** e teste a
conexão. Variáveis úteis: `TRIBUNAL_BASE_URL` (provedor padrão) e `TRIBUNAL_VAULT_DIR` (pasta do cofre).
A exportação em PDF usa o Microsoft Word; o `.docx` funciona sem ele. Para usar o seu papel timbrado, coloque o
arquivo em `modelos/timbrado.docx`.

Para testar sem documentos reais, use o processo de exemplo fictício em `static/exemplo/`.

## Modo demonstração (para abrir a testadores)

```powershell
$env:TRIBUNAL_DEMO = "1"; $env:TRIBUNAL_SENHA = "uma-senha-forte"
python -m uvicorn app:app --host 127.0.0.1 --port 8779 --proxy-headers
```

Com `TRIBUNAL_DEMO=1`: tela de senha, cada testador só vê as próprias sessões, limite diário
(`TRIBUNAL_LIMITE_DIA`, padrão 3 análises; `TRIBUNAL_LIMITE_CHAT`, padrão 20 mensagens) e as funções de
administração (zerar sessões, trocar chave/modelo) ficam bloqueadas. `iniciar_demo.ps1` sobe a demonstração e um
túnel `cloudflared` com endereço https público (o executável não vem no repositório).

### Painel do administrador

Com o modo demonstração ligado, `http://127.0.0.1:8779/admin` (só no computador que hospeda) mostra cada testador com IP,
navegador, sessões, análises, mensagens e consumo de IA (chamadas, tokens, tempo), com as ações **derrubar**,
**bloquear IP** e **permitir**, registro de eventos e limites ajustáveis ao vivo. No máximo 5 testadores online ao
mesmo tempo (`TRIBUNAL_MAX_USUARIOS`); o sexto recebe "sala cheia".

## Papel da peça

Nas abas II e III, escolha **Folha em branco** (A4 com margens ABNT, como uma página nova do Word) ou envie o
**seu timbrado em .docx**; a exportação usa o cabeçalho e o rodapé dele.

## Estrutura

| Arquivo | Papel |
|---|---|
| `app.py` | API FastAPI e páginas |
| `motor.py` | pipeline da análise (leitura integral, teses, matriz, cálculo, decisão) |
| `advogado.py` | plano cirúrgico do advogado sênior |
| `diretrizes.py` / `diretrizes_juridicas_v5.md` | regras jurídicas e conferência da saída do modelo |
| `magistrado.py`, `folhas.py`, `dosimetria.py` | ferramentas determinísticas da v5 |
| `chat_estrategia.py` | copiloto e `/adversario` |
| `peca.py`, `peca_sugestao.py` | editor, peça sugerida e exportação |
| `demo.py`, `static/admin.html` | modo demonstração e painel do administrador |

Histórico completo em `CHANGELOG.md`.
