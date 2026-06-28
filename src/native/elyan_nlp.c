/*
 * elyan_nlp.c — Elyan NLP + ML Core
 *
 * High-performance C daemon for the Elyan backend.
 * Provides: tokenization, BM25, hash embedding, cosine similarity,
 * batch scoring, fact extraction, world-signal hints, intent classification.
 *
 * Protocol: newline-delimited JSON on stdin/stdout.
 * Each request must include "_id" (string); responses echo it back.
 *
 * Compile: gcc -O2 -Wall -o bin/elyan_nlp src/native/elyan_nlp.c -lm
 *
 * Request types:
 *   ping            — health check
 *   tokenize        — Turkish-aware tokenize + stem
 *   score_bm25      — BM25 score, one document
 *   bm25_batch      — BM25 score, N documents (single IPC round-trip)
 *   embed_256       — 256-dim hash embedding (SHA-256 based, matches Node.js)
 *   cosine_sim      — cosine similarity between two float vectors
 *   extract_facts   — name / city extraction from user text
 *   derive_hints    — world signal → behavioural/situational hints
 *   classify_intent — fast Turkish/English intent label
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <stdint.h>
#include <time.h>

/* ── constants ──────────────────────────────────────────────────────── */

#define MAX_LINE          65536
#define MAX_TOKENS        512
#define MAX_TOKEN_LEN     80
#define MAX_FACTS         16
#define MAX_HINTS         14
#define MAX_BATCH_DOCS    128
#define MAX_DOC_LEN       4096
#define EMBED_DIM         256

#define BM25_K1 1.5f
#define BM25_B  0.75f

/* ── basic types ──────────────────────────────────────────────────────── */

typedef struct { char t[MAX_TOKEN_LEN]; } Token;
typedef struct { char k[64]; char v[256]; float c; } Fact;
typedef struct { char hint[320]; char bucket[32]; float w; } Hint;

/* ════════════════════════════════════════════════════════════════════════
 * SHA-256 (FIPS 180-4 compliant, public domain)
 * Identical output to Node.js crypto.createHash("sha256")
 * ════════════════════════════════════════════════════════════════════════ */

#define ROR32(v,n) (((v)>>(n)) | ((v)<<(32-(n))))
#define CH(x,y,z)  (((x)&(y))^(~(x)&(z)))
#define MAJ(x,y,z) (((x)&(y))^((x)&(z))^((y)&(z)))
#define S0(x) (ROR32(x,2)^ROR32(x,13)^ROR32(x,22))
#define S1(x) (ROR32(x,6)^ROR32(x,11)^ROR32(x,25))
#define G0(x) (ROR32(x,7)^ROR32(x,18)^((x)>>3))
#define G1(x) (ROR32(x,17)^ROR32(x,19)^((x)>>10))

static const uint32_t SHA256_K[64] = {
  0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,
  0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
  0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,
  0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
  0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,
  0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
  0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,
  0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
  0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,
  0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
  0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,
  0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
  0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,
  0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
  0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,
  0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2,
};

typedef struct {
  unsigned char data[64];
  uint32_t      state[8];
  uint64_t      bits;
  int           datalen;
} SHA256_CTX;

static void sha256_init(SHA256_CTX *ctx) {
  ctx->datalen = 0; ctx->bits = 0;
  ctx->state[0]=0x6a09e667; ctx->state[1]=0xbb67ae85;
  ctx->state[2]=0x3c6ef372; ctx->state[3]=0xa54ff53a;
  ctx->state[4]=0x510e527f; ctx->state[5]=0x9b05688c;
  ctx->state[6]=0x1f83d9ab; ctx->state[7]=0x5be0cd19;
}

static void sha256_transform(SHA256_CTX *ctx, const unsigned char *d) {
  uint32_t a,b,c,e,f,g,h,t1,t2,m[64]; int i;
  uint32_t dd = 0;
  (void)dd;
  for (i=0;i<16;i++)
    m[i]=((uint32_t)d[i*4]<<24)|((uint32_t)d[i*4+1]<<16)|((uint32_t)d[i*4+2]<<8)|(uint32_t)d[i*4+3];
  for (;i<64;i++) m[i]=G1(m[i-2])+m[i-7]+G0(m[i-15])+m[i-16];
  a=ctx->state[0];b=ctx->state[1];c=ctx->state[2];dd=ctx->state[3];
  e=ctx->state[4];f=ctx->state[5];g=ctx->state[6];h=ctx->state[7];
  for (i=0;i<64;i++) {
    t1=h+S1(e)+CH(e,f,g)+SHA256_K[i]+m[i];
    t2=S0(a)+MAJ(a,b,c);
    h=g; g=f; f=e; e=dd+t1; dd=c; c=b; b=a; a=t1+t2;
  }
  ctx->state[0]+=a; ctx->state[1]+=b; ctx->state[2]+=c; ctx->state[3]+=dd;
  ctx->state[4]+=e; ctx->state[5]+=f; ctx->state[6]+=g; ctx->state[7]+=h;
}

static void sha256_update(SHA256_CTX *ctx, const unsigned char *data, size_t len) {
  for (size_t i=0;i<len;i++) {
    ctx->data[ctx->datalen++]=(unsigned char)data[i];
    if (ctx->datalen==64) { sha256_transform(ctx,ctx->data); ctx->bits+=512; ctx->datalen=0; }
  }
}

static void sha256_final(SHA256_CTX *ctx, unsigned char *digest) {
  int i=ctx->datalen;
  ctx->data[i++]=0x80;
  if (ctx->datalen<56) { while (i<56) ctx->data[i++]=0; }
  else { while (i<64) ctx->data[i++]=0; sha256_transform(ctx,ctx->data); memset(ctx->data,0,56); }
  ctx->bits += (uint64_t)ctx->datalen*8;
  for (i=0;i<8;i++) ctx->data[56+i]=(ctx->bits>>((7-i)*8))&0xff;
  sha256_transform(ctx,ctx->data);
  for (i=0;i<8;i++) {
    digest[i*4+0]=(ctx->state[i]>>24)&0xff; digest[i*4+1]=(ctx->state[i]>>16)&0xff;
    digest[i*4+2]=(ctx->state[i]>>8)&0xff;  digest[i*4+3]=(ctx->state[i]    )&0xff;
  }
}

static void sha256_hash(const unsigned char *data, size_t len, unsigned char *out) {
  SHA256_CTX ctx; sha256_init(&ctx); sha256_update(&ctx,data,len); sha256_final(&ctx,out);
}

/* ── Turkish character helpers ──────────────────────────────────────── */

static const char *TR_U[] = {
  "\xc3\x87","\xc4\x9e","\xc4\xb0","\xc3\x96","\xc5\x9e","\xc3\x9c", NULL
};
static const char *TR_L[] = {
  "\xc3\xa7","\xc4\x9f","\xc4\xb1","\xc3\xb6","\xc5\x9f","\xc3\xbc", NULL
};

static int tr_lower(const char *src, char *dst, int dmax) {
  unsigned char c = (unsigned char)*src;
  for (int i=0; TR_U[i]; i++) {
    int ul=(int)strlen(TR_U[i]), ll=(int)strlen(TR_L[i]);
    if (strncmp(src,TR_U[i],ul)==0 && ll<dmax) {
      memcpy(dst,TR_L[i],ll); dst[ll]='\0'; return ul;
    }
  }
  if (c>='A'&&c<='Z'&&dmax>1) { dst[0]=(char)(c+32); dst[1]='\0'; return 1; }
  int clen=(c<0x80)?1:(c<0xE0)?2:(c<0xF0)?3:4;
  if (clen<dmax) { memcpy(dst,src,clen); dst[clen]='\0'; }
  return clen;
}

static int tr_isalpha(const char *s) {
  unsigned char c=(unsigned char)*s;
  if ((c>='a'&&c<='z')||(c>='A'&&c<='Z')) return 1;
  for (int i=0; TR_U[i]; i++) if (strncmp(s,TR_U[i],strlen(TR_U[i]))==0) return 1;
  for (int i=0; TR_L[i]; i++) if (strncmp(s,TR_L[i],strlen(TR_L[i]))==0) return 1;
  return 0;
}

