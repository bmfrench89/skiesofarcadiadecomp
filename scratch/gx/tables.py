DEST_RD = set('''addi addis addic addic. subfic mulli lwz lwzu lbz lbzu lhz lhzu lha lhau
 lwzx lwzux lbzx lbzux lhzx lhzux lhax lhaux add addc adde addze addme subf subfc subfe
 subfze subfme neg mullw mulhw mulhwu divw divwu mfspr mfcr mfmsr mftb mfsr lwbrx lhbrx
 lswi lswx lwarx li lis mr lmw'''.split())
DEST_RA = set('''ori oris xori xoris andi. andis. rlwinm rlwimi rlwnm and andc or orc nand
 nor xor eqv slw srw sraw srawi extsb extsh cntlzw'''.split())
NO_GPR = set('''stw stwu stwx stwux stb stbu stbx stbux sth sthu sthx sthux stmw stswi stswx
 stwbrx sthbrx stfs stfsu stfsx stfsux stfd stfdu stfdx stfdux stfiwx psq_st psq_stu psq_stx
 psq_stux b bc bclr bcctr sc rfi sync isync twi tw dcbt dcbst dcbf dcbi dcbz dcbz_l icbi
 cmp cmpi cmpl cmpli crand cror crxor crnand crnor creqv crandc crorc mcrf mcrxr mcrfs
 mtspr mtmsr mtsr mtsrin mtcrf mtfsf mtfsb0 mtfsb1 mtfsfi mffs fmr fneg fabs fnabs frsp
 fctiw fctiwz fadd fsub fmul fdiv fmadd fmsub fnmadd fnmsub fres frsqrte fsel fsqrt
 fcmpo fcmpu fadds fsubs fmuls fdivs fmadds fmsubs fnmadds fnmsubs eieio tlbie tlbsync
 lfs lfsx lfd lfdx psq_l psq_lx'''.split())
UPD_RA = set('''lwzu lwzux lbzu lbzux lhzu lhzux lhau lhaux stwu stwux stbu stbux sthu sthux
 lfsu lfsux lfdu lfdux stfsu stfsux stfdu stfdux psq_lu psq_lux psq_stu psq_stux'''.split())
NO_GPR |= set('''ps_mul ps_sum0 ps_madd ps_merge00 ps_muls0 ps_madds1 ps_madds0 ps_merge10
 ps_msub ps_merge11 ps_nmsub ps_sum1 ps_neg ps_muls1 ps_merge01 ps_sub ps_nmadd ps_cmpo0
 ps_cmpo1 ps_cmpu0 ps_cmpu1 ps_add ps_div ps_abs ps_nabs ps_res ps_rsqrte ps_sel'''.split())
STORES=set(m for m in NO_GPR if m.startswith('st') or m.startswith('psq_st'))
LOADS=set('''lwz lwzu lwzx lwzux lbz lbzu lbzx lbzux lhz lhzu lhzx lhzux lha lhau lhax lhaux
 lmw lwbrx lhbrx lfs lfsu lfsx lfsux lfd lfdu lfdx lfdux psq_l psq_lu psq_lx psq_lux'''.split())
MEM=STORES|LOADS
XFORM=set(m for m in MEM if m.endswith('x'))
