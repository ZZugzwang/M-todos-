"""
Sistema de Gerenciamento de Eventos (Shows) — API
Refinado a partir do projeto original de Métodos Computacionais (IF264).

Conceitos de estruturas de dados mantidos e expandidos:
- BST (Árvore Binária de Busca) para relatório ordenado em memória
- Fila FIFO persistida para lista de espera
- Relacionamento muitos-para-muitos (eventos <-> participantes)

Sistema de usuários:
- Senhas nunca são guardadas em texto puro: usamos PBKDF2-HMAC-SHA256
  (biblioteca padrão do Python — sem dependências externas que possam
  falhar ao compilar, como aconteceu com pydantic-core).
- Login gera um token opaco (string aleatória) guardado na tabela
  `sessoes`. O front envia esse token no header Authorization: Bearer <token>.
- Só o usuário que criou um evento pode editá-lo ou excluí-lo.
"""

import hashlib
import secrets
from datetime import datetime
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import (
    create_engine, Column, Integer, String, Float, DateTime, ForeignKey, Table
)
from sqlalchemy.orm import declarative_base, sessionmaker, Session, relationship
from pydantic import BaseModel, field_validator

# ==============================================================================
# 1. CONFIGURAÇÃO DO BANCO DE DADOS (SQLite para persistência)
# ==============================================================================
DATABASE_URL = "sqlite:///./eventos.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Tabela intermediária de relacionamento Muitos-para-Muitos (Inscrições Confirmadas)
inscricoes_confirmadas = Table(
    "inscricoes_confirmadas",
    Base.metadata,
    Column("evento_id", Integer, ForeignKey("eventos.id", ondelete="CASCADE")),
    Column("participante_id", Integer, ForeignKey("participantes.id", ondelete="CASCADE")),
)


class UsuarioDB(Base):
    __tablename__ = "usuarios"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    senha_hash = Column(String, nullable=False)
    criado_em = Column(DateTime, default=datetime.utcnow)

    eventos = relationship("EventoDB", back_populates="criador")


class SessaoDB(Base):
    __tablename__ = "sessoes"

    token = Column(String, primary_key=True, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id", ondelete="CASCADE"))
    criado_em = Column(DateTime, default=datetime.utcnow)

    usuario = relationship("UsuarioDB")


class EventoDB(Base):
    __tablename__ = "eventos"

    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String, unique=True, index=True, nullable=False)
    descricao = Column(String, default="")
    local = Column(String, default="A definir")
    categoria = Column(String, default="Geral", index=True)
    imagem_url = Column(String, default="")
    preco = Column(Float, default=0.0)
    data = Column(DateTime, index=True, nullable=False)
    lotacao_maxima = Column(Integer, nullable=False)
    criado_em = Column(DateTime, default=datetime.utcnow)
    criador_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)

    criador = relationship("UsuarioDB", back_populates="eventos")
    inscritos = relationship(
        "ParticipanteDB", secondary=inscricoes_confirmadas, back_populates="eventos"
    )
    fila_espera = relationship(
        "FilaEsperaDB", back_populates="evento", cascade="all, delete-orphan"
    )


class ParticipanteDB(Base):
    __tablename__ = "participantes"

    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String, unique=True, nullable=False)
    email = Column(String, default="")

    eventos = relationship(
        "EventoDB", secondary=inscricoes_confirmadas, back_populates="inscritos"
    )


class FilaEsperaDB(Base):
    __tablename__ = "fila_espera"

    id = Column(Integer, primary_key=True, index=True)
    evento_id = Column(Integer, ForeignKey("eventos.id", ondelete="CASCADE"))
    participante_nome = Column(String)
    posicao = Column(Integer)  # Garante a ordem FIFO da fila no banco

    evento = relationship("EventoDB", back_populates="fila_espera")


Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ==============================================================================
# 2. SENHAS E TOKENS (sem dependências externas)
# ==============================================================================
def gerar_hash_senha(senha: str) -> str:
    """PBKDF2-HMAC-SHA256 com salt aleatório. Formato salvo: 'salt$hash'."""
    salt = secrets.token_hex(16)
    hash_bytes = hashlib.pbkdf2_hmac("sha256", senha.encode("utf-8"), bytes.fromhex(salt), 100_000)
    return f"{salt}${hash_bytes.hex()}"


