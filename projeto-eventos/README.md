# Showline — Gerenciamento de Shows

Front-end + back-end para o seu projeto original do repositório `M-todos-` (IF264).
O back-end (FastAPI + SQLite) foi refinado e ganhou um front-end inspirado em
plataformas como Sympla / Eventbrite / Ticketmaster, com cards em formato de
"canhoto de ingresso", barra de lotação, fila de espera e busca.

```
projeto-eventos/
├── backend/
│   ├── main.py            # API (refinada a partir do seu main.py original)
│   └── requirements.txt
└── frontend/
    ├── index.html
    ├── style.css
    └── script.js
```

## O que mudou em relação ao seu `main.py` original

- **CORS habilitado** — sem isso o navegador bloqueia as chamadas do front (porta diferente da API).
- **Validação com Pydantic** (`EventoCreate`, `InscricaoCreate`) em vez de query params soltos — menos erro de digitação, erros 422 claros.
- **Novos campos no evento**: `descricao`, `local`, `categoria`, `imagem_url`, `preco`, `criado_em`.
- **Novos endpoints**: `GET /eventos/` (listar tudo), `GET /eventos/{id}` (detalhe), `DELETE /eventos/{id}` (remover evento), `GET /categorias`.
- **Cascade delete**: ao apagar um evento, fila de espera e vínculos de inscrição são removidos junto (`ondelete="CASCADE"` + `cascade="all, delete-orphan"`).
- **Bug corrigido** na busca por data (a versão original comparava `DateTime` completo com uma data sem hora, então quase nunca encontrava nada).
- A lógica de **BST** (relatório ordenado) e **fila FIFO** (lista de espera) que você implementou foi mantida 100% — só ganhou serialização mais rica.

### Sistema de usuários (login/cadastro)

- Tabela `usuarios` (username + senha) e `sessoes` (tokens de login).
- Senhas nunca ficam em texto puro: usamos **PBKDF2-HMAC-SHA256** com salt aleatório,
  só com a biblioteca padrão do Python (`hashlib`/`secrets`) — escolhi essa abordagem
  de propósito para não depender de pacotes como `bcrypt`/`passlib` que às vezes
  exigem compilação no Windows (o mesmo problema que você teve com o `pydantic-core`).
- Login gera um **token opaco** (string aleatória) salvo em `sessoes`. O front guarda
  esse token no `localStorage` do navegador e manda em todo pedido protegido como
  `Authorization: Bearer <token>`.
- Cada evento agora tem um `criador_id`. **Só quem criou o evento pode editá-lo ou excluí-lo**
  (`PUT /eventos/{id}` e `DELETE /eventos/{id}` verificam isso e retornam `403` se não for o dono).
- Inscrição/cancelamento de participantes continuam públicos — qualquer visitante pode se
  inscrever num evento, só a gestão do evento em si é restrita ao criador.

> ⚠️ **Se você já tinha rodado uma versão anterior e existe um arquivo `backend/eventos.db`,
> apague-o antes de rodar de novo.** O SQLAlchemy só cria tabelas que ainda não existem —
> ele não adiciona colunas novas (`criador_id`) nem tabelas novas (`usuarios`, `sessoes`)
> a um banco que já existe com o esquema antigo. Apagando o `.db`, ele é recriado do zero
> já com o esquema novo na próxima vez que você rodar `uvicorn main:app --reload`.

---

## 1. Rodando na sua máquina

### Pré-requisitos
- Python 3.10+ instalado (`python --version` no terminal)
- Não precisa de Node nem de nada além de um navegador para o front-end

### 1.1. Backend (API)

```powershell
# entre na pasta do backend
cd projeto-eventos/backend

# crie um ambiente virtual (recomendado)
python -m venv venv

# ative o ambiente virtual
# Windows (PowerShell):
venv\Scripts\Activate.ps1
# Windows (cmd):
venv\Scripts\activate.bat
# Linux/Mac:
source venv/bin/activate

# instale as dependências
pip install -r requirements.txt

# rode o servidor
uvicorn main:app --reload
```

