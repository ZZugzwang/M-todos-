
#bolinha de golfe
from fastapi import FastAPI, HTTPException, Depends
from sqlalchemy import create_engine, Column, Integer, String, DateTime, ForeignKey, Table
from sqlalchemy.orm import declarative_base, sessionmaker, Session, relationship
from datetime import datetime
from collections import deque
from typing import List

# ==============================================================================
# 1. CONFIGURAÇÃO DO BANCO DE DADOS (SQLite para persistência)
# ==============================================================================
DATABASE_URL = "sqlite:///./eventos.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Tabela intermediária de relacionamento Muitos-para-Muitos (Inscrições Confirmadas)
inscricoes_confirmadas = Table(
    'inscricoes_confirmadas', Base.metadata,
    Column('evento_id', Integer, ForeignKey('eventos.id')),
    Column('participante_id', Integer, ForeignKey('participantes.id'))
)

class EventoDB(Base):
    __tablename__ = "eventos"
    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String, unique=True, index=True)
    data = Column(DateTime, index=True)
    lotacao_maxima = Column(Integer)
    
    # Listas/Relacionamentos do Banco de Dados
    inscritos = relationship("ParticipanteDB", secondary=inscricoes_confirmadas, back_populates="eventos")
    fila_espera = relationship("FilaEsperaDB", back_populates="evento", cascade="all, delete-orphan")

class ParticipanteDB(Base):
    __tablename__ = "participantes"
    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String, unique=True)
    eventos = relationship("EventoDB", secondary=inscricoes_confirmadas, back_populates="inscritos")

class FilaEsperaDB(Base):
    __tablename__ = "fila_espera"
    id = Column(Integer, primary_key=True, index=True)
    evento_id = Column(Integer, ForeignKey("eventos.id"))
    participante_nome = Column(String)
    posicao = Column(Integer) # Garante a ordem FIFO da fila no banco
    evento = relationship("EventoDB", back_populates="fila_espera")

Base.metadata.create_all(bind=engine)

# Dependência para injetar a sessão do banco nas rotas
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ==============================================================================
# 2. CONCEITO: ÁRVORE BINÁRIA DE BUSCA (BST) - Processamento em Memória
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

# ==============================================================================
# 3. ENDPOINTS DA API REST (FastAPI)
# ==============================================================================
app = FastAPI(title="Sistema de Gerenciamento de Eventos", version="1.0")

@app.post("/eventos/", tags=["Eventos"])
def cadastrar_evento(nome: str, data_iso: str, lotacao: int, db: Session = Depends(get_db)):
    """Cadastra um novo evento no sistema."""
    try:
        data_formatada = datetime.fromisoformat(data_iso)
    except ValueError:
        raise HTTPException(status_code=400, detail="Formato de data inválido. Use AAAA-MM-DD")
        
    if db.query(EventoDB).filter(EventoDB.nome == nome).first():
        raise HTTPException(status_code=400, detail="Já existe um evento com este nome.")
        
    novo_evento = EventoDB(nome=nome, data=data_formatada, lotacao_maxima=lotacao)
    db.add(novo_evento)
    db.commit()
    return {"status": "Sucesso", "mensagem": f"Evento '{nome}' criado!"}