static int tr_isalnum_or_special(const char *s) {
  unsigned char c=(unsigned char)*s;
  if ((c>='a'&&c<='z')||(c>='A'&&c<='Z')||(c>='0'&&c<='9')) return 1;
  if (c=='_'||c=='-'||c=='.') return 1;
  /* Turkish multibyte */
  for (int i=0; TR_U[i]; i++) if (strncmp(s,TR_U[i],strlen(TR_U[i]))==0) return 1;
  for (int i=0; TR_L[i]; i++) if (strncmp(s,TR_L[i],strlen(TR_L[i]))==0) return 1;
  return 0;
}

static int utf8_step(const char *s) {
  unsigned char c=(unsigned char)*s;
  return (c<0x80)?1:(c<0xE0)?2:(c<0xF0)?3:4;
}

static void lowercase_to(const char *src, char *dst, int dlen) {
  int lp=0;
  for (const char *p=src; *p && lp<dlen-4;) {
    char seq[8]={0}; int n=tr_lower(p,seq,sizeof(seq));
    int sl=(int)strlen(seq); memcpy(dst+lp,seq,sl); lp+=sl; p+=n;
  }
  dst[lp<dlen?lp:dlen-1]='\0';
}

/* ── Turkish suffix stemmer ─────────────────────────────────────────── */

static const char *TR_SFX[] = {
  "bildiriyorum","biliyorum","ediyorum","yapıyorum","istiyorum",
  "yapabilecek","geliştiren","geliştirdi","geliştirmek",
  "yorum","lerin","ların","larım","lerden","lardan",
  "ından","inden","undan","ünden",
  "larını","lerini","lardaki","lerdeki",
  "dalar","deler","talar","teler",
  "lardan","lerden","ların","lerin","ları","leri",
  "ndan","nden","nın","nin","nün","nun",
  "dan","den","tan","ten","yla","yle",
  "lar","ler","ın","in","un","ün",
  "da","de","ta","te","ya","ye",
  "ı","i","u","ü","a","e",
  NULL
};

static void stem(char *buf) {
  int len=(int)strlen(buf);
  if (len<=4) return;
  for (int p=0;p<2;p++) {
    for (int i=0;TR_SFX[i];i++) {
      int slen=(int)strlen(TR_SFX[i]);
      if (len>slen+3 && strcmp(buf+len-slen,TR_SFX[i])==0) {
        buf[len-slen]='\0'; len-=slen; break;
      }
    }
  }
}

/* ── Stopwords ──────────────────────────────────────────────────────── */

static const char *TR_STOP[] = {
  "bir","bu","ve","ile","için","ben","sen","biz","siz","var","yok",
  "olan","gibi","kadar","daha","çok","ama","fakat","ancak","eğer",
  "her","hiç","bazı","şu","ise","da","de","ki","mi","mı","mu","mü",
  NULL
};
static const char *EN_STOP[] = {
  "the","and","for","are","but","not","you","all","can","has","her",
  "was","one","our","out","use","that","this","from","with","have",
  "they","will","been","were","which",
  NULL
};

static int is_stop(const char *t) {
  for (int i=0;TR_STOP[i];i++) if (!strcmp(t,TR_STOP[i])) return 1;
  for (int i=0;EN_STOP[i];i++) if (!strcmp(t,EN_STOP[i])) return 1;
  return 0;
}

/* ── NLP tokenizer (with stemming, for BM25 / scoring) ──────────────── */

static int tokenize_nlp(const char *text, Token *out, int maxn) {
  int count=0;
  const char *p=text;
  while (*p && count<maxn) {
    while (*p && !tr_isalpha(p)) p+=utf8_step(p);
    if (!*p) break;
    char buf[MAX_TOKEN_LEN*3]={0}; int bpos=0;
    while (*p && tr_isalpha(p) && bpos<(int)sizeof(buf)-8) {
      char lo[8]={0}; int n=tr_lower(p,lo,sizeof(lo));
      int ll=(int)strlen(lo); memcpy(buf+bpos,lo,ll); bpos+=ll; p+=n;
    }
    buf[bpos]='\0';
    if (bpos<2 || is_stop(buf)) continue;
    stem(buf);
    if ((int)strlen(buf)<2) continue;
    strncpy(out[count].t,buf,MAX_TOKEN_LEN-1); out[count].t[MAX_TOKEN_LEN-1]='\0';
    count++;
  }
  return count;
}

/* ── Retrieval tokenizer (NO stemming, matches retrieval.ts) ─────────── */
/* Keeps [a-z0-9çğıöşü_.-], min 2 chars, max 120 tokens.                  */

static int tokenize_retrieval(const char *text, char (*out)[MAX_TOKEN_LEN], int maxn) {
  int count=0;
  const char *p=text;
  while (*p && count<maxn) {
    while (*p && !tr_isalnum_or_special(p)) p+=utf8_step(p);
    if (!*p) break;
    char buf[MAX_TOKEN_LEN*3]={0}; int bpos=0;
    while (*p && tr_isalnum_or_special(p) && bpos<(int)sizeof(buf)-8) {
      char lo[8]={0}; int n=tr_lower(p,lo,sizeof(lo));
      int ll=(int)strlen(lo); memcpy(buf+bpos,lo,ll); bpos+=ll; p+=n;
    }
    buf[bpos]='\0';
    if (bpos<2) continue;
    snprintf(out[count], MAX_TOKEN_LEN, "%s", buf);
    count++;
  }
  return count;
}

/* ── BM25 scoring ────────────────────────────────────────────────────── */

static float bm25(Token *q, int qn, Token *d, int dn, float avgdl) {
  if (!qn || !dn || avgdl<1.0f) return 0.0f;
  float score=0.0f, norm=(float)dn/avgdl;
  for (int qi=0;qi<qn;qi++) {
    int tf=0;
    for (int di=0;di<dn;di++) if (!strcmp(q[qi].t,d[di].t)) tf++;
    if (!tf) continue;
    score += (float)tf*(BM25_K1+1.0f) /
             ((float)tf+BM25_K1*(1.0f-BM25_B+BM25_B*norm));
  }
  return score;
}

/* ── 256-dim hash embedding (mirrors retrieval.ts buildHashedKnowledgeEmbedding) ── */

static void embed_256(const char *text, float *vector) {
  /* Initialize */
  for (int i=0;i<EMBED_DIM;i++) vector[i]=0.0f;

  char rtoks[120][MAX_TOKEN_LEN];
  int n = tokenize_retrieval(text, rtoks, 120);

  for (int ti=0;ti<n;ti++) {
    const char *tok = rtoks[ti];
    size_t tlen = strlen(tok);

    /* SHA-256 of the UTF-8 token bytes */
    unsigned char digest[32];
    sha256_hash((const unsigned char *)tok, tlen, digest);

    /* Weight: min(2.5, 1 + len/10) — uses byte length to match JS */
    float weight = 1.0f + (float)tlen / 10.0f;
    if (weight > 2.5f) weight = 2.5f;

    /* 3 (bucket, sign) pairs from bytes [0:2], [2:4], [4:6] */
    for (int off=0;off<6;off+=2) {
      int bucket = (((int)digest[off]<<8) | (int)digest[off+1]) % EMBED_DIM;
      float sign = (digest[off+2] % 2 == 0) ? 1.0f : -1.0f;
      vector[bucket] += sign * weight;
    }
  }

  /* L2 normalize */
  float mag=0.0f;
  for (int i=0;i<EMBED_DIM;i++) mag+=vector[i]*vector[i];
  mag=sqrtf(mag);
  if (mag>0.0f) {
    for (int i=0;i<EMBED_DIM;i++) vector[i]/=mag;
  }
}

/* ── Cosine similarity ───────────────────────────────────────────────── */

