import zipfile
z = zipfile.ZipFile(r"D:\09work\quant_workbench_v3\dist\qwb_market_pack_20260921.zip")
names = z.namelist()
out = {"total": len(names),
       "stock": [x for x in names if "stock_names" in x],
       "first3": names[:3]}
import pathlib
pathlib.Path(r"D:\09work\quant_workbench_v3\quant_workbench_package\artifacts\verification\gem10_ruling\oldpack_inspect.json").write_text(
    __import__("json").dumps(out, indent=1), encoding="utf-8")
print("ok")
