import sys,pickle,struct,collections,bisect,re
sys.path.insert(0,'tools')
from soa import dol as D
from soa.ppc import decode
SCR=r'C:\Users\bmfre\AppData\Local\Temp\claude\C--Users-bmfre\ea97428e-9906-4826-98b8-90b86878c881\scratchpad'
d=D.parse(open('extracted/sys/main.dol','rb').read())
F=pickle.load(open('scratch/gx/flow3.pkl','rb'));mo=F['memops']
funcs=sorted(pickle.load(open(SCR+r'\skies_funcs.pkl','rb')))
# collect C strings in data sections
strs={}
for s in d.sections:
    if s.is_text: continue
    b=d.data[s.file_offset:s.file_offset+s.size]
    for m in re.finditer(rb'[\x20-\x7E]{6,}\x00', b):
        strs[s.address+m.start()]=m.group()[:-1].decode('ascii','replace')
print("C strings in data:",len(strs))
# find address materialisations (lis+addi / lis+ori) pointing at strings, per text region
import collections as C
hits=C.defaultdict(list)
insns={}
for s in d.sections:
    if not s.is_text: continue
    b=d.data[s.file_offset:s.file_offset+s.size]
    for i in range(0,s.size,4):
        a=s.address+i;insns[a]=decode(struct.unpack_from('>I',b,i)[0],a)
order=sorted(insns)
hi={}
for a in order:
    i=insns[a]
    if not i.valid: continue
    if i.mnemonic in ('lis',) or (i.mnemonic=='addis' and i.ra==0):
        hi[i.rd]=(i.imm<<16)&0xFFFFFFFF
    elif i.mnemonic=='addi' and i.ra in hi:
        v=(hi[i.ra]+i.imm)&0xFFFFFFFF
        if v in strs: hits[v].append(a)
        hi.pop(i.rd,None) if i.rd!=i.ra else None
    elif i.mnemonic=='ori' and i.ra in hi:
        v=(hi[i.ra]|(i.imm&0xFFFF))&0xFFFFFFFF
        if v in strs: hits[v].append(a)
    else:
        if i.rd in hi and i.mnemonic not in ('stw','stb','sth','stfs','stfd'): hi.pop(i.rd,None)
REG=[('game-main 0x80005600-0x802319E0',0x80005600,0x802319E0),
     ('SDK 0x802319E0-0x80266778',0x802319E0,0x80266778),
     ('post-SDK 0x80266778-0x802AC7E0',0x80266778,0x802AC7E0)]
for nm,lo,hi2 in REG:
    ss=set()
    for v,ls in hits.items():
        if any(lo<=a<hi2 for a in ls): ss.add(v)
    print("\n### %s : %d distinct strings referenced"%(nm,len(ss)))
    if 'post-SDK' in nm or 'SDK ' in nm:
        for v in sorted(ss)[:60]:
            print("   0x%08X  %r"%(v,strs[v][:90]))
