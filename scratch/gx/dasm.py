import sys,struct,bisect,pickle
sys.path.insert(0,'tools')
from soa import dol as D
from soa.ppc import decode
SCR=r'C:\Users\bmfre\AppData\Local\Temp\claude\C--Users-bmfre\ea97428e-9906-4826-98b8-90b86878c881\scratchpad'
d=D.parse(open('extracted/sys/main.dol','rb').read())
def dis(lo,hi):
    a=lo
    while a<hi:
        w=d.word(a); i=decode(w,a)
        ops=[]
        if i.rd>=0: ops.append('rd=%d'%i.rd)
        if i.ra>=0: ops.append('ra=%d'%i.ra)
        if i.rb>=0: ops.append('rb=%d'%i.rb)
        if i.imm: ops.append('imm=%d/0x%X'%(i.imm,i.imm&0xFFFF))
        if i.gqr>=0: ops.append('gqr=%d w=%d'%(i.gqr,i.quant_w))
        if i.spr>=0: ops.append('spr=%d'%i.spr)
        t=i.target if i.valid and i.is_direct_branch else None
        print(f"{a:08X}  {w:08X}  {i.mnemonic:<9} {' '.join(ops)}"+(f"  -> 0x{t:08X}" if t else ""))
        a+=4
import sys as S
for spec in S.argv[1:]:
    lo,hi=spec.split(':'); print(f"\n######## {lo}..{hi}"); dis(int(lo,16),int(hi,16))
