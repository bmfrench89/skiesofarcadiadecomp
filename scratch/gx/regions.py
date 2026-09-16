import sys,pickle,struct,collections,bisect
sys.path.insert(0,'tools')
from soa import dol as D
from soa.ppc import decode
exec(open('scratch/gx/tables.py').read())
SCR=r'C:\Users\bmfre\AppData\Local\Temp\claude\C--Users-bmfre\ea97428e-9906-4826-98b8-90b86878c881\scratchpad'
d=D.parse(open('extracted/sys/main.dol','rb').read())
F=pickle.load(open('scratch/gx/flow.pkl','rb'));memops=F['memops']
funcs=sorted(pickle.load(open(SCR+r'\skies_funcs.pkl','rb')));fstarts=[f[0] for f in funcs]
sdk={}
for ln in open(SCR+r'\skies_sdk_symbols.txt'):
    if ln.startswith('0x'): p=ln.split(); sdk[int(p[0],16)]=p[2]
def fn(a):
    i=bisect.bisect_right(fstarts,a)-1;f=funcs[i]
    return (f[0],sdk.get(f[0],f[2])) if f[0]<=a<f[0]+f[1] else (f[0],'~'+sdk.get(f[0],f[2]))
SDKLO,SDKHI=0x802319E0,0x80266770
REG=[('CP  Command Processor',0xCC000000,0xCC001000),
     ('PE  Pixel Engine',     0xCC001000,0xCC002000),
     ('VI  Video Interface',  0xCC002000,0xCC003000),
     ('PI  Processor Iface',  0xCC003000,0xCC004000),
     ('MI  Memory Iface',     0xCC004000,0xCC005000),
     ('DSP/AI-DMA',           0xCC005000,0xCC006000),
     ('DI  DVD Interface',    0xCC006000,0xCC006400),
     ('SI  Serial Interface', 0xCC006400,0xCC006800),
     ('EXI External Iface',   0xCC006800,0xCC006C00),
     ('AI  Audio Interface',  0xCC006C00,0xCC007000),
     ('(gap 7000-8000)',      0xCC007000,0xCC008000),
     ('GX  FIFO gather pipe', 0xCC008000,0xCC008100),
     ('(above 8100)',         0xCC008100,0xCD000000),
     ('CC01+ high',           0xCD000000,0xCE000000),
     ('EFB (C8000000)',       0xC8000000,0xC9000000)]
mm=[x for x in memops if 0xC8000000<=x[2]<0xCE000000]
print("total resolved MMIO-range ops:",len(mm))
print(f"\n{'region':26s} {'st':>5s} {'ld':>5s} {'sites':>6s} {'funcs':>6s} {'SDKst':>6s} {'GAMEst':>6s}  distinct-offsets")
for nm,lo,hi in REG:
    ops=[x for x in mm if lo<=x[2]<hi]
    if not ops: continue
    st=[x for x in ops if x[1] in STORES];ld=[x for x in ops if x[1] in LOADS]
    fs=set(fn(x[0])[0] for x in ops)
    sdkst=sum(1 for x in st if SDKLO<=x[0]<SDKHI)
    offs=sorted(set(x[2] for x in ops))
    print(f"{nm:26s} {len(st):5d} {len(ld):5d} {len(ops):6d} {len(fs):6d} {sdkst:6d} {len(st)-sdkst:6d}  {len(offs)}")
print()
for nm,lo,hi in REG:
    ops=[x for x in mm if lo<=x[2]<hi]
    if not ops or 'FIFO' in nm: continue
    print(f"--- {nm}: {len(ops)} ops, functions touching it:")
    fc=collections.Counter(fn(x[0]) for x in ops)
    for (fa,n),c in sorted(fc.items())[:40]:
        tag='SDK' if SDKLO<=fa<SDKHI else 'GAME'
        print(f"      0x{fa:08X} {tag:4s} x{c:<3d} {n}")
    if len(fc)>40: print("      ... +%d more"%(len(fc)-40))
    offs=collections.Counter(x[2] for x in ops)
    print("      offsets:", ' '.join('%04X:%d'%(o&0xFFFF,c) for o,c in sorted(offs.items())))
pickle.dump(mm,open('scratch/gx/mm.pkl','wb'))
