import ast, sqlite3, datetime
src = open('app.py', encoding='utf-8').read()
tree = ast.parse(src)
want_funcs = {"_normalize_unit_label","units_equivalent","convert_weight_qty","get_material_base_unit",
              "set_material_base_unit","get_material_unit_factor","set_material_unit_factor",
              "convert_material_qty_to_base"}
want_assign = {"_WEIGHT_UNIT_TO_KG","DEFAULT_MATERIAL_BASE_UNIT"}
nodes=[]
for n in tree.body:
    if isinstance(n, ast.FunctionDef) and n.name in want_funcs: nodes.append(n)
    elif isinstance(n, ast.Assign) and any(getattr(t,'id',None) in want_assign for t in n.targets): nodes.append(n)
conn = sqlite3.connect(":memory:"); cur = conn.cursor()
cur.executescript("""
CREATE TABLE material_stock_unit(material TEXT PRIMARY KEY, base_unit TEXT, updated_by TEXT, updated_at TEXT);
CREATE TABLE material_unit_factors(material TEXT, unit TEXT, factor_to_base REAL, updated_by TEXT, updated_at TEXT, PRIMARY KEY(material,unit));
""")
ns = {"conn":conn,"cur":cur,"log_audit":lambda *a,**k:None,"_now_iso":lambda:datetime.datetime.now().isoformat()}
# Order matters: exec in source order, but definitions only resolve names at call time
exec(compile(ast.Module(body=nodes, type_ignores=[]), "app_extract", "exec"), ns)
G = ns
results=[]
def check(name, got, exp, tol=1e-9):
    ok = (got is None and exp is None) or (got is not None and exp is not None and abs(got-exp)<=tol)
    results.append((name, got, exp, ok))

check("1 MT -> KG", G["convert_weight_qty"](1,"MT","KG"), 1000)
check("500 KG -> MT", G["convert_weight_qty"](500,"KG","MT"), 0.5)
check("1000 g -> KG", G["convert_weight_qty"](1000,"g","KG"), 1)
check("Bag->KG via weight helper (must be None)", G["convert_weight_qty"](1,"Bag","KG"), None)
check("None qty -> None", G["convert_weight_qty"](None,"KG","MT"), None)

# material "Cement": base KG
G["set_material_base_unit"]("Cement","KG","t")
G["set_material_unit_factor"]("Cement","Bag",50,"t")
check("1 Bag Cement (factor 50) -> factor", G["get_material_unit_factor"]("Cement","Bag"), 50)
check("Bag->KG, no factor on file (Sand) -> None (blocked)", G["get_material_unit_factor"]("Sand","Bag"), None)
q, exact, note = G["convert_material_qty_to_base"]("Sand", 10, "Bag")
results.append(("convert_material_qty_to_base Sand 10 Bag -> is_exact False + note", (q,exact,bool(note)), (10,False,True), (q,exact,bool(note))==(10,False,True)))
# base unit MT
G["set_material_base_unit"]("Filler","MT","t")
check("KG -> MT, base MT (factor)", G["get_material_unit_factor"]("Filler","KG"), 0.001)
q,exact,_ = G["convert_material_qty_to_base"]("Filler", 500, "KG")
check("500 KG Filler -> base MT", q, 0.5)
# receipt KG + consumption MT, base KG
rec,_,_ = G["convert_material_qty_to_base"]("Cement", 5000, "KG")
con,_,_ = G["convert_material_qty_to_base"]("Cement", 1.2, "MT")
check("5000 KG receipt - 1.2 MT consumption (base KG)", rec-con, 3800)
# reservation in different unit: 2 MT reserved vs 4500KG physical
phys,_,_ = G["convert_material_qty_to_base"]("Cement", 4500, "KG")
res,_,_ = G["convert_material_qty_to_base"]("Cement", 2, "MT")
check("Available = 4500 KG - 2 MT reserved", phys-res, 2500)
# casing/plural
check("MT lowercase 'mt'", G["convert_weight_qty"](2,"mt","kg"), 2000)
check("units_equivalent Bag/Bags", float(G["units_equivalent"]("Bag","Bags")), 1.0)
check("units_equivalent KG/MT", float(G["units_equivalent"]("KG","MT")), 0.0)
for n,g,e,ok in results: print(("PASS" if ok else "FAIL"), n, "| got", g, "| expected", e)
print("ALL PASS" if all(r[3] for r in results) else "FAILURES")