static float cosine_sim(const float *a, const float *b, int n) {
  float dot=0.0f, ma=0.0f, mb=0.0f;
  for (int i=0;i<n;i++) { dot+=a[i]*b[i]; ma+=a[i]*a[i]; mb+=b[i]*b[i]; }
  if (ma<=0.0f || mb<=0.0f) return 0.0f;
  return dot / (sqrtf(ma)*sqrtf(mb));
}

/* ════════════════════════════════════════════════════════════════════════
 * JSON helpers
 * ════════════════════════════════════════════════════════════════════════ */

static void json_esc(const char *src, char *dst, int dmax) {
  int d=0;
  for (int i=0;src[i]&&d<dmax-2;i++) {
    unsigned char c=(unsigned char)src[i];
    if      (c=='"')  { dst[d++]='\\'; dst[d++]='"';  }
    else if (c=='\\') { dst[d++]='\\'; dst[d++]='\\'; }
    else if (c=='\n') { dst[d++]='\\'; dst[d++]='n';  }
    else if (c=='\r') { dst[d++]='\\'; dst[d++]='r';  }
    else if (c=='\t') { dst[d++]='\\'; dst[d++]='t';  }
    else              { dst[d++]=(char)c;              }
  }
  dst[d]='\0';
}

static int jstr(const char *json, const char *key, char *out, int olen) {
  char search[128]; snprintf(search,sizeof(search),"\"%s\":",key);
  const char *p=strstr(json,search); if (!p) return 0;
  p+=strlen(search);
  while (*p==' '||*p=='\t') p++;
  if (*p!='"') { return 0; } p++;
  int i=0;
  while (*p&&*p!='"'&&i<olen-1) {
    if (*p=='\\') {
      p++; if (!*p) break;
      if      (*p=='n')  out[i++]='\n';
      else if (*p=='r')  out[i++]='\r';
      else if (*p=='t')  out[i++]='\t';
      else if (*p=='"')  out[i++]='"';
      else if (*p=='\\') out[i++]='\\';
      else               out[i++]=*p;
      p++;
    } else out[i++]=*p++;
  }
  out[i]='\0'; return 1;
}

static int jnum(const char *json, const char *key, float *out) {
  char search[128]; snprintf(search,sizeof(search),"\"%s\":",key);
  const char *p=strstr(json,search); if (!p) return 0;
  p+=strlen(search);
  while (*p==' '||*p=='\t') p++;
  if ((*p<'0'||*p>'9')&&*p!='-'&&*p!='.') return 0;
  *out=(float)atof(p); return 1;
}

static int jnum_flex(const char *json, const char *key, float *out) {
  if (jnum(json,key,out)) return 1;
  char s[64]={0};
  if (!jstr(json,key,s,sizeof(s))||!s[0]) return 0;
  *out=(float)atof(s); return 1;
}

/* Parse "key":[f1,f2,...] into a float array; returns count */
static int jfloat_array(const char *json, const char *key, float *out, int maxn) {
  char search[128]; snprintf(search,sizeof(search),"\"%s\":[",key);
  const char *p=strstr(json,search); if (!p) return 0;
  p+=strlen(search);
  int count=0;
  while (*p&&*p!=']'&&count<maxn) {
    while (*p==' '||*p==','||*p=='\t') p++;
    if (*p==']'||!*p) break;
    char *end; float v=(float)strtod(p,&end);
    if (end==p) break;
    out[count++]=v; p=end;
  }
  return count;
}

/* Parse "key":["s1","s2",...] into char arrays; returns count */
static int jstring_array(const char *json, const char *key,
                         char (*out)[MAX_DOC_LEN], int maxn) {
  char search[128]; snprintf(search,sizeof(search),"\"%s\":[",key);
  const char *p=strstr(json,search); if (!p) return 0;
  p+=strlen(search);
  int count=0;
  while (*p&&*p!=']'&&count<maxn) {
    while (*p==' '||*p==','||*p=='\t') p++;
    if (*p==']'||!*p) break;
    if (*p!='"') { while (*p&&*p!=','&&*p!=']') p++; continue; }
    p++; int i=0;
    while (*p&&*p!='"'&&i<MAX_DOC_LEN-1) {
      if (*p=='\\') {
        p++; if (!*p) break;
        if      (*p=='n')  out[count][i++]='\n';
        else if (*p=='t')  out[count][i++]='\t';
        else if (*p=='"')  out[count][i++]='"';
        else if (*p=='\\') out[count][i++]='\\';
        else               out[count][i++]=*p;
        p++;
      } else out[count][i++]=*p++;
    }
    out[count][i]='\0';
    if (*p=='"') p++;
    count++;
  }
  return count;
}

/* ── Fact extraction ─────────────────────────────────────────────────── */

static const char *NAME_PAT[] = {
  "benim adım ","adım ","ismim ","adı ","ben ",
  "my name is ","i am ","i'm ","call me ","name is ",
  NULL
};

static int extract_name(const char *text, char *out, int olen) {
  char lo[MAX_LINE]={0}; lowercase_to(text,lo,sizeof(lo));
  for (int i=0;NAME_PAT[i];i++) {
    const char *found=strstr(lo,NAME_PAT[i]); if (!found) continue;
    int off=(int)(found+strlen(NAME_PAT[i])-lo);
    while (lo[off]==' ') off++;
    const char *orig=text+off; int len=0;
    while (orig[len]&&orig[len]!=' '&&orig[len]!=','&&orig[len]!='.'
           &&orig[len]!='\n'&&orig[len]!='!'&&orig[len]!='?'&&len<olen-1) len++;
    if (len>=2&&len<=40) {
      strncpy(out,orig,len); out[len]='\0';
      if (out[0]>='a'&&out[0]<='z') out[0]-=32;
      return 1;
    }
  }
  return 0;
}

static const char *CITIES[] = {
  "istanbul","ankara","izmir","bursa","antalya","adana","konya",
  "gaziantep","mersin","diyarbakır","kayseri","eskişehir","samsun",
  "trabzon","erzurum","van","bodrum","kocaeli","muğla","denizli",
  "new york","london","berlin","paris","tokyo","dubai","amsterdam",
  "vienna","barcelona","madrid","rome","lisbon","stockholm","oslo",
  "singapore","toronto","sydney","melbourne",
  NULL
};

static int extract_city(const char *text, char *out, int olen) {
  char lo[MAX_LINE]={0}; lowercase_to(text,lo,sizeof(lo));
  for (int i=0;CITIES[i];i++) {
    if (strstr(lo,CITIES[i])) {
      snprintf(out,olen,"%s",CITIES[i]);
      if (out[0]>='a'&&out[0]<='z') out[0]-=32;
      return 1;
    }
  }
  return 0;
}

static int extract_facts(const char *text, Fact *facts, int maxf) {
  int n=0;
  char name[128]={0};
  if (n<maxf && extract_name(text,name,sizeof(name))) {
    strncpy(facts[n].k,"name",63); strncpy(facts[n].v,name,255);
    facts[n].c=0.84f; n++;
  }
  char city[128]={0};
  if (n<maxf && extract_city(text,city,sizeof(city))) {
    strncpy(facts[n].k,"city",63); strncpy(facts[n].v,city,255);
    facts[n].c=0.76f; n++;
  }
  return n;
}

/* ── World-signal hint derivation ────────────────────────────────────── */

#define PUSH(bucket_, weight_, fmt, ...) do { \
  if (nh<maxh) { \
    snprintf(out[nh].hint,sizeof(out[nh].hint)-1,fmt,##__VA_ARGS__); \
    strncpy(out[nh].bucket,bucket_,31); out[nh].w=(weight_); nh++; \
  } \
} while(0)

