import sys,pickle,struct,collections,bisect
sys.path.insert(0,'tools')
from soa import dol as D
from soa.ppc import decode
exec(open('scratch/gx/tables.py').read())
SCR=r'C:\Users\bmfre\AppData\Local\Temp\claude\C--Users-bmfre\ea97428e-9906-4826-98b8-90b86878c881\scratchpad'
d=D.parse(open('extracted/sys/main.dol','rb').read())
F=pickle.load(open('scratch/gx/flow3.pkl','rb'))
funcs=sorted(pickle.load(open(SCR+r'\skies_funcs.pkl','rb')));fstarts=[f[0] for f in funcs]
sdk={}
for ln in open(SCR+r'\skies_sdk_symbols.txt'):
    if ln.startswith('0x'): p=ln.split(); sdk[int(p[0],16)]=p[2]
def fnm(a):
    i=bisect.bisect_right(fstarts,a)-1;f=funcs[i]
    return (f[0],sdk.get(f[0],f[2]))
SDKLO,SDKHI=0x802319E0,0x80266778
# re-run flow3's IN by re-executing it and capturing values of stored regs
src=open('scratch/gx/flow3.py').read()
src=src.split("print(\"\nGLOBAL MMIO POINTER TABLE")[0]
g={'__name__':'m'}
exec(compile(src,'f3','exec'),g)
IN=g['IN'];insns=g['insns'];order=g['order']
GP=0xCC008000
stb_const=collections.Counter();stb_var=collections.Counter()
stw_const=collections.Counter()
rows=[]
for a in order:
    i=insns[a]
    if not i.valid or i.mnemonic not in STORES: continue
    st=IN.get(a) or {}
    if i.ra not in st or ((st[i.ra]+i.imm)&0xFFFFFFFF)!=GP: continue
    zone='SDK' if SDKLO<=a<SDKHI else 'GAME'
    v=st.get(i.rd)
    rows.append((a,i.mnemonic,zone,v))
    if i.mnemonic=='stb':
        if v is not None: stb_const[(zone,v&0xFF)]+=1
        else: stb_var[zone]+=1
    if i.mnemonic=='stw' and v is not None: stw_const[(zone,v)]+=1
print("gather-pipe stores:",len(rows))
print("\n=== stb (GX command opcode byte) ===")
print("constant opcodes:")
CMD={0x00:'NOP',0x08:'LOAD_CP_REG',0x10:'LOAD_XF_REG',0x20:'LOAD_INDX_A(pos)',0x28:'LOAD_INDX_B(nrm)',
     0x30:'LOAD_INDX_C(clr)',0x38:'LOAD_INDX_D(tex)',0x40:'CALL_DL',0x48:'INVL_VC',0x61:'LOAD_BP_REG'}
def cname(v):
    if v in CMD: return CMD[v]
    if 0x80<=v<=0xBF: return 'DRAW prim=%d vat=%d'%((v>>3)&7,v&7)
    return '?'
for (z,v),n in sorted(stb_const.items()):
    print("   %-4s 0x%02X x%-4d %s"%(z,v,n,cname(v)))
print("non-constant stb (runtime opcode):",dict(stb_var))
print("\n=== stw with constant value (register-write header or payload) ===")
for (z,v),n in sorted(stw_const.items(),key=lambda kv:(kv[0][0],-kv[1]))[:60]:
    print("   %-4s 0x%08X x%d"%(z,v,n))
print("total const stw:",sum(stw_const.values()))
nc=collections.Counter((z) for a,m,z,v in rows if m=='stw' and v is None)
print("non-constant stw:",dict(nc))
byk=collections.Counter((z,m) for a,m,z,v in rows)
print("\nstores by zone/mnemonic:",dict(byk))
pickle.dump(rows,open('scratch/gx/gpstores.pkl','wb'))
