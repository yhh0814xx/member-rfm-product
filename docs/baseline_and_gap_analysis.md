# RFM 产品开发基线与差距分析

> 项目：`D:\Projects\member-rfm-product`  
> 核查日期：2026-07-02  
> 核查方式：只读检查 Git、数据、源码、测试和当前虚拟环境。除本报告外未修改项目文件；未创建分支、未调整远程地址、未提交、未推送。

## 1. 执行摘要

当前仓库已经具备完整的离线 RFM 分析能力：读取仓库自带的清洗后交易 CSV，计算客户级 RFM，进行五分位评分和 10 类规则分层，运行 K-Means、GMM、Hopkins 检验及算法比较，并输出 7 张静态 PNG。

当前仍是“可重复运行的数据分析项目”，不是完整产品。主要差距是：输入适配层缺失、运行结果只存在内存、默认输出覆盖仓库示例图片、没有稳定的依赖锁、没有交互界面/API/数据库，以及文档、清洗代码与实际 CSV 之间存在版本漂移。

## 2. 当前可运行能力

- Python：3.11.9，项目虚拟环境位于 `.venv/`。
- 测试：61/61 通过，失败 0，警告 0。
- 默认入口：`python run_pipeline.py`。
- 默认输入：`data/online_retail_clean.csv`（由仓库中的 ZIP 解压得到，Git 忽略）。
- 默认输出：`visualizations/`。
- 已验证功能：
  - 读取清洗后 CSV；
  - RFM 聚合；
  - R/F/M 五分位评分；
  - 10 类规则型客户分层；
  - K-Means 聚类及 K 值评估；
  - GMM 聚类；
  - log 与 Yeo-Johnson 两种预处理比较；
  - Hopkins 聚类倾向检验；
  - Silhouette、Davies-Bouldin、BIC、AIC 指标；
  - 7 张静态分析图。

默认运行的主要结果：388,724 条交易、4,290 位客户、10 个规则分层；K-Means（K=4、log）Silhouette 0.380、Davies-Bouldin 0.857。

## 3. Git 开发基线

### 3.1 当前身份

- 当前分支：`main`
- HEAD：`838dbcdb0965b20ea5cf75c7e2a84bb2f3569f7b`
- HEAD 说明：`Add bilingual README (EN + DE)`
- HEAD 作者：`Lee Lesemann <lee.lesemann@gmail.com>`
- 当前跟踪关系：`main...origin/main`
- origin（fetch/push）：`https://github.com/leelesemann-sys/rfm-customer-segmentation.git`

当前 `origin` 是原作者仓库。不得向该地址推送。

### 3.2 当前 Git 状态

被修改的已跟踪文件：

```text
M visualizations/1_rfm_segment_overview.png
M visualizations/2_rfm_executive_summary.png
M visualizations/3_rfm_3d_scatter.png
M visualizations/4_rfm_action_cards.png
M visualizations/5_kmeans_elbow_method.png
M visualizations/6_kmeans_final_comparison.png
M visualizations/7_algorithm_comparison.png
```

未跟踪且未忽略的文件：无（本报告创建前）。

被忽略的运行环境/生成文件：

```text
!! .pytest_cache/
!! .venv/
!! data/online_retail_clean.csv
!! src/__pycache__/
!! tests/__pycache__/
```

### 3.3 后续安全远程方案（本阶段不执行）

建议把 `main` 用作原作者基线镜像，把产品开发放在独立分支：

1. 先处理当前 7 张图片的工作区差异，不把重新渲染图片混入开发基线。
2. 将原作者远程改名：`git remote rename origin upstream`。
3. 可选防误推措施：给 `upstream` 设置一个无效 push URL，并只把它用于 fetch。
4. 在自己的 GitHub 账号下创建空仓库后，再执行：`git remote add origin <自己的仓库URL>`。
5. 设置默认推送目标：`git config remote.pushDefault origin`。
6. 首次推送自己的基线：`git push -u origin main`。
7. 后续从原作者同步使用 `git fetch upstream`，审查后再合并或变基，不直接向 upstream 推送。

建议的可选防误推命令如下（仅作为方案，不应在本阶段执行）：

```powershell
git remote rename origin upstream
git remote set-url --push upstream DISABLED
git remote add origin <自己的仓库URL>
git config remote.pushDefault origin
```

### 3.4 本地开发分支方案（本阶段不执行）