static int derive_hints(const char *kind, const char *summary,
                        const char *energy_s, float readiness,
                        const char *mobility, const char *busyness,
                        const char *attention, const char *city,
                        float free_minutes, Hint *out, int maxh) {
  int nh=0;
  char sum[2048]={0}; lowercase_to(summary,sum,sizeof(sum));

  if (strstr(kind,"health")||strstr(kind,"fitness")) {
    char enlo[64]={0}; lowercase_to(energy_s,enlo,sizeof(enlo));
    int low  = (readiness>=0&&readiness<0.45f)||!strcmp(enlo,"low")||!strcmp(enlo,"düşük")
             ||strstr(sum,"düşük enerji")||strstr(sum,"low energy")
             ||strstr(sum,"yorgun")||strstr(sum,"tired")||strstr(sum,"uykusuz");
    int high = (readiness>=0.72f)||!strcmp(enlo,"high")||!strcmp(enlo,"yüksek")
             ||strstr(sum,"yüksek enerji")||strstr(sum,"high energy")
             ||strstr(sum,"dinç")||strstr(sum,"rested");
    if (low)  PUSH("situational",0.88f,"User energy is low — keep responses short, direct, friction-light.");
    else if (high) PUSH("situational",0.82f,"User energy is high — detailed or multi-step answers are welcome.");
    if ((strstr(sum,"egzersiz")||strstr(sum,"workout")||strstr(sum,"spor")||strstr(sum,"active"))&&high)
      PUSH("behavioral",0.78f,"User is active and energised; momentum-building suggestions fit well.");
  }

  if (strstr(kind,"calendar")||strstr(kind,"schedule")) {
    char buslo[64]={0}; lowercase_to(busyness,buslo,sizeof(buslo));
    int packed  = strstr(sum,"yoğun")||strstr(sum,"busy")||!strcmp(buslo,"high");
    int relaxed = strstr(sum,"boş")||strstr(sum,"free")||!strcmp(buslo,"low");
    if (packed)  PUSH("situational",0.82f,"Calendar is packed — bullet-point clarity and next-actions matter most.");
    else if (relaxed) PUSH("situational",0.68f,"User has open time; deeper exploration or longer answers are fine.");
    else if (free_minutes>=0&&free_minutes<45)
      PUSH("situational",0.78f,"Only %.0f free minutes today — prioritise bite-sized, high-value steps.",free_minutes);
    else if (free_minutes>=90)
      PUSH("situational",0.70f,"A focus block of %.0f+ minutes is available; deeper work is actionable.",free_minutes);
    if (strstr(sum,"sabah")||strstr(sum,"morning"))
      PUSH("behavioral",0.66f,"Morning session — structured planning suggestions land well.");
    else if (strstr(sum,"gece")||strstr(sum,"night"))
      PUSH("behavioral",0.72f,"Late-night session — calm tone, low urgency, easy-to-scan answers.");
    else if (strstr(sum,"akşam")||strstr(sum,"evening"))
      PUSH("behavioral",0.62f,"Evening session — avoid introducing heavy new commitments.");
  }

  if (strstr(kind,"location")||strstr(kind,"mobility")) {
    char moblo[64]={0}; lowercase_to(mobility,moblo,sizeof(moblo));
    int moving  = strstr(sum,"hareket")||strstr(sum,"moving")||strstr(sum,"transit")
               ||strstr(sum,"commut")||strstr(sum,"yolda")||!strcmp(moblo,"transit");
    int at_home = strstr(sum,"evde")||strstr(sum,"home")||!strcmp(moblo,"home");
    int at_work = strstr(sum,"ofiste")||strstr(sum,"office")||!strcmp(moblo,"office");
    if (moving)  PUSH("situational",0.78f,"User is in transit — short, scannable output works best.");
    else if (at_home) PUSH("environmental",0.62f,"User is at home; relaxed, longer reads are fine.");
    else if (at_work) PUSH("environmental",0.64f,"User is at work; task-focused, professional tone.");
    if (city[0]) {
      char cap[128]={0}; snprintf(cap,sizeof(cap),"%s",city);
      if (cap[0]>='a'&&cap[0]<='z') cap[0]-=32;
      PUSH("environmental",0.70f,"User is in %s — prefer local time, language, conventions.",cap);
    }
  }

  if (strstr(kind,"notification")||strstr(kind,"attention")) {
    char attlo[64]={0}; lowercase_to(attention,attlo,sizeof(attlo));
    int heavy = strstr(sum,"yüksek")||strstr(sum,"high")||!strcmp(attlo,"high");
    int light = strstr(sum,"düşük")||strstr(sum,"low")||!strcmp(attlo,"quiet");
    if (heavy) PUSH("situational",0.74f,"High notification load — crisp, scannable structure preferred.");
    else if (light) PUSH("situational",0.62f,"Low interruption load — focused attention likely available.");
  }

  if (strstr(kind,"device")||strstr(kind,"screen")) {
    if (strstr(sum,"heavy")||strstr(sum,"yoğun kullanım"))
      PUSH("behavioral",0.60f,"Heavy screen usage today — shorter interactions are considerate.");
  }

  return nh;
}

#undef PUSH

/* ── Sentiment scoring ───────────────────────────────────────────────── */

static const char *POS_TR[] = {
  "harika","güzel","mükemmel","seviyorum","teşekkür","süper","başarı","mutlu",
  "muhteşem","sevindim","memnun","bravo","oldu","kolay","hızlı","çözüldü",
  "tebrikler","evet","kesinlikle","inanılmaz","love","wow","yay","bravo","eyvallah",
  NULL
};
static const char *NEG_TR[] = {
  "kötü","berbat","sorun","olmadı","çalışmıyor","üzgün","sinirli","bozuldu",
  "bıktım","yoruldum","anlamıyorum","kafam","karmaşık","zor","başaramadım",
  "hata","problem","çökeliyor","çöküyor","sıkıntı","lanet","rezalet",
  NULL
};
static const char *POS_EN[] = {
  "great","good","excellent","love","thanks","awesome","perfect","happy","success",
  "wonderful","easy","fast","solved","nice","brilliant","amazing","fantastic",
  "helpful","thank","appreciate","yes","works","fixed","done",
  NULL
};
static const char *NEG_EN[] = {
  "bad","broken","awful","sad","angry","confused","stuck","hate","terrible",
  "wrong","failed","error","crash","issue","frustrating","annoying","slow",
  "problem","useless","worst","doesn't work","not working",
  NULL
};

static void score_sentiment(const char *text, char *label_out, float *score_out,
                            int *pos_out, int *neg_out) {
  char lo[MAX_LINE]={0}; lowercase_to(text,lo,sizeof(lo));
  int pos=0, neg=0;
  for (int i=0; POS_TR[i]; i++) if (strstr(lo,POS_TR[i])) pos++;
  for (int i=0; NEG_TR[i]; i++) if (strstr(lo,NEG_TR[i])) neg++;
  for (int i=0; POS_EN[i]; i++) if (strstr(lo,POS_EN[i])) pos++;
  for (int i=0; NEG_EN[i]; i++) if (strstr(lo,NEG_EN[i])) neg++;

  if (pos_out) *pos_out = pos;
  if (neg_out) *neg_out = neg;

  int total = pos + neg;
  if (total == 0) {
    if (label_out) strcpy(label_out,"neutral");
    if (score_out) *score_out = 0.5f;
    return;
  }
  float ratio = (float)pos / (float)total;
  if (ratio > 0.6f) {
    if (label_out) strcpy(label_out,"positive");
    if (score_out) *score_out = 0.5f + ratio * 0.5f;
  } else if (ratio < 0.4f) {
    if (label_out) strcpy(label_out,"negative");
    if (score_out) *score_out = 0.5f + (1.0f - ratio) * 0.5f;
  } else {
    if (label_out) strcpy(label_out,"mixed");
    if (score_out) *score_out = 0.5f;
  }
}

/* ── Language detection ──────────────────────────────────────────────── */

static const char *TR_SPECIFIC_WORDS[] = {
  "bir","bu","ve","ile","için","ben","sen","biz","var","yok","olan",
  "gibi","kadar","daha","ama","fakat","eğer","her","hiç","bazı",
  "nasıl","neden","nedir","nerede","ne zaman","merhaba","selam",
  "tamam","evet","hayır","lütfen","teşekkür","anladım",
  NULL
};
static const char *EN_SPECIFIC_WORDS[] = {
  "the","and","for","are","but","not","you","all","can","has","was",
  "one","use","that","this","from","with","have","they","will","been",
  "hello","please","thank","okay","yes","no","understand","because",
  NULL
};