@app.post("/eventos/{evento_id}/inscrever", tags=["Inscrições"])
def inscrever_participante(evento_id: int, nome_participante: str, db: Session = Depends(get_db)):
    """Inscreve um participante ou o coloca na fila de espera caso lote."""
    evento = db.query(EventoDB).filter(EventoDB.id == evento_id).first()
    if not evento:
        raise HTTPException(status_code=404, detail="Evento não encontrado.")

    # Busca ou cria o participante
    participante = db.query(ParticipanteDB).filter(ParticipanteDB.nome == nome_participante).first()
    if not participante:
        participante = ParticipanteDB(nome=nome_participante)
        db.add(participante)
        db.commit()

    # Verifica Lotação (Conceito de Listas/Controle de Capacidade)
    if len(evento.inscritos) < evento.lotacao_maxima:
        if participante in evento.inscritos:
            return {"status": "Aviso", "mensagem": "Participante já inscrito."}
        evento.inscritos.append(participante)
        db.commit()
        return {"status": "Sucesso", "mensagem": f"{nome_participante} inscrito com sucesso!"}
    else:
        # Conceito de Fila de Espera (FIFO persistido)
        ultima_posicao = db.query(FilaEsperaDB).filter(FilaEsperaDB.evento_id == evento_id).count()
        nova_espera = FilaEsperaDB(evento_id=evento_id, participante_nome=nome_participante, posicao=ultima_posicao + 1)
        db.add(nova_espera)
        db.commit()
        return {"status": "Fila de Espera", "mensagem": f"Evento lotado. {nome_participante} foi adicionado à fila de espera."}

@app.delete("/eventos/{evento_id}/cancelar", tags=["Inscrições"])
def cancelar_inscricao(evento_id: int, nome_participante: str, db: Session = Depends(get_db)):
    """Remove a inscrição e puxa automaticamente o próximo da fila de espera."""
    evento = db.query(EventoDB).filter(EventoDB.id == evento_id).first()
    participante = db.query(ParticipanteDB).filter(ParticipanteDB.nome == nome_participante).first()
    
    if not evento or not participante:
        raise HTTPException(status_code=404, detail="Evento ou participante inválido.")

    if participante in evento.inscritos:
        evento.inscritos.remove(participante)
        db.commit()
        
        # Puxa o próximo da fila de espera (Lógica de Fila FIFO)
        proximo_fila = db.query(FilaEsperaDB).filter(FilaEsperaDB.evento_id == evento_id).order_by(FilaEsperaDB.posicao.asc()).first()
        if proximo_fila:
            # Puxa da fila e insere no evento
            novo_inscrito = db.query(ParticipanteDB).filter(ParticipanteDB.nome == proximo_fila.participante_nome).first()
            if novo_inscrito:
                evento.inscritos.append(novo_inscrito)
            
            db.delete(proximo_fila)
            db.commit()
            return {"status": "Cancelado", "mensagem": f"Inscrição cancelada. Próximo da fila ({proximo_fila.participante_nome}) foi inscrito!"}
            
        return {"status": "Cancelado", "mensagem": "Inscrição cancelada com sucesso."}
    
    raise HTTPException(status_code=400, detail="Participante não está inscrito neste evento.")

@app.get("/eventos/buscar/data", tags=["Buscas"])
def buscar_por_data(data_iso: str, db: Session = Depends(get_db)):
    """Busca sequencial simplificada utilizando filtros por data."""
    data_busca = datetime.fromisoformat(data_iso)
    eventos = db.query(EventoDB).filter(Base.metadata.tables['eventos'].c.data == data_busca).all()
    return [{"id": e.id, "nome": e.nome, "data": e.data.strftime('%Y-%m-%d')} for e in eventos]

@app.get("/eventos/relatorio-ordenado", tags=["Relatórios (Extras)"])
def relatorio_ordenado(db: Session = Depends(get_db)):
    """Gera um relatório alfabético usando a estrutura de Árvore de Busca (BST)."""
    arvore = construir_arvore_do_banco(db)
    lista_ordenada = []
    arvore.percorrer_em_ordem(arvore.raiz, lista_ordenada)
    
    resposta = []
    for e in lista_ordenada:
        fila = db.query(FilaEsperaDB).filter(FilaEsperaDB.evento_id == e.id).order_by(FilaEsperaDB.posicao.asc()).all()
        resposta.append({
            "id": e.id,
            "nome": e.nome,
            "data": e.data.strftime('%Y-%m-%d'),
            "vagas_ocupadas": f"{len(e.inscritos)}/{e.lotacao_maxima}",
            "fila_espera": [f.participante_nome for f in fila]
        })
    return resposta