建议在工作区恢复到明确基线后创建：

```powershell
git switch -c product-development
```

分支职责建议：

- `main`：尽量保持与上游稳定版本一致；
- `product-development`：输入适配、导出、界面和产品化改造；
- 后续按主题建立短生命周期分支，如 `feature/data-adapter`、`feature/result-export`、`feature/streamlit-app`。

不要在 7 张图片仍处于修改状态时直接创建并提交开发基线，否则这些二进制差异容易被误带入后续提交。

## 4. 运行后图片覆盖问题

`run_pipeline.py` 的默认 `--output-dir` 是 `visualizations/`，而该目录中的 7 张示例图片本身已由上游 Git 跟踪。默认运行会覆盖它们。

比较工作区图片与 HEAD 版本后的结果：

| 图片 | HEAD 大小（字节） | 当前大小（字节） | 像素/尺寸结论 |
|---|---:|---:|---|
| 1_rfm_segment_overview.png | 650,414 | 662,290 | 尺寸由 4763×3595 变为 4756×3597 |
| 2_rfm_executive_summary.png | 670,717 | 638,516 | 尺寸由 4767×3594 变为 4768×3597 |
| 3_rfm_3d_scatter.png | 1,463,273 | 1,414,331 | 尺寸由 4713×3570 变为 4703×3571 |
| 4_rfm_action_cards.png | 911,242 | 864,211 | 尺寸相同，但像素存在轻微差异 |
| 5_kmeans_elbow_method.png | 364,345 | 335,953 | 尺寸由 5372×1483 变为 5366×1485 |
| 6_kmeans_final_comparison.png | 1,168,361 | 1,199,375 | 尺寸由 4769×3567 变为 4762×3568 |
| 7_algorithm_comparison.png | 400,563 | 398,605 | 尺寸由 4770×3600 变为 4767×3597 |

结论：

- 源码、数据和参数没有变化，但 7 个二进制文件全部变化。
- 6 张图片的像素尺寸发生轻微变化；第 4 张尺寸相同但像素值不同。
- 这不仅是 PNG 元数据变化，而是不同 Matplotlib/Pillow/字体渲染环境造成的实际重绘差异。
- 这些结果可以视为“同一逻辑的环境相关重新渲染”，但不应直接提交，否则会产生大体积、低信息量的二进制噪声。

### 4.1 后续输出隔离方案（本阶段不执行）

无需改代码即可使用现有参数：

```powershell
python run_pipeline.py --output-dir outputs/visualizations/
```

产品化阶段建议：

1. 将 `--output-dir` 默认值改为 `outputs/visualizations/`，但仍允许命令行覆盖；
2. 将 `outputs/visualizations/` 加入 `.gitignore`，只在需要发布时选择性纳入成果；
3. 保持上游 `visualizations/` 作为只读示例图库；
4. 为每次运行增加时间戳或 run ID 子目录，避免不同运行相互覆盖；
5. 把图片生成信息写入运行清单，例如参数、数据哈希、Python及依赖版本。

## 5. 393,915 与 388,724 行差异调查

### 5.1 ZIP 内 CSV 的实际情况

文件：`data/online_retail_clean.zip`  
内部条目：`online_retail_clean.csv`

- 文件含表头：是；表头 1 行，9 个字段。
- 数据行数：388,724。
- CSV 物理逻辑行数（含表头）：388,725。
- 字段：`InvoiceNo, StockCode, Description, Quantity, InvoiceDate, UnitPrice, CustomerID, Country, TotalAmount`。
- 唯一订单数：18,018。
- 唯一客户数：4,290。
- 完全重复行：0。
- CustomerID 缺失：0。
- 日期范围：2010-12-01 08:26:00 至 2011-12-09 12:50:00。

### 5.2 `run_pipeline.py` 读取后是否继续过滤

没有交易行过滤。

默认入口在 `run_pipeline.py`：

1. 第 833 行：`pd.read_csv(args.input)`，读取 388,724 行；
2. 第 834 行：将 `InvoiceDate` 转换为日期，不删除行；
3. 第 841 行：`compute_rfm(df)`，按客户聚合成 4,290 行。这是粒度聚合，不是清洗过滤；
4. 后续评分、规则分层、K-Means 和算法比较都基于该客户级表，没有继续删除交易行。

`RFMPipeline.clean_data()` 存在于源码，但默认 `run_pipeline.py` 没有调用它，因为默认输入被假设为已经清洗完成的 CSV。

