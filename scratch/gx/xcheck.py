import sys,pickle,struct,collections,bisect
sys.path.insert(0,'tools')
from soa import dol as D
from soa.ppc import decode
exec(open('scratch/gx/tables.py').read())
SCR=r'C:\Users\bmfre\AppData\Local\Temp\claude\C--Users-bmfre\ea97428e-9906-4826-98b8-90b86878c881\scratchpad'
d=D.parse(open('extracted/sys/main.dol','rb').read())
F=pickle.load(open('scratch/gx/flow.pkl','rb'))
flowset=set(a for a,m,ea,ra in F['memops'] if ea==0xCC008000)
# syntactic: any d-form store with displacement exactly -32768
syn=[];allm=collections.Counter()
for s in d.sections:
    if not s.is_text: continue
    b=d.data[s.file_offset:s.file_offset+s.size]
    for i in range(0,s.size,4):
        a=s.address+i; ins=decode(struct.unpack_from('>I',b,i)[0],a)
        if ins.valid and ins.mnemonic in STORES and ins.mnemonic not in XFORM and ins.imm==-32768 and ins.ra!=1:
            syn.append((a,ins.mnemonic,ins.ra)); allm[ins.mnemonic]+=1
print("syntactic st*(-0x8000, rN!=r1):",len(syn),dict(allm))
ss=set(a for a,_,_ in syn)
print("  in flow set:",len(ss&flowset)," syn-only:",len(ss-flowset)," flow-only:",len(flowset-ss))
print("  syn-only sample:",[hex(a) for a in sorted(ss-flowset)[:12]])
print("  flow-only sample:",[hex(a) for a in sorted(flowset-ss)[:12]])
for a in sorted(flowset-ss)[:6]:
    ins=decode(d.word(a),a); print("   flow-only 0x%08X %s ra=%d imm=%d"%(a,ins.mnemonic,ins.ra,ins.imm))