def verificar_senha(senha: str, hash_armazenado: str) -> bool:
    try:
        salt, hash_hex = hash_armazenado.split("$")
        novo_hash = hashlib.pbkdf2_hmac("sha256", senha.encode("utf-8"), bytes.fromhex(salt), 100_000)
        return secrets.compare_digest(novo_hash.hex(), hash_hex)
    except (ValueError, AttributeError):
        return False


def gerar_token() -> str:
    return secrets.token_hex(32)


def get_usuario_opcional(
    authorization: Optional[str] = Header(None), db: Session = Depends(get_db)
) -> Optional[UsuarioDB]:
    """Não derruba a requisição se não houver login — usado em rotas públicas
    que só precisam SABER quem está logado (ex: para calcular 'pode_editar')."""
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization.removeprefix("Bearer ").strip()
    sessao = db.query(SessaoDB).filter(SessaoDB.token == token).first()
    return sessao.usuario if sessao else None


def get_usuario_atual(
    usuario: Optional[UsuarioDB] = Depends(get_usuario_opcional),
) -> UsuarioDB:
    """Usado em rotas que EXIGEM login (criar/editar/excluir evento)."""
    if not usuario:
        raise HTTPException(status_code=401, detail="Você precisa estar logado para fazer isso.")
    return usuario


# ==============================================================================
# 3. SCHEMAS (Pydantic) — validação de entrada/saída
# ==============================================================================
class UsuarioCreate(BaseModel):
    username: str
    senha: str

    @field_validator("username")
    @classmethod
    def username_valido(cls, v):
        v = v.strip()
        if len(v) < 3:
            raise ValueError("o nome de usuário precisa ter pelo menos 3 caracteres")
        return v

    @field_validator("senha")
    @classmethod
    def senha_valida(cls, v):
        if len(v) < 4:
            raise ValueError("a senha precisa ter pelo menos 4 caracteres")
        return v


class EventoCreate(BaseModel):
    nome: str
    descricao: str = ""
    local: str = "A definir"
    categoria: str = "Geral"
    imagem_url: str = ""
    preco: float = 0.0
    data_iso: str
    lotacao_maxima: int

    @field_validator("lotacao_maxima")
    @classmethod
    def lotacao_positiva(cls, v):
        if v <= 0:
            raise ValueError("lotacao_maxima deve ser maior que zero")
        return v

    @field_validator("nome")
    @classmethod
    def nome_nao_vazio(cls, v):
        if not v.strip():
            raise ValueError("nome não pode ser vazio")
        return v.strip()


class InscricaoCreate(BaseModel):
    nome_participante: str
    email: Optional[str] = ""


# ==============================================================================
# 4. CONCEITO: ÁRVORE BINÁRIA DE BUSCA (BST) - Processamento em Memória
# ==============================================================================
class NodoEvento:
    def __init__(self, evento: EventoDB):
        self.evento = evento
        self.esquerda = None
        self.direita = None


class ArvoreEventos:
    def __init__(self):
        self.raiz = None

    def inserir(self, evento: EventoDB):
        if not self.raiz:
            self.raiz = NodoEvento(evento)
        else:
            self._inserir_recursivo(self.raiz, evento)

    def _inserir_recursivo(self, atual, evento):
        if evento.nome.lower() < atual.evento.nome.lower():
            if not atual.esquerda:
                atual.esquerda = NodoEvento(evento)
            else:
                self._inserir_recursivo(atual.esquerda, evento)
        else:
            if not atual.direita:
                atual.direita = NodoEvento(evento)
            else:
                self._inserir_recursivo(atual.direita, evento)

    def percorrer_em_ordem(self, atual, resultado: List[EventoDB]):
        if atual:
            self.percorrer_em_ordem(atual.esquerda, resultado)
            resultado.append(atual.evento)
            self.percorrer_em_ordem(atual.direita, resultado)


def construir_arvore_do_banco(db: Session) -> ArvoreEventos:
    arvore = ArvoreEventos()
    eventos = db.query(EventoDB).all()
    for e in eventos:
        arvore.inserir(e)
    return arvore


