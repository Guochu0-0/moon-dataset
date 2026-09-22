"""第二步：对齐控制点——读取人工在 ENVI 中标注的 `.pts`/`.txt`，规范化坐标符号约定。

**对齐控制点（alignment tie points）** 标在整幅对齐影像上，每 ROI 约 30 对，
用于解算全局变换、决定 patch 切在何处。它与 patch 旁边的 **评测真值点
（evaluation ground truth）** 是两种东西，本包只管前者。

待实现，见 issue #8。
"""
