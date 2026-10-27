# K11: every script write of B[2..5]

Read 2026-10-27 for PLAN-GAMEPLAY-MODS K11 (milestone 3, for P7b), statically: two independent raw scans of
the 258 decompressed field scripts, each re-derived by a second reader (FINDINGS "K11"). B[n] is the script
byte variable at `0x80310A1C + n`. Nothing here is game data: script and entry names, flag numbers, offsets and
the constants stored.

Every B[2..5] write in the game, in story order. `@` is sct.py's code offset (from the script's code base). "file" is the offset in the decompressed `.sct`. A dash means that byte is not written.

| # | Script | Entry, and what runs it | Flag set just before | B[2] | B[3] | B[4] | B[5] | Where | sct.py shows it |
|---|---|---|---|---|---|---|---|---|---|
| 1 | me101b | me101ba04, CALLed only by object entry M06500 (@02144), whose condition is FLAG[3]==0 | 3 | 0 | 3 | 0 | 4 | FLAGSET @04100; SETB @04110-@04158 (file 0x4518-0x4560) | no: entry desynchronised after op 23 @04170 |
| 2 | me101c | me101ca05, CALLed by the loop | 4 | 0 | 4 | 0 | 5 | @00238; @00248-@00290 (file 0xaec-0xb34) | yes |
| 3 | me101c | loop, right after CALL me101ca06 (@03918), inside IF !FLAG[5], IF B[4]==0, IF B[5]==5 | 6 | 0 | 6 | 0 | 7 | @00194; @001a4-@001ec (file 0xa48-0xa90) | yes |
| 4 | me099e | M04000, an object entry with no caller and no IF; warps to me002a. 099e is the world map while B[6]=4, i.e. flags 1-12 [I] | field flag 1087 | - | - | 0 | 9 | @00a90; @00abc-@00ad4 (file 0x3d2c-0x3d44); op 26 and op 16 between | yes |
| 5 | me202a | me202aa12, CALLed by the loop, which then warps to me002a | 11 | 0 | 12 | 0 | 13 | @001bc; @001cc-@00214 (file 0xb74-0xbbc) | yes |
| 6 | me099a | kujira, CALLed by the loop (@00760) inside IF FLAG[1764], IF FLAG[16]; the loop then warps to me205a | field flags 1103 (@00e74), then 1105 | - | - | 1 | 1 | @00e84; @00ed8-@00ef0 (file 0x41fc-0x4214); op 186 and four op-144 messages between | yes |
| 7 | me205a | me205ab01, CALLed by the loop on arrival from 099a (IF !FLAG[50], CALL b01, WARP me033a). `--story` shows flag 50 as "099a via205a" | 50 | 1 | 1 | 1 | 3 | @00304; @00314-@0035c (file 0xfc8-0x1010) | no: after op 69 @00378 |
| 8 | me004a | me004ab05, CALLed by object M03001 | 57 | 1 | 5 | 0 | 0 | @098cc; SETB B[6]=5 @098dc; @098f4-@0993c (file 0xe400-0xe448) | no: after op 23 @09984 |
| 9 | me004a | me004ab06, CALLed by object M04010 | 58 | 1 | 6 | 0 | 0 | @0dfb4; @0dfc4-@0e00c (file 0x12ad0-0x12b18) | no: false SWITCH @0e080 |
| 10 | me099f | loop, inside IF FLAG[1767], IF !FLAG[61], IF FLAG[58] && !FLAG[62]; hook 1767 warps to me205a | field flag 1087 | - | - | 1 | 7 | @01d08; @01d18-@01d30 (file 0x5154-0x516c) | yes |
| 11 | me099f | M06010, an object entry, inside IF FLAG[58] && !FLAG[62]; after the stores it CALLs me099ab09 (@02b70), which sets 62 | field flag 1087 | - | - | 1 | 9 | @02a7c; @02b04-@02b1c (file 0x5f40-0x5f58); six op 99 between (each with a count of 1 and one expression) | yes |
| 12 | me033a | me033ab08, CALLed by the loop | 61 | 1 | 8 | 0 | 0 | @0f6ec; @0f6fc-@0f744 (file 0x15310-0x15358) | yes |
| 13 | me008b | me008bd02, CALLed by the loop | 151 | 3 | 2 | - | - | @061e4; @061f4-@0620c (file 0x7bb4-0x7bcc) | yes |
| 14 | me033a | me033ad11, CALLed by the loop (@01e10) inside IF sys[15]==40000, IF FLAG[159] && !FLAG[160] | 160 | 3 | 11 | 3 | 12 | @1a734; @1a744-@1a78c (file 0x20358-0x203a0) | no: after op 69 @1a7a8 |
| 15 | me241a | me241ae05, CALLed by the loop on arrival from 099a. `--story` shows flag 204 as "099a via241a" | 204 | 4 | 5 | - | - | @002e8; @002f8-@00310 (file 0x118c-0x11a4) | yes |
| 16 | me018a | me018ag22, CALLed by object M03006 | 321 | 6 | 22 | - | - | @0577c; @0578c-@057a4 (file 0x74f8-0x7510) | yes |