static void detect_language(const char *text, char *lang_out, float *conf_out) {
  char lo[MAX_LINE]={0}; lowercase_to(text,lo,sizeof(lo));

  /* Count Turkish-specific UTF-8 chars (ç,ğ,ı,ö,ş,ü) */
  int tr_chars=0;
  const char *tr_chars_list[] = {"\xc3\xa7","\xc4\x9f","\xc4\xb1","\xc3\xb6","\xc5\x9f","\xc3\xbc",NULL};
  for (int i=0; tr_chars_list[i]; i++) {
    const char *p=lo;
    while ((p=strstr(p,tr_chars_list[i]))) { tr_chars++; p+=strlen(tr_chars_list[i]); }
  }

  int tr_words=0, en_words=0;
  for (int i=0; TR_SPECIFIC_WORDS[i]; i++) {
    char pat[128]; snprintf(pat,sizeof(pat)," %s ",TR_SPECIFIC_WORDS[i]);
    if (strstr(lo,pat)||strncmp(lo,TR_SPECIFIC_WORDS[i],strlen(TR_SPECIFIC_WORDS[i]))==0)
      tr_words++;
  }
  for (int i=0; EN_SPECIFIC_WORDS[i]; i++) {
    char pat[128]; snprintf(pat,sizeof(pat)," %s ",EN_SPECIFIC_WORDS[i]);
    if (strstr(lo,pat)||strncmp(lo,EN_SPECIFIC_WORDS[i],strlen(EN_SPECIFIC_WORDS[i]))==0)
      en_words++;
  }

  float tr_score = (float)(tr_chars * 3 + tr_words * 2);
  float en_score = (float)(en_words * 2);
  float total = tr_score + en_score;

  if (total < 1.0f) {
    if (lang_out) strcpy(lang_out,"en");
    if (conf_out) *conf_out = 0.5f;
    return;
  }
  float tr_ratio = tr_score / total;
  if (tr_ratio > 0.65f) {
    if (lang_out) strcpy(lang_out,"tr");
    if (conf_out) *conf_out = 0.5f + tr_ratio * 0.5f;
  } else if (tr_ratio < 0.35f) {
    if (lang_out) strcpy(lang_out,"en");
    if (conf_out) *conf_out = 0.5f + (1.0f - tr_ratio) * 0.5f;
  } else {
    if (lang_out) strcpy(lang_out,"mixed");
    if (conf_out) *conf_out = 0.5f;
  }
}

/* ── Keyword extraction (frequency-based, no stemming for readability) ── */

#define MAX_KW 32

typedef struct { char w[MAX_TOKEN_LEN]; int freq; } KwEntry;

static int kw_cmp(const void *a, const void *b) {
  return ((KwEntry*)b)->freq - ((KwEntry*)a)->freq;
}

static int extract_keywords(const char *text, char (*out)[MAX_TOKEN_LEN], int maxkw) {
  char rtoks[120][MAX_TOKEN_LEN];
  int ntoks = tokenize_retrieval(text, rtoks, 120);
  KwEntry kws[MAX_KW]; int nkw=0;

  for (int i=0; i<ntoks; i++) {
    if (is_stop(rtoks[i])) continue;
    if ((int)strlen(rtoks[i]) < 3) continue;
    int found=0;
    for (int j=0; j<nkw; j++) {
      if (!strcmp(kws[j].w, rtoks[i])) { kws[j].freq++; found=1; break; }
    }
    if (!found && nkw<MAX_KW) {
      strncpy(kws[nkw].w, rtoks[i], MAX_TOKEN_LEN-1);
      kws[nkw].w[MAX_TOKEN_LEN-1]='\0';
      kws[nkw].freq=1; nkw++;
    }
  }
  if (nkw>1) qsort(kws, nkw, sizeof(KwEntry), kw_cmp);
  int n = (nkw < maxkw) ? nkw : maxkw;
  for (int i=0; i<n; i++) strncpy(out[i], kws[i].w, MAX_TOKEN_LEN-1);
  return n;
}

/* ── Text complexity scoring ─────────────────────────────────────────── */

static void score_complexity(const char *text,
                             float *avg_sent_len_out,
                             float *vocab_richness_out,
                             int   *token_count_out,
                             int   *sentence_count_out) {
  /* Sentence count: count . ! ? terminators */
  int sentences=0;
  for (const char *p=text; *p; p++) {
    if (*p=='.'||*p=='!'||*p=='?') sentences++;
  }
  if (sentences==0) sentences=1;

  Token toks[MAX_TOKENS]; int ntoks=tokenize_nlp(text,toks,MAX_TOKENS);

  /* Unique token count (vocab richness) */
  int unique=0;
  for (int i=0; i<ntoks; i++) {
    int dup=0;
    for (int j=0; j<i; j++) if (!strcmp(toks[i].t,toks[j].t)) { dup=1; break; }
    if (!dup) unique++;
  }

  if (token_count_out)    *token_count_out    = ntoks;
  if (sentence_count_out) *sentence_count_out = sentences;
  if (avg_sent_len_out)   *avg_sent_len_out   = ntoks>0 ? (float)ntoks/(float)sentences : 0.0f;
  if (vocab_richness_out) *vocab_richness_out = ntoks>0 ? (float)unique/(float)ntoks : 0.0f;
}

/* ── Intent classification ───────────────────────────────────────────── */

static const char *classify_intent(const char *text) {
  char lo[MAX_LINE]={0}; lowercase_to(text,lo,sizeof(lo));
  if (strstr(lo,"merhaba")||strstr(lo,"selam")||strstr(lo,"günaydın")
    ||strstr(lo,"iyi akşam")||strstr(lo,"hello")||strstr(lo,"hi ")||strstr(lo,"hey "))
    return "greeting";
  if (strstr(lo,"hissediyorum")||strstr(lo,"üzgün")||strstr(lo,"mutlu")
    ||strstr(lo,"endişe")||strstr(lo,"stres")||strstr(lo,"yoruldum")
    ||strstr(lo,"feeling")||strstr(lo,"tired")||strstr(lo,"worried")||strstr(lo,"anxious"))
    return "emotional_support";
  if (strstr(lo,"planla")||strstr(lo,"organize")||strstr(lo,"takvim")
    ||strstr(lo,"öncelik")||strstr(lo,"schedule")||strstr(lo,"priority")||strstr(lo,"roadmap"))
    return "planning";
  if (strstr(lo,"kod")||strstr(lo,"hata")||strstr(lo,"bug")||strstr(lo,"fonksiyon")
    ||strstr(lo,"code")||strstr(lo,"error")||strstr(lo,"function")||strstr(lo,"debug")
    ||strstr(lo,"typescript")||strstr(lo,"javascript")||strstr(lo,"python")||strstr(lo,"api"))
    return "coding";
  if (strstr(lo,"yap")||strstr(lo,"oluştur")||strstr(lo,"yaz")||strstr(lo,"düzenle")
    ||strstr(lo,"create")||strstr(lo,"write")||strstr(lo,"generate")||strstr(lo,"build")
    ||strstr(lo,"run")||strstr(lo,"deploy")||strstr(lo,"fix")||strstr(lo,"send"))
    return "task_execution";
  if (strstr(lo,"nedir")||strstr(lo,"neden")||strstr(lo,"nasıl")||strstr(lo,"ne zaman")
    ||strstr(lo,"nerede")||strstr(lo,"what is")||strstr(lo,"how to")||strstr(lo,"why")
    ||strstr(lo,"explain")||strstr(lo,"what are"))
    return "information_seeking";
  return "general";
}

/* ════════════════════════════════════════════════════════════════════════
 * Request handlers
 * ════════════════════════════════════════════════════════════════════════ */

static void write_ok(const char *id) {
  if (id[0]) printf("{\"ok\":true,\"_id\":\"%s\"", id);
  else       printf("{\"ok\":true");
}

