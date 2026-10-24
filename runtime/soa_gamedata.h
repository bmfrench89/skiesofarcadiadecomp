/* Generated from config/gamedata.txt by tools/gamedata.py; do not edit.
 *
 * The game's data by name (T9, docs/specs/game-names.md), each address proved
 * against the instruction in the DOL that reaches it. Accessors go through the
 * mod API's big-endian reads and writes and return what they do: 1, or 0 when
 * the address is refused. A name behind a pointer follows the pointer first.
 * Include after soa_mod.h. */
#ifndef SOA_GAMEDATA_H
#define SOA_GAMEDATA_H

#define SOA_SCENE 0x803475CCu /* u32 */
#define SOA_FIELD_STATE 0x80311AECu /* u32 */
#define SOA_MAP_NUMBER 0x80311AC0u /* u32 */
#define SOA_MAP_PICKER 0x80311AC4u /* u32 */
#define SOA_MAP_LETTER 0x80311AC8u /* u8 */
#define SOA_WARP_SCRIPT 0x80305CF0u /* bytes[32] */
#define SOA_SHIP_BATTLE_RETURN_SCRIPT 0x802E5E68u /* bytes[11] */
#define SOA_SHIP_BATTLE_PENDING 0x803472E4u /* u32 */
#define SOA_SKY_MODE 0x80347464u /* u32 */
#define SOA_MESSAGE_TASK 0x80346E4Cu /* ptr */
#define SOA_MESSAGE_STATE 0x80346E64u /* s16 */
#define SOA_ENCOUNTER_TABLE 0x803474BCu /* ptr:ect_zone[8] */
#define SOA_ENCOUNTER_ENEMIES 0x803474B8u /* ptr */
#define SOA_ENCOUNTER_STEPS 0x80346D28u /* u32 */
#define SOA_ENCOUNTER_ZONE 0x8034740Eu /* u16 */
#define SOA_ENCOUNTER_ZONE_SKY 0x80346CD4u /* u32 */
#define SOA_ENCOUNTER_MULTIPLIER 0x8030B7ADu /* s8 */
#define SOA_BATTLE_REQUEST_STAGE 0x803473C8u /* u32 */
#define SOA_BATTLE_REQUEST_ID 0x803473CCu /* u32 */
#define SOA_BATTLE_REQUEST_MODE 0x803473D0u /* u32 */
#define SOA_BATTLE_REQUEST_FORCED 0x803473D4u /* u32 */
#define SOA_BATTLE_REQUEST_TRANSITION 0x803473D8u /* u32 */
#define SOA_STORY_FLAGS 0x80310B3Cu /* u32[854] */
#define SOA_STORY_VARS 0x80310A1Cu /* u8[288] */
#define SOA_PARTY_MEMBERS 0x80310BBCu /* u32 */
#define SOA_PARTY_CHARACTER 0x8030B7F4u /* character[6] */
#define SOA_PARTY_ACTIVE 0x8030BB1Cu /* u8[4] */
#define SOA_PARTY_COUNT 0x8030B7A8u /* u8 */
#define SOA_PARTY_GOLD 0x8030BB40u /* s32 */
#define SOA_INVENTORY_WEAPONS 0x8030BB48u /* slot[80] */
#define SOA_INVENTORY_ARMOR 0x8030BC88u /* slot[80] */
#define SOA_INVENTORY_ACCESSORIES 0x8030BDC8u /* slot[80] */
#define SOA_INVENTORY_ITEMS 0x8030BF08u /* slot[80] */
#define SOA_INVENTORY_KEY_ITEMS 0x8030C048u /* slot[80] */
#define SOA_SYS15 0x8030E420u /* u32 */
#define SOA_SCRIPT_ENTRY_BUSY 0x8030E714u /* u32 */
#define SOA_SAVE_VARIANT 0x803473B0u /* u32 */
#define SOA_SAVE_REQUEST 0x803473B4u /* u32 */
#define SOA_SAVE_RESULT 0x803473C4u /* u32 */
#define SOA_BATTLE_ACTOR_IDS 0x80309DCCu /* u16[12] */
#define SOA_BATTLE_ACTORS 0x80309DE4u /* ptr[12] */
#define SOA_BATTLE_CONTEXT 0x80347390u /* ptr:battle_context */
#define SOA_BATTLE_FORMATION 0x80347384u /* ptr */
#define SOA_BATTLE_COMMANDS 0x80309174u /* bytes[384] */
#define SOA_BATTLE_RESULTS 0x80309730u /* bytes[192] */
#define SOA_BATTLE_TURN_ORDER 0x803092F4u /* s8[12] */
#define SOA_BATTLE_PHASE 0x8034733Cu /* u32 */
#define SOA_BATTLE_CHOOSING 0x80347330u /* u32 */
#define SOA_BATTLE_ROUND_STATE 0x80347338u /* u32 */
#define SOA_BATTLE_ROUND 0x80347340u /* u8 */
#define SOA_BATTLE_TASKS 0x80309700u /* ptr[12] */
#define SOA_BATTLE_OVERRIDE_INITIATIVE 0x8030B7AAu /* s8 */
#define SOA_BATTLE_OVERRIDE_ESCAPE_PARTY 0x8030B7ABu /* s8 */
#define SOA_BATTLE_OVERRIDE_ESCAPE_ENEMY 0x8030B7ACu /* s8 */
#define SOA_BATTLE_SP_MAX 0x8030B7A4u /* s16 */
#define SOA_BATTLE_SP_START 0x8030B7A6u /* s16 */
#define SOA_RNG_SEED 0x803469A8u /* u32 */
#define SOA_SHIP_BATTLE_STATE 0x8034727Cu /* u32 */
#define SOA_SHIP_BATTLE_OUTCOME 0x80347278u /* u32 */
#define SOA_SHIP_BATTLE_RESULTS_NEXT 0x80347280u /* u32 */
#define SOA_FRAME_START_FIELDS 0x8034768Cu /* u32 */
#define SOA_FRAME_GAME 0x803475C0u /* u32 */
#define SOA_VI_RETRACE_COUNT 0x80347A64u /* u32 */
#define SOA_SCRIPT_OPCODES 0x802F7940u /* opcode[266] */
#define SOA_TABLES_WEAPONS 0x802C5790u /* bytes[2560] */
#define SOA_TABLES_ARMOR 0x802C6190u /* bytes[3200] */
#define SOA_TABLES_ACCESSORIES 0x802C6E10u /* bytes[3200] */
#define SOA_TABLES_ITEMS 0x802C7C34u /* bytes[2880] */
#define SOA_TABLES_KEY_ITEMS 0x802C8774u /* bytes[1760] */
#define SOA_TABLES_SHIPS 0x802D6934u /* bytes[5400] */
#define SOA_TABLES_CHARACTER_TEMPLATES 0x802C4860u /* bytes[912] */