**Totals [V].** 50 stores in 16 groups in 12 scripts. By byte: B[2] 12, B[3] 12, B[4] 13, B[5] 13.
- Every store is op 5 storing a constant: the expression is `B[n] k =`.
- sct.py alone lists 30 of them, in 9 scripts. It drops rows 1, 7, 8, 9 and 14: each of those entries' whole listing becomes a "desynchronised" line, which hides stores that sit before the point where sync was lost.
- The last story flag followed by a write is 321. The highest flag number that comes literally just before a write is field flag 1105 (row 6), whose story gate is flag 16.

**The only script reads [V].** The 4 other aligned operand hits are me101c's loop IFs: B[4]==0 @000c0, B[5]==4 @000dc, B[4]==0 @00144, B[5]==5 @00160. Those IFs are the only script reads of B[2..5]. No script reads B[2] or B[3].

**What the values say [V for the bytes; I for the meaning].**
- B[2] = floor(flag/50) for all 12 B[2] writes.
- B[3] is not flag mod 50; that holds only at flags 3, 4 and 6.
- (B[2],B[3]) is the writing entry's part letter and number in 10 of the 12. Examples: b05 gives (1,5), d11 gives (3,11), g22 gives (6,22), and me101c's loop counts as a06. The two exceptions are me101ba04 (0,3) and me101ca05 (0,4).
- (B[4],B[5]) names the scene expected next. Rows 8, 9 and 12 write (0,0). Of the 10 nonzero pairs, 8 name an existing entry that the writer then calls or warps to:
  - a07: me028ea07
  - a09: me002aa09
  - a13: me002aa13
  - b01: me205ab01
  - b03: me033ab03
  - b07: me205ab07
  - b09: me099ab09
  - d12: me220ad12, reached in two hops. d11 returns to me033a's loop, whose then-branch reloads me033a with sys[15]=40000 (op 214 @01e28; fn_80207428 is a WARP plus fn_801F7B04(40000)). The WARP to me220a @01e48 is in that IF's else branch [I: the runtime order].
- The other two pairs are part A's, one step behind: me101c's loop plays a05 only at (0,4) and a06 only at (0,5).
- No B[2..3] write falls in parts C, F or H-L.

**How it was established.**
- Raw scan, done twice by independent scanners (researcher: scratchpad\k11\scan.py; skeptic: scratchpad\k11v\scan.py, groups.py). Each AKLZ-decompressed script was searched for 0x10000002-5 at every byte offset, in both byte orders. Only the 54 big-endian word-aligned hits can be operands; 50 of them follow word 5.
- Handler-rule scan (mine: scratchpad\k11w\aliasscan.py). The index rule is fn_801F5EB4's: addis -0x1000 then extsh, at 0x801F5EEC/F0, so the index is the operand's low halfword, sign-extended. Over all 258 scripts, every aligned op 5 indexing 2..5 is one of the same 50 exact tokens.
- Each group was decoded forward from its constant FLAGSET (sct.disassemble). The enclosing IFs and callers come from sct.py's listings and the skeptic's decoder.
- Scope: extracted/field holds 258 .sct files (257 meNNNx plus me035ag), byte-identical to those in extracted/disc.iso. No .sct exists outside field/.

Scratchpad root: C:\Users\bmfre\AppData\Local\Temp\claude\c--Users-bmfre-Documents-Github-SOA\a8e3d58f-06a6-4356-a09b-6810f71ace7e\scratchpad