static void write_err(const char *id, const char *msg) {
  char e[256]; json_esc(msg,e,sizeof(e));
  if (id[0]) printf("{\"ok\":false,\"_id\":\"%s\",\"error\":\"%s\"}\n",id,e);
  else       printf("{\"ok\":false,\"error\":\"%s\"}\n",e);
}

static void h_ping(const char *id) {
  write_ok(id); printf(",\"pong\":true}\n");
}

static void h_tokenize(const char *json, const char *id) {
  char text[MAX_LINE]={0};
  if (!jstr(json,"text",text,sizeof(text))) { write_err(id,"missing text"); return; }
  Token toks[MAX_TOKENS]; int n=tokenize_nlp(text,toks,MAX_TOKENS);
  write_ok(id); printf(",\"tokens\":[");
  for (int i=0;i<n;i++) {
    char esc[MAX_TOKEN_LEN*2]; json_esc(toks[i].t,esc,sizeof(esc));
    if (i) { putchar(','); } printf("\"%s\"",esc);
  }
  printf("]}\n");
}

static void h_score_bm25(const char *json, const char *id) {
  char q[MAX_LINE]={0}, d[MAX_LINE]={0};
  jstr(json,"query",q,sizeof(q)); jstr(json,"doc",d,sizeof(d));
  float avgdl=20.0f; jnum_flex(json,"avg_len",&avgdl);
  Token qt[MAX_TOKENS], dt[MAX_TOKENS];
  int qn=tokenize_nlp(q,qt,MAX_TOKENS), dn=tokenize_nlp(d,dt,MAX_TOKENS);
  float score=bm25(qt,qn,dt,dn,avgdl);
  write_ok(id); printf(",\"score\":%.4f,\"q_tokens\":%d,\"d_tokens\":%d}\n",score,qn,dn);
}

static void h_bm25_batch(const char *json, const char *id) {
  char q[MAX_LINE]={0}; jstr(json,"query",q,sizeof(q));
  float avgdl=20.0f; jnum_flex(json,"avg_len",&avgdl);

  static char docs[MAX_BATCH_DOCS][MAX_DOC_LEN];
  int ndocs=jstring_array(json,"docs",docs,MAX_BATCH_DOCS);
  if (!ndocs) { write_ok(id); printf(",\"scores\":[]}\n"); return; }

  Token qt[MAX_TOKENS]; int qn=tokenize_nlp(q,qt,MAX_TOKENS);
  write_ok(id); printf(",\"scores\":[");
  for (int di=0;di<ndocs;di++) {
    Token dt[MAX_TOKENS]; int dn=tokenize_nlp(docs[di],dt,MAX_TOKENS);
    float score=bm25(qt,qn,dt,dn,avgdl);
    if (di) { putchar(','); } printf("%.4f",score);
  }
  printf("]}\n");
}

static void h_embed_256(const char *json, const char *id) {
  char text[MAX_LINE]={0};
  if (!jstr(json,"text",text,sizeof(text))) { write_err(id,"missing text"); return; }
  float vec[EMBED_DIM]; embed_256(text,vec);
  write_ok(id); printf(",\"vector\":[");
  for (int i=0;i<EMBED_DIM;i++) {
    if (i) putchar(',');
    /* 6 decimal places to match JS toFixed(6) */
    printf("%.6f",vec[i]);
  }
  printf("]}\n");
}

static void h_cosine_sim(const char *json, const char *id) {
  float a[EMBED_DIM]={0}, b[EMBED_DIM]={0};
  int na=jfloat_array(json,"a",a,EMBED_DIM);
  int nb=jfloat_array(json,"b",b,EMBED_DIM);
  int n=(na<nb)?na:nb;
  if (n<=0) { write_ok(id); printf(",\"score\":0.0}\n"); return; }
  float score=cosine_sim(a,b,n);
  write_ok(id); printf(",\"score\":%.6f}\n",score);
}

static void h_extract_facts(const char *json, const char *id) {
  char text[MAX_LINE]={0};
  if (!jstr(json,"text",text,sizeof(text))) { write_err(id,"missing text"); return; }
  Fact facts[MAX_FACTS]; int n=extract_facts(text,facts,MAX_FACTS);
  write_ok(id); printf(",\"facts\":[");
  for (int i=0;i<n;i++) {
    char ke[128],ve[512]; json_esc(facts[i].k,ke,sizeof(ke)); json_esc(facts[i].v,ve,sizeof(ve));
    if (i) putchar(',');
    printf("{\"k\":\"%s\",\"v\":\"%s\",\"c\":%.2f}",ke,ve,facts[i].c);
  }
  printf("]}\n");
}

static void h_derive_hints(const char *json, const char *id) {
  char kind[128]={0}, summary[MAX_LINE]={0};
  char energy[64]={0}, mobility[64]={0}, busyness[64]={0};
  char attention[64]={0}, city[128]={0};
  float readiness=-1.0f, free_min=-1.0f;
  jstr(json,"kind",kind,sizeof(kind)); jstr(json,"summary",summary,sizeof(summary));
  jstr(json,"energy",energy,sizeof(energy)); jstr(json,"mobility",mobility,sizeof(mobility));
  jstr(json,"busyness",busyness,sizeof(busyness)); jstr(json,"attention",attention,sizeof(attention));
  jstr(json,"city",city,sizeof(city));
  jnum_flex(json,"readiness",&readiness); jnum_flex(json,"freeMinutes",&free_min);
  Hint hints[MAX_HINTS];
  int n=derive_hints(kind,summary,energy,readiness,mobility,busyness,attention,city,free_min,hints,MAX_HINTS);
  write_ok(id); printf(",\"hints\":[");
  for (int i=0;i<n;i++) {
    char he[640],be[64]; json_esc(hints[i].hint,he,sizeof(he)); json_esc(hints[i].bucket,be,sizeof(be));
    if (i) putchar(',');
    printf("{\"hint\":\"%s\",\"bucket\":\"%s\",\"w\":%.2f}",he,be,hints[i].w);
  }
  printf("]}\n");
}

static void h_classify_intent(const char *json, const char *id) {
  char text[MAX_LINE]={0};
  if (!jstr(json,"text",text,sizeof(text))) { write_err(id,"missing text"); return; }
  const char *intent=classify_intent(text);
  write_ok(id); printf(",\"intent\":\"%s\"}\n",intent);
}

static void h_score_sentiment(const char *json, const char *id) {
  char text[MAX_LINE]={0};
  if (!jstr(json,"text",text,sizeof(text))) { write_err(id,"missing text"); return; }
  char label[16]={0}; float score=0.5f; int pos=0, neg=0;
  score_sentiment(text,label,&score,&pos,&neg);
  char le[24]; json_esc(label,le,sizeof(le));
  write_ok(id);
  printf(",\"label\":\"%s\",\"score\":%.4f,\"positive\":%d,\"negative\":%d}\n",le,score,pos,neg);
}

static void h_detect_language(const char *json, const char *id) {
  char text[MAX_LINE]={0};
  if (!jstr(json,"text",text,sizeof(text))) { write_err(id,"missing text"); return; }
  char lang[8]={0}; float conf=0.5f;
  detect_language(text,lang,&conf);
  char le[12]; json_esc(lang,le,sizeof(le));
  write_ok(id); printf(",\"lang\":\"%s\",\"confidence\":%.4f}\n",le,conf);
}

static void h_extract_keywords(const char *json, const char *id) {
  char text[MAX_LINE]={0};
  if (!jstr(json,"text",text,sizeof(text))) { write_err(id,"missing text"); return; }
  float fn=8.0f; jnum_flex(json,"topN",&fn);
  int topN=(int)fn; if (topN<1) topN=1; if (topN>MAX_KW) topN=MAX_KW;
  char kws[MAX_KW][MAX_TOKEN_LEN];
  int n=extract_keywords(text,kws,topN);
  write_ok(id); printf(",\"keywords\":[");
  for (int i=0;i<n;i++) {
    char esc[MAX_TOKEN_LEN*2]; json_esc(kws[i],esc,sizeof(esc));
    if (i) putchar(',');
    printf("\"%s\"",esc);
  }
  printf("]}\n");
}

