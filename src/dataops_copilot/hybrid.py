"""Pinned public E5 ONNX + local Qdrant + BM25, rank fusion, distinct document top-3."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import numpy as np
import onnxruntime as ort
from qdrant_client import QdrantClient, models
from rank_bm25 import BM25Okapi
from tokenizers import Tokenizer

from .models import RetrievalHit
from .knowledge_summaries import SUMMARIES
from .local_paths import WORK

ROOT=Path(__file__).resolve().parents[2]
KNOWLEDGE=Path(__file__).parent/'runbooks'


def terms(text):
    words=re.findall(r'[a-z0-9_]+|[가-힣]+',text.lower())
    return words+[word[i:i+2] for word in words if re.fullmatch('[가-힣]+',word) for i in range(len(word)-1)]


def evidence_query(evidence):
    """Use observations, never case ID, labels, or gold answers, for the retrieval query."""
    parts=[]
    logs=[]
    for e in evidence:
        if e.status != 'success' or not e.data:
            continue
        d=e.data
        if e.kind=='get_task_context':
            lines=d.get('log_lines',[])
            # Domain errors outrank generic Airflow wrapper tracebacks; no answer labels are used.
            chosen=[s for s in lines if re.search(r'column .+does not exist|not_null|connection refused|authentication failed|translate host|NXDOMAIN|unique.+fail',s,re.I)]
            logs.extend(chosen[-4:] or [s for s in lines if re.search('error|failed|unavailable',s,re.I)][-1:])
        elif e.kind=='get_dbt_artifacts':
            parts.extend(str(d[k]) for k in ('issue','column_id','message','connection_id') if d.get(k))
    text=' '.join(parts+logs)
    text=re.sub(r'/Users/[^\s\"\']+|[a-f0-9]{24,}', ' ', text)
    return text[:2500] or '자료 누락 unavailable evidence'


class E5Encoder:
    def __init__(self, directory=None):
        self.directory=Path(directory or WORK/'models/e5-small')
        if not (self.directory/'tokenizer.json').is_file():
            raise RuntimeError('LOCAL_E5_MODEL_MISSING_RUN_SETUP_RAG_MODEL')
        self.tokenizer=Tokenizer.from_file(str(self.directory/'tokenizer.json'))
        options=ort.SessionOptions()
        options.intra_op_num_threads=2
        options.inter_op_num_threads=1
        self.session=ort.InferenceSession(str(self.directory/'onnx/model_qint8_avx512_vnni.onnx'),sess_options=options,providers=['CPUExecutionProvider'])
        self.names={i.name for i in self.session.get_inputs()}

    def encode(self,texts,prefix):
        results=[]
        for offset in range(0,len(texts),8):
            enc=self.tokenizer.encode_batch([prefix+t for t in texts[offset:offset+8]])
            if any(len(x.ids)>512 for x in enc):
                raise ValueError('E5_INPUT_OVER_512_TOKENS')
            size=max(len(x.ids) for x in enc)
            ids=np.ones((len(enc),size),dtype=np.int64)
            mask=np.zeros_like(ids)
            for row,x in enumerate(enc):
                ids[row,:len(x.ids)]=x.ids
                mask[row,:len(x.ids)]=1
            feed={'input_ids':ids,'attention_mask':mask}
            if 'token_type_ids' in self.names: feed['token_type_ids']=np.zeros_like(ids)
            hidden=self.session.run(None,feed)[0]
            pooled=(hidden*mask[...,None]).sum(axis=1)/mask.sum(axis=1,keepdims=True)
            pooled/=np.maximum(np.linalg.norm(pooled,axis=1,keepdims=True),1e-12)
            results.extend(pooled.astype(np.float32).tolist())
        return results


class HybridRunbooks:
    collection='runbooks'
    def __init__(self,index_path=None,encoder=None):
        self.encoder=encoder or E5Encoder()
        self.path=Path(index_path or WORK/'rag-index')
        self.path.mkdir(parents=True,exist_ok=True)
        manifest=json.loads((KNOWLEDGE/'manifest.json').read_text())
        model=json.loads((ROOT/'deployment/embedding-model.json').read_text())
        texts=[]
        self.chunks=[]
        tok=self.encoder.tokenizer
        corpus_hash=hashlib.sha256()
        for item in manifest:
            if item['kind'] not in ('runbook','synthetic_history') or '/' in item['path'] or '..' in item['path']:
                raise ValueError('KNOWLEDGE_MANIFEST_NOT_ALLOWLISTED')
            content=(KNOWLEDGE/item['path']).read_text()
            corpus_hash.update(content.encode())
            corpus_hash.update(SUMMARIES[item['doc_id']].encode())
            title=content.splitlines()[0]
            # Tokenizer offsets preserve the original text; title+prefix are included in the limit.
            prefix_tokens=len(tok.encode('passage: '+title+'\n').ids)
            capacity=350-prefix_tokens-2
            encoding=tok.encode(content,add_special_tokens=False)
            for n,start in enumerate(range(0,len(encoding.ids),capacity-50)):
                stop=min(start+capacity,len(encoding.ids))
                a,b=encoding.offsets[start][0],encoding.offsets[stop-1][1]
                text=title+'\n'+content[a:b]
                if len(tok.encode('passage: '+text).ids)>350:
                    raise ValueError('CHUNK_TOKEN_BOUND_EXCEEDED')
                texts.append(text)
                self.chunks.append({'doc_id':item['doc_id'],'doc_version':item['version'],'chunk_id':item['doc_id']+f':{n}',
                    'content':text,'content_hash':hashlib.sha256(text.encode()).hexdigest(),'document_hash':hashlib.sha256(content.encode()).hexdigest(),
                    'tokens_with_prefix':len(tok.encode('passage: '+text).ids),'kind':item['kind']})
                if stop==len(encoding.ids):break
        policy={'model_revision':model['revision'],'variant':model['variant'],'corpus_hash':corpus_hash.hexdigest(),'chunk_max_tokens':350,'overlap_tokens':50,'rrf_k':60,'candidate_k':10,'distinct_documents':3}
        self.version='hybrid-e5-bm25-rrf-'+hashlib.sha256(json.dumps(policy,sort_keys=True).encode()).hexdigest()[:16]
        self.client=QdrantClient(path=str(self.path),force_disable_check_same_thread=True)
        stored=self.path/'index-metadata.json'
        existing=json.loads(stored.read_text()) if stored.exists() else {}
        if existing.get('version')!=self.version or not self.client.collection_exists(self.collection):
            if self.client.collection_exists(self.collection):self.client.delete_collection(self.collection)
            self.client.create_collection(self.collection,vectors_config=models.VectorParams(size=384,distance=models.Distance.COSINE))
            vectors=self.encoder.encode(texts,'passage: ')
            self.client.upsert(self.collection,[models.PointStruct(id=i,vector=v,payload=self.chunks[i]) for i,v in enumerate(vectors)],wait=True)
            stored.write_text(json.dumps({'version':self.version,**policy,'documents':len(manifest),'chunks':len(texts),'model':model['model']},indent=2)+'\n')
        self.bm25=BM25Okapi([terms(t) for t in texts])
        self.last_ranking={}

    async def search(self,query):
        # Query truncation uses E5 token boundaries, including query prefix and special tokens.
        encoded=self.encoder.tokenizer.encode(query,add_special_tokens=False)
        if len(encoded.ids)>480:
            query=query[:encoded.offsets[479][1]]
        sparse=self.bm25.get_scores(terms(query))
        bm=sorted(range(len(sparse)),key=lambda i:(-sparse[i],i))[:10]
        dense=self.client.query_points(self.collection,query=self.encoder.encode([query],'query: ')[0],limit=10,with_payload=False).points
        de=[int(p.id) for p in dense]
        scores={}
        for ranking in (bm,de):
            for rank,i in enumerate(ranking,1):scores[i]=scores.get(i,0)+1/(60+rank)
        ranked=sorted(scores,key=lambda i:(-scores[i],i))
        selected=[]
        docs=set()
        for i in ranked:
            chunk=self.chunks[i]
            if chunk['doc_id'] not in docs:
                docs.add(chunk['doc_id'])
                selected.append(RetrievalHit(**{k:chunk[k] for k in ('doc_id','doc_version','chunk_id','content_hash','content')},rank=len(selected)+1,method='bm25_e5_qdrant_rrf_k60',llm_summary=SUMMARIES[chunk['doc_id']]))
            if len(selected)==3:break
        self.last_ranking={'bm25_chunk_ids':[self.chunks[i]['chunk_id'] for i in bm],'dense_chunk_ids':[self.chunks[i]['chunk_id'] for i in de],
            'top3_doc_ids':[h.doc_id for h in selected],'query_sha256':hashlib.sha256(query.encode()).hexdigest()}
        return selected

    def close(self):self.client.close()
