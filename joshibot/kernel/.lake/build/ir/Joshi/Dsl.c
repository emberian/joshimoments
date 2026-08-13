// Lean compiler output
// Module: Joshi.Dsl
// Imports: public import Init public meta import Init public import Joshi.History
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
lean_object* lean_nat_add(lean_object*, lean_object*);
lean_object* lean_nat_sub(lean_object*, lean_object*);
uint8_t lean_nat_dec_le(lean_object*, lean_object*);
lean_object* l_Nat_reprFast(lean_object*);
lean_object* l_Repr_addAppParen(lean_object*, lean_object*);
lean_object* lean_nat_to_int(lean_object*);
uint8_t lean_nat_dec_eq(lean_object*, lean_object*);
lean_object* lean_nat_mul(lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_joshi_Joshi_Expr_ctorIdx___redArg(lean_object*);
LEAN_EXPORT lean_object* lp_joshi_Joshi_Expr_ctorIdx___redArg___boxed(lean_object*);
LEAN_EXPORT lean_object* lp_joshi_Joshi_Expr_ctorIdx(lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_joshi_Joshi_Expr_ctorIdx___boxed(lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_joshi_Joshi_Expr_ctorElim___redArg(lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_joshi_Joshi_Expr_ctorElim(lean_object*, lean_object*, lean_object*, lean_object*, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_joshi_Joshi_Expr_ctorElim___boxed(lean_object*, lean_object*, lean_object*, lean_object*, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_joshi_Joshi_Expr_lit_elim___redArg(lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_joshi_Joshi_Expr_lit_elim(lean_object*, lean_object*, lean_object*, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_joshi_Joshi_Expr_lit_elim___boxed(lean_object*, lean_object*, lean_object*, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_joshi_Joshi_Expr_feat_elim___redArg(lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_joshi_Joshi_Expr_feat_elim(lean_object*, lean_object*, lean_object*, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_joshi_Joshi_Expr_feat_elim___boxed(lean_object*, lean_object*, lean_object*, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_joshi_Joshi_Expr_add_elim___redArg(lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_joshi_Joshi_Expr_add_elim(lean_object*, lean_object*, lean_object*, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_joshi_Joshi_Expr_add_elim___boxed(lean_object*, lean_object*, lean_object*, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_joshi_Joshi_Expr_sub_elim___redArg(lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_joshi_Joshi_Expr_sub_elim(lean_object*, lean_object*, lean_object*, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_joshi_Joshi_Expr_sub_elim___boxed(lean_object*, lean_object*, lean_object*, lean_object*, lean_object*);
static const lean_string_object lp_joshi_Joshi_instReprExpr_repr___redArg___closed__0_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 15, .m_capacity = 15, .m_length = 14, .m_data = "Joshi.Expr.lit"};
static const lean_object* lp_joshi_Joshi_instReprExpr_repr___redArg___closed__0 = (const lean_object*)&lp_joshi_Joshi_instReprExpr_repr___redArg___closed__0_value;
static const lean_ctor_object lp_joshi_Joshi_instReprExpr_repr___redArg___closed__1_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*1 + 0, .m_other = 1, .m_tag = 3}, .m_objs = {((lean_object*)&lp_joshi_Joshi_instReprExpr_repr___redArg___closed__0_value)}};
static const lean_object* lp_joshi_Joshi_instReprExpr_repr___redArg___closed__1 = (const lean_object*)&lp_joshi_Joshi_instReprExpr_repr___redArg___closed__1_value;
static const lean_ctor_object lp_joshi_Joshi_instReprExpr_repr___redArg___closed__2_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 5}, .m_objs = {((lean_object*)&lp_joshi_Joshi_instReprExpr_repr___redArg___closed__1_value),((lean_object*)(((size_t)(1) << 1) | 1))}};
static const lean_object* lp_joshi_Joshi_instReprExpr_repr___redArg___closed__2 = (const lean_object*)&lp_joshi_Joshi_instReprExpr_repr___redArg___closed__2_value;
static lean_once_cell_t lp_joshi_Joshi_instReprExpr_repr___redArg___closed__3_once = LEAN_ONCE_CELL_INITIALIZER;
static lean_object* lp_joshi_Joshi_instReprExpr_repr___redArg___closed__3;
static lean_once_cell_t lp_joshi_Joshi_instReprExpr_repr___redArg___closed__4_once = LEAN_ONCE_CELL_INITIALIZER;
static lean_object* lp_joshi_Joshi_instReprExpr_repr___redArg___closed__4;
static const lean_string_object lp_joshi_Joshi_instReprExpr_repr___redArg___closed__5_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 16, .m_capacity = 16, .m_length = 15, .m_data = "Joshi.Expr.feat"};
static const lean_object* lp_joshi_Joshi_instReprExpr_repr___redArg___closed__5 = (const lean_object*)&lp_joshi_Joshi_instReprExpr_repr___redArg___closed__5_value;
static const lean_ctor_object lp_joshi_Joshi_instReprExpr_repr___redArg___closed__6_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*1 + 0, .m_other = 1, .m_tag = 3}, .m_objs = {((lean_object*)&lp_joshi_Joshi_instReprExpr_repr___redArg___closed__5_value)}};
static const lean_object* lp_joshi_Joshi_instReprExpr_repr___redArg___closed__6 = (const lean_object*)&lp_joshi_Joshi_instReprExpr_repr___redArg___closed__6_value;
static const lean_ctor_object lp_joshi_Joshi_instReprExpr_repr___redArg___closed__7_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 5}, .m_objs = {((lean_object*)&lp_joshi_Joshi_instReprExpr_repr___redArg___closed__6_value),((lean_object*)(((size_t)(1) << 1) | 1))}};
static const lean_object* lp_joshi_Joshi_instReprExpr_repr___redArg___closed__7 = (const lean_object*)&lp_joshi_Joshi_instReprExpr_repr___redArg___closed__7_value;
static const lean_string_object lp_joshi_Joshi_instReprExpr_repr___redArg___closed__8_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 15, .m_capacity = 15, .m_length = 14, .m_data = "Joshi.Expr.add"};
static const lean_object* lp_joshi_Joshi_instReprExpr_repr___redArg___closed__8 = (const lean_object*)&lp_joshi_Joshi_instReprExpr_repr___redArg___closed__8_value;
static const lean_ctor_object lp_joshi_Joshi_instReprExpr_repr___redArg___closed__9_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*1 + 0, .m_other = 1, .m_tag = 3}, .m_objs = {((lean_object*)&lp_joshi_Joshi_instReprExpr_repr___redArg___closed__8_value)}};
static const lean_object* lp_joshi_Joshi_instReprExpr_repr___redArg___closed__9 = (const lean_object*)&lp_joshi_Joshi_instReprExpr_repr___redArg___closed__9_value;
static const lean_ctor_object lp_joshi_Joshi_instReprExpr_repr___redArg___closed__10_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 5}, .m_objs = {((lean_object*)&lp_joshi_Joshi_instReprExpr_repr___redArg___closed__9_value),((lean_object*)(((size_t)(1) << 1) | 1))}};
static const lean_object* lp_joshi_Joshi_instReprExpr_repr___redArg___closed__10 = (const lean_object*)&lp_joshi_Joshi_instReprExpr_repr___redArg___closed__10_value;
static const lean_string_object lp_joshi_Joshi_instReprExpr_repr___redArg___closed__11_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 15, .m_capacity = 15, .m_length = 14, .m_data = "Joshi.Expr.sub"};
static const lean_object* lp_joshi_Joshi_instReprExpr_repr___redArg___closed__11 = (const lean_object*)&lp_joshi_Joshi_instReprExpr_repr___redArg___closed__11_value;
static const lean_ctor_object lp_joshi_Joshi_instReprExpr_repr___redArg___closed__12_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*1 + 0, .m_other = 1, .m_tag = 3}, .m_objs = {((lean_object*)&lp_joshi_Joshi_instReprExpr_repr___redArg___closed__11_value)}};
static const lean_object* lp_joshi_Joshi_instReprExpr_repr___redArg___closed__12 = (const lean_object*)&lp_joshi_Joshi_instReprExpr_repr___redArg___closed__12_value;
static const lean_ctor_object lp_joshi_Joshi_instReprExpr_repr___redArg___closed__13_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 5}, .m_objs = {((lean_object*)&lp_joshi_Joshi_instReprExpr_repr___redArg___closed__12_value),((lean_object*)(((size_t)(1) << 1) | 1))}};
static const lean_object* lp_joshi_Joshi_instReprExpr_repr___redArg___closed__13 = (const lean_object*)&lp_joshi_Joshi_instReprExpr_repr___redArg___closed__13_value;
LEAN_EXPORT lean_object* lp_joshi_Joshi_instReprExpr_repr___redArg(lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_joshi_Joshi_instReprExpr_repr___redArg___boxed(lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_joshi_Joshi_instReprExpr_repr(lean_object*, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_joshi_Joshi_instReprExpr_repr___boxed(lean_object*, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_joshi_Joshi_instReprExpr(lean_object*);
LEAN_EXPORT lean_object* lp_joshi_Joshi_Pred_ctorIdx___redArg(lean_object*);
LEAN_EXPORT lean_object* lp_joshi_Joshi_Pred_ctorIdx___redArg___boxed(lean_object*);
LEAN_EXPORT lean_object* lp_joshi_Joshi_Pred_ctorIdx(lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_joshi_Joshi_Pred_ctorIdx___boxed(lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_joshi_Joshi_Pred_ctorElim___redArg(lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_joshi_Joshi_Pred_ctorElim(lean_object*, lean_object*, lean_object*, lean_object*, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_joshi_Joshi_Pred_ctorElim___boxed(lean_object*, lean_object*, lean_object*, lean_object*, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_joshi_Joshi_Pred_le_elim___redArg(lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_joshi_Joshi_Pred_le_elim(lean_object*, lean_object*, lean_object*, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_joshi_Joshi_Pred_le_elim___boxed(lean_object*, lean_object*, lean_object*, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_joshi_Joshi_Pred_and_elim___redArg(lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_joshi_Joshi_Pred_and_elim(lean_object*, lean_object*, lean_object*, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_joshi_Joshi_Pred_and_elim___boxed(lean_object*, lean_object*, lean_object*, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_joshi_Joshi_Pred_neg_elim___redArg(lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_joshi_Joshi_Pred_neg_elim(lean_object*, lean_object*, lean_object*, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_joshi_Joshi_Pred_neg_elim___boxed(lean_object*, lean_object*, lean_object*, lean_object*, lean_object*);
static const lean_string_object lp_joshi_Joshi_instReprPred_repr___redArg___closed__0_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 14, .m_capacity = 14, .m_length = 13, .m_data = "Joshi.Pred.le"};
static const lean_object* lp_joshi_Joshi_instReprPred_repr___redArg___closed__0 = (const lean_object*)&lp_joshi_Joshi_instReprPred_repr___redArg___closed__0_value;
static const lean_ctor_object lp_joshi_Joshi_instReprPred_repr___redArg___closed__1_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*1 + 0, .m_other = 1, .m_tag = 3}, .m_objs = {((lean_object*)&lp_joshi_Joshi_instReprPred_repr___redArg___closed__0_value)}};
static const lean_object* lp_joshi_Joshi_instReprPred_repr___redArg___closed__1 = (const lean_object*)&lp_joshi_Joshi_instReprPred_repr___redArg___closed__1_value;
static const lean_ctor_object lp_joshi_Joshi_instReprPred_repr___redArg___closed__2_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 5}, .m_objs = {((lean_object*)&lp_joshi_Joshi_instReprPred_repr___redArg___closed__1_value),((lean_object*)(((size_t)(1) << 1) | 1))}};
static const lean_object* lp_joshi_Joshi_instReprPred_repr___redArg___closed__2 = (const lean_object*)&lp_joshi_Joshi_instReprPred_repr___redArg___closed__2_value;
static const lean_string_object lp_joshi_Joshi_instReprPred_repr___redArg___closed__3_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 15, .m_capacity = 15, .m_length = 14, .m_data = "Joshi.Pred.and"};
static const lean_object* lp_joshi_Joshi_instReprPred_repr___redArg___closed__3 = (const lean_object*)&lp_joshi_Joshi_instReprPred_repr___redArg___closed__3_value;
static const lean_ctor_object lp_joshi_Joshi_instReprPred_repr___redArg___closed__4_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*1 + 0, .m_other = 1, .m_tag = 3}, .m_objs = {((lean_object*)&lp_joshi_Joshi_instReprPred_repr___redArg___closed__3_value)}};
static const lean_object* lp_joshi_Joshi_instReprPred_repr___redArg___closed__4 = (const lean_object*)&lp_joshi_Joshi_instReprPred_repr___redArg___closed__4_value;
static const lean_ctor_object lp_joshi_Joshi_instReprPred_repr___redArg___closed__5_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 5}, .m_objs = {((lean_object*)&lp_joshi_Joshi_instReprPred_repr___redArg___closed__4_value),((lean_object*)(((size_t)(1) << 1) | 1))}};
static const lean_object* lp_joshi_Joshi_instReprPred_repr___redArg___closed__5 = (const lean_object*)&lp_joshi_Joshi_instReprPred_repr___redArg___closed__5_value;
static const lean_string_object lp_joshi_Joshi_instReprPred_repr___redArg___closed__6_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 15, .m_capacity = 15, .m_length = 14, .m_data = "Joshi.Pred.neg"};
static const lean_object* lp_joshi_Joshi_instReprPred_repr___redArg___closed__6 = (const lean_object*)&lp_joshi_Joshi_instReprPred_repr___redArg___closed__6_value;
static const lean_ctor_object lp_joshi_Joshi_instReprPred_repr___redArg___closed__7_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*1 + 0, .m_other = 1, .m_tag = 3}, .m_objs = {((lean_object*)&lp_joshi_Joshi_instReprPred_repr___redArg___closed__6_value)}};
static const lean_object* lp_joshi_Joshi_instReprPred_repr___redArg___closed__7 = (const lean_object*)&lp_joshi_Joshi_instReprPred_repr___redArg___closed__7_value;
static const lean_ctor_object lp_joshi_Joshi_instReprPred_repr___redArg___closed__8_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 5}, .m_objs = {((lean_object*)&lp_joshi_Joshi_instReprPred_repr___redArg___closed__7_value),((lean_object*)(((size_t)(1) << 1) | 1))}};
static const lean_object* lp_joshi_Joshi_instReprPred_repr___redArg___closed__8 = (const lean_object*)&lp_joshi_Joshi_instReprPred_repr___redArg___closed__8_value;
LEAN_EXPORT lean_object* lp_joshi_Joshi_instReprPred_repr___redArg(lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_joshi_Joshi_instReprPred_repr___redArg___boxed(lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_joshi_Joshi_instReprPred_repr(lean_object*, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_joshi_Joshi_instReprPred_repr___boxed(lean_object*, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_joshi_Joshi_instReprPred(lean_object*);
LEAN_EXPORT lean_object* lp_joshi_Joshi_Expr_eval___redArg(lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_joshi_Joshi_Expr_eval(lean_object*, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_joshi_Joshi_Expr_eval___boxed(lean_object*, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_joshi_Joshi_Expr_depth___redArg(lean_object*);
LEAN_EXPORT lean_object* lp_joshi_Joshi_Expr_depth___redArg___boxed(lean_object*);
LEAN_EXPORT lean_object* lp_joshi_Joshi_Expr_depth(lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_joshi_Joshi_Expr_depth___boxed(lean_object*, lean_object*);
LEAN_EXPORT uint8_t lp_joshi_Joshi_Pred_eval___redArg(lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_joshi_Joshi_Pred_eval___redArg___boxed(lean_object*, lean_object*);
LEAN_EXPORT uint8_t lp_joshi_Joshi_Pred_eval(lean_object*, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_joshi_Joshi_Pred_eval___boxed(lean_object*, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_joshi_Joshi_Pred_depth___redArg(lean_object*);
LEAN_EXPORT lean_object* lp_joshi_Joshi_Pred_depth___redArg___boxed(lean_object*);
LEAN_EXPORT lean_object* lp_joshi_Joshi_Pred_depth(lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_joshi_Joshi_Pred_depth___boxed(lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_joshi_Joshi_exprCount(lean_object*, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_joshi_Joshi_exprCount___boxed(lean_object*, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_joshi_Joshi_predCount(lean_object*, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_joshi_Joshi_predCount___boxed(lean_object*, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_joshi___private_Joshi_Dsl_0__Joshi_exprCount_match__1_splitter___redArg(lean_object*, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_joshi___private_Joshi_Dsl_0__Joshi_exprCount_match__1_splitter___redArg___boxed(lean_object*, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_joshi___private_Joshi_Dsl_0__Joshi_exprCount_match__1_splitter(lean_object*, lean_object*, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_joshi___private_Joshi_Dsl_0__Joshi_exprCount_match__1_splitter___boxed(lean_object*, lean_object*, lean_object*, lean_object*);
LEAN_EXPORT uint8_t lp_joshi_Joshi_Pred_toStrategy___redArg___lam__0(lean_object*, lean_object*, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_joshi_Joshi_Pred_toStrategy___redArg___lam__0___boxed(lean_object*, lean_object*, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_joshi_Joshi_Pred_toStrategy___redArg(lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_joshi_Joshi_Pred_toStrategy(lean_object*, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_joshi_Joshi_Pred_toStrategy___boxed(lean_object*, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_joshi_Joshi_Expr_ctorIdx___redArg(lean_object* v_x_1_){
_start:
{
switch(lean_obj_tag(v_x_1_))
{
case 0:
{
lean_object* v___x_2_; 
v___x_2_ = lean_unsigned_to_nat(0u);
return v___x_2_;
}
case 1:
{
lean_object* v___x_3_; 
v___x_3_ = lean_unsigned_to_nat(1u);
return v___x_3_;
}
case 2:
{
lean_object* v___x_4_; 
v___x_4_ = lean_unsigned_to_nat(2u);
return v___x_4_;
}
default: 
{
lean_object* v___x_5_; 
v___x_5_ = lean_unsigned_to_nat(3u);
return v___x_5_;
}
}
}
}
LEAN_EXPORT lean_object* lp_joshi_Joshi_Expr_ctorIdx___redArg___boxed(lean_object* v_x_6_){
_start:
{
lean_object* v_res_7_; 
v_res_7_ = lp_joshi_Joshi_Expr_ctorIdx___redArg(v_x_6_);
lean_dec_ref(v_x_6_);
return v_res_7_;
}
}
LEAN_EXPORT lean_object* lp_joshi_Joshi_Expr_ctorIdx(lean_object* v_n_8_, lean_object* v_x_9_){
_start:
{
lean_object* v___x_10_; 
v___x_10_ = lp_joshi_Joshi_Expr_ctorIdx___redArg(v_x_9_);
return v___x_10_;
}
}
LEAN_EXPORT lean_object* lp_joshi_Joshi_Expr_ctorIdx___boxed(lean_object* v_n_11_, lean_object* v_x_12_){
_start:
{
lean_object* v_res_13_; 
v_res_13_ = lp_joshi_Joshi_Expr_ctorIdx(v_n_11_, v_x_12_);
lean_dec_ref(v_x_12_);
lean_dec(v_n_11_);
return v_res_13_;
}
}
LEAN_EXPORT lean_object* lp_joshi_Joshi_Expr_ctorElim___redArg(lean_object* v_t_14_, lean_object* v_k_15_){
_start:
{
switch(lean_obj_tag(v_t_14_))
{
case 2:
{
lean_object* v_a_16_; lean_object* v_b_17_; lean_object* v___x_18_; 
v_a_16_ = lean_ctor_get(v_t_14_, 0);
lean_inc_ref(v_a_16_);
v_b_17_ = lean_ctor_get(v_t_14_, 1);
lean_inc_ref(v_b_17_);
lean_dec_ref_known(v_t_14_, 2);
v___x_18_ = lean_apply_2(v_k_15_, v_a_16_, v_b_17_);
return v___x_18_;
}
case 3:
{
lean_object* v_a_19_; lean_object* v_b_20_; lean_object* v___x_21_; 
v_a_19_ = lean_ctor_get(v_t_14_, 0);
lean_inc_ref(v_a_19_);
v_b_20_ = lean_ctor_get(v_t_14_, 1);
lean_inc_ref(v_b_20_);
lean_dec_ref_known(v_t_14_, 2);
v___x_21_ = lean_apply_2(v_k_15_, v_a_19_, v_b_20_);
return v___x_21_;
}
default: 
{
lean_object* v_v_22_; lean_object* v___x_23_; 
v_v_22_ = lean_ctor_get(v_t_14_, 0);
lean_inc(v_v_22_);
lean_dec_ref(v_t_14_);
v___x_23_ = lean_apply_1(v_k_15_, v_v_22_);
return v___x_23_;
}
}
}
}
LEAN_EXPORT lean_object* lp_joshi_Joshi_Expr_ctorElim(lean_object* v_n_24_, lean_object* v_motive_25_, lean_object* v_ctorIdx_26_, lean_object* v_t_27_, lean_object* v_h_28_, lean_object* v_k_29_){
_start:
{
lean_object* v___x_30_; 
v___x_30_ = lp_joshi_Joshi_Expr_ctorElim___redArg(v_t_27_, v_k_29_);
return v___x_30_;
}
}
LEAN_EXPORT lean_object* lp_joshi_Joshi_Expr_ctorElim___boxed(lean_object* v_n_31_, lean_object* v_motive_32_, lean_object* v_ctorIdx_33_, lean_object* v_t_34_, lean_object* v_h_35_, lean_object* v_k_36_){
_start:
{
lean_object* v_res_37_; 
v_res_37_ = lp_joshi_Joshi_Expr_ctorElim(v_n_31_, v_motive_32_, v_ctorIdx_33_, v_t_34_, v_h_35_, v_k_36_);
lean_dec(v_ctorIdx_33_);
lean_dec(v_n_31_);
return v_res_37_;
}
}
LEAN_EXPORT lean_object* lp_joshi_Joshi_Expr_lit_elim___redArg(lean_object* v_t_38_, lean_object* v_lit_39_){
_start:
{
lean_object* v___x_40_; 
v___x_40_ = lp_joshi_Joshi_Expr_ctorElim___redArg(v_t_38_, v_lit_39_);
return v___x_40_;
}
}
LEAN_EXPORT lean_object* lp_joshi_Joshi_Expr_lit_elim(lean_object* v_n_41_, lean_object* v_motive_42_, lean_object* v_t_43_, lean_object* v_h_44_, lean_object* v_lit_45_){
_start:
{
lean_object* v___x_46_; 
v___x_46_ = lp_joshi_Joshi_Expr_ctorElim___redArg(v_t_43_, v_lit_45_);
return v___x_46_;
}
}
LEAN_EXPORT lean_object* lp_joshi_Joshi_Expr_lit_elim___boxed(lean_object* v_n_47_, lean_object* v_motive_48_, lean_object* v_t_49_, lean_object* v_h_50_, lean_object* v_lit_51_){
_start:
{
lean_object* v_res_52_; 
v_res_52_ = lp_joshi_Joshi_Expr_lit_elim(v_n_47_, v_motive_48_, v_t_49_, v_h_50_, v_lit_51_);
lean_dec(v_n_47_);
return v_res_52_;
}
}
LEAN_EXPORT lean_object* lp_joshi_Joshi_Expr_feat_elim___redArg(lean_object* v_t_53_, lean_object* v_feat_54_){
_start:
{
lean_object* v___x_55_; 
v___x_55_ = lp_joshi_Joshi_Expr_ctorElim___redArg(v_t_53_, v_feat_54_);
return v___x_55_;
}
}
LEAN_EXPORT lean_object* lp_joshi_Joshi_Expr_feat_elim(lean_object* v_n_56_, lean_object* v_motive_57_, lean_object* v_t_58_, lean_object* v_h_59_, lean_object* v_feat_60_){
_start:
{
lean_object* v___x_61_; 
v___x_61_ = lp_joshi_Joshi_Expr_ctorElim___redArg(v_t_58_, v_feat_60_);
return v___x_61_;
}
}
LEAN_EXPORT lean_object* lp_joshi_Joshi_Expr_feat_elim___boxed(lean_object* v_n_62_, lean_object* v_motive_63_, lean_object* v_t_64_, lean_object* v_h_65_, lean_object* v_feat_66_){
_start:
{
lean_object* v_res_67_; 
v_res_67_ = lp_joshi_Joshi_Expr_feat_elim(v_n_62_, v_motive_63_, v_t_64_, v_h_65_, v_feat_66_);
lean_dec(v_n_62_);
return v_res_67_;
}
}
LEAN_EXPORT lean_object* lp_joshi_Joshi_Expr_add_elim___redArg(lean_object* v_t_68_, lean_object* v_add_69_){
_start:
{
lean_object* v___x_70_; 
v___x_70_ = lp_joshi_Joshi_Expr_ctorElim___redArg(v_t_68_, v_add_69_);
return v___x_70_;
}
}
LEAN_EXPORT lean_object* lp_joshi_Joshi_Expr_add_elim(lean_object* v_n_71_, lean_object* v_motive_72_, lean_object* v_t_73_, lean_object* v_h_74_, lean_object* v_add_75_){
_start:
{
lean_object* v___x_76_; 
v___x_76_ = lp_joshi_Joshi_Expr_ctorElim___redArg(v_t_73_, v_add_75_);
return v___x_76_;
}
}
LEAN_EXPORT lean_object* lp_joshi_Joshi_Expr_add_elim___boxed(lean_object* v_n_77_, lean_object* v_motive_78_, lean_object* v_t_79_, lean_object* v_h_80_, lean_object* v_add_81_){
_start:
{
lean_object* v_res_82_; 
v_res_82_ = lp_joshi_Joshi_Expr_add_elim(v_n_77_, v_motive_78_, v_t_79_, v_h_80_, v_add_81_);
lean_dec(v_n_77_);
return v_res_82_;
}
}
LEAN_EXPORT lean_object* lp_joshi_Joshi_Expr_sub_elim___redArg(lean_object* v_t_83_, lean_object* v_sub_84_){
_start:
{
lean_object* v___x_85_; 
v___x_85_ = lp_joshi_Joshi_Expr_ctorElim___redArg(v_t_83_, v_sub_84_);
return v___x_85_;
}
}
LEAN_EXPORT lean_object* lp_joshi_Joshi_Expr_sub_elim(lean_object* v_n_86_, lean_object* v_motive_87_, lean_object* v_t_88_, lean_object* v_h_89_, lean_object* v_sub_90_){
_start:
{
lean_object* v___x_91_; 
v___x_91_ = lp_joshi_Joshi_Expr_ctorElim___redArg(v_t_88_, v_sub_90_);
return v___x_91_;
}
}
LEAN_EXPORT lean_object* lp_joshi_Joshi_Expr_sub_elim___boxed(lean_object* v_n_92_, lean_object* v_motive_93_, lean_object* v_t_94_, lean_object* v_h_95_, lean_object* v_sub_96_){
_start:
{
lean_object* v_res_97_; 
v_res_97_ = lp_joshi_Joshi_Expr_sub_elim(v_n_92_, v_motive_93_, v_t_94_, v_h_95_, v_sub_96_);
lean_dec(v_n_92_);
return v_res_97_;
}
}
static lean_object* _init_lp_joshi_Joshi_instReprExpr_repr___redArg___closed__3(void){
_start:
{
lean_object* v___x_104_; lean_object* v___x_105_; 
v___x_104_ = lean_unsigned_to_nat(2u);
v___x_105_ = lean_nat_to_int(v___x_104_);
return v___x_105_;
}
}
static lean_object* _init_lp_joshi_Joshi_instReprExpr_repr___redArg___closed__4(void){
_start:
{
lean_object* v___x_106_; lean_object* v___x_107_; 
v___x_106_ = lean_unsigned_to_nat(1u);
v___x_107_ = lean_nat_to_int(v___x_106_);
return v___x_107_;
}
}
LEAN_EXPORT lean_object* lp_joshi_Joshi_instReprExpr_repr___redArg(lean_object* v_x_126_, lean_object* v_prec_127_){
_start:
{
switch(lean_obj_tag(v_x_126_))
{
case 0:
{
lean_object* v_v_128_; lean_object* v___x_130_; uint8_t v_isShared_131_; uint8_t v_isSharedCheck_148_; 
v_v_128_ = lean_ctor_get(v_x_126_, 0);
v_isSharedCheck_148_ = !lean_is_exclusive(v_x_126_);
if (v_isSharedCheck_148_ == 0)
{
v___x_130_ = v_x_126_;
v_isShared_131_ = v_isSharedCheck_148_;
goto v_resetjp_129_;
}
else
{
lean_inc(v_v_128_);
lean_dec(v_x_126_);
v___x_130_ = lean_box(0);
v_isShared_131_ = v_isSharedCheck_148_;
goto v_resetjp_129_;
}
v_resetjp_129_:
{
lean_object* v___y_133_; lean_object* v___x_144_; uint8_t v___x_145_; 
v___x_144_ = lean_unsigned_to_nat(1024u);
v___x_145_ = lean_nat_dec_le(v___x_144_, v_prec_127_);
if (v___x_145_ == 0)
{
lean_object* v___x_146_; 
v___x_146_ = lean_obj_once(&lp_joshi_Joshi_instReprExpr_repr___redArg___closed__3, &lp_joshi_Joshi_instReprExpr_repr___redArg___closed__3_once, _init_lp_joshi_Joshi_instReprExpr_repr___redArg___closed__3);
v___y_133_ = v___x_146_;
goto v___jp_132_;
}
else
{
lean_object* v___x_147_; 
v___x_147_ = lean_obj_once(&lp_joshi_Joshi_instReprExpr_repr___redArg___closed__4, &lp_joshi_Joshi_instReprExpr_repr___redArg___closed__4_once, _init_lp_joshi_Joshi_instReprExpr_repr___redArg___closed__4);
v___y_133_ = v___x_147_;
goto v___jp_132_;
}
v___jp_132_:
{
lean_object* v___x_134_; lean_object* v___x_135_; lean_object* v___x_137_; 
v___x_134_ = ((lean_object*)(lp_joshi_Joshi_instReprExpr_repr___redArg___closed__2));
v___x_135_ = l_Nat_reprFast(v_v_128_);
if (v_isShared_131_ == 0)
{
lean_ctor_set_tag(v___x_130_, 3);
lean_ctor_set(v___x_130_, 0, v___x_135_);
v___x_137_ = v___x_130_;
goto v_reusejp_136_;
}
else
{
lean_object* v_reuseFailAlloc_143_; 
v_reuseFailAlloc_143_ = lean_alloc_ctor(3, 1, 0);
lean_ctor_set(v_reuseFailAlloc_143_, 0, v___x_135_);
v___x_137_ = v_reuseFailAlloc_143_;
goto v_reusejp_136_;
}
v_reusejp_136_:
{
lean_object* v___x_138_; lean_object* v___x_139_; uint8_t v___x_140_; lean_object* v___x_141_; lean_object* v___x_142_; 
v___x_138_ = lean_alloc_ctor(5, 2, 0);
lean_ctor_set(v___x_138_, 0, v___x_134_);
lean_ctor_set(v___x_138_, 1, v___x_137_);
lean_inc(v___y_133_);
v___x_139_ = lean_alloc_ctor(4, 2, 0);
lean_ctor_set(v___x_139_, 0, v___y_133_);
lean_ctor_set(v___x_139_, 1, v___x_138_);
v___x_140_ = 0;
v___x_141_ = lean_alloc_ctor(6, 1, 1);
lean_ctor_set(v___x_141_, 0, v___x_139_);
lean_ctor_set_uint8(v___x_141_, sizeof(void*)*1, v___x_140_);
v___x_142_ = l_Repr_addAppParen(v___x_141_, v_prec_127_);
return v___x_142_;
}
}
}
}
case 1:
{
lean_object* v_i_149_; lean_object* v___x_151_; uint8_t v_isShared_152_; uint8_t v_isSharedCheck_169_; 
v_i_149_ = lean_ctor_get(v_x_126_, 0);
v_isSharedCheck_169_ = !lean_is_exclusive(v_x_126_);
if (v_isSharedCheck_169_ == 0)
{
v___x_151_ = v_x_126_;
v_isShared_152_ = v_isSharedCheck_169_;
goto v_resetjp_150_;
}
else
{
lean_inc(v_i_149_);
lean_dec(v_x_126_);
v___x_151_ = lean_box(0);
v_isShared_152_ = v_isSharedCheck_169_;
goto v_resetjp_150_;
}
v_resetjp_150_:
{
lean_object* v___y_154_; lean_object* v___x_165_; uint8_t v___x_166_; 
v___x_165_ = lean_unsigned_to_nat(1024u);
v___x_166_ = lean_nat_dec_le(v___x_165_, v_prec_127_);
if (v___x_166_ == 0)
{
lean_object* v___x_167_; 
v___x_167_ = lean_obj_once(&lp_joshi_Joshi_instReprExpr_repr___redArg___closed__3, &lp_joshi_Joshi_instReprExpr_repr___redArg___closed__3_once, _init_lp_joshi_Joshi_instReprExpr_repr___redArg___closed__3);
v___y_154_ = v___x_167_;
goto v___jp_153_;
}
else
{
lean_object* v___x_168_; 
v___x_168_ = lean_obj_once(&lp_joshi_Joshi_instReprExpr_repr___redArg___closed__4, &lp_joshi_Joshi_instReprExpr_repr___redArg___closed__4_once, _init_lp_joshi_Joshi_instReprExpr_repr___redArg___closed__4);
v___y_154_ = v___x_168_;
goto v___jp_153_;
}
v___jp_153_:
{
lean_object* v___x_155_; lean_object* v___x_156_; lean_object* v___x_158_; 
v___x_155_ = ((lean_object*)(lp_joshi_Joshi_instReprExpr_repr___redArg___closed__7));
v___x_156_ = l_Nat_reprFast(v_i_149_);
if (v_isShared_152_ == 0)
{
lean_ctor_set_tag(v___x_151_, 3);
lean_ctor_set(v___x_151_, 0, v___x_156_);
v___x_158_ = v___x_151_;
goto v_reusejp_157_;
}
else
{
lean_object* v_reuseFailAlloc_164_; 
v_reuseFailAlloc_164_ = lean_alloc_ctor(3, 1, 0);
lean_ctor_set(v_reuseFailAlloc_164_, 0, v___x_156_);
v___x_158_ = v_reuseFailAlloc_164_;
goto v_reusejp_157_;
}
v_reusejp_157_:
{
lean_object* v___x_159_; lean_object* v___x_160_; uint8_t v___x_161_; lean_object* v___x_162_; lean_object* v___x_163_; 
v___x_159_ = lean_alloc_ctor(5, 2, 0);
lean_ctor_set(v___x_159_, 0, v___x_155_);
lean_ctor_set(v___x_159_, 1, v___x_158_);
lean_inc(v___y_154_);
v___x_160_ = lean_alloc_ctor(4, 2, 0);
lean_ctor_set(v___x_160_, 0, v___y_154_);
lean_ctor_set(v___x_160_, 1, v___x_159_);
v___x_161_ = 0;
v___x_162_ = lean_alloc_ctor(6, 1, 1);
lean_ctor_set(v___x_162_, 0, v___x_160_);
lean_ctor_set_uint8(v___x_162_, sizeof(void*)*1, v___x_161_);
v___x_163_ = l_Repr_addAppParen(v___x_162_, v_prec_127_);
return v___x_163_;
}
}
}
}
case 2:
{
lean_object* v_a_170_; lean_object* v_b_171_; lean_object* v___x_173_; uint8_t v_isShared_174_; uint8_t v_isSharedCheck_194_; 
v_a_170_ = lean_ctor_get(v_x_126_, 0);
v_b_171_ = lean_ctor_get(v_x_126_, 1);
v_isSharedCheck_194_ = !lean_is_exclusive(v_x_126_);
if (v_isSharedCheck_194_ == 0)
{
v___x_173_ = v_x_126_;
v_isShared_174_ = v_isSharedCheck_194_;
goto v_resetjp_172_;
}
else
{
lean_inc(v_b_171_);
lean_inc(v_a_170_);
lean_dec(v_x_126_);
v___x_173_ = lean_box(0);
v_isShared_174_ = v_isSharedCheck_194_;
goto v_resetjp_172_;
}
v_resetjp_172_:
{
lean_object* v___x_175_; lean_object* v___y_177_; uint8_t v___x_191_; 
v___x_175_ = lean_unsigned_to_nat(1024u);
v___x_191_ = lean_nat_dec_le(v___x_175_, v_prec_127_);
if (v___x_191_ == 0)
{
lean_object* v___x_192_; 
v___x_192_ = lean_obj_once(&lp_joshi_Joshi_instReprExpr_repr___redArg___closed__3, &lp_joshi_Joshi_instReprExpr_repr___redArg___closed__3_once, _init_lp_joshi_Joshi_instReprExpr_repr___redArg___closed__3);
v___y_177_ = v___x_192_;
goto v___jp_176_;
}
else
{
lean_object* v___x_193_; 
v___x_193_ = lean_obj_once(&lp_joshi_Joshi_instReprExpr_repr___redArg___closed__4, &lp_joshi_Joshi_instReprExpr_repr___redArg___closed__4_once, _init_lp_joshi_Joshi_instReprExpr_repr___redArg___closed__4);
v___y_177_ = v___x_193_;
goto v___jp_176_;
}
v___jp_176_:
{
lean_object* v___x_178_; lean_object* v___x_179_; lean_object* v___x_180_; lean_object* v___x_182_; 
v___x_178_ = lean_box(1);
v___x_179_ = ((lean_object*)(lp_joshi_Joshi_instReprExpr_repr___redArg___closed__10));
v___x_180_ = lp_joshi_Joshi_instReprExpr_repr___redArg(v_a_170_, v___x_175_);
if (v_isShared_174_ == 0)
{
lean_ctor_set_tag(v___x_173_, 5);
lean_ctor_set(v___x_173_, 1, v___x_180_);
lean_ctor_set(v___x_173_, 0, v___x_179_);
v___x_182_ = v___x_173_;
goto v_reusejp_181_;
}
else
{
lean_object* v_reuseFailAlloc_190_; 
v_reuseFailAlloc_190_ = lean_alloc_ctor(5, 2, 0);
lean_ctor_set(v_reuseFailAlloc_190_, 0, v___x_179_);
lean_ctor_set(v_reuseFailAlloc_190_, 1, v___x_180_);
v___x_182_ = v_reuseFailAlloc_190_;
goto v_reusejp_181_;
}
v_reusejp_181_:
{
lean_object* v___x_183_; lean_object* v___x_184_; lean_object* v___x_185_; lean_object* v___x_186_; uint8_t v___x_187_; lean_object* v___x_188_; lean_object* v___x_189_; 
v___x_183_ = lean_alloc_ctor(5, 2, 0);
lean_ctor_set(v___x_183_, 0, v___x_182_);
lean_ctor_set(v___x_183_, 1, v___x_178_);
v___x_184_ = lp_joshi_Joshi_instReprExpr_repr___redArg(v_b_171_, v___x_175_);
v___x_185_ = lean_alloc_ctor(5, 2, 0);
lean_ctor_set(v___x_185_, 0, v___x_183_);
lean_ctor_set(v___x_185_, 1, v___x_184_);
lean_inc(v___y_177_);
v___x_186_ = lean_alloc_ctor(4, 2, 0);
lean_ctor_set(v___x_186_, 0, v___y_177_);
lean_ctor_set(v___x_186_, 1, v___x_185_);
v___x_187_ = 0;
v___x_188_ = lean_alloc_ctor(6, 1, 1);
lean_ctor_set(v___x_188_, 0, v___x_186_);
lean_ctor_set_uint8(v___x_188_, sizeof(void*)*1, v___x_187_);
v___x_189_ = l_Repr_addAppParen(v___x_188_, v_prec_127_);
return v___x_189_;
}
}
}
}
default: 
{
lean_object* v_a_195_; lean_object* v_b_196_; lean_object* v___x_198_; uint8_t v_isShared_199_; uint8_t v_isSharedCheck_219_; 
v_a_195_ = lean_ctor_get(v_x_126_, 0);
v_b_196_ = lean_ctor_get(v_x_126_, 1);
v_isSharedCheck_219_ = !lean_is_exclusive(v_x_126_);
if (v_isSharedCheck_219_ == 0)
{
v___x_198_ = v_x_126_;
v_isShared_199_ = v_isSharedCheck_219_;
goto v_resetjp_197_;
}
else
{
lean_inc(v_b_196_);
lean_inc(v_a_195_);
lean_dec(v_x_126_);
v___x_198_ = lean_box(0);
v_isShared_199_ = v_isSharedCheck_219_;
goto v_resetjp_197_;
}
v_resetjp_197_:
{
lean_object* v___x_200_; lean_object* v___y_202_; uint8_t v___x_216_; 
v___x_200_ = lean_unsigned_to_nat(1024u);
v___x_216_ = lean_nat_dec_le(v___x_200_, v_prec_127_);
if (v___x_216_ == 0)
{
lean_object* v___x_217_; 
v___x_217_ = lean_obj_once(&lp_joshi_Joshi_instReprExpr_repr___redArg___closed__3, &lp_joshi_Joshi_instReprExpr_repr___redArg___closed__3_once, _init_lp_joshi_Joshi_instReprExpr_repr___redArg___closed__3);
v___y_202_ = v___x_217_;
goto v___jp_201_;
}
else
{
lean_object* v___x_218_; 
v___x_218_ = lean_obj_once(&lp_joshi_Joshi_instReprExpr_repr___redArg___closed__4, &lp_joshi_Joshi_instReprExpr_repr___redArg___closed__4_once, _init_lp_joshi_Joshi_instReprExpr_repr___redArg___closed__4);
v___y_202_ = v___x_218_;
goto v___jp_201_;
}
v___jp_201_:
{
lean_object* v___x_203_; lean_object* v___x_204_; lean_object* v___x_205_; lean_object* v___x_207_; 
v___x_203_ = lean_box(1);
v___x_204_ = ((lean_object*)(lp_joshi_Joshi_instReprExpr_repr___redArg___closed__13));
v___x_205_ = lp_joshi_Joshi_instReprExpr_repr___redArg(v_a_195_, v___x_200_);
if (v_isShared_199_ == 0)
{
lean_ctor_set_tag(v___x_198_, 5);
lean_ctor_set(v___x_198_, 1, v___x_205_);
lean_ctor_set(v___x_198_, 0, v___x_204_);
v___x_207_ = v___x_198_;
goto v_reusejp_206_;
}
else
{
lean_object* v_reuseFailAlloc_215_; 
v_reuseFailAlloc_215_ = lean_alloc_ctor(5, 2, 0);
lean_ctor_set(v_reuseFailAlloc_215_, 0, v___x_204_);
lean_ctor_set(v_reuseFailAlloc_215_, 1, v___x_205_);
v___x_207_ = v_reuseFailAlloc_215_;
goto v_reusejp_206_;
}
v_reusejp_206_:
{
lean_object* v___x_208_; lean_object* v___x_209_; lean_object* v___x_210_; lean_object* v___x_211_; uint8_t v___x_212_; lean_object* v___x_213_; lean_object* v___x_214_; 
v___x_208_ = lean_alloc_ctor(5, 2, 0);
lean_ctor_set(v___x_208_, 0, v___x_207_);
lean_ctor_set(v___x_208_, 1, v___x_203_);
v___x_209_ = lp_joshi_Joshi_instReprExpr_repr___redArg(v_b_196_, v___x_200_);
v___x_210_ = lean_alloc_ctor(5, 2, 0);
lean_ctor_set(v___x_210_, 0, v___x_208_);
lean_ctor_set(v___x_210_, 1, v___x_209_);
lean_inc(v___y_202_);
v___x_211_ = lean_alloc_ctor(4, 2, 0);
lean_ctor_set(v___x_211_, 0, v___y_202_);
lean_ctor_set(v___x_211_, 1, v___x_210_);
v___x_212_ = 0;
v___x_213_ = lean_alloc_ctor(6, 1, 1);
lean_ctor_set(v___x_213_, 0, v___x_211_);
lean_ctor_set_uint8(v___x_213_, sizeof(void*)*1, v___x_212_);
v___x_214_ = l_Repr_addAppParen(v___x_213_, v_prec_127_);
return v___x_214_;
}
}
}
}
}
}
}
LEAN_EXPORT lean_object* lp_joshi_Joshi_instReprExpr_repr___redArg___boxed(lean_object* v_x_220_, lean_object* v_prec_221_){
_start:
{
lean_object* v_res_222_; 
v_res_222_ = lp_joshi_Joshi_instReprExpr_repr___redArg(v_x_220_, v_prec_221_);
lean_dec(v_prec_221_);
return v_res_222_;
}
}
LEAN_EXPORT lean_object* lp_joshi_Joshi_instReprExpr_repr(lean_object* v_n_223_, lean_object* v_x_224_, lean_object* v_prec_225_){
_start:
{
lean_object* v___x_226_; 
v___x_226_ = lp_joshi_Joshi_instReprExpr_repr___redArg(v_x_224_, v_prec_225_);
return v___x_226_;
}
}
LEAN_EXPORT lean_object* lp_joshi_Joshi_instReprExpr_repr___boxed(lean_object* v_n_227_, lean_object* v_x_228_, lean_object* v_prec_229_){
_start:
{
lean_object* v_res_230_; 
v_res_230_ = lp_joshi_Joshi_instReprExpr_repr(v_n_227_, v_x_228_, v_prec_229_);
lean_dec(v_prec_229_);
lean_dec(v_n_227_);
return v_res_230_;
}
}
LEAN_EXPORT lean_object* lp_joshi_Joshi_instReprExpr(lean_object* v_n_231_){
_start:
{
lean_object* v___x_232_; 
v___x_232_ = lean_alloc_closure((void*)(lp_joshi_Joshi_instReprExpr_repr___boxed), 3, 1);
lean_closure_set(v___x_232_, 0, v_n_231_);
return v___x_232_;
}
}
LEAN_EXPORT lean_object* lp_joshi_Joshi_Pred_ctorIdx___redArg(lean_object* v_x_233_){
_start:
{
switch(lean_obj_tag(v_x_233_))
{
case 0:
{
lean_object* v___x_234_; 
v___x_234_ = lean_unsigned_to_nat(0u);
return v___x_234_;
}
case 1:
{
lean_object* v___x_235_; 
v___x_235_ = lean_unsigned_to_nat(1u);
return v___x_235_;
}
default: 
{
lean_object* v___x_236_; 
v___x_236_ = lean_unsigned_to_nat(2u);
return v___x_236_;
}
}
}
}
LEAN_EXPORT lean_object* lp_joshi_Joshi_Pred_ctorIdx___redArg___boxed(lean_object* v_x_237_){
_start:
{
lean_object* v_res_238_; 
v_res_238_ = lp_joshi_Joshi_Pred_ctorIdx___redArg(v_x_237_);
lean_dec_ref(v_x_237_);
return v_res_238_;
}
}
LEAN_EXPORT lean_object* lp_joshi_Joshi_Pred_ctorIdx(lean_object* v_n_239_, lean_object* v_x_240_){
_start:
{
lean_object* v___x_241_; 
v___x_241_ = lp_joshi_Joshi_Pred_ctorIdx___redArg(v_x_240_);
return v___x_241_;
}
}
LEAN_EXPORT lean_object* lp_joshi_Joshi_Pred_ctorIdx___boxed(lean_object* v_n_242_, lean_object* v_x_243_){
_start:
{
lean_object* v_res_244_; 
v_res_244_ = lp_joshi_Joshi_Pred_ctorIdx(v_n_242_, v_x_243_);
lean_dec_ref(v_x_243_);
lean_dec(v_n_242_);
return v_res_244_;
}
}
LEAN_EXPORT lean_object* lp_joshi_Joshi_Pred_ctorElim___redArg(lean_object* v_t_245_, lean_object* v_k_246_){
_start:
{
if (lean_obj_tag(v_t_245_) == 2)
{
lean_object* v_a_247_; lean_object* v___x_248_; 
v_a_247_ = lean_ctor_get(v_t_245_, 0);
lean_inc_ref(v_a_247_);
lean_dec_ref_known(v_t_245_, 1);
v___x_248_ = lean_apply_1(v_k_246_, v_a_247_);
return v___x_248_;
}
else
{
lean_object* v_a_249_; lean_object* v_b_250_; lean_object* v___x_251_; 
v_a_249_ = lean_ctor_get(v_t_245_, 0);
lean_inc_ref(v_a_249_);
v_b_250_ = lean_ctor_get(v_t_245_, 1);
lean_inc_ref(v_b_250_);
lean_dec_ref(v_t_245_);
v___x_251_ = lean_apply_2(v_k_246_, v_a_249_, v_b_250_);
return v___x_251_;
}
}
}
LEAN_EXPORT lean_object* lp_joshi_Joshi_Pred_ctorElim(lean_object* v_n_252_, lean_object* v_motive_253_, lean_object* v_ctorIdx_254_, lean_object* v_t_255_, lean_object* v_h_256_, lean_object* v_k_257_){
_start:
{
lean_object* v___x_258_; 
v___x_258_ = lp_joshi_Joshi_Pred_ctorElim___redArg(v_t_255_, v_k_257_);
return v___x_258_;
}
}
LEAN_EXPORT lean_object* lp_joshi_Joshi_Pred_ctorElim___boxed(lean_object* v_n_259_, lean_object* v_motive_260_, lean_object* v_ctorIdx_261_, lean_object* v_t_262_, lean_object* v_h_263_, lean_object* v_k_264_){
_start:
{
lean_object* v_res_265_; 
v_res_265_ = lp_joshi_Joshi_Pred_ctorElim(v_n_259_, v_motive_260_, v_ctorIdx_261_, v_t_262_, v_h_263_, v_k_264_);
lean_dec(v_ctorIdx_261_);
lean_dec(v_n_259_);
return v_res_265_;
}
}
LEAN_EXPORT lean_object* lp_joshi_Joshi_Pred_le_elim___redArg(lean_object* v_t_266_, lean_object* v_le_267_){
_start:
{
lean_object* v___x_268_; 
v___x_268_ = lp_joshi_Joshi_Pred_ctorElim___redArg(v_t_266_, v_le_267_);
return v___x_268_;
}
}
LEAN_EXPORT lean_object* lp_joshi_Joshi_Pred_le_elim(lean_object* v_n_269_, lean_object* v_motive_270_, lean_object* v_t_271_, lean_object* v_h_272_, lean_object* v_le_273_){
_start:
{
lean_object* v___x_274_; 
v___x_274_ = lp_joshi_Joshi_Pred_ctorElim___redArg(v_t_271_, v_le_273_);
return v___x_274_;
}
}
LEAN_EXPORT lean_object* lp_joshi_Joshi_Pred_le_elim___boxed(lean_object* v_n_275_, lean_object* v_motive_276_, lean_object* v_t_277_, lean_object* v_h_278_, lean_object* v_le_279_){
_start:
{
lean_object* v_res_280_; 
v_res_280_ = lp_joshi_Joshi_Pred_le_elim(v_n_275_, v_motive_276_, v_t_277_, v_h_278_, v_le_279_);
lean_dec(v_n_275_);
return v_res_280_;
}
}
LEAN_EXPORT lean_object* lp_joshi_Joshi_Pred_and_elim___redArg(lean_object* v_t_281_, lean_object* v_and_282_){
_start:
{
lean_object* v___x_283_; 
v___x_283_ = lp_joshi_Joshi_Pred_ctorElim___redArg(v_t_281_, v_and_282_);
return v___x_283_;
}
}
LEAN_EXPORT lean_object* lp_joshi_Joshi_Pred_and_elim(lean_object* v_n_284_, lean_object* v_motive_285_, lean_object* v_t_286_, lean_object* v_h_287_, lean_object* v_and_288_){
_start:
{
lean_object* v___x_289_; 
v___x_289_ = lp_joshi_Joshi_Pred_ctorElim___redArg(v_t_286_, v_and_288_);
return v___x_289_;
}
}
LEAN_EXPORT lean_object* lp_joshi_Joshi_Pred_and_elim___boxed(lean_object* v_n_290_, lean_object* v_motive_291_, lean_object* v_t_292_, lean_object* v_h_293_, lean_object* v_and_294_){
_start:
{
lean_object* v_res_295_; 
v_res_295_ = lp_joshi_Joshi_Pred_and_elim(v_n_290_, v_motive_291_, v_t_292_, v_h_293_, v_and_294_);
lean_dec(v_n_290_);
return v_res_295_;
}
}
LEAN_EXPORT lean_object* lp_joshi_Joshi_Pred_neg_elim___redArg(lean_object* v_t_296_, lean_object* v_neg_297_){
_start:
{
lean_object* v___x_298_; 
v___x_298_ = lp_joshi_Joshi_Pred_ctorElim___redArg(v_t_296_, v_neg_297_);
return v___x_298_;
}
}
LEAN_EXPORT lean_object* lp_joshi_Joshi_Pred_neg_elim(lean_object* v_n_299_, lean_object* v_motive_300_, lean_object* v_t_301_, lean_object* v_h_302_, lean_object* v_neg_303_){
_start:
{
lean_object* v___x_304_; 
v___x_304_ = lp_joshi_Joshi_Pred_ctorElim___redArg(v_t_301_, v_neg_303_);
return v___x_304_;
}
}
LEAN_EXPORT lean_object* lp_joshi_Joshi_Pred_neg_elim___boxed(lean_object* v_n_305_, lean_object* v_motive_306_, lean_object* v_t_307_, lean_object* v_h_308_, lean_object* v_neg_309_){
_start:
{
lean_object* v_res_310_; 
v_res_310_ = lp_joshi_Joshi_Pred_neg_elim(v_n_305_, v_motive_306_, v_t_307_, v_h_308_, v_neg_309_);
lean_dec(v_n_305_);
return v_res_310_;
}
}
LEAN_EXPORT lean_object* lp_joshi_Joshi_instReprPred_repr___redArg(lean_object* v_x_329_, lean_object* v_prec_330_){
_start:
{
switch(lean_obj_tag(v_x_329_))
{
case 0:
{
lean_object* v_a_331_; lean_object* v_b_332_; lean_object* v___x_334_; uint8_t v_isShared_335_; uint8_t v_isSharedCheck_356_; 
v_a_331_ = lean_ctor_get(v_x_329_, 0);
v_b_332_ = lean_ctor_get(v_x_329_, 1);
v_isSharedCheck_356_ = !lean_is_exclusive(v_x_329_);
if (v_isSharedCheck_356_ == 0)
{
v___x_334_ = v_x_329_;
v_isShared_335_ = v_isSharedCheck_356_;
goto v_resetjp_333_;
}
else
{
lean_inc(v_b_332_);
lean_inc(v_a_331_);
lean_dec(v_x_329_);
v___x_334_ = lean_box(0);
v_isShared_335_ = v_isSharedCheck_356_;
goto v_resetjp_333_;
}
v_resetjp_333_:
{
lean_object* v___y_337_; lean_object* v___x_352_; uint8_t v___x_353_; 
v___x_352_ = lean_unsigned_to_nat(1024u);
v___x_353_ = lean_nat_dec_le(v___x_352_, v_prec_330_);
if (v___x_353_ == 0)
{
lean_object* v___x_354_; 
v___x_354_ = lean_obj_once(&lp_joshi_Joshi_instReprExpr_repr___redArg___closed__3, &lp_joshi_Joshi_instReprExpr_repr___redArg___closed__3_once, _init_lp_joshi_Joshi_instReprExpr_repr___redArg___closed__3);
v___y_337_ = v___x_354_;
goto v___jp_336_;
}
else
{
lean_object* v___x_355_; 
v___x_355_ = lean_obj_once(&lp_joshi_Joshi_instReprExpr_repr___redArg___closed__4, &lp_joshi_Joshi_instReprExpr_repr___redArg___closed__4_once, _init_lp_joshi_Joshi_instReprExpr_repr___redArg___closed__4);
v___y_337_ = v___x_355_;
goto v___jp_336_;
}
v___jp_336_:
{
lean_object* v___x_338_; lean_object* v___x_339_; lean_object* v___x_340_; lean_object* v___x_341_; lean_object* v___x_343_; 
v___x_338_ = lean_box(1);
v___x_339_ = ((lean_object*)(lp_joshi_Joshi_instReprPred_repr___redArg___closed__2));
v___x_340_ = lean_unsigned_to_nat(1024u);
v___x_341_ = lp_joshi_Joshi_instReprExpr_repr___redArg(v_a_331_, v___x_340_);
if (v_isShared_335_ == 0)
{
lean_ctor_set_tag(v___x_334_, 5);
lean_ctor_set(v___x_334_, 1, v___x_341_);
lean_ctor_set(v___x_334_, 0, v___x_339_);
v___x_343_ = v___x_334_;
goto v_reusejp_342_;
}
else
{
lean_object* v_reuseFailAlloc_351_; 
v_reuseFailAlloc_351_ = lean_alloc_ctor(5, 2, 0);
lean_ctor_set(v_reuseFailAlloc_351_, 0, v___x_339_);
lean_ctor_set(v_reuseFailAlloc_351_, 1, v___x_341_);
v___x_343_ = v_reuseFailAlloc_351_;
goto v_reusejp_342_;
}
v_reusejp_342_:
{
lean_object* v___x_344_; lean_object* v___x_345_; lean_object* v___x_346_; lean_object* v___x_347_; uint8_t v___x_348_; lean_object* v___x_349_; lean_object* v___x_350_; 
v___x_344_ = lean_alloc_ctor(5, 2, 0);
lean_ctor_set(v___x_344_, 0, v___x_343_);
lean_ctor_set(v___x_344_, 1, v___x_338_);
v___x_345_ = lp_joshi_Joshi_instReprExpr_repr___redArg(v_b_332_, v___x_340_);
v___x_346_ = lean_alloc_ctor(5, 2, 0);
lean_ctor_set(v___x_346_, 0, v___x_344_);
lean_ctor_set(v___x_346_, 1, v___x_345_);
lean_inc(v___y_337_);
v___x_347_ = lean_alloc_ctor(4, 2, 0);
lean_ctor_set(v___x_347_, 0, v___y_337_);
lean_ctor_set(v___x_347_, 1, v___x_346_);
v___x_348_ = 0;
v___x_349_ = lean_alloc_ctor(6, 1, 1);
lean_ctor_set(v___x_349_, 0, v___x_347_);
lean_ctor_set_uint8(v___x_349_, sizeof(void*)*1, v___x_348_);
v___x_350_ = l_Repr_addAppParen(v___x_349_, v_prec_330_);
return v___x_350_;
}
}
}
}
case 1:
{
lean_object* v_a_357_; lean_object* v_b_358_; lean_object* v___x_360_; uint8_t v_isShared_361_; uint8_t v_isSharedCheck_381_; 
v_a_357_ = lean_ctor_get(v_x_329_, 0);
v_b_358_ = lean_ctor_get(v_x_329_, 1);
v_isSharedCheck_381_ = !lean_is_exclusive(v_x_329_);
if (v_isSharedCheck_381_ == 0)
{
v___x_360_ = v_x_329_;
v_isShared_361_ = v_isSharedCheck_381_;
goto v_resetjp_359_;
}
else
{
lean_inc(v_b_358_);
lean_inc(v_a_357_);
lean_dec(v_x_329_);
v___x_360_ = lean_box(0);
v_isShared_361_ = v_isSharedCheck_381_;
goto v_resetjp_359_;
}
v_resetjp_359_:
{
lean_object* v___x_362_; lean_object* v___y_364_; uint8_t v___x_378_; 
v___x_362_ = lean_unsigned_to_nat(1024u);
v___x_378_ = lean_nat_dec_le(v___x_362_, v_prec_330_);
if (v___x_378_ == 0)
{
lean_object* v___x_379_; 
v___x_379_ = lean_obj_once(&lp_joshi_Joshi_instReprExpr_repr___redArg___closed__3, &lp_joshi_Joshi_instReprExpr_repr___redArg___closed__3_once, _init_lp_joshi_Joshi_instReprExpr_repr___redArg___closed__3);
v___y_364_ = v___x_379_;
goto v___jp_363_;
}
else
{
lean_object* v___x_380_; 
v___x_380_ = lean_obj_once(&lp_joshi_Joshi_instReprExpr_repr___redArg___closed__4, &lp_joshi_Joshi_instReprExpr_repr___redArg___closed__4_once, _init_lp_joshi_Joshi_instReprExpr_repr___redArg___closed__4);
v___y_364_ = v___x_380_;
goto v___jp_363_;
}
v___jp_363_:
{
lean_object* v___x_365_; lean_object* v___x_366_; lean_object* v___x_367_; lean_object* v___x_369_; 
v___x_365_ = lean_box(1);
v___x_366_ = ((lean_object*)(lp_joshi_Joshi_instReprPred_repr___redArg___closed__5));
v___x_367_ = lp_joshi_Joshi_instReprPred_repr___redArg(v_a_357_, v___x_362_);
if (v_isShared_361_ == 0)
{
lean_ctor_set_tag(v___x_360_, 5);
lean_ctor_set(v___x_360_, 1, v___x_367_);
lean_ctor_set(v___x_360_, 0, v___x_366_);
v___x_369_ = v___x_360_;
goto v_reusejp_368_;
}
else
{
lean_object* v_reuseFailAlloc_377_; 
v_reuseFailAlloc_377_ = lean_alloc_ctor(5, 2, 0);
lean_ctor_set(v_reuseFailAlloc_377_, 0, v___x_366_);
lean_ctor_set(v_reuseFailAlloc_377_, 1, v___x_367_);
v___x_369_ = v_reuseFailAlloc_377_;
goto v_reusejp_368_;
}
v_reusejp_368_:
{
lean_object* v___x_370_; lean_object* v___x_371_; lean_object* v___x_372_; lean_object* v___x_373_; uint8_t v___x_374_; lean_object* v___x_375_; lean_object* v___x_376_; 
v___x_370_ = lean_alloc_ctor(5, 2, 0);
lean_ctor_set(v___x_370_, 0, v___x_369_);
lean_ctor_set(v___x_370_, 1, v___x_365_);
v___x_371_ = lp_joshi_Joshi_instReprPred_repr___redArg(v_b_358_, v___x_362_);
v___x_372_ = lean_alloc_ctor(5, 2, 0);
lean_ctor_set(v___x_372_, 0, v___x_370_);
lean_ctor_set(v___x_372_, 1, v___x_371_);
lean_inc(v___y_364_);
v___x_373_ = lean_alloc_ctor(4, 2, 0);
lean_ctor_set(v___x_373_, 0, v___y_364_);
lean_ctor_set(v___x_373_, 1, v___x_372_);
v___x_374_ = 0;
v___x_375_ = lean_alloc_ctor(6, 1, 1);
lean_ctor_set(v___x_375_, 0, v___x_373_);
lean_ctor_set_uint8(v___x_375_, sizeof(void*)*1, v___x_374_);
v___x_376_ = l_Repr_addAppParen(v___x_375_, v_prec_330_);
return v___x_376_;
}
}
}
}
default: 
{
lean_object* v_a_382_; lean_object* v___x_383_; lean_object* v___y_385_; uint8_t v___x_393_; 
v_a_382_ = lean_ctor_get(v_x_329_, 0);
lean_inc_ref(v_a_382_);
lean_dec_ref_known(v_x_329_, 1);
v___x_383_ = lean_unsigned_to_nat(1024u);
v___x_393_ = lean_nat_dec_le(v___x_383_, v_prec_330_);
if (v___x_393_ == 0)
{
lean_object* v___x_394_; 
v___x_394_ = lean_obj_once(&lp_joshi_Joshi_instReprExpr_repr___redArg___closed__3, &lp_joshi_Joshi_instReprExpr_repr___redArg___closed__3_once, _init_lp_joshi_Joshi_instReprExpr_repr___redArg___closed__3);
v___y_385_ = v___x_394_;
goto v___jp_384_;
}
else
{
lean_object* v___x_395_; 
v___x_395_ = lean_obj_once(&lp_joshi_Joshi_instReprExpr_repr___redArg___closed__4, &lp_joshi_Joshi_instReprExpr_repr___redArg___closed__4_once, _init_lp_joshi_Joshi_instReprExpr_repr___redArg___closed__4);
v___y_385_ = v___x_395_;
goto v___jp_384_;
}
v___jp_384_:
{
lean_object* v___x_386_; lean_object* v___x_387_; lean_object* v___x_388_; lean_object* v___x_389_; uint8_t v___x_390_; lean_object* v___x_391_; lean_object* v___x_392_; 
v___x_386_ = ((lean_object*)(lp_joshi_Joshi_instReprPred_repr___redArg___closed__8));
v___x_387_ = lp_joshi_Joshi_instReprPred_repr___redArg(v_a_382_, v___x_383_);
v___x_388_ = lean_alloc_ctor(5, 2, 0);
lean_ctor_set(v___x_388_, 0, v___x_386_);
lean_ctor_set(v___x_388_, 1, v___x_387_);
lean_inc(v___y_385_);
v___x_389_ = lean_alloc_ctor(4, 2, 0);
lean_ctor_set(v___x_389_, 0, v___y_385_);
lean_ctor_set(v___x_389_, 1, v___x_388_);
v___x_390_ = 0;
v___x_391_ = lean_alloc_ctor(6, 1, 1);
lean_ctor_set(v___x_391_, 0, v___x_389_);
lean_ctor_set_uint8(v___x_391_, sizeof(void*)*1, v___x_390_);
v___x_392_ = l_Repr_addAppParen(v___x_391_, v_prec_330_);
return v___x_392_;
}
}
}
}
}
LEAN_EXPORT lean_object* lp_joshi_Joshi_instReprPred_repr___redArg___boxed(lean_object* v_x_396_, lean_object* v_prec_397_){
_start:
{
lean_object* v_res_398_; 
v_res_398_ = lp_joshi_Joshi_instReprPred_repr___redArg(v_x_396_, v_prec_397_);
lean_dec(v_prec_397_);
return v_res_398_;
}
}
LEAN_EXPORT lean_object* lp_joshi_Joshi_instReprPred_repr(lean_object* v_n_399_, lean_object* v_x_400_, lean_object* v_prec_401_){
_start:
{
lean_object* v___x_402_; 
v___x_402_ = lp_joshi_Joshi_instReprPred_repr___redArg(v_x_400_, v_prec_401_);
return v___x_402_;
}
}
LEAN_EXPORT lean_object* lp_joshi_Joshi_instReprPred_repr___boxed(lean_object* v_n_403_, lean_object* v_x_404_, lean_object* v_prec_405_){
_start:
{
lean_object* v_res_406_; 
v_res_406_ = lp_joshi_Joshi_instReprPred_repr(v_n_403_, v_x_404_, v_prec_405_);
lean_dec(v_prec_405_);
lean_dec(v_n_403_);
return v_res_406_;
}
}
LEAN_EXPORT lean_object* lp_joshi_Joshi_instReprPred(lean_object* v_n_407_){
_start:
{
lean_object* v___x_408_; 
v___x_408_ = lean_alloc_closure((void*)(lp_joshi_Joshi_instReprPred_repr___boxed), 3, 1);
lean_closure_set(v___x_408_, 0, v_n_407_);
return v___x_408_;
}
}
LEAN_EXPORT lean_object* lp_joshi_Joshi_Expr_eval___redArg(lean_object* v_00_u03c6_409_, lean_object* v_x_410_){
_start:
{
switch(lean_obj_tag(v_x_410_))
{
case 0:
{
lean_object* v_v_411_; 
lean_dec_ref(v_00_u03c6_409_);
v_v_411_ = lean_ctor_get(v_x_410_, 0);
lean_inc(v_v_411_);
lean_dec_ref_known(v_x_410_, 1);
return v_v_411_;
}
case 1:
{
lean_object* v_i_412_; lean_object* v___x_413_; 
v_i_412_ = lean_ctor_get(v_x_410_, 0);
lean_inc(v_i_412_);
lean_dec_ref_known(v_x_410_, 1);
v___x_413_ = lean_apply_1(v_00_u03c6_409_, v_i_412_);
return v___x_413_;
}
case 2:
{
lean_object* v_a_414_; lean_object* v_b_415_; lean_object* v___x_416_; lean_object* v___x_417_; lean_object* v___x_418_; 
v_a_414_ = lean_ctor_get(v_x_410_, 0);
lean_inc_ref(v_a_414_);
v_b_415_ = lean_ctor_get(v_x_410_, 1);
lean_inc_ref(v_b_415_);
lean_dec_ref_known(v_x_410_, 2);
lean_inc_ref(v_00_u03c6_409_);
v___x_416_ = lp_joshi_Joshi_Expr_eval___redArg(v_00_u03c6_409_, v_a_414_);
v___x_417_ = lp_joshi_Joshi_Expr_eval___redArg(v_00_u03c6_409_, v_b_415_);
v___x_418_ = lean_nat_add(v___x_416_, v___x_417_);
lean_dec(v___x_417_);
lean_dec(v___x_416_);
return v___x_418_;
}
default: 
{
lean_object* v_a_419_; lean_object* v_b_420_; lean_object* v___x_421_; lean_object* v___x_422_; lean_object* v___x_423_; 
v_a_419_ = lean_ctor_get(v_x_410_, 0);
lean_inc_ref(v_a_419_);
v_b_420_ = lean_ctor_get(v_x_410_, 1);
lean_inc_ref(v_b_420_);
lean_dec_ref_known(v_x_410_, 2);
lean_inc_ref(v_00_u03c6_409_);
v___x_421_ = lp_joshi_Joshi_Expr_eval___redArg(v_00_u03c6_409_, v_a_419_);
v___x_422_ = lp_joshi_Joshi_Expr_eval___redArg(v_00_u03c6_409_, v_b_420_);
v___x_423_ = lean_nat_sub(v___x_421_, v___x_422_);
lean_dec(v___x_422_);
lean_dec(v___x_421_);
return v___x_423_;
}
}
}
}
LEAN_EXPORT lean_object* lp_joshi_Joshi_Expr_eval(lean_object* v_n_424_, lean_object* v_00_u03c6_425_, lean_object* v_x_426_){
_start:
{
lean_object* v___x_427_; 
v___x_427_ = lp_joshi_Joshi_Expr_eval___redArg(v_00_u03c6_425_, v_x_426_);
return v___x_427_;
}
}
LEAN_EXPORT lean_object* lp_joshi_Joshi_Expr_eval___boxed(lean_object* v_n_428_, lean_object* v_00_u03c6_429_, lean_object* v_x_430_){
_start:
{
lean_object* v_res_431_; 
v_res_431_ = lp_joshi_Joshi_Expr_eval(v_n_428_, v_00_u03c6_429_, v_x_430_);
lean_dec(v_n_428_);
return v_res_431_;
}
}
LEAN_EXPORT lean_object* lp_joshi_Joshi_Expr_depth___redArg(lean_object* v_x_432_){
_start:
{
lean_object* v_a_434_; lean_object* v_b_435_; 
switch(lean_obj_tag(v_x_432_))
{
case 2:
{
lean_object* v_a_442_; lean_object* v_b_443_; 
v_a_442_ = lean_ctor_get(v_x_432_, 0);
v_b_443_ = lean_ctor_get(v_x_432_, 1);
v_a_434_ = v_a_442_;
v_b_435_ = v_b_443_;
goto v___jp_433_;
}
case 3:
{
lean_object* v_a_444_; lean_object* v_b_445_; 
v_a_444_ = lean_ctor_get(v_x_432_, 0);
v_b_445_ = lean_ctor_get(v_x_432_, 1);
v_a_434_ = v_a_444_;
v_b_435_ = v_b_445_;
goto v___jp_433_;
}
default: 
{
lean_object* v___x_446_; 
v___x_446_ = lean_unsigned_to_nat(0u);
return v___x_446_;
}
}
v___jp_433_:
{
lean_object* v___x_436_; lean_object* v___x_437_; lean_object* v___x_438_; uint8_t v___x_439_; 
v___x_436_ = lean_unsigned_to_nat(1u);
v___x_437_ = lp_joshi_Joshi_Expr_depth___redArg(v_a_434_);
v___x_438_ = lp_joshi_Joshi_Expr_depth___redArg(v_b_435_);
v___x_439_ = lean_nat_dec_le(v___x_437_, v___x_438_);
if (v___x_439_ == 0)
{
lean_object* v___x_440_; 
lean_dec(v___x_438_);
v___x_440_ = lean_nat_add(v___x_436_, v___x_437_);
lean_dec(v___x_437_);
return v___x_440_;
}
else
{
lean_object* v___x_441_; 
lean_dec(v___x_437_);
v___x_441_ = lean_nat_add(v___x_436_, v___x_438_);
lean_dec(v___x_438_);
return v___x_441_;
}
}
}
}
LEAN_EXPORT lean_object* lp_joshi_Joshi_Expr_depth___redArg___boxed(lean_object* v_x_447_){
_start:
{
lean_object* v_res_448_; 
v_res_448_ = lp_joshi_Joshi_Expr_depth___redArg(v_x_447_);
lean_dec_ref(v_x_447_);
return v_res_448_;
}
}
LEAN_EXPORT lean_object* lp_joshi_Joshi_Expr_depth(lean_object* v_n_449_, lean_object* v_x_450_){
_start:
{
lean_object* v___x_451_; 
v___x_451_ = lp_joshi_Joshi_Expr_depth___redArg(v_x_450_);
return v___x_451_;
}
}
LEAN_EXPORT lean_object* lp_joshi_Joshi_Expr_depth___boxed(lean_object* v_n_452_, lean_object* v_x_453_){
_start:
{
lean_object* v_res_454_; 
v_res_454_ = lp_joshi_Joshi_Expr_depth(v_n_452_, v_x_453_);
lean_dec_ref(v_x_453_);
lean_dec(v_n_452_);
return v_res_454_;
}
}
LEAN_EXPORT uint8_t lp_joshi_Joshi_Pred_eval___redArg(lean_object* v_00_u03c6_455_, lean_object* v_x_456_){
_start:
{
switch(lean_obj_tag(v_x_456_))
{
case 0:
{
lean_object* v_a_457_; lean_object* v_b_458_; lean_object* v___x_459_; lean_object* v___x_460_; uint8_t v___x_461_; 
v_a_457_ = lean_ctor_get(v_x_456_, 0);
lean_inc_ref(v_a_457_);
v_b_458_ = lean_ctor_get(v_x_456_, 1);
lean_inc_ref(v_b_458_);
lean_dec_ref_known(v_x_456_, 2);
lean_inc_ref(v_00_u03c6_455_);
v___x_459_ = lp_joshi_Joshi_Expr_eval___redArg(v_00_u03c6_455_, v_a_457_);
v___x_460_ = lp_joshi_Joshi_Expr_eval___redArg(v_00_u03c6_455_, v_b_458_);
v___x_461_ = lean_nat_dec_le(v___x_459_, v___x_460_);
lean_dec(v___x_460_);
lean_dec(v___x_459_);
return v___x_461_;
}
case 1:
{
lean_object* v_a_462_; lean_object* v_b_463_; uint8_t v___x_464_; 
v_a_462_ = lean_ctor_get(v_x_456_, 0);
lean_inc_ref(v_a_462_);
v_b_463_ = lean_ctor_get(v_x_456_, 1);
lean_inc_ref(v_b_463_);
lean_dec_ref_known(v_x_456_, 2);
lean_inc_ref(v_00_u03c6_455_);
v___x_464_ = lp_joshi_Joshi_Pred_eval___redArg(v_00_u03c6_455_, v_a_462_);
if (v___x_464_ == 0)
{
lean_dec_ref(v_b_463_);
lean_dec_ref(v_00_u03c6_455_);
return v___x_464_;
}
else
{
v_x_456_ = v_b_463_;
goto _start;
}
}
default: 
{
lean_object* v_a_466_; uint8_t v___x_467_; 
v_a_466_ = lean_ctor_get(v_x_456_, 0);
lean_inc_ref(v_a_466_);
lean_dec_ref_known(v_x_456_, 1);
v___x_467_ = lp_joshi_Joshi_Pred_eval___redArg(v_00_u03c6_455_, v_a_466_);
if (v___x_467_ == 0)
{
uint8_t v___x_468_; 
v___x_468_ = 1;
return v___x_468_;
}
else
{
uint8_t v___x_469_; 
v___x_469_ = 0;
return v___x_469_;
}
}
}
}
}
LEAN_EXPORT lean_object* lp_joshi_Joshi_Pred_eval___redArg___boxed(lean_object* v_00_u03c6_470_, lean_object* v_x_471_){
_start:
{
uint8_t v_res_472_; lean_object* v_r_473_; 
v_res_472_ = lp_joshi_Joshi_Pred_eval___redArg(v_00_u03c6_470_, v_x_471_);
v_r_473_ = lean_box(v_res_472_);
return v_r_473_;
}
}
LEAN_EXPORT uint8_t lp_joshi_Joshi_Pred_eval(lean_object* v_n_474_, lean_object* v_00_u03c6_475_, lean_object* v_x_476_){
_start:
{
uint8_t v___x_477_; 
v___x_477_ = lp_joshi_Joshi_Pred_eval___redArg(v_00_u03c6_475_, v_x_476_);
return v___x_477_;
}
}
LEAN_EXPORT lean_object* lp_joshi_Joshi_Pred_eval___boxed(lean_object* v_n_478_, lean_object* v_00_u03c6_479_, lean_object* v_x_480_){
_start:
{
uint8_t v_res_481_; lean_object* v_r_482_; 
v_res_481_ = lp_joshi_Joshi_Pred_eval(v_n_478_, v_00_u03c6_479_, v_x_480_);
lean_dec(v_n_478_);
v_r_482_ = lean_box(v_res_481_);
return v_r_482_;
}
}
LEAN_EXPORT lean_object* lp_joshi_Joshi_Pred_depth___redArg(lean_object* v_x_483_){
_start:
{
switch(lean_obj_tag(v_x_483_))
{
case 0:
{
lean_object* v_a_484_; lean_object* v_b_485_; lean_object* v___x_486_; lean_object* v___x_487_; uint8_t v___x_488_; 
v_a_484_ = lean_ctor_get(v_x_483_, 0);
v_b_485_ = lean_ctor_get(v_x_483_, 1);
v___x_486_ = lp_joshi_Joshi_Expr_depth___redArg(v_a_484_);
v___x_487_ = lp_joshi_Joshi_Expr_depth___redArg(v_b_485_);
v___x_488_ = lean_nat_dec_le(v___x_486_, v___x_487_);
if (v___x_488_ == 0)
{
lean_dec(v___x_487_);
return v___x_486_;
}
else
{
lean_dec(v___x_486_);
return v___x_487_;
}
}
case 1:
{
lean_object* v_a_489_; lean_object* v_b_490_; lean_object* v___x_491_; lean_object* v___x_492_; lean_object* v___x_493_; uint8_t v___x_494_; 
v_a_489_ = lean_ctor_get(v_x_483_, 0);
v_b_490_ = lean_ctor_get(v_x_483_, 1);
v___x_491_ = lean_unsigned_to_nat(1u);
v___x_492_ = lp_joshi_Joshi_Pred_depth___redArg(v_a_489_);
v___x_493_ = lp_joshi_Joshi_Pred_depth___redArg(v_b_490_);
v___x_494_ = lean_nat_dec_le(v___x_492_, v___x_493_);
if (v___x_494_ == 0)
{
lean_object* v___x_495_; 
lean_dec(v___x_493_);
v___x_495_ = lean_nat_add(v___x_491_, v___x_492_);
lean_dec(v___x_492_);
return v___x_495_;
}
else
{
lean_object* v___x_496_; 
lean_dec(v___x_492_);
v___x_496_ = lean_nat_add(v___x_491_, v___x_493_);
lean_dec(v___x_493_);
return v___x_496_;
}
}
default: 
{
lean_object* v_a_497_; lean_object* v___x_498_; lean_object* v___x_499_; lean_object* v___x_500_; 
v_a_497_ = lean_ctor_get(v_x_483_, 0);
v___x_498_ = lean_unsigned_to_nat(1u);
v___x_499_ = lp_joshi_Joshi_Pred_depth___redArg(v_a_497_);
v___x_500_ = lean_nat_add(v___x_498_, v___x_499_);
lean_dec(v___x_499_);
return v___x_500_;
}
}
}
}
LEAN_EXPORT lean_object* lp_joshi_Joshi_Pred_depth___redArg___boxed(lean_object* v_x_501_){
_start:
{
lean_object* v_res_502_; 
v_res_502_ = lp_joshi_Joshi_Pred_depth___redArg(v_x_501_);
lean_dec_ref(v_x_501_);
return v_res_502_;
}
}
LEAN_EXPORT lean_object* lp_joshi_Joshi_Pred_depth(lean_object* v_n_503_, lean_object* v_x_504_){
_start:
{
lean_object* v___x_505_; 
v___x_505_ = lp_joshi_Joshi_Pred_depth___redArg(v_x_504_);
return v___x_505_;
}
}
LEAN_EXPORT lean_object* lp_joshi_Joshi_Pred_depth___boxed(lean_object* v_n_506_, lean_object* v_x_507_){
_start:
{
lean_object* v_res_508_; 
v_res_508_ = lp_joshi_Joshi_Pred_depth(v_n_506_, v_x_507_);
lean_dec_ref(v_x_507_);
lean_dec(v_n_506_);
return v_res_508_;
}
}
LEAN_EXPORT lean_object* lp_joshi_Joshi_exprCount(lean_object* v_n_509_, lean_object* v_lits_510_, lean_object* v_x_511_){
_start:
{
lean_object* v_zero_512_; uint8_t v_isZero_513_; 
v_zero_512_ = lean_unsigned_to_nat(0u);
v_isZero_513_ = lean_nat_dec_eq(v_x_511_, v_zero_512_);
if (v_isZero_513_ == 1)
{
lean_object* v___x_514_; 
v___x_514_ = lean_nat_add(v_lits_510_, v_n_509_);
return v___x_514_;
}
else
{
lean_object* v_one_515_; lean_object* v_n_516_; lean_object* v___x_517_; lean_object* v___x_518_; lean_object* v___x_519_; lean_object* v___x_520_; lean_object* v___x_521_; lean_object* v___x_522_; 
v_one_515_ = lean_unsigned_to_nat(1u);
v_n_516_ = lean_nat_sub(v_x_511_, v_one_515_);
v___x_517_ = lean_nat_add(v_lits_510_, v_n_509_);
v___x_518_ = lean_unsigned_to_nat(2u);
v___x_519_ = lp_joshi_Joshi_exprCount(v_n_509_, v_lits_510_, v_n_516_);
lean_dec(v_n_516_);
v___x_520_ = lean_nat_mul(v___x_518_, v___x_519_);
v___x_521_ = lean_nat_mul(v___x_520_, v___x_519_);
lean_dec(v___x_519_);
lean_dec(v___x_520_);
v___x_522_ = lean_nat_add(v___x_517_, v___x_521_);
lean_dec(v___x_521_);
lean_dec(v___x_517_);
return v___x_522_;
}
}
}
LEAN_EXPORT lean_object* lp_joshi_Joshi_exprCount___boxed(lean_object* v_n_523_, lean_object* v_lits_524_, lean_object* v_x_525_){
_start:
{
lean_object* v_res_526_; 
v_res_526_ = lp_joshi_Joshi_exprCount(v_n_523_, v_lits_524_, v_x_525_);
lean_dec(v_x_525_);
lean_dec(v_lits_524_);
lean_dec(v_n_523_);
return v_res_526_;
}
}
LEAN_EXPORT lean_object* lp_joshi_Joshi_predCount(lean_object* v_n_527_, lean_object* v_lits_528_, lean_object* v_x_529_){
_start:
{
lean_object* v_zero_530_; uint8_t v_isZero_531_; 
v_zero_530_ = lean_unsigned_to_nat(0u);
v_isZero_531_ = lean_nat_dec_eq(v_x_529_, v_zero_530_);
if (v_isZero_531_ == 1)
{
lean_object* v___x_532_; lean_object* v___x_533_; 
v___x_532_ = lp_joshi_Joshi_exprCount(v_n_527_, v_lits_528_, v_zero_530_);
v___x_533_ = lean_nat_mul(v___x_532_, v___x_532_);
lean_dec(v___x_532_);
return v___x_533_;
}
else
{
lean_object* v_one_534_; lean_object* v_n_535_; lean_object* v___x_536_; lean_object* v___x_537_; lean_object* v___x_538_; lean_object* v___x_539_; lean_object* v___x_540_; lean_object* v___x_541_; lean_object* v___x_542_; 
v_one_534_ = lean_unsigned_to_nat(1u);
v_n_535_ = lean_nat_sub(v_x_529_, v_one_534_);
v___x_536_ = lean_nat_add(v_n_535_, v_one_534_);
v___x_537_ = lp_joshi_Joshi_exprCount(v_n_527_, v_lits_528_, v___x_536_);
lean_dec(v___x_536_);
v___x_538_ = lean_nat_mul(v___x_537_, v___x_537_);
lean_dec(v___x_537_);
v___x_539_ = lp_joshi_Joshi_predCount(v_n_527_, v_lits_528_, v_n_535_);
lean_dec(v_n_535_);
v___x_540_ = lean_nat_mul(v___x_539_, v___x_539_);
v___x_541_ = lean_nat_add(v___x_538_, v___x_540_);
lean_dec(v___x_540_);
lean_dec(v___x_538_);
v___x_542_ = lean_nat_add(v___x_541_, v___x_539_);
lean_dec(v___x_539_);
lean_dec(v___x_541_);
return v___x_542_;
}
}
}
LEAN_EXPORT lean_object* lp_joshi_Joshi_predCount___boxed(lean_object* v_n_543_, lean_object* v_lits_544_, lean_object* v_x_545_){
_start:
{
lean_object* v_res_546_; 
v_res_546_ = lp_joshi_Joshi_predCount(v_n_543_, v_lits_544_, v_x_545_);
lean_dec(v_x_545_);
lean_dec(v_lits_544_);
lean_dec(v_n_543_);
return v_res_546_;
}
}
LEAN_EXPORT lean_object* lp_joshi___private_Joshi_Dsl_0__Joshi_exprCount_match__1_splitter___redArg(lean_object* v_x_547_, lean_object* v_h__1_548_, lean_object* v_h__2_549_){
_start:
{
lean_object* v_zero_550_; uint8_t v_isZero_551_; 
v_zero_550_ = lean_unsigned_to_nat(0u);
v_isZero_551_ = lean_nat_dec_eq(v_x_547_, v_zero_550_);
if (v_isZero_551_ == 1)
{
lean_object* v___x_552_; lean_object* v___x_553_; 
lean_dec(v_h__2_549_);
v___x_552_ = lean_box(0);
v___x_553_ = lean_apply_1(v_h__1_548_, v___x_552_);
return v___x_553_;
}
else
{
lean_object* v_one_554_; lean_object* v_n_555_; lean_object* v___x_556_; 
lean_dec(v_h__1_548_);
v_one_554_ = lean_unsigned_to_nat(1u);
v_n_555_ = lean_nat_sub(v_x_547_, v_one_554_);
v___x_556_ = lean_apply_1(v_h__2_549_, v_n_555_);
return v___x_556_;
}
}
}
LEAN_EXPORT lean_object* lp_joshi___private_Joshi_Dsl_0__Joshi_exprCount_match__1_splitter___redArg___boxed(lean_object* v_x_557_, lean_object* v_h__1_558_, lean_object* v_h__2_559_){
_start:
{
lean_object* v_res_560_; 
v_res_560_ = lp_joshi___private_Joshi_Dsl_0__Joshi_exprCount_match__1_splitter___redArg(v_x_557_, v_h__1_558_, v_h__2_559_);
lean_dec(v_x_557_);
return v_res_560_;
}
}
LEAN_EXPORT lean_object* lp_joshi___private_Joshi_Dsl_0__Joshi_exprCount_match__1_splitter(lean_object* v_motive_561_, lean_object* v_x_562_, lean_object* v_h__1_563_, lean_object* v_h__2_564_){
_start:
{
lean_object* v_zero_565_; uint8_t v_isZero_566_; 
v_zero_565_ = lean_unsigned_to_nat(0u);
v_isZero_566_ = lean_nat_dec_eq(v_x_562_, v_zero_565_);
if (v_isZero_566_ == 1)
{
lean_object* v___x_567_; lean_object* v___x_568_; 
lean_dec(v_h__2_564_);
v___x_567_ = lean_box(0);
v___x_568_ = lean_apply_1(v_h__1_563_, v___x_567_);
return v___x_568_;
}
else
{
lean_object* v_one_569_; lean_object* v_n_570_; lean_object* v___x_571_; 
lean_dec(v_h__1_563_);
v_one_569_ = lean_unsigned_to_nat(1u);
v_n_570_ = lean_nat_sub(v_x_562_, v_one_569_);
v___x_571_ = lean_apply_1(v_h__2_564_, v_n_570_);
return v___x_571_;
}
}
}
LEAN_EXPORT lean_object* lp_joshi___private_Joshi_Dsl_0__Joshi_exprCount_match__1_splitter___boxed(lean_object* v_motive_572_, lean_object* v_x_573_, lean_object* v_h__1_574_, lean_object* v_h__2_575_){
_start:
{
lean_object* v_res_576_; 
v_res_576_ = lp_joshi___private_Joshi_Dsl_0__Joshi_exprCount_match__1_splitter(v_motive_572_, v_x_573_, v_h__1_574_, v_h__2_575_);
lean_dec(v_x_573_);
return v_res_576_;
}
}
LEAN_EXPORT uint8_t lp_joshi_Joshi_Pred_toStrategy___redArg___lam__0(lean_object* v_features_577_, lean_object* v_p_578_, lean_object* v_t_579_, lean_object* v_v_580_){
_start:
{
lean_object* v___x_581_; uint8_t v___x_582_; 
v___x_581_ = lean_apply_2(v_features_577_, v_t_579_, v_v_580_);
v___x_582_ = lp_joshi_Joshi_Pred_eval___redArg(v___x_581_, v_p_578_);
return v___x_582_;
}
}
LEAN_EXPORT lean_object* lp_joshi_Joshi_Pred_toStrategy___redArg___lam__0___boxed(lean_object* v_features_583_, lean_object* v_p_584_, lean_object* v_t_585_, lean_object* v_v_586_){
_start:
{
uint8_t v_res_587_; lean_object* v_r_588_; 
v_res_587_ = lp_joshi_Joshi_Pred_toStrategy___redArg___lam__0(v_features_583_, v_p_584_, v_t_585_, v_v_586_);
v_r_588_ = lean_box(v_res_587_);
return v_r_588_;
}
}
LEAN_EXPORT lean_object* lp_joshi_Joshi_Pred_toStrategy___redArg(lean_object* v_p_589_, lean_object* v_features_590_){
_start:
{
lean_object* v___f_591_; 
v___f_591_ = lean_alloc_closure((void*)(lp_joshi_Joshi_Pred_toStrategy___redArg___lam__0___boxed), 4, 2);
lean_closure_set(v___f_591_, 0, v_features_590_);
lean_closure_set(v___f_591_, 1, v_p_589_);
return v___f_591_;
}
}
LEAN_EXPORT lean_object* lp_joshi_Joshi_Pred_toStrategy(lean_object* v_n_592_, lean_object* v_p_593_, lean_object* v_features_594_){
_start:
{
lean_object* v___f_595_; 
v___f_595_ = lean_alloc_closure((void*)(lp_joshi_Joshi_Pred_toStrategy___redArg___lam__0___boxed), 4, 2);
lean_closure_set(v___f_595_, 0, v_features_594_);
lean_closure_set(v___f_595_, 1, v_p_593_);
return v___f_595_;
}
}
LEAN_EXPORT lean_object* lp_joshi_Joshi_Pred_toStrategy___boxed(lean_object* v_n_596_, lean_object* v_p_597_, lean_object* v_features_598_){
_start:
{
lean_object* v_res_599_; 
v_res_599_ = lp_joshi_Joshi_Pred_toStrategy(v_n_596_, v_p_597_, v_features_598_);
lean_dec(v_n_596_);
return v_res_599_;
}
}
lean_object* initialize_Init(uint8_t builtin);
lean_object* initialize_Init(uint8_t builtin);
lean_object* initialize_joshi_Joshi_History(uint8_t builtin);
static bool _G_initialized = false;
LEAN_EXPORT lean_object* initialize_joshi_Joshi_Dsl(uint8_t builtin) {
lean_object * res;
if (_G_initialized) return lean_io_result_mk_ok(lean_box(0));
_G_initialized = true;
res = initialize_Init(builtin);
if (lean_io_result_is_error(res)) return res;
lean_dec_ref(res);
res = initialize_Init(builtin);
if (lean_io_result_is_error(res)) return res;
lean_dec_ref(res);
res = initialize_joshi_Joshi_History(builtin);
if (lean_io_result_is_error(res)) return res;
lean_dec_ref(res);
return lean_io_result_mk_ok(lean_box(0));
}
#ifdef __cplusplus
}
#endif