static void h_score_complexity(const char *json, const char *id) {
  char text[MAX_LINE]={0};
  if (!jstr(json,"text",text,sizeof(text))) { write_err(id,"missing text"); return; }
  float avg_sent=0.0f, vocab_rich=0.0f;
  int tok_count=0, sent_count=0;
  score_complexity(text,&avg_sent,&vocab_rich,&tok_count,&sent_count);
  write_ok(id);
  printf(",\"avgSentenceLen\":%.2f,\"vocabRichness\":%.4f,\"tokenCount\":%d,\"sentenceCount\":%d}\n",
         avg_sent,vocab_rich,tok_count,sent_count);
}

/* ════════════════════════════════════════════════════════════════════════
 * Token bucket rate limiter — per-user in-process, zero DB
 *
 * Per-plan rates:
 *   free  → 5 req/min  = 0.0833/s  burst 3
 *   solo  → 20 req/min = 0.3333/s  burst 8
 *   pro   → 60 req/min = 1.0000/s  burst 20
 *
 * Bucket slots: up to 2048 users (LRU-evict oldest on overflow).
 * ════════════════════════════════════════════════════════════════════════ */

#define TB_SLOTS 2048
#define TB_KEY_LEN 64

typedef struct {
  char    key[TB_KEY_LEN];
  float   tokens;
  float   rate;
  float   capacity;
  double  last_refill;
} TBucket;

static TBucket g_buckets[TB_SLOTS];
static int     g_bucket_n = 0;

static double tb_now(void) {
  struct timespec ts;
  clock_gettime(CLOCK_MONOTONIC, &ts);
  return (double)ts.tv_sec + (double)ts.tv_nsec * 1e-9;
}

static void tb_plan_params(const char *plan, float *rate_out, float *cap_out) {
  if (!plan || !*plan || !strcmp(plan,"free")) {
    *rate_out = 5.0f / 60.0f;
    *cap_out  = 3.0f;
  } else if (!strcmp(plan,"solo")) {
    *rate_out = 20.0f / 60.0f;
    *cap_out  = 8.0f;
  } else if (!strcmp(plan,"pro")) {
    *rate_out = 60.0f / 60.0f;
    *cap_out  = 20.0f;
  } else {
    *rate_out = 5.0f / 60.0f;
    *cap_out  = 3.0f;
  }
}

static TBucket *tb_find_or_create(const char *key, float rate, float cap) {
  for (int i = 0; i < g_bucket_n; i++) {
    if (!strcmp(g_buckets[i].key, key)) return &g_buckets[i];
  }
  int slot;
  if (g_bucket_n < TB_SLOTS) {
    slot = g_bucket_n++;
  } else {
    memmove(&g_buckets[0], &g_buckets[1], sizeof(TBucket) * (TB_SLOTS - 1));
    slot = TB_SLOTS - 1;
  }
  TBucket *b = &g_buckets[slot];
  strncpy(b->key, key, TB_KEY_LEN - 1);
  b->key[TB_KEY_LEN - 1] = '\0';
  b->tokens      = cap;
  b->rate        = rate;
  b->capacity    = cap;
  b->last_refill = tb_now();
  return b;
}

static int tb_consume(const char *userId, const char *plan, float *retry_after_ms_out) {
  char key[TB_KEY_LEN];
  snprintf(key, sizeof(key), "%s|%s", userId, plan ? plan : "free");
  float rate, cap;
  tb_plan_params(plan, &rate, &cap);
  TBucket *b = tb_find_or_create(key, rate, cap);
  double now = tb_now();
  float elapsed = (float)(now - b->last_refill);
  b->tokens = b->tokens + elapsed * b->rate;
  if (b->tokens > b->capacity) b->tokens = b->capacity;
  b->last_refill = now;
  if (b->tokens >= 1.0f) {
    b->tokens -= 1.0f;
    *retry_after_ms_out = 0.0f;
    return 1;
  }
  float wait_tokens = 1.0f - b->tokens;
  *retry_after_ms_out = (wait_tokens / b->rate) * 1000.0f;
  return 0;
}

static void h_rate_check(const char *json, const char *id) {
  char userId[TB_KEY_LEN] = {0};
  char plan[16]           = {0};
  if (!jstr(json, "userId", userId, sizeof(userId))) {
    write_err(id, "missing userId");
    return;
  }
  jstr(json, "plan", plan, sizeof(plan));
  float retry_ms = 0.0f;
  int allowed = tb_consume(userId, plan, &retry_ms);
  write_ok(id);
  printf(",\"allowed\":%s,\"retryAfterMs\":%d}\n",
         allowed ? "true" : "false",
         allowed ? 0 : (int)(retry_ms + 0.5f));
}

static void h_estimate_tokens(const char *json, const char *id) {
  char text[MAX_LINE] = {0};
  if (!jstr(json, "text", text, sizeof(text))) { write_err(id, "missing text"); return; }
  int n = 0, in_space = 1;
  for (const char *p = text; *p; p++) {
    unsigned char c = (unsigned char)*p;
    if (c == ' ' || c == '\t' || c == '\n' || c == '\r') {
      if (!in_space) { n++; in_space = 1; }
    } else {
      n++; in_space = 0;
    }
  }
  int estimate = n > 0 ? (int)((n + 3) / 4) : 0;
  if (estimate < 1 && n > 0) estimate = 1;
  write_ok(id);
  printf(",\"tokens\":%d,\"chars\":%d}\n", estimate, n);
}

/* ── Chunk budget selector ───────────────────────────────────────────── */
/*
 * Given an array of {id, charCount} chunk descriptors and a budget,
 * selects chunk IDs (greedy, first-fit) that fit within the budget.
 * Edge chunks (position near 0 or 1) are scored higher.
 *
 * Input:  {"type":"chunk_budget","_id":"...","chunks":[{"id":"...","charCount":N,"position":F}],"budgetChars":N}
 * Output: {"ok":true,"_id":"...","selected":["id1","id2",...]}
 */

#define CB_MAX_CHUNKS 256
#define CB_ID_LEN     128

typedef struct { char id[CB_ID_LEN]; int chars; float pos; } CBChunk;

static int cb_cmp(const void *a, const void *b) {
  const CBChunk *ca = (const CBChunk *)a;
  const CBChunk *cb = (const CBChunk *)b;
  /* Edge boost: pos near 0 or 1 scores higher */
  float sa = (ca->pos < 0.15f || ca->pos > 0.85f) ? 2.0f - ca->pos * 0.1f : 1.0f - ca->pos * 0.1f;
  float sb = (cb->pos < 0.15f || cb->pos > 0.85f) ? 2.0f - cb->pos * 0.1f : 1.0f - cb->pos * 0.1f;
  return (sb > sa) ? 1 : (sb < sa) ? -1 : 0;
}

/* Parse array: [{"id":"...","charCount":N,"position":F}, ...] */
static int parse_cb_chunks(const char *json, CBChunk *out, int maxn) {
  const char *p = strchr(json, '[');
  if (!p) return 0;
  int n = 0;
  while (n < maxn && *p) {
    const char *ob = strchr(p, '{');
    if (!ob) break;
    const char *cb_e = strchr(ob, '}');
    if (!cb_e) break;
    char obj[512] = {0};
    int olen = (int)(cb_e - ob + 1);
    if (olen >= (int)sizeof(obj)) { p = cb_e + 1; continue; }
    memcpy(obj, ob, olen);
    char idv[CB_ID_LEN] = {0};
    jstr(obj, "id", idv, sizeof(idv));
    if (!idv[0]) { p = cb_e + 1; continue; }
    strncpy(out[n].id, idv, CB_ID_LEN - 1);
    char numv[32] = {0};
    jstr(obj, "charCount", numv, sizeof(numv)); out[n].chars = numv[0] ? atoi(numv) : 0;
    jstr(obj, "position", numv, sizeof(numv));  out[n].pos   = numv[0] ? (float)atof(numv) : 0.5f;
    n++;
    p = cb_e + 1;
  }
  return n;
}