因此不存在“pipeline 从 393,915 运行时过滤到 388,724”的过程；pipeline 一开始读到的就是 388,724。

### 5.3 实际清洗历史与逐步行数

使用源码中注明的 UCI 官方一年版地址，在内存中读取 `Online Retail.xlsx`，按仓库数据形成逻辑逐字段复算，得到：

| 步骤 | 条件/动作 | 前 | 删除 | 后 |
|---|---|---:|---:|---:|
| 原始数据 | UCI Online Retail 一年版 | — | — | 541,909 |
| 1 | 删除 `CustomerID` 为空 | 541,909 | 135,080 | 406,829 |
| 2 | 删除 `InvoiceNo` 以 `C` 开头 | 406,829 | 8,905 | 397,924 |
| 3 | 保留 `Quantity > 0` 且 `UnitPrice > 0` | 397,924 | 40 | 397,884 |
| 4 | 新增 `TotalAmount = Quantity × UnitPrice` | 397,884 | 0 | 397,884 |
| 5 | 删除交易金额最高 1%：`TotalAmount > P99`，P99=202.5 | 397,884 | 3,969 | **393,915** |
| 6 | 删除完全重复行 | 393,915 | **5,191** | **388,724** |

以上过程得到的 388,724 行，与仓库 CSV 逐字段比较，在统一日期和序列化类型后 9 个字段均为 0 处不一致；唯一订单数和唯一客户数也完全一致。

因此：

- **393,915 是删除交易金额最高 1% 后、删除重复记录前的中间行数。**
- **388,724 才是仓库 ZIP 中当前清洗后 CSV 的最终行数。**
- 两者差 5,191，正是最后一步删除的完全重复记录数。
- `data/README.md` 把 393,915 写成最终行数，是文档错误/旧阶段口径。
- 顶层 README 中的“394k”只是对 393,915 的近似，也没有反映当前 CSV 的最终行数。

### 5.4 文档与代码漂移

存在三处需要后续单独修正的漂移，本阶段不改：

1. `data/README.md` 写“Final: 393,915”，实际最终文件为 388,724；
2. `data/README.md` 写“>£10k transactions”，但复算的实际 99 分位阈值是 `TotalAmount > 202.5`，不是 £10,000；
3. 当前 `RFMPipeline.clean_data()` 和 `01_data_exploration.ipynb` 的源码明确不做异常值过滤。若只按当前 `clean_data()` 处理官方原始文件，会得到 392,692 行，而不能生成仓库中的 388,724 行。说明仓库 CSV 来自包含额外 99 分位过滤的旧版/不同版清洗流程。

`02_rfm_analysis.ipynb` 已明确写明清洗后为 388,724，并说明移除了缺失客户、取消单和异常值，因此它与实际 CSV 更一致。

## 6. 数据来源与性质

当前 CSV 来自 UCI Machine Learning Repository 的 **Online Retail 一年版**，不是 Online Retail II 两年版。

- UCI 数据集 ID：352
- 官方源码中记录的下载地址：`https://archive.ics.uci.edu/static/public/352/online+retail.zip`
- 官方文件：`Online Retail.xlsx`
- 原始范围：2010-12-01 至 2011-12-09
- 原始行数：541,909

当前 CSV 已经历：

- 删除 CustomerID 缺失；
- 删除取消订单；
- 删除非正数量或价格；
- 新增 TotalAmount；
- 删除交易金额最高 1%；
- 删除完全重复行；
- 导出为 CSV 并压缩进仓库。

它不是 UCI 原始文件，不能作为“原始数据层”使用；它是分析就绪的派生数据。

## 7. 源码主要模块与扩展点

### 7.1 读取数据

- 当前读取函数并未独立封装。
- `run_pipeline.main()` 第 833 行直接调用 `pd.read_csv(args.input)`。
- 第 834 行直接转换 `InvoiceDate`。
- `download_dataset()` 只负责从 UCI 下载和解压官方 ZIP，不负责解析 Excel、字段校验或清洗。

### 7.2 数据清洗

- `RFMPipeline.clean_data(df)`：删除缺失客户、取消单、非正数量/价格、重复行，并创建 TotalAmount。
- 默认 `run_pipeline.py` 不调用该方法。
- 当前方法不包含形成仓库 CSV 时实际使用的 99 分位异常值过滤。

### 7.3 RFM 计算

