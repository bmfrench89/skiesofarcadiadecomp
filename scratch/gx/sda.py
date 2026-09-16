import sys,pickle,struct,collections,bisect
sys.path.insert(0,'tools')
from soa import dol as D
from soa.ppc import decode
exec(open('scratch/gx/tables.py').read())
SCR=r'C:\Users\bmfre\AppData\Local\Temp\claude\C--Users-bmfre\ea97428e-9906-4826-98b8-90b86878c881\scratchpad'
d=D.parse(open('extracted/sys/main.dol','rb').read())
R13=0x8034E720
funcs=sorted(pickle.load(open(SCR+r'\skies_funcs.pkl','rb')));fstarts=[f[0] for f in funcs]
sdk={}
for ln in open(SCR+r'\skies_sdk_symbols.txt'):
    if ln.startswith('0x'): p=ln.split(); sdk[int(p[0],16)]=p[2]
def fn(a):
    i=bisect.bisect_right(fstarts,a)-1;f=funcs[i]
    return (f[0],sdk.get(f[0],f[2]))
# find, per function, "lwz rD, d(r13)"  followed within the function by use of rD as mem base
insns={}
for s in d.sections:
    if not s.is_text: continue
    b=d.data[s.file_offset:s.file_offset+s.size]
    for i in range(0,s.size,4):
        a=s.address+i;insns[a]=decode(struct.unpack_from('>I',b,i)[0],a)
order=sorted(insns)
# map: sda-global -> set of (func, memop-mnem, disp) where the loaded value is used as base
ptr=collections.defaultdict(lambda: collections.Counter())
writers=collections.defaultdict(set)
for idx,a in enumerate(order):
    i=insns[a]
    if not i.valid: continue
    if i.mnemonic=='lwz' and i.ra==13:
        g=(R13+i.imm)&0xFFFFFFFF; rD=i.rd
        # scan forward up to 12 insns in the same function
        f0=fn(a)[0]
        for j in range(idx+1,min(idx+13,len(order))):
            b2=order[j];i2=insns[b2]
            if not i2.valid or fn(b2)[0]!=f0: break
            if i2.mnemonic in MEM and i2.ra==rD and i2.mnemonic not in XFORM:
                ptr[g][(i2.mnemonic,i2.imm)]+=1
            # rD redefined?
            if i2.mnemonic in DEST_RD and i2.rd==rD: break
            if i2.mnemonic in DEST_RA and i2.ra==rD: break
    if i.mnemonic in ('stw','stwu') and i.ra==13:
        writers[(R13+i.imm)&0xFFFFFFFF].add(fn(a))
# which globals look like MMIO bases: used with small positive displacements in GX/SDK funcs
print("SDA globals used as memory bases, with displacement profile (top 30 by use):")
for g,c in sorted(ptr.items(), key=lambda kv:-sum(kv[1].values()))[:30]:
    tot=sum(c.values())
    ds=sorted(set(dd for _,dd in c))
    ws=writers.get(g,set())
    print("  0x%08X (r13%+d) uses=%-4d disps=%s writers=%s"%(g,g-R13,tot,ds[:14],[('0x%08X %s'%w) for w in sorted(ws)][:4]))
