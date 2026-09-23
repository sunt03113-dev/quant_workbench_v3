import zipfile, collections
z = zipfile.ZipFile(r"D:\09work\quant_workbench_v3\dist\qwb_m4_deploy_20260921.zip")
names = [n for n in z.namelist() if not n.endswith("/")]
tops = collections.Counter(n.split("/")[0] for n in names)
lines = [f"total={len(names)}"]
for k, v in sorted(tops.items()):
    lines.append(f"{k}: {v}")
lines.append("--- golden entries ---")
lines += [n for n in names if n.startswith("golden/")]
lines.append("--- deploy entries ---")
lines += [n for n in names if n.startswith("deploy/")]
open(r"D:\09work\quant_workbench_v3\quant_workbench_package\artifacts\verification\gem10_ruling\pack_manifest.txt", "w", encoding="utf-8").write("\n".join(lines))
print("ok")