def serializar_evento(e: EventoDB, db: Session, usuario_atual: Optional[UsuarioDB] = None) -> dict:
    fila = (
        db.query(FilaEsperaDB)
        .filter(FilaEsperaDB.evento_id == e.id)
        .order_by(FilaEsperaDB.posicao.asc())
        .all()
    )
    return {
        "id": e.id,
        "nome": e.nome,
        "descricao": e.descricao,
        "local": e.local,
        "categoria": e.categoria,
        "imagem_url": e.imagem_url,
        "preco": e.preco,
        "data": e.data.strftime("%Y-%m-%d"),
        "lotacao_maxima": e.lotacao_maxima,
        "vagas_ocupadas": len(e.inscritos),
        "vagas_restantes": max(e.lotacao_maxima - len(e.inscritos), 0),
        "esgotado": len(e.inscritos) >= e.lotacao_maxima,
        "fila_espera": [f.participante_nome for f in fila],
        "inscritos": [p.nome for p in e.inscritos],
        "criador": e.criador.username if e.criador else None,
        "pode_editar": bool(usuario_atual and e.criador_id == usuario_atual.id),
    }


# ==============================================================================
# 5. ENDPOINTS DA API REST (FastAPI)
# ==============================================================================
app = FastAPI(title="Sistema de Gerenciamento de Eventos (Shows)", version="3.0")

# CORS liberado para o frontend rodar em outra porta/origem durante o desenvolvimento
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ----- Usuários -----
@app.post("/usuarios/registrar", tags=["Usuários"])
def registrar(payload: UsuarioCreate, db: Session = Depends(get_db)):
    """Cria uma conta nova e já retorna um token de sessão (login automático)."""
    if db.query(UsuarioDB).filter(UsuarioDB.username == payload.username).first():
        raise HTTPException(status_code=400, detail="Esse nome de usuário já está em uso.")

    usuario = UsuarioDB(username=payload.username, senha_hash=gerar_hash_senha(payload.senha))
    db.add(usuario)
    db.commit()
    db.refresh(usuario)

    token = gerar_token()
    db.add(SessaoDB(token=token, usuario_id=usuario.id))
    db.commit()
    return {"token": token, "username": usuario.username}


@app.post("/usuarios/login", tags=["Usuários"])
def login(payload: UsuarioCreate, db: Session = Depends(get_db)):
    usuario = db.query(UsuarioDB).filter(UsuarioDB.username == payload.username).first()
    if not usuario or not verificar_senha(payload.senha, usuario.senha_hash):
        raise HTTPException(status_code=401, detail="Usuário ou senha incorretos.")

    token = gerar_token()
    db.add(SessaoDB(token=token, usuario_id=usuario.id))
    db.commit()
    return {"token": token, "username": usuario.username}


@app.post("/usuarios/logout", tags=["Usuários"])
def logout(authorization: Optional[str] = Header(None), db: Session = Depends(get_db)):
    if authorization and authorization.startswith("Bearer "):
        token = authorization.removeprefix("Bearer ").strip()
        db.query(SessaoDB).filter(SessaoDB.token == token).delete()
        db.commit()
    return {"status": "Sucesso"}


@app.get("/usuarios/me", tags=["Usuários"])
def usuario_atual(usuario: UsuarioDB = Depends(get_usuario_atual)):
    return {"username": usuario.username}


# ----- Eventos -----
@app.get("/eventos/", tags=["Eventos"])
def listar_eventos(
    categoria: Optional[str] = None,
    db: Session = Depends(get_db),
    usuario: Optional[UsuarioDB] = Depends(get_usuario_opcional),
):
    """Lista todos os eventos, com filtro opcional por categoria."""
    query = db.query(EventoDB)
    if categoria:
        query = query.filter(EventoDB.categoria.ilike(categoria))
    eventos = query.order_by(EventoDB.data.asc()).all()
    return [serializar_evento(e, db, usuario) for e in eventos]


@app.get("/eventos/buscar/data", tags=["Buscas"])
def buscar_por_data(
    data_iso: str,
    db: Session = Depends(get_db),
    usuario: Optional[UsuarioDB] = Depends(get_usuario_opcional),
):
    """Busca eventos que ocorrem em uma data específica (AAAA-MM-DD)."""
    try:
        data_busca = datetime.fromisoformat(data_iso).date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Formato de data inválido. Use AAAA-MM-DD")

    eventos = db.query(EventoDB).all()
    encontrados = [e for e in eventos if e.data.date() == data_busca]
    return [serializar_evento(e, db, usuario) for e in encontrados]


