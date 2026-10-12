"""Durable scoped local vectors; default lexical encoder, optional cached learned model/FAISS."""
import hashlib
import importlib.util
import math
import os
from pathlib import Path
from threading import RLock

from sqlalchemy import delete,select

from app.agent.tools import tokens
from app.memory.embedding import EmbeddingGateway
from app.models import IndexOutbox,LocalVector,Source,VectorDocument,new_id
from app.security.policies import BoundaryError,SourceContext,scoped_source
from app.storage import owned_query


class LexicalEncoder:
    processing_location="local"
    def embed(self,texts):
        output=[]
        for text in texts:
            vector=[0.0]*256
            for token in tokens(text):
                digest=hashlib.blake2b(token.encode(),digest_size=8).digest()
                vector[int.from_bytes(digest[:4],"little")%256]+=1 if digest[4]%2 else -1
            norm=math.sqrt(sum(value*value for value in vector)) or 1
            output.append([value/norm for value in vector])
        return output


class CachedSentenceEncoder:
    processing_location="local"
    def __init__(self,path):
        if not path.is_dir():raise BoundaryError("EMBEDDING_MODEL_NOT_CACHED",409)
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            raise BoundaryError("SEMANTIC_DEPENDENCY_MISSING",409) from None
        self.model=SentenceTransformer(str(path),local_files_only=True,trust_remote_code=False,device="cpu")
    def embed(self,texts):
        return self.model.encode(texts,normalize_embeddings=True,show_progress_bar=False,convert_to_numpy=True).tolist()


class VectorStore:
    def __init__(self,database,model_dir=None):
        self.db,self.lock=database,RLock()
        self.directory=database.path.parent/"indexes"
        self.model_path=Path(model_dir).expanduser().resolve() if model_dir else None
        self.encoder=None
        self.mode="semantic" if self.model_path else "lexical"
        if self.model_path:
            digest=hashlib.sha256()
            if not self.model_path.is_dir():raise BoundaryError("EMBEDDING_MODEL_NOT_CACHED",409)
            for file in sorted(self.model_path.rglob("*")):
                if file.is_symlink():raise BoundaryError("LINKED_MODEL_REJECTED",409)
                if file.is_file():
                    digest.update(str(file.relative_to(self.model_path)).encode())
                    with file.open("rb") as stream:
                        for chunk in iter(lambda:stream.read(1024*1024),b""):digest.update(chunk)
            self.version="cached-sentence:"+digest.hexdigest()
        else:self.version="lexical-charhash-v1:256"

    def provider(self):
        if self.encoder is None:
            self.encoder=CachedSentenceEncoder(self.model_path) if self.model_path else LexicalEncoder()
        return self.encoder

    def embed(self,ctx,texts):
        return EmbeddingGateway(self.db,self.version,self.provider).embed(ctx,texts)

    def apply(self,change):
        ctx=SourceContext(change.workspace_id,change.source_id)
        with self.lock:
            vectors=self.embed(ctx,[change.text[:16000]]) if change.operation=="upsert" else None
            with self.db.transaction() as session:
                source=scoped_source(session,ctx)
                document=session.scalar(owned_query(VectorDocument,ctx).where(VectorDocument.id==change.document_id))
                if not document or document.version!=change.version or source.index_generation!=change.generation or document.generation!=change.generation or ((change.operation=="delete") != (document.deleted_at is not None)):
                    raise BoundaryError("STALE_INDEX_WRITE",409)
                row=session.scalar(owned_query(LocalVector,ctx).where(LocalVector.document_id==document.id))
                if change.operation=="delete":
                    if row:session.delete(row)
                else:
                    if row is None:
                        row=LocalVector(workspace_id=ctx.workspace_id,source_id=ctx.source_id,document_id=document.id)
                        session.add(row)
                    row.generation,row.document_version,row.embedding_version,row.values=change.generation,change.version,self.version,vectors[0]
                    document.embedding_version=self.version

    def search(self,ctx,query,limit=10):
        if not query.strip():return []
        vector=self.embed(ctx,[query[:2000]])[0]
        with self.lock,self.db.transaction() as session:
            source=scoped_source(session,ctx)
            rows=session.execute(select(LocalVector,VectorDocument).join(VectorDocument,VectorDocument.id==LocalVector.document_id).where(
                LocalVector.source_id==ctx.source_id,LocalVector.workspace_id==ctx.workspace_id,LocalVector.generation==source.index_generation,
                LocalVector.embedding_version==self.version,VectorDocument.source_id==ctx.source_id,VectorDocument.workspace_id==ctx.workspace_id,
                VectorDocument.generation==source.index_generation,VectorDocument.kind=="email",VectorDocument.deleted_at.is_(None),
                VectorDocument.indexed_version==VectorDocument.version,LocalVector.document_version==VectorDocument.version).limit(5000)).all()
            valid=[(row,document) for row,document in rows if len(row.values)==len(vector)]
            if importlib.util.find_spec("faiss") and valid:
                import faiss
                import numpy as np
                index=faiss.IndexFlatIP(len(vector));index.add(np.asarray([row.values for row,_ in valid],dtype="float32"))
                scores,indices=index.search(np.asarray([vector],dtype="float32"),min(limit,len(valid)))
                ranked=[(float(score),valid[int(i)][1]) for score,i in zip(scores[0],indices[0]) if i>=0]
            else:
                ranked=sorted(((sum(a*b for a,b in zip(vector,row.values)),document) for row,document in valid),key=lambda item:(-item[0],item[1].id))[:limit]
            return [{"email_id":document.email_id,"document_id":document.id,"score":float(score),"mode":self.mode,"excerpt":document.text[:1000]} for score,document in ranked if score>0]

    def drop(self,ctx):
        with self.lock:
            if self.directory.exists():
                prefix=hashlib.sha256(f"{ctx.workspace_id}:{ctx.source_id}".encode()).hexdigest()
                for file in self.directory.glob(prefix+".*"):
                    target=file.resolve()
                    if target.is_relative_to(self.directory.resolve()) and target.is_file():target.unlink()

    def rebuild(self,ctx):
        with self.lock,self.db.transaction() as session:
            source=scoped_source(session,ctx);source.index_generation+=1
            session.execute(delete(LocalVector).where(LocalVector.source_id==ctx.source_id,LocalVector.workspace_id==ctx.workspace_id))
            documents=list(session.scalars(owned_query(VectorDocument,ctx).where(VectorDocument.deleted_at.is_(None))))
            for document in documents:
                document.generation=source.index_generation;document.indexed_version=None;document.embedding_version=self.version
                session.add(IndexOutbox(workspace_id=ctx.workspace_id,source_id=ctx.source_id,document_id=document.id,document_version=document.version,generation=source.index_generation))
        self.drop(ctx)