- `RFMPipeline.compute_rfm(df)`：
  - Recency：参考日期减最近购买日期；
  - Frequency：唯一订单数；
  - Monetary：TotalAmount 总和。

### 7.4 RFM 评分和规则分层

- `RFMPipeline.score_rfm(rfm)`：五分位 R/F/M 评分。
- `RFMPipeline._map_segment(row)`：单客户规则映射。
- `RFMPipeline.segment_customers(rfm)`：应用规则并添加 `Segment`。

### 7.5 K-Means

- `RFMPipeline.cluster_kmeans(rfm, ...)`：K-Means 聚类并返回客户表、模型、缩放器和指标。
- `RFMPipeline.find_optimal_k(rfm, ...)`：计算多个 K 的 inertia、Silhouette 和 Davies-Bouldin。
- `RFMPipeline._preprocess_features(...)`：log 或 Yeo-Johnson 预处理。

### 7.6 GMM

- `RFMPipeline.cluster_gmm(rfm, ...)`：单独训练 GMM，返回客户表、模型、变换器和指标。
- `RFMPipeline.compare_algorithms(rfm, ...)`：比较 K-Means/GMM × log/Yeo-Johnson 四种组合；只返回比较 DataFrame，不返回其中训练的模型。

### 7.7 当前仅存在内存中的结果

- 原始读取 DataFrame `df`；
- 客户级 RFM 表 `rfm`；
- R/F/M 分数和规则分层；
- K-Means Cluster、业务标签、模型和 scaler；
- Elbow/K 值评估表 `elbow_df`；
- GMM/K-Means 比较表 `comparison_df`；
- Hopkins 值、聚类评估指标；
- 规则分层摘要和 K-Means 摘要。

当前代码只调用 `savefig` 保存图片，不调用 `to_csv`、`to_excel` 或模型序列化。解压后的清洗 CSV 来自仓库数据包，不是本次 pipeline 新导出的结果。

## 8. 结果导出接入点

建议不要把导出逻辑塞进 `compute_rfm()` 或聚类方法，以保持算法函数易测试、可复用。

更合适的设计：

1. 新增独立导出层，例如 `src/exporters.py` 或 `src/result_writer.py`；
2. 定义统一运行结果对象，保存 `rfm`、`elbow_df`、`comparison_df`、metrics 和模型引用；
3. 在 `run_pipeline.main()` 完成全部计算后调用导出层；
4. 支持：
   - `rfm_customers.csv/xlsx`；
   - `segment_summary.csv/xlsx`；
   - `algorithm_comparison.csv/xlsx`；
   - `run_metadata.json`；
   - 可选的 joblib 模型和预处理器；
5. 输出到独立 run 目录，避免覆盖。

Excel 导出属于展示/交付层；算法层继续返回 DataFrame 和模型即可。

## 9. Streamlit 接入点

现有可直接调用的稳定能力：

- `RFMPipeline.clean_data()`；
- `compute_rfm()`；
- `score_rfm()`；
- `segment_customers()`；
- `find_optimal_k()`；
- `cluster_kmeans()`；
- `cluster_gmm()`；
- `compare_algorithms()`；
- `hopkins_statistic()`。

建议 Streamlit 不通过 shell 调用 `run_pipeline.py`，而是在服务层直接调用这些函数。界面层负责上传、参数和展示；服务层负责数据验证、流程编排和缓存；算法层保持不变。

当前 `run_pipeline.py` 中的画图函数也可直接调用，但它们和文件写入绑定较紧。后续宜提取为 `src/visualization.py`，让函数返回 Figure，再由 CLI 或 Streamlit 决定显示/保存。

建议的 Streamlit 调用链：

```text
上传/选择数据
  -> data adapter + schema validation
  -> clean_data（由用户确认清洗规则）
  -> compute_rfm
  -> score_rfm
  -> segment_customers
  -> cluster_kmeans / cluster_gmm / compare_algorithms
  -> 页面展示 + export service
```

## 10. UCI 官方原始 `Online Retail.xlsx` 适配需求

当前默认入口不适合直接处理官方原始 Excel：

- 只调用 `pd.read_csv`；
- 假定输入已存在 `TotalAmount`；
- 假定 CustomerID 完整、取消单和异常值已经处理；
- 没有输入 schema、工作表、类型、文件哈希或来源验证；
- `requirements.txt` 没有 Excel 引擎（如 openpyxl）。