@app.get("/eventos/relatorio-ordenado", tags=["Relatórios (Extras)"])
def relatorio_ordenado(
    db: Session = Depends(get_db),
    usuario: Optional[UsuarioDB] = Depends(get_usuario_opcional),
):
    """Gera um relatório alfabético usando a estrutura de Árvore de Busca (BST)."""
    arvore = construir_arvore_do_banco(db)
    lista_ordenada: List[EventoDB] = []
    arvore.percorrer_em_ordem(arvore.raiz, lista_ordenada)
    return [serializar_evento(e, db, usuario) for e in lista_ordenada]


# IMPORTANTE: esta rota com parâmetro dinâmico {evento_id} deve vir DEPOIS
# das rotas de caminho fixo acima (/buscar/data, /relatorio-ordenado),
# senão o FastAPI tenta casar "buscar" ou "relatorio-ordenado" como se
# fossem um evento_id e retorna erro 422.
@app.get("/eventos/{evento_id}", tags=["Eventos"])
def obter_evento(
    evento_id: int,
    db: Session = Depends(get_db),
    usuario: Optional[UsuarioDB] = Depends(get_usuario_opcional),
):
    """Retorna o detalhe de um evento específico."""
    evento = db.query(EventoDB).filter(EventoDB.id == evento_id).first()
    if not evento:
        raise HTTPException(status_code=404, detail="Evento não encontrado.")
    return serializar_evento(evento, db, usuario)


@app.post("/eventos/", tags=["Eventos"])
def cadastrar_evento(
    payload: EventoCreate,
    db: Session = Depends(get_db),
    usuario: UsuarioDB = Depends(get_usuario_atual),
):
    """Cadastra um novo evento no sistema. Exige login — o usuário logado vira o dono do evento."""
    try:
        data_formatada = datetime.fromisoformat(payload.data_iso)
    except ValueError:
        raise HTTPException(status_code=400, detail="Formato de data inválido. Use AAAA-MM-DD")

    if db.query(EventoDB).filter(EventoDB.nome == payload.nome).first():
        raise HTTPException(status_code=400, detail="Já existe um evento com este nome.")

    novo_evento = EventoDB(
        nome=payload.nome,
        descricao=payload.descricao,
        local=payload.local,
        categoria=payload.categoria,
        imagem_url=payload.imagem_url,
        preco=payload.preco,
        data=data_formatada,
        lotacao_maxima=payload.lotacao_maxima,
        criador_id=usuario.id,
    )
    db.add(novo_evento)
    db.commit()
    db.refresh(novo_evento)
    return serializar_evento(novo_evento, db, usuario)


@app.put("/eventos/{evento_id}", tags=["Eventos"])
def editar_evento(
    evento_id: int,
    payload: EventoCreate,
    db: Session = Depends(get_db),
    usuario: UsuarioDB = Depends(get_usuario_atual),
):
    """Edita um evento existente. Só o criador do evento pode editar."""
    evento = db.query(EventoDB).filter(EventoDB.id == evento_id).first()
    if not evento:
        raise HTTPException(status_code=404, detail="Evento não encontrado.")
    if evento.criador_id != usuario.id:
        raise HTTPException(status_code=403, detail="Só quem criou este evento pode editá-lo.")

    try:
        data_formatada = datetime.fromisoformat(payload.data_iso)
    except ValueError:
        raise HTTPException(status_code=400, detail="Formato de data inválido. Use AAAA-MM-DD")

    nome_em_uso = (
        db.query(EventoDB)
        .filter(EventoDB.nome == payload.nome, EventoDB.id != evento_id)
        .first()
    )
    if nome_em_uso:
        raise HTTPException(status_code=400, detail="Já existe outro evento com este nome.")

    evento.nome = payload.nome
    evento.descricao = payload.descricao
    evento.local = payload.local
    evento.categoria = payload.categoria
    evento.imagem_url = payload.imagem_url
    evento.preco = payload.preco
    evento.data = data_formatada
    evento.lotacao_maxima = payload.lotacao_maxima
    db.commit()
    db.refresh(evento)
    return serializar_evento(evento, db, usuario)


