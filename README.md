# eijyo_tracker_data

永住 Tracker App 的公开数据托管仓库。App 启动时从 jsDelivr CDN 拉取 `public-data.json`，
三层降级（CDN → 本地缓存 → APK 内置兜底）。**无后端**，每月人工跟 e-Stat 月报更新。

拉取 URL：
```
https://cdn.jsdelivr.net/gh/hongyi-wang0108/eijyo_tracker_data@main/public-data.json
```

## 目录

```
public-data.json          # 成品（App 直接拉取）
scripts/
  estat_to_json.py        # CSV → JSON 转换脚本
  test_estat_to_json.py   # 转换断言（gold standard，每月跑一遍）
raw/
  monthly_2026-03.csv     # e-Stat 月度受理处理（主表，sid=0003449073）
  permits_2024.csv        # e-Stat 年度永住许可数（sid=0003289203）
  annual_processing.csv   # e-Stat 年度受理处理（交叉验证，sid=0003288730）
```

## 每月更新 SOP

1. 到 e-Stat 下载最新 3 个 CSV（Shift-JIS）：
   - 主表 月度受理处理：https://www.e-stat.go.jp/dbview?sid=0003449073
   - 年度永住许可数：https://www.e-stat.go.jp/dbview?sid=0003289203
2. 覆盖 `raw/` 里对应文件（文件名随月份更新，如 `monthly_2026-04.csv`）。
3. 跑转换 + 断言：
   ```bash
   cd scripts
   python3 estat_to_json.py ../raw/monthly_2026-04.csv ../raw/permits_2024.csv --out ../public-data.json
   python3 test_estat_to_json.py   # 必须全绿（gold standard 校验列定位/拆分公式）
   ```
4. 检查 `git diff public-data.json` 数值合理（积压/处理量变化平滑、无列错位）。
5. `git commit -am "data: 更新至 YYYY-MM 月报" && git push`。
6. App 下次启动自动拉到（jsDelivr 缓存延迟 ~12h，无需发版）。

## 关键口径（详见 App 仓库 docs/PREDICTION_AND_DATA.md）

- **永住** = 在留資格审查代码 `60`；项目代码 受理总 `100000`／新受 `103000`／既済总 `300000`。
- **pending** = 受理_総数 − 既済_総数（无单列）。
- ⚠️ **列定位坑**：每个受理处理项目后有个空「補助コード」列，导致数据列偏移。
  東京管内=第17、横浜=第20。转换脚本已处理，靠 gold-standard 断言兜底。
- **双口径**：`monthly` = 纯辖区（东京减成田/羽田/横浜，用于预测+默认展示）；
  `bureauTotal` = 管内合计（e-Stat 原始列，仅对比展示）。
- **calibrationFactor**：FIFO 模型按 积压÷处理量 硬算偏短，乘此系数对齐实际观测。
  东京=1.65（≈700天）；其余局无 ground truth 暂 1.0。在 `estat_to_json.py` 的 `CALIBRATION` dict 调整。

## gold standard（2026-03·永住，每月断言兜底）

| 口径 | 新受 | 既済 | pending |
|------|------|------|---------|
| 纯东京（管内−横浜−成田−羽田） | 4423 | 3155 | 46300 |
| 东京管内（bureauTotal） | 5713 | 3720 | 51707 |
