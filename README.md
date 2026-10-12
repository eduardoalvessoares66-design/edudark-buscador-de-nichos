# Radar de Nichos

Roda todo dia às 06:30 (Brasília) no GitHub Actions e guarda canais novos bombando
(1º vídeo há no máx. 90 dias, até 15 vídeos, 20 mil+ views) em `data/novos_<idioma>.json`.
O Buscador de Nichos lê esses arquivos pelo GitHub Pages, sem gastar a cota de quem usa.

- Chave do YouTube: secret `YT_KEY` do repositório.
- Palavras pesquisadas: `kw.json`.
- Pesquisas por dia: `BUDGET` em `radar.py` (60 = ~6.000 unidades).
- Rodar na hora: aba **Actions** → **Radar diario** → **Run workflow**.