static void h_chunk_budget(const char *json, const char *id) {
  char budget_str[32] = {0};
  if (!jstr(json, "budgetChars", budget_str, sizeof(budget_str))) { write_err(id, "missing budgetChars"); return; }
  int budget = atoi(budget_str);
  if (budget <= 0) { write_err(id, "invalid budgetChars"); return; }

  CBChunk chunks[CB_MAX_CHUNKS];
  int n = parse_cb_chunks(json, chunks, CB_MAX_CHUNKS);
  if (n == 0) {
    write_ok(id);
    printf(",\"selected\":[]}\n");
    return;
  }

  /* Sort by score descending */
  qsort(chunks, n, sizeof(CBChunk), cb_cmp);

  /* Greedy fill */
  char selected[CB_MAX_CHUNKS][CB_ID_LEN];
  int sel_n = 0, used = 0;
  for (int i = 0; i < n; i++) {
    if (used + chunks[i].chars > budget) continue;
    strncpy(selected[sel_n++], chunks[i].id, CB_ID_LEN - 1);
    used += chunks[i].chars;
  }

  write_ok(id);
  printf(",\"selected\":[");
  for (int i = 0; i < sel_n; i++) {
    char esc[CB_ID_LEN * 2] = {0};
    json_esc(selected[i], esc, sizeof(esc));
    if (i) putchar(',');
    printf("\"%s\"", esc);
  }
  printf("]}\n");
}

/* ── Search query cleaner ────────────────────────────────────────────── */
/*
 * Strips Turkish + English stopwords from a search query and normalises
 * whitespace.  Only ASCII-range lowercasing — Türkçe özel harfler
 * (ç, ğ, ı, ö, ş, ü) are NOT lowercased here; the caller lowercases first
 * if needed.  Works on UTF-8 as byte stream (stopwords are ASCII tokens).
 *
 * Input:  {"type":"clean_search_query","_id":"...","query":"..."}
 * Output: {"ok":true,"_id":"...","query":"cleaned query"}
 */

static const char *TR_STOPWORDS[] = {
  "ve","bir","bu","da","de","için","ile","mi","mı","mu","mü",
  "ne","var","yok","ama","ya","ki","ben","sen","biz","siz",
  "o","bu","şu","su","hangi","kadar","daha","en","çok","cok",
  "gibi","göre","gore","sonra","önce","once","üzere","uzere",
  "her","hiç","hic","bile","dahi","sadece","ancak","fakat",
  "lakin","ise","değil","degil","veya","ya da","hem","hem de",
  "nasıl","nasil","neden","niçin","nicin","nerede","nereye",
  "ne zaman","kim","kimi","kime","kimin","hangi","hangisi",
  "kaç","kac","kaçta","nacta","ne kadar","nasıl",
  NULL
};

static const char *EN_STOPWORDS[] = {
  "a","an","the","and","or","but","in","on","at","to","for",
  "of","with","by","from","is","are","was","were","be","been",
  "have","has","had","do","does","did","will","would","could",
  "should","may","might","can","that","this","these","those",
  "it","its","i","we","you","he","she","they","what","which",
  "who","how","when","where","why","not","no","yes","about",
  "as","if","so","then","than","more","most","also","just",
  NULL
};

/* Returns 1 if `tok` (lowercase) is a stopword */
static int is_stopword(const char *tok) {
  for (int i = 0; TR_STOPWORDS[i]; i++)
    if (!strcmp(tok, TR_STOPWORDS[i])) return 1;
  for (int i = 0; EN_STOPWORDS[i]; i++)
    if (!strcmp(tok, EN_STOPWORDS[i])) return 1;
  return 0;
}

/* Lowercase ASCII only (leaves Türkçe multibyte chars intact) */
static void ascii_lower(char *s) {
  for (; *s; s++)
    if (*s >= 'A' && *s <= 'Z') *s = (char)(*s + 32);
}

static void h_clean_search_query(const char *json, const char *id) {
  char query[MAX_LINE] = {0};
  if (!jstr(json, "query", query, sizeof(query))) { write_err(id, "missing query"); return; }

  /* ASCII lowercase for stopword matching */
  char lower[MAX_LINE];
  strncpy(lower, query, sizeof(lower)-1);
  lower[sizeof(lower)-1] = '\0';
  ascii_lower(lower);

  /* Split on whitespace, drop stopwords, keep original-case tokens */
  char out[MAX_LINE] = {0};
  int out_len = 0;
  char *orig_p = query, *low_p = lower;
  int first = 1;

  while (*orig_p) {
    /* skip leading whitespace */
    while (*orig_p == ' ' || *orig_p == '\t') { orig_p++; low_p++; }
    if (!*orig_p) break;

    /* collect token */
    char tok_orig[MAX_TOKEN_LEN] = {0};
    char tok_low[MAX_TOKEN_LEN]  = {0};
    int ti = 0;
    while (*orig_p && *orig_p != ' ' && *orig_p != '\t' && ti < (int)sizeof(tok_orig)-1) {
      tok_orig[ti] = *orig_p++;
      tok_low[ti]  = *low_p++;
      ti++;
    }
    tok_orig[ti] = tok_low[ti] = '\0';

    if (!is_stopword(tok_low) && ti > 0) {
      int space = first ? 0 : 1;
      if (out_len + ti + space < (int)sizeof(out) - 1) {
        if (!first) out[out_len++] = ' ';
        memcpy(out + out_len, tok_orig, ti);
        out_len += ti;
        out[out_len] = '\0';
        first = 0;
      }
    }
  }

  /* If nothing survived stopword filter, keep original */
  if (out_len == 0) {
    strncpy(out, query, sizeof(out)-1);
    out[sizeof(out)-1] = '\0';
  }

  char escaped[MAX_LINE*2] = {0};
  json_esc(out, escaped, sizeof(escaped));
  write_ok(id);
  printf(",\"query\":\"%s\"}\n", escaped);
}

/* ── Main event loop ─────────────────────────────────────────────────── */

int main(void) {
  setbuf(stdout,NULL);
  char line[MAX_LINE], type[64], req_id[64];
  while (fgets(line,sizeof(line),stdin)) {
    int len=(int)strlen(line);
    while (len>0&&(line[len-1]=='\n'||line[len-1]=='\r')) line[--len]='\0';
    if (!len) continue;
    type[0]='\0'; req_id[0]='\0';
    jstr(line,"type",type,sizeof(type)); jstr(line,"_id",req_id,sizeof(req_id));
    if      (!strcmp(type,"ping"))            h_ping(req_id);
    else if (!strcmp(type,"tokenize"))        h_tokenize(line,req_id);
    else if (!strcmp(type,"score_bm25"))      h_score_bm25(line,req_id);
    else if (!strcmp(type,"bm25_batch"))      h_bm25_batch(line,req_id);
    else if (!strcmp(type,"embed_256"))       h_embed_256(line,req_id);
    else if (!strcmp(type,"cosine_sim"))      h_cosine_sim(line,req_id);
    else if (!strcmp(type,"extract_facts"))   h_extract_facts(line,req_id);
    else if (!strcmp(type,"derive_hints"))    h_derive_hints(line,req_id);
    else if (!strcmp(type,"classify_intent"))  h_classify_intent(line,req_id);
    else if (!strcmp(type,"score_sentiment"))  h_score_sentiment(line,req_id);
    else if (!strcmp(type,"detect_language"))  h_detect_language(line,req_id);
    else if (!strcmp(type,"extract_keywords")) h_extract_keywords(line,req_id);
    else if (!strcmp(type,"score_complexity")) h_score_complexity(line,req_id);
    else if (!strcmp(type,"rate_check"))       h_rate_check(line,req_id);
    else if (!strcmp(type,"estimate_tokens"))      h_estimate_tokens(line,req_id);
    else if (!strcmp(type,"clean_search_query"))   h_clean_search_query(line,req_id);
    else if (!strcmp(type,"chunk_budget"))          h_chunk_budget(line,req_id);
    else write_err(req_id,"unknown type");
    fflush(stdout);
  }
  return 0;
}