static inline int soa_scene_get(const SoaModApi* api, uint32_t* out)
{
    return api->read32(0x803475CCu, out);
}
static inline int soa_scene_set(const SoaModApi* api, uint32_t v)
{
    return api->write32(0x803475CCu, v);
}
static inline int soa_field_state_get(const SoaModApi* api, uint32_t* out)
{
    return api->read32(0x80311AECu, out);
}
static inline int soa_field_state_set(const SoaModApi* api, uint32_t v)
{
    return api->write32(0x80311AECu, v);
}
static inline int soa_map_number_get(const SoaModApi* api, uint32_t* out)
{
    return api->read32(0x80311AC0u, out);
}
static inline int soa_map_number_set(const SoaModApi* api, uint32_t v)
{
    return api->write32(0x80311AC0u, v);
}
static inline int soa_map_picker_get(const SoaModApi* api, uint32_t* out)
{
    return api->read32(0x80311AC4u, out);
}
static inline int soa_map_picker_set(const SoaModApi* api, uint32_t v)
{
    return api->write32(0x80311AC4u, v);
}
static inline int soa_map_letter_get(const SoaModApi* api, uint8_t* out)
{
    return api->read8(0x80311AC8u, out);
}
static inline int soa_map_letter_set(const SoaModApi* api, uint8_t v)
{
    return api->write8(0x80311AC8u, v);
}
static inline int soa_ship_battle_pending_get(const SoaModApi* api, uint32_t* out)
{
    return api->read32(0x803472E4u, out);
}
static inline int soa_ship_battle_pending_set(const SoaModApi* api, uint32_t v)
{
    return api->write32(0x803472E4u, v);
}
static inline int soa_sky_mode_get(const SoaModApi* api, uint32_t* out)
{
    return api->read32(0x80347464u, out);
}
static inline int soa_sky_mode_set(const SoaModApi* api, uint32_t v)
{
    return api->write32(0x80347464u, v);
}
static inline int soa_message_task_get(const SoaModApi* api, uint32_t* out)
{
    return api->read32(0x80346E4Cu, out);
}
static inline int soa_message_task_set(const SoaModApi* api, uint32_t v)
{
    return api->write32(0x80346E4Cu, v);
}
static inline int soa_message_state_get(const SoaModApi* api, int16_t* out)
{
    uint16_t v;
    if (!api->read16(0x80346E64u, &v)) return 0;
    *out = (int16_t)v;
    return 1;
}
static inline int soa_message_state_set(const SoaModApi* api, int16_t v)
{
    return api->write16(0x80346E64u, (uint16_t)v);
}
static inline int soa_encounter_table_get(const SoaModApi* api, uint32_t* out)
{
    return api->read32(0x803474BCu, out);
}
static inline int soa_encounter_table_set(const SoaModApi* api, uint32_t v)
{
    return api->write32(0x803474BCu, v);
}
static inline int soa_encounter_table_rate_get(const SoaModApi* api, uint32_t i, uint16_t* out)
{
    uint32_t p;
    if (!api->read32(0x803474BCu, &p)) return 0;
    return api->read16(p + i * 132u + 2u, out);
}
static inline int soa_encounter_table_rate_set(const SoaModApi* api, uint32_t i, uint16_t v)
{
    uint32_t p;
    if (!api->read32(0x803474BCu, &p)) return 0;
    return api->write16(p + i * 132u + 2u, v);
}
static inline int soa_encounter_enemies_get(const SoaModApi* api, uint32_t* out)
{
    return api->read32(0x803474B8u, out);
}
static inline int soa_encounter_enemies_set(const SoaModApi* api, uint32_t v)
{
    return api->write32(0x803474B8u, v);
}
static inline int soa_encounter_steps_get(const SoaModApi* api, uint32_t* out)
{
    return api->read32(0x80346D28u, out);
}
static inline int soa_encounter_steps_set(const SoaModApi* api, uint32_t v)
{
    return api->write32(0x80346D28u, v);
}
static inline int soa_encounter_zone_get(const SoaModApi* api, uint16_t* out)
{
    return api->read16(0x8034740Eu, out);
}
static inline int soa_encounter_zone_set(const SoaModApi* api, uint16_t v)
{
    return api->write16(0x8034740Eu, v);
}
static inline int soa_encounter_zone_sky_get(const SoaModApi* api, uint32_t* out)
{
    return api->read32(0x80346CD4u, out);
}
static inline int soa_encounter_zone_sky_set(const SoaModApi* api, uint32_t v)
{
    return api->write32(0x80346CD4u, v);
}
static inline int soa_encounter_multiplier_get(const SoaModApi* api, int8_t* out)
{
    uint8_t v;
    if (!api->read8(0x8030B7ADu, &v)) return 0;
    *out = (int8_t)v;
    return 1;
}
static inline int soa_encounter_multiplier_set(const SoaModApi* api, int8_t v)
{
    return api->write8(0x8030B7ADu, (uint8_t)v);
}
static inline int soa_battle_request_stage_get(const SoaModApi* api, uint32_t* out)
{
    return api->read32(0x803473C8u, out);
}
static inline int soa_battle_request_stage_set(const SoaModApi* api, uint32_t v)
{
    return api->write32(0x803473C8u, v);
}
static inline int soa_battle_request_id_get(const SoaModApi* api, uint32_t* out)
{
    return api->read32(0x803473CCu, out);
}
static inline int soa_battle_request_id_set(const SoaModApi* api, uint32_t v)
{
    return api->write32(0x803473CCu, v);
}
static inline int soa_battle_request_mode_get(const SoaModApi* api, uint32_t* out)
{
    return api->read32(0x803473D0u, out);
}
static inline int soa_battle_request_mode_set(const SoaModApi* api, uint32_t v)
{
    return api->write32(0x803473D0u, v);
}
static inline int soa_battle_request_forced_get(const SoaModApi* api, uint32_t* out)
{
    return api->read32(0x803473D4u, out);
}
static inline int soa_battle_request_forced_set(const SoaModApi* api, uint32_t v)
{
    return api->write32(0x803473D4u, v);
}
static inline int soa_battle_request_transition_get(const SoaModApi* api, uint32_t* out)
{
    return api->read32(0x803473D8u, out);
}
static inline int soa_battle_request_transition_set(const SoaModApi* api, uint32_t v)
{
    return api->write32(0x803473D8u, v);
}
static inline int soa_story_flags_get(const SoaModApi* api, uint32_t i, uint32_t* out)
{
    return api->read32(0x80310B3Cu + i * 4u, out);
}
static inline int soa_story_flags_set(const SoaModApi* api, uint32_t i, uint32_t v)
{
    return api->write32(0x80310B3Cu + i * 4u, v);
}
static inline int soa_story_vars_get(const SoaModApi* api, uint32_t i, uint8_t* out)
{
    return api->read8(0x80310A1Cu + i * 1u, out);
}
static inline int soa_story_vars_set(const SoaModApi* api, uint32_t i, uint8_t v)
{
    return api->write8(0x80310A1Cu + i * 1u, v);
}
static inline int soa_party_members_get(const SoaModApi* api, uint32_t* out)
{
    return api->read32(0x80310BBCu, out);
}
static inline int soa_party_members_set(const SoaModApi* api, uint32_t v)
{
    return api->write32(0x80310BBCu, v);
}
static inline int soa_party_character_level_get(const SoaModApi* api, uint32_t i, uint8_t* out)
{
    return api->read8(0x8030B7F4u + i * 92u + 11u, out);
}
static inline int soa_party_character_level_set(const SoaModApi* api, uint32_t i, uint8_t v)
{
    return api->write8(0x8030B7F4u + i * 92u + 11u, v);
}
static inline int soa_party_character_mp_get(const SoaModApi* api, uint32_t i, uint8_t* out)
{
    return api->read8(0x8030B7F4u + i * 92u + 13u, out);
}
static inline int soa_party_character_mp_set(const SoaModApi* api, uint32_t i, uint8_t v)
{
    return api->write8(0x8030B7F4u + i * 92u + 13u, v);
}
static inline int soa_party_character_mp_max_get(const SoaModApi* api, uint32_t i, uint8_t* out)
{
    return api->read8(0x8030B7F4u + i * 92u + 14u, out);
}
static inline int soa_party_character_mp_max_set(const SoaModApi* api, uint32_t i, uint8_t v)
{
    return api->write8(0x8030B7F4u + i * 92u + 14u, v);
}
static inline int soa_party_character_weapon_get(const SoaModApi* api, uint32_t i, int16_t* out)
{
    uint16_t v;
    if (!api->read16(0x8030B7F4u + i * 92u + 16u, &v)) return 0;
    *out = (int16_t)v;
    return 1;
}
static inline int soa_party_character_weapon_set(const SoaModApi* api, uint32_t i, int16_t v)
{
    return api->write16(0x8030B7F4u + i * 92u + 16u, (uint16_t)v);
}
static inline int soa_party_character_armor_get(const SoaModApi* api, uint32_t i, int16_t* out)
{
    uint16_t v;
    if (!api->read16(0x8030B7F4u + i * 92u + 18u, &v)) return 0;
    *out = (int16_t)v;
    return 1;
}
static inline int soa_party_character_armor_set(const SoaModApi* api, uint32_t i, int16_t v)
{
    return api->write16(0x8030B7F4u + i * 92u + 18u, (uint16_t)v);
}
static inline int soa_party_character_accessory_get(const SoaModApi* api, uint32_t i, int16_t* out)
{
    uint16_t v;
    if (!api->read16(0x8030B7F4u + i * 92u + 20u, &v)) return 0;
    *out = (int16_t)v;
    return 1;
}
static inline int soa_party_character_accessory_set(const SoaModApi* api, uint32_t i, int16_t v)
{
    return api->write16(0x8030B7F4u + i * 92u + 20u, (uint16_t)v);
}
static inline int soa_party_character_hp_get(const SoaModApi* api, uint32_t i, int16_t* out)
{
    uint16_t v;
    if (!api->read16(0x8030B7F4u + i * 92u + 24u, &v)) return 0;
    *out = (int16_t)v;
    return 1;
}
static inline int soa_party_character_hp_set(const SoaModApi* api, uint32_t i, int16_t v)
{
    return api->write16(0x8030B7F4u + i * 92u + 24u, (uint16_t)v);
}
static inline int soa_party_character_hp_max_get(const SoaModApi* api, uint32_t i, int16_t* out)
{
    uint16_t v;
    if (!api->read16(0x8030B7F4u + i * 92u + 26u, &v)) return 0;
    *out = (int16_t)v;
    return 1;
}
static inline int soa_party_character_hp_max_set(const SoaModApi* api, uint32_t i, int16_t v)
{
    return api->write16(0x8030B7F4u + i * 92u + 26u, (uint16_t)v);
}
static inline int soa_party_character_exp_get(const SoaModApi* api, uint32_t i, int32_t* out)
{
    uint32_t v;
    if (!api->read32(0x8030B7F4u + i * 92u + 36u, &v)) return 0;
    *out = (int32_t)v;
    return 1;
}
static inline int soa_party_character_exp_set(const SoaModApi* api, uint32_t i, int32_t v)
{
    return api->write32(0x8030B7F4u + i * 92u + 36u, (uint32_t)v);
}
static inline int soa_party_active_get(const SoaModApi* api, uint32_t i, uint8_t* out)
{
    return api->read8(0x8030BB1Cu + i * 1u, out);
}
static inline int soa_party_active_set(const SoaModApi* api, uint32_t i, uint8_t v)
{
    return api->write8(0x8030BB1Cu + i * 1u, v);
}
static inline int soa_party_count_get(const SoaModApi* api, uint8_t* out)
{
    return api->read8(0x8030B7A8u, out);
}
static inline int soa_party_count_set(const SoaModApi* api, uint8_t v)
{
    return api->write8(0x8030B7A8u, v);
}
static inline int soa_party_gold_get(const SoaModApi* api, int32_t* out)
{
    uint32_t v;
    if (!api->read32(0x8030BB40u, &v)) return 0;
    *out = (int32_t)v;
    return 1;
}
static inline int soa_party_gold_set(const SoaModApi* api, int32_t v)
{
    return api->write32(0x8030BB40u, (uint32_t)v);
}
static inline int soa_inventory_weapons_id_get(const SoaModApi* api, uint32_t i, int16_t* out)
{
    uint16_t v;
    if (!api->read16(0x8030BB48u + i * 4u, &v)) return 0;
    *out = (int16_t)v;
    return 1;
}
static inline int soa_inventory_weapons_id_set(const SoaModApi* api, uint32_t i, int16_t v)
{
    return api->write16(0x8030BB48u + i * 4u, (uint16_t)v);
}
static inline int soa_inventory_weapons_count_get(const SoaModApi* api, uint32_t i, uint8_t* out)
{
    return api->read8(0x8030BB48u + i * 4u + 2u, out);
}
static inline int soa_inventory_weapons_count_set(const SoaModApi* api, uint32_t i, uint8_t v)
{
    return api->write8(0x8030BB48u + i * 4u + 2u, v);
}
static inline int soa_inventory_armor_id_get(const SoaModApi* api, uint32_t i, int16_t* out)
{
    uint16_t v;
    if (!api->read16(0x8030BC88u + i * 4u, &v)) return 0;
    *out = (int16_t)v;
    return 1;
}
static inline int soa_inventory_armor_id_set(const SoaModApi* api, uint32_t i, int16_t v)
{
    return api->write16(0x8030BC88u + i * 4u, (uint16_t)v);
}
static inline int soa_inventory_armor_count_get(const SoaModApi* api, uint32_t i, uint8_t* out)
{
    return api->read8(0x8030BC88u + i * 4u + 2u, out);
}
static inline int soa_inventory_armor_count_set(const SoaModApi* api, uint32_t i, uint8_t v)
{
    return api->write8(0x8030BC88u + i * 4u + 2u, v);
}
static inline int soa_inventory_accessories_id_get(const SoaModApi* api, uint32_t i, int16_t* out)
{
    uint16_t v;
    if (!api->read16(0x8030BDC8u + i * 4u, &v)) return 0;
    *out = (int16_t)v;
    return 1;
}
static inline int soa_inventory_accessories_id_set(const SoaModApi* api, uint32_t i, int16_t v)
{
    return api->write16(0x8030BDC8u + i * 4u, (uint16_t)v);
}
static inline int soa_inventory_accessories_count_get(const SoaModApi* api, uint32_t i, uint8_t* out)
{
    return api->read8(0x8030BDC8u + i * 4u + 2u, out);
}
static inline int soa_inventory_accessories_count_set(const SoaModApi* api, uint32_t i, uint8_t v)
{
    return api->write8(0x8030BDC8u + i * 4u + 2u, v);
}
static inline int soa_inventory_items_id_get(const SoaModApi* api, uint32_t i, int16_t* out)
{
    uint16_t v;
    if (!api->read16(0x8030BF08u + i * 4u, &v)) return 0;
    *out = (int16_t)v;
    return 1;
}
static inline int soa_inventory_items_id_set(const SoaModApi* api, uint32_t i, int16_t v)
{
    return api->write16(0x8030BF08u + i * 4u, (uint16_t)v);
}
static inline int soa_inventory_items_count_get(const SoaModApi* api, uint32_t i, uint8_t* out)
{
    return api->read8(0x8030BF08u + i * 4u + 2u, out);
}
static inline int soa_inventory_items_count_set(const SoaModApi* api, uint32_t i, uint8_t v)
{
    return api->write8(0x8030BF08u + i * 4u + 2u, v);
}
static inline int soa_inventory_key_items_id_get(const SoaModApi* api, uint32_t i, int16_t* out)
{
    uint16_t v;
    if (!api->read16(0x8030C048u + i * 4u, &v)) return 0;
    *out = (int16_t)v;
    return 1;
}
static inline int soa_inventory_key_items_id_set(const SoaModApi* api, uint32_t i, int16_t v)
{
    return api->write16(0x8030C048u + i * 4u, (uint16_t)v);
}
static inline int soa_inventory_key_items_count_get(const SoaModApi* api, uint32_t i, uint8_t* out)
{
    return api->read8(0x8030C048u + i * 4u + 2u, out);
}
static inline int soa_inventory_key_items_count_set(const SoaModApi* api, uint32_t i, uint8_t v)
{
    return api->write8(0x8030C048u + i * 4u + 2u, v);
}
static inline int soa_sys15_get(const SoaModApi* api, uint32_t* out)
{
    return api->read32(0x8030E420u, out);
}
static inline int soa_sys15_set(const SoaModApi* api, uint32_t v)
{
    return api->write32(0x8030E420u, v);
}
static inline int soa_script_entry_busy_get(const SoaModApi* api, uint32_t* out)
{
    return api->read32(0x8030E714u, out);
}
static inline int soa_script_entry_busy_set(const SoaModApi* api, uint32_t v)
{
    return api->write32(0x8030E714u, v);
}
static inline int soa_save_variant_get(const SoaModApi* api, uint32_t* out)
{
    return api->read32(0x803473B0u, out);
}
static inline int soa_save_variant_set(const SoaModApi* api, uint32_t v)
{
    return api->write32(0x803473B0u, v);
}
static inline int soa_save_request_get(const SoaModApi* api, uint32_t* out)
{
    return api->read32(0x803473B4u, out);
}
static inline int soa_save_request_set(const SoaModApi* api, uint32_t v)
{
    return api->write32(0x803473B4u, v);
}
static inline int soa_save_result_get(const SoaModApi* api, uint32_t* out)
{
    return api->read32(0x803473C4u, out);
}
static inline int soa_save_result_set(const SoaModApi* api, uint32_t v)
{
    return api->write32(0x803473C4u, v);
}
static inline int soa_battle_actor_ids_get(const SoaModApi* api, uint32_t i, uint16_t* out)
{
    return api->read16(0x80309DCCu + i * 2u, out);
}
static inline int soa_battle_actor_ids_set(const SoaModApi* api, uint32_t i, uint16_t v)
{
    return api->write16(0x80309DCCu + i * 2u, v);
}
static inline int soa_battle_actors_get(const SoaModApi* api, uint32_t i, uint32_t* out)
{
    return api->read32(0x80309DE4u + i * 4u, out);
}
static inline int soa_battle_actors_set(const SoaModApi* api, uint32_t i, uint32_t v)
{
    return api->write32(0x80309DE4u + i * 4u, v);
}
static inline int soa_battle_context_get(const SoaModApi* api, uint32_t* out)
{
    return api->read32(0x80347390u, out);
}
static inline int soa_battle_context_set(const SoaModApi* api, uint32_t v)
{
    return api->write32(0x80347390u, v);
}
static inline int soa_battle_context_initiative_get(const SoaModApi* api, uint8_t* out)
{
    uint32_t p;
    if (!api->read32(0x80347390u, &p)) return 0;
    return api->read8(p + 0u, out);
}
static inline int soa_battle_context_initiative_set(const SoaModApi* api, uint8_t v)
{
    uint32_t p;
    if (!api->read32(0x80347390u, &p)) return 0;
    return api->write8(p + 0u, v);
}
static inline int soa_battle_context_magic_exp_get(const SoaModApi* api, uint8_t* out)
{
    uint32_t p;
    if (!api->read32(0x80347390u, &p)) return 0;
    return api->read8(p + 1u, out);
}
static inline int soa_battle_context_magic_exp_set(const SoaModApi* api, uint8_t v)
{
    uint32_t p;
    if (!api->read32(0x80347390u, &p)) return 0;
    return api->write8(p + 1u, v);
}
static inline int soa_battle_context_escape_party_get(const SoaModApi* api, int8_t* out)
{
    uint32_t p;
    uint8_t v;
    if (!api->read32(0x80347390u, &p)) return 0;
    if (!api->read8(p + 2u, &v)) return 0;
    *out = (int8_t)v;
    return 1;
}
static inline int soa_battle_context_escape_party_set(const SoaModApi* api, int8_t v)
{
    uint32_t p;
    if (!api->read32(0x80347390u, &p)) return 0;
    return api->write8(p + 2u, (uint8_t)v);
}
static inline int soa_battle_context_escape_enemy_get(const SoaModApi* api, int8_t* out)
{
    uint32_t p;
    uint8_t v;
    if (!api->read32(0x80347390u, &p)) return 0;
    if (!api->read8(p + 3u, &v)) return 0;
    *out = (int8_t)v;
    return 1;
}
static inline int soa_battle_context_escape_enemy_set(const SoaModApi* api, int8_t v)
{
    uint32_t p;
    if (!api->read32(0x80347390u, &p)) return 0;
    return api->write8(p + 3u, (uint8_t)v);
}
static inline int soa_battle_context_defeat_get(const SoaModApi* api, uint8_t* out)
{
    uint32_t p;
    if (!api->read32(0x80347390u, &p)) return 0;
    return api->read8(p + 4u, out);
}
static inline int soa_battle_context_defeat_set(const SoaModApi* api, uint8_t v)
{
    uint32_t p;
    if (!api->read32(0x80347390u, &p)) return 0;
    return api->write8(p + 4u, v);
}
static inline int soa_battle_context_escape_get(const SoaModApi* api, uint8_t* out)
{
    uint32_t p;
    if (!api->read32(0x80347390u, &p)) return 0;
    return api->read8(p + 5u, out);
}
static inline int soa_battle_context_escape_set(const SoaModApi* api, uint8_t v)
{
    uint32_t p;
    if (!api->read32(0x80347390u, &p)) return 0;
    return api->write8(p + 5u, v);
}
static inline int soa_battle_context_sp_max_get(const SoaModApi* api, int16_t* out)
{
    uint32_t p;
    uint16_t v;
    if (!api->read32(0x80347390u, &p)) return 0;
    if (!api->read16(p + 6u, &v)) return 0;
    *out = (int16_t)v;
    return 1;
}
static inline int soa_battle_context_sp_max_set(const SoaModApi* api, int16_t v)
{
    uint32_t p;
    if (!api->read32(0x80347390u, &p)) return 0;
    return api->write16(p + 6u, (uint16_t)v);
}
static inline int soa_battle_context_sp_get(const SoaModApi* api, int16_t* out)
{
    uint32_t p;
    uint16_t v;
    if (!api->read32(0x80347390u, &p)) return 0;
    if (!api->read16(p + 8u, &v)) return 0;
    *out = (int16_t)v;
    return 1;
}
static inline int soa_battle_context_sp_set(const SoaModApi* api, int16_t v)
{
    uint32_t p;
    if (!api->read32(0x80347390u, &p)) return 0;
    return api->write16(p + 8u, (uint16_t)v);
}
static inline int soa_battle_context_sp_free_get(const SoaModApi* api, int16_t* out)
{
    uint32_t p;
    uint16_t v;
    if (!api->read32(0x80347390u, &p)) return 0;
    if (!api->read16(p + 10u, &v)) return 0;
    *out = (int16_t)v;
    return 1;
}
static inline int soa_battle_context_sp_free_set(const SoaModApi* api, int16_t v)
{
    uint32_t p;
    if (!api->read32(0x80347390u, &p)) return 0;
    return api->write16(p + 10u, (uint16_t)v);
}
static inline int soa_battle_context_kills_get(const SoaModApi* api, int16_t* out)
{
    uint32_t p;
    uint16_t v;
    if (!api->read32(0x80347390u, &p)) return 0;
    if (!api->read16(p + 12u, &v)) return 0;
    *out = (int16_t)v;
    return 1;
}
static inline int soa_battle_context_kills_set(const SoaModApi* api, int16_t v)
{
    uint32_t p;
    if (!api->read32(0x80347390u, &p)) return 0;
    return api->write16(p + 12u, (uint16_t)v);
}
static inline int soa_battle_context_exp_get(const SoaModApi* api, int32_t* out)
{
    uint32_t p;
    uint32_t v;
    if (!api->read32(0x80347390u, &p)) return 0;
    if (!api->read32(p + 48u, &v)) return 0;
    *out = (int32_t)v;
    return 1;
}
static inline int soa_battle_context_exp_set(const SoaModApi* api, int32_t v)
{
    uint32_t p;
    if (!api->read32(0x80347390u, &p)) return 0;
    return api->write32(p + 48u, (uint32_t)v);
}
static inline int soa_battle_context_gold_get(const SoaModApi* api, int32_t* out)
{
    uint32_t p;
    uint32_t v;
    if (!api->read32(0x80347390u, &p)) return 0;
    if (!api->read32(p + 52u, &v)) return 0;
    *out = (int32_t)v;
    return 1;
}
static inline int soa_battle_context_gold_set(const SoaModApi* api, int32_t v)
{
    uint32_t p;
    if (!api->read32(0x80347390u, &p)) return 0;
    return api->write32(p + 52u, (uint32_t)v);
}
static inline int soa_battle_formation_get(const SoaModApi* api, uint32_t* out)
{
    return api->read32(0x80347384u, out);
}
static inline int soa_battle_formation_set(const SoaModApi* api, uint32_t v)
{
    return api->write32(0x80347384u, v);
}
static inline int soa_battle_turn_order_get(const SoaModApi* api, uint32_t i, int8_t* out)
{
    uint8_t v;
    if (!api->read8(0x803092F4u + i * 1u, &v)) return 0;
    *out = (int8_t)v;
    return 1;
}
static inline int soa_battle_turn_order_set(const SoaModApi* api, uint32_t i, int8_t v)
{
    return api->write8(0x803092F4u + i * 1u, (uint8_t)v);
}
static inline int soa_battle_phase_get(const SoaModApi* api, uint32_t* out)
{
    return api->read32(0x8034733Cu, out);
}
static inline int soa_battle_phase_set(const SoaModApi* api, uint32_t v)
{
    return api->write32(0x8034733Cu, v);
}
static inline int soa_battle_choosing_get(const SoaModApi* api, uint32_t* out)
{
    return api->read32(0x80347330u, out);
}
static inline int soa_battle_choosing_set(const SoaModApi* api, uint32_t v)
{
    return api->write32(0x80347330u, v);
}
static inline int soa_battle_round_state_get(const SoaModApi* api, uint32_t* out)
{
    return api->read32(0x80347338u, out);
}
static inline int soa_battle_round_state_set(const SoaModApi* api, uint32_t v)
{
    return api->write32(0x80347338u, v);
}
static inline int soa_battle_round_get(const SoaModApi* api, uint8_t* out)
{
    return api->read8(0x80347340u, out);
}
static inline int soa_battle_round_set(const SoaModApi* api, uint8_t v)
{
    return api->write8(0x80347340u, v);
}
static inline int soa_battle_tasks_get(const SoaModApi* api, uint32_t i, uint32_t* out)
{
    return api->read32(0x80309700u + i * 4u, out);
}
static inline int soa_battle_tasks_set(const SoaModApi* api, uint32_t i, uint32_t v)
{
    return api->write32(0x80309700u + i * 4u, v);
}
static inline int soa_battle_override_initiative_get(const SoaModApi* api, int8_t* out)
{
    uint8_t v;
    if (!api->read8(0x8030B7AAu, &v)) return 0;
    *out = (int8_t)v;
    return 1;
}
static inline int soa_battle_override_initiative_set(const SoaModApi* api, int8_t v)
{
    return api->write8(0x8030B7AAu, (uint8_t)v);
}
static inline int soa_battle_override_escape_party_get(const SoaModApi* api, int8_t* out)
{
    uint8_t v;
    if (!api->read8(0x8030B7ABu, &v)) return 0;
    *out = (int8_t)v;
    return 1;
}
static inline int soa_battle_override_escape_party_set(const SoaModApi* api, int8_t v)
{
    return api->write8(0x8030B7ABu, (uint8_t)v);
}
static inline int soa_battle_override_escape_enemy_get(const SoaModApi* api, int8_t* out)
{
    uint8_t v;
    if (!api->read8(0x8030B7ACu, &v)) return 0;
    *out = (int8_t)v;
    return 1;
}
static inline int soa_battle_override_escape_enemy_set(const SoaModApi* api, int8_t v)
{
    return api->write8(0x8030B7ACu, (uint8_t)v);
}
static inline int soa_battle_sp_max_get(const SoaModApi* api, int16_t* out)
{
    uint16_t v;
    if (!api->read16(0x8030B7A4u, &v)) return 0;
    *out = (int16_t)v;
    return 1;
}
static inline int soa_battle_sp_max_set(const SoaModApi* api, int16_t v)
{
    return api->write16(0x8030B7A4u, (uint16_t)v);
}
static inline int soa_battle_sp_start_get(const SoaModApi* api, int16_t* out)
{
    uint16_t v;
    if (!api->read16(0x8030B7A6u, &v)) return 0;
    *out = (int16_t)v;
    return 1;
}
static inline int soa_battle_sp_start_set(const SoaModApi* api, int16_t v)
{
    return api->write16(0x8030B7A6u, (uint16_t)v);
}
static inline int soa_rng_seed_get(const SoaModApi* api, uint32_t* out)
{
    return api->read32(0x803469A8u, out);
}
static inline int soa_rng_seed_set(const SoaModApi* api, uint32_t v)
{
    return api->write32(0x803469A8u, v);
}
static inline int soa_ship_battle_state_get(const SoaModApi* api, uint32_t* out)
{
    return api->read32(0x8034727Cu, out);
}
static inline int soa_ship_battle_state_set(const SoaModApi* api, uint32_t v)
{
    return api->write32(0x8034727Cu, v);
}
static inline int soa_ship_battle_outcome_get(const SoaModApi* api, uint32_t* out)
{
    return api->read32(0x80347278u, out);
}
static inline int soa_ship_battle_outcome_set(const SoaModApi* api, uint32_t v)
{
    return api->write32(0x80347278u, v);
}
static inline int soa_ship_battle_results_next_get(const SoaModApi* api, uint32_t* out)
{
    return api->read32(0x80347280u, out);
}
static inline int soa_ship_battle_results_next_set(const SoaModApi* api, uint32_t v)
{
    return api->write32(0x80347280u, v);
}
static inline int soa_frame_start_fields_get(const SoaModApi* api, uint32_t* out)
{
    return api->read32(0x8034768Cu, out);
}
static inline int soa_frame_start_fields_set(const SoaModApi* api, uint32_t v)
{
    return api->write32(0x8034768Cu, v);
}
static inline int soa_frame_game_get(const SoaModApi* api, uint32_t* out)
{
    return api->read32(0x803475C0u, out);
}
static inline int soa_frame_game_set(const SoaModApi* api, uint32_t v)
{
    return api->write32(0x803475C0u, v);
}
static inline int soa_vi_retrace_count_get(const SoaModApi* api, uint32_t* out)
{
    return api->read32(0x80347A64u, out);
}
static inline int soa_vi_retrace_count_set(const SoaModApi* api, uint32_t v)
{
    return api->write32(0x80347A64u, v);
}
static inline int soa_script_opcodes_handler_get(const SoaModApi* api, uint32_t i, uint32_t* out)
{
    return api->read32(0x802F7940u + i * 12u + 8u, out);
}
static inline int soa_script_opcodes_handler_set(const SoaModApi* api, uint32_t i, uint32_t v)
{
    return api->write32(0x802F7940u + i * 12u + 8u, v);
}

#endif
