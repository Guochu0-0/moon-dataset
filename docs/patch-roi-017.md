# ROI_017 文件补丁

此操作从经光学覆盖核查的 9,862 对冻结成品派生 9,844 对版本。源目录应为该版 `Processed_Data/`，其中 `Train/ROI_017` 的两个模态各有编号 0–212 的 213 个 TIFF。修订版保留其余文件的原路径和内容。成品树通过硬链接共享文件，两个版本都按只读成品使用。

在仓库根目录激活 `moon-dataset` 环境。把下方两个路径替换为源目录与同一文件系统上的新目录。操作在新目录的父目录中准备文件树，完成后再将其放到指定路径。准备文件树时若失败，已创建的 `roi-017-*` 暂存目录会保留供检查，重试时会另建暂存目录。

```bash
python - /path/to/Processed_Data /path/to/Processed_Data-9844 <<'PY'
import os
import runpy
import shutil
import sys
from pathlib import Path
from tempfile import mkdtemp

source, target = (Path(arg).resolve() for arg in sys.argv[1:])
if target.exists() or target.is_relative_to(source):
    raise SystemExit(f"请选择源目录之外的全新路径：{target}")

roi = source / "Train" / "ROI_017"
modalities = {roi / "Optical", roi / "SAR"}
expected = {f"patch_{index}.tif" for index in range(213)}
for directory in sorted(modalities):
    if {path.name for path in directory.glob("patch_*.tif") if path.is_file()} != expected:
        raise SystemExit(f"成品编号与原版 ROI_017 不符：{directory}")

numbers = runpy.run_path("scripts/02_patches.py")["DELETED_NUMBERS"]["ROI_017"]
excluded = {f"patch_{index}.tif" for index in numbers}


def ignore(directory, names):
    return excluded.intersection(names) if Path(directory) in modalities else set()


temporary = Path(mkdtemp(prefix="roi-017-", dir=target.parent))
staged = temporary / target.name
shutil.copytree(source, staged, copy_function=os.link, ignore=ignore)
staged.rename(target)
temporary.rmdir()

print(f"已生成 {target}，ROI_017 排除了 {len(numbers)} 对 patch")
PY
```

修订版的 `Train/ROI_017/Optical` 与 `SAR` 应各有 195 个 TIFF。此时仍是 Git 修订 `0388796` 的划分，训练集有 7,889 对 patch。要得到当前划分，继续执行 [ROI 划分迁移](roi-split-migration.md)。复核剔除前的实验时，使用原版目录及其 7,907 对训练 patch。
