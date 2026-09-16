import sys,pickle,struct,collections,bisect
sys.path.insert(0,'tools')
from soa import dol as D
from soa.ppc import decode
exec(open('scratch/gx/tables.py').read())
SCR=r'C:\Users\bmfre\AppData\Local\Temp\claude\C--Users-bmfre\ea97428e-9906-4826-98b8-90b86878c881\scratchpad'
d=D.parse(open('extracted/sys/main.dol','rb').read())
funcs=sorted(pickle.load(open(SCR+r'\skies_funcs.pkl','rb')));fstarts=set(f[0] for f in funcs)
TEXT=[s for s in d.sections if s.is_text]
TLO,THI=0x80003100,0x80005600+2781664
R13=0x8034E720;R2=0x80350000
insns={};order=[]
for s in TEXT:
    b=d.data[s.file_offset:s.file_offset+s.size]
    for i in range(0,s.size,4):
        a=s.address+i;insns[a]=decode(struct.unpack_from('>I',b,i)[0],a);order.append(a)
oset=set(order)
unk=set(fstarts)
for s in d.sections:
    b=d.data[s.file_offset:s.file_offset+s.size]
    for i in range(0,s.size-3,4):
        v=struct.unpack_from('>I',b,i)[0]
        if v in oset: unk.add(v)
for s in TEXT: unk.add(s.address)
for a in order:
    if not insns[a].valid: unk.add(a);unk.add(a+4)
succ=collections.defaultdict(list)
for a in order:
    i=insns[a]
    if not i.valid: continue
    m=i.mnemonic
    if m in ('b','bc'):
        if i.target in oset: succ[a].append(i.target)
        if m=='bc' and (not i.is_unconditional or i.lk_bit) and a+4 in oset: succ[a].append(a+4)
        if m=='b' and i.lk_bit and a+4 in oset: succ[a].append(a+4)
    elif m in ('bclr','bcctr'):
        if (i.lk_bit or not i.is_unconditional) and a+4 in oset: succ[a].append(a+4)
    elif m in ('rfi','sc'): pass
    else:
        if a+4 in oset: succ[a].append(a+4)

GLOB={}   # ea -> const value  (oracle for loads)
def run():
    def transfer(a,st):
        i=insns[a]
        if not i.valid: return {}
        m=i.mnemonic;r=dict(st)
        if m=='lwz':
            ea=None
            if i.ra in r: ea=(r[i.ra]+i.imm)&0xFFFFFFFF
            if ea is not None and ea in GLOB: r[i.rd]=GLOB[ea]
            else: r.pop(i.rd,None)
            return r
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
    IN={};wl=collections.deque()
    for a in order:
        if a in unk: IN[a]={};wl.append(a)
    SENT=object()
    # seed r13/r2 everywhere (they are fixed for the whole program after __init_registers)
    for a in list(IN): IN[a]={13:R13,2:R2}
    while wl:
        a=wl.popleft();st=IN.get(a)
        if st is None: continue
        out=transfer(a,st)
        for t in succ.get(a,()):
            cur=IN.get(t)
            if cur is None: IN[t]=dict(out);wl.append(t)
            else:
                new={k:v for k,v in cur.items() if out.get(k,SENT)==v}
                if len(new)!=len(cur): IN[t]=new;wl.append(t)
    return IN

MMIOR=lambda v: 0xCC000000<=v<0xCC008200 or 0x0C000000<=v<0x0C008200 or 0xC8000000<=v<0xC8400000
for rnd in range(4):
    IN=run()
    # find stores of MMIO constants into fixed globals
    cand=collections.defaultdict(set)
    nstore=collections.defaultdict(int)
    for a in order:
        i=insns[a]
        if not i.valid or i.mnemonic!='stw': continue
        st=IN.get(a) or {}
        if i.ra not in st: continue
        ea=(st[i.ra]+i.imm)&0xFFFFFFFF
        if not (0x80302A00<=ea<0x8034D4C4 or 0x80346720<=ea<0x8034D460): continue
        nstore[ea]+=1
        if i.rd in st and MMIOR(st[i.rd]): cand[ea].add(st[i.rd])
    newg={ea:list(vs)[0] for ea,vs in cand.items() if len(vs)==1 and nstore[ea]==1}
    added={k:v for k,v in newg.items() if GLOB.get(k)!=v}
    print("round",rnd,"global MMIO pointers found:",len(newg),"new:",len(added))
    if not added: break
    GLOB.update(newg)
print("\nGLOBAL MMIO POINTER TABLE (written exactly once):")
for ea,v in sorted(GLOB.items()):
    print("  [0x%08X] (r13%+d) = 0x%08X"%(ea,ea-R13,v))
# final memop resolution
memops=[];unres=collections.Counter()
for a in order:
    i=insns[a]
    if not i.valid or i.mnemonic not in MEM: continue
    st=IN.get(a) or {}
    ra=i.ra;ea=None
    if i.mnemonic in XFORM:
        if (ra==0 or ra in st) and i.rb in st: ea=((st.get(ra,0) if ra else 0)+st[i.rb])&0xFFFFFFFF
    else:
        if ra==0: ea=i.imm&0xFFFFFFFF
        elif ra in st: ea=(st[ra]+i.imm)&0xFFFFFFFF
    if ea is not None: memops.append((a,i.mnemonic,ea,ra))
    else: unres[i.mnemonic]+=1
print("\nresolved memops:",len(memops),"unresolved:",sum(unres.values()))
pickle.dump({'memops':memops,'GLOB':GLOB},open('scratch/gx/flow2.pkl','wb'))
