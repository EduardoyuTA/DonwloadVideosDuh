# VideoFlow Downloader

Aplicacao local em Python para baixar videos por meio de links.

## O que o app faz

- Recebe uma URL de video
- Salva o arquivo em uma pasta escolhida por voce
- Exporta em MP4, WEBM e MKV
- Permite escolher qualidade maxima, 4K, 1440p, 1080p, 720p ou 480p
- Mostra preview com titulo, plataforma, duracao e tamanho estimado antes de baixar
- Exibe progresso real com fila de downloads
- Mantem historico persistente dos downloads concluidos
- Exporta em MP3 quando o FFmpeg estiver instalado
- Possui modo online responsivo, com entrega do arquivo pelo navegador
- Usa Neon/Postgres em producao quando `DATABASE_URL` estiver configurada

## Uso responsavel

Use este projeto apenas com conteudo que voce tem permissao para baixar. Algumas plataformas possuem restricoes proprias de uso e download.

## Como rodar

### Modo rapido

Execute o arquivo `iniciar_app.bat` com duplo clique. Ele:

- cria a pasta `.venv` se ainda nao existir
- instala ou verifica as dependencias
- fecha processos antigos presos na porta `5000`
- inicia o servidor Flask
- abre o navegador em `http://127.0.0.1:5000`

Se a interface estiver nova, mas algum recurso continuar se comportando como versao antiga, rode `reiniciar_app_limpo.bat`. Ele encerra qualquer instancia que ainda esteja ouvindo a porta `5000` e sobe o app de novo.

## Recursos novos

- Preview automatico do link antes do download
- Fila com status em tempo real
- Historico salvo em `data/download_history.json`
- Preferencias locais de formato, qualidade e pasta de destino

## Gerar EXE

Para empacotar o app em um executavel do Windows, rode:

```powershell
.\gerar_exe.bat
```

O build gera o arquivo `dist\VideoFlow.exe`.

## Gerar instalador Windows

Para gerar um instalador real do Windows com atalho e desinstalacao:

```powershell
.\gerar_instalador.bat
```

O build gera o arquivo `dist\installer\VideoFlow-Installer.exe`.
O instalador usa o Inno Setup e instala o app por usuario em `%LOCALAPPDATA%\Programs\VideoFlow`.

### Modo manual

1. Crie um ambiente virtual:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

2. Instale as dependencias:

```powershell
pip install -r requirements.txt
```

3. Inicie o servidor:

```powershell
python app.py
```

4. Abra o navegador em:

```text
http://127.0.0.1:5000
```

## Colocar no ar

O projeto agora inclui um modo hospedado para publicar o app como site responsivo.
Nesse modo, o campo de pasta local e escondido, o servidor salva o arquivo em uma
pasta temporaria e a interface mostra o botao `Baixar arquivo` quando o job termina.
O endpoint de arquivo força resposta como anexo, o que ajuda Safari, Chrome, Edge
e navegadores mobile a baixar MP3/MP4 em vez de tentar reproduzir inline.

### Deploy com Docker

O caminho recomendado e usar Docker, porque o app precisa de FFmpeg para MP3,
contagem BPM e espelhamento de video.

Arquivos incluidos:

- `Dockerfile`: instala Python, dependencias e FFmpeg
- `.dockerignore`: evita enviar builds, downloads e ambiente virtual para a imagem
- `render.yaml`: blueprint para Render usando runtime Docker
- `Procfile`: alternativa para plataformas que leem comando web

### Banco de dados Neon

No modo online, configure uma variavel `DATABASE_URL` com a connection string do
Neon. O app cria automaticamente a tabela `download_history` no primeiro boot e
usa o banco para guardar o historico dos downloads concluidos.

Exemplo de formato da connection string:

```text
postgresql://usuario:senha@host-pooler.regiao.aws.neon.tech/dbname?sslmode=require&channel_binding=require
```

Se `DATABASE_URL` nao existir, o app volta para o historico local em
`data/download_history.json`.

### Rodar como web local

```powershell
$env:VIDEOFLOW_HOSTED="1"
python app.py
```

Depois abra:

```text
http://127.0.0.1:5000
```

### Publicar no Render

1. Suba o projeto para um repositorio GitHub.
2. No Render, crie um novo Web Service a partir desse repositorio.
3. Escolha Docker como runtime, ou use o blueprint `render.yaml`.
4. Confirme que a variavel `VIDEOFLOW_HOSTED` esta com valor `1`.
5. Adicione `DATABASE_URL` com a connection string do Neon.
6. Depois do deploy, o Render vai gerar uma URL publica `onrender.com`.

Observacao: em hospedagens gratuitas, downloads grandes podem demorar ou falhar por
limites de CPU, memoria, armazenamento temporario ou tempo de execucao.

## FFmpeg para MP3

Se quiser extrair audio em MP3, instale o FFmpeg e deixe o executavel disponivel no `PATH` do Windows.