Se tudo der certo, vai aparecer algo como:
```
Uvicorn running on http://127.0.0.1:8000
```

Deixe esse terminal aberto. Você pode testar a API sozinha abrindo
`http://127.0.0.1:8000/docs` no navegador (documentação automática do FastAPI).

O banco `eventos.db` (SQLite) é criado automaticamente na primeira execução,
na própria pasta `backend/`.

### 1.2. Frontend

Abra um **segundo terminal** (deixe o backend rodando no primeiro):

```powershell
cd projeto-eventos/frontend

# qualquer servidor estático funciona. Com Python já instalado:
python -m http.server 5500
```

Agora abra `http://127.0.0.1:5500` no navegador.

> Por que não abrir o `index.html` direto com duplo clique?
> Alguns navegadores bloqueiam `fetch()` em arquivos abertos via `file://`.
> Servir por `http.server` (ou a extensão "Live Server" do VS Code) evita esse problema.

Se o indicador no topo da página mostrar **"API conectada"** (ponto verde), está tudo certo.
Se mostrar **"API offline"**, confirme que o terminal do backend ainda está rodando.

---

## 2. Subindo as alterações para o GitHub com o GitHub Desktop

Como o seu repositório `ZZugzwang/M-todos-` é um **fork**, o fluxo é:

1. **Abra o GitHub Desktop** e clone o repositório, se ainda não tiver feito isso:
   `File → Clone repository → ZZugzwang/M-todos-`

2. **Copie os arquivos deste projeto** para dentro da pasta local do repositório clonado.
   Por exemplo, se o GitHub Desktop clonou em `C:\Users\SeuUsuario\Documents\GitHub\M-todos-`,
   copie as pastas `backend/` e `frontend/` (e este `README.md`) para dentro dela, ficando assim:

   ```
   M-todos-/
   ├── 1qst.ipynb          (já existia)
   ├── backend/
   │   ├── main.py
   │   └── requirements.txt
   ├── frontend/
   │   ├── index.html
   │   ├── style.css
   │   └── script.js
   └── README.md
   ```

   > Dica: pode apagar o `main.py` antigo da raiz, já que ele foi incorporado e
   > refinado dentro de `backend/main.py` — ou deixá-lo como histórico, fica a seu critério.

3. **Volte ao GitHub Desktop.** Ele vai detectar automaticamente todos os arquivos novos/alterados
   na aba **"Changes"** (lado esquerdo), mostrando um diff de cada arquivo.

4. **Adicione um `.gitignore`** (se ainda não existir) para não subir o ambiente virtual nem o banco de dados:

   Crie um arquivo `.gitignore` na raiz do repositório com:
   ```
   venv/
   __pycache__/
   *.pyc
   backend/eventos.db
   ```

5. **Escreva uma mensagem de commit** no campo inferior esquerdo, por exemplo:
   `"Adiciona front-end e refina API de gerenciamento de eventos"`

6. Clique em **"Commit to main"**.

7. Clique em **"Push origin"** no topo da janela para enviar as alterações para o seu fork no GitHub.

8. Pronto — confira em `https://github.com/ZZugzwang/M-todos-` se os arquivos apareceram.

> Se quiser eventualmente contribuir de volta para o repositório original
> (`hungryteam-43/M-todos-`), o GitHub Desktop também tem o botão **"Branch → Create Pull Request"**,
> mas isso só faz sentido se for combinado com o dono do repositório original.

---

## 3. Possíveis ajustes futuros

- Trocar SQLite por PostgreSQL quando for hospedar de verdade (troque só a `DATABASE_URL`).
- Autenticação simples para a criação/exclusão de eventos (hoje qualquer pessoa que acessa o front pode criar/excluir).
- Upload de imagem em vez de URL.
- Paginação na listagem se o número de eventos crescer muito.
