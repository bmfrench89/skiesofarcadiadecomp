import sys,pickle,struct,collections,bisect
sys.path.insert(0,'tools')
from soa import dol as D
from soa.ppc import decode
SCR=r'C:\Users\bmfre\AppData\Local\Temp\claude\C--Users-bmfre\ea97428e-9906-4826-98b8-90b86878c881\scratchpad'
d=D.parse(open('extracted/sys/main.dol','rb').read())
funcs=sorted(pickle.load(open(SCR+r'\skies_funcs.pkl','rb')));fstarts=set(f[0] for f in funcs)
TEXT=[s for s in d.sections if s.is_text]
TLO,THI=0x80003100,0x80005600+2781664
exec(open('scratch/gx/tables.py').read())

insns={};order=[]
for s in TEXT:
    b=d.data[s.file_offset:s.file_offset+s.size]
    for i in range(0,s.size,4):
        a=s.address+i; insns[a]=decode(struct.unpack_from('>I',b,i)[0],a); order.append(a)
oset=set(order)

# unknown-entry points
unk=set(fstarts)
for s in d.sections:
    b=d.data[s.file_offset:s.file_offset+s.size]
    for i in range(0,s.size-3,4):
        v=struct.unpack_from('>I',b,i)[0]
        if TLO<=v<THI and (v&3)==0 and v in oset: unk.add(v)
for s in TEXT: unk.add(s.address)
# invalid words: treat following insn as unknown entry
for a in order:
    if not insns[a].valid: unk.add(a); unk.add(a+4)

succ=collections.defaultdict(list)
for a in order:
    i=insns[a]
    if not i.valid: continue
    m=i.mnemonic
    if m=='b':
        if i.target in oset: succ[a].append(i.target)
    elif m=='bc':
        if i.target in oset: succ[a].append(i.target)
        if not i.is_unconditional and a+4 in oset: succ[a].append(a+4)
        elif i.lk_bit and a+4 in oset: succ[a].append(a+4)
    elif m in ('bclr','bcctr'):
        if i.lk_bit or not i.is_unconditional:
            if a+4 in oset: succ[a].append(a+4)
    elif m in ('rfi','sc'):
        pass
    else:
        if a+4 in oset: succ[a].append(a+4)
    if m=='b' and i.lk_bit and a+4 in oset: succ[a].append(a+4)
pred=collections.defaultdict(list)
for a,ss in succ.items():
    for t in ss: pred[t].append(a)

def transfer(a,st):
    i=insns[a]
    if not i.valid: return {}
    m=i.mnemonic; r=dict(st)
    if m=='lis' or (m=='addis' and i.ra==0): r[i.rd]=(i.imm<<16)&0xFFFFFFFF
    elif m=='addi' and i.ra==0: r[i.rd]=i.imm&0xFFFFFFFF
    elif m=='addi' and i.ra in r: r[i.rd]=(r[i.ra]+i.imm)&0xFFFFFFFF
    elif m=='addis' and i.ra in r: r[i.rd]=(r[i.ra]+(i.imm<<16))&0xFFFFFFFF
    elif m=='ori' and i.ra in r: r[i.rd]=(r[i.ra]|(i.imm&0xFFFF))&0xFFFFFFFF
    elif m=='oris' and i.ra in r: r[i.rd]=(r[i.ra]|((i.imm&0xFFFF)<<16))&0xFFFFFFFF
    elif m=='or' and i.rd==i.rb:
        if i.rd in r: r[i.ra]=r[i.rd]
        else: r.pop(i.ra,None)
    else:
        if m in DEST_RD:
            r.pop(i.rd,None)
            if m=='lmw':
                for x in range(i.rd,32): r.pop(x,None)
        elif m in DEST_RA: r.pop(i.ra,None)
        elif m in NO_GPR: pass
        else: r={}
        if m in UPD_RA: r.pop(i.ra,None)
    if i.is_call:
        for x in list(r):
            if x==0 or 3<=x<=12: r.pop(x,None)
    return r

IN={}
wl=collections.deque()
for a in order:
    if a in unk: IN[a]={}; wl.append(a)
INIT=object()
cnt=0
while wl:
    a=wl.popleft(); cnt+=1
    st=IN.get(a)
    if st is None: continue
    out=transfer(a,st)
    for t in succ.get(a,()):
        cur=IN.get(t)
        if cur is None:
            IN[t]=dict(out); wl.append(t)
        else:
            new={k:v for k,v in cur.items() if out.get(k,INIT)==v}
            if len(new)!=len(cur):
                IN[t]=new; wl.append(t)
print("fixpoint iterations:",cnt,"reached:",len(IN),"/",len(order))

memops=[];unres=collections.Counter();lis_sites=collections.defaultdict(list)
for a in order:
    i=insns[a]
    if not i.valid: continue
    st=IN.get(a)
    if st is None: st={}
    m=i.mnemonic
    if m in MEM:
        ra=i.ra; ea=None
        if m in XFORM:
            if (ra==0 or ra in st) and i.rb in st: ea=((st.get(ra,0) if ra else 0)+st[i.rb])&0xFFFFFFFF
        else:
            if ra==0: ea=i.imm&0xFFFFFFFF
            elif ra in st: ea=(st[ra]+i.imm)&0xFFFFFFFF
        if ea is not None: memops.append((a,m,ea,ra))
        else: unres[m]+=1
    if m=='lis' or (m=='addis' and i.ra==0):
        v=(i.imm<<16)&0xFFFFFFFF
        if (v>>24) in (0xCC,0xCD,0xC8,0xC0): lis_sites[v].append(a)
print("resolved:",len(memops),"unresolved:",sum(unres.values()))
pickle.dump({'memops':memops,'lis':dict(lis_sites),'IN_unres':dict(unres)},open('scratch/gx/flow.pkl','wb'))
gp=[x for x in memops if x[2]==0xCC008000]
print("\nEA==0xCC008000:",len(gp),dict(collections.Counter(x[1] for x in gp).most_common()))
print("near range CC008000-CC0080FF:",sum(1 for x in memops if 0xCC008000<=x[2]<0xCC008100))