@app.delete("/eventos/{evento_id}", tags=["Eventos"])
def remover_evento(
    evento_id: int,
    db: Session = Depends(get_db),
    usuario: UsuarioDB = Depends(get_usuario_atual),
):
    """Remove um evento e tudo que está relacionado a ele (fila, inscrições). Só o criador pode excluir."""
    evento = db.query(EventoDB).filter(EventoDB.id == evento_id).first()
    if not evento:
        raise HTTPException(status_code=404, detail="Evento não encontrado.")
    if evento.criador_id != usuario.id:
        raise HTTPException(status_code=403, detail="Só quem criou este evento pode excluí-lo.")

    db.delete(evento)
    db.commit()
    return {"status": "Sucesso", "mensagem": "Evento removido."}


# ----- Inscrições (continuam públicas: qualquer visitante pode se inscrever) -----
@app.post("/eventos/{evento_id}/inscrever", tags=["Inscrições"])
def inscrever_participante(
    evento_id: int, payload: InscricaoCreate, db: Session = Depends(get_db)
):
    """Inscreve um participante ou o coloca na fila de espera caso lote."""
    evento = db.query(EventoDB).filter(EventoDB.id == evento_id).first()
    if not evento:
        raise HTTPException(status_code=404, detail="Evento não encontrado.")

    nome_participante = payload.nome_participante.strip()
    if not nome_participante:
        raise HTTPException(status_code=400, detail="Nome do participante é obrigatório.")

    participante = (
        db.query(ParticipanteDB).filter(ParticipanteDB.nome == nome_participante).first()
    )
    if not participante:
        participante = ParticipanteDB(nome=nome_participante, email=payload.email or "")
        db.add(participante)
        db.commit()
        db.refresh(participante)

    if participante in evento.inscritos:
        return {"status": "Aviso", "mensagem": "Participante já inscrito."}

    if len(evento.inscritos) < evento.lotacao_maxima:
        evento.inscritos.append(participante)
        db.commit()
        return {"status": "Sucesso", "mensagem": f"{nome_participante} inscrito com sucesso!"}
    else:
        ultima_posicao = (
            db.query(FilaEsperaDB).filter(FilaEsperaDB.evento_id == evento_id).count()
        )
        nova_espera = FilaEsperaDB(
            evento_id=evento_id,
            participante_nome=nome_participante,
            posicao=ultima_posicao + 1,
        )
        db.add(nova_espera)
        db.commit()
        return {
            "status": "Fila de Espera",
            "mensagem": f"Evento lotado. {nome_participante} foi adicionado à fila de espera.",
        }


@app.delete("/eventos/{evento_id}/cancelar", tags=["Inscrições"])
def cancelar_inscricao(
    evento_id: int, nome_participante: str, db: Session = Depends(get_db)
):
    """Remove a inscrição e puxa automaticamente o próximo da fila de espera."""
    evento = db.query(EventoDB).filter(EventoDB.id == evento_id).first()
    participante = (
        db.query(ParticipanteDB).filter(ParticipanteDB.nome == nome_participante).first()
    )
    if not evento or not participante:
        raise HTTPException(status_code=404, detail="Evento ou participante inválido.")

    if participante in evento.inscritos:
        evento.inscritos.remove(participante)
        db.commit()

        proximo_fila = (
            db.query(FilaEsperaDB)
            .filter(FilaEsperaDB.evento_id == evento_id)
            .order_by(FilaEsperaDB.posicao.asc())
            .first()
        )
        if proximo_fila:
            novo_inscrito = (
                db.query(ParticipanteDB)
                .filter(ParticipanteDB.nome == proximo_fila.participante_nome)
                .first()
            )
            if novo_inscrito:
                evento.inscritos.append(novo_inscrito)
                db.delete(proximo_fila)
                db.commit()
            return {
                "status": "Cancelado",
                "mensagem": f"Inscrição cancelada. Próximo da fila ({proximo_fila.participante_nome}) foi inscrito!",
            }
        return {"status": "Cancelado", "mensagem": "Inscrição cancelada com sucesso."}

    raise HTTPException(status_code=400, detail="Participante não está inscrito neste evento.")


@app.get("/categorias", tags=["Eventos"])
def listar_categorias(db: Session = Depends(get_db)):
    """Lista as categorias distintas já cadastradas, para popular filtros no front."""
    categorias = db.query(EventoDB.categoria).distinct().all()
    return sorted({c[0] for c in categorias if c[0]})