建议新增独立适配层，而不是修改 RFM 算法：

1. `src/data_loader.py`：按扩展名读取 CSV/XLSX；
2. `src/schema.py`：校验 `InvoiceNo, StockCode, Description, Quantity, InvoiceDate, UnitPrice, CustomerID, Country`；
3. 日期、订单号和客户号类型规范化；
4. 调用 `clean_data()` 生成 TotalAmount 和清洗统计；
5. 将异常值策略显式配置化，并保存审计记录；
6. 对 Online Retail II 两年版另设适配器：读取两个 sheet，并将 `Invoice/Price/Customer ID` 映射到当前字段名；
7. 增加输入数据哈希、来源、行数和处理步骤元数据；
8. 将 Excel 引擎纳入依赖和锁文件。

## 11. 依赖可重复性

### 11.1 当前风险

`requirements.txt` 只有最低版本：

```text
pandas>=2.0
numpy>=1.24
scikit-learn>=1.3
matplotlib>=3.7
seaborn>=0.12
pytest>=7.0
```

没有锁定精确版本，也没有上限。未来重新安装的风险包括：

- Pandas、NumPy 或 scikit-learn 大版本改变 API、默认参数或数值结果；
- Matplotlib/Pillow/字体栈改变 PNG 尺寸和像素，当前7张图的差异已经证明该风险；
- pytest 大版本改变插件和警告行为；
- 间接依赖变化导致相同 requirements 得到不同环境；
- 无法准确复现当前已验证的61项测试和聚类指标；
- Windows、Linux和不同Python版本可能解析到不同二进制包。

### 11.2 建议的 `requirements-lock.txt` 内容（本阶段不创建）

下面是当前已验证 Python 3.11.9 / Windows 环境的完整 `pip freeze`：

```text
colorama==0.4.6
contourpy==1.3.3
cycler==0.12.1
fonttools==4.63.0
iniconfig==2.3.0
joblib==1.5.3
kiwisolver==1.5.0
matplotlib==3.11.0
narwhals==2.23.0
numpy==2.4.6
packaging==26.2
pandas==3.0.3
pillow==12.3.0
pluggy==1.6.0
Pygments==2.20.0
pyparsing==3.3.2
pytest==9.1.1
python-dateutil==2.9.0.post0
scikit-learn==1.9.0
scipy==1.17.1
seaborn==0.13.2
six==1.17.0
threadpoolctl==3.6.0
tzdata==2026.2
```

说明：这是环境快照，不是跨平台的长期最终锁。产品化阶段应将运行依赖和开发/测试依赖拆分，并在支持的 Python/操作系统矩阵上重新生成和验证锁文件。若增加 Excel 输入，还需在评审后把 Excel 引擎加入顶层依赖。

## 12. 下一阶段产品化改造顺序

建议按风险由低到高推进：

1. **建立安全 Git 拓扑**：upstream 指向原作者，origin 指向自己的仓库；保留 main 作为上游基线。
2. **处理当前图片差异**：不提交环境重绘噪声；把生成目录迁移到 `outputs/visualizations/`。
3. **建立 `product-development` 分支**：所有产品改造在该分支进行。
4. **冻结可复现环境**：增加锁文件、Python版本说明和跨平台测试策略。
5. **修正文档/数据血缘**：明确388,724最终行数、99分位阈值202.5、重复去除和数据哈希。
6. **增加输入适配层**：CSV、官方 Online Retail.xlsx、后续 Online Retail II，保持核心算法不变。
7. **增加统一运行结果对象**：避免关键表和模型散落在局部变量。
8. **增加导出层**：CSV、Excel、JSON和可选模型文件，输出到按 run ID 隔离的目录。
9. **拆分可视化模块**：Figure 与文件保存解耦，便于 CLI 和 Streamlit 共用。
10. **再接入 Streamlit**：先做数据上传、参数选择、结果表和图表展示，再做下载。
11. **补产品能力**：日志、错误提示、运行元数据、配置、数据隐私、部署和监控。

## 13. 本阶段未执行事项

- 未创建 `product-development` 或任何其他分支；
- 未修改 origin/upstream；
- 未创建个人远程仓库；
- 未提交或推送；
- 未修改 RFM 算法、规则、测试、数据、图片、README 或 requirements；
- 未创建 `requirements-lock.txt`；
- 未新增 Streamlit 或其他功能。
