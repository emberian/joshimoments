// Lean compiler output
// Module: Joshi.History
// Imports: public import Init public meta import Init
#include <lean/lean.h>
#if defined(__clang__)
#pragma clang diagnostic ignored "-Wunused-parameter"
#pragma clang diagnostic ignored "-Wunused-label"
#elif defined(__GNUC__) && !defined(__CLANG__)
#pragma GCC diagnostic ignored "-Wunused-parameter"
#pragma GCC diagnostic ignored "-Wunused-label"
#pragma GCC diagnostic ignored "-Wunused-but-set-variable"
#endif
#ifdef __cplusplus
extern "C" {
#endif
uint8_t lean_nat_dec_eq(lean_object*, lean_object*);
lean_object* l_List_reverse___redArg(lean_object*);
uint8_t lean_nat_dec_le(lean_object*, lean_object*);
lean_object* lean_nat_to_int(lean_object*);
lean_object* l_Nat_reprFast(lean_object*);
lean_object* lean_string_length(lean_object*);
static const lean_string_object lp_joshi_Joshi_instReprObs_repr___redArg___closed__0_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 3, .m_capacity = 3, .m_length = 2, .m_data = "{ "};
static const lean_object* lp_joshi_Joshi_instReprObs_repr___redArg___closed__0 = (const lean_object*)&lp_joshi_Joshi_instReprObs_repr___redArg___closed__0_value;
static const lean_string_object lp_joshi_Joshi_instReprObs_repr___redArg___closed__1_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 5, .m_capacity = 5, .m_length = 4, .m_data = "slot"};
static const lean_object* lp_joshi_Joshi_instReprObs_repr___redArg___closed__1 = (const lean_object*)&lp_joshi_Joshi_instReprObs_repr___redArg___closed__1_value;
static const lean_ctor_object lp_joshi_Joshi_instReprObs_repr___redArg___closed__2_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*1 + 0, .m_other = 1, .m_tag = 3}, .m_objs = {((lean_object*)&lp_joshi_Joshi_instReprObs_repr___redArg___closed__1_value)}};
static const lean_object* lp_joshi_Joshi_instReprObs_repr___redArg___closed__2 = (const lean_object*)&lp_joshi_Joshi_instReprObs_repr___redArg___closed__2_value;
static const lean_ctor_object lp_joshi_Joshi_instReprObs_repr___redArg___closed__3_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 5}, .m_objs = {((lean_object*)(((size_t)(0) << 1) | 1)),((lean_object*)&lp_joshi_Joshi_instReprObs_repr___redArg___closed__2_value)}};
static const lean_object* lp_joshi_Joshi_instReprObs_repr___redArg___closed__3 = (const lean_object*)&lp_joshi_Joshi_instReprObs_repr___redArg___closed__3_value;
static const lean_string_object lp_joshi_Joshi_instReprObs_repr___redArg___closed__4_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 5, .m_capacity = 5, .m_length = 4, .m_data = " := "};
static const lean_object* lp_joshi_Joshi_instReprObs_repr___redArg___closed__4 = (const lean_object*)&lp_joshi_Joshi_instReprObs_repr___redArg___closed__4_value;
static const lean_ctor_object lp_joshi_Joshi_instReprObs_repr___redArg___closed__5_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*1 + 0, .m_other = 1, .m_tag = 3}, .m_objs = {((lean_object*)&lp_joshi_Joshi_instReprObs_repr___redArg___closed__4_value)}};
static const lean_object* lp_joshi_Joshi_instReprObs_repr___redArg___closed__5 = (const lean_object*)&lp_joshi_Joshi_instReprObs_repr___redArg___closed__5_value;
static const lean_ctor_object lp_joshi_Joshi_instReprObs_repr___redArg___closed__6_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 5}, .m_objs = {((lean_object*)&lp_joshi_Joshi_instReprObs_repr___redArg___closed__3_value),((lean_object*)&lp_joshi_Joshi_instReprObs_repr___redArg___closed__5_value)}};
static const lean_object* lp_joshi_Joshi_instReprObs_repr___redArg___closed__6 = (const lean_object*)&lp_joshi_Joshi_instReprObs_repr___redArg___closed__6_value;
static lean_once_cell_t lp_joshi_Joshi_instReprObs_repr___redArg___closed__7_once = LEAN_ONCE_CELL_INITIALIZER;
static lean_object* lp_joshi_Joshi_instReprObs_repr___redArg___closed__7;
static const lean_string_object lp_joshi_Joshi_instReprObs_repr___redArg___closed__8_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 2, .m_capacity = 2, .m_length = 1, .m_data = ","};
static const lean_object* lp_joshi_Joshi_instReprObs_repr___redArg___closed__8 = (const lean_object*)&lp_joshi_Joshi_instReprObs_repr___redArg___closed__8_value;
static const lean_ctor_object lp_joshi_Joshi_instReprObs_repr___redArg___closed__9_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*1 + 0, .m_other = 1, .m_tag = 3}, .m_objs = {((lean_object*)&lp_joshi_Joshi_instReprObs_repr___redArg___closed__8_value)}};
static const lean_object* lp_joshi_Joshi_instReprObs_repr___redArg___closed__9 = (const lean_object*)&lp_joshi_Joshi_instReprObs_repr___redArg___closed__9_value;
static const lean_string_object lp_joshi_Joshi_instReprObs_repr___redArg___closed__10_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 6, .m_capacity = 6, .m_length = 5, .m_data = "value"};
static const lean_object* lp_joshi_Joshi_instReprObs_repr___redArg___closed__10 = (const lean_object*)&lp_joshi_Joshi_instReprObs_repr___redArg___closed__10_value;
static const lean_ctor_object lp_joshi_Joshi_instReprObs_repr___redArg___closed__11_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*1 + 0, .m_other = 1, .m_tag = 3}, .m_objs = {((lean_object*)&lp_joshi_Joshi_instReprObs_repr___redArg___closed__10_value)}};
static const lean_object* lp_joshi_Joshi_instReprObs_repr___redArg___closed__11 = (const lean_object*)&lp_joshi_Joshi_instReprObs_repr___redArg___closed__11_value;
static lean_once_cell_t lp_joshi_Joshi_instReprObs_repr___redArg___closed__12_once = LEAN_ONCE_CELL_INITIALIZER;
static lean_object* lp_joshi_Joshi_instReprObs_repr___redArg___closed__12;
static const lean_string_object lp_joshi_Joshi_instReprObs_repr___redArg___closed__13_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 3, .m_capacity = 3, .m_length = 2, .m_data = " }"};
static const lean_object* lp_joshi_Joshi_instReprObs_repr___redArg___closed__13 = (const lean_object*)&lp_joshi_Joshi_instReprObs_repr___redArg___closed__13_value;
static lean_once_cell_t lp_joshi_Joshi_instReprObs_repr___redArg___closed__14_once = LEAN_ONCE_CELL_INITIALIZER;
static lean_object* lp_joshi_Joshi_instReprObs_repr___redArg___closed__14;
static lean_once_cell_t lp_joshi_Joshi_instReprObs_repr___redArg___closed__15_once = LEAN_ONCE_CELL_INITIALIZER;
static lean_object* lp_joshi_Joshi_instReprObs_repr___redArg___closed__15;
static const lean_ctor_object lp_joshi_Joshi_instReprObs_repr___redArg___closed__16_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*1 + 0, .m_other = 1, .m_tag = 3}, .m_objs = {((lean_object*)&lp_joshi_Joshi_instReprObs_repr___redArg___closed__0_value)}};
static const lean_object* lp_joshi_Joshi_instReprObs_repr___redArg___closed__16 = (const lean_object*)&lp_joshi_Joshi_instReprObs_repr___redArg___closed__16_value;
static const lean_ctor_object lp_joshi_Joshi_instReprObs_repr___redArg___closed__17_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*1 + 0, .m_other = 1, .m_tag = 3}, .m_objs = {((lean_object*)&lp_joshi_Joshi_instReprObs_repr___redArg___closed__13_value)}};
static const lean_object* lp_joshi_Joshi_instReprObs_repr___redArg___closed__17 = (const lean_object*)&lp_joshi_Joshi_instReprObs_repr___redArg___closed__17_value;
LEAN_EXPORT lean_object* lp_joshi_Joshi_instReprObs_repr___redArg(lean_object*);
LEAN_EXPORT lean_object* lp_joshi_Joshi_instReprObs_repr(lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_joshi_Joshi_instReprObs_repr___boxed(lean_object*, lean_object*);
static const lean_closure_object lp_joshi_Joshi_instReprObs___closed__0_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_closure_object) + sizeof(void*)*0, .m_other = 0, .m_tag = 245}, .m_fun = (void*)lp_joshi_Joshi_instReprObs_repr___boxed, .m_arity = 2, .m_num_fixed = 0, .m_objs = {} };
static const lean_object* lp_joshi_Joshi_instReprObs___closed__0 = (const lean_object*)&lp_joshi_Joshi_instReprObs___closed__0_value;
LEAN_EXPORT const lean_object* lp_joshi_Joshi_instReprObs = (const lean_object*)&lp_joshi_Joshi_instReprObs___closed__0_value;
LEAN_EXPORT uint8_t lp_joshi_Joshi_instDecidableEqObs_decEq(lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_joshi_Joshi_instDecidableEqObs_decEq___boxed(lean_object*, lean_object*);
LEAN_EXPORT uint8_t lp_joshi_Joshi_instDecidableEqObs(lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_joshi_Joshi_instDecidableEqObs___boxed(lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_joshi_List_foldl___at___00List_foldl___at___00Std_Format_joinSep___at___00List_repr___at___00Joshi_instReprHistory_repr_spec__0_spec__0_spec__1_spec__2(lean_object*, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_joshi_List_foldl___at___00Std_Format_joinSep___at___00List_repr___at___00Joshi_instReprHistory_repr_spec__0_spec__0_spec__1(lean_object*, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_joshi_Std_Format_joinSep___at___00List_repr___at___00Joshi_instReprHistory_repr_spec__0_spec__0(lean_object*, lean_object*);
static const lean_string_object lp_joshi_List_repr___at___00Joshi_instReprHistory_repr_spec__0___redArg___closed__0_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 3, .m_capacity = 3, .m_length = 2, .m_data = "[]"};
static const lean_object* lp_joshi_List_repr___at___00Joshi_instReprHistory_repr_spec__0___redArg___closed__0 = (const lean_object*)&lp_joshi_List_repr___at___00Joshi_instReprHistory_repr_spec__0___redArg___closed__0_value;
static const lean_ctor_object lp_joshi_List_repr___at___00Joshi_instReprHistory_repr_spec__0___redArg___closed__1_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*1 + 0, .m_other = 1, .m_tag = 3}, .m_objs = {((lean_object*)&lp_joshi_List_repr___at___00Joshi_instReprHistory_repr_spec__0___redArg___closed__0_value)}};
static const lean_object* lp_joshi_List_repr___at___00Joshi_instReprHistory_repr_spec__0___redArg___closed__1 = (const lean_object*)&lp_joshi_List_repr___at___00Joshi_instReprHistory_repr_spec__0___redArg___closed__1_value;
static const lean_string_object lp_joshi_List_repr___at___00Joshi_instReprHistory_repr_spec__0___redArg___closed__2_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 2, .m_capacity = 2, .m_length = 1, .m_data = "["};
static const lean_object* lp_joshi_List_repr___at___00Joshi_instReprHistory_repr_spec__0___redArg___closed__2 = (const lean_object*)&lp_joshi_List_repr___at___00Joshi_instReprHistory_repr_spec__0___redArg___closed__2_value;
static const lean_ctor_object lp_joshi_List_repr___at___00Joshi_instReprHistory_repr_spec__0___redArg___closed__3_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 5}, .m_objs = {((lean_object*)&lp_joshi_Joshi_instReprObs_repr___redArg___closed__9_value),((lean_object*)(((size_t)(1) << 1) | 1))}};
static const lean_object* lp_joshi_List_repr___at___00Joshi_instReprHistory_repr_spec__0___redArg___closed__3 = (const lean_object*)&lp_joshi_List_repr___at___00Joshi_instReprHistory_repr_spec__0___redArg___closed__3_value;
static const lean_string_object lp_joshi_List_repr___at___00Joshi_instReprHistory_repr_spec__0___redArg___closed__4_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 2, .m_capacity = 2, .m_length = 1, .m_data = "]"};
static const lean_object* lp_joshi_List_repr___at___00Joshi_instReprHistory_repr_spec__0___redArg___closed__4 = (const lean_object*)&lp_joshi_List_repr___at___00Joshi_instReprHistory_repr_spec__0___redArg___closed__4_value;
static lean_once_cell_t lp_joshi_List_repr___at___00Joshi_instReprHistory_repr_spec__0___redArg___closed__5_once = LEAN_ONCE_CELL_INITIALIZER;
static lean_object* lp_joshi_List_repr___at___00Joshi_instReprHistory_repr_spec__0___redArg___closed__5;
static lean_once_cell_t lp_joshi_List_repr___at___00Joshi_instReprHistory_repr_spec__0___redArg___closed__6_once = LEAN_ONCE_CELL_INITIALIZER;
static lean_object* lp_joshi_List_repr___at___00Joshi_instReprHistory_repr_spec__0___redArg___closed__6;
static const lean_ctor_object lp_joshi_List_repr___at___00Joshi_instReprHistory_repr_spec__0___redArg___closed__7_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*1 + 0, .m_other = 1, .m_tag = 3}, .m_objs = {((lean_object*)&lp_joshi_List_repr___at___00Joshi_instReprHistory_repr_spec__0___redArg___closed__2_value)}};
static const lean_object* lp_joshi_List_repr___at___00Joshi_instReprHistory_repr_spec__0___redArg___closed__7 = (const lean_object*)&lp_joshi_List_repr___at___00Joshi_instReprHistory_repr_spec__0___redArg___closed__7_value;
static const lean_ctor_object lp_joshi_List_repr___at___00Joshi_instReprHistory_repr_spec__0___redArg___closed__8_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*1 + 0, .m_other = 1, .m_tag = 3}, .m_objs = {((lean_object*)&lp_joshi_List_repr___at___00Joshi_instReprHistory_repr_spec__0___redArg___closed__4_value)}};
static const lean_object* lp_joshi_List_repr___at___00Joshi_instReprHistory_repr_spec__0___redArg___closed__8 = (const lean_object*)&lp_joshi_List_repr___at___00Joshi_instReprHistory_repr_spec__0___redArg___closed__8_value;
LEAN_EXPORT lean_object* lp_joshi_List_repr___at___00Joshi_instReprHistory_repr_spec__0___redArg(lean_object*);
static const lean_string_object lp_joshi_Joshi_instReprHistory_repr___redArg___closed__0_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 7, .m_capacity = 7, .m_length = 6, .m_data = "events"};
static const lean_object* lp_joshi_Joshi_instReprHistory_repr___redArg___closed__0 = (const lean_object*)&lp_joshi_Joshi_instReprHistory_repr___redArg___closed__0_value;
static const lean_ctor_object lp_joshi_Joshi_instReprHistory_repr___redArg___closed__1_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*1 + 0, .m_other = 1, .m_tag = 3}, .m_objs = {((lean_object*)&lp_joshi_Joshi_instReprHistory_repr___redArg___closed__0_value)}};
static const lean_object* lp_joshi_Joshi_instReprHistory_repr___redArg___closed__1 = (const lean_object*)&lp_joshi_Joshi_instReprHistory_repr___redArg___closed__1_value;
static const lean_ctor_object lp_joshi_Joshi_instReprHistory_repr___redArg___closed__2_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 5}, .m_objs = {((lean_object*)(((size_t)(0) << 1) | 1)),((lean_object*)&lp_joshi_Joshi_instReprHistory_repr___redArg___closed__1_value)}};
static const lean_object* lp_joshi_Joshi_instReprHistory_repr___redArg___closed__2 = (const lean_object*)&lp_joshi_Joshi_instReprHistory_repr___redArg___closed__2_value;
static const lean_ctor_object lp_joshi_Joshi_instReprHistory_repr___redArg___closed__3_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 5}, .m_objs = {((lean_object*)&lp_joshi_Joshi_instReprHistory_repr___redArg___closed__2_value),((lean_object*)&lp_joshi_Joshi_instReprObs_repr___redArg___closed__5_value)}};
static const lean_object* lp_joshi_Joshi_instReprHistory_repr___redArg___closed__3 = (const lean_object*)&lp_joshi_Joshi_instReprHistory_repr___redArg___closed__3_value;
static lean_once_cell_t lp_joshi_Joshi_instReprHistory_repr___redArg___closed__4_once = LEAN_ONCE_CELL_INITIALIZER;
static lean_object* lp_joshi_Joshi_instReprHistory_repr___redArg___closed__4;
LEAN_EXPORT lean_object* lp_joshi_Joshi_instReprHistory_repr___redArg(lean_object*);
LEAN_EXPORT lean_object* lp_joshi_Joshi_instReprHistory_repr(lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_joshi_Joshi_instReprHistory_repr___boxed(lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_joshi_List_repr___at___00Joshi_instReprHistory_repr_spec__0(lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_joshi_List_repr___at___00Joshi_instReprHistory_repr_spec__0___boxed(lean_object*, lean_object*);
static const lean_closure_object lp_joshi_Joshi_instReprHistory___closed__0_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_closure_object) + sizeof(void*)*0, .m_other = 0, .m_tag = 245}, .m_fun = (void*)lp_joshi_Joshi_instReprHistory_repr___boxed, .m_arity = 2, .m_num_fixed = 0, .m_objs = {} };
static const lean_object* lp_joshi_Joshi_instReprHistory___closed__0 = (const lean_object*)&lp_joshi_Joshi_instReprHistory___closed__0_value;
LEAN_EXPORT const lean_object* lp_joshi_Joshi_instReprHistory = (const lean_object*)&lp_joshi_Joshi_instReprHistory___closed__0_value;
LEAN_EXPORT lean_object* lp_joshi_List_filterTR_loop___at___00Joshi_History_visible_spec__0(lean_object*, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_joshi_List_filterTR_loop___at___00Joshi_History_visible_spec__0___boxed(lean_object*, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_joshi_Joshi_History_visible(lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_joshi_Joshi_History_visible___boxed(lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_joshi_Joshi_View_at(lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_joshi_Joshi_View_at___boxed(lean_object*, lean_object*);
static lean_object* _init_lp_joshi_Joshi_instReprObs_repr___redArg___closed__7(void){
_start:
{
lean_object* v___x_14_; lean_object* v___x_15_; 
v___x_14_ = lean_unsigned_to_nat(8u);
v___x_15_ = lean_nat_to_int(v___x_14_);
return v___x_15_;
}
}
static lean_object* _init_lp_joshi_Joshi_instReprObs_repr___redArg___closed__12(void){
_start:
{
lean_object* v___x_22_; lean_object* v___x_23_; 
v___x_22_ = lean_unsigned_to_nat(9u);
v___x_23_ = lean_nat_to_int(v___x_22_);
return v___x_23_;
}
}
static lean_object* _init_lp_joshi_Joshi_instReprObs_repr___redArg___closed__14(void){
_start:
{
lean_object* v___x_25_; lean_object* v___x_26_; 
v___x_25_ = ((lean_object*)(lp_joshi_Joshi_instReprObs_repr___redArg___closed__0));
v___x_26_ = lean_string_length(v___x_25_);
return v___x_26_;
}
}
static lean_object* _init_lp_joshi_Joshi_instReprObs_repr___redArg___closed__15(void){
_start:
{
lean_object* v___x_27_; lean_object* v___x_28_; 
v___x_27_ = lean_obj_once(&lp_joshi_Joshi_instReprObs_repr___redArg___closed__14, &lp_joshi_Joshi_instReprObs_repr___redArg___closed__14_once, _init_lp_joshi_Joshi_instReprObs_repr___redArg___closed__14);
v___x_28_ = lean_nat_to_int(v___x_27_);
return v___x_28_;
}
}
LEAN_EXPORT lean_object* lp_joshi_Joshi_instReprObs_repr___redArg(lean_object* v_x_33_){
_start:
{
lean_object* v_slot_34_; lean_object* v_value_35_; lean_object* v___x_37_; uint8_t v_isShared_38_; uint8_t v_isSharedCheck_70_; 
v_slot_34_ = lean_ctor_get(v_x_33_, 0);
v_value_35_ = lean_ctor_get(v_x_33_, 1);
v_isSharedCheck_70_ = !lean_is_exclusive(v_x_33_);
if (v_isSharedCheck_70_ == 0)
{
v___x_37_ = v_x_33_;
v_isShared_38_ = v_isSharedCheck_70_;
goto v_resetjp_36_;
}
else
{
lean_inc(v_value_35_);
lean_inc(v_slot_34_);
lean_dec(v_x_33_);
v___x_37_ = lean_box(0);
v_isShared_38_ = v_isSharedCheck_70_;
goto v_resetjp_36_;
}
v_resetjp_36_:
{
lean_object* v___x_39_; lean_object* v___x_40_; lean_object* v___x_41_; lean_object* v___x_42_; lean_object* v___x_43_; lean_object* v___x_45_; 
v___x_39_ = ((lean_object*)(lp_joshi_Joshi_instReprObs_repr___redArg___closed__5));
v___x_40_ = ((lean_object*)(lp_joshi_Joshi_instReprObs_repr___redArg___closed__6));
v___x_41_ = lean_obj_once(&lp_joshi_Joshi_instReprObs_repr___redArg___closed__7, &lp_joshi_Joshi_instReprObs_repr___redArg___closed__7_once, _init_lp_joshi_Joshi_instReprObs_repr___redArg___closed__7);
v___x_42_ = l_Nat_reprFast(v_slot_34_);
v___x_43_ = lean_alloc_ctor(3, 1, 0);
lean_ctor_set(v___x_43_, 0, v___x_42_);
if (v_isShared_38_ == 0)
{
lean_ctor_set_tag(v___x_37_, 4);
lean_ctor_set(v___x_37_, 1, v___x_43_);
lean_ctor_set(v___x_37_, 0, v___x_41_);
v___x_45_ = v___x_37_;
goto v_reusejp_44_;
}
else
{
lean_object* v_reuseFailAlloc_69_; 
v_reuseFailAlloc_69_ = lean_alloc_ctor(4, 2, 0);
lean_ctor_set(v_reuseFailAlloc_69_, 0, v___x_41_);
lean_ctor_set(v_reuseFailAlloc_69_, 1, v___x_43_);
v___x_45_ = v_reuseFailAlloc_69_;
goto v_reusejp_44_;
}
v_reusejp_44_:
{
uint8_t v___x_46_; lean_object* v___x_47_; lean_object* v___x_48_; lean_object* v___x_49_; lean_object* v___x_50_; lean_object* v___x_51_; lean_object* v___x_52_; lean_object* v___x_53_; lean_object* v___x_54_; lean_object* v___x_55_; lean_object* v___x_56_; lean_object* v___x_57_; lean_object* v___x_58_; lean_object* v___x_59_; lean_object* v___x_60_; lean_object* v___x_61_; lean_object* v___x_62_; lean_object* v___x_63_; lean_object* v___x_64_; lean_object* v___x_65_; lean_object* v___x_66_; lean_object* v___x_67_; lean_object* v___x_68_; 
v___x_46_ = 0;
v___x_47_ = lean_alloc_ctor(6, 1, 1);
lean_ctor_set(v___x_47_, 0, v___x_45_);
lean_ctor_set_uint8(v___x_47_, sizeof(void*)*1, v___x_46_);
v___x_48_ = lean_alloc_ctor(5, 2, 0);
lean_ctor_set(v___x_48_, 0, v___x_40_);
lean_ctor_set(v___x_48_, 1, v___x_47_);
v___x_49_ = ((lean_object*)(lp_joshi_Joshi_instReprObs_repr___redArg___closed__9));
v___x_50_ = lean_alloc_ctor(5, 2, 0);
lean_ctor_set(v___x_50_, 0, v___x_48_);
lean_ctor_set(v___x_50_, 1, v___x_49_);
v___x_51_ = lean_box(1);
v___x_52_ = lean_alloc_ctor(5, 2, 0);
lean_ctor_set(v___x_52_, 0, v___x_50_);
lean_ctor_set(v___x_52_, 1, v___x_51_);
v___x_53_ = ((lean_object*)(lp_joshi_Joshi_instReprObs_repr___redArg___closed__11));
v___x_54_ = lean_alloc_ctor(5, 2, 0);
lean_ctor_set(v___x_54_, 0, v___x_52_);
lean_ctor_set(v___x_54_, 1, v___x_53_);
v___x_55_ = lean_alloc_ctor(5, 2, 0);
lean_ctor_set(v___x_55_, 0, v___x_54_);
lean_ctor_set(v___x_55_, 1, v___x_39_);
v___x_56_ = lean_obj_once(&lp_joshi_Joshi_instReprObs_repr___redArg___closed__12, &lp_joshi_Joshi_instReprObs_repr___redArg___closed__12_once, _init_lp_joshi_Joshi_instReprObs_repr___redArg___closed__12);
v___x_57_ = l_Nat_reprFast(v_value_35_);
v___x_58_ = lean_alloc_ctor(3, 1, 0);
lean_ctor_set(v___x_58_, 0, v___x_57_);
v___x_59_ = lean_alloc_ctor(4, 2, 0);
lean_ctor_set(v___x_59_, 0, v___x_56_);
lean_ctor_set(v___x_59_, 1, v___x_58_);
v___x_60_ = lean_alloc_ctor(6, 1, 1);
lean_ctor_set(v___x_60_, 0, v___x_59_);
lean_ctor_set_uint8(v___x_60_, sizeof(void*)*1, v___x_46_);
v___x_61_ = lean_alloc_ctor(5, 2, 0);
lean_ctor_set(v___x_61_, 0, v___x_55_);
lean_ctor_set(v___x_61_, 1, v___x_60_);
v___x_62_ = lean_obj_once(&lp_joshi_Joshi_instReprObs_repr___redArg___closed__15, &lp_joshi_Joshi_instReprObs_repr___redArg___closed__15_once, _init_lp_joshi_Joshi_instReprObs_repr___redArg___closed__15);
v___x_63_ = ((lean_object*)(lp_joshi_Joshi_instReprObs_repr___redArg___closed__16));
v___x_64_ = lean_alloc_ctor(5, 2, 0);
lean_ctor_set(v___x_64_, 0, v___x_63_);
lean_ctor_set(v___x_64_, 1, v___x_61_);
v___x_65_ = ((lean_object*)(lp_joshi_Joshi_instReprObs_repr___redArg___closed__17));
v___x_66_ = lean_alloc_ctor(5, 2, 0);
lean_ctor_set(v___x_66_, 0, v___x_64_);
lean_ctor_set(v___x_66_, 1, v___x_65_);
v___x_67_ = lean_alloc_ctor(4, 2, 0);
lean_ctor_set(v___x_67_, 0, v___x_62_);
lean_ctor_set(v___x_67_, 1, v___x_66_);
v___x_68_ = lean_alloc_ctor(6, 1, 1);
lean_ctor_set(v___x_68_, 0, v___x_67_);
lean_ctor_set_uint8(v___x_68_, sizeof(void*)*1, v___x_46_);
return v___x_68_;
}
}
}
}
LEAN_EXPORT lean_object* lp_joshi_Joshi_instReprObs_repr(lean_object* v_x_71_, lean_object* v_prec_72_){
_start:
{
lean_object* v___x_73_; 
v___x_73_ = lp_joshi_Joshi_instReprObs_repr___redArg(v_x_71_);
return v___x_73_;
}
}
LEAN_EXPORT lean_object* lp_joshi_Joshi_instReprObs_repr___boxed(lean_object* v_x_74_, lean_object* v_prec_75_){
_start:
{
lean_object* v_res_76_; 
v_res_76_ = lp_joshi_Joshi_instReprObs_repr(v_x_74_, v_prec_75_);
lean_dec(v_prec_75_);
return v_res_76_;
}
}
LEAN_EXPORT uint8_t lp_joshi_Joshi_instDecidableEqObs_decEq(lean_object* v_x_79_, lean_object* v_x_80_){
_start:
{
lean_object* v_slot_81_; lean_object* v_value_82_; lean_object* v_slot_83_; lean_object* v_value_84_; uint8_t v___x_85_; 
v_slot_81_ = lean_ctor_get(v_x_79_, 0);
v_value_82_ = lean_ctor_get(v_x_79_, 1);
v_slot_83_ = lean_ctor_get(v_x_80_, 0);
v_value_84_ = lean_ctor_get(v_x_80_, 1);
v___x_85_ = lean_nat_dec_eq(v_slot_81_, v_slot_83_);
if (v___x_85_ == 0)
{
return v___x_85_;
}
else
{
uint8_t v___x_86_; 
v___x_86_ = lean_nat_dec_eq(v_value_82_, v_value_84_);
return v___x_86_;
}
}
}
LEAN_EXPORT lean_object* lp_joshi_Joshi_instDecidableEqObs_decEq___boxed(lean_object* v_x_87_, lean_object* v_x_88_){
_start:
{
uint8_t v_res_89_; lean_object* v_r_90_; 
v_res_89_ = lp_joshi_Joshi_instDecidableEqObs_decEq(v_x_87_, v_x_88_);
lean_dec_ref(v_x_88_);
lean_dec_ref(v_x_87_);
v_r_90_ = lean_box(v_res_89_);
return v_r_90_;
}
}
LEAN_EXPORT uint8_t lp_joshi_Joshi_instDecidableEqObs(lean_object* v_x_91_, lean_object* v_x_92_){
_start:
{
uint8_t v___x_93_; 
v___x_93_ = lp_joshi_Joshi_instDecidableEqObs_decEq(v_x_91_, v_x_92_);
return v___x_93_;
}
}
LEAN_EXPORT lean_object* lp_joshi_Joshi_instDecidableEqObs___boxed(lean_object* v_x_94_, lean_object* v_x_95_){
_start:
{
uint8_t v_res_96_; lean_object* v_r_97_; 
v_res_96_ = lp_joshi_Joshi_instDecidableEqObs(v_x_94_, v_x_95_);
lean_dec_ref(v_x_95_);
lean_dec_ref(v_x_94_);
v_r_97_ = lean_box(v_res_96_);
return v_r_97_;
}
}
LEAN_EXPORT lean_object* lp_joshi_List_foldl___at___00List_foldl___at___00Std_Format_joinSep___at___00List_repr___at___00Joshi_instReprHistory_repr_spec__0_spec__0_spec__1_spec__2(lean_object* v_x_98_, lean_object* v_x_99_, lean_object* v_x_100_){
_start:
{
if (lean_obj_tag(v_x_100_) == 0)
{
lean_dec(v_x_98_);
return v_x_99_;
}
else
{
lean_object* v_head_101_; lean_object* v_tail_102_; lean_object* v___x_104_; uint8_t v_isShared_105_; uint8_t v_isSharedCheck_112_; 
v_head_101_ = lean_ctor_get(v_x_100_, 0);
v_tail_102_ = lean_ctor_get(v_x_100_, 1);
v_isSharedCheck_112_ = !lean_is_exclusive(v_x_100_);
if (v_isSharedCheck_112_ == 0)
{
v___x_104_ = v_x_100_;
v_isShared_105_ = v_isSharedCheck_112_;
goto v_resetjp_103_;
}
else
{
lean_inc(v_tail_102_);
lean_inc(v_head_101_);
lean_dec(v_x_100_);
v___x_104_ = lean_box(0);
v_isShared_105_ = v_isSharedCheck_112_;
goto v_resetjp_103_;
}
v_resetjp_103_:
{
lean_object* v___x_107_; 
lean_inc(v_x_98_);
if (v_isShared_105_ == 0)
{
lean_ctor_set_tag(v___x_104_, 5);
lean_ctor_set(v___x_104_, 1, v_x_98_);
lean_ctor_set(v___x_104_, 0, v_x_99_);
v___x_107_ = v___x_104_;
goto v_reusejp_106_;
}
else
{
lean_object* v_reuseFailAlloc_111_; 
v_reuseFailAlloc_111_ = lean_alloc_ctor(5, 2, 0);
lean_ctor_set(v_reuseFailAlloc_111_, 0, v_x_99_);
lean_ctor_set(v_reuseFailAlloc_111_, 1, v_x_98_);
v___x_107_ = v_reuseFailAlloc_111_;
goto v_reusejp_106_;
}
v_reusejp_106_:
{
lean_object* v___x_108_; lean_object* v___x_109_; 
v___x_108_ = lp_joshi_Joshi_instReprObs_repr___redArg(v_head_101_);
v___x_109_ = lean_alloc_ctor(5, 2, 0);
lean_ctor_set(v___x_109_, 0, v___x_107_);
lean_ctor_set(v___x_109_, 1, v___x_108_);
v_x_99_ = v___x_109_;
v_x_100_ = v_tail_102_;
goto _start;
}
}
}
}
}
LEAN_EXPORT lean_object* lp_joshi_List_foldl___at___00Std_Format_joinSep___at___00List_repr___at___00Joshi_instReprHistory_repr_spec__0_spec__0_spec__1(lean_object* v_x_113_, lean_object* v_x_114_, lean_object* v_x_115_){
_start:
{
if (lean_obj_tag(v_x_115_) == 0)
{
lean_dec(v_x_113_);
return v_x_114_;
}
else
{
lean_object* v_head_116_; lean_object* v_tail_117_; lean_object* v___x_119_; uint8_t v_isShared_120_; uint8_t v_isSharedCheck_127_; 
v_head_116_ = lean_ctor_get(v_x_115_, 0);
v_tail_117_ = lean_ctor_get(v_x_115_, 1);
v_isSharedCheck_127_ = !lean_is_exclusive(v_x_115_);
if (v_isSharedCheck_127_ == 0)
{
v___x_119_ = v_x_115_;
v_isShared_120_ = v_isSharedCheck_127_;
goto v_resetjp_118_;
}
else
{
lean_inc(v_tail_117_);
lean_inc(v_head_116_);
lean_dec(v_x_115_);
v___x_119_ = lean_box(0);
v_isShared_120_ = v_isSharedCheck_127_;
goto v_resetjp_118_;
}
v_resetjp_118_:
{
lean_object* v___x_122_; 
lean_inc(v_x_113_);
if (v_isShared_120_ == 0)
{
lean_ctor_set_tag(v___x_119_, 5);
lean_ctor_set(v___x_119_, 1, v_x_113_);
lean_ctor_set(v___x_119_, 0, v_x_114_);
v___x_122_ = v___x_119_;
goto v_reusejp_121_;
}
else
{
lean_object* v_reuseFailAlloc_126_; 
v_reuseFailAlloc_126_ = lean_alloc_ctor(5, 2, 0);
lean_ctor_set(v_reuseFailAlloc_126_, 0, v_x_114_);
lean_ctor_set(v_reuseFailAlloc_126_, 1, v_x_113_);
v___x_122_ = v_reuseFailAlloc_126_;
goto v_reusejp_121_;
}
v_reusejp_121_:
{
lean_object* v___x_123_; lean_object* v___x_124_; lean_object* v___x_125_; 
v___x_123_ = lp_joshi_Joshi_instReprObs_repr___redArg(v_head_116_);
v___x_124_ = lean_alloc_ctor(5, 2, 0);
lean_ctor_set(v___x_124_, 0, v___x_122_);
lean_ctor_set(v___x_124_, 1, v___x_123_);
v___x_125_ = lp_joshi_List_foldl___at___00List_foldl___at___00Std_Format_joinSep___at___00List_repr___at___00Joshi_instReprHistory_repr_spec__0_spec__0_spec__1_spec__2(v_x_113_, v___x_124_, v_tail_117_);
return v___x_125_;
}
}
}
}
}
LEAN_EXPORT lean_object* lp_joshi_Std_Format_joinSep___at___00List_repr___at___00Joshi_instReprHistory_repr_spec__0_spec__0(lean_object* v_x_128_, lean_object* v_x_129_){
_start:
{
if (lean_obj_tag(v_x_128_) == 0)
{
lean_object* v___x_130_; 
lean_dec(v_x_129_);
v___x_130_ = lean_box(0);
return v___x_130_;
}
else
{
lean_object* v_tail_131_; 
v_tail_131_ = lean_ctor_get(v_x_128_, 1);
if (lean_obj_tag(v_tail_131_) == 0)
{
lean_object* v_head_132_; lean_object* v___x_133_; 
lean_dec(v_x_129_);
v_head_132_ = lean_ctor_get(v_x_128_, 0);
lean_inc(v_head_132_);
lean_dec_ref_known(v_x_128_, 2);
v___x_133_ = lp_joshi_Joshi_instReprObs_repr___redArg(v_head_132_);
return v___x_133_;
}
else
{
lean_object* v_head_134_; lean_object* v___x_135_; lean_object* v___x_136_; 
lean_inc(v_tail_131_);
v_head_134_ = lean_ctor_get(v_x_128_, 0);
lean_inc(v_head_134_);
lean_dec_ref_known(v_x_128_, 2);
v___x_135_ = lp_joshi_Joshi_instReprObs_repr___redArg(v_head_134_);
v___x_136_ = lp_joshi_List_foldl___at___00Std_Format_joinSep___at___00List_repr___at___00Joshi_instReprHistory_repr_spec__0_spec__0_spec__1(v_x_129_, v___x_135_, v_tail_131_);
return v___x_136_;
}
}
}
}
static lean_object* _init_lp_joshi_List_repr___at___00Joshi_instReprHistory_repr_spec__0___redArg___closed__5(void){
_start:
{
lean_object* v___x_145_; lean_object* v___x_146_; 
v___x_145_ = ((lean_object*)(lp_joshi_List_repr___at___00Joshi_instReprHistory_repr_spec__0___redArg___closed__2));
v___x_146_ = lean_string_length(v___x_145_);
return v___x_146_;
}
}
static lean_object* _init_lp_joshi_List_repr___at___00Joshi_instReprHistory_repr_spec__0___redArg___closed__6(void){
_start:
{
lean_object* v___x_147_; lean_object* v___x_148_; 
v___x_147_ = lean_obj_once(&lp_joshi_List_repr___at___00Joshi_instReprHistory_repr_spec__0___redArg___closed__5, &lp_joshi_List_repr___at___00Joshi_instReprHistory_repr_spec__0___redArg___closed__5_once, _init_lp_joshi_List_repr___at___00Joshi_instReprHistory_repr_spec__0___redArg___closed__5);
v___x_148_ = lean_nat_to_int(v___x_147_);
return v___x_148_;
}
}
LEAN_EXPORT lean_object* lp_joshi_List_repr___at___00Joshi_instReprHistory_repr_spec__0___redArg(lean_object* v_a_153_){
_start:
{
if (lean_obj_tag(v_a_153_) == 0)
{
lean_object* v___x_154_; 
v___x_154_ = ((lean_object*)(lp_joshi_List_repr___at___00Joshi_instReprHistory_repr_spec__0___redArg___closed__1));
return v___x_154_;
}
else
{
lean_object* v___x_155_; lean_object* v___x_156_; lean_object* v___x_157_; lean_object* v___x_158_; lean_object* v___x_159_; lean_object* v___x_160_; lean_object* v___x_161_; lean_object* v___x_162_; uint8_t v___x_163_; lean_object* v___x_164_; 
v___x_155_ = ((lean_object*)(lp_joshi_List_repr___at___00Joshi_instReprHistory_repr_spec__0___redArg___closed__3));
v___x_156_ = lp_joshi_Std_Format_joinSep___at___00List_repr___at___00Joshi_instReprHistory_repr_spec__0_spec__0(v_a_153_, v___x_155_);
v___x_157_ = lean_obj_once(&lp_joshi_List_repr___at___00Joshi_instReprHistory_repr_spec__0___redArg___closed__6, &lp_joshi_List_repr___at___00Joshi_instReprHistory_repr_spec__0___redArg___closed__6_once, _init_lp_joshi_List_repr___at___00Joshi_instReprHistory_repr_spec__0___redArg___closed__6);
v___x_158_ = ((lean_object*)(lp_joshi_List_repr___at___00Joshi_instReprHistory_repr_spec__0___redArg___closed__7));
v___x_159_ = lean_alloc_ctor(5, 2, 0);
lean_ctor_set(v___x_159_, 0, v___x_158_);
lean_ctor_set(v___x_159_, 1, v___x_156_);
v___x_160_ = ((lean_object*)(lp_joshi_List_repr___at___00Joshi_instReprHistory_repr_spec__0___redArg___closed__8));
v___x_161_ = lean_alloc_ctor(5, 2, 0);
lean_ctor_set(v___x_161_, 0, v___x_159_);
lean_ctor_set(v___x_161_, 1, v___x_160_);
v___x_162_ = lean_alloc_ctor(4, 2, 0);
lean_ctor_set(v___x_162_, 0, v___x_157_);
lean_ctor_set(v___x_162_, 1, v___x_161_);
v___x_163_ = 0;
v___x_164_ = lean_alloc_ctor(6, 1, 1);
lean_ctor_set(v___x_164_, 0, v___x_162_);
lean_ctor_set_uint8(v___x_164_, sizeof(void*)*1, v___x_163_);
return v___x_164_;
}
}
}
static lean_object* _init_lp_joshi_Joshi_instReprHistory_repr___redArg___closed__4(void){
_start:
{
lean_object* v___x_174_; lean_object* v___x_175_; 
v___x_174_ = lean_unsigned_to_nat(10u);
v___x_175_ = lean_nat_to_int(v___x_174_);
return v___x_175_;
}
}
LEAN_EXPORT lean_object* lp_joshi_Joshi_instReprHistory_repr___redArg(lean_object* v_x_176_){
_start:
{
lean_object* v___x_177_; lean_object* v___x_178_; lean_object* v___x_179_; lean_object* v___x_180_; uint8_t v___x_181_; lean_object* v___x_182_; lean_object* v___x_183_; lean_object* v___x_184_; lean_object* v___x_185_; lean_object* v___x_186_; lean_object* v___x_187_; lean_object* v___x_188_; lean_object* v___x_189_; lean_object* v___x_190_; 
v___x_177_ = ((lean_object*)(lp_joshi_Joshi_instReprHistory_repr___redArg___closed__3));
v___x_178_ = lean_obj_once(&lp_joshi_Joshi_instReprHistory_repr___redArg___closed__4, &lp_joshi_Joshi_instReprHistory_repr___redArg___closed__4_once, _init_lp_joshi_Joshi_instReprHistory_repr___redArg___closed__4);
v___x_179_ = lp_joshi_List_repr___at___00Joshi_instReprHistory_repr_spec__0___redArg(v_x_176_);
v___x_180_ = lean_alloc_ctor(4, 2, 0);
lean_ctor_set(v___x_180_, 0, v___x_178_);
lean_ctor_set(v___x_180_, 1, v___x_179_);
v___x_181_ = 0;
v___x_182_ = lean_alloc_ctor(6, 1, 1);
lean_ctor_set(v___x_182_, 0, v___x_180_);
lean_ctor_set_uint8(v___x_182_, sizeof(void*)*1, v___x_181_);
v___x_183_ = lean_alloc_ctor(5, 2, 0);
lean_ctor_set(v___x_183_, 0, v___x_177_);
lean_ctor_set(v___x_183_, 1, v___x_182_);
v___x_184_ = lean_obj_once(&lp_joshi_Joshi_instReprObs_repr___redArg___closed__15, &lp_joshi_Joshi_instReprObs_repr___redArg___closed__15_once, _init_lp_joshi_Joshi_instReprObs_repr___redArg___closed__15);
v___x_185_ = ((lean_object*)(lp_joshi_Joshi_instReprObs_repr___redArg___closed__16));
v___x_186_ = lean_alloc_ctor(5, 2, 0);
lean_ctor_set(v___x_186_, 0, v___x_185_);
lean_ctor_set(v___x_186_, 1, v___x_183_);
v___x_187_ = ((lean_object*)(lp_joshi_Joshi_instReprObs_repr___redArg___closed__17));
v___x_188_ = lean_alloc_ctor(5, 2, 0);
lean_ctor_set(v___x_188_, 0, v___x_186_);
lean_ctor_set(v___x_188_, 1, v___x_187_);
v___x_189_ = lean_alloc_ctor(4, 2, 0);
lean_ctor_set(v___x_189_, 0, v___x_184_);
lean_ctor_set(v___x_189_, 1, v___x_188_);
v___x_190_ = lean_alloc_ctor(6, 1, 1);
lean_ctor_set(v___x_190_, 0, v___x_189_);
lean_ctor_set_uint8(v___x_190_, sizeof(void*)*1, v___x_181_);
return v___x_190_;
}
}
LEAN_EXPORT lean_object* lp_joshi_Joshi_instReprHistory_repr(lean_object* v_x_191_, lean_object* v_prec_192_){
_start:
{
lean_object* v___x_193_; 
v___x_193_ = lp_joshi_Joshi_instReprHistory_repr___redArg(v_x_191_);
return v___x_193_;
}
}
LEAN_EXPORT lean_object* lp_joshi_Joshi_instReprHistory_repr___boxed(lean_object* v_x_194_, lean_object* v_prec_195_){
_start:
{
lean_object* v_res_196_; 
v_res_196_ = lp_joshi_Joshi_instReprHistory_repr(v_x_194_, v_prec_195_);
lean_dec(v_prec_195_);
return v_res_196_;
}
}
LEAN_EXPORT lean_object* lp_joshi_List_repr___at___00Joshi_instReprHistory_repr_spec__0(lean_object* v_a_197_, lean_object* v_n_198_){
_start:
{
lean_object* v___x_199_; 
v___x_199_ = lp_joshi_List_repr___at___00Joshi_instReprHistory_repr_spec__0___redArg(v_a_197_);
return v___x_199_;
}
}
LEAN_EXPORT lean_object* lp_joshi_List_repr___at___00Joshi_instReprHistory_repr_spec__0___boxed(lean_object* v_a_200_, lean_object* v_n_201_){
_start:
{
lean_object* v_res_202_; 
v_res_202_ = lp_joshi_List_repr___at___00Joshi_instReprHistory_repr_spec__0(v_a_200_, v_n_201_);
lean_dec(v_n_201_);
return v_res_202_;
}
}
LEAN_EXPORT lean_object* lp_joshi_List_filterTR_loop___at___00Joshi_History_visible_spec__0(lean_object* v_t_205_, lean_object* v_a_206_, lean_object* v_a_207_){
_start:
{
if (lean_obj_tag(v_a_206_) == 0)
{
lean_object* v___x_208_; 
v___x_208_ = l_List_reverse___redArg(v_a_207_);
return v___x_208_;
}
else
{
lean_object* v_head_209_; lean_object* v_tail_210_; lean_object* v___x_212_; uint8_t v_isShared_213_; uint8_t v_isSharedCheck_221_; 
v_head_209_ = lean_ctor_get(v_a_206_, 0);
v_tail_210_ = lean_ctor_get(v_a_206_, 1);
v_isSharedCheck_221_ = !lean_is_exclusive(v_a_206_);
if (v_isSharedCheck_221_ == 0)
{
v___x_212_ = v_a_206_;
v_isShared_213_ = v_isSharedCheck_221_;
goto v_resetjp_211_;
}
else
{
lean_inc(v_tail_210_);
lean_inc(v_head_209_);
lean_dec(v_a_206_);
v___x_212_ = lean_box(0);
v_isShared_213_ = v_isSharedCheck_221_;
goto v_resetjp_211_;
}
v_resetjp_211_:
{
lean_object* v_slot_214_; uint8_t v___x_215_; 
v_slot_214_ = lean_ctor_get(v_head_209_, 0);
v___x_215_ = lean_nat_dec_le(v_slot_214_, v_t_205_);
if (v___x_215_ == 0)
{
lean_del_object(v___x_212_);
lean_dec(v_head_209_);
v_a_206_ = v_tail_210_;
goto _start;
}
else
{
lean_object* v___x_218_; 
if (v_isShared_213_ == 0)
{
lean_ctor_set(v___x_212_, 1, v_a_207_);
v___x_218_ = v___x_212_;
goto v_reusejp_217_;
}
else
{
lean_object* v_reuseFailAlloc_220_; 
v_reuseFailAlloc_220_ = lean_alloc_ctor(1, 2, 0);
lean_ctor_set(v_reuseFailAlloc_220_, 0, v_head_209_);
lean_ctor_set(v_reuseFailAlloc_220_, 1, v_a_207_);
v___x_218_ = v_reuseFailAlloc_220_;
goto v_reusejp_217_;
}
v_reusejp_217_:
{
v_a_206_ = v_tail_210_;
v_a_207_ = v___x_218_;
goto _start;
}
}
}
}
}
}
LEAN_EXPORT lean_object* lp_joshi_List_filterTR_loop___at___00Joshi_History_visible_spec__0___boxed(lean_object* v_t_222_, lean_object* v_a_223_, lean_object* v_a_224_){
_start:
{
lean_object* v_res_225_; 
v_res_225_ = lp_joshi_List_filterTR_loop___at___00Joshi_History_visible_spec__0(v_t_222_, v_a_223_, v_a_224_);
lean_dec(v_t_222_);
return v_res_225_;
}
}
LEAN_EXPORT lean_object* lp_joshi_Joshi_History_visible(lean_object* v_h_226_, lean_object* v_t_227_){
_start:
{
lean_object* v___x_228_; lean_object* v___x_229_; 
v___x_228_ = lean_box(0);
v___x_229_ = lp_joshi_List_filterTR_loop___at___00Joshi_History_visible_spec__0(v_t_227_, v_h_226_, v___x_228_);
return v___x_229_;
}
}
LEAN_EXPORT lean_object* lp_joshi_Joshi_History_visible___boxed(lean_object* v_h_230_, lean_object* v_t_231_){
_start:
{
lean_object* v_res_232_; 
v_res_232_ = lp_joshi_Joshi_History_visible(v_h_230_, v_t_231_);
lean_dec(v_t_231_);
return v_res_232_;
}
}
LEAN_EXPORT lean_object* lp_joshi_Joshi_View_at(lean_object* v_h_233_, lean_object* v_t_234_){
_start:
{
lean_object* v___x_235_; 
v___x_235_ = lp_joshi_Joshi_History_visible(v_h_233_, v_t_234_);
return v___x_235_;
}
}
LEAN_EXPORT lean_object* lp_joshi_Joshi_View_at___boxed(lean_object* v_h_236_, lean_object* v_t_237_){
_start:
{
lean_object* v_res_238_; 
v_res_238_ = lp_joshi_Joshi_View_at(v_h_236_, v_t_237_);
lean_dec(v_t_237_);
return v_res_238_;
}
}
lean_object* initialize_Init(uint8_t builtin);
lean_object* initialize_Init(uint8_t builtin);
static bool _G_initialized = false;
LEAN_EXPORT lean_object* initialize_joshi_Joshi_History(uint8_t builtin) {
lean_object * res;
if (_G_initialized) return lean_io_result_mk_ok(lean_box(0));
_G_initialized = true;
res = initialize_Init(builtin);
if (lean_io_result_is_error(res)) return res;
lean_dec_ref(res);
res = initialize_Init(builtin);
if (lean_io_result_is_error(res)) return res;
lean_dec_ref(res);
return lean_io_result_mk_ok(lean_box(0));
}
#ifdef __cplusplus
}
#endif
